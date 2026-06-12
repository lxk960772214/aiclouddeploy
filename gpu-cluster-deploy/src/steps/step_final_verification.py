"""
步骤99: 最终验证
部署完成后检查所有步骤的配置状态，生成完整的配置报告
"""

from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import json

from src.steps.base import BaseStep, StepResult, StepStatus


class CheckStatus(Enum):
    """检查状态"""
    PASS = "pass"           # 通过
    FAIL = "fail"           # 失败
    WARNING = "warning"     # 警告
    SKIP = "skip"           # 跳过
    UNKNOWN = "unknown"     # 未知


@dataclass
class CheckItem:
    """检查项"""
    name: str                           # 检查项名称
    status: CheckStatus                 # 检查状态
    message: str = ""                   # 检查消息
    details: Dict[str, Any] = field(default_factory=dict)  # 详细信息
    host_results: Dict[str, CheckStatus] = field(default_factory=dict)  # 按主机的结果

    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "status": self.status.value,
            "message": self.message,
            "details": self.details,
            "host_results": {k: v.value for k, v in self.host_results.items()}
        }


@dataclass
class VerificationReport:
    """验证报告"""
    cluster_name: str
    check_time: str
    total_checks: int = 0
    passed: int = 0
    failed: int = 0
    warnings: int = 0
    skipped: int = 0
    checks: List[CheckItem] = field(default_factory=list)
    network_status: Dict[str, Any] = field(default_factory=dict)
    device_status: Dict[str, Any] = field(default_factory=dict)
    summary: str = ""

    def to_dict(self) -> Dict:
        return {
            "cluster_name": self.cluster_name,
            "check_time": self.check_time,
            "total_checks": self.total_checks,
            "passed": self.passed,
            "failed": self.failed,
            "warnings": self.warnings,
            "skipped": self.skipped,
            "checks": [c.to_dict() for c in self.checks],
            "network_status": self.network_status,
            "device_status": self.device_status,
            "summary": self.summary
        }


