# GPU Cluster Deploy

GPU 集群环境自动化部署工具，支持大规模 GPU 集群的批量配置、设备一致性检查和模块化部署。

## 功能特性

| 特性 | 描述 |
|------|------|
| **跳转服务器支持** | 通过堡垒机访问内网集群，支持密钥/密码认证 |
| **批量节点配置** | hosts 文件、模板生成、YAML 配置三种方式 |
| **设备一致性检查** | 部署前检查 RDMA/GPU/NVMe 设备集群一致性 |
| **网络测试模块** | 三轮测试策略定位异常 RDMA 设备，支持带宽测试和连通性检查 |
| **模块化部署** | 按阶段/步骤/模块/分类/计划灵活执行 |
| **安装包管理器** | 自动下载、分发、校验，支持 download_url 和 local_file 两种模式 |
| **磁盘格式化选项** | 支持 single/RAID1/RAID10，可配置格式化策略 |
| **多版本软件栈** | CUDA、NVIDIA 驱动、MLNX_OFED 版本可配置 |
| **执行计划文件** | YAML 格式的执行计划导入导出 |
| **详细日志报告** | 结构化日志、进度追踪、HTML 报告 |

## 目录结构

```
gpu-cluster-deploy/
├── config/                          # 配置文件目录
│   ├── cluster.yaml                 # 集群配置（节点、网络、存储）
│   ├── versions.yaml                # 软件版本配置
│   ├── cluster_batch_example.yaml   # 批量节点配置示例
│   └── plans/                       # 执行计划目录
│       ├── gpu-only.yaml            # 仅 GPU 相关模块计划
│       └── full-deployment.yaml     # 完整部署计划
├── src/                             # 源代码目录
│   ├── main.py                      # 主入口
│   ├── config_loader.py             # 配置加载器
│   ├── ssh_manager.py               # SSH 连接管理
│   ├── batch_executor.py            # 批量命令执行
│   ├── package_manager.py           # 安装包管理器
│   ├── cli/                         # CLI 模块
│   │   ├── main.py                  # CLI 主入口
│   │   ├── execution_controller.py  # 执行控制器
│   │   ├── progress_reporter.py     # 进度报告器
│   │   └── network_test_cli.py      # 网络测试 CLI
│   ├── deployment/                  # 部署框架
│   │   ├── core.py                  # 核心类定义
│   │   ├── module_manager.py        # 模块管理器
│   │   ├── execution_plan.py        # 执行计划
│   │   └── step_adapter.py          # 步骤适配器
│   ├── models/                      # 数据模型
│   │   ├── cluster.py               # 集群模型
│   │   ├── node.py                  # 节点模型
│   │   ├── network.py               # 网络模型
│   │   ├── module.py                # 模块模型
│   │   └── device_check.py          # 设备检查模型
│   ├── network/                     # 网络配置模块
│   │   ├── device_discovery.py      # 设备发现
│   │   ├── device_checker.py        # 设备一致性检查
│   │   ├── gpu_topo_checker.py      # GPU 拓扑检查
│   │   ├── nic_mapper.py            # 网卡映射
│   │   ├── nic_renamer.py           # 网卡重命名
│   │   ├── ibdev_parser.py          # IB 设备解析
│   │   ├── fix_suggestions.py       # 修复建议生成
│   │   ├── connectivity_checker.py  # 网络连通性检查
│   │   ├── rdma_detector.py         # RDMA 设备检测
│   │   ├── ibandwidth_tester.py     # IB 带宽测试
│   │   ├── roce_ping_tester.py      # RoCE Ping 连通性测试
│   │   ├── three_phase_tester.py    # 三轮测试策略
│   │   ├── ip_resolver.py           # IP 解析器
│   │   └── deployment_verifier.py   # 部署验证器
│   ├── steps/                       # 部署步骤实现
│   │   ├── base.py                  # 步骤基类
│   │   ├── step_0_device_check.py   # 设备一致性检查
│   │   ├── step_0b_network_check.py # 网络连通性检查
│   │   ├── step_0c_network_rdma_test.py # RDMA 网络测试
│   │   ├── step_final_verification.py # 部署验证
│   │   ├── step_1_dependencies.py   # 依赖安装
│   │   ├── step_2_kernel_check.py   # 内核检查
│   │   ├── step_3_glibc_check.py    # glibc 检查
│   │   ├── step_4_openssh_check.py  # OpenSSH 检查
│   │   ├── step_5_sudo_nopasswd.py  # Sudo 免密配置
│   │   ├── step_6_disk_mount.py     # 磁盘挂载
│   │   ├── step_7_msr_settings.py   # MSR 设置
│   │   ├── step_8_rc_local.py       # rc.local 配置
│   │   ├── step_9_hostname_hosts.py # 主机名配置
│   │   ├── step_10_create_user.py   # 用户创建
│   │   ├── step_0d_ssh_key.py       # SSH 免密配置
│   │   ├── step_12_cpu_performance.py # CPU 性能模式
│   │   ├── step_13_file_limits.py   # 文件描述符限制
│   │   ├── step_15_disable_autoupdate.py # 禁用自动更新
│   │   ├── step_16_lock_kernel.py   # 锁定内核
│   │   ├── step_17_timezone.py      # 时区设置
│   │   ├── step_18_disable_ipv6.py  # 禁用 IPv6
│   │   ├── step_19_vmcore_hibernate.py # vmcore/休眠配置
│   │   ├── step_20_mlnx_ofed.py     # MLNX OFED 安装
│   │   ├── step_21_disable_nouveau.py # 禁用 Nouveau
│   │   ├── step_22_nvidia_driver.py # NVIDIA 驱动安装
│   │   ├── step_23_fabricmanager.py # Fabric Manager 安装
│   │   ├── step_24_cuda_toolkit.py  # CUDA 工具包安装
│   │   ├── step_25_nccl.py          # NCCL 安装
│   │   ├── step_26_rdma_rename.py   # RDMA 网卡重命名
│   │   ├── step_26b_ethernet_rename.py # 以太网卡重命名
│   │   ├── step_27_gpu_persistence.py # GPU 持久化模式
│   │   ├── step_28_nvidia_modules.py # NVIDIA 内核模块
│   │   ├── step_29_disable_acs.py   # 禁用 ACS
│   │   ├── step_30_time_sync.py     # 时间同步
│   │   └── step_34_nfs_config.py    # NFS 配置
│   └── utils/                       # 工具函数
│       ├── logger.py                # 日志模块
│       └── hosts_parser.py          # hosts 文件解析
├── tests/                           # 测试目录
│   ├── test_config_loader.py        # 配置加载测试
│   ├── test_batch_executor.py       # 批量执行测试
│   ├── test_ssh_manager.py          # SSH 管理测试
│   ├── test_device_check.py         # 设备检查测试
│   ├── test_module_manager.py       # 模块管理测试
│   ├── test_network_config.py       # 网络配置测试
│   ├── test_connectivity_checker.py # 连通性检查测试
│   ├── test_network_modules.py      # 网络模块测试
│   ├── test_cli.py                  # CLI 测试
│   └── integration/                 # 集成测试
├── logs/                            # 日志输出目录
└── requirements.txt                 # Python 依赖
```

