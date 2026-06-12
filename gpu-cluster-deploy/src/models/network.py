#!/usr/bin/env python3
"""
GPU Cluster Deploy - 网络配置数据模型
定义网卡映射、网卡重命名配置、网络拓扑等数据模型
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List, Dict, Any


class NICType(Enum):
    """网卡类型枚举"""
    RDMA = "rdma"  # RDMA设备 (mlx5_*)
    ETHERNET = "ethernet"  # 以太网设备 (ens*)
    UNKNOWN = "unknown"


class NICStatus(Enum):
    """网卡状态枚举"""
    UP = "up"
    DOWN = "down"
    UNKNOWN = "unknown"


@dataclass
class NICInfo:
    """网卡信息数据类"""
    name: str  # 当前名称
    nic_type: NICType  # 网卡类型
    mac_address: Optional[str] = None  # MAC地址
    pci_address: Optional[str] = None  # PCI地址
    driver: Optional[str] = None  # 驱动名称
    status: NICStatus = NICStatus.UNKNOWN  # 状态
    speed: Optional[str] = None  # 速度 (如 "100Gbps")
    mtu: Optional[int] = None  # MTU值

    # RDMA特定字段
    ib_device: Optional[str] = None  # IB设备名 (如 mlx5_0)
    ib_port: Optional[int] = None  # IB端口

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "nic_type": self.nic_type.value,
            "mac_address": self.mac_address,
            "pci_address": self.pci_address,
            "driver": self.driver,
            "status": self.status.value,
            "speed": self.speed,
            "mtu": self.mtu,
            "ib_device": self.ib_device,
            "ib_port": self.ib_port,
        }


@dataclass
class NICMapping:
    """网卡映射数据类

    定义从一个网卡到另一个名称的映射规则
    """
    source_pattern: str  # 源名称模式 (支持通配符，如 "mlx5_*")
    target_name: str  # 目标名称模板 (支持变量，如 "rdma{index}")
    nic_type: NICType  # 网卡类型

    # 可选条件
    condition: Optional[Dict[str, Any]] = None  # 匹配条件
    enabled: bool = True  # 是否启用此映射

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_pattern": self.source_pattern,
            "target_name": self.target_name,
            "nic_type": self.nic_type.value,
            "condition": self.condition,
            "enabled": self.enabled,
        }


@dataclass
class NICRenameRule:
    """网卡重命名规则数据类"""
    original_name: str  # 原始名称
    new_name: str  # 新名称
    nic_type: NICType  # 网卡类型
    pci_address: Optional[str] = None  # PCI地址 (用于udev规则)
    mac_address: Optional[str] = None  # MAC地址 (备用匹配方式)

    # 执行信息
    executed: bool = False  # 是否已执行
    success: bool = False  # 是否成功
    error: Optional[str] = None  # 错误信息

    def to_dict(self) -> Dict[str, Any]:
        return {
            "original_name": self.original_name,
            "new_name": self.new_name,
            "nic_type": self.nic_type.value,
            "pci_address": self.pci_address,
            "mac_address": self.mac_address,
            "executed": self.executed,
            "success": self.success,
            "error": self.error,
        }


@dataclass
class NICRenameConfig:
    """网卡重命名配置数据类"""
    enabled: bool = False  # 是否启用重命名
    mappings: List[NICMapping] = field(default_factory=list)  # 映射规则列表

    # 执行选项
    create_udev_rules: bool = True  # 是否创建udev规则
    backup_original: bool = True  # 是否备份原始配置
    require_reboot: bool = False  # 是否需要重启

    # 安全选项
    skip_if_exists: bool = True  # 如果目标名称已存在则跳过
    dry_run: bool = False  # 预览模式

    def to_dict(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "mappings": [m.to_dict() for m in self.mappings],
            "create_udev_rules": self.create_udev_rules,
            "backup_original": self.backup_original,
            "require_reboot": self.require_reboot,
            "skip_if_exists": self.skip_if_exists,
            "dry_run": self.dry_run,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "NICRenameConfig":
        """从字典创建配置"""
        mappings = []
        for m in data.get("mappings", []):
            mapping = NICMapping(
                source_pattern=m["source_pattern"],
                target_name=m["target_name"],
                nic_type=NICType(m.get("nic_type", "unknown")),
                condition=m.get("condition"),
                enabled=m.get("enabled", True),
            )
            mappings.append(mapping)

        return cls(
            enabled=data.get("enabled", False),
            mappings=mappings,
            create_udev_rules=data.get("create_udev_rules", True),
            backup_original=data.get("backup_original", True),
            require_reboot=data.get("require_reboot", False),
            skip_if_exists=data.get("skip_if_exists", True),
            dry_run=data.get("dry_run", False),
        )


@dataclass
class NetworkTopology:
    """网络拓扑数据类"""
    node_hostname: str  # 节点主机名

    # 网卡列表
    rdma_nics: List[NICInfo] = field(default_factory=list)  # RDMA网卡
    ethernet_nics: List[NICInfo] = field(default_factory=list)  # 以太网网卡

    # 拓扑信息
    numa_topology: Dict[str, List[str]] = field(default_factory=dict)  # NUMA节点到网卡映射

    # 连接信息
    switches: Dict[str, str] = field(default_factory=dict)  # 网卡到交换机映射

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_hostname": self.node_hostname,
            "rdma_nics": [n.to_dict() for n in self.rdma_nics],
            "ethernet_nics": [n.to_dict() for n in self.ethernet_nics],
            "numa_topology": self.numa_topology,
            "switches": self.switches,
        }

    @property
    def total_nics(self) -> int:
        """总网卡数"""
        return len(self.rdma_nics) + len(self.ethernet_nics)


@dataclass
class NetworkConfig:
    """网络配置数据类"""
    rename_config: Optional[NICRenameConfig] = None  # 重命名配置

    # IP配置
    configure_ip: bool = False  # 是否配置IP
    ip_configs: Dict[str, Dict[str, Any]] = field(default_factory=dict)  # 网卡IP配置

    # MTU配置
    configure_mtu: bool = False  # 是否配置MTU
    default_mtu: int = 9000  # 默认MTU

    # 其他配置
    configure_dns: bool = False  # 是否配置DNS
    dns_servers: List[str] = field(default_factory=list)  # DNS服务器列表

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rename_config": self.rename_config.to_dict() if self.rename_config else None,
            "configure_ip": self.configure_ip,
            "ip_configs": self.ip_configs,
            "configure_mtu": self.configure_mtu,
            "default_mtu": self.default_mtu,
            "configure_dns": self.configure_dns,
            "dns_servers": self.dns_servers,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "NetworkConfig":
        """从字典创建配置"""
        rename_config = None
        if data.get("rename_config"):
            rename_config = NICRenameConfig.from_dict(data["rename_config"])

        return cls(
            rename_config=rename_config,
            configure_ip=data.get("configure_ip", False),
            ip_configs=data.get("ip_configs", {}),
            configure_mtu=data.get("configure_mtu", False),
            default_mtu=data.get("default_mtu", 9000),
            configure_dns=data.get("configure_dns", False),
            dns_servers=data.get("dns_servers", []),
        )


@dataclass
class NICRenameResult:
    """网卡重命名结果数据类"""
    node_hostname: str  # 节点主机名
    rules: List[NICRenameRule] = field(default_factory=list)  # 执行的规则
    success: bool = False  # 整体是否成功
    error: Optional[str] = None  # 错误信息

    @property
    def total_rules(self) -> int:
        return len(self.rules)

    @property
    def successful_rules(self) -> int:
        return sum(1 for r in self.rules if r.success)

    @property
    def failed_rules(self) -> int:
        return sum(1 for r in self.rules if not r.success and r.executed)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_hostname": self.node_hostname,
            "rules": [r.to_dict() for r in self.rules],
            "success": self.success,
            "error": self.error,
            "total_rules": self.total_rules,
            "successful_rules": self.successful_rules,
            "failed_rules": self.failed_rules,
        }
