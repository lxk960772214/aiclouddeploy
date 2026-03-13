# 网络连通性检查模块设计

## 1. 概述

### 1.1 目标
在部署开始前检查所有主机的网络连通性，提前发现网络问题，减少部署失败排查时间。

### 1.2 背景
- 现有 `batch_executor.check_hosts_connectivity()` 仅检查 SSH 连接
- 缺少网络层连通性检查（IP层、DNS、HTTP）
- 需要在部署最开始执行，结果记录到报告

## 2. 检查类型

| 类型 | 命令 | 目的 | 超时 |
|------|------|------|------|
| IP层 | `ping -c 3 -W 5 8.8.8.8` | 检查基础IP连通性 | 15秒 |
| DNS | `ping -c 3 -W 5 www.baidu.com` | 检查DNS解析 | 15秒 |
| HTTP | `curl -s -o /dev/null -w "%{http_code}" --connect-timeout 10 http://www.baidu.com` | 检查HTTP连接 | 10秒 |

## 3. 模块设计

### 3.1 文件结构

```
gpu-cluster-deploy/
├── src/
│   ├── network/
│   │   ├── __init__.py
│   │   └── connectivity_checker.py  # 新增
│   └── steps/
│       └── step_0b_network_check.py  # 新增
```

### 3.2 ConnectivityChecker 类