## 快速开始

### 1. 安装依赖

```bash
cd gpu-cluster-deploy
pip install -r requirements.txt
```

依赖列表：
- `paramiko >= 3.0.0` - SSH 连接库
- `PyYAML >= 6.0` - YAML 解析
- `colorama >= 0.4.6` - 终端颜色输出

### 2. 配置集群

编辑 `config/cluster.yaml`：

```yaml
# 集群基础配置
cluster:
  name: "gpu-cluster-001"
  description: "生产环境GPU集群"
  deploy_user: "ubuntu"     # 部署用户（可选，默认使用登录用户）

# SSH 免密配置（可选）
ssh_key:
  enabled: true             # 是否启用免密配置（默认 true）
  users:                    # 要配置免密的用户列表（可选，默认自动检测部署用户）
    - ubuntu
  # private_key: "~/.ssh/id_rsa"  # 指定私钥路径（可选）
  # public_key: "~/.ssh/id_rsa.pub"  # 指定公钥路径（可选）

# 跳转服务器配置
jumphost:
  host: "1.2.3.4"           # 公网IP（必填）
  port: 22                   # SSH端口
  # 认证配置（支持两种格式）
  # 格式一：嵌套格式
  auth:
    type: "key"              # key | password
    username: "ubuntu"
    private_key: "~/.ssh/id_rsa"
    # 或密码认证（二选一）
    # password: "your-password"
  # 格式二：扁平格式（向后兼容）
  # username: "ubuntu"
  # password: "your-password"
  # private_key: "~/.ssh/id_rsa"

  # 节点认证配置（可选，用于访问内网节点）
  # 如果不配置，将使用与跳转服务器相同的认证
  node_auth:
    type: "password"         # key | password
    username: "ubuntu"
    password: "node-password"
    # 或使用密钥
    # private_key: "~/.ssh/node_key"

# 节点配置
nodes:
  # NFS Server 节点
  - hostname: "gpu-master"
    ip: "10.254.43.65"
    username: "root"        # 登录用户（必须指定）
    password: "root-password"  # 登录密码或私钥
    roles:
      - nfs_server
      - time_server
    storage:
      type: "raid10"         # single | raid1 | raid10
      devices:
        - "/dev/nvme0n1"
        - "/dev/nvme1n1"
        - "/dev/nvme2n1"
        - "/dev/nvme3n1"
      mount_point: "/ssd"
      format_disk: false     # 安全默认：不格式化
    # 节点级别认证（可选，覆盖默认认证）
    # username: "ubuntu"
    # password: "specific-password"
    # private_key: "~/.ssh/gpu-master-key"

  # GPU 计算节点
  - hostname: "gpu-node-01"
    ip: "10.254.43.66"
    username: "root"        # 登录用户
    password: "root-password"
    roles:
      - gpu_node
    storage:
      type: "single"
      device: "/dev/nvme0n1"
      mount_point: "/ssd"
      format_disk: false

  # 不同密码的节点示例
  - hostname: "gpu-node-02"
    ip: "10.254.43.67"
    username: "root"        # 登录用户
    password: "different-pwd" # 不同的密码
    roles:
      - gpu_node
    storage:
      type: "single"
      device: "/dev/nvme0n1"
      mount_point: "/ssd"
      format_disk: false
```

### 3. 配置软件版本

编辑 `config/versions.yaml`：

```yaml
# CUDA 配置
cuda:
  version: "12.8"
  toolkit_file: "cuda_12.8.0_570.86.10_linux.run"

# NVIDIA 驱动配置
nvidia_driver:
  version: "590.48.01"
  file: "NVIDIA-Linux-x86_64-590.48.01.run"

# MLNX_OFED 驱动配置
mlnx_ofed:
  version: "24.10-2.1.8.0"
  file: "MLNX_OFED_LINUX-24.10-2.1.8.0-ubuntu22.04-x86_64.tgz"

# 内核配置
kernel:
  mode: "keep"              # keep | specify
  keep:
    lock_version: true      # 锁定当前内核版本
    update_grub: true       # 更新 GRUB 固定启动版本

# OpenSSH 配置
openssh:
  min_version: "1:8.9p1-3ubuntu0.10"  # CVE-2024-6387 修复版本
  auto_upgrade: true
```

