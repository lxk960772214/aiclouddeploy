"""
配置加载器 - YAML配置解析和验证
"""

import os
import yaml
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from pathlib import Path
import re


@dataclass
class NodeAuthConfig:
    """节点认证配置"""
    auth_type: str = "key"  # key | password
    username: str = "ubuntu"
    private_key: Optional[str] = None
    password: Optional[str] = None

    def __post_init__(self):
        self._validate()

    def _validate(self):
        if self.auth_type not in ["key", "password"]:
            raise ValueError(f"认证类型必须是 'key' 或 'password', 当前: {self.auth_type}")
        if self.auth_type == "key" and not self.private_key:
            raise ValueError("密钥认证需要指定private_key路径")
        if self.auth_type == "password" and not self.password:
            raise ValueError("密码认证需要指定password")


@dataclass
class JumphostConfig:
    """跳转服务器配置"""
    host: str
    port: int = 22
    auth_type: str = "key"  # key | password
    username: str = "ubuntu"
    private_key: Optional[str] = None
    password: Optional[str] = None
    node_auth: Optional[NodeAuthConfig] = None  # 用于访问节点的认证配置

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
    filesystem: str = "ext4"
    format_disk: bool = False  # 是否格式化磁盘（默认不格式化，防止数据丢失）

    def __post_init__(self):
        self._validate()

    def _validate(self):
        if self.type not in ["single", "raid1", "raid10"]:
            raise ValueError(f"存储类型必须是 single/raid1/raid10, 当前: {self.type}")
        # 注意：对于批量节点模板，device可以稍后指定，所以这里不强制验证
        # if self.type == "single" and not self.device:
        #     raise ValueError("单盘存储需要指定device")
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
class NICMappingConfig:
    """网卡映射配置（简化版）"""
    source_pattern: str  # 源名称模式
    target_name: str  # 目标名称模板
    nic_type: str = "unknown"  # rdma | ethernet | unknown
    enabled: bool = True


@dataclass
class NICRenameConfigLoader:
    """网卡重命名配置（用于配置加载器）"""
    enabled: bool = False
    mappings: List[NICMappingConfig] = field(default_factory=list)
    create_udev_rules: bool = True
    backup_original: bool = True
    skip_if_exists: bool = True
    dry_run: bool = False


@dataclass
class NetworkConfig:
    """网络配置"""
    nics: Dict[str, NICConfig] = field(default_factory=dict)
    nic_rename: Optional[NICRenameConfigLoader] = None  # 网卡重命名配置


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