class FinalVerification(BaseStep):
    """最终验证步骤"""

    step_id = "99"
    step_name = "最终验证"
    step_description = "部署完成后验证所有配置项状态"
    requires_sudo = False
    supports_batch = False
    skip_if_configured = False  # 每次都执行
    timeout = 600

    def __init__(self, config, ssh_manager, batch_executor, logger=None, versions=None,
                 step_registry: Optional[Dict] = None):
        """
        初始化验证步骤

        Args:
            config: 集群配置
            ssh_manager: SSH管理器
            batch_executor: 批量执行器
            logger: 日志记录器
            versions: 版本配置
            step_registry: 步骤注册表（包含所有已注册的步骤实例）
        """
        super().__init__(config, ssh_manager, batch_executor, logger, versions)
        self.step_registry = step_registry or {}

    def execute(self, hosts: List[str]) -> StepResult:
        """执行最终验证"""
        self.logger.info("=" * 60)
        self.logger.info("开始最终验证...")
        self.logger.info("=" * 60)

        report = VerificationReport(
            cluster_name=self.config.name if self.config else "unknown",
            check_time=datetime.now().isoformat()
        )

        # 1. 检查网络状态
        self.logger.info("\n[1/4] 检查网络连通性...")
        report.network_status = self._check_network_status(hosts)
        self.logger.info(f"    网络状态: {report.network_status.get('summary', 'unknown')}")

        # 2. 检查设备状态
        self.logger.info("\n[2/4] 检查设备状态...")
        report.device_status = self._check_device_status(hosts)
        self.logger.info(f"    设备状态: {report.device_status.get('summary', 'unknown')}")

        # 3. 检查所有步骤配置状态
        self.logger.info("\n[3/4] 检查部署步骤配置状态...")
        self._check_all_steps(hosts, report)

        # 4. 运行健康检查
        self.logger.info("\n[4/4] 运行健康检查...")
        self._run_health_checks(hosts, report)

        # 生成汇总
        report.total_checks = len(report.checks)
        report.passed = sum(1 for c in report.checks if c.status == CheckStatus.PASS)
        report.failed = sum(1 for c in report.checks if c.status == CheckStatus.FAIL)
        report.warnings = sum(1 for c in report.checks if c.status == CheckStatus.WARNING)
        report.skipped = sum(1 for c in report.checks if c.status == CheckStatus.SKIP)

        # 生成汇总消息
        if report.failed == 0 and report.warnings == 0:
            report.summary = f"验证通过: {report.passed}/{report.total_checks} 项检查通过"
        elif report.failed == 0:
            report.summary = f"验证完成(有警告): {report.passed} 通过, {report.warnings} 警告"
        else:
            report.summary = f"验证失败: {report.passed} 通过, {report.failed} 失败, {report.warnings} 警告"

        # 打印报告摘要
        self._print_report_summary(report)

        # 生成HTML报告
        self._generate_html_report(report)

        # 判断整体状态
        success = report.failed == 0

        return StepResult(
            step_id=self.step_id,
            step_name=self.step_name,
            status=StepStatus.SUCCESS if success else StepStatus.FAILED,
            message=report.summary,
            details=report.to_dict(),
            warnings=[c.message for c in report.checks if c.status == CheckStatus.WARNING]
        )

    def _check_network_status(self, hosts: List[str]) -> Dict[str, Any]:
        """检查网络状态"""
        result = {
            "connectivity": {},
            "dns": {},
            "summary": "unknown"
        }

        # 检查节点间连通性
        reachable = 0
        for host in hosts:
            ping_result = self.execute_on_host(
                host,
                "ping -c 1 -W 2 8.8.8.8 > /dev/null 2>&1 && echo 'ok' || echo 'fail'",
                sudo=False
            )
            is_reachable = ping_result.get("stdout", "").strip() == "ok"
            result["connectivity"][host] = is_reachable
            if is_reachable:
                reachable += 1

        # DNS检查
        for host in hosts:
            dns_result = self.execute_on_host(
                host,
                "nslookup github.com > /dev/null 2>&1 && echo 'ok' || echo 'fail'",
                sudo=False
            )
            result["dns"][host] = dns_result.get("stdout", "").strip() == "ok"

        # 汇总
        if reachable == len(hosts):
            result["summary"] = "all_reachable"
        elif reachable > 0:
            result["summary"] = f"partial({reachable}/{len(hosts)})"
        else:
            result["summary"] = "unreachable"

        return result

    def _check_device_status(self, hosts: List[str]) -> Dict[str, Any]:
        """检查设备状态"""
        result = {
            "gpu": {},
            "rdma": {},
            "ethernet": {},
            "summary": "unknown"
        }

        all_gpu_ok = True
        all_rdma_ok = True

        for host in hosts:
            # GPU检查
            gpu_result = self.execute_on_host(
                host,
                "nvidia-smi -L 2>/dev/null | wc -l",
                sudo=False
            )
            gpu_count = 0
            try:
                gpu_count = int(gpu_result.get("stdout", "0").strip())
            except ValueError:
                pass
            result["gpu"][host] = {"count": gpu_count, "ok": gpu_count > 0}
            if gpu_count == 0:
                all_gpu_ok = False

            # RDMA检查
            rdma_result = self.execute_on_host(
                host,
                "ibdev2netdev 2>/dev/null | grep -v down | wc -l",
                sudo=False
            )
            rdma_up = 0
            try:
                rdma_up = int(rdma_result.get("stdout", "0").strip())
            except ValueError:
                pass
            result["rdma"][host] = {"up_count": rdma_up}
            # RDMA可能没有，不算错误

            # 以太网检查
            eth_result = self.execute_on_host(
                host,
                "ip link show up 2>/dev/null | grep -E '^[0-9]+:' | wc -l",
                sudo=False
            )
            eth_count = 0
            try:
                eth_count = int(eth_result.get("stdout", "0").strip())
            except ValueError:
                pass
            result["ethernet"][host] = {"up_count": eth_count}

        # 汇总
        if all_gpu_ok:
            result["summary"] = "all_ok"
        else:
            result["summary"] = "gpu_issues"

        return result

    def _check_all_steps(self, hosts: List[str], report: VerificationReport):
        """检查所有步骤的配置状态"""
        # 步骤ID到名称的映射
        step_names = {
            "00": "设备一致性检查",
            "0b": "网络连通性检查",
            "01": "依赖软件包",
            "02": "内核版本检查",
            "03": "glibc版本检查",
            "04": "OpenSSH版本检查",
            "05": "sudo免密",
            "06": "数据盘挂载",
            "07": "MSR设置",
            "08": "rc.local配置",
            "09": "主机名和hosts",
            "10": "ubuntu用户",
            "11": "SSH免密登录",
            "12": "CPU性能模式",
            "13": "文件描述符",
            "15": "禁用自动更新",
            "16": "固定内核版本",
            "17": "时区设置",
            "18": "禁用IPv6",
            "19": "vmcore和休眠",
            "20": "Mellanox驱动",
            "21": "禁用nouveau",
            "22": "NVIDIA驱动",
            "23": "FabricManager",
            "24": "CUDA Toolkit",
            "25": "NCCL",
            "26": "RDMA网卡重命名",
            "26b": "以太网重命名",
            "27": "GPU持久模式",
            "28": "NVIDIA内核模块",
            "29": "禁用ACS",
            "30": "时间同步",
            "34": "NFS配置",
        }

        # 检查每个步骤
        for step_id, step_name in step_names.items():
            check_item = self._check_step_config(step_id, step_name, hosts)
            report.checks.append(check_item)

            # 状态统计
            status_str = {
                CheckStatus.PASS: "✓",
                CheckStatus.FAIL: "✗",
                CheckStatus.WARNING: "⚠",
                CheckStatus.SKIP: "○"
            }.get(check_item.status, "?")

            self.logger.info(f"    [{status_str}] {step_id} {step_name}: {check_item.message}")

    def _check_step_config(self, step_id: str, step_name: str, hosts: List[str]) -> CheckItem:
        """检查单个步骤的配置状态"""
        check_item = CheckItem(name=f"step_{step_id}: {step_name}", status=CheckStatus.UNKNOWN)

        # 尝试从注册表获取步骤实例
        step_instance = self.step_registry.get(step_id)

        if step_instance and hasattr(step_instance, 'is_configured'):
            # 使用步骤自己的检查方法
            host_results = {}
            all_configured = True
            some_configured = False

            for host in hosts:
                try:
                    configured, reason = step_instance.is_configured(host)
                    host_results[host] = CheckStatus.PASS if configured else CheckStatus.FAIL
                    check_item.host_results[host] = host_results[host]

                    if configured:
                        some_configured = True
                    else:
                        all_configured = False
                        check_item.details[host] = reason
                except Exception as e:
                    host_results[host] = CheckStatus.UNKNOWN
                    check_item.host_results[host] = CheckStatus.UNKNOWN
                    check_item.details[host] = str(e)
                    all_configured = False

            if all_configured:
                check_item.status = CheckStatus.PASS
                check_item.message = "所有节点已配置"
            elif some_configured:
                check_item.status = CheckStatus.WARNING
                check_item.message = f"部分节点未配置"
            else:
                check_item.status = CheckStatus.FAIL
                check_item.message = "未配置"
        else:
            # 使用内置检查方法
            check_item = self._builtin_check(step_id, step_name, hosts)

        return check_item

    def _builtin_check(self, step_id: str, step_name: str, hosts: List[str]) -> CheckItem:
        """内置检查方法（当步骤没有注册时的备用方案）"""
        check_item = CheckItem(name=f"step_{step_id}: {step_name}", status=CheckStatus.UNKNOWN)

        # 根据步骤ID定义检查命令
        check_commands = {
            "05": "sudo -n true 2>/dev/null && echo 'ok' || echo 'fail'",  # sudo免密
            "06": "mountpoint -q /ssd 2>/dev/null && echo 'ok' || echo 'fail'",  # 数据盘
            "09": f"grep -q $(hostname) /etc/hosts && echo 'ok' || echo 'fail'",  # hosts
            "11": "test -s ~/.ssh/authorized_keys && test -f ~/.ssh/id_rsa && echo 'configured' || echo 'not_configured'",  # SSH免密
            "12": "cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor 2>/dev/null || echo 'unknown'",  # CPU模式
            "13": "ulimit -n",  # 文件描述符
            "16": "grep 'GRUB_DEFAULT' /etc/default/grub | grep -q 'Advanced options' && echo 'locked' || echo 'not_locked'",  # 内核锁定
            "17": "timedatectl | grep 'Time zone' | awk '{print $3}'",  # 时区
            "18": "cat /proc/sys/net/ipv6/conf/all/disable_ipv6",  # IPv6
            "21": "lsmod | grep -c nouveau 2>/dev/null || true",  # nouveau (grep -c输出0但exit=1时||true防止重复)
            "22": "nvidia-smi -L 2>/dev/null | wc -l || echo 0",  # NVIDIA驱动
            "24": "nvcc --version 2>/dev/null | tail -1 || echo 'not_installed'",  # CUDA
            "27": "nvidia-smi -q 2>/dev/null | grep -c 'Persistence Mode.*Enabled' || true",  # GPU持久模式
        }

        if step_id not in check_commands:
            check_item.status = CheckStatus.SKIP
            check_item.message = "跳过检查（无检查方法）"
            return check_item

        cmd = check_commands[step_id]
        all_ok = True
        some_ok = False

        for host in hosts:
            result = self.execute_on_host(host, cmd, sudo=False)
            output = result.get("stdout", "").strip()

            # 根据步骤ID判断结果
            if step_id == "05":
                ok = output == "ok"
            elif step_id == "06":
                ok = output == "ok"
            elif step_id == "09":
                ok = output == "ok"
            elif step_id == "11":
                # SSH免密登录检查
                ok = output == "configured"
            elif step_id == "12":
                ok = output == "performance"
            elif step_id == "13":
                try:
                    ok = int(output) > 1024
                except ValueError:
                    ok = False
            elif step_id == "16":
                # 内核锁定检查
                ok = output == "locked"
            elif step_id == "17":
                ok = "Asia/Shanghai" in output
            elif step_id == "18":
                ok = output == "1"
            elif step_id == "21":
                try:
                    # 取第一行避免重复输出问题
                    first_line = output.split('\n')[0].strip() if output else "0"
                    ok = int(first_line) == 0  # nouveau应该被禁用
                except ValueError:
                    ok = False
            elif step_id == "22":
                try:
                    ok = int(output) > 0
                except ValueError:
                    ok = False
            elif step_id == "24":
                ok = "not_installed" not in output
            elif step_id == "27":
                try:
                    # 取第一行避免重复输出问题
                    first_line = output.split('\n')[0].strip() if output else "0"
                    ok = int(first_line) > 0
                except ValueError:
                    ok = False
            else:
                ok = False

            check_item.host_results[host] = CheckStatus.PASS if ok else CheckStatus.FAIL
            check_item.details[host] = output

            if ok:
                some_ok = True
            else:
                all_ok = False

        if all_ok:
            check_item.status = CheckStatus.PASS
            check_item.message = "所有节点已配置"
        elif some_ok:
            check_item.status = CheckStatus.WARNING
            check_item.message = "部分节点未配置"
        else:
            check_item.status = CheckStatus.FAIL
            check_item.message = "未配置"

        return check_item

    def _run_health_checks(self, hosts: List[str], report: VerificationReport):
        """运行健康检查（参考health-check-v2.sh）"""
        health_checks = [
            ("GPU持久模式", self._check_gpu_persistence),
            ("GPU ECC错误", self._check_gpu_ecc),
            ("GPU温度", self._check_gpu_temperature),
            ("GPU功率", self._check_gpu_power),
            ("RDMA链路状态", self._check_rdma_status),
            ("FabricManager服务", self._check_fabricmanager),
            ("ACS状态", self._check_acs_status),
            ("nvidia_peermem模块", self._check_peermem_module),
            ("时间同步", self._check_time_sync),
        ]

        for name, check_func in health_checks:
            try:
                check_item = check_func(hosts)
                report.checks.append(check_item)

                status_str = {
                    CheckStatus.PASS: "✓",
                    CheckStatus.FAIL: "✗",
                    CheckStatus.WARNING: "⚠",
                    CheckStatus.SKIP: "○"
                }.get(check_item.status, "?")

                self.logger.info(f"    [{status_str}] {name}: {check_item.message}")
            except Exception as e:
                check_item = CheckItem(
                    name=name,
                    status=CheckStatus.UNKNOWN,
                    message=f"检查异常: {str(e)}"
                )
                report.checks.append(check_item)
                self.logger.warning(f"    [?] {name}: 检查异常 - {str(e)}")

    def _check_gpu_persistence(self, hosts: List[str]) -> CheckItem:
        """检查GPU持久模式"""
        check_item = CheckItem(name="GPU持久模式", status=CheckStatus.UNKNOWN)

        for host in hosts:
            result = self.execute_on_host(
                host,
                "nvidia-smi -q 2>/dev/null | grep -c 'Persistence Mode.*Enabled' || true",
                sudo=False
            )
            try:
                stdout = result.get("stdout", "0").strip()
                # 取第一行避免重复输出问题
                first_line = stdout.split('\n')[0].strip() if stdout else "0"
                count = int(first_line) if first_line.isdigit() else 0
                check_item.host_results[host] = CheckStatus.PASS if count > 0 else CheckStatus.FAIL
                check_item.details[host] = f"{count} GPUs in persistence mode"
            except ValueError:
                check_item.host_results[host] = CheckStatus.UNKNOWN
                check_item.details[host] = "无法获取"

        self._summarize_check(check_item, hosts)
        return check_item

    def _check_gpu_ecc(self, hosts: List[str]) -> CheckItem:
        """检查GPU ECC错误"""
        check_item = CheckItem(name="GPU ECC错误", status=CheckStatus.UNKNOWN)

        for host in hosts:
            result = self.execute_on_host(
                host,
                "nvidia-smi --query-gpu=index,ecc.errors.uncorrected.volatile.total --format=csv,noheader,nounits 2>/dev/null || echo 'error'",
                sudo=False
            )
            output = result.get("stdout", "").strip()
            if output == "error" or not output:
                check_item.host_results[host] = CheckStatus.UNKNOWN
                check_item.details[host] = "无法获取"
            else:
                has_error = False
                for line in output.split('\n'):
                    try:
                        parts = line.strip().split(',')
                        if len(parts) >= 2:
                            ecc_count = int(parts[1].strip())
                            if ecc_count > 0:
                                has_error = True
                                check_item.details[host] = f"GPU {parts[0]}: {ecc_count} ECC errors"
                                break
                    except (ValueError, IndexError):
                        pass

                if has_error:
                    check_item.host_results[host] = CheckStatus.FAIL
                else:
                    check_item.host_results[host] = CheckStatus.PASS
                    check_item.details[host] = "无ECC错误"

        self._summarize_check(check_item, hosts)
        return check_item

    def _check_gpu_temperature(self, hosts: List[str]) -> CheckItem:
        """检查GPU温度"""
        check_item = CheckItem(name="GPU温度", status=CheckStatus.UNKNOWN)
        threshold = 80  # 温度阈值

        for host in hosts:
            result = self.execute_on_host(
                host,
                f"nvidia-smi --query-gpu=index,temperature.gpu --format=csv,noheader,nounits 2>/dev/null || echo 'error'",
                sudo=False
            )
            output = result.get("stdout", "").strip()
            if output == "error" or not output:
                check_item.host_results[host] = CheckStatus.UNKNOWN
                check_item.details[host] = "无法获取"
            else:
                over_temp = False
                max_temp = 0
                for line in output.split('\n'):
                    try:
                        parts = line.strip().split(',')
                        if len(parts) >= 2:
                            temp = int(parts[1].strip())
                            max_temp = max(max_temp, temp)
                            if temp > threshold:
                                over_temp = True
                    except (ValueError, IndexError):
                        pass

                if over_temp:
                    check_item.host_results[host] = CheckStatus.WARNING
                    check_item.details[host] = f"最高温度 {max_temp}°C"
                else:
                    check_item.host_results[host] = CheckStatus.PASS
                    check_item.details[host] = f"最高温度 {max_temp}°C"

        self._summarize_check(check_item, hosts)
        return check_item

    def _check_gpu_power(self, hosts: List[str]) -> CheckItem:
        """检查GPU功率状态"""
        check_item = CheckItem(name="GPU功率", status=CheckStatus.UNKNOWN)

        for host in hosts:
            result = self.execute_on_host(
                host,
                "nvidia-smi 2>/dev/null | grep -c 'ERR!' || true",
                sudo=False
            )
            try:
                stdout = result.get("stdout", "0").strip()
                # 取第一行避免重复输出问题
                first_line = stdout.split('\n')[0].strip() if stdout else "0"
                err_count = int(first_line) if first_line.isdigit() else 0
                if err_count > 0:
                    check_item.host_results[host] = CheckStatus.FAIL
                    check_item.details[host] = f"{err_count} GPU功率异常"
                else:
                    check_item.host_results[host] = CheckStatus.PASS
                    check_item.details[host] = "正常"
            except ValueError:
                check_item.host_results[host] = CheckStatus.UNKNOWN
                check_item.details[host] = "无法获取"

        self._summarize_check(check_item, hosts)
        return check_item

    def _check_rdma_status(self, hosts: List[str]) -> CheckItem:
        """检查RDMA链路状态"""
        check_item = CheckItem(name="RDMA链路状态", status=CheckStatus.UNKNOWN)

        for host in hosts:
            result = self.execute_on_host(
                host,
                "ibdev2netdev 2>/dev/null | grep -c -v down || true",
                sudo=False
            )
            try:
                stdout = result.get("stdout", "0").strip()
                # 取第一行避免重复输出问题
                first_line = stdout.split('\n')[0].strip() if stdout else "0"
                up_count = int(first_line) if first_line.isdigit() else 0
                # 检查是否有down的接口
                result_down = self.execute_on_host(
                    host,
                    "ibdev2netdev 2>/dev/null | grep -i down | wc -l || true",
                    sudo=False
                )
                stdout_down = result_down.get("stdout", "0").strip()
                first_line_down = stdout_down.split('\n')[0].strip() if stdout_down else "0"
                down_count = int(first_line_down) if first_line_down.isdigit() else 0

                if up_count == 0 and down_count == 0:
                    # 检查是否有任何IB设备
                    result_any = self.execute_on_host(
                        host,
                        "ibdev2netdev 2>/dev/null | wc -l || true",
                        sudo=False
                    )
                    stdout_any = result_any.get("stdout", "0").strip()
                    first_line_any = stdout_any.split('\n')[0].strip() if stdout_any else "0"
                    total_count = int(first_line_any) if first_line_any.isdigit() else 0
                    if total_count == 0:
                        check_item.host_results[host] = CheckStatus.SKIP
                        check_item.details[host] = "无IB设备"
                    else:
                        check_item.host_results[host] = CheckStatus.WARNING
                        check_item.details[host] = "IB设备存在但状态未知"
                elif down_count > 0:
                    check_item.host_results[host] = CheckStatus.WARNING
                    check_item.details[host] = f"{up_count} up, {down_count} down"
                else:
                    check_item.host_results[host] = CheckStatus.PASS
                    check_item.details[host] = f"{up_count} 接口正常"
            except ValueError:
                check_item.host_results[host] = CheckStatus.UNKNOWN
                check_item.details[host] = "无法获取"

        self._summarize_check(check_item, hosts)
        return check_item

    def _check_fabricmanager(self, hosts: List[str]) -> CheckItem:
        """检查FabricManager服务"""
        check_item = CheckItem(name="FabricManager服务", status=CheckStatus.UNKNOWN)

        for host in hosts:
            result = self.execute_on_host(
                host,
                "systemctl is-active nvidia-fabricmanager 2>/dev/null || true",
                sudo=False
            )
            status = result.get("stdout", "").strip()
            # 取第一行避免重复输出问题
            status = status.split('\n')[0].strip() if status else ""

            if status == "active":
                check_item.host_results[host] = CheckStatus.PASS
                check_item.details[host] = "运行中"
            elif status == "inactive" or status == "":
                # 可能没有安装，检查是否需要
                check_result = self.execute_on_host(
                    host,
                    "which nv-fabricmanager 2>/dev/null || true",
                    sudo=False
                )
                if not check_result.get("stdout", "").strip():
                    check_item.host_results[host] = CheckStatus.SKIP
                    check_item.details[host] = "未安装"
                else:
                    check_item.host_results[host] = CheckStatus.FAIL
                    check_item.details[host] = "已安装但未运行"
            else:
                check_item.host_results[host] = CheckStatus.UNKNOWN
                check_item.details[host] = status

        self._summarize_check(check_item, hosts)
        return check_item

    def _check_acs_status(self, hosts: List[str]) -> CheckItem:
        """检查ACS状态（应该被禁用）"""
        check_item = CheckItem(name="ACS状态", status=CheckStatus.UNKNOWN)

        for host in hosts:
            result = self.execute_on_host(
                host,
                "lspci -vvv 2>/dev/null | grep -c 'ACSCtl.*SrcValid+' || true",
                sudo=True
            )
            try:
                stdout = result.get("stdout", "0").strip()
                # 取第一行避免重复输出问题
                first_line = stdout.split('\n')[0].strip() if stdout else "0"
                acs_count = int(first_line) if first_line.isdigit() else 0
                # ACS应该被禁用（count应该为0）
                if acs_count == 0:
                    check_item.host_results[host] = CheckStatus.PASS
                    check_item.details[host] = "已禁用"
                else:
                    check_item.host_results[host] = CheckStatus.WARNING
                    check_item.details[host] = f"检测到 {acs_count} 个ACS启用"
            except ValueError:
                check_item.host_results[host] = CheckStatus.UNKNOWN
                check_item.details[host] = "无法获取"

        self._summarize_check(check_item, hosts)
        return check_item

    def _check_peermem_module(self, hosts: List[str]) -> CheckItem:
        """检查nvidia_peermem模块"""
        check_item = CheckItem(name="nvidia_peermem模块", status=CheckStatus.UNKNOWN)

        for host in hosts:
            result = self.execute_on_host(
                host,
                "lsmod | grep -c nvidia_peermem || true",
                sudo=False
            )
            try:
                stdout = result.get("stdout", "0").strip()
                # 取第一行避免重复输出问题
                first_line = stdout.split('\n')[0].strip() if stdout else "0"
                count = int(first_line) if first_line.isdigit() else 0
                if count > 0:
                    check_item.host_results[host] = CheckStatus.PASS
                    check_item.details[host] = "已加载"
                else:
                    # 检查配置文件是否存在（模块可能需要重启才能加载）
                    config_result = self.execute_on_host(
                        host,
                        "test -f /etc/modules-load.d/nvidia.conf && echo 'configured' || true",
                        sudo=False
                    )
                    if "configured" in config_result.get("stdout", ""):
                        check_item.host_results[host] = CheckStatus.WARNING
                        check_item.details[host] = "配置已创建，需重启加载"
                    else:
                        check_item.host_results[host] = CheckStatus.FAIL
                        check_item.details[host] = "未配置"
            except ValueError:
                check_item.host_results[host] = CheckStatus.UNKNOWN
                check_item.details[host] = "无法获取"

        self._summarize_check(check_item, hosts)
        return check_item

    def _check_time_sync(self, hosts: List[str]) -> CheckItem:
        """检查时间同步"""
        check_item = CheckItem(name="时间同步", status=CheckStatus.UNKNOWN)

        for host in hosts:
            result = self.execute_on_host(
                host,
                "chronyc tracking 2>/dev/null | grep 'Last offset' | awk '{print $4}' || echo 'unknown'",
                sudo=False
            )
            offset = result.get("stdout", "").strip()

            if offset == "unknown":
                # 检查chrony是否安装
                check_result = self.execute_on_host(
                    host,
                    "which chronyc 2>/dev/null || echo 'not_installed'",
                    sudo=False
                )
                if "not_installed" in check_result.get("stdout", ""):
                    check_item.host_results[host] = CheckStatus.SKIP
                    check_item.details[host] = "未安装chrony"
                else:
                    check_item.host_results[host] = CheckStatus.UNKNOWN
                    check_item.details[host] = "无法获取"
            else:
                try:
                    offset_val = float(offset)
                    if abs(offset_val) < 0.1:  # 小于100ms
                        check_item.host_results[host] = CheckStatus.PASS
                        check_item.details[host] = f"偏移 {offset}s"
                    else:
                        check_item.host_results[host] = CheckStatus.WARNING
                        check_item.details[host] = f"偏移 {offset}s (较大)"
                except ValueError:
                    check_item.host_results[host] = CheckStatus.UNKNOWN
                    check_item.details[host] = offset

        self._summarize_check(check_item, hosts)
        return check_item

    def _summarize_check(self, check_item: CheckItem, hosts: List[str]):
        """汇总检查结果"""
        all_pass = all(
            check_item.host_results.get(h) == CheckStatus.PASS
            for h in hosts
        )
        all_fail = all(
            check_item.host_results.get(h) in [CheckStatus.FAIL, CheckStatus.UNKNOWN]
            for h in hosts
        )
        all_skip = all(
            check_item.host_results.get(h) == CheckStatus.SKIP
            for h in hosts
        )

        if all_skip:
            check_item.status = CheckStatus.SKIP
            check_item.message = "所有节点跳过"
        elif all_pass:
            check_item.status = CheckStatus.PASS
            check_item.message = "所有节点正常"
        elif all_fail:
            check_item.status = CheckStatus.FAIL
            # 显示具体失败的节点和原因
            failed_hosts = []
            for h in hosts:
                status = check_item.host_results.get(h)
                if status in [CheckStatus.FAIL, CheckStatus.UNKNOWN]:
                    detail = check_item.details.get(h, "")
                    failed_hosts.append(f"{h}({detail})" if detail else h)
            check_item.message = f"异常节点: {', '.join(failed_hosts)}"
        else:
            # 检查是否有FAIL
            has_fail = any(
                check_item.host_results.get(h) == CheckStatus.FAIL
                for h in hosts
            )
            if has_fail:
                check_item.status = CheckStatus.WARNING
            else:
                check_item.status = CheckStatus.WARNING
            # 显示具体异常的节点和原因
            abnormal_hosts = []
            for h in hosts:
                status = check_item.host_results.get(h)
                if status != CheckStatus.PASS:
                    detail = check_item.details.get(h, "")
                    abnormal_hosts.append(f"{h}({detail})" if detail else h)
            check_item.message = f"异常节点: {', '.join(abnormal_hosts)}"

    def _print_report_summary(self, report: VerificationReport):
        """打印报告摘要"""
        self.logger.info("\n" + "=" * 60)
        self.logger.info("验证报告摘要")
        self.logger.info("=" * 60)
        self.logger.info(f"集群名称: {report.cluster_name}")
        self.logger.info(f"检查时间: {report.check_time}")
        self.logger.info(f"检查项总数: {report.total_checks}")
        self.logger.info(f"  通过: {report.passed}")
        self.logger.info(f"  失败: {report.failed}")
        self.logger.info(f"  警告: {report.warnings}")
        self.logger.info(f"  跳过: {report.skipped}")
        self.logger.info("-" * 60)

        # 网络状态
        self.logger.info(f"网络状态: {report.network_status.get('summary', 'unknown')}")

        # 设备状态
        self.logger.info(f"设备状态: {report.device_status.get('summary', 'unknown')}")

        self.logger.info("=" * 60)
        self.logger.info(report.summary)
        self.logger.info("=" * 60)

        # 显示失败的检查项
        failed_checks = [c for c in report.checks if c.status == CheckStatus.FAIL]
        if failed_checks:
            self.logger.info("\n失败的检查项:")
            for c in failed_checks:
                self.logger.info(f"  - {c.name}: {c.message}")
                # 显示节点详情
                for host, status in c.host_results.items():
                    if status in [CheckStatus.FAIL, CheckStatus.UNKNOWN]:
                        detail = c.details.get(host, "")
                        self.logger.info(f"      [{host}] {detail}")

        # 显示警告的检查项
        warning_checks = [c for c in report.checks if c.status == CheckStatus.WARNING]
        if warning_checks:
            self.logger.info("\n警告的检查项:")
            for c in warning_checks:
                self.logger.info(f"  - {c.name}: {c.message}")
                # 显示节点详情
                for host, status in c.host_results.items():
                    if status != CheckStatus.PASS:
                        detail = c.details.get(host, "")
                        self.logger.info(f"      [{host}] {detail}")

    def _generate_html_report(self, report: VerificationReport):
        """生成HTML报告"""
        import os

        report_dir = "logs"
        os.makedirs(report_dir, exist_ok=True)

        report_path = os.path.join(report_dir, "verification_report.html")

        html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>GPU集群验证报告 - {report.cluster_name}</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; background: #f5f5f5; }}
        .container {{ max-width: 1200px; margin: 0 auto; background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
        h1 {{ color: #333; border-bottom: 2px solid #4CAF50; padding-bottom: 10px; }}
        h2 {{ color: #555; margin-top: 30px; }}
        .summary {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 10px; margin: 20px 0; }}
        .summary-item {{ text-align: center; padding: 15px; border-radius: 8px; }}
        .summary-item.total {{ background: #e3f2fd; }}
        .summary-item.pass {{ background: #e8f5e9; }}
        .summary-item.fail {{ background: #ffebee; }}
        .summary-item.warning {{ background: #fff3e0; }}
        .summary-item.skip {{ background: #f5f5f5; }}
        .summary-item .count {{ font-size: 32px; font-weight: bold; }}
        .summary-item .label {{ font-size: 14px; color: #666; }}
        table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
        th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }}
        th {{ background: #f5f5f5; font-weight: bold; }}
        tr:hover {{ background: #f9f9f9; }}
        .status-pass {{ color: #4CAF50; font-weight: bold; }}
        .status-fail {{ color: #f44336; font-weight: bold; }}
        .status-warning {{ color: #ff9800; font-weight: bold; }}
        .status-skip {{ color: #9e9e9e; }}
        .status-unknown {{ color: #9e9e9e; }}
        .meta {{ color: #666; font-size: 14px; margin-bottom: 20px; }}
        .section {{ margin: 20px 0; padding: 15px; background: #fafafa; border-radius: 8px; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>GPU集群验证报告</h1>
        <div class="meta">
            <p>集群名称: {report.cluster_name}</p>
            <p>检查时间: {report.check_time}</p>
        </div>

        <div class="summary">
            <div class="summary-item total">
                <div class="count">{report.total_checks}</div>
                <div class="label">总检查项</div>
            </div>
            <div class="summary-item pass">
                <div class="count">{report.passed}</div>
                <div class="label">通过</div>
            </div>
            <div class="summary-item fail">
                <div class="count">{report.failed}</div>
                <div class="label">失败</div>
            </div>
            <div class="summary-item warning">
                <div class="count">{report.warnings}</div>
                <div class="label">警告</div>
            </div>
            <div class="summary-item skip">
                <div class="count">{report.skipped}</div>
                <div class="label">跳过</div>
            </div>
        </div>

        <div class="section">
            <h2>网络状态</h2>
            <p>状态: {report.network_status.get('summary', 'unknown')}</p>
        </div>

        <div class="section">
            <h2>设备状态</h2>
            <p>状态: {report.device_status.get('summary', 'unknown')}</p>
        </div>

        <h2>检查结果详情</h2>
        <table>
            <thead>
                <tr>
                    <th>检查项</th>
                    <th>状态</th>
                    <th>消息</th>
                </tr>
            </thead>
            <tbody>
"""

        for check in report.checks:
            status_class = f"status-{check.status.value}"
            status_text = {
                CheckStatus.PASS: "通过",
                CheckStatus.FAIL: "失败",
                CheckStatus.WARNING: "警告",
                CheckStatus.SKIP: "跳过",
                CheckStatus.UNKNOWN: "未知"
            }.get(check.status, check.status.value)

            # 构建节点详情HTML
            host_details_html = ""
            if check.host_results and check.details:
                host_details_html = '<div class="host-details" style="margin-top: 8px; font-size: 12px; color: #666;">'
                for host, status in check.host_results.items():
                    detail = check.details.get(host, "")
                    host_status_class = f"status-{status.value}"
                    host_status_text = {
                        CheckStatus.PASS: "✓",
                        CheckStatus.FAIL: "✗",
                        CheckStatus.WARNING: "⚠",
                        CheckStatus.SKIP: "○",
                        CheckStatus.UNKNOWN: "?"
                    }.get(status, "?")
                    host_details_html += f'<span class="{host_status_class}" style="margin-right: 10px;">{host}: {host_status_text} {detail}</span>'
                host_details_html += '</div>'

            html += f"""                <tr>
                    <td>{check.name}</td>
                    <td class="{status_class}">{status_text}</td>
                    <td>{check.message}{host_details_html}</td>
                </tr>
"""

        html += """            </tbody>
        </table>
    </div>
</body>
</html>
"""

        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(html)

        self.logger.info(f"HTML报告已生成: {report_path}")

    def post_check(self, hosts: List[str]) -> bool:
        """验证检查（本步骤不需要post_check）"""
        return True
