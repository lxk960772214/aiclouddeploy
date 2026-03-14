"""
ib_write_bw性能测试器 - 封装ib_write_bw带宽测试
"""

import logging
import re
import time
import threading
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Tuple, TYPE_CHECKING
from concurrent.futures import ThreadPoolExecutor, as_completed

if TYPE_CHECKING:
    from src.ssh_manager import SSHManager
    from src.network.rdma_detector import RDMADetector, RDMADeviceType

logger = logging.getLogger(__name__)


@dataclass
class BandwidthTestResult:
    """带宽测试结果"""
    success: bool
    server_host: str
    client_host: str
    server_device: str
    client_device: str
    port: int
    bandwidth_gbps: float = 0.0
    bandwidth_percent: float = 0.0
    theoretical_bandwidth_gbps: float = 0.0
    duration: float = 0.0
    error_message: str = ""
    raw_output: str = ""
    test_command: str = ""  # 实际执行的测试命令
    device_type: str = ""   # 设备类型 (roce/infiniband)

    def to_dict(self) -> Dict:
        return {
            "success": self.success,
            "server_host": self.server_host,
            "client_host": self.client_host,
            "server_device": self.server_device,
            "client_device": self.client_device,
            "port": self.port,
            "bandwidth_gbps": round(self.bandwidth_gbps, 2),
            "bandwidth_percent": round(self.bandwidth_percent, 2),
            "theoretical_bandwidth_gbps": self.theoretical_bandwidth_gbps,
            "duration": round(self.duration, 2),
            "error_message": self.error_message,
            "test_command": self.test_command,
            "device_type": self.device_type
        }


@dataclass
class BandwidthTestConfig:
    """带宽测试配置"""
    duration: int = 10
    size: int = 65536
    port_base: int = 18500
    min_bandwidth_percent: float = 90.0
    timeout: int = 120
    theoretical_bandwidth_gbps: float = 400.0


