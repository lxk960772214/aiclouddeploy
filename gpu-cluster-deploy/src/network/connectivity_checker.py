"""
网络连通性检查模块

检查主机的内网互通性（节点间 ping）和外网连通性（DNS 解析、HTTP 连接）
"""

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Any
from concurrent.futures import ThreadPoolExecutor, as_completed

from src.utils.logger import get_logger


class CheckType(Enum):
    """检查类型"""
    INTERNAL_PING = "internal_ping"   # 内网互通（节点间 ping）
    DNS = "dns"                       # DNS解析
    HTTP = "http"                     # HTTP连接


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
class InternalPingResult:
    """单次内网 ping 结果"""
    target_host: str
    success: bool
    latency_ms: float = 0.0
    message: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "target_host": self.target_host,
            "success": self.success,
            "latency_ms": self.latency_ms,
            "message": self.message
        }


@dataclass
class HostConnectivityResult:
    """单台主机的连通性检查结果"""
    host: str
    # 内网互通检查
    internal_ping: CheckResult          # 内网互通总览
    internal_ping_details: List[InternalPingResult] = field(default_factory=list)  # 逐节点 ping 详情
    # 外网连通检查
    dns_check: CheckResult = None
    http_check: CheckResult = None

    @property
    def internal_passed(self) -> bool:
        """内网互通是否全部通过"""
        return self.internal_ping.success

    @property
    def external_passed(self) -> bool:
        """外网连通是否全部通过"""
        if self.dns_check is None and self.http_check is None:
            return True  # 未检查外网，视为通过
        results = []
        if self.dns_check is not None:
            results.append(self.dns_check.success)
        if self.http_check is not None:
            results.append(self.http_check.success)
        return all(results)

    @property
    def all_passed(self) -> bool:
        """所有检查是否全部通过"""
        return self.internal_passed and self.external_passed

    def to_dict(self) -> Dict[str, Any]:
        return {
            "host": self.host,
            "internal_passed": self.internal_passed,
            "external_passed": self.external_passed,
            "all_passed": self.all_passed,
            "internal_ping": self.internal_ping.to_dict(),
            "internal_ping_details": [d.to_dict() for d in self.internal_ping_details],
            "dns_check": self.dns_check.to_dict() if self.dns_check else None,
            "http_check": self.http_check.to_dict() if self.http_check else None
        }


