# 发现和问题记录

## 代码库发现

### 现有架构分析

#### 1. 网络配置现状
**文件**: `src/models/cluster.py`, `src/config_loader.py`

当前网络配置结构：
```python
@dataclass
class NetworkConfig:
    compute_nics: List[str] = field(default_factory=list)
    storage_nics: List[str] = field(default_factory=list)
    management_nics: List[str] = field(default_factory=list)
    nics: Dict[str, NICConfig] = field(default_factory=dict)
    nic_rename: Optional[NICRenameConfig] = None
```

**发现**：
- 已有compute_nics/storage_nics/management_nics字段，但只是简单的字符串列表
- nics字典存储的是pattern匹配配置
- 缺少RDMA设备关联和性能测试参数

#### 2. NFS配置现状
**文件**: `src/steps/step_34_nfs_config.py`

当前实现：
- 使用`nfs_server.ip`作为NFS服务器地址
- 没有区分存储网和管理网IP
- 直接在配置中硬编码IP使用方式

**改进点**：
- 需要根据网络配置智能选择IP
- 存储网存在时使用存储网IP
- 日志记录使用的网络类型

#### 3. 连通性检查现状
**文件**: `src/network/connectivity_checker.py`

已实现：
- IP层连通性检查（ping）
- DNS解析检查
- HTTP连接检查

**缺失**：
- RDMA设备检测
- ib_write_bw带宽测试
- 跨主机网卡互通测试

#### 4. 参考实现分析
**文件**: `/mnt/e/github/roce-checker/roce_checker.py`

关键功能：
1. **RDMA设备检测**：
   - `RDMADeviceDetector`类
   - 支持ibv_devinfo和rdma link两种检测方式
   - 区分RoCE/RoCEv2/InfiniBand

2. **ib_write_bw测试**：
   - `IBWriteBWTester`类
   - 支持RoCE(-R参数)和IB模式
   - 自动计算端口号
   - 解析带宽结果

3. **三轮测试策略**：
   - `ThreePhaseLocator`类
   - 相邻配对、错位配对、异常定位
   - 并发执行

4. **配置加载**：
   - 支持只写主机名，自动解析IP
   - 网络类型分离配置

## 设计决策

### 1. 数据模型扩展方案

**决策**：扩展现有NetworkConfig而非替换

```python
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

@dataclass
class IBWriteBWConfig:
    """ib_write_bw测试参数"""
    duration: int = 10
    size: int = 65536
    port_base: int = 18500
    min_bandwidth_percent: float = 90.0

@dataclass
class NetworkConfig:
    """扩展后的网络配置"""
    # 新格式
    management: Optional[NetworkTypeConfig] = None
    compute: Optional[NetworkTypeConfig] = None
    storage: Optional[NetworkTypeConfig] = None
    ib_write_bw: Optional[IBWriteBWConfig] = None

    # 保留旧格式兼容
    nics: Dict[str, NICConfig] = field(default_factory=dict)
    nic_rename: Optional[NICRenameConfig] = None
```

**理由**：
- 向后兼容
- 清晰的网络类型分离
- 支持独立配置

### 2. IP选择策略

**决策**：创建独立的IPResolver类

```python
class IPResolver:
    def get_ip_for_interface(self, host: str, interface: str) -> Optional[str]:
        """根据网卡名获取IP"""

    def get_ip_for_network(self, host: str, network_type: str) -> Optional[str]:
        """根据网络类型获取IP"""

    def get_ip_for_purpose(self, host: str, purpose: str) -> Optional[str]:
        """根据用途获取IP"""
```

**用途映射**：
- `storage_nfs`: 存储网IP（无则管理网）
- `package_transfer`: 管理网IP
- `ssh_connection`: 管理网IP

### 3. 测试模块架构

**决策**：分层设计，可独立使用

```
Layer 1: 基础组件
├── RDMA设备检测器
├── IP解析器
└── ib_write_bw测试器

Layer 2: 测试策略
├── 三轮测试策略
└── 部署验证器

Layer 3: 集成入口
├── 独立测试步骤
└── CLI入口
```

## 待解决问题

### 问题1：并发测试端口冲突
**状态**：待解决

**描述**：多对主机同时测试时，ib_write_bw端口可能冲突

**方案**：
```python
# 基于网卡名称计算唯一端口
port = port_base + hash(interface) % 1000
# 或
iface_num = re.search(r'(\d+)', interface)
port = port_base + int(iface_num.group(1)) * 10
```

### 问题2：远程主机IP获取
**状态**：待解决

**描述**：需要从远程主机获取指定网卡的IP

**方案**：
```python
cmd = f"ip -j addr show {interface}"
# 解析JSON输出获取IPv4地址
```

### 问题3：配置迁移
**状态**：待解决

**描述**：现有配置文件需要迁移到新格式

**方案**：
1. 自动检测配置格式
2. 自动转换旧格式到新格式
3. 提供迁移脚本

## 改进建议

### 1. 统一日志格式
建议所有模块使用统一的日志格式：
```
[{step_id}] [{host}] {action}: {result}
```

### 2. 错误处理增强
建议添加更详细的错误上下文：
- 主机名/IP
- 网卡名称
- 执行的命令
- 预期结果
- 实际结果

### 3. 测试报告统一
建议创建统一的报告生成器：
- Markdown格式
- HTML格式
- JSON格式

## 参考代码片段

### RDMA设备类型检测
```python
def _get_device_type(self, host: str, rdma_device: str) -> RDMADeviceType:
    cmd = f"cat /sys/class/infiniband/{rdma_device}/transport 2>/dev/null"
    code, stdout, stderr = self.executor.execute(host, cmd)
    if code == 0:
        transport = stdout.strip()
        if 'RoCE' in transport:
            return RDMADeviceType.ROCE
        elif 'InfiniBand' in transport:
            return RDMADeviceType.INFINIBAND
    return RDMADeviceType.UNKNOWN
```

### ib_write_bw命令构建
```python
if device_type == RDMADeviceType.INFINIBAND:
    server_cmd = f"ib_write_bw -d {server_device} -F -s {self.size} -D {self.duration} -p {port}"
    client_cmd = f"ib_write_bw -d {client_device} -F -s {self.size} -D {self.duration} -p {port} {server_hostname}"
else:  # RoCE
    server_cmd = f"ib_write_bw -d {server_device} -R -F -s {self.size} -D {self.duration} -p {port}"
    client_cmd = f"ib_write_bw -d {client_device} -R -F -s {self.size} -D {self.duration} -p {port} {server_hostname}"
```

### 三轮配对生成
```python
def _generate_round1_pairs(self) -> List[Tuple[HostConfig, HostConfig]]:
    """相邻配对 (1,2), (3,4), (5,6)..."""
    pairs = []
    for i in range(0, len(self.hosts) - 1, 2):
        pairs.append((self.hosts[i], self.hosts[i + 1]))
    return pairs

def _generate_round2_pairs(self) -> List[Tuple[HostConfig, HostConfig]]:
    """错位配对 (2,3), (4,5), (6,7)..."""
    pairs = []
    start = 0 if len(self.hosts) % 2 == 0 else 1
    for i in range(start, len(self.hosts) - 1, 2):
        pairs.append((self.hosts[i], self.hosts[i + 1]))
    if len(self.hosts) > 2 and len(self.hosts) % 2 == 0:
        pairs.append((self.hosts[-1], self.hosts[0]))
    return pairs
```
