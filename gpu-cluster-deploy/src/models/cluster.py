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

    def _validate(self):
        """验证存储配置"""
        if self.type == StorageType.SINGLE:
            if not self.device and not self.devices:
                raise ValueError("single模式需要指定device或devices")
        elif self.type in (StorageType.RAID1, StorageType.RAID10):
            if not self.devices or len(self.devices) < 2:
                raise ValueError(f"{self.type.value}模式需要至少2个设备")
            if self.type == StorageType.RAID10 and len(self.devices) < 4:
                raise ValueError("RAID10模式需要至少4个设备")

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
    port: int = 22  # SSH端口
    username: Optional[str] = None  # SSH用户名
    password: Optional[str] = None  # SSH密码
    private_key: Optional[str] = None  # SSH私钥路径

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
            "port": self.port,
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
class TimeSyncConfig:
    """时间同步配置"""
    server: Optional[str] = None
    timezone: str = "Asia/Shanghai"

    def to_dict(self) -> Dict:
        return {
            "server": self.server,
            "timezone": self.timezone
        }


@dataclass
class NICConfig:
    """网卡配置"""
    pattern: str
    count: int
    net_prefix: str


@dataclass
class NetworkTypeConfig:
    """单个网络类型配置"""
    description: str = ""
    interfaces: List[str] = field(default_factory=list)
    rdma_devices: List[str] = field(default_factory=list)
    enabled: bool = True
    skip_performance_test: bool = False
    skip_inter_host_test: bool = False
    theoretical_bandwidth_gbps: float = 100.0

    def to_dict(self) -> Dict:
        return {
            "description": self.description,
            "interfaces": self.interfaces,
            "rdma_devices": self.rdma_devices,
            "enabled": self.enabled,
            "skip_performance_test": self.skip_performance_test,
            "skip_inter_host_test": self.skip_inter_host_test,
            "theoretical_bandwidth_gbps": self.theoretical_bandwidth_gbps
        }


@dataclass
class IBWriteBWConfig:
    """ib_write_bw测试参数"""
    duration: int = 10
    size: int = 65536
    port_base: int = 18500
    min_bandwidth_percent: float = 90.0

    def to_dict(self) -> Dict:
        return {
            "duration": self.duration,
            "size": self.size,
            "port_base": self.port_base,
            "min_bandwidth_percent": self.min_bandwidth_percent
        }


@dataclass
class NICMappingConfig:
    """网卡映射配置（简化版）"""
    source_pattern: str  # 源名称模式
    target_name: str  # 目标名称模板
    nic_type: str = "unknown"  # rdma | ethernet | unknown
    enabled: bool = True


@dataclass
class NICRenameConfig:
    """网卡重命名配置"""
    enabled: bool = False
    mappings: List[NICMappingConfig] = field(default_factory=list)
    create_udev_rules: bool = True
    backup_original: bool = True
    skip_if_exists: bool = True
    dry_run: bool = False


@dataclass
class SSHKeyConfig:
    """SSH免密登录配置"""
    enabled: bool = True  # 是否启用免密配置
    users: Optional[List[str]] = None  # 要配置免密的用户列表，None表示自动检测部署用户
    # 密钥配置（可选，不指定则自动生成）
    private_key: Optional[str] = None  # 指定私钥路径
    public_key: Optional[str] = None  # 指定公钥路径或公钥内容

    def to_dict(self) -> Dict:
        return {
            "enabled": self.enabled,
            "users": self.users,
            "private_key": "***" if self.private_key else None,
            "public_key": "***" if self.public_key else None
        }