class IBWriteBWTester:
    """ib_write_bw带宽测试器

    支持RoCE和InfiniBand两种模式的带宽测试
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
        self._port_lock = threading.Lock()
        self._current_port = None

    def calculate_port(self, device: str, port_base: int = 18500) -> int:
        """
        根据设备名称计算唯一端口号

        避免并发测试时的端口冲突

        Args:
            device: RDMA设备名称 (如 mlx5_0, mlx5_1)
            port_base: 基础端口号

        Returns:
            计算出的端口号
        """
        # 从设备名中提取最后一个数字 (如 mlx5_0 -> 0, mlx5_1 -> 1)
        matches = re.findall(r'(\d+)', device)
        if matches:
            # 使用最后一个数字作为设备编号
            device_num = int(matches[-1])
        else:
            # 如果没有数字，使用稳定的hash生成
            device_num = int.from_bytes(device.encode(), 'little') % 1000

        return port_base + device_num * 10

    def test_bandwidth(self, server_host: str, client_host: str,
                       server_device: str, client_device: str,
                       config: Optional[BandwidthTestConfig] = None) -> BandwidthTestResult:
        """
        执行单次带宽测试

        Args:
            server_host: 服务器主机
            client_host: 客户端主机
            server_device: 服务器RDMA设备
            client_device: 客户端RDMA设备
            config: 测试配置

        Returns:
            BandwidthTestResult对象
        """
        if config is None:
            config = BandwidthTestConfig()

        port = self.calculate_port(server_device, config.port_base)

        result = BandwidthTestResult(
            success=False,
            server_host=server_host,
            client_host=client_host,
            server_device=server_device,
            client_device=client_device,
            port=port,
            theoretical_bandwidth_gbps=config.theoretical_bandwidth_gbps
        )

        if not self.ssh_manager:
            result.error_message = "SSH管理器未初始化"
            return result

        try:
            # 检测设备类型
            device_type = self._get_device_type(server_host, server_device)

            # 构建命令
            if device_type == "infiniband":
                # InfiniBand 模式
                server_cmd = (
                    f"ib_write_bw -d {server_device} -F -s {config.size} "
                    f"-D {config.duration} -p {port}"
                )
                client_cmd = (
                    f"ib_write_bw -d {client_device} -F -s {config.size} "
                    f"-D {config.duration} -p {port} {server_host}"
                )
            else:
                # RoCE 模式 - 使用 -x 3 指定 GID index
                # -x 3 是 RoCEv2 的标准 GID index
                # 不使用 -R 参数，直接使用以太网链路层
                server_cmd = (
                    f"ib_write_bw -d {server_device} -x 3 -F -s {config.size} "
                    f"-D {config.duration} -p {port}"
                )
                client_cmd = (
                    f"ib_write_bw -d {client_device} -x 3 -F -s {config.size} "
                    f"-D {config.duration} -p {port} {server_host}"
                )

            # 记录测试命令和设备类型
            result.test_command = client_cmd
            result.device_type = device_type

            logger.debug(f"[{server_host}] 启动服务器: {server_cmd}")
            logger.debug(f"[{client_host}] 启动客户端: {client_cmd}")

            # 启动服务器（后台运行）
            server_thread = threading.Thread(
                target=self._run_server,
                args=(server_host, server_cmd, config.timeout)
            )
            server_thread.start()

            # 等待服务器启动
            time.sleep(2)

            # 启动客户端
            start_time = time.time()
            client_result = self.ssh_manager.execute_on_host(
                client_host, client_cmd, timeout=config.timeout
            )
            duration = time.time() - start_time

            # 等待服务器线程结束
            server_thread.join(timeout=5)

            result.duration = duration
            result.raw_output = client_result.stdout

            if not client_result.success:
                result.error_message = f"客户端执行失败: {client_result.stderr}"
                return result

            # 解析带宽结果
            bandwidth = self._parse_bandwidth(client_result.stdout)
            if bandwidth is not None:
                result.bandwidth_gbps = bandwidth
                if config.theoretical_bandwidth_gbps > 0:
                    result.bandwidth_percent = (bandwidth / config.theoretical_bandwidth_gbps) * 100
                result.success = result.bandwidth_percent >= config.min_bandwidth_percent
                if not result.success:
                    if bandwidth > 0:
                        result.error_message = f"带宽 {bandwidth:.1f} Gbps ({result.bandwidth_percent:.1f}%) 低于阈值 {config.min_bandwidth_percent}%"
                    else:
                        result.error_message = "带宽为0，测试未产生有效数据"
            else:
                result.error_message = "无法解析带宽结果"

            return result

        except Exception as e:
            result.error_message = f"测试异常: {e}"
            logger.error(f"带宽测试异常: {e}")
            return result

    def _run_server(self, host: str, command: str, timeout: int):
        """运行服务器命令"""
        try:
            self.ssh_manager.execute_on_host(host, command, timeout=timeout)
        except Exception as e:
            logger.debug(f"服务器命令结束 [{host}]: {e}")

    def _get_device_type(self, host: str, device: str) -> str:
        """获取设备类型"""
        if self.rdma_detector:
            info = self.rdma_detector.detect_device_type(host, device)
            return str(info.device_type)
        return "roce"  # 默认使用RoCE模式

    def _parse_bandwidth(self, output: str) -> Optional[float]:
        """
        解析ib_write_bw输出，提取带宽值

        输出格式示例:
        #bytes     #iterations    BW peak[MB/sec]    BW average[MB/sec]   MsgRate[Mpps]
        65536      1121952          0.00               11684.41            0.186951

        或者简单格式:
        #bytes     #iterations    BW peak[MB/sec]    BW average[MB/sec]
        65536      1000           48000.00           47500.00

        Returns:
            带宽值(Gbps)，如果解析失败返回None
        """
        try:
            lines = output.strip().split('\n')

            # 方法1: 查找包含数字的数据行（以数字开头）
            for line in reversed(lines):
                line = line.strip()
                # 跳过空行和标题行
                if not line or line.startswith('#') or line.startswith('-'):
                    continue

                parts = line.split()
                # 数据行通常有 4-6 列: #bytes, #iterations, BW peak, BW average, [MsgRate]
                if len(parts) >= 4:
                    try:
                        # 第一列应该是 bytes (整数)
                        int(parts[0])
                        # 第四列 (index 3) 是 BW average[MB/sec]
                        bandwidth_mbps = float(parts[3])
                        if bandwidth_mbps > 0:
                            # 转换为Gbps (MB/s * 8 / 1000 = Gbps)
                            bandwidth_gbps = bandwidth_mbps * 8 / 1000
                            return bandwidth_gbps
                    except (ValueError, IndexError):
                        continue

            # 方法2: 尝试匹配特定格式
            # 查找 BW average 列
            for line in lines:
                if 'BW average' in line or 'BW peak' in line:
                    # 这可能是标题行，下一行是数据
                    continue

            return None

        except Exception as e:
            logger.error(f"解析带宽输出失败: {e}")
            return None

    def test_pair(self, host1: str, host2: str,
                  device1: str, device2: str,
                  config: Optional[BandwidthTestConfig] = None,
                  bidirectional: bool = True) -> List[BandwidthTestResult]:
        """
        测试一对主机之间的带宽

        Args:
            host1: 主机1
            host2: 主机2
            device1: 主机1的RDMA设备
            device2: 主机2的RDMA设备
            config: 测试配置
            bidirectional: 是否双向测试

        Returns:
            测试结果列表
        """
        results = []

        # host1作为服务器，host2作为客户端
        result1 = self.test_bandwidth(host1, host2, device1, device2, config)
        results.append(result1)

        if bidirectional:
            # host2作为服务器，host1作为客户端
            result2 = self.test_bandwidth(host2, host1, device2, device1, config)
            results.append(result2)

        return results

    def test_concurrent(self, test_pairs: List[Tuple[str, str, str, str]],
                        config: Optional[BandwidthTestConfig] = None,
                        max_workers: int = 4) -> List[BandwidthTestResult]:
        """
        并发测试多对主机

        注意：为了避免资源竞争，同一台主机不会同时参与多个测试。
        测试会按组执行，每组中的主机互不重叠。

        Args:
            test_pairs: 测试对列表 [(server_host, client_host, server_device, client_device), ...]
            config: 测试配置
            max_workers: 最大并发数（用于不同主机组的并发）

        Returns:
            测试结果列表
        """
        results = []

        # 将测试对分组，确保同一组内主机不重叠
        test_groups = self._group_non_overlapping_tests(test_pairs)

        logger.info(f"将 {len(test_pairs)} 个测试分为 {len(test_groups)} 组执行（避免主机资源竞争）")

        for group_idx, group in enumerate(test_groups):
            logger.debug(f"执行第 {group_idx + 1}/{len(test_groups)} 组测试，共 {len(group)} 个")

            # 同一组内的测试可以并发执行（因为主机不重叠）
            with ThreadPoolExecutor(max_workers=min(max_workers, len(group))) as executor:
                futures = {
                    executor.submit(
                        self.test_bandwidth, server, client, sdev, cdev, config
                    ): (server, client, sdev, cdev)
                    for server, client, sdev, cdev in group
                }

                group_results = {}
                for future in as_completed(futures):
                    try:
                        result = future.result()
                        pair = futures[future]
                        group_results[pair] = result
                    except Exception as e:
                        pair = futures[future]
                        logger.error(f"测试 {pair} 异常: {e}")
                        group_results[pair] = BandwidthTestResult(
                            success=False,
                            server_host=pair[0],
                            client_host=pair[1],
                            server_device=pair[2],
                            client_device=pair[3],
                            port=0,
                            error_message=str(e)
                        )

                # 按原始顺序添加结果
                for pair in group:
                    results.append(group_results.get(pair))

        return results

    def _group_non_overlapping_tests(self, test_pairs: List[Tuple[str, str, str, str]]) -> List[List[Tuple[str, str, str, str]]]:
        """
        将测试对分组，确保同一组内主机不重叠

        这样可以避免同一台主机同时参与多个测试，防止资源竞争

        Args:
            test_pairs: 测试对列表

        Returns:
            分组后的测试列表
        """
        if not test_pairs:
            return []

        groups = []

        for pair in test_pairs:
            server_host, client_host = pair[0], pair[1]

            # 查找可以添加该测试的组（组内没有使用相同主机）
            found_group = None
            for group in groups:
                hosts_in_group = set()
                for p in group:
                    hosts_in_group.add(p[0])  # server
                    hosts_in_group.add(p[1])  # client

                # 如果该组没有使用 server_host 和 client_host，可以添加
                if server_host not in hosts_in_group and client_host not in hosts_in_group:
                    found_group = group
                    break

            if found_group:
                found_group.append(pair)
            else:
                # 创建新组
                groups.append([pair])

        return groups

    def test_all_devices(self, host1: str, host2: str,
                         devices1: List[str], devices2: List[str],
                         config: Optional[BandwidthTestConfig] = None,
                         concurrent: bool = True,
                         max_workers: int = 4) -> Dict[str, BandwidthTestResult]:
        """
        测试两个主机之间所有设备对的带宽

        Args:
            host1: 主机1
            host2: 主机2
            devices1: 主机1的设备列表
            devices2: 主机2的设备列表
            config: 测试配置
            concurrent: 是否并发测试
            max_workers: 最大并发数

        Returns:
            结果字典 {(device1, device2): result}
        """
        results = {}

        if len(devices1) != len(devices2):
            logger.warning(f"设备数量不匹配: {host1}有{len(devices1)}个, {host2}有{len(devices2)}个")
            # 使用较小的数量
            min_count = min(len(devices1), len(devices2))
            devices1 = devices1[:min_count]
            devices2 = devices2[:min_count]

        if concurrent:
            test_pairs = [(host1, host2, d1, d2) for d1, d2 in zip(devices1, devices2)]
            test_results = self.test_concurrent(test_pairs, config, max_workers)
            for i, result in enumerate(test_results):
                key = f"{devices1[i]}-{devices2[i]}"
                results[key] = result
        else:
            for d1, d2 in zip(devices1, devices2):
                result = self.test_bandwidth(host1, host2, d1, d2, config)
                key = f"{d1}-{d2}"
                results[key] = result

        return results

    def check_tool_available(self, host: str) -> bool:
        """
        检查ib_write_bw工具是否可用

        Args:
            host: 主机名或IP

        Returns:
            工具是否可用
        """
        if not self.ssh_manager:
            return False

        try:
            result = self.ssh_manager.execute_on_host(
                host, "which ib_write_bw", timeout=10
            )
            return result.success and result.stdout.strip()
        except Exception:
            return False

    def get_summary(self, results: List[BandwidthTestResult]) -> Dict:
        """
        生成测试结果摘要

        Args:
            results: 测试结果列表

        Returns:
            摘要字典
        """
        if not results:
            return {
                "total": 0,
                "success": 0,
                "failed": 0,
                "success_rate": 0,
                "avg_bandwidth_gbps": 0,
                "min_bandwidth_gbps": 0,
                "max_bandwidth_gbps": 0
            }

        success_results = [r for r in results if r.success]
        bandwidths = [r.bandwidth_gbps for r in success_results if r.bandwidth_gbps > 0]

        return {
            "total": len(results),
            "success": len(success_results),
            "failed": len(results) - len(success_results),
            "success_rate": round(len(success_results) / len(results) * 100, 2) if results else 0,
            "avg_bandwidth_gbps": round(sum(bandwidths) / len(bandwidths), 2) if bandwidths else 0,
            "min_bandwidth_gbps": round(min(bandwidths), 2) if bandwidths else 0,
            "max_bandwidth_gbps": round(max(bandwidths), 2) if bandwidths else 0
        }
