"""
设备检查数据模型
定义用于设备一致性检查的数据结构
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from enum import Enum


class DeviceType(Enum):
    """设备类型"""
    RDMA = "rdma"          # RDMA设备 (mlx5_*)
    ETHERNET = "ethernet"  # 以太网设备 (ens*, eth*)
    GPU = "gpu"            # GPU设备
    NVME = "nvme"          # NVMe存储设备


class DeviceStatus(Enum):
    """设备状态"""
    PRESENT = "present"        # 设备存在
    MISSING = "missing"        # 设备缺失
    EXTRA = "extra"            # 多余设备
    MISMATCH = "mismatch"      # 不匹配


class ConsistencyLevel(Enum):
    """一致性级别"""
    CONSISTENT = "consistent"      # 完全一致
    WARNING = "warning"            # 有警告但不影响
    INCONSISTENT = "inconsistent"  # 不一致，需要修复
    CRITICAL = "critical"          # 严重不一致


@dataclass
class DeviceInfo:
    """设备信息"""
    name: str                           # 设备名称 (如 mlx5_0, ens4f0)
    device_type: DeviceType             # 设备类型
    pci_address: Optional[str] = None   # PCI地址
    driver: Optional[str] = None        # 驱动程序
    firmware: Optional[str] = None      # 固件版本
    numa_node: Optional[int] = None     # NUMA节点
    port: Optional[int] = None          # 端口号
    netdev: Optional[str] = None        # 关联的网络设备
    speed: Optional[str] = None         # 速度
    mtu: Optional[int] = None           # MTU
    state: Optional[str] = None         # 状态 (up/down)
    extra_info: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "device_type": self.device_type.value,
            "pci_address": self.pci_address,
            "driver": self.driver,
            "firmware": self.firmware,
            "numa_node": self.numa_node,
            "port": self.port,
            "netdev": self.netdev,
            "speed": self.speed,
            "mtu": self.mtu,
            "state": self.state,
            "extra_info": self.extra_info
        }


@dataclass
class NodeDeviceSnapshot:
    """节点设备快照"""
    hostname: str
    timestamp: str
    rdma_devices: List[DeviceInfo] = field(default_factory=list)
    ethernet_devices: List[DeviceInfo] = field(default_factory=list)
    gpu_devices: List[DeviceInfo] = field(default_factory=list)
    nvme_devices: List[DeviceInfo] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    @property
    def all_devices(self) -> List[DeviceInfo]:
        """获取所有设备"""
        return self.rdma_devices + self.ethernet_devices + self.gpu_devices + self.nvme_devices

    @property
    def device_count(self) -> Dict[str, int]:
        """获取各类设备数量"""
        return {
            "rdma": len(self.rdma_devices),
            "ethernet": len(self.ethernet_devices),
            "gpu": len(self.gpu_devices),
            "nvme": len(self.nvme_devices)
        }

    def get_rdma_names(self) -> List[str]:
        """获取RDMA设备名称列表"""
        return sorted([d.name for d in self.rdma_devices])

    def get_ethernet_names(self) -> List[str]:
        """获取以太网设备名称列表"""
        return sorted([d.name for d in self.ethernet_devices])

    def to_dict(self) -> Dict:
        return {
            "hostname": self.hostname,
            "timestamp": self.timestamp,
            "rdma_devices": [d.to_dict() for d in self.rdma_devices],
            "ethernet_devices": [d.to_dict() for d in self.ethernet_devices],
            "gpu_devices": [d.to_dict() for d in self.gpu_devices],
            "nvme_devices": [d.to_dict() for d in self.nvme_devices],
            "device_count": self.device_count,
            "errors": self.errors
        }


@dataclass
class DeviceDifference:
    """设备差异"""
    device_type: DeviceType
    device_name: str
    status: DeviceStatus
    reference_node: Optional[str] = None    # 参考节点（有此设备的节点）
    affected_nodes: List[str] = field(default_factory=list)  # 受影响的节点
    details: str = ""

    def to_dict(self) -> Dict:
        return {
            "device_type": self.device_type.value,
            "device_name": self.device_name,
            "status": self.status.value,
            "reference_node": self.reference_node,
            "affected_nodes": self.affected_nodes,
            "details": self.details
        }


@dataclass
class ConsistencyReport:
    """一致性检查报告"""
    cluster_name: str
    check_time: str
    overall_level: ConsistencyLevel
    node_snapshots: List[NodeDeviceSnapshot] = field(default_factory=list)
    differences: List[DeviceDifference] = field(default_factory=list)
    summary: Dict[str, Any] = field(default_factory=dict)

    @property
    def node_count(self) -> int:
        return len(self.node_snapshots)

    @property
    def difference_count(self) -> int:
        return len(self.differences)

    @property
    def critical_count(self) -> int:
        return sum(1 for d in self.differences if d.status == DeviceStatus.MISSING)

    @property
    def warning_count(self) -> int:
        return sum(1 for d in self.differences if d.status == DeviceStatus.EXTRA)

    def get_differences_by_type(self, device_type: DeviceType) -> List[DeviceDifference]:
        """按设备类型获取差异"""
        return [d for d in self.differences if d.device_type == device_type]

    def get_differences_by_status(self, status: DeviceStatus) -> List[DeviceDifference]:
        """按状态获取差异"""
        return [d for d in self.differences if d.status == status]

    def to_dict(self) -> Dict:
        return {
            "cluster_name": self.cluster_name,
            "check_time": self.check_time,
            "overall_level": self.overall_level.value,
            "node_count": self.node_count,
            "difference_count": self.difference_count,
            "critical_count": self.critical_count,
            "warning_count": self.warning_count,
            "node_snapshots": [s.to_dict() for s in self.node_snapshots],
            "differences": [d.to_dict() for d in self.differences],
            "summary": self.summary
        }


@dataclass
class FixSuggestion:
    """修复建议"""
    priority: int                              # 优先级 (1最高)
    device_difference: DeviceDifference        # 对应的设备差异
    action: str                                # 建议的操作
    commands: List[str] = field(default_factory=list)  # 可执行的命令
    risk_level: str = "low"                    # 风险级别
    requires_reboot: bool = False              # 是否需要重启
    notes: str = ""                            # 备注

    def to_dict(self) -> Dict:
        return {
            "priority": self.priority,
            "device_difference": self.device_difference.to_dict(),
            "action": self.action,
            "commands": self.commands,
            "risk_level": self.risk_level,
            "requires_reboot": self.requires_reboot,
            "notes": self.notes
        }


@dataclass
class GPUTopologyInfo:
    """GPU拓扑信息"""
    gpu_index: int
    gpu_name: str
    pci_address: str
    numa_node: int
    connected_rdma: List[str] = field(default_factory=list)  # 连接的RDMA设备
    nvlink_connections: List[int] = field(default_factory=list)  # NVLink连接的GPU索引

    def to_dict(self) -> Dict:
        return {
            "gpu_index": self.gpu_index,
            "gpu_name": self.gpu_name,
            "pci_address": self.pci_address,
            "numa_node": self.numa_node,
            "connected_rdma": self.connected_rdma,
            "nvlink_connections": self.nvlink_connections
        }


@dataclass
class TopologyCheckResult:
    """拓扑检查结果"""
    hostname: str
    gpu_topologies: List[GPUTopologyInfo] = field(default_factory=list)
    numa_consistency: bool = True
    issues: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "hostname": self.hostname,
            "gpu_topologies": [t.to_dict() for t in self.gpu_topologies],
            "numa_consistency": self.numa_consistency,
            "issues": self.issues
        }


@dataclass
class DeviceCheckConfig:
    """设备检查配置"""
    enabled: bool = True
    check_rdma: bool = True
    check_ethernet: bool = True
    check_gpu: bool = True
    check_nvme: bool = False
    tolerance_level: str = "strict"  # strict | moderate | lenient
    expected_rdma_count: Optional[int] = None
    expected_ethernet_count: Optional[int] = None
    expected_gpu_count: Optional[int] = None
    rdma_name_pattern: str = r"mlx5_\d+"
    ethernet_name_pattern: str = r"ens\d+f\d+|eth\d+"

    def to_dict(self) -> Dict:
        return {
            "enabled": self.enabled,
            "check_rdma": self.check_rdma,
            "check_ethernet": self.check_ethernet,
            "check_gpu": self.check_gpu,
            "check_nvme": self.check_nvme,
            "tolerance_level": self.tolerance_level,
            "expected_rdma_count": self.expected_rdma_count,
            "expected_ethernet_count": self.expected_ethernet_count,
            "expected_gpu_count": self.expected_gpu_count,
            "rdma_name_pattern": self.rdma_name_pattern,
            "ethernet_name_pattern": self.ethernet_name_pattern
        }
