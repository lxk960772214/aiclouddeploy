"""
配置加载器 - YAML配置解析和验证
"""

import os
import yaml
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class JumphostConfig:
    """跳转服务器配置"""
    host: str
    port: int = 22
    auth_type: str = "key"  # key | password
    username: str = "ubuntu"
    private_key: Optional[str] = None
    password: Optional[str] = None

    def __post_init__(self):
        self._validate()

    def _validate(self):
        if not self.host:
            raise ValueError("跳转服务器host不能为空")
        if self.auth_type not in ["key", "password"]:
            raise ValueError(f"认证类型必须是 'key' 或 'password', 当前: {self.auth_type}")
        if self.auth_type == "key" and not self.private_key:
            raise ValueError("密钥认证需要指定private_key路径")
        if self.auth_type == "password" and not self.password:
            raise ValueError("密码认证需要指定password")


@dataclass
class StorageConfig:
    """存储配置"""
    type: str = "single"  # single | raid1 | raid10
    device: Optional[str] = None
    devices: List[str] = field(default_factory=list)
    mount_point: str = "/ssd"

    def __post_init__(self):
        self._validate()

    def _validate(self):
        if self.type not in ["single", "raid1", "raid10"]:
            raise ValueError(f"存储类型必须是 single/raid1/raid10, 当前: {self.type}")
        if self.type == "single" and not self.device:
            raise ValueError("单盘存储需要指定device")
        if self.type in ["raid1", "raid10"] and len(self.devices) < 2:
            raise ValueError(f"{self.type}需要至少2个设备")


@dataclass
class NodeConfig:
    """集群节点配置"""
    hostname: str
    ip: str
    roles: List[str] = field(default_factory=list)
    storage: Optional[StorageConfig] = None

    def __post_init__(self):
        self._validate()

    def _validate(self):
        if not self.hostname:
            raise ValueError("节点hostname不能为空")
        if not self.ip:
            raise ValueError("节点ip不能为空")
        valid_roles = ["nfs_server", "time_server", "gpu_node"]
        for role in self.roles:
            if role not in valid_roles:
                raise ValueError(f"无效的角色: {role}, 有效角色: {valid_roles}")


@dataclass
class NFSConfig:
    """NFS配置"""
    enabled: bool = True
    server: Optional[str] = None
    export_path: str = "/ssd/nfs"
    client_mount: str = "/data"
    client_ips: List[str] = field(default_factory=list)


@dataclass
class TimeSyncConfig:
    """时间同步配置"""
    server: Optional[str] = None
    timezone: str = "Asia/Shanghai"


@dataclass
class NICConfig:
    """网卡配置"""
    pattern: str
    count: int
    net_prefix: str


@dataclass
class NetworkConfig:
    """网络配置"""
    nics: Dict[str, NICConfig] = field(default_factory=dict)


@dataclass
class KernelConfig:
    """内核配置"""
    mode: str = "keep"  # keep | specify
    keep: Dict[str, Any] = field(default_factory=lambda: {"lock_version": True, "update_grub": True})
    specify: Dict[str, Any] = field(default_factory=lambda: {"version": None})

    def __post_init__(self):
        self._validate()

    def _validate(self):
        if self.mode not in ["keep", "specify"]:
            raise ValueError(f"内核模式必须是 keep 或 specify, 当前: {self.mode}")
        if self.mode == "specify" and not self.specify.get("version"):
            raise ValueError("specify模式需要指定version")


@dataclass
class CudaConfig:
    """CUDA配置"""
    version: str = "12.8"
    toolkit_file: Optional[str] = None
    download_url: Optional[str] = None
    local_file: Optional[str] = None


@dataclass
class NvidiaDriverConfig:
    """NVIDIA驱动配置"""
    version: str = "590.48.01"
    file: Optional[str] = None
    download_url: Optional[str] = None
    local_file: Optional[str] = None


@dataclass
class MlnxOfedConfig:
    """MLNX_OFED配置"""
    version: str = "24.10-2.1.8.0"
    file: Optional[str] = None
    download_url: Optional[str] = None
    local_file: Optional[str] = None


@dataclass
class OpenSSHConfig:
    """OpenSSH配置"""
    min_version: str = "1:8.9p1-3ubuntu0.10"
    auto_upgrade: bool = True


@dataclass
class NCCLConfig:
    """NCCL配置"""
    enabled: bool = False
    install_method: str = "source"  # source | package
    install_path: str = "/home/ubuntu/nccl"


