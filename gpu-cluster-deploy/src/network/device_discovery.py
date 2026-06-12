"""
设备发现工具类
通过SSH发现节点上的RDMA设备和以太网设备序列
"""

import re
from typing import List, Dict, Any, Optional, Callable
from datetime import datetime

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from models.device_check import (
    DeviceInfo, DeviceType, NodeDeviceSnapshot
)


class DeviceDiscovery:
    """设备发现工具类"""

    def __init__(self, execute_func: Optional[Callable] = None):
        """
        初始化设备发现器

        Args:
            execute_func: 执行远程命令的函数，签名为 (host: str, command: str) -> Dict
        """
        self.execute_func = execute_func

    def discover_node_devices(self, hostname: str) -> NodeDeviceSnapshot:
        """
        发现指定节点的所有设备

        Args:
            hostname: 节点主机名或IP

        Returns:
            NodeDeviceSnapshot: 节点设备快照
        """
        snapshot = NodeDeviceSnapshot(
            hostname=hostname,
            timestamp=datetime.now().isoformat()
        )

        try:
            # 发现RDMA设备
            snapshot.rdma_devices = self._discover_rdma_devices(hostname)

            # 发现以太网设备
            snapshot.ethernet_devices = self._discover_ethernet_devices(hostname)

            # 发现GPU设备
            snapshot.gpu_devices = self._discover_gpu_devices(hostname)

            # 发现NVMe设备
            snapshot.nvme_devices = self._discover_nvme_devices(hostname)

        except Exception as e:
            snapshot.errors.append(f"设备发现失败: {str(e)}")

        return snapshot

    def _discover_rdma_devices(self, hostname: str) -> List[DeviceInfo]:
        """发现RDMA设备 (mlx5_*)"""
        devices = []

        # 获取RDMA设备列表
        result = self._execute(hostname, "ls -1 /sys/class/infiniband/ 2>/dev/null || true")
        if not result.get("success"):
            return devices

        rdma_names = result.get("stdout", "").strip().split("\n")
        rdma_names = [n.strip() for n in rdma_names if n.strip()]

        for name in rdma_names:
            device = DeviceInfo(
                name=name,
                device_type=DeviceType.RDMA
            )

            # 获取PCI地址
            pci_path = f"/sys/class/infiniband/{name}/device"
            pci_result = self._execute(hostname, f"readlink -f {pci_path} 2>/dev/null | xargs basename")
            if pci_result.get("success"):
                device.pci_address = pci_result.get("stdout", "").strip()

            # 获取固件版本
            fw_result = self._execute(hostname, f"cat /sys/class/infiniband/{name}/fw_ver 2>/dev/null || true")
            if fw_result.get("success"):
                device.firmware = fw_result.get("stdout", "").strip()

            # 获取NUMA节点
            if device.pci_address:
                numa_result = self._execute(
                    hostname,
                    f"cat /sys/bus/pci/devices/{device.pci_address}/numa_node 2>/dev/null || echo -1"
                )
                if numa_result.get("success"):
                    try:
                        device.numa_node = int(numa_result.get("stdout", "-1").strip())
                    except ValueError:
                        device.numa_node = -1

            # 获取端口数量
            ports_result = self._execute(hostname, f"ls -1 /sys/class/infiniband/{name}/ports/ 2>/dev/null || true")
            if ports_result.get("success"):
                ports = ports_result.get("stdout", "").strip().split("\n")
                ports = [p.strip() for p in ports if p.strip()]
                if ports:
                    device.port = int(ports[0]) if len(ports) == 1 else len(ports)

            devices.append(device)

        return devices

    def _discover_ethernet_devices(self, hostname: str) -> List[DeviceInfo]:
        """发现以太网设备 (ens*, eth*)"""
        devices = []

        # 获取所有网络接口
        result = self._execute(hostname, "ls -1 /sys/class/net/ 2>/dev/null || true")
        if not result.get("success"):
            return devices

        net_interfaces = result.get("stdout", "").strip().split("\n")
        net_interfaces = [n.strip() for n in net_interfaces if n.strip()]

        # 过滤以太网设备 (排除lo, docker, veth等)
        ethernet_pattern = re.compile(r'^(ens|eth|enp|eno|em)\d+')

        for iface in net_interfaces:
            if not ethernet_pattern.match(iface):
                continue

            device = DeviceInfo(
                name=iface,
                device_type=DeviceType.ETHERNET
            )

            # 获取PCI地址
            pci_path = f"/sys/class/net/{iface}/device"
            pci_result = self._execute(hostname, f"readlink -f {pci_path} 2>/dev/null | xargs basename 2>/dev/null || true")
            if pci_result.get("success") and pci_result.get("stdout", "").strip():
                device.pci_address = pci_result.get("stdout", "").strip()

            # 获取驱动
            driver_result = self._execute(hostname, f"readlink -f /sys/class/net/{iface}/device/driver 2>/dev/null | xargs basename 2>/dev/null || true")
            if driver_result.get("success"):
                device.driver = driver_result.get("stdout", "").strip()

            # 获取MTU
            mtu_result = self._execute(hostname, f"cat /sys/class/net/{iface}/mtu 2>/dev/null || true")
            if mtu_result.get("success"):
                try:
                    device.mtu = int(mtu_result.get("stdout", "0").strip())
                except ValueError:
                    pass

            # 获取状态
            state_result = self._execute(hostname, f"cat /sys/class/net/{iface}/operstate 2>/dev/null || true")
            if state_result.get("success"):
                device.state = state_result.get("stdout", "").strip()

            # 获取速度
            speed_result = self._execute(hostname, f"cat /sys/class/net/{iface}/speed 2>/dev/null || true")
            if speed_result.get("success"):
                speed = speed_result.get("stdout", "").strip()
                if speed and speed != "Unknown":
                    device.speed = speed

            devices.append(device)

        return devices

    def _discover_gpu_devices(self, hostname: str) -> List[DeviceInfo]:
        """发现GPU设备"""
        devices = []

        # 使用nvidia-smi获取GPU信息
        result = self._execute(
            hostname,
            "nvidia-smi --query-gpu=index,name,pci.bus_id,driver_version --format=csv,noheader 2>/dev/null || true"
        )
        if not result.get("success"):
            return devices

        lines = result.get("stdout", "").strip().split("\n")
        for line in lines:
            if not line.strip():
                continue

            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 3:
                try:
                    device = DeviceInfo(
                        name=f"GPU{parts[0]}",
                        device_type=DeviceType.GPU,
                        pci_address=parts[2] if len(parts) > 2 else None,
                        driver=parts[3] if len(parts) > 3 else None,
                        extra_info={"gpu_name": parts[1] if len(parts) > 1 else "Unknown"}
                    )

                    # 获取NUMA节点
                    if device.pci_address:
                        numa_result = self._execute(
                            hostname,
                            f"cat /sys/bus/pci/devices/{device.pci_address}/numa_node 2>/dev/null || echo -1"
                        )
                        if numa_result.get("success"):
                            try:
                                device.numa_node = int(numa_result.get("stdout", "-1").strip())
                            except ValueError:
                                device.numa_node = -1

                    devices.append(device)
                except (ValueError, IndexError):
                    continue

        return devices

    def _discover_nvme_devices(self, hostname: str) -> List[DeviceInfo]:
        """发现NVMe设备"""
        devices = []

        result = self._execute(hostname, "ls -1 /sys/class/nvme/ 2>/dev/null || true")
        if not result.get("success"):
            return devices

        nvme_names = result.get("stdout", "").strip().split("\n")
        nvme_names = [n.strip() for n in nvme_names if n.strip()]

        for name in nvme_names:
            device = DeviceInfo(
                name=name,
                device_type=DeviceType.NVME
            )

            # 获取PCI地址
            pci_result = self._execute(hostname, f"readlink -f /sys/class/nvme/{name}/device 2>/dev/null | xargs basename 2>/dev/null || true")
            if pci_result.get("success"):
                device.pci_address = pci_result.get("stdout", "").strip()

            # 获取固件版本
            fw_result = self._execute(hostname, f"cat /sys/class/nvme/{name}/firmware_rev 2>/dev/null || true")
            if fw_result.get("success"):
                device.firmware = fw_result.get("stdout", "").strip()

            # 获取NUMA节点
            if device.pci_address:
                numa_result = self._execute(
                    hostname,
                    f"cat /sys/bus/pci/devices/{device.pci_address}/numa_node 2>/dev/null || echo -1"
                )
                if numa_result.get("success"):
                    try:
                        device.numa_node = int(numa_result.get("stdout", "-1").strip())
                    except ValueError:
                        device.numa_node = -1

            devices.append(device)

        return devices

    def _execute(self, hostname: str, command: str) -> Dict[str, Any]:
        """
        执行远程命令

        Args:
            hostname: 目标主机
            command: 要执行的命令

        Returns:
            执行结果字典
        """
        if self.execute_func:
            return self.execute_func(hostname, command)

        # 如果没有提供执行函数，返回模拟结果
        return {
            "success": False,
            "stdout": "",
            "stderr": "No execute function provided",
            "error": "No execute function provided"
        }

    def get_ibdev2netdev_output(self, hostname: str) -> str:
        """
        获取ibdev2netdev命令输出

        Args:
            hostname: 目标主机

        Returns:
            ibdev2netdev命令的输出
        """
        result = self._execute(hostname, "ibdev2netdev 2>/dev/null || true")
        if result.get("success"):
            return result.get("stdout", "")
        return ""


def create_device_discovery(execute_func: Callable) -> DeviceDiscovery:
    """
    创建设备发现器实例

    Args:
        execute_func: 执行远程命令的函数

    Returns:
        DeviceDiscovery实例
    """
    return DeviceDiscovery(execute_func=execute_func)
