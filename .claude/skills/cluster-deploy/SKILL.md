---
name: cluster-deploy
description: GPU集群自动化部署 - 配置生成、预检查、执行、验证全流程。支持多集群管理、实时日志、安装包管理。
---

# Cluster Deploy - GPU集群自动化部署

## 目录结构

```
/mnt/e/openclaw-workspace/deploy/
├── config/
│   └── <集群名>/
│       ├── cluster.yaml      # 集群配置
│       └── versions.yaml     # 软件版本配置
├── logs/
│   └── <集群名>/
│       ├── deploy.log        # 部署主日志
│       ├── progress.json     # 进度跟踪
│       └── report.html       # 部署报告
└── packages/
    ├── packageslist.md       # 安装包下载清单
    └── *.run/*.tgz           # 本地安装包文件
```

## 工作流程

### 1. 接收部署任务 → 确认集群信息

收集以下信息:
- 集群名称 (cluster name)
- 跳转服务器 (jumphost IP, port, auth)
- 集群节点 (hostname, IP, roles)
- 网络配置 (management, compute, storage)
- NFS配置 (可选)
- 软件版本 (CUDA, NVIDIA driver, MLNX_OFED)

### 2. 登录集群 → 环境探测 (新增)

**必须先登录集群收集当前环境信息!**

通过 SSH 跳转登录到集群节点，执行环境探测命令:

#### SSH 跳转连接方式

**前置条件：安装 sshpass（密码认证时需要）**
```bash
# Ubuntu/Debian
sudo apt-get install sshpass

# CentOS/RHEL
sudo yum install sshpass
```

**方式一：免密认证（推荐）**
```bash
# 已配置密钥认证时，直接使用 -J 参数
ssh -J root@jumphost.example.com:1038 root@10.0.0.1

# 或使用 ProxyJump 选项
ssh -o ProxyJump=root@jumphost.example.com:1038 root@10.0.0.1
```

**方式二：密码认证 - 跳转和目标密码相同**
```bash
# 使用 sshpass 提供密码
sshpass -p '密码' ssh -J root@jumphost.example.com:1038 -o StrictHostKeyChecking=no root@10.0.0.1
```

**方式三：密码认证 - 跳转和目标密码不同**
```bash
# 外层 sshpass：目标服务器密码
# 内层 sshpass：跳转服务器密码
sshpass -p '目标密码' ssh -o ProxyCommand="sshpass -p '跳转密码' ssh -W %h:%p -o StrictHostKeyChecking=no root@jumphost.example.com -p 1038" -o StrictHostKeyChecking=no root@10.0.0.1
```

**方式四：配置 ~/.ssh/config（长期使用推荐）**
```bash
# 编辑 ~/.ssh/config
Host jumphost
    HostName jumphost.example.com
    Port 1038
    User root

Host gpu-node
    HostName 10.0.0.1
    User root
    ProxyJump jumphost

# 然后可以直接连接（需先配置免密或使用 sshpass）
ssh gpu-node
```

#### 部署程序内部连接方式

部署程序使用 **paramiko** 库通过跳转服务器连接，不依赖系统 SSH 命令：

```python
# 程序内部实现（仅供参考）
# 1. 先连接跳转服务器
jump_client.connect(jumphost_host, jumphost_port, jumphost_user, jumphost_password)

# 2. 通过跳转服务器的 transport 打开到目标节点的通道
transport = jump_client.get_transport()
channel = transport.open_channel('direct-tcpip', (node_ip, node_port), ('127.0.0.1', 22))

# 3. 通过通道连接目标节点
node_client.connect(node_ip, node_port, node_user, node_password, sock=channel)
```

**配置完成后免密连接**：
部署程序在 Step 0d 配置完 SSH 免密后，后续所有连接都使用密钥认证，不再需要密码：
- scp 传输文件：`scp file user@host:/path`
- ssh 执行命令：`ssh user@host "command"`
- pdsh 批量执行：`pdsh -w hosts "command"`

#### 探测项目