@dataclass
class VersionsConfig:
    """软件版本配置"""
    cuda: CudaConfig = field(default_factory=CudaConfig)
    nvidia_driver: NvidiaDriverConfig = field(default_factory=NvidiaDriverConfig)
    mlnx_ofed: MlnxOfedConfig = field(default_factory=MlnxOfedConfig)
    kernel: KernelConfig = field(default_factory=KernelConfig)
    openssh: OpenSSHConfig = field(default_factory=OpenSSHConfig)
    nccl: NCCLConfig = field(default_factory=NCCLConfig)


@dataclass
class ClusterConfig:
    """集群完整配置"""
    name: str = "gpu-cluster"
    description: str = ""
    jumphost: Optional[JumphostConfig] = None
    nodes: List[NodeConfig] = field(default_factory=list)
    nfs: NFSConfig = field(default_factory=NFSConfig)
    time_sync: TimeSyncConfig = field(default_factory=TimeSyncConfig)
    network: NetworkConfig = field(default_factory=NetworkConfig)


class ConfigLoader:
    """配置加载器"""

    def __init__(self, config_dir: str = "config"):
        self.config_dir = Path(config_dir)
        self.cluster_config: Optional[ClusterConfig] = None
        self.versions_config: Optional[VersionsConfig] = None

    def load_cluster_config(self, filename: str = "cluster.yaml") -> ClusterConfig:
        """加载集群配置"""
        config_path = self.config_dir / filename

        if not config_path.exists():
            raise FileNotFoundError(f"配置文件不存在: {config_path}")

        with open(config_path, 'r', encoding='utf-8') as f:
            raw_config = yaml.safe_load(f)

        self.cluster_config = self._parse_cluster_config(raw_config)
        return self.cluster_config

    def load_versions_config(self, filename: str = "versions.yaml") -> VersionsConfig:
        """加载版本配置"""
        config_path = self.config_dir / filename

        if not config_path.exists():
            raise FileNotFoundError(f"配置文件不存在: {config_path}")

        with open(config_path, 'r', encoding='utf-8') as f:
            raw_config = yaml.safe_load(f)

        self.versions_config = self._parse_versions_config(raw_config)
        return self.versions_config

    def _parse_cluster_config(self, raw: Dict) -> ClusterConfig:
        """解析集群配置"""
        cluster_raw = raw.get("cluster", {})

        # 解析跳转服务器
        jumphost_raw = raw.get("jumphost", {})
        jumphost = None
        if jumphost_raw:
            auth_raw = jumphost_raw.get("auth", {})
            jumphost = JumphostConfig(
                host=jumphost_raw.get("host", ""),
                port=jumphost_raw.get("port", 22),
                auth_type=auth_raw.get("type", "key"),
                username=auth_raw.get("username", "ubuntu"),
                private_key=auth_raw.get("private_key"),
                password=auth_raw.get("password")
            )

        # 解析节点列表
        nodes = []
        for node_raw in raw.get("nodes", []):
            storage_raw = node_raw.get("storage", {})
            storage = None
            if storage_raw:
                storage = StorageConfig(
                    type=storage_raw.get("type", "single"),
                    device=storage_raw.get("device"),
                    devices=storage_raw.get("devices", []),
                    mount_point=storage_raw.get("mount_point", "/ssd")
                )
            nodes.append(NodeConfig(
                hostname=node_raw.get("hostname", ""),
                ip=node_raw.get("ip", ""),
                roles=node_raw.get("roles", []),
                storage=storage
            ))

        # 解析NFS配置
        nfs_raw = raw.get("nfs", {})
        nfs = NFSConfig(
            enabled=nfs_raw.get("enabled", True),
            server=nfs_raw.get("server"),
            export_path=nfs_raw.get("export_path", "/ssd/nfs"),
            client_mount=nfs_raw.get("client_mount", "/data"),
            client_ips=nfs_raw.get("client_ips", [])
        )

        # 解析时间同步
        time_sync_raw = raw.get("time_sync", {})
        time_sync = TimeSyncConfig(
            server=time_sync_raw.get("server"),
            timezone=time_sync_raw.get("timezone", "Asia/Shanghai")
        )

        # 解析网络配置
        network_raw = raw.get("network", {})
        nics = {}
        for nic_name, nic_raw in network_raw.get("nics", {}).items():
            nics[nic_name] = NICConfig(
                pattern=nic_raw.get("pattern", ""),
                count=nic_raw.get("count", 0),
                net_prefix=nic_raw.get("net_prefix", "")
            )
        network = NetworkConfig(nics=nics)

        return ClusterConfig(
            name=cluster_raw.get("name", "gpu-cluster"),
            description=cluster_raw.get("description", ""),
            jumphost=jumphost,
            nodes=nodes,
            nfs=nfs,
            time_sync=time_sync,
            network=network
        )

    def _parse_versions_config(self, raw: Dict) -> VersionsConfig:
        """解析版本配置"""
        # 解析CUDA
        cuda_raw = raw.get("cuda", {})
        cuda = CudaConfig(
            version=cuda_raw.get("version", "12.8"),
            toolkit_file=cuda_raw.get("toolkit_file"),
            download_url=cuda_raw.get("download_url"),
            local_file=cuda_raw.get("local_file")
        )

        # 解析NVIDIA驱动
        driver_raw = raw.get("nvidia_driver", {})
        nvidia_driver = NvidiaDriverConfig(
            version=driver_raw.get("version", "590.48.01"),
            file=driver_raw.get("file"),
            download_url=driver_raw.get("download_url"),
            local_file=driver_raw.get("local_file")
        )

        # 解析MLNX_OFED
        mlnx_raw = raw.get("mlnx_ofed", {})
        mlnx_ofed = MlnxOfedConfig(
            version=mlnx_raw.get("version", "24.10-2.1.8.0"),
            file=mlnx_raw.get("file"),
            download_url=mlnx_raw.get("download_url"),
            local_file=mlnx_raw.get("local_file")
        )

        # 解析内核配置
        kernel_raw = raw.get("kernel", {})
        kernel = KernelConfig(
            mode=kernel_raw.get("mode", "keep"),
            keep=kernel_raw.get("keep", {"lock_version": True, "update_grub": True}),
            specify=kernel_raw.get("specify", {"version": None})
        )

        # 解析OpenSSH
        openssh_raw = raw.get("openssh", {})
        openssh = OpenSSHConfig(
            min_version=openssh_raw.get("min_version", "1:8.9p1-3ubuntu0.10"),
            auto_upgrade=openssh_raw.get("auto_upgrade", True)
        )

        # 解析NCCL
        nccl_raw = raw.get("nccl", {})
        nccl = NCCLConfig(
            enabled=nccl_raw.get("enabled", False),
            install_method=nccl_raw.get("install_method", "source"),
            install_path=nccl_raw.get("install_path", "/home/ubuntu/nccl")
        )

        return VersionsConfig(
            cuda=cuda,
            nvidia_driver=nvidia_driver,
            mlnx_ofed=mlnx_ofed,
            kernel=kernel,
            openssh=openssh,
            nccl=nccl
        )

    def validate(self) -> List[str]:
        """验证配置完整性"""
        errors = []

        if not self.cluster_config:
            errors.append("集群配置未加载")
            return errors

        if not self.cluster_config.jumphost:
            errors.append("跳转服务器配置缺失")
        else:
            if not self.cluster_config.jumphost.host:
                errors.append("跳转服务器IP未配置")

        if not self.cluster_config.nodes:
            errors.append("集群节点列表为空")

        return errors

    def get_nfs_server_node(self) -> Optional[NodeConfig]:
        """获取NFS服务器节点"""
        for node in self.cluster_config.nodes:
            if "nfs_server" in node.roles:
                return node
        return None

    def get_time_server_node(self) -> Optional[NodeConfig]:
        """获取时间服务器节点"""
        for node in self.cluster_config.nodes:
            if "time_server" in node.roles:
                return node
        return None

    def get_gpu_nodes(self) -> List[NodeConfig]:
        """获取GPU节点列表"""
        return [node for node in self.cluster_config.nodes if "gpu_node" in node.roles]

    def get_client_nodes(self) -> List[NodeConfig]:
        """获取客户端节点列表（非NFS服务器节点）"""
        return [node for node in self.cluster_config.nodes if "nfs_server" not in node.roles]


def load_configs(config_dir: str = "config") -> tuple:
    """便捷函数：加载所有配置"""
    loader = ConfigLoader(config_dir)
    cluster = loader.load_cluster_config()
    versions = loader.load_versions_config()
    errors = loader.validate()

    if errors:
        raise ValueError(f"配置验证失败: {errors}")

    return cluster, versions, loader
