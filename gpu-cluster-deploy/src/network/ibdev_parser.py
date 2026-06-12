"""
ibdev2netdev解析器
解析ibdev2netdev命令输出，建立RDMA设备和网络接口的映射关系
"""

import re
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass


@dataclass
class IbdevMapping:
    """RDMA设备到网络设备的映射"""
    rdma_device: str       # RDMA设备名 (如 mlx5_0)
    port: int              # 端口号
    state: str             # 状态 (Active/Down)
    netdev: Optional[str]  # 网络设备名 (如 ib0, eth1)
    speed: str             # 速度描述
    original_line: str     # 原始行内容

    def to_dict(self) -> Dict:
        return {
            "rdma_device": self.rdma_device,
            "port": self.port,
            "state": self.state,
            "netdev": self.netdev,
            "speed": self.speed,
            "original_line": self.original_line
        }


class IbdevParser:
    """ibdev2netdev输出解析器"""

    # ibdev2netdev输出的典型格式:
    # mlx5_0 port 1 ==> ib0 (Active) 200Gbps(InfiniBand)
    # mlx5_1 port 1 ==> eth1 (Active) 100Gbps(Ethernet)
    # mlx5_2 port 1 ==> ib2 (Down)

    # 解析正则表达式
    PATTERN = re.compile(
        r'^(?P<rdma_device>\S+)\s+port\s+(?P<port>\d+)\s+==>\s*'
        r'(?P<netdev>\S+)?\s*'
        r'\((?P<state>\w+)\)'
        r'(?:\s+(?P<speed>.*))?$'
    )

    def __init__(self):
        """初始化解析器"""
        self.mappings: List[IbdevMapping] = []

    def parse(self, output: str) -> List[IbdevMapping]:
        """
        解析ibdev2netdev命令输出

        Args:
            output: ibdev2netdev命令的输出

        Returns:
            映射列表
        """
        self.mappings = []
        lines = output.strip().split('\n')

        for line in lines:
            line = line.strip()
            if not line:
                continue

            mapping = self._parse_line(line)
            if mapping:
                self.mappings.append(mapping)

        return self.mappings

    def _parse_line(self, line: str) -> Optional[IbdevMapping]:
        """
        解析单行输出

        Args:
            line: 单行文本

        Returns:
            IbdevMapping或None
        """
        match = self.PATTERN.match(line)
        if not match:
            # 尝试更宽松的解析
            return self._parse_line_loose(line)

        return IbdevMapping(
            rdma_device=match.group('rdma_device'),
            port=int(match.group('port')),
            state=match.group('state'),
            netdev=match.group('netdev') if match.group('netdev') else None,
            speed=match.group('speed').strip() if match.group('speed') else '',
            original_line=line
        )

    def _parse_line_loose(self, line: str) -> Optional[IbdevMapping]:
        """
        宽松解析模式，处理非标准格式

        Args:
            line: 单行文本

        Returns:
            IbdevMapping或None
        """
        # 尝试解析格式: mlx5_0 port 1 ==> ib0 (Active)
        simple_pattern = re.compile(
            r'^(?P<rdma_device>\S+)\s+port\s+(?P<port>\d+)\s+==>\s*'
            r'(?P<netdev>\S+)?\s*\((?P<state>\w+)\)'
        )

        match = simple_pattern.match(line)
        if match:
            return IbdevMapping(
                rdma_device=match.group('rdma_device'),
                port=int(match.group('port')),
                state=match.group('state'),
                netdev=match.group('netdev') if match.group('netdev') else None,
                speed='',
                original_line=line
            )

        # 尝试解析格式: mlx5_0: port 1: ib0 (Active)
        alt_pattern = re.compile(
            r'^(?P<rdma_device>\S+):\s*port\s+(?P<port>\d+):\s*'
            r'(?P<netdev>\S+)\s*\((?P<state>\w+)\)'
        )

        match = alt_pattern.match(line)
        if match:
            return IbdevMapping(
                rdma_device=match.group('rdma_device'),
                port=int(match.group('port')),
                state=match.group('state'),
                netdev=match.group('netdev'),
                speed='',
                original_line=line
            )

        return None

    def get_rdma_to_netdev_map(self) -> Dict[str, str]:
        """
        获取RDMA设备到网络设备的映射字典

        Returns:
            字典，key为RDMA设备名，value为网络设备名
        """
        return {
            m.rdma_device: m.netdev
            for m in self.mappings
            if m.netdev
        }

    def get_netdev_to_rdma_map(self) -> Dict[str, str]:
        """
        获取网络设备到RDMA设备的映射字典

        Returns:
            字典，key为网络设备名，value为RDMA设备名
        """
        return {
            m.netdev: m.rdma_device
            for m in self.mappings
            if m.netdev
        }

    def get_by_rdma_device(self, rdma_device: str) -> Optional[IbdevMapping]:
        """
        根据RDMA设备名获取映射

        Args:
            rdma_device: RDMA设备名

        Returns:
            映射或None
        """
        for mapping in self.mappings:
            if mapping.rdma_device == rdma_device:
                return mapping
        return None

    def get_by_netdev(self, netdev: str) -> Optional[IbdevMapping]:
        """
        根据网络设备名获取映射

        Args:
            netdev: 网络设备名

        Returns:
            映射或None
        """
        for mapping in self.mappings:
            if mapping.netdev == netdev:
                return mapping
        return None

    def get_active_devices(self) -> List[IbdevMapping]:
        """获取状态为Active的设备列表"""
        return [m for m in self.mappings if m.state.lower() == 'active']

    def get_down_devices(self) -> List[IbdevMapping]:
        """获取状态为Down的设备列表"""
        return [m for m in self.mappings if m.state.lower() == 'down']

    def get_infiniband_devices(self) -> List[IbdevMapping]:
        """获取InfiniBand设备列表"""
        return [
            m for m in self.mappings
            if m.netdev and m.netdev.startswith('ib')
        ]

    def get_ethernet_devices(self) -> List[IbdevMapping]:
        """获取以太网设备列表（通过RDMA）"""
        return [
            m for m in self.mappings
            if m.netdev and (m.netdev.startswith('eth') or m.netdev.startswith('ens'))
        ]

    def get_device_summary(self) -> Dict:
        """
        获取设备摘要

        Returns:
            设备摘要字典
        """
        return {
            "total_devices": len(self.mappings),
            "active_devices": len(self.get_active_devices()),
            "down_devices": len(self.get_down_devices()),
            "infiniband_devices": len(self.get_infiniband_devices()),
            "ethernet_devices": len(self.get_ethernet_devices()),
            "rdma_device_names": [m.rdma_device for m in self.mappings],
            "netdev_names": [m.netdev for m in self.mappings if m.netdev]
        }

    def validate_consistency(self) -> List[str]:
        """
        验证映射一致性

        Returns:
            问题列表
        """
        issues = []

        # 检查是否有重复的RDMA设备
        rdma_devices = [m.rdma_device for m in self.mappings]
        seen_rdma = set()
        for rdma in rdma_devices:
            if rdma in seen_rdma:
                issues.append(f"重复的RDMA设备: {rdma}")
            seen_rdma.add(rdma)

        # 检查是否有重复的网络设备
        netdevs = [m.netdev for m in self.mappings if m.netdev]
        seen_netdev = set()
        for netdev in netdevs:
            if netdev in seen_netdev:
                issues.append(f"重复的网络设备: {netdev}")
            seen_netdev.add(netdev)

        # 检查端口是否连续
        ports = sorted([m.port for m in self.mappings])
        if ports and ports != list(range(1, len(ports) + 1)):
            issues.append(f"端口不连续: {ports}")

        return issues

    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            "mappings": [m.to_dict() for m in self.mappings],
            "summary": self.get_device_summary()
        }


def parse_ibdev_output(output: str) -> List[IbdevMapping]:
    """
    解析ibdev2netdev输出的便捷函数

    Args:
        output: ibdev2netdev命令的输出

    Returns:
        映射列表
    """
    parser = IbdevParser()
    return parser.parse(output)


def get_rdma_netdev_mapping(output: str) -> Dict[str, str]:
    """
    获取RDMA到网络设备映射的便捷函数

    Args:
        output: ibdev2netdev命令的输出

    Returns:
        映射字典
    """
    parser = IbdevParser()
    parser.parse(output)
    return parser.get_rdma_to_netdev_map()