#### 安装包来源配置

支持两种主要模式指定安装包位置：

**模式一：download_url（登录服务器下载）**

在登录服务器（跳转服务器）上下载安装包，然后分发到GPU节点：
- 适合登录服务器有外网访问权限的场景
- 只需下载一次，自动分发到所有GPU节点
- 如果登录服务器同时是GPU节点，自动跳过本机传输

```yaml
cuda:
  version: "12.8"
  download_url: "https://developer.download.nvidia.com/compute/cuda/12.8.0/local_installers/cuda_12.8.0_570.86.10_linux.run"

nvidia_driver:
  version: "590.48.01"
  download_url: "https://us.download.nvidia.com/XFree86/Linux-x86_64/590.48.01/NVIDIA-Linux-x86_64-590.48.01.run"
```

分发流程：
1. 在登录服务器下载到 `/tmp/` 目录
2. 从登录服务器传输到各GPU节点
3. 登录服务器同时是GPU节点时跳过步骤2

**模式二：local_file（本机文件上传）**

安装包放在运行部署工具的本机上，先上传到登录服务器再分发：
- 适合本机已有安装包的场景
- 从本机上传到登录服务器的 `/tmp/` 目录
- 从登录服务器分发到GPU节点
- 如果登录服务器同时是GPU节点，自动跳过本机传输

```yaml
cuda:
  version: "12.8"
  local_file: "/home/user/software/cuda_12.8.0_570.86.10_linux.run"
  # 这是运行部署工具的本机上的路径

nvidia_driver:
  version: "590.48.01"
  local_file: "/home/user/software/NVIDIA-Linux-x86_64-590.48.01.run"
```

分发流程：
1. 从本机上传到登录服务器 `/tmp/` 目录
2. 从登录服务器传输到各GPU节点
3. 登录服务器同时是GPU节点时跳过步骤2

**优先级说明**：
- `local_file` 优先级高于 `download_url`
- 如果两者都未配置，使用登录服务器默认路径 `/tmp/{filename}`

> **注意**：如果登录服务器同时也是GPU节点（即程序在登录服务器上运行且该节点需要安装软件），工具会自动识别并跳过不必要的传输步骤。

### 4. 执行部署

```bash
# 预检查模式（不执行实际部署）
python src/main.py --dry-run

# 完整部署
python src/main.py

# 执行指定阶段
python src/main.py --phase 1 --phase 2

# 使用新 CLI 模式（模块化执行）
python src/main.py --new-cli --category gpu --category storage

# 从执行计划文件执行
python src/main.py --new-cli --plan config/plans/gpu-only.yaml
```

## 使用指南

### 批量节点配置

支持三种批量节点配置方式：

#### 方式一：使用 hosts 文件

```yaml
node_batch:
  enabled: true
  hosts_file: "/path/to/hosts/file"  # hosts 格式文件路径
  auth_template:            # 登录用户配置（必须指定）
    username: "root"
    password: "root-password"
    # 或使用私钥
    # private_key: "~/.ssh/id_rsa"
  roles:
    - gpu_node
  storage_template:
    type: "single"
    device: "/dev/nvme0n1"
    mount_point: "/ssd"
    format_disk: false
```

hosts 文件格式：
```
# 批量GPU节点配置
10.254.43.66 gpu-node-01
10.254.43.67 gpu-node-02
10.254.43.68 gpu-node-03
10.254.43.69 gpu-node-04
10.254.43.70 gpu-node-05
```

#### 方式二：直接提供 hosts 内容

```yaml
node_batch:
  enabled: true
  auth_template:            # 登录用户配置
    username: "root"
    password: "root-password"
  hosts_content: |
    # 批量GPU节点配置
    10.254.43.66 gpu-node-01
    10.254.43.67 gpu-node-02
    10.254.43.68 gpu-node-03
```

#### 方式三：基于模板生成

```yaml
node_batch:
  enabled: true
  base_hostname_prefix: "gpu-node-"
  base_ip_prefix: "10.254.43"
  count: 5                  # 生成5个节点
  start_index: 66           # 起始索引为66
  auth_template:            # 登录用户配置
    username: "root"
    password: "root-password"
  roles:
    - gpu_node
  storage_template:
    type: "single"
    device: "/dev/nvme0n1"
    mount_point: "/ssd"
    format_disk: false
```

#### 覆盖特定节点配置

```yaml
# 覆盖批量节点中特定节点的配置
nodes_override:
  - hostname: "gpu-node-02"
    storage:
      device: "/dev/nvme1n1"  # 使用不同的设备
      format_disk: false

  - hostname: "gpu-node-05"
    roles:
      - gpu_node
      - test_node           # 添加额外角色
```

### SSH 认证配置

支持灵活的SSH认证配置，适应不同安全场景：

#### 登录用户与部署用户

系统区分两种用户角色：

| 用户角色 | 说明 | 配置位置 |
|----------|------|----------|
| **登录用户** | 用于初始连接节点，必须有密码或密钥认证 | `nodes[].username` 或 `jumphost.node_auth.username` |
| **部署用户** | 部署过程中使用的目标用户，可自动配置免密登录 | `cluster.deploy_user`（可选） |