| # | 探测项 | 命令 | 用途 |
|---|--------|------|------|
| 1 | 操作系统 | `cat /etc/os-release` | 确认系统版本 |
| 2 | 内核版本 | `uname -r` | 驱动兼容性检查 |
| 3 | GPU信息 | `nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv` | GPU型号、数量 |
| 4 | RDMA设备 | `ibv_devinfo 2>/dev/null \| grep -E "hca_id\|transport\|link_layer"` | 网卡型号、数量 |
| 5 | 网络接口 | `ip -br addr show` | 网卡名称、状态 |
| 6 | 磁盘信息 | `lsblk -d -o NAME,SIZE,TYPE \| grep -E "disk\|nvme"` | NVMe设备 |
| 7 | 已装CUDA | `nvcc --version 2>/dev/null \|\| ls /usr/local/cuda*/version.txt 2>/dev/null` | CUDA状态 |
| 8 | 已装驱动 | `cat /proc/driver/nvidia/version 2>/dev/null` | 驱动状态 |
| 9 | MLNX_OFED | `ofed_info -s 2>/dev/null` | OFED状态 |
| 10 | 内存信息 | `free -h` | 内存容量 |

#### 环境探测脚本

```bash
#!/bin/bash
# 一键环境探测脚本
echo "=== 系统信息 ==="
cat /etc/os-release | grep -E "PRETTY_NAME|VERSION_ID"
echo "内核: $(uname -r)"

echo ""
echo "=== GPU信息 ==="
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader 2>/dev/null || echo "NVIDIA驱动未安装"

echo ""
echo "=== RDMA设备 ==="
ibv_devinfo 2>/dev/null | grep -E "hca_id|link_layer" | head -20 || echo "RDMA设备未配置"

echo ""
echo "=== 网络接口 ==="
ip -br addr show | grep -v "lo\|DOWN"

echo ""
echo "=== NVMe磁盘 ==="
lsblk -d -o NAME,SIZE,TYPE | grep -E "nvme|disk"

echo ""
echo "=== 内存 ==="
free -h | grep Mem

echo ""
echo "=== 已安装软件 ==="
echo "CUDA: $(nvcc --version 2>/dev/null | grep release || echo '未安装')"
echo "OFED: $(ofed_info -s 2>/dev/null || echo '未安装')"
```

#### 探测结果保存

探测结果保存到:
```
/mnt/e/openclaw-workspace/deploy/logs/<集群名>/env_check_YYYYMMDD_HHMMSS.log
```

#### 根据探测结果调整配置

| 探测结果 | 配置调整 |
|----------|----------|
| GPU已安装驱动 | 检查版本兼容性，决定是否升级 |
| RDMA设备数量 | 自动填充 network.compute.rdma_devices |
| NVMe设备列表 | 自动填充 nodes[].storage.devices |
| 已有CUDA | 检查版本，决定是否重新安装 |
| 内核版本 | 判断 MLNX_OFED 兼容性 |

### 3. 自动写配置文件 → 用户确认

根据环境探测结果，生成配置文件到:
```
/mnt/e/openclaw-workspace/deploy/config/<集群名>/cluster.yaml
/mnt/e/openclaw-workspace/deploy/config/<集群名>/versions.yaml
```

**必须等待用户确认后才能继续!**

#### 需要用户确认的关键事项

| # | 确认项 | 配置字段 | 说明 | 危险级别 |
|---|--------|----------|------|----------|
| 1 | **登录用户** | `nodes[].username` | 用于SSH连接节点的用户（必须指定） | ⚠️ 中 |
| 2 | **登录认证方式** | `nodes[].password` / `nodes[].private_key` | 密码或密钥认证 | ⚠️ 中 |
| 3 | **部署用户** | `cluster.deploy_user` | 部署过程中使用的目标用户（可选，默认使用登录用户） | ⚠️ 中 |
| 4 | **NVMe磁盘是否格式化** | `nodes[].storage.format_disk` | **默认 false**，设为 true 会清除磁盘数据 | 🔴 高危 |
| 5 | **RAID级别** | `nodes[].storage.type` | single / raid1 / raid10，影响磁盘配置 | 🔴 高危 |
| 6 | **RAID设备列表** | `nodes[].storage.devices` | 参与RAID的磁盘设备列表 | 🔴 高危 |
| 7 | **NFS是否启用** | `nfs.enabled` | 是否配置NFS服务 | ⚠️ 中 |
| 8 | **NFS服务器** | `nfs.server` | NFS服务器节点 | ⚠️ 中 |
| 9 | **软件版本** | `versions.yaml` | CUDA、Driver、MLNX_OFED版本 | ⚠️ 中 |
| 10 | **内核模式** | `kernel.mode` | keep（保持）/ specify（指定版本） | ⚠️ 中 |

