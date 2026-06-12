"""
IP解析器 - 根据网卡名称或网络类型获取IP地址
"""

import json
import logging
import re
from typing import Optional, List, Dict, TYPE_CHECKING

if TYPE_CHECKING:
    from src.models.cluster import NetworkConfig, NodeConfig

logger = logging.getLogger(__name__)


class IPResolver:
    """IP地址解析器

    提供根据网卡名称或网络类型获取IP地址的功能
    """

    def __init__(self, ssh_manager=None):
        """
        初始化IP解析器

        Args:
            ssh_manager: SSH管理器实例，用于远程执行命令
        """
        self.ssh_manager = ssh_manager

    def get_interface_ip(self, host: str, interface: str) -> Optional[str]:
        """
        获取指定主机上网卡的IP地址

        Args:
            host: 主机名或IP地址
            interface: 网卡名称

        Returns:
            IPv4地址字符串，如果未找到返回None
        """
        if not self.ssh_manager:
            logger.error("SSH管理器未初始化")
            return None

        try:
            # 使用 ip -j addr show 命令获取JSON格式的网卡信息
            cmd = f"ip -j addr show {interface} 2>/dev/null"
            result = self.ssh_manager.execute_on_host(host, cmd, timeout=30)

            if not result.success:
                logger.warning(f"获取网卡IP失败 [{host}] {interface}: {result.stderr}")
                return None

            # 解析JSON输出
            interfaces_info = json.loads(result.stdout)
            if not interfaces_info:
                return None

            # 提取IPv4地址
            for addr_info in interfaces_info:
                for addr in addr_info.get('addr_info', []):
                    if addr.get('family') == 'inet':
                        ip = addr.get('local')
                        if ip:
                            logger.debug(f"获取网卡IP成功 [{host}] {interface}: {ip}")
                            return ip

            return None

        except json.JSONDecodeError as e:
            logger.error(f"解析网卡信息JSON失败 [{host}] {interface}: {e}")
            return None
        except Exception as e:
            logger.error(f"获取网卡IP异常 [{host}] {interface}: {e}")
            return None

    def get_interface_ip_local(self, interface: str) -> Optional[str]:
        """
        获取本地网卡IP地址（不通过SSH）

        Args:
            interface: 网卡名称

        Returns:
            IPv4地址字符串，如果未找到返回None
        """
        import subprocess

        try:
            result = subprocess.run(
                ['ip', '-j', 'addr', 'show', interface],
                capture_output=True,
                text=True,
                timeout=10
            )

            if result.returncode != 0:
                return None

            interfaces_info = json.loads(result.stdout)
            if not interfaces_info:
                return None

            for addr_info in interfaces_info:
                for addr in addr_info.get('addr_info', []):
                    if addr.get('family') == 'inet':
                        return addr.get('local')

            return None

        except Exception as e:
            logger.error(f"获取本地网卡IP异常 {interface}: {e}")
            return None

    def get_network_ip(self, host: str, network_config: "NetworkConfig",
                       network_type: str) -> Optional[str]:
        """
        根据网络类型获取对应的IP地址

        优先使用新格式的配置，回退到旧格式

        Args:
            host: 主机名或IP地址
            network_config: 网络配置对象
            network_type: 网络类型 (management/compute/storage)

        Returns:
            IPv4地址字符串，如果未找到返回None
        """
        # 尝试从新格式获取
        interfaces = network_config.get_network_interfaces(network_type)
        if interfaces:
            for interface in interfaces:
                ip = self.get_interface_ip(host, interface)
                if ip:
                    logger.info(f"获取{network_type}网络IP [{host}]: {ip} (via {interface})")
                    return ip

        logger.warning(f"未找到{network_type}网络IP [{host}]")
        return None

    def get_ip_for_purpose(self, host: str, network_config: "NetworkConfig",
                           purpose: str) -> Optional[str]:
        """
        根据用途获取IP地址

        用途映射:
        - storage_nfs: 存储网IP（无则管理网IP）
        - package_transfer: 管理网IP
        - ssh_connection: 管理网IP
        - general: 管理网IP

        Args:
            host: 主机名或IP地址
            network_config: 网络配置对象
            purpose: 用途标识

        Returns:
            IPv4地址字符串，如果未找到返回None
        """
        if purpose == "storage_nfs":
            # 优先使用存储网IP
            if network_config.has_network_config("storage"):
                ip = self.get_network_ip(host, network_config, "storage")
                if ip:
                    logger.info(f"使用存储网IP [{host}] for {purpose}: {ip}")
                    return ip
            # 回退到管理网
            ip = self.get_network_ip(host, network_config, "management")
            if ip:
                logger.info(f"存储网未配置，使用管理网IP [{host}] for {purpose}: {ip}")
            return ip

        elif purpose == "package_transfer":
            ip = self.get_network_ip(host, network_config, "management")
            if ip:
                logger.info(f"使用管理网IP [{host}] for {purpose}: {ip}")
            return ip

        elif purpose == "ssh_connection":
            ip = self.get_network_ip(host, network_config, "management")
            if ip:
                logger.info(f"使用管理网IP [{host}] for {purpose}: {ip}")
            return ip

        else:
            # 默认使用管理网
            ip = self.get_network_ip(host, network_config, "management")
            if ip:
                logger.info(f"使用管理网IP [{host}] for {purpose}: {ip}")
            return ip

    def get_all_interface_ips(self, host: str, interfaces: List[str]) -> Dict[str, Optional[str]]:
        """
        批量获取多个网卡的IP地址

        Args:
            host: 主机名或IP地址
            interfaces: 网卡名称列表

        Returns:
            字典 {网卡名: IP地址}
        """
        result = {}
        for interface in interfaces:
            result[interface] = self.get_interface_ip(host, interface)
        return result

    def get_rdma_device_ip(self, host: str, rdma_device: str) -> Optional[str]:
        """
        获取RDMA设备对应的IP地址

        Args:
            host: 主机名或IP地址
            rdma_device: RDMA设备名称 (如 mlx5_0)

        Returns:
            IPv4地址字符串，如果未找到返回None
        """
        if not self.ssh_manager:
            logger.error("SSH管理器未初始化")
            return None

        try:
            # 方法1: 通过ibdev2netdev找到对应的网卡
            cmd = f"ibdev2netdev 2>/dev/null | grep {rdma_device}"
            result = self.ssh_manager.execute_on_host(host, cmd, timeout=30)

            if result.success and result.stdout.strip():
                # 解析输出: mlx5_0 port 1 ==> ib0
                match = re.search(r'=>\s+(\S+)', result.stdout)
                if match:
                    interface = match.group(1)
                    ip = self.get_interface_ip(host, interface)
                    if ip:
                        logger.debug(f"获取RDMA设备IP [{host}] {rdma_device}: {ip} (via {interface})")
                        return ip

            # 方法2: 通过rdma link找到对应的网卡
            cmd = f"rdma link show {rdma_device}/1 2>/dev/null"
            result = self.ssh_manager.execute_on_host(host, cmd, timeout=30)

            if result.success and result.stdout.strip():
                # 解析输出: link mlx5_0/1 state ACTIVE physical_state LINK_UP netdev ib0
                match = re.search(r'netdev\s+(\S+)', result.stdout)
                if match:
                    interface = match.group(1)
                    ip = self.get_interface_ip(host, interface)
                    if ip:
                        logger.debug(f"获取RDMA设备IP [{host}] {rdma_device}: {ip} (via {interface})")
                        return ip

            logger.warning(f"未找到RDMA设备对应的网卡 [{host}] {rdma_device}")
            return None

        except Exception as e:
            logger.error(f"获取RDMA设备IP异常 [{host}] {rdma_device}: {e}")
            return None

    def resolve_hostname_to_ip(self, hostname: str) -> Optional[str]:
        """
        将主机名解析为IP地址

        Args:
            hostname: 主机名

        Returns:
            IP地址字符串，如果解析失败返回None
        """
        import socket

        try:
            ip = socket.gethostbyname(hostname)
            logger.debug(f"解析主机名 {hostname} -> {ip}")
            return ip
        except socket.gaierror as e:
            logger.error(f"解析主机名失败 {hostname}: {e}")
            return None