class ConnectivityChecker:
    """网络连通性检查器"""

    # 默认检查目标
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

    def check_internal_ping(self, host: str, username: str, password: str,
                            target_hosts: List[str]) -> CheckResult:
        """
        检查内网互通性（从 host ping 所有 target_hosts）

        Args:
            host: 当前检查的主机
            username: SSH用户名
            password: SSH密码
            target_hosts: 需要 ping 的目标主机列表

        Returns:
            CheckResult: 内网互通总览结果
        """
        if not target_hosts:
            return CheckResult(
                check_type=CheckType.INTERNAL_PING,
                success=True,
                message="无内网目标需要检查",
                details={}
            )

        details = []
        success_count = 0
        total_latency = 0.0

        for target in target_hosts:
            # 不 ping 自己
            if target == host:
                continue

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
                total_latency += latency
                success_count += 1
                details.append(InternalPingResult(
                    target_host=target,
                    success=True,
                    latency_ms=latency,
                    message=f"连通，延迟 {latency:.1f}ms"
                ))
            else:
                error_msg = self._parse_ping_error(stdout or stderr)
                details.append(InternalPingResult(
                    target_host=target,
                    success=False,
                    message=f"不通: {error_msg}"
                ))

        # 统计结果（排除自身后的目标数）
        expected_count = len([t for t in target_hosts if t != host])
        if expected_count == 0:
            return CheckResult(
                check_type=CheckType.INTERNAL_PING,
                success=True,
                message="无其他内网节点需要检查",
                details={"targets": details}
            )

        all_success = success_count == expected_count
        if all_success:
            avg_latency = total_latency / success_count if success_count > 0 else 0
            return CheckResult(
                check_type=CheckType.INTERNAL_PING,
                success=True,
                message=f"内网互通正常 ({success_count}/{expected_count})，平均延迟 {avg_latency:.1f}ms",
                latency_ms=avg_latency,
                details={"targets": details}
            )
        else:
            failed_targets = [d.target_host for d in details if not d.success]
            return CheckResult(
                check_type=CheckType.INTERNAL_PING,
                success=False,
                message=f"内网互通异常 ({success_count}/{expected_count})，不可达: {', '.join(failed_targets)}",
                details={"targets": details, "failed_targets": failed_targets}
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

    def check_host(self, host: str, username: str, password: str,
                   all_hosts: List[str] = None) -> HostConnectivityResult:
        """
        执行单台主机的所有连通性检查

        Args:
            host: 当前检查的主机
            username: SSH用户名
            password: SSH密码
            all_hosts: 所有内网主机列表（用于内网互通检查）

        Returns:
            HostConnectivityResult: 检查结果
        """
        self.logger.info(f"[ConnectivityCheck] 检查主机: {host}")

        # 并行执行内网互通和外网连通检查
        with ThreadPoolExecutor(max_workers=3) as executor:
            # 内网互通检查
            future_internal = executor.submit(
                self.check_internal_ping, host, username, password,
                all_hosts or [host]
            )
            # 外网DNS检查
            future_dns = executor.submit(
                self.check_dns_resolution, host, username, password
            )
            # 外网HTTP检查
            future_http = executor.submit(
                self.check_http_connection, host, username, password
            )

            internal_result = future_internal.result()
            dns_result = future_dns.result()
            http_result = future_http.result()

        return HostConnectivityResult(
            host=host,
            internal_ping=internal_result,
            internal_ping_details=internal_result.details.get("targets", []),
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
        # 提取所有主机 IP 列表，用于内网互通检查
        all_host_ips = [h[0] for h in hosts]

        results = {}
        self.logger.info(f"[ConnectivityCheck] 开始检查 {len(hosts)} 台主机的网络连通性...")

        # 使用线程池并行检查多台主机
        with ThreadPoolExecutor(max_workers=min(len(hosts), 10)) as executor:
            futures = {
                executor.submit(self.check_host, host, username, password, all_host_ips): host
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
                        check_type=CheckType.INTERNAL_PING,
                        success=False,
                        message=f"检查异常: {str(e)}"
                    )
                    results[host] = HostConnectivityResult(
                        host=host,
                        internal_ping=failed_check,
                        dns_check=CheckResult(check_type=CheckType.DNS, success=False, message=f"检查异常: {str(e)}"),
                        http_check=CheckResult(check_type=CheckType.HTTP, success=False, message=f"检查异常: {str(e)}")
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
    生成网络连通性检查报告（内网互通 + 外网连通分开统计）

    Args:
        results: 检查结果字典

    Returns:
        str: Markdown 格式的报告
    """
    # ===== 统计 =====
    internal_ok = sum(1 for r in results.values() if r.internal_passed)
    external_ok = sum(1 for r in results.values() if r.external_passed)
    all_ok = sum(1 for r in results.values() if r.all_passed)
    failed = len(results) - all_ok

    lines = [
        "# 网络连通性检查报告",
        "",
        "## 检查结果汇总",
        "",
        "| 主机 | 内网互通 | DNS | HTTP | 状态 |",
        "|------|----------|-----|------|------|",
    ]

    for host, result in sorted(results.items()):
        internal_status = "✓" if result.internal_passed else "✗"
        dns_status = "✓" if result.dns_check and result.dns_check.success else "✗"
        http_status = "✓" if result.http_check and result.http_check.success else "✗"

        if result.all_passed:
            overall = "✅ 全部通过"
        elif result.internal_passed:
            overall = "⚠️ 内网正常/外网不通"
        else:
            overall = "❌ 内网异常"

        lines.append(
            f"| {host} | {internal_status} | {dns_status} | {http_status} | {overall} |"
        )

    lines.extend([
        "",
        f"**统计**: 内网互通 {internal_ok}/{len(results)} 通过，外网连通 {external_ok}/{len(results)} 通过",
        ""
    ])

    # ===== 内网互通详情 =====
    internal_failed = {h: r for h, r in results.items() if not r.internal_passed}
    if internal_failed:
        lines.extend([
            "## 内网互通失败详情",
            ""
        ])
        for host, result in sorted(internal_failed.items()):
            lines.append(f"### {host}")
            lines.append(f"- **总览**: {result.internal_ping.message}")
            for detail in result.internal_ping_details:
                status = "✓" if detail.success else "✗"
                lines.append(f"  - {status} → {detail.target_host}: {detail.message}")
            lines.append("")

    # ===== 外网连通详情 =====
    external_failed = {h: r for h, r in results.items()
                       if not r.external_passed and r.internal_passed}
    if external_failed:
        lines.extend([
            "## 外网连通失败详情（内网正常但外网不通的节点）",
            ""
        ])
        for host, result in sorted(external_failed.items()):
            lines.append(f"### {host}")
            if result.dns_check and not result.dns_check.success:
                lines.append(f"- **DNS**: {result.dns_check.message}")
            if result.http_check and not result.http_check.success:
                lines.append(f"- **HTTP**: {result.http_check.message}")
            lines.append("")

    # ===== 内网互通矩阵 =====
    lines.extend([
        "## 内网互通矩阵",
        ""
    ])

    all_hosts = sorted(results.keys())
    if all_hosts:
        # 表头
        header = "| 源 \\ 目 | " + " | ".join(all_hosts) + " |"
        separator = "|" + "---|" * (len(all_hosts) + 1)
        lines.append(header)
        lines.append(separator)

        # 表体
        for src in all_hosts:
            row = f"| {src} |"
            result = results[src]
            for dst in all_hosts:
                if src == dst:
                    row += " - |"
                else:
                    # 从详情中查找
                    found = False
                    for detail in result.internal_ping_details:
                        if detail.target_host == dst:
                            row += " ✓ |" if detail.success else " ✗ |"
                            found = True
                            break
                    if not found:
                        row += " ? |"
            lines.append(row)

        lines.append("")

    return "\n".join(lines)
