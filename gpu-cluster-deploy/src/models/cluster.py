"""
集群模型
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from enum import Enum


class NodeRole(Enum):
    """节点角色"""
    NFS_SERVER = "nfs_server"
    TIME_SERVER = "time_server"
    GPU_NODE = "gpu_node"
    CPU_NODE = "cpu_node"


class StorageType(Enum):
    """存储类型"""
    SINGLE = "single"
    RAID1 = "raid1"
    RAID10 = "raid10"


@dataclass
class JumphostConfig:
    """跳转服务器配置"""
    host: str
    port: int = 22
    auth_type: str = "key"
    username: str = "ubuntu"
    private_key: Optional[str] = None
    password: Optional[str] = None

    def to_dict(self) -> Dict:
        return {
            "host": self.host,
            "port": self.port,
            "auth_type": self.auth_type,
            "username": self.username,
            "private_key": "***" if self.private_key else None,
            "password": "***" if self.password else None
        }


@dataclass
class StorageConfig:
    """存储配置"""
    type: StorageType = StorageType.SINGLE
    device: Optional[str] = None
    devices: List[str] = field(default_factory=list)
    mount_point: str = "/ssd"
    filesystem: str = "ext4"

    def to_dict(self) -> Dict:
        return {
            "type": self.type.value,
            "device": self.device,
            "devices": self.devices,
            "mount_point": self.mount_point,
            "filesystem": self.filesystem
        }


@dataclass
class NodeConfig:
    """节点配置"""
    hostname: str
    ip: str
    roles: List[str] = field(default_factory=list)
    storage: Optional[StorageConfig] = None

    @property
    def is_nfs_server(self) -> bool:
        return NodeRole.NFS_SERVER.value in self.roles

    @property
    def is_time_server(self) -> bool:
        return NodeRole.TIME_SERVER.value in self.roles

    @property
    def is_gpu_node(self) -> bool:
        return NodeRole.GPU_NODE.value in self.roles

    def to_dict(self) -> Dict:
        return {
            "hostname": self.hostname,
            "ip": self.ip,
            "roles": self.roles,
            "storage": self.storage.to_dict() if self.storage else None
        }


@dataclass
class NFSConfig:
    """NFS配置"""
    enabled: bool = True
    server: Optional[str] = None
    export_path: str = "/ssd/nfs"
    client_mount: str = "/data"
    client_ips: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "enabled": self.enabled,
            "server": self.server,
            "export_path": self.export_path,
            "client_mount": self.client_mount,
            "client_ips": self.client_ips
        }


@dataclass
class NetworkConfig:
    """网络配置"""
    compute_nics: List[str] = field(default_factory=list)
    storage_nics: List[str] = field(default_factory=list)
    management_nics: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "compute_nics": self.compute_nics,
            "storage_nics": self.storage_nics,
            "management_nics": self.management_nics
        }


@dataclass
class ClusterConfig:
    """集群配置"""
    name: str = "gpu-cluster"
    description: str = ""
    jumphost: Optional[JumphostConfig] = None
    nodes: List[NodeConfig] = field(default_factory=list)
    nfs: NFSConfig = field(default_factory=NFSConfig)
    network: NetworkConfig = field(default_factory=NetworkConfig)

    @property
    def node_count(self) -> int:
        return len(self.nodes)

    @property
    def nfs_server_node(self) -> Optional[NodeConfig]:
        for node in self.nodes:
            if node.is_nfs_server:
                return node
        return None

    @property
    def time_server_node(self) -> Optional[NodeConfig]:
        for node in self.nodes:
            if node.is_time_server:
                return node
        return None

    @property
    def gpu_nodes(self) -> List[NodeConfig]:
        return [node for node in self.nodes if node.is_gpu_node]

    @property
    def client_nodes(self) -> List[NodeConfig]:
        """非NFS服务器的节点"""
        return [node for node in self.nodes if not node.is_nfs_server]

    def get_node_by_hostname(self, hostname: str) -> Optional[NodeConfig]:
        for node in self.nodes:
            if node.hostname == hostname:
                return node
        return None

    def get_node_by_ip(self, ip: str) -> Optional[NodeConfig]:
        for node in self.nodes:
            if node.ip == ip:
                return node
        return None

    def get_all_ips(self) -> List[str]:
        return [node.ip for node in self.nodes]

    def get_all_hostnames(self) -> List[str]:
        return [node.hostname for node in self.nodes]

    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "description": self.description,
            "jumphost": self.jumphost.to_dict() if self.jumphost else None,
            "nodes": [node.to_dict() for node in self.nodes],
            "nfs": self.nfs.to_dict(),
            "network": self.network.to_dict(),
            "node_count": self.node_count
        }
