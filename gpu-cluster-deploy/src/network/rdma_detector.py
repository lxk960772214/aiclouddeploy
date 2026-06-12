"""
RDMA设备类型检测器 - 自动检测RoCE/InfiniBand设备类型
"""

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List, Dict, TYPE_CHECKING

if TYPE_CHECKING:
    from src.ssh_manager import SSHManager

logger = logging.getLogger(__name__)


class RDMADeviceType(Enum):
    """RDMA设备类型"""
    INFINIBAND = "infiniband"
    ROCE = "roce"
    ROCEV2 = "rocev2"
    UNKNOWN = "unknown"

    def __str__(self):
        return self.value


@dataclass
class RDMADeviceInfo:
    """RDMA设备信息"""
    device_name: str
    device_type: RDMADeviceType
    transport: str = ""
    state: str = ""
    physical_state: str = ""
    link_layer: str = ""
    netdev: str = ""
    port: int = 1
    rate: str = ""
    fw_ver: str = ""
    board_id: str = ""

    def to_dict(self) -> Dict:
        return {
            "device_name": self.device_name,
            "device_type": str(self.device_type),
            "transport": self.transport,
            "state": self.state,
            "physical_state": self.physical_state,
            "link_layer": self.link_layer,
            "netdev": self.netdev,
            "port": self.port,
            "rate": self.rate,
            "fw_ver": self.fw_ver,
            "board_id": self.board_id
        }


