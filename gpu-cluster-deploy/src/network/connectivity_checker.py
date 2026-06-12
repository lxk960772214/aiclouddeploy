"""
网络连通性检查模块

检查主机的 IP 层、DNS 解析、HTTP 连接状态
"""

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Any
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

    def to_dict(self) -> Dict[str, Any]:
        return {
            "check_type": self.check_type.value,
            "success": self.success,
            "message": self.message,
            "latency_ms": self.latency_ms,
            "details": self.details
        }


@dataclass
class HostConnectivityResult:
    """单台主机的连通性检查结果"""
    host: str
    ip_check: CheckResult
    dns_check: CheckResult
    http_check: CheckResult

    @property
    def all_passed(self) -> bool:
        """所有检查是否全部通过"""
        return self.ip_check.success and self.dns_check.success and self.http_check.success

    @property
    def partial_passed(self) -> bool:
        """是否有部分检查通过"""
        return any([
            self.ip_check.success,
            self.dns_check.success,
            self.http_check.success
        ]) and not self.all_passed

    def to_dict(self) -> Dict[str, Any]:
        return {
            "host": self.host,
            "all_passed": self.all_passed,
            "partial_passed": self.partial_passed,
            "checks": {
                "ip": self.ip_check.to_dict(),
                "dns": self.dns_check.to_dict(),
                "http": self.http_check.to_dict()
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
        """
        初始化检查器

        Args:
            ssh_manager: SSH 管理器
            batch_executor: 批量执行器（可选）
            logger: 日志记录器
        """
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
            timeout=self.PING_COUNT * self.PING_TIMEOUT + 10
        )

        stdout = result.stdout or ""
        stderr = result.stderr or ""

        if result.success and "0% packet loss" in stdout:
            # 解析延迟
            latency = self._parse_ping_latency(stdout)
            return CheckResult(
                check_type=CheckType.IP,
                success=True,
                message=f"IP层连通正常，延迟 {latency:.1f}ms",
                latency_ms=latency,
                details={"target": target}
            )

        # 解析失败原因
        error_msg = self._parse_ping_error(stdout or stderr)
        return CheckResult(
            check_type=CheckType.IP,
            success=False,
            message=f"IP层连通失败: {error_msg}",
            details={"target": target, "error": error_msg}
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
            timeout=self.PING_COUNT * self.PING_TIMEOUT + 10
        )

        stdout = result.stdout or ""
        stderr = result.stderr or ""

        if result.success and "0% packet loss" in stdout:
            latency = self._parse_ping_latency(stdout)
            return CheckResult(
                check_type=CheckType.DNS,
                success=True,
                message=f"DNS解析正常，延迟 {latency:.1f}ms",
                latency_ms=latency,
                details={"target": target}
            )

        # 检查是否是DNS解析失败
        if "Name or service not known" in stdout or "Temporary failure in name resolution" in stdout:
            return CheckResult(
                check_type=CheckType.DNS,
                success=False,
                message="DNS解析失败: 无法解析域名",
                details={"target": target, "error": "dns_resolution_failed"}
            )

        error_msg = self._parse_ping_error(stdout or stderr)
        return CheckResult(
            check_type=CheckType.DNS,
            success=False,
            message=f"DNS检查失败: {error_msg}",
            details={"target": target, "error": error_msg}
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
            timeout=self.HTTP_TIMEOUT + 10
        )

        stdout = result.stdout or ""
        stderr = result.stderr or ""

        if result.success:
            http_code = stdout.strip().strip("'\"")
            if http_code.isdigit():
                code = int(http_code)
                if 200 <= code < 500:
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
            message=f"HTTP连接失败: {stderr or '未知错误'}",
            details={"target": target, "error": stderr or "unknown"}
        )

    def check_host(self, host: str, username: str, password: str) -> HostConnectivityResult:
        """
        执行单台主机的所有连通性检查（并行执行三种检查）

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
            future_ip = executor.submit(
                self.check_ip_connectivity, host, username, password
            )
            future_dns = executor.submit(
                self.check_dns_resolution, host, username, password
            )
            future_http = executor.submit(
                self.check_http_connection, host, username, password
            )

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
        检查所有主机的连通性（并行检查多台主机）

        Args:
            hosts: 主机列表，每项为 (host, username, password)

        Returns:
            Dict[str, HostConnectivityResult]: 每个主机的检查结果
        """
        results = {}
        self.logger.info(f"[ConnectivityCheck] 开始检查 {len(hosts)} 台主机的网络连通性...")

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
        """解析ping输出中的平均延迟"""
        match = re.search(r'rtt min/avg/max/mdev = [\d.]+/([\d.]+)/', output)
        if match:
            return float(match.group(1))
        # 备用解析方式
        match = re.search(r'time=([\d.]+)\s*ms', output)
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
        if "Temporary failure in name resolution" in output:
            return "DNS 解析临时失败"
        if "connect: Network is unreachable" in output:
            return "网络不可达"

        return "未知错误"


def generate_connectivity_report(results: Dict[str, HostConnectivityResult]) -> str:
    """
    生成网络连通性检查报告

    Args:
        results: 检查结果字典

    Returns:
        str: Markdown 格式的报告
    """
    lines = [
        "# 网络连通性检查报告",
        "",
        "## 检查结果汇总",
        "",
        "| 主机 | IP层 | DNS | HTTP | 状态 |",
        "|------|------|-----|------|------|",
    ]

    # 统计
    all_passed = sum(1 for r in results.values() if r.all_passed)
    partial_passed = sum(1 for r in results.values() if r.partial_passed)
    failed = len(results) - all_passed - partial_passed

    for host, result in sorted(results.items()):
        ip_status = "✓" if result.ip_check.success else "✗"
        dns_status = "✓" if result.dns_check.success else "✗"
        http_status = "✓" if result.http_check.success else "✗"

        if result.all_passed:
            overall = "✅ 全部通过"
        elif result.partial_passed:
            overall = "⚠️ 部分通过"
        else:
            overall = "❌ 失败"

        lines.append(
            f"| {host} | {ip_status} | {dns_status} | {http_status} | {overall} |"
        )

    # 添加汇总
    lines.extend([
        "",
        f"**统计**: {all_passed} 全部通过, {partial_passed} 部分通过, {failed} 失败",
        ""
    ])

    # 添加失败详情
    failed_hosts = {h: r for h, r in results.items() if not r.all_passed}
    if failed_hosts:
        lines.extend([
            "## 失败详情",
            ""
        ])

        for host, result in sorted(failed_hosts.items()):
            lines.append(f"### {host}")
            if not result.ip_check.success:
                lines.append(f"- **IP层**: {result.ip_check.message}")
            if not result.dns_check.success:
                lines.append(f"- **DNS**: {result.dns_check.message}")
            if not result.http_check.success:
                lines.append(f"- **HTTP**: {result.http_check.message}")
            lines.append("")

    return "\n".join(lines)