**典型场景：**

```yaml
cluster:
  name: "gpu-cluster"
  deploy_user: "ubuntu"    # 部署用户（可选，默认使用登录用户）

jumphost:
  host: "1.2.3.4"
  username: "ubuntu"
  password: "jumphost-password"
  node_auth:
    username: "root"       # 登录用户（有 root 密码）
    password: "root-password"

nodes:
  - hostname: "gpu-node-01"
    ip: "10.0.1.10"
    username: "root"        # 登录用户（必须指定）
    password: "root-password"
    # 部署时会自动创建 deploy_user (ubuntu) 并配置 sudo 免密
```

**执行流程：**

1. **Phase 0** (step_0, step_0b): 使用**登录用户**连接（部署用户可能不存在）
2. **Phase 1** (step_0d): 使用**登录用户**配置 SSH 免密
   - 如果 deploy_user ≠ login_user，自动创建 deploy_user 并配置 sudo 免密
3. **Phase 2+**: 使用**部署用户**免密连接

#### 跳转服务器认证

支持两种配置格式：

**格式一：嵌套格式（推荐）**

```yaml
jumphost:
  host: "1.2.3.4"
  port: 22
  auth:
    type: "key"              # key | password
    username: "ubuntu"
    private_key: "~/.ssh/id_rsa"
    # password: "your-password"  # 密码认证时使用
```

**格式二：扁平格式（向后兼容）**

```yaml
jumphost:
  host: "1.2.3.4"
  port: 22
  username: "ubuntu"
  password: "your-password"
  # private_key: "~/.ssh/id_rsa"  # 密钥认证时使用
```

#### 节点认证配置

**场景一：所有节点使用相同认证**

通过 `node_auth` 配置统一的节点访问认证：

```yaml
jumphost:
  host: "36.103.234.31"
  username: "ubuntu"
  password: "jumphost-password"
  # 节点访问认证（与跳转服务器不同时配置）
  node_auth:
    type: "password"
    username: "ubuntu"
    password: "node-password"
```

**场景二：不同节点使用不同认证**

在每个节点上单独配置认证信息：

```yaml
nodes:
  - hostname: "node-01"
    ip: "10.0.18.87"
    username: "ubuntu"
    password: "password-01"

  - hostname: "node-02"
    ip: "10.0.19.134"
    username: "ubuntu"
    password: "password-02"    # 不同的密码

  - hostname: "node-03"
    ip: "10.0.20.100"
    username: "admin"          # 不同的用户名
    private_key: "~/.ssh/node-03-key"  # 使用密钥认证
```

**认证优先级**

节点认证配置的优先级从高到低：

1. 节点级别配置 (`nodes[].username/password/private_key`)
2. 跳转服务器的 `node_auth` 配置
3. 跳转服务器的认证配置（向后兼容）

#### 完整配置示例

```yaml
# 集群基础配置
cluster:
  name: "test-cluster"
  description: "测试集群"

# 跳转服务器
jumphost:
  host: "1.2.3.4"
  port: 22
  username: "ubuntu"
  password: "your-jumphost-password"
  # 内网节点使用不同密码
  node_auth:
    type: "password"
    username: "ubuntu"
    password: "your-node-password"

# 节点列表
nodes:
  - hostname: "node-01"
    ip: "10.0.1.10"
    username: "root"        # 登录用户（必须指定）
    password: "root-password"
    roles: [gpu_node]

  - hostname: "node-02"
    ip: "10.0.1.11"
    username: "root"        # 登录用户（必须指定）
    password: "your-special-password"
    roles: [gpu_node]
```

### 部署参数配置

在 `cluster.yaml` 中配置部署行为：

```yaml
deployment:
  parallel: true           # 是否并行执行步骤
  max_workers: 2           # 最大并行工作线程数
  timeout: 300             # 单步超时时间（秒）
  retry: 3                 # 失败重试次数
  continue_on_failure: false  # 失败后是否继续执行
```

**参数说明：**

| 参数 | 类型 | 默认值 | 描述 |
|------|------|--------|------|
| `parallel` | bool | true | 是否并行执行多个节点的部署步骤 |
| `max_workers` | int | 2 | 并行执行时的最大工作线程数，建议不超过节点数量 |
| `timeout` | int | 300 | 单个步骤的超时时间（秒），复杂步骤（如驱动安装）可适当增大 |
| `retry` | int | 3 | 命令执行失败时的重试次数 |
| `continue_on_failure` | bool | false | 步骤失败后是否继续执行后续步骤 |

**使用建议：**

- **小规模集群（<10节点）**：`max_workers: 2-3`
- **中等规模集群（10-50节点）**：`max_workers: 5-10`
- **大规模集群（>50节点）**：`max_workers: 10-20`，注意网络带宽

**CLI 命令行覆盖：**

```bash
# 命令行参数会覆盖配置文件
python src/main.py --new-cli --category gpu --parallel --max-parallel 4
python src/main.py --new-cli --plan config/plans/full.yaml --continue-on-error
```

### 网络测试模块

提供独立的网络测试工具，用于验证 RDMA 网络配置和定位异常设备。

#### 测试内容

1. **RoCE Ping 连通性测试** - 对所有主机的所有计算网卡执行全量 ping 测试（N×M 矩阵）
2. **ib_write_bw 带宽测试** - 三轮测试策略精确定位异常设备

#### 三轮测试策略

通过三轮测试精确定位异常网络设备：

