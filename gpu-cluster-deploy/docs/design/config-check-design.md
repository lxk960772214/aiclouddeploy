# 配置项检查机制设计

## 1. 概述

### 1.1 目标
为部署步骤增加统一的配置检查机制，避免重复执行已完成的配置项，提升重复部署效率。

### 1.2 背景
- 当前大多数步骤没有实现统一的配置检查机制
- 基类 `BaseStep` 有 `pre_check()` 和 `post_check()` 方法，但默认返回True
- 部分步骤有自定义检测逻辑（如step_22检测驱动版本）
- 需要设计统一的 `is_configured` 接口

## 2. 接口设计

### 2.1 BaseStep 扩展

```python
class BaseStep(ABC):
    # 新增属性
    skip_if_configured: bool = True  # 如果已配置，是否跳过执行

    def is_configured(self, host: str) -> tuple[bool, str]:
        """
        检查单个主机上的配置是否已完成

        Args:
            host: 主机地址

        Returns:
            tuple[bool, str]: (是否已配置, 检查详情/原因)
        """
        # 默认返回False，强制子类实现具体检查逻辑
        return False, "未实现配置检查"

    def check_all_configured(self, hosts: List[str]) -> Dict[str, tuple[bool, str]]:
        """
        检查所有主机的配置状态

        Args:
            hosts: 主机列表

        Returns:
            Dict[str, tuple[bool, str]]: 每个主机的配置检查结果
        """
        results = {}
        for host in hosts:
            try:
                results[host] = self.is_configured(host)
            except Exception as e:
                results[host] = (False, f"检查异常: {str(e)}")
        return results
```

### 2.2 StepResult 扩展

```python
@dataclass
class StepResult:
    # 新增字段
    skipped_hosts: List[str] = field(default_factory=list)  # 跳过的主机
    skip_reasons: Dict[str, str] = field(default_factory=dict)  # 跳过原因
```

### 2.3 run() 方法修改

```python
def run(self, hosts: List[str]) -> StepResult:
    start_time = time.time()
    self._status = StepStatus.RUNNING

    # 新增：配置检查
    if self.skip_if_configured:
        config_status = self.check_all_configured(hosts)
        all_configured = all(status for status, _ in config_status.values())

        if all_configured:
            self._status = StepStatus.SKIPPED
            return StepResult(
                step_id=self.step_id,
                step_name=self.step_name,
                status=StepStatus.SKIPPED,
                message="所有主机已配置，跳过执行",
                skipped_hosts=hosts,
                skip_reasons={h: reason for h, (_, reason) in config_status.items()}
            )

        # 部分已配置，筛选需要执行的主机
        hosts_to_execute = [h for h, (status, _) in config_status.items() if not status]
        if len(hosts_to_execute) < len(hosts):
            self.logger.info(
                f"[{self.step_id}] {len(hosts) - len(hosts_to_execute)} 台主机已配置，跳过"
            )
    else:
        hosts_to_execute = hosts

    # 原有执行逻辑...
```

## 3. 子类实现示例

### 3.1 依赖安装步骤 (step_1)

```python
class DependenciesStep(BaseStep):
    def is_configured(self, host: str) -> tuple[bool, str]:
        """检查依赖包是否已安装"""
        required_packages = [
            "gcc", "make", "perl", "dkms",
            "libelf-dev", "libssl-dev", "build-essential"
        ]

        # 使用 dpkg 检查包是否安装
        check_cmd = "dpkg -l " + " ".join(required_packages) + " 2>/dev/null | grep -c '^ii'"
        result = self.execute_on_host(host, check_cmd)

        if result["success"] and result["stdout"].strip() == str(len(required_packages)):
            return True, f"所有 {len(required_packages)} 个依赖包已安装"

        # 检查缺失的包
        missing = []
        for pkg in required_packages:
            check = self.execute_on_host(host, f"dpkg -l {pkg} 2>/dev/null | grep -q '^ii'")
            if not check["success"]:
                missing.append(pkg)

        return False, f"缺失依赖包: {', '.join(missing)}"
```

### 3.2 NVIDIA 驱动步骤 (step_22)

```python
class NVIDIADriverStep(BaseStep):
    def is_configured(self, host: str) -> tuple[bool, str]:
        """检查 NVIDIA 驱动是否已安装"""
        # 方法1: nvidia-smi 检测
        result = self.execute_on_host(host, "nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null")
        if result["success"] and result["stdout"].strip():
            version = result["stdout"].strip().split('\n')[0]
            return True, f"NVIDIA 驱动已安装，版本: {version}"

        # 方法2: 内核模块检测
        result = self.execute_on_host(host, "test -f /proc/driver/nvidia/version")
        if result["success"]:
            return True, "NVIDIA 内核模块已加载"

        # 方法3: modinfo 检测
        result = self.execute_on_host(host, "modinfo nvidia 2>/dev/null | grep -q '^version'")
        if result["success"]:
            return True, "NVIDIA 内核模块存在"

        return False, "NVIDIA 驱动未安装"
```

### 3.3 CPU 性能模式步骤 (step_12)

```python
class CPUPerformanceStep(BaseStep):
    def is_configured(self, host: str) -> tuple[bool, str]:
        """检查 CPU 是否已设置为 performance 模式"""
        # 检查 cpufreq 支持
        result = self.execute_on_host(
            host,
            "test -d /sys/devices/system/cpu/cpu0/cpufreq"
        )
        if not result["success"]:
            return True, "系统不支持 cpufreq，无需配置"

        # 检查所有 CPU 核心的 governor
        check_cmd = (
            "cat /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor 2>/dev/null | "
            "sort -u | wc -l"
        )
        result = self.execute_on_host(host, check_cmd)

        if result["success"] and result["stdout"].strip() == "1":
            # 只有一个值，检查是否为 performance
            governor_cmd = "cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor"
            gov_result = self.execute_on_host(host, governor_cmd)
            if gov_result["success"] and "performance" in gov_result["stdout"]:
                return True, "所有 CPU 核心已设置为 performance 模式"

        return False, "CPU 性能模式未正确配置"
```

## 4. 行为规范

### 4.1 检查时机
1. 在 `pre_check` 之后、`execute` 之前执行
2. 检查结果记录到日志和报告

### 4.2 跳过行为
1. **全部跳过**: 所有主机都已配置 → 返回 SKIPPED 状态
2. **部分跳过**: 部分主机已配置 → 只对未配置主机执行
3. **不跳过**: 设置 `skip_if_configured = False` → 强制执行

### 4.3 检查失败处理
- 如果检查过程本身失败（如SSH连接问题），返回 `(False, "检查失败原因")`
- 不阻断部署，按未配置处理

## 5. 向后兼容

1. 默认 `is_configured` 返回 `(False, "未实现配置检查")`
2. 默认 `skip_if_configured = True`
3. 未实现 `is_configured` 的步骤按原逻辑执行

## 6. 实现优先级

| 优先级 | 步骤 | 原因 |
|--------|------|------|
| P0 | step_22_nvidia_driver | 已有检测逻辑，改动最小 |
| P0 | step_1_dependencies | 高频使用，效率提升明显 |
| P1 | step_12_cpu_performance | 配置检查简单 |
| P1 | step_20_mlnx_ofed | 安装耗时长 |
| P2 | 其他步骤 | 按需逐步实现 |