class RDMADetector:
    """RDMA设备类型检测器

    支持多种检测方法：
    1. /sys/class/infiniband/{device}/transport
    2. ibv_devinfo -v
    3. rdma link show
    """

    def __init__(self, ssh_manager: Optional["SSHManager"] = None):
        """
        初始化检测器

        Args:
            ssh_manager: SSH管理器实例
        """
        self.ssh_manager = ssh_manager

    def detect_device_type(self, host: str, device: str) -> RDMADeviceInfo:
        """
        检测RDMA设备类型

        Args:
            host: 主机名或IP
            device: RDMA设备名称

        Returns:
            RDMADeviceInfo对象
        """
        device_info = RDMADeviceInfo(
            device_name=device,
            device_type=RDMADeviceType.UNKNOWN
        )

        # 方法1: 通过sysfs检测
        if self._detect_via_sysfs(host, device, device_info):
            logger.debug(f"[{host}] {device}: 通过sysfs检测为 {device_info.device_type}")
            return device_info

        # 方法2: 通过ibv_devinfo检测
        if self._detect_via_ibv_devinfo(host, device, device_info):
            logger.debug(f"[{host}] {device}: 通过ibv_devinfo检测为 {device_info.device_type}")
            return device_info

        # 方法3: 通过rdma link检测
        if self._detect_via_rdma_link(host, device, device_info):
            logger.debug(f"[{host}] {device}: 通过rdma link检测为 {device_info.device_type}")
            return device_info

        logger.warning(f"[{host}] {device}: 无法确定设备类型")
        return device_info

    def _detect_via_sysfs(self, host: str, device: str, info: RDMADeviceInfo) -> bool:
        """通过sysfs检测设备类型

        关键判断：使用 link_layer 而不是 transport 来区分 InfiniBand 和 RoCE
        - link_layer: InfiniBand -> 真正的 InfiniBand 网络
        - link_layer: Ethernet -> RoCE (RDMA over Converged Ethernet)

        注意：transport 对于 RoCE 也会返回 "InfiniBand"，因为 RoCE 使用 IB 传输协议
        """
        if not self.ssh_manager:
            return False

        try:
            # 先读取 link_layer（关键判断依据）
            link_layer_cmd = f"cat /sys/class/infiniband/{device}/ports/1/link_layer 2>/dev/null"
            link_layer_result = self.ssh_manager.execute_on_host(host, link_layer_cmd, timeout=30)

            if link_layer_result.success and link_layer_result.stdout.strip():
                link_layer = link_layer_result.stdout.strip().lower()
                info.link_layer = link_layer

                # 根据 link_layer 判断设备类型
                if link_layer == "infiniband":
                    info.device_type = RDMADeviceType.INFINIBAND
                elif link_layer == "ethernet":
                    # Ethernet link_layer 表示 RoCE
                    info.device_type = RDMADeviceType.ROCE
                else:
                    info.device_type = RDMADeviceType.UNKNOWN

            # 读取 transport（补充信息）
            transport_cmd = f"cat /sys/class/infiniband/{device}/transport 2>/dev/null"
            transport_result = self.ssh_manager.execute_on_host(host, transport_cmd, timeout=30)

            if transport_result.success and transport_result.stdout.strip():
                info.transport = transport_result.stdout.strip().lower()

            # 读取更多设备信息
            self._read_sysfs_attrs(host, device, info)

            # 如果 link_layer 检测成功，返回 True
            if info.link_layer:
                return True

            return False

        except Exception as e:
            logger.error(f"[{host}] sysfs检测失败 {device}: {e}")
            return False

    def _read_sysfs_attrs(self, host: str, device: str, info: RDMADeviceInfo):
        """读取sysfs属性"""
        if not self.ssh_manager:
            return

        attrs = {
            "state": f"cat /sys/class/infiniband/{device}/ports/1/state 2>/dev/null",
            "physical_state": f"cat /sys/class/infiniband/{device}/ports/1/phys_state 2>/dev/null",
            "link_layer": f"cat /sys/class/infiniband/{device}/ports/1/link_layer 2>/dev/null",
            "rate": f"cat /sys/class/infiniband/{device}/ports/1/rate 2>/dev/null",
            "fw_ver": f"cat /sys/class/infiniband/{device}/fw_ver 2>/dev/null",
            "board_id": f"cat /sys/class/infiniband/{device}/board_id 2>/dev/null"
        }

        for attr, cmd in attrs.items():
            try:
                result = self.ssh_manager.execute_on_host(host, cmd, timeout=10)
                if result.success and result.stdout.strip():
                    setattr(info, attr, result.stdout.strip())
            except Exception:
                pass

    def _detect_via_ibv_devinfo(self, host: str, device: str, info: RDMADeviceInfo) -> bool:
        """通过ibv_devinfo检测设备类型"""
        if not self.ssh_manager:
            return False

        try:
            # 使用ibv_devinfo -v获取详细信息
            cmd = f"ibv_devinfo -v -d {device} 2>/dev/null"
            result = self.ssh_manager.execute_on_host(host, cmd, timeout=30)

            if not result.success or not result.stdout.strip():
                return False

            output = result.stdout

            # 解析transport
            transport_match = re.search(r'transport:\s+(\S+)', output, re.IGNORECASE)
            if transport_match:
                transport = transport_match.group(1).lower()
                info.transport = transport

                if transport == "infiniband":
                    info.device_type = RDMADeviceType.INFINIBAND
                elif "roce" in transport:
                    info.device_type = RDMADeviceType.ROCE

            # 解析link_layer
            link_layer_match = re.search(r'link_layer:\s+(\S+)', output, re.IGNORECASE)
            if link_layer_match:
                info.link_layer = link_layer_match.group(1).lower()

                # 通过link_layer进一步确认
                if info.device_type == RDMADeviceType.UNKNOWN:
                    if info.link_layer == "infiniband":
                        info.device_type = RDMADeviceType.INFINIBAND
                    elif info.link_layer == "ethernet":
                        info.device_type = RDMADeviceType.ROCE

            # 解析状态
            state_match = re.search(r'state:\s+(\S+)', output, re.IGNORECASE)
            if state_match:
                info.state = state_match.group(1)

            phys_state_match = re.search(r'physical_state:\s+(\S+)', output, re.IGNORECASE)
            if phys_state_match:
                info.physical_state = phys_state_match.group(1)

            # 解析速率
            rate_match = re.search(r'active_speed:\s+(.+?)(?:\n|$)', output, re.IGNORECASE)
            if rate_match:
                info.rate = rate_match.group(1).strip()

            # 解析固件版本
            fw_match = re.search(r'fw_ver:\s+(\S+)', output, re.IGNORECASE)
            if fw_match:
                info.fw_ver = fw_match.group(1)

            return info.device_type != RDMADeviceType.UNKNOWN

        except Exception as e:
            logger.error(f"[{host}] ibv_devinfo检测失败 {device}: {e}")
            return False

    def _detect_via_rdma_link(self, host: str, device: str, info: RDMADeviceInfo) -> bool:
        """通过rdma link检测设备类型"""
        if not self.ssh_manager:
            return False

        try:
            # 使用rdma link show获取信息
            cmd = f"rdma link show {device}/1 2>/dev/null"
            result = self.ssh_manager.execute_on_host(host, cmd, timeout=30)

            if not result.success or not result.stdout.strip():
                return False

            output = result.stdout

            # 解析netdev
            netdev_match = re.search(r'netdev\s+(\S+)', output)
            if netdev_match:
                info.netdev = netdev_match.group(1)

            # 解析状态
            state_match = re.search(r'state\s+(\S+)', output)
            if state_match:
                info.state = state_match.group(1)

            physical_state_match = re.search(r'physical_state\s+(\S+)', output)
            if physical_state_match:
                info.physical_state = physical_state_match.group(1)

            # 通过netdev进一步确认类型
            if info.netdev:
                # 检查是否有IB接口名
                if info.netdev.startswith('ib'):
                    info.device_type = RDMADeviceType.INFINIBAND
                else:
                    # 以太网接口，可能是RoCE
                    info.device_type = RDMADeviceType.ROCE

            return info.device_type != RDMADeviceType.UNKNOWN

        except Exception as e:
            logger.error(f"[{host}] rdma link检测失败 {device}: {e}")
            return False

    def get_all_devices(self, host: str) -> List[str]:
        """
        获取主机上所有RDMA设备

        Args:
            host: 主机名或IP

        Returns:
            RDMA设备名称列表
        """
        if not self.ssh_manager:
            return []

        try:
            # 方法1: 通过sysfs
            cmd = "ls /sys/class/infiniband/ 2>/dev/null"
            result = self.ssh_manager.execute_on_host(host, cmd, timeout=30)

            if result.success and result.stdout.strip():
                devices = [d.strip() for d in result.stdout.strip().split('\n') if d.strip()]
                if devices:
                    return devices

            # 方法2: 通过ibv_devices
            cmd = "ibv_devices 2>/dev/null | tail -n +2 | awk '{print $1}'"
            result = self.ssh_manager.execute_on_host(host, cmd, timeout=30)

            if result.success and result.stdout.strip():
                devices = [d.strip() for d in result.stdout.strip().split('\n') if d.strip()]
                return devices

            return []

        except Exception as e:
            logger.error(f"[{host}] 获取RDMA设备列表失败: {e}")
            return []

    def detect_all_devices(self, host: str) -> List[RDMADeviceInfo]:
        """
        检测主机上所有RDMA设备

        Args:
            host: 主机名或IP

        Returns:
            RDMADeviceInfo列表
        """
        devices = self.get_all_devices(host)
        results = []

        for device in devices:
            info = self.detect_device_type(host, device)
            results.append(info)

        return results

    def get_device_netdev(self, host: str, device: str) -> Optional[str]:
        """
        获取RDMA设备对应的网络接口

        Args:
            host: 主机名或IP
            device: RDMA设备名称

        Returns:
            网络接口名称
        """
        if not self.ssh_manager:
            return None

        try:
            # 方法1: 通过ibdev2netdev
            cmd = f"ibdev2netdev 2>/dev/null | grep {device}"
            result = self.ssh_manager.execute_on_host(host, cmd, timeout=30)

            if result.success and result.stdout.strip():
                # 解析: mlx5_0 port 1 ==> ib0
                match = re.search(r'=>\s+(\S+)', result.stdout)
                if match:
                    return match.group(1)

            # 方法2: 通过rdma link
            cmd = f"rdma link show {device}/1 2>/dev/null"
            result = self.ssh_manager.execute_on_host(host, cmd, timeout=30)

            if result.success and result.stdout.strip():
                match = re.search(r'netdev\s+(\S+)', result.stdout)
                if match:
                    return match.group(1)

            return None

        except Exception as e:
            logger.error(f"[{host}] 获取RDMA设备网络接口失败 {device}: {e}")
            return None

    def is_device_ready(self, host: str, device: str) -> bool:
        """
        检查RDMA设备是否就绪

        Args:
            host: 主机名或IP
            device: RDMA设备名称

        Returns:
            设备是否就绪
        """
        info = self.detect_device_type(host, device)

        # 检查状态
        if info.state.lower() in ['active', 'ib:active', '4']:
            return True

        if 'active' in info.state.lower():
            return True

        return False

    def get_device_by_netdev(self, host: str, netdev: str) -> Optional[str]:
        """
        根据网络接口名获取对应的RDMA设备

        Args:
            host: 主机名或IP
            netdev: 网络接口名称

        Returns:
            RDMA设备名称
        """
        if not self.ssh_manager:
            return None

        try:
            # 方法1: 通过ibdev2netdev
            cmd = f"ibdev2netdev 2>/dev/null | grep {netdev}"
            result = self.ssh_manager.execute_on_host(host, cmd, timeout=30)

            if result.success and result.stdout.strip():
                # 解析: mlx5_0 port 1 ==> ib0
                match = re.search(r'^(\S+)\s+port', result.stdout)
                if match:
                    return match.group(1)

            # 方法2: 通过rdma link
            cmd = f"rdma link show 2>/dev/null | grep 'netdev {netdev}'"
            result = self.ssh_manager.execute_on_host(host, cmd, timeout=30)

            if result.success and result.stdout.strip():
                match = re.search(r'link\s+(\S+)/', result.stdout)
                if match:
                    return match.group(1)

            return None

        except Exception as e:
            logger.error(f"[{host}] 获取RDMA设备失败 {netdev}: {e}")
            return None