1. **第一轮：相邻配对测试** - 测试 (1,2), (3,4), ...
2. **第二轮：错位配对测试** - 测试 (2,3), (4,5), ...
3. **第三轮：异常定位** - 使用正常主机定位异常设备

**重要说明：**
- 当主机数量为奇数时，最后一台主机在第一轮被跳过，必须执行第二轮
- 只有当主机数量为偶数且第一轮全部正常时，才会跳过后续轮次
- RoCE Ping 测试独立于带宽测试，不会因为 ping 失败而跳过带宽测试

#### 网络测试 CLI

```bash
# 测试所有主机的 RDMA 网络
python -m src.cli.network_test_cli --config config/cluster.yaml

# 测试指定主机
python -m src.cli.network_test_cli --config config/cluster.yaml --hosts node01,node02

# 指定网络类型
python -m src.cli.network_test_cli --config config/cluster.yaml --network compute

# 生成 HTML 报告
python -m src.cli.network_test_cli --config config/cluster.yaml --format html --output report.html

# JSON 输出
python -m src.cli.network_test_cli --config config/cluster.yaml --format json --output results.json
```

#### 连通性检查

在部署前检查各节点的网络连通性：

```bash
# IP 层连通性（ping 8.8.8.8）
# DNS 解析（ping www.baidu.com）
# HTTP 连接（curl http://www.baidu.com）
```

### 安装包管理器

自动管理安装包的下载、分发和校验。

#### 双模式分发

| 模式 | 配置字段 | 描述 |
|------|----------|------|
| 登录服务器下载 | `download_url` | 在登录服务器下载后分发到 GPU 节点 |
| 本机文件上传 | `local_file` | 从本机上传到登录服务器再分发 |

#### 配置示例

```yaml
# 方式一：登录服务器下载（推荐）
cuda:
  version: "12.8"
  download_url: "https://developer.download.nvidia.com/compute/cuda/12.8.0/local_installers/cuda_12.8.0_570.86.10_linux.run"

# 方式二：本机文件上传
nvidia_driver:
  version: "590.48.01"
  local_file: "/home/user/software/NVIDIA-Linux-x86_64-590.48.01.run"

# 方式三：集群节点已有文件
mlnx_ofed:
  version: "24.10-2.1.8.0"
  local_file: "/opt/software/MLNX_OFED_LINUX-24.10-2.1.8.0-ubuntu22.04-x86_64.tgz"
```

#### 分发流程

1. 检查各节点是否已有文件
2. 在登录服务器准备文件（下载或上传）
3. 从登录服务器分发到 GPU 节点
4. 如果登录服务器同时是 GPU 节点，自动跳过传输

### 设备一致性检查

部署前自动检查所有节点的设备一致性：

```yaml
network:
  device_consistency_check:
    enabled: true
    check_items:
      - network_adapters     # 检查 RDMA/以太网设备
      - gpu_cards           # 检查 GPU 设备
      - nvme_disks          # 检查 NVMe 磁盘
    tolerance_level: "strict"  # strict | moderate | lenient
```

**容忍级别说明：**

| 级别 | 描述 |
|------|------|
| `strict` | 要求完全一致，任何差异都会失败 |
| `moderate` | 允许多余设备，不允许缺失设备 |
| `lenient` | 仅报告严重问题，不阻止部署 |

**检查项目：**

- **RDMA 设备** - 检查所有节点的 IB/RoCE 网卡数量和型号一致性
- **GPU 卡** - 检查 GPU 数量、型号、拓扑一致性
- **NVMe 磁盘** - 检查 NVMe 设备一致性
- **GPU 拓扑** - 检查 GPU 与 RDMA 的 NUMA 亲和性

### 磁盘配置选项

```yaml
nodes:
  - hostname: "gpu-node-01"
    ip: "10.254.43.66"
    username: "root"           # 登录用户（必须指定）
    password: "root-password"
    storage:
      type: "single"           # single | raid1 | raid10
      device: "/dev/nvme0n1"   # single 模式
      mount_point: "/ssd"
      filesystem: "ext4"       # ext4 | xfs
      format_disk: true        # 是否格式化（默认 false）

  - hostname: "gpu-master"
    ip: "10.254.43.65"
    username: "root"
    password: "root-password"
    storage:
      type: "raid10"           # RAID10 模式
      devices:
        - "/dev/nvme0n1"
        - "/dev/nvme1n1"
        - "/dev/nvme2n1"
        - "/dev/nvme3n1"
      mount_point: "/ssd"
      filesystem: "ext4"
      format_disk: false       # 安全默认
```

### 执行计划

创建执行计划文件 `config/plans/gpu-only.yaml`：

```yaml
name: gpu-only-deployment
version: "1.0.0"
description: "GPU-focused deployment plan"

global_config:
  log_level: INFO
  continue_on_failure: false
  timeout_multiplier: 1.0

# 模块分组
groups:
  - name: gpu-drivers
    description: "GPU driver installation"
    modules:
      - disable-nouveau
      - nvidia-driver
      - fabric-manager
    parallel: false
    stop_on_failure: true

  - name: gpu-tools
    description: "CUDA toolkit and libraries"
    modules:
      - cuda-toolkit
      - nccl-install
    parallel: false
    stop_on_failure: true

# 模块定义
modules:
  - name: disable-nouveau
    module_class: step_21
    category: gpu
    enabled: true
    depends_on: []
    timeout: 300

  - name: nvidia-driver
    module_class: step_22
    category: gpu
    enabled: true
    config:
      driver_version: "535"
    depends_on:
      - disable-nouveau
    timeout: 600

  - name: cuda-toolkit
    module_class: step_24
    category: gpu
    enabled: true
    config:
      cuda_version: "12.2"
    depends_on:
      - nvidia-driver
    timeout: 900

# 执行顺序（可自动推导）
execution_order:
  - disable-nouveau
  - nvidia-driver
  - fabric-manager
  - cuda-toolkit
  - nccl-install
  - gpu-persistence
  - nvidia-modules
```