@dataclass
class ClusterConfig:
    """集群完整配置"""
    name: str = "gpu-cluster"
    description: str = ""
    jumphost: Optional[JumphostConfig] = None
    nodes: List[NodeConfig] = field(default_factory=list)
    node_batch: NodeBatchConfig = field(default_factory=NodeBatchConfig)  # 批量节点配置
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

            # 解析节点认证配置
            node_auth_raw = auth_raw.get("node_auth", {})
            node_auth = None
            if node_auth_raw:
                node_auth = NodeAuthConfig(
                    auth_type=node_auth_raw.get("type", "key"),
                    username=node_auth_raw.get("username", "ubuntu"),
                    private_key=node_auth_raw.get("private_key"),
                    password=node_auth_raw.get("password")
                )

            jumphost = JumphostConfig(
                host=jumphost_raw.get("host", ""),
                port=jumphost_raw.get("port", 22),
                auth_type=auth_raw.get("type", "key"),
                username=auth_raw.get("username", "ubuntu"),
                private_key=auth_raw.get("private_key"),
                password=auth_raw.get("password"),
                node_auth=node_auth
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
                    mount_point=storage_raw.get("mount_point", "/ssd"),
                    filesystem=storage_raw.get("filesystem", "ext4"),
                    format_disk=storage_raw.get("format_disk", False)
                )
            nodes.append(NodeConfig(
                hostname=node_raw.get("hostname", ""),
                ip=node_raw.get("ip", ""),
                roles=node_raw.get("roles", []),
                storage=storage
            ))

        # 解析批量节点配置
        node_batch_raw = raw.get("node_batch", {})

        # 解析存储模板
        storage_template_raw = node_batch_raw.get("storage_template", {})
        storage_template = None
        if storage_template_raw:
            storage_template = StorageConfig(
                type=storage_template_raw.get("type", "single"),
                device=storage_template_raw.get("device"),
                devices=storage_template_raw.get("devices", []),
                mount_point=storage_template_raw.get("mount_point", "/ssd"),
                filesystem=storage_template_raw.get("filesystem", "ext4"),
                format_disk=storage_template_raw.get("format_disk", True)
            )

        # 解析认证模板
        auth_template_raw = node_batch_raw.get("auth_template", {})
        auth_template = None
        if auth_template_raw:
            auth_template = NodeAuthConfig(
                auth_type=auth_template_raw.get("type", "key"),
                username=auth_template_raw.get("username", "ubuntu"),
                private_key=auth_template_raw.get("private_key"),
                password=auth_template_raw.get("password")
            )

        node_batch = NodeBatchConfig(
            enabled=node_batch_raw.get("enabled", False),
            hosts_file=node_batch_raw.get("hosts_file"),
            hosts_content=node_batch_raw.get("hosts_content"),
            base_hostname_prefix=node_batch_raw.get("base_hostname_prefix", "node"),
            base_ip_prefix=node_batch_raw.get("base_ip_prefix", "10.0.0"),
            count=node_batch_raw.get("count", 0),
            start_index=node_batch_raw.get("start_index", 1),
            roles=node_batch_raw.get("roles", []),
            storage_template=storage_template,
            auth_template=auth_template
        )

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

        # 解析网卡重命名配置
        nic_rename = None
        nic_rename_raw = network_raw.get("nic_rename", {})
        if nic_rename_raw:
            mappings = []
            for m in nic_rename_raw.get("mappings", []):
                mapping = NICMappingConfig(
                    source_pattern=m.get("source_pattern", ""),
                    target_name=m.get("target_name", ""),
                    nic_type=m.get("nic_type", "unknown"),
                    enabled=m.get("enabled", True)
                )
                mappings.append(mapping)

            nic_rename = NICRenameConfigLoader(
                enabled=nic_rename_raw.get("enabled", False),
                mappings=mappings,
                create_udev_rules=nic_rename_raw.get("create_udev_rules", True),
                backup_original=nic_rename_raw.get("backup_original", True),
                skip_if_exists=nic_rename_raw.get("skip_if_exists", True),
                dry_run=nic_rename_raw.get("dry_run", False)
            )

        network = NetworkConfig(nics=nics, nic_rename=nic_rename)

        # 如果启用了批量节点配置，生成批量节点
        if node_batch.enabled:
            batch_nodes = self._generate_batch_nodes(node_batch, raw.get("nodes_override", []))
            # 合并批量节点和个别节点
            all_nodes = self._merge_nodes(batch_nodes, nodes)
        else:
            all_nodes = nodes

        return ClusterConfig(
            name=cluster_raw.get("name", "gpu-cluster"),
            description=cluster_raw.get("description", ""),
            jumphost=jumphost,
            nodes=all_nodes,
            node_batch=node_batch,
            nfs=nfs,
            time_sync=time_sync,
            network=network
        )

    def _generate_batch_nodes(self, node_batch: NodeBatchConfig, overrides: List[Dict]) -> List[NodeConfig]:
        """
        生成批量节点配置

        Args:
            node_batch: 批量节点配置
            overrides: 覆盖配置列表

        Returns:
            批量节点列表
        """
        nodes = []

        # 处理hosts文件或内容
        if node_batch.hosts_file or node_batch.hosts_content:
            nodes = self._parse_hosts_batch_nodes(node_batch)
        else:
            # 基于模板生成节点
            nodes = self._generate_template_batch_nodes(node_batch)

        # 应用覆盖配置
        if overrides:
            nodes = self._apply_node_overrides(nodes, overrides)

        return nodes

    def _parse_hosts_batch_nodes(self, node_batch: NodeBatchConfig) -> List[NodeConfig]:
        """
        解析hosts格式的批量节点

        Args:
            node_batch: 批量节点配置

        Returns:
            批量节点列表
        """
        nodes = []

        try:
            from utils.hosts_parser import HostsParser
            parser = HostsParser()

            # 优先使用文件内容
            if node_batch.hosts_content:
                parsed_nodes = parser.parse_content(node_batch.hosts_content)
            elif node_batch.hosts_file:
                parsed_nodes = parser.parse_file(node_batch.hosts_file)
            else:
                return nodes

            # 转换为NodeConfig
            for parsed_node in parsed_nodes:
                storage = None
                if node_batch.storage_template:
                    # 创建存储配置的副本
                    storage = StorageConfig(
                        type=node_batch.storage_template.type,
                        device=node_batch.storage_template.device,
                        devices=node_batch.storage_template.devices.copy(),
                        mount_point=node_batch.storage_template.mount_point,
                        filesystem=node_batch.storage_template.filesystem,
                        format_disk=node_batch.storage_template.format_disk
                    )

                node = NodeConfig(
                    hostname=parsed_node['hostname'],
                    ip=parsed_node['ip'],
                    roles=node_batch.roles.copy(),
                    storage=storage
                )
                nodes.append(node)

        except ImportError:
            print("警告: 无法导入HostsParser，跳过hosts文件解析")
        except Exception as e:
            print(f"警告: 解析hosts配置失败: {e}")

        return nodes

    def _generate_template_batch_nodes(self, node_batch: NodeBatchConfig) -> List[NodeConfig]:
        """
        基于模板生成批量节点

        Args:
            node_batch: 批量节点配置

        Returns:
            批量节点列表
        """
        nodes = []

        for i in range(node_batch.start_index, node_batch.start_index + node_batch.count):
            hostname = f"{node_batch.base_hostname_prefix}{i:02d}"
            ip = f"{node_batch.base_ip_prefix}.{i}"

            storage = None
            if node_batch.storage_template:
                # 为每个节点创建存储配置的副本
                storage = StorageConfig(
                    type=node_batch.storage_template.type,
                    device=node_batch.storage_template.device,
                    devices=node_batch.storage_template.devices.copy(),
                    mount_point=node_batch.storage_template.mount_point,
                    filesystem=node_batch.storage_template.filesystem,
                    format_disk=node_batch.storage_template.format_disk
                )

            node = NodeConfig(
                hostname=hostname,
                ip=ip,
                roles=node_batch.roles.copy(),
                storage=storage
            )
            nodes.append(node)

        return nodes

    def _apply_node_overrides(self, batch_nodes: List[NodeConfig], overrides: List[Dict]) -> List[NodeConfig]:
        """
        应用节点覆盖配置

        Args:
            batch_nodes: 批量节点列表
            overrides: 覆盖配置列表

        Returns:
            应用覆盖后的节点列表
        """
        # 创建查找字典
        batch_dict = {node.hostname: node for node in batch_nodes}

        # 应用覆盖
        for override in overrides:
            hostname = override.get("hostname")
            if not hostname:
                continue

            if hostname in batch_dict:
                # 更新现有节点
                node = batch_dict[hostname]

                # 更新IP
                if "ip" in override:
                    node.ip = override["ip"]

                # 更新角色
                if "roles" in override:
                    node.roles = override["roles"]

                # 更新存储配置
                if "storage" in override:
                    storage_raw = override["storage"]
                    if node.storage:
                        # 更新现有存储配置
                        if "type" in storage_raw:
                            node.storage.type = storage_raw["type"]
                        if "device" in storage_raw:
                            node.storage.device = storage_raw["device"]
                        if "devices" in storage_raw:
                            node.storage.devices = storage_raw["devices"]
                        if "mount_point" in storage_raw:
                            node.storage.mount_point = storage_raw["mount_point"]
                        if "filesystem" in storage_raw:
                            node.storage.filesystem = storage_raw["filesystem"]
                        if "format_disk" in storage_raw:
                            node.storage.format_disk = storage_raw["format_disk"]
                    elif storage_raw:
                        # 创建新的存储配置
                        node.storage = StorageConfig(
                            type=storage_raw.get("type", "single"),
                            device=storage_raw.get("device"),
                            devices=storage_raw.get("devices", []),
                            mount_point=storage_raw.get("mount_point", "/ssd"),
                            filesystem=storage_raw.get("filesystem", "ext4"),
                            format_disk=storage_raw.get("format_disk", False)
                        )
            else:
                # 添加新节点
                storage_raw = override.get("storage", {})
                storage = None
                if storage_raw:
                    storage = StorageConfig(
                        type=storage_raw.get("type", "single"),
                        device=storage_raw.get("device"),
                        devices=storage_raw.get("devices", []),
                        mount_point=storage_raw.get("mount_point", "/ssd"),
                        filesystem=storage_raw.get("filesystem", "ext4"),
                        format_disk=storage_raw.get("format_disk", False)
                    )

                node = NodeConfig(
                    hostname=hostname,
                    ip=override.get("ip", ""),
                    roles=override.get("roles", []),
                    storage=storage
                )
                batch_dict[hostname] = node

        return list(batch_dict.values())

    def _merge_nodes(self, batch_nodes: List[NodeConfig], individual_nodes: List[NodeConfig]) -> List[NodeConfig]:
        """
        合并批量节点和个别节点

        Args:
            batch_nodes: 批量节点列表
            individual_nodes: 个别节点列表

        Returns:
            合并后的节点列表
        """
        # 创建查找字典
        node_dict = {}

        # 先添加批量节点
        for node in batch_nodes:
            node_dict[node.hostname] = node

        # 添加或覆盖个别节点
        for node in individual_nodes:
            node_dict[node.hostname] = node

        return list(node_dict.values())

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

        # 验证节点配置
        if self.cluster_config.node_batch.enabled:
            # 批量节点验证
            if not self.cluster_config.node_batch.hosts_file and not self.cluster_config.node_batch.hosts_content:
                if self.cluster_config.node_batch.count <= 0:
                    errors.append("批量节点数量必须大于0")
                if not self.cluster_config.node_batch.base_hostname_prefix:
                    errors.append("批量节点主机名前缀不能为空")
                if not self.cluster_config.node_batch.base_ip_prefix:
                    errors.append("批量节点IP前缀不能为空")
        else:
            # 传统节点验证
            if not self.cluster_config.nodes:
                errors.append("集群节点列表为空")
            else:
                # 验证每个节点
                for i, node in enumerate(self.cluster_config.nodes):
                    if not node.hostname:
                        errors.append(f"节点[{i}]主机名不能为空")
                    if not node.ip:
                        errors.append(f"节点[{i}]IP地址不能为空")
                    if node.storage:
                        try:
                            node.storage._validate()
                        except ValueError as e:
                            errors.append(f"节点[{i}]存储配置错误: {e}")

        return errors

    def get_nfs_server_node(self) -> Optional[NodeConfig]:
        """获取NFS服务器节点"""
        if not self.cluster_config:
            return None
        for node in self.cluster_config.nodes:
            if "nfs_server" in node.roles:
                return node
        return None

    def get_time_server_node(self) -> Optional[NodeConfig]:
        """获取时间服务器节点"""
        if not self.cluster_config:
            return None
        for node in self.cluster_config.nodes:
            if "time_server" in node.roles:
                return node
        return None

    def get_gpu_nodes(self) -> List[NodeConfig]:
        """获取GPU节点列表"""
        if not self.cluster_config:
            return []
        return [node for node in self.cluster_config.nodes if "gpu_node" in node.roles]

    def get_client_nodes(self) -> List[NodeConfig]:
        """获取客户端节点列表（非NFS服务器节点）"""
        if not self.cluster_config:
            return []
        return [node for node in self.cluster_config.nodes if "nfs_server" not in node.roles]

    def get_node_by_hostname(self, hostname: str) -> Optional[NodeConfig]:
        """根据主机名获取节点配置"""
        if not self.cluster_config:
            return None
        for node in self.cluster_config.nodes:
            if node.hostname == hostname:
                return node
        return None

    def get_node_by_ip(self, ip: str) -> Optional[NodeConfig]:
        """根据IP地址获取节点配置"""
        if not self.cluster_config:
            return None
        for node in self.cluster_config.nodes:
            if node.ip == ip:
                return node
        return None

    def get_all_ips(self) -> List[str]:
        """获取所有节点的IP地址"""
        if not self.cluster_config:
            return []
        return [node.ip for node in self.cluster_config.nodes]

    def get_all_hostnames(self) -> List[str]:
        """获取所有节点的主机名"""
        if not self.cluster_config:
            return []
        return [node.hostname for node in self.cluster_config.nodes]

    def get_node_auth_config(self, node_hostname: str) -> Optional[NodeAuthConfig]:
        """
        获取节点的认证配置

        Args:
            node_hostname: 节点主机名

        Returns:
            节点的认证配置，如果未配置则返回jumphost的node_auth
        """
        if not self.cluster_config or not self.cluster_config.jumphost:
            return None

        # 首先检查节点是否有特定的认证配置
        # (此功能可以后续扩展)

        # 返回跳转服务器的节点认证配置
        return self.cluster_config.jumphost.node_auth


def load_configs(config_dir: str = "config") -> tuple:
    """便捷函数：加载所有配置"""
    loader = ConfigLoader(config_dir)
    cluster = loader.load_cluster_config()
    versions = loader.load_versions_config()
    errors = loader.validate()

    if errors:
        raise ValueError(f"配置验证失败: {errors}")

    return cluster, versions, loader