#### 高危操作特别说明

**磁盘格式化 (format_disk)**
- 默认值: `false` (安全默认)
- 设为 `true` 会**永久删除磁盘上的所有数据**
- 必须明确确认每个节点的格式化设置

**RAID 配置**
- `single`: 单盘模式
- `raid1`: 镜像模式（至少2块盘）
- `raid10`: 条带+镜像（至少4块盘）
- RAID配置会改变磁盘结构，需谨慎

#### 确认检查清单

生成配置后，必须向用户展示并确认:

```
请确认以下配置:
□ 登录用户: root / ubuntu / 其他
□ 登录认证: 密码 / 密钥
□ 部署用户: [与登录用户相同 / 指定用户]
□ 磁盘格式化: [否 / 是 - 节点列表]
□ RAID级别: [不配置 / single / raid1 / raid10]
□ NFS服务: [禁用 / 启用]
□ CUDA版本: [保持 / 升级到 x.x]
□ 驱动版本: [保持 / 升级到 xxx.xx]
□ MLNX_OFED: [已安装 / 需要安装]
```

### 4. 预检查 (--dry-run)

执行预检查验证:
- 配置文件语法正确
- SSH连接可达
- 节点连通性
- 安装包可用性
- 依赖关系检查

### 5. 确认执行 → 用户确认后执行

**必须等待用户确认后才能执行实际部署!**

### 6. 执行完成 → 检查所有步骤

调用检查模块验证:
- 所有部署步骤状态
- 服务运行状态
- 网络配置正确性
- GPU可用性
- RDMA功能

## 安装包管理

### 优先级顺序

1. **packageslist.md 中的下载链接** - 优先使用
2. **本地 packages 目录** - 备选方案
3. **默认下载地址** - 最后选择

### 解析 packageslist.md

从 packageslist.md 中提取:

| 软件 | 版本 | 文件名 | 下载地址 |
|------|------|--------|----------|
| CUDA | 12.8 | cuda_12.8.0_570.86.10_linux.run | https://developer.download.nvidia.com/... |
| NVIDIA Driver | 590.48.01 | NVIDIA-Linux-x86_64-590.48.01.run | https://file.mir.blsc.cn/... |
| MLNX_OFED | 24.10-2.1.8.0 | MLNX_OFED_LINUX-24.10-2.1.8.0-ubuntu22.04-x86_64.tgz | https://file.mir.blsc.cn/... |

### 配置文件中的引用

```yaml
# versions.yaml
cuda:
  version: "12.8"
  toolkit_file: "cuda_12.8.0_570.86.10_linux.run"
  # 自动填充 download_url

nvidia_driver:
  version: "590.48.01"
  file: "NVIDIA-Linux-x86_64-590.48.01.run"
  # 自动填充 download_url

mlnx_ofed:
  version: "24.10-2.1.8.0"
  file: "MLNX_OFED_LINUX-24.10-2.1.8.0-ubuntu22.04-x86_64.tgz"
  # 自动填充 download_url
```

## 配置模板

### cluster.yaml 模板

