"""
RoCE Ping 连通性测试器 - 测试RoCE网络IP层连通性

对所有主机的所有网卡执行全量ping测试（N×M矩阵）
独立于ib_write_bw带宽测试
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Optional, List, Dict, TYPE_CHECKING

if TYPE_CHECKING:
    from src.ssh_manager import SSHManager
    from src.network.rdma_detector import RDMADetector

logger = logging.getLogger(__name__)


@dataclass
class PingResult:
    """单个ping测试结果"""
    source_host: str
    source_interface: str
    source_ip: str
    target_host: str
    target_interface: str
    target_ip: str
    success: bool
    packet_loss: float = 0.0
    avg_latency_ms: float = 0.0
    error_message: str = ""

    def to_dict(self) -> Dict:
        return {
            "source_host": self.source_host,
            "source_interface": self.source_interface,
            "source_ip": self.source_ip,
            "target_host": self.target_host,
            "target_interface": self.target_interface,
            "target_ip": self.target_ip,
            "success": self.success,
            "packet_loss": self.packet_loss,
            "avg_latency_ms": round(self.avg_latency_ms, 2),
            "error_message": self.error_message
        }


@dataclass
class PingTestReport:
    """Ping测试报告"""
    network_type: str = "compute"
    device_type: str = "RoCE"
    results: List[PingResult] = field(default_factory=list)
    total_tests: int = 0
    passed_tests: int = 0
    failed_tests: int = 0

    def to_dict(self) -> Dict:
        return {
            "network_type": self.network_type,
            "device_type": self.device_type,
            "results": [r.to_dict() for r in self.results],
            "total_tests": self.total_tests,
            "passed_tests": self.passed_tests,
            "failed_tests": self.failed_tests
        }


class RoCEPingTester:
    """RoCE网络Ping连通性测试器

    执行全量ping测试：对于每对主机(host1, host2):
    - host1的每个网卡 ping host2的每个网卡的IP
    - 双向测试（host2的每个网卡 ping host1的每个网卡的IP）

    这是一个 N×M 的全量测试矩阵
    """

    def __init__(self, ssh_manager: Optional["SSHManager"] = None,
                 rdma_detector: Optional["RDMADetector"] = None):
        """
        初始化测试器

        Args:
            ssh_manager: SSH管理器实例
            rdma_detector: RDMA设备检测器实例
        """
        self.ssh_manager = ssh_manager
        self.rdma_detector = rdma_detector

    def get_interface_ip(self, host: str, interface: str) -> Optional[str]:
        """
        获取主机指定网卡的IP地址

        Args:
            host: 主机名或IP
            interface: 网卡名称

        Returns:
            IP地址字符串，失败返回None
        """
        if not self.ssh_manager:
            logger.warning(f"SSH管理器未初始化，无法获取 {interface} 的IP")
            return None

        if not interface or not interface.strip():
            logger.warning(f"无效的网卡名称: {interface}")
            return None

        try:
            # 使用ip命令获取IP地址
            cmd = f"ip -4 addr show {interface} 2>/dev/null | grep -oP 'inet \\K[\\d.]+'"
            result = self.ssh_manager.execute_on_host(host, cmd, timeout=10)

            if result.success and result.stdout.strip():
                return result.stdout.strip().split('\n')[0].strip()

            # 备用方法：使用ifconfig
            cmd = f"ifconfig {interface} 2>/dev/null | grep -oP 'inet addr:\\K[\\d.]+'"
            result = self.ssh_manager.execute_on_host(host, cmd, timeout=10)

            if result.success and result.stdout.strip():
                return result.stdout.strip().split('\n')[0].strip()

            logger.debug(f"[{host}] 网卡 {interface} 未找到IPv4地址")
            return None

        except Exception as e:
            logger.error(f"[{host}] 获取网卡 {interface} IP地址失败: {e}")
            return None

    def get_rdma_interfaces(self, host: str, exclude_patterns: List[str] = None) -> Dict[str, str]:
        """
        获取主机上所有RDMA网卡及其IP地址

        Args:
            host: 主机名或IP
            exclude_patterns: 要排除的网卡名称模式列表 (如 ['bond', 'mgmt'])

        Returns:
            字典 {interface_name: ip_address}
        """
        interfaces = {}

        if not self.rdma_detector:
            logger.warning(f"[{host}] RDMA检测器未初始化，无法获取RDMA网卡")
            return interfaces

        if exclude_patterns is None:
            # 默认排除 bond 设备和以 bond 开头的设备（通常是管理网）
            exclude_patterns = ['bond', 'mgmt']

        try:
            # 获取所有RDMA设备
            devices = self.rdma_detector.get_all_devices(host)

            for device in devices:
                # 获取设备对应的网卡
                netdev = self.rdma_detector.get_device_netdev(host, device)
                if not netdev:
                    continue

                # 检查是否应该排除该网卡
                should_exclude = False
                for pattern in exclude_patterns:
                    if pattern.lower() in netdev.lower():
                        should_exclude = True
                        logger.debug(f"[{host}] 排除网卡 {netdev} (匹配模式: {pattern})")
                        break

                if should_exclude:
                    continue

                # 获取网卡IP
                ip = self.get_interface_ip(host, netdev)
                if ip:
                    interfaces[netdev] = ip
                    logger.debug(f"[{host}] {device} -> {netdev} -> {ip}")

            return interfaces

        except Exception as e:
            logger.error(f"[{host}] 获取RDMA网卡失败: {e}")
            return interfaces

    def ping_test(self, source_host: str, source_interface: str,
                  target_host: str, target_ip: str,
                  source_ip: str = None,
                  count: int = 1, deadline: int = 3) -> PingResult:
        """
        执行单个ping测试

        Args:
            source_host: 源主机
            source_interface: 源网卡
            target_host: 目标主机名
            target_ip: 目标IP
            source_ip: 源IP地址 (可选，如果不提供则动态获取)
            count: ping次数 (默认1次)
            deadline: 总超时时间(秒)，无论发多少包都会在此时停止 (默认3秒)

        Returns:
            PingResult对象
        """
        # 如果没有提供源IP，才动态获取
        if not source_ip:
            source_ip = self.get_interface_ip(source_host, source_interface)

        result = PingResult(
            source_host=source_host,
            source_interface=source_interface,
            source_ip=source_ip or "",
            target_host=target_host,
            target_interface="",  # 由调用者设置
            target_ip=target_ip,
            success=False
        )

        if not source_ip:
            result.error_message = f"无法获取源网卡 {source_interface} 的IP地址"
            return result

        if not self.ssh_manager:
            result.error_message = "SSH管理器未初始化"
            return result

        try:
            # 执行ping命令，指定源接口
            # -I: 指定源接口
            # -c: 发送的包数量
            # -W: 等待每个响应的超时时间(秒)
            # -w: 总超时时间(秒)，到时间就停止
            cmd = f"ping -I {source_interface} -c {count} -W 1 -w {deadline} {target_ip}"
            logger.debug(f"[{source_host}] 执行: {cmd}")

            # SSH 命令超时: deadline + 5秒缓冲
            exec_result = self.ssh_manager.execute_on_host(
                source_host, cmd, timeout=deadline + 5
            )

            if not exec_result.success:
                result.error_message = f"Ping命令执行失败: {exec_result.stderr}"
                return result

            output = exec_result.stdout

            # 解析ping结果
            # 丢包率: "3 packets transmitted, 3 received, 0% packet loss"
            loss_match = re.search(r'(\d+)%\s*packet\s*loss', output)
            if loss_match:
                result.packet_loss = float(loss_match.group(1))
            else:
                # 如果找不到丢包率，可能全部丢失
                if "0 packets received" in output or "100% packet loss" in output:
                    result.packet_loss = 100.0
                else:
                    result.packet_loss = 0.0

            # 平均延迟: "rtt min/avg/max/mdev = 0.123/0.456/0.789/0.123 ms"
            latency_match = re.search(r'rtt\s+min/avg/max/mdev\s*=\s*[\d.]+/([\d.]+)/', output)
            if latency_match:
                result.avg_latency_ms = float(latency_match.group(1))

            # 判断成功
            result.success = result.packet_loss == 0.0

            if not result.success:
                result.error_message = f"{result.packet_loss}% 丢包"

            return result

        except Exception as e:
            result.error_message = f"Ping测试异常: {e}"
            logger.error(f"[{source_host}] Ping测试异常: {e}")
            return result

    def test_host_pair(self, host1: str, host2: str,
                       host1_interfaces: Dict[str, str],
                       host2_interfaces: Dict[str, str],
                       max_workers: int = 4) -> List[PingResult]:
        """
        测试一对主机之间所有网卡的ping连通性（并发执行）

        Args:
            host1: 主机1
            host2: 主机2
            host1_interfaces: 主机1的网卡和IP {interface: ip}
            host2_interfaces: 主机2的网卡和IP {interface: ip}
            max_workers: 最大并发数 (默认4，避免SSH通道耗尽)

        Returns:
            PingResult列表
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        results = []
        ping_tasks = []

        # 收集所有 ping 任务
        # host1的每个网卡 ping host2的每个网卡
        for if1, ip1 in host1_interfaces.items():
            for if2, ip2 in host2_interfaces.items():
                ping_tasks.append((host1, if1, ip1, host2, ip2, if2))

        # host2的每个网卡 ping host1的每个网卡（双向测试）
        for if2, ip2 in host2_interfaces.items():
            for if1, ip1 in host1_interfaces.items():
                ping_tasks.append((host2, if2, ip2, host1, ip1, if1))

        # 并发执行所有 ping 测试
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {}
            for task in ping_tasks:
                src_host, src_if, src_ip, tgt_host, tgt_ip, tgt_if = task
                future = executor.submit(
                    self.ping_test, src_host, src_if, tgt_host, tgt_ip, src_ip
                )
                futures[future] = (src_host, src_if, tgt_host, tgt_ip, tgt_if)

            for future in as_completed(futures):
                src_host, src_if, tgt_host, tgt_ip, tgt_if = futures[future]
                try:
                    result = future.result()
                    result.target_interface = tgt_if
                    results.append(result)
                except Exception as e:
                    # 创建失败的 result
                    result = PingResult(
                        source_host=src_host,
                        source_interface=src_if,
                        source_ip="",
                        target_host=tgt_host,
                        target_interface=tgt_if,
                        target_ip=tgt_ip,
                        success=False,
                        error_message=str(e)
                    )
                    results.append(result)

        return results

    def test_all_pairs(self, hosts_info: List[Dict],
                       network_type: str = "compute",
                       device_type: str = "RoCE") -> PingTestReport:
        """
        测试所有主机间所有网卡的ping连通性

        对于每对主机 (host1, host2):
          对于 host1 的每个网卡 if1:
            对于 host2 的每个网卡 if2:
              host1: ping -I if1 -> host2:if2_ip
              host2: ping -I if2 -> host1:if1_ip (双向测试)

        Args:
            hosts_info: 主机信息列表 [{"hostname": ..., "ip": ..., "interfaces": {if: ip}}, ...]
            network_type: 网络类型
            device_type: 设备类型

        Returns:
            PingTestReport对象
        """
        report = PingTestReport(
            network_type=network_type,
            device_type=device_type
        )

        if len(hosts_info) < 2:
            logger.warning("至少需要2台主机进行ping测试")
            return report

        # 收集所有主机的网卡信息
        hosts_interfaces = {}
        for host_info in hosts_info:
            hostname = host_info.get("hostname", "")
            if not hostname:
                continue

            # 如果提供了interfaces，直接使用
            if "interfaces" in host_info:
                hosts_interfaces[hostname] = host_info["interfaces"]
            else:
                # 否则动态获取
                interfaces = self.get_rdma_interfaces(hostname)
                if interfaces:
                    hosts_interfaces[hostname] = interfaces

        if len(hosts_interfaces) < 2:
            logger.warning("未能获取足够的主机网卡信息")
            return report

        # 测试所有主机对
        hostnames = list(hosts_interfaces.keys())
        for i in range(len(hostnames)):
            for j in range(i + 1, len(hostnames)):
                host1 = hostnames[i]
                host2 = hostnames[j]

                logger.info(f"Ping测试: {host1} <-> {host2}")

                results = self.test_host_pair(
                    host1, host2,
                    hosts_interfaces[host1],
                    hosts_interfaces[host2]
                )

                report.results.extend(results)

        # 统计结果
        report.total_tests = len(report.results)
        report.passed_tests = sum(1 for r in report.results if r.success)
        report.failed_tests = report.total_tests - report.passed_tests

        logger.info(f"Ping测试完成: {report.passed_tests}/{report.total_tests} 通过")

        return report

    def generate_report_text(self, report: PingTestReport) -> str:
        """
        生成文本格式的ping测试报告

        Args:
            report: Ping测试报告

        Returns:
            文本格式报告
        """
        lines = []

        lines.append("## Ping 连通性测试 (RoCE IP层 - 所有网卡互相ping)")

        if not report.results:
            lines.append("  无测试结果")
            return "\n".join(lines)

        # 按主机对分组结果
        host_pairs = {}
        for result in report.results:
            # 创建主机对的唯一键（排序以避免重复）
            hosts = sorted([result.source_host, result.target_host])
            pair_key = f"{hosts[0]} <-> {hosts[1]}"
            if pair_key not in host_pairs:
                host_pairs[pair_key] = []
            host_pairs[pair_key].append(result)

        # 输出每个主机对的结果
        for pair_key, results in sorted(host_pairs.items()):
            lines.append(f"  主机对: {pair_key}")

            for r in results:
                if r.success:
                    status = "✓"
                    detail = f"{r.packet_loss:.0f}% loss, {r.avg_latency_ms:.1f}ms"
                else:
                    status = "✗"
                    detail = r.error_message if r.error_message else f"{r.packet_loss:.0f}% loss"

                lines.append(
                    f"    {r.source_host}:{r.source_interface} -> "
                    f"{r.target_host}:{r.target_interface} ({r.target_ip}): "
                    f"{status} {detail}"
                )

        lines.append(f"  Ping 测试结果: {report.passed_tests} 通过 / {report.failed_tests} 失败")
        lines.append("")

        return "\n".join(lines)
