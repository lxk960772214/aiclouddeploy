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
class NodeAuthConfig:
    """节点认证配置"""
    auth_type: str = "key"  # key | password
    username: str = "ubuntu"
    private_key: Optional[str] = None
    password: Optional[str] = None

    def to_dict(self) -> Dict:
        return {
            "auth_type": self.auth_type,
            "username": self.username,
            "private_key": "***" if self.private_key else None,
            "password": "***" if self.password else None
        }


@dataclass
class JumphostConfig:
    """跳转服务器配置"""
    host: str
    port: int = 22
    auth_type: str = "key"
    username: str = "ubuntu"
    private_key: Optional[str] = None
    password: Optional[str] = None
    node_auth: Optional[NodeAuthConfig] = None  # 用于访问节点的认证配置

    def to_dict(self) -> Dict:
        return {
            "host": self.host,
            "port": self.port,
            "auth_type": self.auth_type,
            "username": self.username,
            "private_key": "***" if self.private_key else None,
            "password": "***" if self.password else None,
            "node_auth": self.node_auth.to_dict() if self.node_auth else None
        }


@dataclass
class StorageConfig:
    """存储配置"""
    type: StorageType = StorageType.SINGLE
    device: Optional[str] = None
    devices: List[str] = field(default_factory=list)
    mount_point: str = "/ssd"
    filesystem: str = "ext4"
    format_disk: bool = False  # 是否格式化磁盘（默认不格式化，防止数据丢失）

    def to_dict(self) -> Dict:
        return {
            "type": self.type.value,
            "device": self.device,
            "devices": self.devices,
            "mount_point": self.mount_point,
            "filesystem": self.filesystem,
            "format_disk": self.format_disk
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
class NodeBatchConfig:
    """批量节点配置"""
    enabled: bool = False
    hosts_file: Optional[str] = None  # hosts格式文件路径
    hosts_content: Optional[str] = None  # hosts格式内容
    base_hostname_prefix: str = "node"  # 基础主机名前缀
    base_ip_prefix: str = "10.0.0"  # 基础IP前缀
    count: int = 0  # 批量节点数量
    start_index: int = 1  # 起始索引
    roles: List[str] = field(default_factory=list)  # 批量节点默认角色
    storage_template: Optional[StorageConfig] = None  # 存储配置模板
    auth_template: Optional[NodeAuthConfig] = None  # 认证配置模板

    def to_dict(self) -> Dict:
        return {
            "enabled": self.enabled,
            "hosts_file": self.hosts_file,
            "hosts_content": self.hosts_content,
            "base_hostname_prefix": self.base_hostname_prefix,
            "base_ip_prefix": self.base_ip_prefix,
            "count": self.count,
            "start_index": self.start_index,
            "roles": self.roles,
            "storage_template": self.storage_template.to_dict() if self.storage_template else None,
            "auth_template": self.auth_template.to_dict() if self.auth_template else None
        }


@dataclass
class ClusterConfig:
    """集群配置"""
    name: str = "gpu-cluster"
    description: str = ""
    jumphost: Optional[JumphostConfig] = None
    nodes: List[NodeConfig] = field(default_factory=list)
    node_batch: NodeBatchConfig = field(default_factory=NodeBatchConfig)  # 批量节点配置
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
            "node_batch": self.node_batch.to_dict(),
            "nfs": self.nfs.to_dict(),
            "network": self.network.to_dict(),
            "node_count": self.node_count
        }