```python
"""
网络连通性检查模块
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

from src.utils.logger import get_logger


class CheckType(Enum):
    """检查类型"""
    IP = "ip"           # IP层连通性
    DNS = "dns"         # DNS解析
    HTTP = "http"       # HTTP连接


@dataclass
class CheckResult:
    """单项检查结果"""
    check_type: CheckType
    success: bool
    message: str = ""
    latency_ms: float = 0.0
    details: Dict = field(default_factory=dict)


@dataclass
class HostConnectivityResult:
    """单台主机的连通性检查结果"""
    host: str
    ip_check: CheckResult
    dns_check: CheckResult
    http_check: CheckResult

    @property
    def all_passed(self) -> bool:
        return self.ip_check.success and self.dns_check.success and self.http_check.success

    @property
    def partial_passed(self) -> bool:
        return any([
            self.ip_check.success,
            self.dns_check.success,
            self.http_check.success
        ])

    def to_dict(self) -> Dict:
        return {
            "host": self.host,
            "all_passed": self.all_passed,
            "checks": {
                "ip": {
                    "success": self.ip_check.success,
                    "message": self.ip_check.message,
                    "latency_ms": self.ip_check.latency_ms
                },
                "dns": {
                    "success": self.dns_check.success,
                    "message": self.dns_check.message,
                    "latency_ms": self.dns_check.latency_ms
                },
                "http": {
                    "success": self.http_check.success,
                    "message": self.http_check.message,
                    "latency_ms": self.http_check.latency_ms
                }
            }
        }


class ConnectivityChecker:
    """网络连通性检查器"""

    # 默认检查目标
    DEFAULT_IP_TARGET = "8.8.8.8"
    DEFAULT_DNS_TARGET = "www.baidu.com"
    DEFAULT_HTTP_TARGET = "http://www.baidu.com"

    # 超时配置
    PING_COUNT = 3
    PING_TIMEOUT = 5  # 秒
    HTTP_TIMEOUT = 10  # 秒

    def __init__(self, ssh_manager, batch_executor=None, logger=None):
        self.ssh_manager = ssh_manager
        self.batch_executor = batch_executor
        self.logger = logger or get_logger()

    def check_ip_connectivity(self, host: str, username: str, password: str,
                              target: str = None) -> CheckResult:
        """
        检查IP层连通性

        Args:
            host: 目标主机
            username: SSH用户名
            password: SSH密码
            target: ping目标，默认8.8.8.8

        Returns:
            CheckResult: 检查结果
        """
        target = target or self.DEFAULT_IP_TARGET
        cmd = f"ping -c {self.PING_COUNT} -W {self.PING_TIMEOUT} {target} 2>&1"

        result = self.ssh_manager.execute_on_host(
            host, cmd,
            username=username,
            password=password,
            timeout=self.PING_COUNT * self.PING_TIMEOUT + 5
        )

        if result.success and "0% packet loss" in result.stdout:
            # 解析延迟
            latency = self._parse_ping_latency(result.stdout)
            return CheckResult(
                check_type=CheckType.IP,
                success=True,
                message=f"IP层连通正常，延迟 {latency:.1f}ms",
                latency_ms=latency,
                details={"target": target, "output": result.stdout}
            )

        # 解析失败原因
        error_msg = self._parse_ping_error(result.stdout or result.stderr)
        return CheckResult(
            check_type=CheckType.IP,
            success=False,
            message=f"IP层连通失败: {error_msg}",
            details={"target": target, "output": result.stdout, "stderr": result.stderr}
        )

    def check_dns_resolution(self, host: str, username: str, password: str,
                             target: str = None) -> CheckResult:
        """
        检查DNS解析

        Args:
            host: 目标主机
            username: SSH用户名
            password: SSH密码
            target: DNS解析目标，默认www.baidu.com

        Returns:
            CheckResult: 检查结果
        """
        target = target or self.DEFAULT_DNS_TARGET
        cmd = f"ping -c {self.PING_COUNT} -W {self.PING_TIMEOUT} {target} 2>&1"

        result = self.ssh_manager.execute_on_host(
            host, cmd,
            username=username,
            password=password,
            timeout=self.PING_COUNT * self.PING_TIMEOUT + 5
        )

        if result.success and "0% packet loss" in result.stdout:
            latency = self._parse_ping_latency(result.stdout)
            return CheckResult(
                check_type=CheckType.DNS,
                success=True,
                message=f"DNS解析正常，延迟 {latency:.1f}ms",
                latency_ms=latency,
                details={"target": target}
            )

        # 检查是否是DNS解析失败
        if "Name or service not known" in result.stdout or "Temporary failure in name resolution" in result.stdout:
            return CheckResult(
                check_type=CheckType.DNS,
                success=False,
                message="DNS解析失败: 无法解析域名",
                details={"target": target, "error": "dns_resolution_failed"}
            )

        error_msg = self._parse_ping_error(result.stdout or result.stderr)
        return CheckResult(
            check_type=CheckType.DNS,
            success=False,
            message=f"DNS检查失败: {error_msg}",
            details={"target": target, "output": result.stdout}
        )

    def check_http_connection(self, host: str, username: str, password: str,
                              target: str = None) -> CheckResult:
        """
        检查HTTP连接

        Args:
            host: 目标主机
            username: SSH用户名
            password: SSH密码
            target: HTTP目标URL，默认http://www.baidu.com

        Returns:
            CheckResult: 检查结果
        """
        target = target or self.DEFAULT_HTTP_TARGET
        cmd = f"curl -s -o /dev/null -w '%{{http_code}}' --connect-timeout {self.HTTP_TIMEOUT} {target} 2>&1"

        result = self.ssh_manager.execute_on_host(
            host, cmd,
            username=username,
            password=password,
            timeout=self.HTTP_TIMEOUT + 5
        )

        if result.success:
            http_code = result.stdout.strip()
            if http_code.isdigit() and int(http_code) < 500:
                return CheckResult(
                    check_type=CheckType.HTTP,
                    success=True,
                    message=f"HTTP连接正常，状态码: {http_code}",
                    details={"target": target, "http_code": http_code}
                )
            else:
                return CheckResult(
                    check_type=CheckType.HTTP,
                    success=False,
                    message=f"HTTP连接异常，状态码: {http_code}",
                    details={"target": target, "http_code": http_code}
                )

        return CheckResult(
            check_type=CheckType.HTTP,
            success=False,
            message=f"HTTP连接失败: {result.stderr or '未知错误'}",
            details={"target": target, "stderr": result.stderr}
        )

    def check_host(self, host: str, username: str, password: str) -> HostConnectivityResult:
        """
        执行单台主机的所有连通性检查

        Args:
            host: 目标主机
            username: SSH用户名
            password: SSH密码

        Returns:
            HostConnectivityResult: 检查结果
        """
        self.logger.info(f"[ConnectivityCheck] 检查主机: {host}")

        # 并行执行三种检查
        with ThreadPoolExecutor(max_workers=3) as executor:
            future_ip = executor.submit(self.check_ip_connectivity, host, username, password)
            future_dns = executor.submit(self.check_dns_resolution, host, username, password)
            future_http = executor.submit(self.check_http_connection, host, username, password)

            ip_result = future_ip.result()
            dns_result = future_dns.result()
            http_result = future_http.result()

        return HostConnectivityResult(
            host=host,
            ip_check=ip_result,
            dns_check=dns_result,
            http_check=http_result
        )

    def check_all_hosts(self, hosts: List[tuple]) -> Dict[str, HostConnectivityResult]:
        """
        检查所有主机的连通性

        Args:
            hosts: 主机列表，每项为 (host, username, password)

        Returns:
            Dict[str, HostConnectivityResult]: 每个主机的检查结果
        """
        results = {}

        # 使用线程池并行检查多台主机
        with ThreadPoolExecutor(max_workers=min(len(hosts), 10)) as executor:
            futures = {
                executor.submit(self.check_host, host, username, password): host
                for host, username, password in hosts
            }

            for future in as_completed(futures):
                host = futures[future]
                try:
                    results[host] = future.result()
                except Exception as e:
                    self.logger.error(f"[ConnectivityCheck] {host} 检查异常: {e}")
                    # 创建失败结果
                    failed_check = CheckResult(
                        check_type=CheckType.IP,
                        success=False,
                        message=f"检查异常: {str(e)}"
                    )
                    results[host] = HostConnectivityResult(
                        host=host,
                        ip_check=failed_check,
                        dns_check=failed_check,
                        http_check=failed_check
                    )

        return results

    def _parse_ping_latency(self, output: str) -> float:
        """解析ping输出中的延迟"""
        import re
        match = re.search(r'rtt min/avg/max/mdev = [\d.]+/([\d.]+)/', output)
        if match:
            return float(match.group(1))
        return 0.0

    def _parse_ping_error(self, output: str) -> str:
        """解析ping失败原因"""
        if not output:
            return "无输出"

        if "Destination Host Unreachable" in output:
            return "目标主机不可达"
        if "Network is unreachable" in output:
            return "网络不可达"
        if "100% packet loss" in output:
            return "100% 丢包"
        if "Name or service not known" in output:
            return "域名解析失败"

        return "未知错误"
```