## CLI 命令参考

### 传统 CLI 模式

```bash
# 查看帮助
python src/main.py --help

# 完整部署
python src/main.py

# 使用指定配置目录
python src/main.py --config-dir /path/to/config

# 预检查模式
python src/main.py --dry-run

# 只生成部署报告
python src/main.py --report-only

# 执行指定阶段
python src/main.py --phase 1 --phase 2

# 执行指定步骤
python src/main.py --step 1.1 --step 1.2

# 设置日志级别
python src/main.py --log-level DEBUG

# 指定日志目录
python src/main.py --log-dir /path/to/logs

# 跳过确认提示
python src/main.py -y
```

### 新 CLI 模式

```bash
# 启用新 CLI
python src/main.py --new-cli

# 执行指定分类
python src/main.py --new-cli --category gpu
python src/main.py --new-cli --category gpu --category storage

# 执行指定模块
python src/main.py --new-cli --module disk_mount --module nvidia_driver

# 从执行计划文件执行
python src/main.py --new-cli --plan config/plans/gpu-only.yaml

# 并行执行
python src/main.py --new-cli --category gpu --parallel --max-parallel 4

# 遇到错误继续执行
python src/main.py --new-cli --category gpu --continue-on-error
```

### 输出格式

```bash
# 文本输出（默认）
python src/main.py --output text

# JSON 输出
python src/main.py --output json

# Markdown 输出
python src/main.py --output markdown

# 输出到文件
python src/main.py --output json --output-file report.json
```

### 网络测试命令

```bash
# 测试所有主机的 RDMA 网络
python -m src.cli.network_test_cli --config config/cluster.yaml

# 测试指定主机
python -m src.cli.network_test_cli --config config/cluster.yaml --hosts node01,node02

# 指定网络类型（compute/storage/all）
python -m src.cli.network_test_cli --config config/cluster.yaml --network compute

# 指定测试轮次（1/2/3）
python -m src.cli.network_test_cli --config config/cluster.yaml --rounds 3

# 生成 HTML 报告
python -m src.cli.network_test_cli --config config/cluster.yaml --format html --output report.html

# JSON 格式输出
python -m src.cli.network_test_cli --config config/cluster.yaml --format json

# 详细输出模式
python -m src.cli.network_test_cli --config config/cluster.yaml --verbose

# 模拟运行（不执行实际测试）
python -m src.cli.network_test_cli --config config/cluster.yaml --dry-run
```

### 子命令

```bash
# 列出可用模块
python src/main.py list modules

# 列出可用分类
python src/main.py list categories

# 列出可用步骤
python src/main.py list steps

# 列出执行计划文件
python src/main.py list plans

# 验证配置文件
python src/main.py validate

# 严格验证模式
python src/main.py validate --strict

# 导出执行计划
python src/main.py export --format yaml --output plan.yaml
python src/main.py export --format json --output plan.json
```

## 部署步骤详解

### 步骤分组

| 分组 | 步骤范围 | 描述 |
|------|----------|------|
| 0 | 00-0c | 预检查（设备一致性、网络连通性、RDMA 测试） |
| A | 01-04 | 系统检查（依赖、内核、glibc、OpenSSH） |
| B | 05-09 | 基础配置（sudo、磁盘、MSR、rc.local、主机名） |
| C | 10-13 | 用户与 SSH（用户创建、密钥、CPU 性能、文件限制） |
| D | 15-19 | 系统优化（禁止更新、固定内核、时区、IPv6、休眠） |
| E | 20-23 | 网络驱动（MLNX_OFED、nouveau、NVIDIA 驱动、Fabric Manager） |
| F | 24-28 | GPU 环境（CUDA、NCCL、RDMA 重命名、GPU 持久化、内核模块） |
| G | 29-34 | 高级配置（ACS、时间同步、NFS） |
| H | final | 部署验证（服务状态、网络配置验证） |

### 详细步骤说明

