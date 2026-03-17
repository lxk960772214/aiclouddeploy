"""
三轮测试策略模块 - 定位异常网络设备
"""

import logging
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Tuple, TYPE_CHECKING
from concurrent.futures import ThreadPoolExecutor, as_completed
from enum import Enum

if TYPE_CHECKING:
    from src.ssh_manager import SSHManager
    from src.network.rdma_detector import RDMADetector
    from src.network.ibandwidth_tester import IBWriteBWTester, BandwidthTestResult

logger = logging.getLogger(__name__)


class TestPhase(Enum):
    """测试阶段"""
    ROUND_1 = "round1"  # 相邻配对
    ROUND_2 = "round2"  # 错位配对
    ROUND_3 = "round3"  # 异常定位


class DeviceStatus(Enum):
    """设备状态"""
    NORMAL = "normal"
    ABNORMAL = "abnormal"
    SUSPECTED = "suspected"
    UNKNOWN = "unknown"


@dataclass
class HostDevices:
    """主机设备信息"""
    hostname: str
    ip: str
    devices: List[str] = field(default_factory=list)
    device_status: Dict[str, DeviceStatus] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            "hostname": self.hostname,
            "ip": self.ip,
            "devices": self.devices,
            "device_status": {k: str(v) for k, v in self.device_status.items()}
        }


@dataclass
class TestPair:
    """测试配对"""
    server_host: str
    client_host: str
    server_device: str
    client_device: str
    phase: TestPhase

    def to_dict(self) -> Dict:
        return {
            "server_host": self.server_host,
            "client_host": self.client_host,
            "server_device": self.server_device,
            "client_device": self.client_device,
            "phase": str(self.phase)
        }


@dataclass
class PhaseResult:
    """阶段测试结果"""
    phase: TestPhase
    pairs: List[TestPair] = field(default_factory=list)
    results: List[Dict] = field(default_factory=list)
    abnormal_hosts: List[str] = field(default_factory=list)
    abnormal_devices: Dict[str, List[str]] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            "phase": str(self.phase),
            "pairs": [p.to_dict() for p in self.pairs],
            "results": self.results,
            "abnormal_hosts": self.abnormal_hosts,
            "abnormal_devices": self.abnormal_devices
        }


@dataclass
class DeviceTestStats:
    """设备测试统计"""
    status: DeviceStatus = DeviceStatus.UNKNOWN
    test_count: int = 0
    fail_count: int = 0
    error_details: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "status": self.status.value if isinstance(self.status, DeviceStatus) else str(self.status),
            "test_count": self.test_count,
            "fail_count": self.fail_count,
            "error_details": self.error_details
        }


@dataclass
class ThreePhaseReport:
    """三轮测试报告"""
    hosts: List[HostDevices] = field(default_factory=list)
    round1: Optional[PhaseResult] = None
    round2: Optional[PhaseResult] = None
    round3: Optional[PhaseResult] = None
    final_status: Dict[str, Dict[str, DeviceStatus]] = field(default_factory=dict)
    device_stats: Dict[str, Dict[str, DeviceTestStats]] = field(default_factory=dict)
    summary: Dict = field(default_factory=dict)
    network_type: str = "compute"
    device_type: str = "RoCE"
    theoretical_bandwidth_gbps: float = 400.0
    test_config: Dict = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            "hosts": [h.to_dict() for h in self.hosts],
            "round1": self.round1.to_dict() if self.round1 else None,
            "round2": self.round2.to_dict() if self.round2 else None,
            "round3": self.round3.to_dict() if self.round3 else None,
            "final_status": {
                host: {dev: status.value if isinstance(status, DeviceStatus) else str(status) for dev, status in devices.items()}
                for host, devices in self.final_status.items()
            },
            "device_stats": {
                host: {dev: stats.to_dict() for dev, stats in devices.items()}
                for host, devices in self.device_stats.items()
            },
            "summary": self.summary,
            "network_type": self.network_type,
            "device_type": self.device_type,
            "theoretical_bandwidth_gbps": self.theoretical_bandwidth_gbps,
            "test_config": self.test_config
        }


