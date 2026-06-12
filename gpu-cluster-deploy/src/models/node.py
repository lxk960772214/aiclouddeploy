"""
节点模型
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from enum import Enum
from datetime import datetime


class NodeStatus(Enum):
    """节点状态"""
    UNKNOWN = "unknown"
    REACHABLE = "reachable"
    UNREACHABLE = "unreachable"
    DEPLOYING = "deploying"
    DEPLOYED = "deployed"
    FAILED = "failed"


@dataclass
class NodeInfo:
    """节点运行时信息"""
    hostname: str
    ip: str
    status: NodeStatus = NodeStatus.UNKNOWN

    # 系统信息
    os_version: str = ""
    kernel_version: str = ""
    glibc_version: str = ""
    openssh_version: str = ""

    # GPU信息
    gpu_count: int = 0
    gpu_model: str = ""
    gpu_driver_version: str = ""
    cuda_version: str = ""

    # 网络信息
    rdma_devices: List[str] = field(default_factory=list)
    network_interfaces: Dict[str, str] = field(default_factory=dict)

    # 存储信息
    mounted_filesystems: Dict[str, Dict] = field(default_factory=dict)

    # 部署信息
    deployed_steps: List[str] = field(default_factory=list)
    failed_steps: List[str] = field(default_factory=list)
    last_deploy_time: Optional[str] = None

    # 检查时间
    last_check_time: Optional[str] = None

    def update_check_time(self):
        self.last_check_time = datetime.now().isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "hostname": self.hostname,
            "ip": self.ip,
            "status": self.status.value,
            "os_version": self.os_version,
            "kernel_version": self.kernel_version,
            "glibc_version": self.glibc_version,
            "openssh_version": self.openssh_version,
            "gpu_count": self.gpu_count,
            "gpu_model": self.gpu_model,
            "gpu_driver_version": self.gpu_driver_version,
            "cuda_version": self.cuda_version,
            "rdma_devices": self.rdma_devices,
            "network_interfaces": self.network_interfaces,
            "mounted_filesystems": self.mounted_filesystems,
            "deployed_steps": self.deployed_steps,
            "failed_steps": self.failed_steps,
            "last_deploy_time": self.last_deploy_time,
            "last_check_time": self.last_check_time
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "NodeInfo":
        return cls(
            hostname=data.get("hostname", ""),
            ip=data.get("ip", ""),
            status=NodeStatus(data.get("status", "unknown")),
            os_version=data.get("os_version", ""),
            kernel_version=data.get("kernel_version", ""),
            glibc_version=data.get("glibc_version", ""),
            openssh_version=data.get("openssh_version", ""),
            gpu_count=data.get("gpu_count", 0),
            gpu_model=data.get("gpu_model", ""),
            gpu_driver_version=data.get("gpu_driver_version", ""),
            cuda_version=data.get("cuda_version", ""),
            rdma_devices=data.get("rdma_devices", []),
            network_interfaces=data.get("network_interfaces", {}),
            mounted_filesystems=data.get("mounted_filesystems", {}),
            deployed_steps=data.get("deployed_steps", []),
            failed_steps=data.get("failed_steps", []),
            last_deploy_time=data.get("last_deploy_time"),
            last_check_time=data.get("last_check_time")
        )


@dataclass
class ClusterInfo:
    """集群运行时信息"""
    nodes: Dict[str, NodeInfo] = field(default_factory=dict)  # hostname -> NodeInfo

    def add_node(self, node: NodeInfo):
        self.nodes[node.hostname] = node

    def get_node(self, hostname: str) -> Optional[NodeInfo]:
        return self.nodes.get(hostname)

    def get_all_ips(self) -> List[str]:
        return [node.ip for node in self.nodes.values()]

    def get_nodes_by_status(self, status: NodeStatus) -> List[NodeInfo]:
        return [node for node in self.nodes.values() if node.status == status]

    def get_reachable_nodes(self) -> List[NodeInfo]:
        return self.get_nodes_by_status(NodeStatus.REACHABLE)

    def get_unreachable_nodes(self) -> List[NodeInfo]:
        return self.get_nodes_by_status(NodeStatus.UNREACHABLE)

    def update_node_status(self, hostname: str, status: NodeStatus):
        if hostname in self.nodes:
            self.nodes[hostname].status = status

    def to_dict(self) -> Dict:
        return {
            "nodes": {k: v.to_dict() for k, v in self.nodes.items()},
            "summary": {
                "total": len(self.nodes),
                "reachable": len(self.get_reachable_nodes()),
                "unreachable": len(self.get_unreachable_nodes())
            }
        }