| 步骤 | 名称 | 描述 | 需要 Sudo | 需要重启 |
|------|------|------|-----------|----------|
| 0 | 设备一致性检查 | 检查集群设备一致性（使用登录用户） | 否 | 否 |
| 0b | 网络连通性检查 | 检查 IP/DNS/HTTP 连通性（使用登录用户） | 否 | 否 |
| 0c | RDMA 网络测试 | 三轮测试定位异常网络设备（含 RoCE Ping 测试） | 否 | 否 |
| 0d | SSH 免密配置 | 配置 SSH 免密登录（使用登录用户） | 是 | 否 |
| 01 | 依赖安装 | 安装基础依赖包 | 是 | 否 |
| 02 | 内核检查 | 检查内核版本兼容性 | 是 | 可能 |
| 03 | glibc 检查 | 检查 glibc 版本 | 否 | 否 |
| 04 | OpenSSH 检查 | 检查并修复 CVE-2024-6387 | 是 | 否 |
| 05 | Sudo 免密 | 配置 sudo 免密 | 是 | 否 |
| 06 | 磁盘挂载 | 配置磁盘/RAID 并挂载 | 是 | 否 |
| 07 | MSR 设置 | 配置 MSR（5090 + Intel 5代 CPU） | 是 | 否 |
| 08 | rc.local | 配置开机启动脚本 | 是 | 否 |
| 09 | 主机名/hosts | 配置主机名和 hosts 解析 | 是 | 否 |
| 10 | 创建用户 | 创建部署用户 | 是 | 否 |
| 12 | CPU 性能 | 设置 CPU 性能模式 | 是 | 否 |
| 13 | 文件限制 | 配置文件描述符限制 | 是 | 否 |
| 15 | 禁用自动更新 | 禁用系统自动更新 | 是 | 否 |
| 16 | 锁定内核 | 锁定内核版本 | 是 | 否 |
| 17 | 时区设置 | 设置系统时区 | 是 | 否 |
| 18 | 禁用 IPv6 | 禁用 IPv6 协议 | 是 | 否 |
| 19 | vmcore/休眠 | 配置 kdump 和禁用休眠 | 是 | 否 |
| 20 | MLNX OFED | 安装 Mellanox OFED 驱动 | 是 | 是 |
| 21 | 禁用 Nouveau | 禁用开源 NVIDIA 驱动 | 是 | 是 |
| 22 | NVIDIA 驱动 | 安装 NVIDIA 驱动 | 是 | 是 |
| 23 | Fabric Manager | 安装 NVLink Fabric Manager | 是 | 否 |
| 24 | CUDA Toolkit | 安装 CUDA 工具包 | 是 | 否 |
| 25 | NCCL | 安装 NCCL 通信库 | 是 | 否 |
| 26 | RDMA 重命名 | 重命名 RDMA 网卡 | 是 | 否 |
| 27 | GPU 持久化 | 启用 GPU 持久化模式 | 是 | 否 |
| 28 | NVIDIA 模块 | 加载 NVIDIA 内核模块 | 是 | 否 |
| 29 | 禁用 ACS | 禁用 ACS（GPU Direct RDMA） | 是 | 是 |
| 30 | 时间同步 | 配置 NTP 时间同步 | 是 | 否 |
| 34 | NFS 配置 | 配置 NFS 服务端/客户端 | 是 | 否 |
| final | 部署验证 | 验证部署结果和服务状态 | 否 | 否 |

## 模块分类

| 分类 | 描述 | 包含模块 |
|------|------|----------|
| `system` | 系统基础配置 | 依赖检查、内核、glibc、用户创建、时区等 |
| `network` | 网络配置 | 主机名、RDMA 重命名、网卡配置等 |
| `storage` | 存储配置 | 磁盘挂载、RAID、NFS 配置 |
| `gpu` | GPU 相关 | NVIDIA 驱动、CUDA、NCCL、Fabric Manager |
| `security` | 安全配置 | SSH 检查、sudo 配置 |

## 网络配置

### 网络类型配置（新格式）

支持按网络类型配置网卡和 RDMA 设备，用于网络测试和验证：

```yaml
network:
  # ib_write_bw 测试参数
  ib_write_bw:
    duration: 10              # 测试持续时间(秒)
    size: 65536               # 测试数据块大小(字节)
    port_base: 18500          # 基础端口号
    min_bandwidth_percent: 90 # 最低带宽百分比要求

  # 管理网络 (25G bond网络)
  management:
    description: "管理网络 (25G bond网络)"
    interfaces:
      - ens19f0np0
    rdma_devices:
      - mlx5_bond_0
    enabled: true
    skip_performance_test: true   # 管理网通常跳过性能测试
    skip_inter_host_test: true    # 管理网跳过跨主机测试
    theoretical_bandwidth_gbps: 25

  # 计算网络 (400G RoCE网络)
  compute:
    description: "计算网络 (400G RoCE网络)"
    interfaces:
      - ens11np0
      - ens12np0
      - ens13np0
      - ens14np0
    rdma_devices:
      - mlx5_0
      - mlx5_1
      - mlx5_2
      - mlx5_3
    enabled: true
    skip_performance_test: false
    skip_inter_host_test: false
    theoretical_bandwidth_gbps: 400

  # 存储网络 (200G RoCE网络)
  storage:
    description: "存储网络 (200G RoCE网络)"
    interfaces:
      - ens22np0
    rdma_devices:
      - mlx5_10
    enabled: true
    skip_performance_test: false
    skip_inter_host_test: false
    theoretical_bandwidth_gbps: 200
```

**网络类型配置字段说明：**

| 字段 | 类型 | 描述 |
|------|------|------|
| `description` | string | 网络描述 |
| `interfaces` | list | 网络接口名称列表 |
| `rdma_devices` | list | RDMA 设备名称列表 (如 mlx5_0) |
| `enabled` | bool | 是否启用此网络 |
| `skip_performance_test` | bool | 是否跳过性能测试 |
| `skip_inter_host_test` | bool | 是否跳过跨主机测试 |
| `theoretical_bandwidth_gbps` | int | 理论带宽 (Gbps)，用于验证测试结果 |

### RDMA 网卡重命名（旧格式，向后兼容）

支持两种旧格式：

**格式一：网卡列表方式**

```yaml
network:
  compute_nics:
    - mlx5_0
    - mlx5_1
    - mlx5_2
    - mlx5_3
  storage_nics:
    - mlx5_10
  management_nics:
    - mlx5_bond_0
```

**格式二：模式匹配方式**

```yaml
network:
  nics:
    compute_400g:
      pattern: "mlx5_[0-7]"
      count: 8
      net_prefix: "ib"       # 重命名为 ib0-ib7
    storage_200g:
      pattern: "mlx5_[8-9]"
      count: 2
      net_prefix: "ib"       # 重命名为 ib8-ib9
```