class ThreePhaseTester:
    """三轮测试策略

    通过三轮测试定位异常网络设备：
    1. 第一轮：相邻配对测试 (1,2), (3,4), ...
    2. 第二轮：错位配对测试 (2,3), (4,5), ...
    3. 第三轮：使用正常主机定位异常设备
    """

    def __init__(self, ssh_manager: Optional["SSHManager"] = None,
                 rdma_detector: Optional["RDMADetector"] = None,
                 bandwidth_tester: Optional["IBWriteBWTester"] = None):
        """
        初始化测试器

        Args:
            ssh_manager: SSH管理器
            rdma_detector: RDMA设备检测器
            bandwidth_tester: 带宽测试器
        """
        self.ssh_manager = ssh_manager
        self.rdma_detector = rdma_detector
        self.bandwidth_tester = bandwidth_tester

    def _generate_round1_pairs(self, hosts: List[HostDevices],
                                network_type: str = "compute") -> List[TestPair]:
        """
        生成第一轮配对：相邻配对 (1,2), (3,4), ...

        Args:
            hosts: 主机列表
            network_type: 网络类型

        Returns:
            测试配对列表
        """
        pairs = []
        for i in range(0, len(hosts) - 1, 2):
            host1 = hosts[i]
            host2 = hosts[i + 1]

            # 配对设备
            for d1, d2 in zip(host1.devices, host2.devices):
                pairs.append(TestPair(
                    server_host=host1.hostname,
                    client_host=host2.hostname,
                    server_device=d1,
                    client_device=d2,
                    phase=TestPhase.ROUND_1
                ))

        return pairs

    def _generate_round2_pairs(self, hosts: List[HostDevices],
                                network_type: str = "compute") -> List[TestPair]:
        """
        生成第二轮配对：错位配对 (2,3), (4,5), ...

        Args:
            hosts: 主机列表
            network_type: 网络类型

        Returns:
            测试配对列表
        """
        pairs = []

        # 从第2个主机开始配对
        start = 1 if len(hosts) >= 3 else 0

        for i in range(start, len(hosts) - 1, 2):
            host1 = hosts[i]
            host2 = hosts[i + 1]

            for d1, d2 in zip(host1.devices, host2.devices):
                pairs.append(TestPair(
                    server_host=host1.hostname,
                    client_host=host2.hostname,
                    server_device=d1,
                    client_device=d2,
                    phase=TestPhase.ROUND_2
                ))

        # 如果主机数量是偶数，添加首尾配对
        if len(hosts) > 2 and len(hosts) % 2 == 0:
            host_last = hosts[-1]
            host_first = hosts[0]
            for d1, d2 in zip(host_last.devices, host_first.devices):
                pairs.append(TestPair(
                    server_host=host_last.hostname,
                    client_host=host_first.hostname,
                    server_device=d1,
                    client_device=d2,
                    phase=TestPhase.ROUND_2
                ))

        return pairs

    def _generate_round3_pairs(self, hosts: List[HostDevices],
                                normal_host: HostDevices,
                                suspected_hosts: List[HostDevices]) -> List[TestPair]:
        """
        生成第三轮配对：正常主机 vs 异常主机

        Args:
            hosts: 主机列表
            normal_host: 正常主机
            suspected_hosts: 疑似异常主机列表

        Returns:
            测试配对列表
        """
        pairs = []

        for suspected in suspected_hosts:
            for d_normal, d_suspected in zip(normal_host.devices, suspected.devices):
                pairs.append(TestPair(
                    server_host=normal_host.hostname,
                    client_host=suspected.hostname,
                    server_device=d_normal,
                    client_device=d_suspected,
                    phase=TestPhase.ROUND_3
                ))

        return pairs

    def run_tests(self, pairs: List[TestPair],
                  test_config: Optional[Dict] = None,
                  max_workers: int = 4) -> List[Dict]:
        """
        执行测试

        Args:
            pairs: 测试配对列表
            test_config: 测试配置
            max_workers: 最大并发数

        Returns:
            测试结果列表
        """
        if not self.bandwidth_tester:
            return [{"error": "带宽测试器未初始化"} for _ in pairs]

        results = []
        test_pairs = [
            (p.server_host, p.client_host, p.server_device, p.client_device)
            for p in pairs
        ]

        # 导入配置类
        from .ibandwidth_tester import BandwidthTestConfig

        config = BandwidthTestConfig()
        if test_config:
            if "duration" in test_config:
                config.duration = test_config["duration"]
            if "size" in test_config:
                config.size = test_config["size"]
            if "port_base" in test_config:
                config.port_base = test_config["port_base"]
            if "min_bandwidth_percent" in test_config:
                config.min_bandwidth_percent = test_config["min_bandwidth_percent"]
            if "theoretical_bandwidth_gbps" in test_config:
                config.theoretical_bandwidth_gbps = test_config["theoretical_bandwidth_gbps"]

        test_results = self.bandwidth_tester.test_concurrent(
            test_pairs, config, max_workers
        )

        for pair, result in zip(pairs, test_results):
            results.append({
                "pair": pair.to_dict(),
                "result": result.to_dict()
            })

        return results

    def analyze_round_results(self, results: List[Dict]) -> Tuple[List[str], Dict[str, List[str]]]:
        """
        分析轮次测试结果

        Args:
            results: 测试结果列表

        Returns:
            (异常主机列表, 异常设备字典)
        """
        abnormal_hosts = set()
        abnormal_devices = {}  # {hostname: [device1, device2, ...]}

        for item in results:
            result = item.get("result", {})
            pair = item.get("pair", {})

            if not result.get("success", False):
                server_host = pair.get("server_host")
                client_host = pair.get("client_host")
                server_device = pair.get("server_device")
                client_device = pair.get("client_device")

                # 记录异常
                if server_host:
                    abnormal_hosts.add(server_host)
                    if server_host not in abnormal_devices:
                        abnormal_devices[server_host] = []
                    if server_device and server_device not in abnormal_devices[server_host]:
                        abnormal_devices[server_host].append(server_device)

                if client_host:
                    abnormal_hosts.add(client_host)
                    if client_host not in abnormal_devices:
                        abnormal_devices[client_host] = []
                    if client_device and client_device not in abnormal_devices[client_host]:
                        abnormal_devices[client_host].append(client_device)

        return list(abnormal_hosts), abnormal_devices

    def execute(self, hosts_info: List[Dict],
                test_config: Optional[Dict] = None,
                max_workers: int = 4,
                skip_round2_if_all_normal: bool = True,
                network_type: str = "compute") -> ThreePhaseReport:
        """
        执行三轮测试

        Args:
            hosts_info: 主机信息列表 [{"hostname": ..., "ip": ..., "devices": [...]}, ...]
            test_config: 测试配置
            max_workers: 最大并发数
            skip_round2_if_all_normal: 如果第一轮全部正常是否跳过后续轮次
            network_type: 网络类型 (compute/storage)

        Returns:
            ThreePhaseReport测试报告
        """
        # 构建主机设备列表
        hosts = [
            HostDevices(
                hostname=h.get("hostname", ""),
                ip=h.get("ip", ""),
                devices=h.get("devices", [])
            )
            for h in hosts_info
        ]

        # 检测设备类型
        device_type = self._detect_device_type(hosts_info)

        # 初始化测试配置
        if test_config is None:
            test_config = {}

        report = ThreePhaseReport(
            hosts=hosts,
            network_type=network_type,
            device_type=device_type,
            theoretical_bandwidth_gbps=test_config.get("theoretical_bandwidth_gbps", 400.0),
            test_config=test_config
        )

        if len(hosts) < 2:
            report.summary = {"error": "至少需要2台主机进行测试"}
            return report

        # 第一轮：相邻配对测试
        logger.info("执行第一轮测试：相邻配对...")
        round1_pairs = self._generate_round1_pairs(hosts)
        round1_results = self.run_tests(round1_pairs, test_config, max_workers)
        round1_abnormal_hosts, round1_abnormal_devices = self.analyze_round_results(round1_results)

        report.round1 = PhaseResult(
            phase=TestPhase.ROUND_1,
            pairs=round1_pairs,
            results=round1_results,
            abnormal_hosts=round1_abnormal_hosts,
            abnormal_devices=round1_abnormal_devices
        )

        logger.info(f"第一轮完成，发现 {len(round1_abnormal_hosts)} 台异常主机")

        # 检查是否所有主机都参与了第一轮测试
        # 奇数主机时，最后一台主机在第一轮被跳过，必须执行第二轮
        all_hosts_tested_in_round1 = (len(hosts) % 2 == 0)

        # 如果第一轮全部正常且所有主机都已测试，才跳过后续轮次
        if skip_round2_if_all_normal and not round1_abnormal_hosts and all_hosts_tested_in_round1:
            logger.info("第一轮测试全部正常，所有主机都已测试，跳过后续轮次")
            # 仍然需要生成最终状态和设备统计
            report.final_status = self._determine_final_status(report, hosts)
            report.device_stats = self._generate_device_stats(report, hosts)
            report.summary = self._generate_summary(report)
            return report

        # 第二轮：错位配对测试
        logger.info("执行第二轮测试：错位配对...")
        round2_pairs = self._generate_round2_pairs(hosts)
        round2_results = self.run_tests(round2_pairs, test_config, max_workers)
        round2_abnormal_hosts, round2_abnormal_devices = self.analyze_round_results(round2_results)

        report.round2 = PhaseResult(
            phase=TestPhase.ROUND_2,
            pairs=round2_pairs,
            results=round2_results,
            abnormal_hosts=round2_abnormal_hosts,
            abnormal_devices=round2_abnormal_devices
        )

        logger.info(f"第二轮完成，发现 {len(round2_abnormal_hosts)} 台异常主机")

        # 合并前两轮结果，确定疑似异常主机
        all_abnormal_hosts = set(round1_abnormal_hosts) | set(round2_abnormal_hosts)

        # 找一台正常主机
        normal_host = None
        for h in hosts:
            if h.hostname not in all_abnormal_hosts:
                normal_host = h
                break

        # 第三轮：使用正常主机定位异常设备
        if normal_host and all_abnormal_hosts:
            logger.info("执行第三轮测试：定位异常设备...")
            suspected_hosts = [h for h in hosts if h.hostname in all_abnormal_hosts]
            round3_pairs = self._generate_round3_pairs(hosts, normal_host, suspected_hosts)
            round3_results = self.run_tests(round3_pairs, test_config, max_workers)
            round3_abnormal_hosts, round3_abnormal_devices = self.analyze_round_results(round3_results)

            report.round3 = PhaseResult(
                phase=TestPhase.ROUND_3,
                pairs=round3_pairs,
                results=round3_results,
                abnormal_hosts=round3_abnormal_hosts,
                abnormal_devices=round3_abnormal_devices
            )

            logger.info(f"第三轮完成，精确定位异常设备")

        # 生成最终状态
        report.final_status = self._determine_final_status(report, hosts)
        # 生成设备统计信息
        report.device_stats = self._generate_device_stats(report, hosts)

        # 生成最终状态
        report.final_status = self._determine_final_status(report, hosts)
        report.summary = self._generate_summary(report)

        return report

    def _detect_device_type(self, hosts_info: List[Dict]) -> str:
        """
        检测设备类型 (RoCE/InfiniBand)

        Args:
            hosts_info: 主机信息列表

        Returns:
            设备类型字符串
        """
        if not self.rdma_detector or not hosts_info:
            return "RoCE"  # 默认

        try:
            # 从第一个主机检测
            first_host = hosts_info[0].get("hostname", "")
            devices = hosts_info[0].get("devices", [])

            if first_host and devices:
                info = self.rdma_detector.detect_device_type(first_host, devices[0])
                device_type = str(info.device_type)
                if "infiniband" in device_type.lower():
                    return "InfiniBand"
                elif "roce" in device_type.lower():
                    return "RoCE"

        except Exception as e:
            logger.debug(f"检测设备类型失败: {e}")

        return "RoCE"

    def _generate_device_stats(self, report: ThreePhaseReport,
                               hosts: List[HostDevices]) -> Dict[str, Dict[str, DeviceTestStats]]:
        """
        生成设备测试统计

        Args:
            report: 测试报告
            hosts: 主机列表

        Returns:
            设备统计字典
        """
        device_stats = {}

        # 初始化所有设备统计
        for host in hosts:
            device_stats[host.hostname] = {}
            for device in host.devices:
                device_stats[host.hostname][device] = DeviceTestStats()

        # 收集每轮测试结果
        for phase_result in [report.round1, report.round2, report.round3]:
            if not phase_result:
                continue

            phase_name = {
                TestPhase.ROUND_1: "第一轮",
                TestPhase.ROUND_2: "第二轮",
                TestPhase.ROUND_3: "第三轮"
            }.get(phase_result.phase, "未知")

            for item in phase_result.results:
                result = item.get("result", {})
                pair = item.get("pair", {})

                server_host = pair.get("server_host", "")
                server_device = pair.get("server_device", "")
                client_host = pair.get("client_host", "")
                client_device = pair.get("client_device", "")

                success = result.get("success", False)
                bandwidth = result.get("bandwidth_gbps", 0)
                bandwidth_percent = result.get("bandwidth_percent", 0)
                error_msg = result.get("error_message", "") or "未知错误"

                # 更新服务器端设备统计
                if server_host in device_stats and server_device in device_stats[server_host]:
                    stats = device_stats[server_host][server_device]
                    stats.test_count += 1
                    if not success:
                        stats.fail_count += 1
                        if bandwidth > 0:
                            detail = f"[{phase_name}] {server_device} <-> {client_host}:{client_device}: 带宽 {bandwidth:.1f} Gbps ({bandwidth_percent:.0f}%) 低于阈值"
                        else:
                            detail = f"[{phase_name}] {server_device} <-> {client_host}:{client_device}: {error_msg}"
                        stats.error_details.append(detail)

                # 更新客户端设备统计
                if client_host in device_stats and client_device in device_stats[client_host]:
                    stats = device_stats[client_host][client_device]
                    stats.test_count += 1
                    if not success:
                        stats.fail_count += 1
                        if bandwidth > 0:
                            detail = f"[{phase_name}] {client_device} <-> {server_host}:{server_device}: 带宽 {bandwidth:.1f} Gbps ({bandwidth_percent:.0f}%) 低于阈值"
                        else:
                            detail = f"[{phase_name}] {client_device} <-> {server_host}:{server_device}: {error_msg}"
                        stats.error_details.append(detail)

        return device_stats

    def _determine_final_status(self, report: ThreePhaseReport,
                                 hosts: List[HostDevices]) -> Dict[str, Dict[str, DeviceStatus]]:
        """
        确定最终设备状态

        Args:
            report: 测试报告
            hosts: 主机列表

        Returns:
            设备状态字典 {hostname: {device: status}}
        """
        final_status = {}

        # 初始化所有设备状态为未知
        for host in hosts:
            final_status[host.hostname] = {}
            for device in host.devices:
                final_status[host.hostname][device] = DeviceStatus.UNKNOWN

        # 统计每个设备在所有轮次中失败的次数
        device_fail_count = {}  # {hostname: {device: fail_count}}

        for host in hosts:
            device_fail_count[host.hostname] = {d: 0 for d in host.devices}

        # 根据第一轮结果更新
        if report.round1 and report.round1.abnormal_devices:
            for hostname, devices in report.round1.abnormal_devices.items():
                for device in devices:
                    if hostname in device_fail_count and device in device_fail_count[hostname]:
                        device_fail_count[hostname][device] += 1
                        logger.debug(f"[Round1] {hostname}:{device} fail_count = {device_fail_count[hostname][device]}")

        # 根据第二轮结果更新
        if report.round2 and report.round2.abnormal_devices:
            for hostname, devices in report.round2.abnormal_devices.items():
                for device in devices:
                    if hostname in device_fail_count and device in device_fail_count[hostname]:
                        device_fail_count[hostname][device] += 1
                        logger.debug(f"[Round2] {hostname}:{device} fail_count = {device_fail_count[hostname][device]}")

        # 根据第三轮结果更新
        if report.round3 and report.round3.abnormal_devices:
            for hostname, devices in report.round3.abnormal_devices.items():
                for device in devices:
                    if hostname in device_fail_count and device in device_fail_count[hostname]:
                        device_fail_count[hostname][device] += 1
                        logger.debug(f"[Round3] {hostname}:{device} fail_count = {device_fail_count[hostname][device]}")

        # 计算执行的轮次数
        rounds_executed = sum([
            1 if report.round1 else 0,
            1 if report.round2 else 0,
            1 if report.round3 else 0
        ])

        logger.debug(f"Rounds executed: {rounds_executed}")
        logger.debug(f"Device fail counts: {device_fail_count}")

        # 根据失败次数确定状态
        for hostname, devices in device_fail_count.items():
            for device, fail_count in devices.items():
                if fail_count == 0:
                    final_status[hostname][device] = DeviceStatus.NORMAL
                elif fail_count >= rounds_executed:
                    # 所有轮次都失败，标记为异常
                    final_status[hostname][device] = DeviceStatus.ABNORMAL
                elif fail_count >= 2:
                    # 多轮失败，标记为异常
                    final_status[hostname][device] = DeviceStatus.ABNORMAL
                else:
                    # 部分轮次失败，标记为疑似
                    final_status[hostname][device] = DeviceStatus.SUSPECTED
                logger.debug(f"Final status: {hostname}:{device} = {final_status[hostname][device]} (fail_count={fail_count})")

        return final_status

    def _generate_summary(self, report: ThreePhaseReport) -> Dict:
        """
        生成测试摘要

        Args:
            report: 测试报告

        Returns:
            摘要字典
        """
        total_hosts = len(report.hosts)
        total_devices = sum(len(h.devices) for h in report.hosts)

        abnormal_hosts = set()
        abnormal_devices = []
        suspected_devices = []
        normal_devices = []

        for hostname, devices in report.final_status.items():
            for device, status in devices.items():
                if status == DeviceStatus.ABNORMAL:
                    abnormal_hosts.add(hostname)
                    abnormal_devices.append(f"{hostname}:{device}")
                elif status == DeviceStatus.SUSPECTED:
                    suspected_devices.append(f"{hostname}:{device}")
                elif status == DeviceStatus.NORMAL:
                    normal_devices.append(f"{hostname}:{device}")

        return {
            "total_hosts": total_hosts,
            "total_devices": total_devices,
            "normal_hosts": total_hosts - len(abnormal_hosts),
            "abnormal_hosts": len(abnormal_hosts),
            "normal_devices": len(normal_devices),
            "suspected_devices": len(suspected_devices),
            "abnormal_devices": len(abnormal_devices),
            "abnormal_device_list": abnormal_devices,
            "suspected_device_list": suspected_devices,
            "all_normal": len(abnormal_hosts) == 0 and len(suspected_devices) == 0,
            "rounds_executed": sum([
                1 if report.round1 else 0,
                1 if report.round2 else 0,
                1 if report.round3 else 0
            ])
        }

    def generate_markdown_report(self, report: ThreePhaseReport) -> str:
        """
        生成Markdown格式的测试报告

        Args:
            report: 测试报告

        Returns:
            Markdown格式字符串
        """
        lines = [
            "# RDMA网络测试报告\n",
            "## 测试配置\n",
            f"- 网络类型: {report.network_type}",
            f"- 设备类型: {report.device_type} (自动检测)",
            f"- 理论带宽: {report.theoretical_bandwidth_gbps} Gbps",
        ]

        # 测试参数
        test_config = report.test_config or {}
        lines.append(f"- 测试参数: duration={test_config.get('duration', 10)}s, "
                    f"size={test_config.get('size', 65536)}, "
                    f"min_bandwidth={test_config.get('min_bandwidth_percent', 90)}%")
        lines.append("")

        # 测试摘要
        lines.extend([
            "## ib_write_bw 带宽测试摘要\n",
            f"- 总主机数: {report.summary.get('total_hosts', 0)}",
            f"- 总设备数: {report.summary.get('total_devices', 0)}",
            f"- 正常设备: {report.summary.get('normal_devices', 0)}",
            f"- 疑似设备: {report.summary.get('suspected_devices', 0)}",
            f"- 异常设备: {report.summary.get('abnormal_devices', 0)}",
            f"- 执行轮次: {report.summary.get('rounds_executed', 0)}",
            "",
        ])

        # 异常设备详情
        if report.summary.get('abnormal_devices', 0) > 0 or report.summary.get('suspected_devices', 0) > 0:
            lines.append("## 异常设备详情\n")

            for device in report.summary.get('abnormal_device_list', []):
                parts = device.split(':')
                if len(parts) == 2:
                    hostname, dev = parts
                    stats = report.device_stats.get(hostname, {}).get(dev)
                    if stats:
                        lines.append(f"✗ **{device}** - 两轮测试均失败")
                        for detail in stats.error_details:
                            lines.append(f"  {detail}")
                        lines.append("")

            for device in report.summary.get('suspected_device_list', []):
                parts = device.split(':')
                if len(parts) == 2:
                    hostname, dev = parts
                    stats = report.device_stats.get(hostname, {}).get(dev)
                    if stats:
                        lines.append(f"? **{device}** - 部分测试失败")
                        for detail in stats.error_details:
                            lines.append(f"  {detail}")
                        lines.append("")

        # 测试详情 - 每对设备的带宽结果
        lines.append("## 测试详情 (每对设备的带宽结果)\n")

        for phase_result, phase_key in [(report.round1, "round1"), (report.round2, "round2"), (report.round3, "round3")]:
            if not phase_result:
                continue

            phase_name = {
                TestPhase.ROUND_1: "第一轮 (相邻配对)",
                TestPhase.ROUND_2: "第二轮 (错位配对)",
                TestPhase.ROUND_3: "第三轮 (异常定位)"
            }.get(phase_result.phase, "未知")

            # 提取配对描述
            pair_desc = ""
            if phase_result.pairs:
                first_pair = phase_result.pairs[0]
                if phase_key == "round1":
                    pair_desc = f"{first_pair.server_host}-{first_pair.client_host}"
                elif phase_key == "round2":
                    pair_desc = f"{first_pair.server_host}-{first_pair.client_host}"

            lines.append(f"**{phase_name}**" + (f": {pair_desc}" if pair_desc else "") + ":\n")

            for item in phase_result.results:
                result = item.get("result", {})
                pair = item.get("pair", {})

                server_host = pair.get("server_host", "")
                client_host = pair.get("client_host", "")
                server_device = pair.get("server_device", "")
                client_device = pair.get("client_device", "")
                success = result.get("success", False)
                bandwidth = result.get("bandwidth_gbps", 0)
                bandwidth_percent = result.get("bandwidth_percent", 0)
                error_msg = result.get("error_message", "")

                if success:
                    lines.append(f"  {server_host}:{server_device} <-> {client_host}:{client_device}: "
                               f"{bandwidth:.1f} Gbps ({bandwidth_percent:.1f}%) ✓")
                else:
                    if bandwidth > 0:
                        lines.append(f"  {server_host}:{server_device} <-> {client_host}:{client_device}: "
                                   f"带宽 {bandwidth:.1f} Gbps ({bandwidth_percent:.1f}%) 低于阈值 ✗")
                    else:
                        lines.append(f"  {server_host}:{server_device} <-> {client_host}:{client_device}: "
                                   f"失败 - {error_msg} ✗")

            lines.append("")

        # 设备状态详情表
        lines.append("## 设备状态详情\n")
        lines.append("| 主机 | 设备 | 状态 | 测试次数 | 失败次数 |")
        lines.append("|------|------|------|----------|----------|")

        for hostname, devices in sorted(report.final_status.items()):
            for device, status in sorted(devices.items()):
                stats = report.device_stats.get(hostname, {}).get(device)
                test_count = stats.test_count if stats else 0
                fail_count = stats.fail_count if stats else 0

                status_str = "✓ 正常" if status == DeviceStatus.NORMAL else \
                            "✗ 异常" if status == DeviceStatus.ABNORMAL else \
                            "? 疑似" if status == DeviceStatus.SUSPECTED else \
                            "- 未知"
                lines.append(f"| {hostname} | {device} | {status_str} | {test_count} | {fail_count} |")

        return "\n".join(lines)