```yaml
# GPU集群环境部署配置文件

# 集群基础配置
cluster:
  name: "<集群名>"
  description: "<集群描述>"
  deploy_user: "ubuntu"      # 部署用户（可选，默认使用登录用户）

# 跳转服务器配置
jumphost:
  host: "<公网IP>"
  port: 22
  # 认证配置 - 格式一（推荐）
  auth:
    type: "key"              # key | password
    username: "ubuntu"
    private_key: "~/.ssh/id_rsa"
    # password: "your-password"
  # 或格式二（扁平格式，向后兼容）
  # username: "ubuntu"
  # password: "your-password"
  # private_key: "~/.ssh/id_rsa"
  # 节点认证配置（可选，用于访问内网节点）
  # node_auth:
  #   type: "password"
  #   username: "root"
  #   password: "node-password"

# 集群节点配置
nodes:
  - hostname: "gpu-master"
    ip: "10.x.x.x"
    port: 22                   # SSH端口（可选，默认22）
    username: "root"           # 登录用户（必须指定）
    password: "your-password"  # 登录密码
    # private_key: "~/.ssh/node-key"  # 或使用密钥
    roles:
      - nfs_server
      - time_server
    storage:
      type: "raid10"           # single | raid1 | raid10
      devices:
        - "/dev/nvme0n1"
        - "/dev/nvme1n1"
        - "/dev/nvme2n1"
        - "/dev/nvme3n1"
      mount_point: "/ssd"
      filesystem: "ext4"       # ext4 | xfs
      format_disk: false       # ⚠️ 高危：是否格式化磁盘

  - hostname: "gpu-node-01"
    ip: "10.x.x.x"
    username: "root"           # 登录用户（必须指定）
    password: "your-password"
    roles:
      - gpu_node
    storage:
      type: "single"
      device: "/dev/nvme0n1"
      mount_point: "/ssd"
      format_disk: false       # ⚠️ 默认false，防止数据丢失

# 网络配置
network:
  ib_write_bw:
    duration: 10
    size: 65536
    port_base: 18500
    min_bandwidth_percent: 90

  management:
    description: "管理网络"
    interfaces:
      - ens19f0np0
    rdma_devices:
      - mlx5_bond_0
    enabled: true
    skip_performance_test: true
    theoretical_bandwidth_gbps: 25

  compute:
    description: "计算网络 (400G RoCE)"
    interfaces:
      - ens11np0
      - ens12np0
    rdma_devices:
      - mlx5_0
      - mlx5_1
    enabled: true
    theoretical_bandwidth_gbps: 400

  storage:
    description: "存储网络 (200G RoCE)"
    interfaces:
      - ens22np0
    rdma_devices:
      - mlx5_10
    enabled: true
    theoretical_bandwidth_gbps: 200

# NFS配置
nfs:
  enabled: true                # 是否启用NFS
  server: "gpu-master"         # NFS服务器主机名
  export_path: "/ssd/nfs"
  client_mount: "/data"

# 时间同步配置
time_sync:
  server: "gpu-master"
  timezone: "Asia/Shanghai"

# SSH免密配置（可选）
ssh_key:
  enabled: true                # 是否启用免密配置
  users:                       # 要配置免密的用户列表
    - ubuntu
  # private_key: "~/.ssh/id_rsa"
  # public_key: "~/.ssh/id_rsa.pub"
```

### 配置字段说明

#### cluster 配置

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `name` | string | 是 | - | 集群名称 |
| `description` | string | 否 | "" | 集群描述 |
| `deploy_user` | string | 否 | 登录用户 | 部署过程中使用的目标用户 |

#### jumphost 配置

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `host` | string | 是 | - | 跳转服务器IP |
| `port` | int | 否 | 22 | SSH端口 |
| `auth.type` | string | 否 | "key" | 认证类型: key / password |
| `auth.username` | string | 否 | "ubuntu" | 跳转服务器用户名 |
| `auth.password` | string | 条件 | - | 密码认证时的密码 |
| `auth.private_key` | string | 条件 | - | 密钥认证时的私钥路径 |
| `node_auth` | object | 否 | - | 访问内网节点的认证配置 |

#### nodes 配置

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `hostname` | string | 是 | - | 主机名 |
| `ip` | string | 是 | - | IP地址 |
| `port` | int | 否 | 22 | SSH端口 |
| `username` | string | **是** | - | **登录用户（必须指定）** |
| `password` | string | 条件 | - | 登录密码 |
| `private_key` | string | 条件 | - | 私钥路径 |
| `roles` | list | 否 | [] | 角色: gpu_node, nfs_server, time_server |

#### storage 配置

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `type` | string | 否 | "single" | 存储类型: single / raid1 / raid10 |
| `device` | string | 条件 | - | single模式下的设备路径 |
| `devices` | list | 条件 | - | raid模式下的设备列表 |
| `mount_point` | string | 否 | "/ssd" | 挂载点 |
| `filesystem` | string | 否 | "ext4" | 文件系统: ext4 / xfs |
| `format_disk` | bool | 否 | **false** | **⚠️ 高危: 是否格式化** |

### versions.yaml 模板