### 网络绑定配置

```yaml
network:
  bonding:
    mode4:
      nics: ["eth0", "eth1"]
      mode: "802.3ad"        # LACP
      mtu: 9000
      lacp_rate: "fast"
    mode1:
      nics: ["eth2", "eth3"]
      mode: "active-backup"
      primary: "eth2"
```

## 日志与报告

### 日志文件

| 文件 | 描述 |
|------|------|
| `logs/deploy_YYYYMMDD_HHMMSS.log` | 文本日志 |
| `logs/deploy_YYYYMMDD_HHMMSS.jsonl` | 结构化 JSON 日志 |
| `logs/deployment_report.html` | HTML 可视化报告 |
| `logs/progress_report.json` | 进度追踪报告 |

### 查看日志

```bash
# 查看最新部署日志
tail -f logs/deploy_*.log

# 查看进度报告
cat logs/progress_report.json | python -m json.tool
```

## 故障排除

### 常见问题

#### 1. SSH 连接失败

```
错误: 跳转服务器连接失败
```

**解决方案：**
- 检查跳转服务器 IP 和端口是否正确
- 验证 SSH 密钥权限：`chmod 600 ~/.ssh/id_rsa`
- 确认密钥文件路径正确
- 检查网络连通性：`ping jump_server_ip`

#### 2. 设备一致性检查失败

```
错误: 设备一致性严重问题: 发现 2 个缺失设备
```

**解决方案：**
- 检查硬件是否正确安装
- 验证驱动是否加载：`lspci | grep -i nvidia`
- 调整容忍级别：
  ```yaml
  network:
    device_consistency_check:
      tolerance_level: "lenient"
  ```

#### 3. NVIDIA 驱动安装失败

```
错误: NVIDIA 驱动安装失败
```

**解决方案：**
- 确认 Nouveau 已禁用：`lsmod | grep nouveau`
- 检查内核版本兼容性
- 验证 GCC 版本：`gcc --version`
- 查看详细错误日志

#### 4. 磁盘挂载失败

```
错误: 磁盘挂载失败
```

**解决方案：**
- 确认设备存在：`lsblk`
- 检查文件系统类型
- 验证挂载点是否存在
- 查看磁盘是否有数据（`format_disk` 默认为 false）

### 调试模式

```bash
# 启用详细日志
python src/main.py --log-level DEBUG --dry-run

# 查看详细错误信息
python src/main.py --verbose 2>&1 | tee debug.log
```

## 开发指南

### 添加新步骤

1. 创建步骤文件 `src/steps/step_XX_name.py`：

```python
from steps.base import BaseStep, StepResult, StepStatus
from typing import List

class StepXXName(BaseStep):
    """步骤描述"""

    step_id = "XX"
    step_name = "步骤名称"
    step_description = "详细描述"
    requires_sudo = False
    requires_reboot = False
    can_skip = False
    timeout = 300

    def execute(self, hosts: List[str]) -> StepResult:
        """执行步骤逻辑"""
        try:
            # 执行命令
            results = self.execute_batch(hosts, "echo 'hello'", sudo=False)

            # 检查结果
            success = all(r.get("success", False) for r in results.values())

            return StepResult(
                step_id=self.step_id,
                step_name=self.step_name,
                status=StepStatus.SUCCESS if success else StepStatus.FAILED,
                message="执行成功" if success else "执行失败",
                host_results=results
            )
        except Exception as e:
            return StepResult(
                step_id=self.step_id,
                step_name=self.step_name,
                status=StepStatus.FAILED,
                message=f"执行异常: {str(e)}",
                errors=[str(e)]
            )
```

2. 在部署流程中注册步骤

### 运行测试

```bash
# 运行所有测试
pytest tests/ -v

# 运行指定测试文件
pytest tests/test_config_loader.py -v

# 运行集成测试
pytest tests/integration/ -v

# 生成覆盖率报告
pytest --cov=src --cov-report=html tests/

# 只运行特定测试
pytest tests/test_ssh_manager.py::TestSSHManager::test_connect -v
```

### 代码规范

- 使用 Python 3.8+ 特性
- 遵循 PEP 8 编码规范
- 添加类型注解
- 编写单元测试

## 系统要求

### 控制节点

- Python 3.8+
- 网络可达跳转服务器

### 目标节点

- Ubuntu 22.04 LTS（推荐）
- SSH 服务运行中
- root 或 sudo 权限
- pdsh（可选，用于批量执行加速）

## 注意事项

1. **安装包管理** - 支持 `download_url` 在登录服务器下载，或 `local_file` 从本机上传
2. **网络测试** - 部署前后可使用 `network_test_cli` 验证 RDMA 网络状态
3. **重启要求** - 步骤 20、21、22、29 执行后需要重启
4. **磁盘数据** - `format_disk` 默认为 false，防止意外数据丢失
5. **网络环境** - 确保跳转服务器和内网节点网络可达
6. **向后兼容** - 新功能保持向后兼容，旧配置文件无需修改


## 待办

- chrony 配置


## 许可证

MIT License

## 贡献

欢迎提交 Issue 和 Pull Request。

1. Fork 本仓库
2. 创建特性分支 (`git checkout -b feature/amazing-feature`)
3. 提交更改 (`git commit -m 'Add amazing feature'`)
4. 推送到分支 (`git push origin feature/amazing-feature`)
5. 创建 Pull Request