### 3.3 网络检查步骤 (step_0b_network_check.py)

```python
"""
步骤0b: 网络连通性检查
"""
from typing import Dict, List

from src.steps.base import BaseStep, StepResult, StepStatus
from src.network.connectivity_checker import ConnectivityChecker


class NetworkCheckStep(BaseStep):
    """网络连通性检查步骤"""

    step_id = "0b"
    step_name = "网络连通性检查"
    step_description = "检查所有主机的IP层、DNS、HTTP连通性"
    requires_sudo = False
    can_skip = False
    skip_if_configured = False  # 网络检查每次都执行

    def __init__(self, config, ssh_manager, batch_executor, logger=None, versions=None):
        super().__init__(config, ssh_manager, batch_executor, logger, versions)
        self.checker = ConnectivityChecker(ssh_manager, batch_executor, logger)

    def execute(self, hosts: List[str]) -> StepResult:
        """执行网络连通性检查"""
        self.logger.info(f"[{self.step_id}] 开始网络连通性检查...")

        # 准备主机认证信息
        host_auth_list = []
        for host in hosts:
            node_config = self._get_node_config(host)
            if node_config:
                username = getattr(node_config, 'username', None)
                password = getattr(node_config, 'password', None)
            else:
                username = None
                password = None

            # 使用默认认证
            if not username and self.config.jumphost and self.config.jumphost.node_auth:
                username = self.config.jumphost.node_auth.username
                password = self.config.jumphost.node_auth.password
            if not username:
                username = "ubuntu"

            host_auth_list.append((host, username, password))

        # 执行检查
        results = self.checker.check_all_hosts(host_auth_list)

        # 统计结果
        all_passed = sum(1 for r in results.values() if r.all_passed)
        partial_passed = sum(1 for r in results.values() if r.partial_passed and not r.all_passed)
        failed = len(hosts) - all_passed - partial_passed

        # 生成报告
        report = self._generate_report(results)

        # 记录到文件
        self._save_report(report)

        # 结果消息
        message = f"网络检查完成: {all_passed} 全部通过, {partial_passed} 部分通过, {failed} 失败"

        return StepResult(
            step_id=self.step_id,
            step_name=self.step_name,
            status=StepStatus.SUCCESS,  # 网络检查不阻断部署
            message=message,
            details={
                "all_passed_count": all_passed,
                "partial_passed_count": partial_passed,
                "failed_count": failed,
                "results": {h: r.to_dict() for h, r in results.items()}
            },
            warnings=[f"{h}: {self._get_warning(r)}" for h, r in results.items() if not r.all_passed]
        )

    def _generate_report(self, results: Dict) -> str:
        """生成网络检查报告"""
        lines = [
            "# 网络连通性检查报告",
            "",
            "## 检查结果汇总",
            "",
            "| 主机 | IP层 | DNS | HTTP | 状态 |",
            "|------|------|-----|------|------|",
        ]

        for host, result in results.items():
            ip_status = "✓" if result.ip_check.success else "✗"
            dns_status = "✓" if result.dns_check.success else "✗"
            http_status = "✓" if result.http_check.success else "✗"
            overall = "全部通过" if result.all_passed else ("部分通过" if result.partial_passed else "失败")

            lines.append(f"| {host} | {ip_status} | {dns_status} | {http_status} | {overall} |")

        # 添加详细信息
        lines.extend([
            "",
            "## 详细信息",
            ""
        ])

        for host, result in results.items():
            if not result.all_passed:
                lines.append(f"### {host}")
                if not result.ip_check.success:
                    lines.append(f"- **IP层**: {result.ip_check.message}")
                if not result.dns_check.success:
                    lines.append(f"- **DNS**: {result.dns_check.message}")
                if not result.http_check.success:
                    lines.append(f"- **HTTP**: {result.http_check.message}")
                lines.append("")

        return "\n".join(lines)

    def _save_report(self, report: str):
        """保存报告到文件"""
        import os
        from datetime import datetime

        report_dir = "reports"
        os.makedirs(report_dir, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = os.path.join(report_dir, f"network_check_{timestamp}.md")

        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report)

        self.logger.info(f"[{self.step_id}] 报告已保存: {report_path}")

    def _get_warning(self, result) -> str:
        """生成警告消息"""
        issues = []
        if not result.ip_check.success:
            issues.append(f"IP层({result.ip_check.message})")
        if not result.dns_check.success:
            issues.append(f"DNS({result.dns_check.message})")
        if not result.http_check.success:
            issues.append(f"HTTP({result.http_check.message})")
        return "; ".join(issues)
```

## 4. 执行流程

```
Phase 0: 设备检查 (step_0)
    ↓
Phase 0b: 网络连通性检查 (step_0b) [新增]
    ↓
Phase 1-26: 各配置步骤
    ↓
生成最终报告 (包含网络检查结果)
```

## 5. 配置选项

在 `config.yaml` 中可选配置:

```yaml
network_check:
  enabled: true
  ip_target: "8.8.8.8"
  dns_target: "www.baidu.com"
  http_target: "http://www.baidu.com"
  timeout:
    ping: 15
    http: 10
  fail_action: "warn"  # warn | continue | abort
```

## 6. 不阻断部署的设计理由

1. **环境差异**: 某些环境可能限制外网访问
2. **部署目的**: 可能是离线部署
3. **用户决策**: 让用户根据报告决定是否继续

## 7. 实现计划

1. 创建 `src/network/connectivity_checker.py`
2. 创建 `src/steps/step_0b_network_check.py`
3. 更新 `src/steps/__init__.py` 注册新步骤
4. 更新 `src/main.py` 在 Phase 0 后执行