```yaml
# 软件版本配置

# CUDA 配置
cuda:
  mode: "install"             # keep | install
  version: "12.8"
  toolkit_file: "cuda_12.8.0_570.86.10_linux.run"
  # 安装包来源（三选一，优先级从高到低）
  # local_file: "/path/to/cuda_12.8.0_570.86.10_linux.run"  # 本机文件
  download_url: "https://developer.download.nvidia.com/..."   # 下载地址

# NVIDIA 驱动配置
nvidia_driver:
  mode: "install"             # keep | install
  version: "590.48.01"
  file: "NVIDIA-Linux-x86_64-590.48.01.run"
  # local_file: "/path/to/NVIDIA-Linux-x86_64-590.48.01.run"
  download_url: "https://file.mir.blsc.cn/..."

# MLNX_OFED 驱动配置
mlnx_ofed:
  mode: "install"             # keep | install
  version: "24.10-2.1.8.0"
  file: "MLNX_OFED_LINUX-24.10-2.1.8.0-ubuntu22.04-x86_64.tgz"
  # local_file: "/path/to/MLNX_OFED_LINUX-24.10-2.1.8.0-ubuntu22.04-x86_64.tgz"
  download_url: "https://file.mir.blsc.cn/..."

# 内核配置
kernel:
  mode: "keep"                # keep | specify
  keep:
    lock_version: true        # 锁定当前内核版本
    update_grub: true         # 更新GRUB固定启动版本
  specify:
    version: null             # specify模式时指定版本

# OpenSSH 配置
openssh:
  min_version: "1:8.9p1-3ubuntu0.10"  # CVE-2024-6387 修复版本
  auto_upgrade: true

# NCCL 配置
nccl:
  enabled: false
  install_method: "source"    # source | package
  install_path: "/home/ubuntu/nccl"
```

### versions.yaml 字段说明

| 软件 | 字段 | 说明 |
|------|------|------|
| **cuda** | `mode` | keep=保持现有版本, install=安装指定版本 |
| | `version` | CUDA 版本号 |
| | `toolkit_file` | 安装包文件名 |
| | `download_url` | 下载地址（登录服务器下载） |
| | `local_file` | 本机文件路径（上传到登录服务器） |
| **nvidia_driver** | `mode` | keep / install |
| | `version` | 驱动版本号 |
| | `file` | 安装包文件名 |
| **mlnx_ofed** | `mode` | keep / install |
| | `version` | OFED 版本号 |
| **kernel** | `mode` | keep=保持当前内核, specify=指定版本 |

## 常见配置问题

### 1. 登录用户未指定

**错误信息**: `节点[x]必须指定登录用户 (username)`

**解决方案**: 在每个节点配置中添加 `username` 字段:
```yaml
nodes:
  - hostname: "gpu-node-01"
    ip: "10.0.0.1"
    username: "root"        # 必须指定
    password: "your-password"
```

### 2. 认证配置优先级

节点认证的优先级（从高到低）:
1. 节点级别配置 `nodes[].username/password/private_key`
2. 跳转服务器的 `node_auth` 配置
3. 跳转服务器的认证配置

### 3. 磁盘格式化警告

`format_disk` 默认为 `false`，这是**安全默认值**。

如果需要格式化磁盘，必须**明确确认**:
```yaml
storage:
  type: "single"
  device: "/dev/nvme0n1"
  mount_point: "/ssd"
  format_disk: true    # ⚠️ 高危操作，会清除磁盘所有数据
```

### 4. NFS 配置

如果不使用NFS，设置 `nfs.enabled: false`:
```yaml
nfs:
  enabled: false
```

## 实时日志

### 日志文件位置

```
/mnt/e/openclaw-workspace/deploy/logs/<集群名>/deploy_YYYYMMDD_HHMMSS.log
```

### 日志格式

```
[2026-04-02 10:30:15] INFO  ======== 开始GPU集群环境部署 ========
[2026-04-02 10:30:15] INFO  [Phase 0] 设备检查
[2026-04-02 10:30:16] INFO  [Step 00] RDMA设备一致性检查...
[2026-04-02 10:30:18] INFO  [Step 00] ✓ 完成 - RDMA设备数量: 8
[2026-04-02 10:30:18] INFO  [Step 00] GPU设备一致性检查...
[2026-04-02 10:30:20] INFO  [Step 00] ✓ 完成 - GPU设备数量: 8
```

### 实时写入策略

每条日志立即写入文件，确保:
- 执行过程可追踪
- 异常中断不丢失日志
- 支持远程监控

## 部署执行

### 调用方式