@dataclass
class NetworkConfig:
    """网络配置

    支持两种配置格式:
    1. 新格式: management/compute/storage 独立配置
    2. 旧格式: compute_nics/storage_nics/management_nics 列表 + nics pattern配置
    """
    # 新格式 - 独立网络类型配置
    management: Optional[NetworkTypeConfig] = None
    compute: Optional[NetworkTypeConfig] = None
    storage: Optional[NetworkTypeConfig] = None
    ib_write_bw: Optional[IBWriteBWConfig] = None

    # 旧格式 - 保留向后兼容
    compute_nics: List[str] = field(default_factory=list)
    storage_nics: List[str] = field(default_factory=list)
    management_nics: List[str] = field(default_factory=list)
    nics: Dict[str, NICConfig] = field(default_factory=dict)
    nic_rename: Optional[NICRenameConfig] = None  # 网卡重命名配置

    def get_enabled_networks(self) -> Dict[str, NetworkTypeConfig]:
        """获取所有启用的网络配置"""
        result = {}
        if self.management and self.management.enabled:
            result['management'] = self.management
        if self.compute and self.compute.enabled:
            result['compute'] = self.compute
        if self.storage and self.storage.enabled:
            result['storage'] = self.storage
        return result

    def get_network_interfaces(self, network_type: str) -> List[str]:
        """获取指定网络类型的接口列表"""
        network = getattr(self, network_type, None)
        if network and isinstance(network, NetworkTypeConfig):
            return network.interfaces
        # 回退到旧格式
        if network_type == 'management':
            return self.management_nics
        elif network_type == 'compute':
            return self.compute_nics
        elif network_type == 'storage':
            return self.storage_nics
        return []

    def get_network_rdma_devices(self, network_type: str) -> List[str]:
        """获取指定网络类型的RDMA设备列表"""
        network = getattr(self, network_type, None)
        if network and isinstance(network, NetworkTypeConfig):
            return network.rdma_devices
        return []

    def has_network_config(self, network_type: str) -> bool:
        """检查是否配置了指定网络类型"""
        network = getattr(self, network_type, None)
        if network and isinstance(network, NetworkTypeConfig) and network.enabled:
            return bool(network.interfaces or network.rdma_devices)
        # 检查旧格式
        if network_type == 'management':
            return bool(self.management_nics)
        elif network_type == 'compute':
            return bool(self.compute_nics)
        elif network_type == 'storage':
            return bool(self.storage_nics)
        return False

    def to_dict(self) -> Dict:
        result = {
            # 新格式
            "management": self.management.to_dict() if self.management else None,
            "compute": self.compute.to_dict() if self.compute else None,
            "storage": self.storage.to_dict() if self.storage else None,
            "ib_write_bw": self.ib_write_bw.to_dict() if self.ib_write_bw else None,
            # 旧格式
            "compute_nics": self.compute_nics,
            "storage_nics": self.storage_nics,
            "management_nics": self.management_nics,
            "nics": {k: {"pattern": v.pattern, "count": v.count, "net_prefix": v.net_prefix} for k, v in self.nics.items()},
            "nic_rename": {
                "enabled": self.nic_rename.enabled,
                "mappings": [{"source_pattern": m.source_pattern, "target_name": m.target_name, "nic_type": m.nic_type, "enabled": m.enabled} for m in self.nic_rename.mappings]
            } if self.nic_rename else None
        }
        return result


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
    deploy_user: Optional[str] = None  # 部署用户（可选，默认使用登录用户）
    create_users: bool = False  # 是否创建ubuntu用户（默认不创建）
    jumphost: Optional[JumphostConfig] = None
    nodes: List[NodeConfig] = field(default_factory=list)
    node_batch: NodeBatchConfig = field(default_factory=NodeBatchConfig)  # 批量节点配置
    nfs: NFSConfig = field(default_factory=NFSConfig)
    time_sync: TimeSyncConfig = field(default_factory=TimeSyncConfig)
    network: NetworkConfig = field(default_factory=NetworkConfig)
    ssh_key: Optional["SSHKeyConfig"] = None  # SSH免密登录配置

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
            "deploy_user": self.deploy_user,
            "create_users": self.create_users,
            "jumphost": self.jumphost.to_dict() if self.jumphost else None,
            "nodes": [node.to_dict() for node in self.nodes],
            "node_batch": self.node_batch.to_dict(),
            "nfs": self.nfs.to_dict(),
            "time_sync": self.time_sync.to_dict(),
            "network": self.network.to_dict(),
            "ssh_key": self.ssh_key.to_dict() if self.ssh_key else None,
            "node_count": self.node_count
        }