```bash
# 预检查模式
python gpu-cluster-deploy/src/main.py \
  --config-dir /mnt/e/openclaw-workspace/deploy/config/<集群名> \
  --log-dir /mnt/e/openclaw-workspace/deploy/logs/<集群名> \
  --dry-run

# 完整部署
python gpu-cluster-deploy/src/main.py \
  --config-dir /mnt/e/openclaw-workspace/deploy/config/<集群名> \
  --log-dir /mnt/e/openclaw-workspace/deploy/logs/<集群名> \
  --log-level INFO

# 指定阶段
python gpu-cluster-deploy/src/main.py \
  --config-dir /mnt/e/openclaw-workspace/deploy/config/<集群名> \
  --log-dir /mnt/e/openclaw-workspace/deploy/logs/<集群名> \
  --phase 1 --phase 2

# 使用新CLI模式
python gpu-cluster-deploy/src/main.py --new-cli \
  --config-dir /mnt/e/openclaw-workspace/deploy/config/<集群名> \
  --log-dir /mnt/e/openclaw-workspace/deploy/logs/<集群名> \
  --category gpu --category network
```

### 部署阶段

| Phase | 名称 | 内容 |
|-------|------|------|
| 0 | 设备检查 | RDMA/GPU/NVMe一致性验证 |
| 1 | SSH & Hosts | SSH免密、主机名配置 |
| 2 | 系统检查 | 内核、glibc、OpenSSH验证 |
| 3 | 基础配置 | 磁盘挂载、sudo、rc.local |
| 4 | 安全配置 | 用户创建、文件限制 |
| 5 | 网络驱动 | MLNX_OFED、NVIDIA驱动 |
| 6 | GPU环境 | CUDA、NCCL、RDMA配置 |
| 7 | 高级配置 | 时间同步、NFS配置 |

## 执行后检查

### 检查项目

| # | 检查项 | 命令 |
|---|--------|------|
| 1 | GPU状态 | `nvidia-smi` |
| 2 | RDMA设备 | `ibv_devinfo` |
| 3 | 网络接口 | `ip addr show` |
| 4 | NFS挂载 | `df -h \| grep nfs` |
| 5 | 时间同步 | `chronyc sources` |
| 6 | CUDA版本 | `nvcc --version` |
| 7 | 驱动版本 | `cat /proc/driver/nvidia/version` |

### 检查脚本

```bash
# 自动生成检查报告
python -c "
from src.steps.step_final_verification import FinalVerification
# 执行验证并生成报告
"
```

## 交互流程示例

```
用户: 部署新集群 gpu-cluster-002

Claude: 收到部署任务。请提供以下信息:

1. 跳转服务器 IP:
2. 跳转服务器 SSH 认证方式 (key/password):
3. 节点列表 (hostname, IP, roles):
4. 网络配置:
5. 软件版本 (使用默认版本?):

用户: [提供信息]

Claude: 正在生成配置文件...

配置文件已生成:
- /mnt/e/openclaw-workspace/deploy/config/gpu-cluster-002/cluster.yaml
- /mnt/e/openclaw-workspace/deploy/config/gpu-cluster-002/versions.yaml

请确认配置是否正确? [y/N]

用户: y

Claude: 正在执行预检查 (--dry-run)...

[预检查结果]
✓ 配置文件语法正确
✓ 安装包可用
✓ 网络配置有效
⚠ 跳转服务器连接需要验证

预检查通过。是否开始实际部署? [y/N]

用户: y

Claude: 开始部署... 日志文件: deploy_20260402_103015.log

[Phase 0] 设备检查...
[Phase 1] SSH & Hosts...
...

部署完成。正在执行验证...

✓ 所有检查通过
✓ 报告已生成: report.html
```

## 错误处理

### 常见错误

| 错误 | 原因 | 解决方案 |
|------|------|----------|
| 跳转服务器连接失败 | SSH认证错误 | 检查密钥/密码 |
| 节点不可达 | 网络问题 | 检查跳转服务器路由 |
| 安装包不存在 | 文件缺失 | 检查packages目录 |
| 步骤执行失败 | 配置/环境问题 | 查看详细日志 |

### 恢复机制

- 部署中断后可从失败步骤继续
- 支持单独重新执行失败的阶段
- 日志记录完整，便于问题定位

## 相关命令

- `/remote-test` - 远程GPU集群测试
- `/task-status` - 查看任务执行状态
- `/task-resume` - 恢复中断的任务