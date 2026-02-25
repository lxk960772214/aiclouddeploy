# GPU Cluster Deploy

GPU集群自动化部署工具，支持通过跳转服务器批量部署GPU集群。

## 功能特性

- **跳转服务器支持**: 支持密码认证和密钥认证
- **批量节点配置**: 使用hosts格式批量定义节点，支持个别覆盖
- **设备一致性检查**: 自动检测RDMA和以太网设备序列一致性
- **模块化执行**: 支持按分类、按模块、按计划执行部署步骤
- **网络配置增强**: 支持选择性网卡重命名和非连续设备映射
- **完整部署流程**: 34个标准化部署步骤
- **灵活配置**: YAML配置文件，支持自定义版本
- **详细日志**: 结构化日志、进度追踪、HTML报告

## 部署步骤

| Group | 步骤 | 描述 |
|-------|------|------|
| 0 | 00 | 设备一致性检查（新增） |
| A | 01-04 | 系统检查（依赖、内核、glibc、OpenSSH） |
| B | 05-09 | 基础配置（sudo、磁盘、MSR、rc.local、主机名） |
| C | 10-13 | 用户与SSH（用户创建、免密登录、CPU性能、文件描述符） |
| D | 15-19 | 系统优化（禁止更新、固定内核、时区、IPv6、休眠） |
| E | 20-23 | 网络驱动（Mellanox、nouveau、NVIDIA驱动、Fabric Manager） |
| F | 24-28 | GPU环境（CUDA、NCCL、RDMA重命名、GPU持久模式、内核模块） |
| G | 29-34 | 高级配置（ACS、时间同步、NFS） |

## 快速开始

### 1. 安装依赖

```bash
cd gpu-cluster-deploy
pip install -r requirements.txt
```

### 2. 配置集群

编辑 `config/cluster.yaml`:

```yaml
cluster:
  name: "gpu-cluster-001"

jumphost:
  host: "公网IP"
  port: 22
  auth:
    type: "key"
    username: "ubuntu"
    private_key: "~/.ssh/id_rsa"

nodes:
  - hostname: "gpu-master"
    ip: "10.254.43.65"
    roles: [nfs_server, time_server]
    storage:
      type: "raid10"
      devices: ["/dev/nvme0n1", "/dev/nvme1n1", "/dev/nvme2n1", "/dev/nvme3n1"]
      mount_point: "/ssd"
      format_disk: false

  - hostname: "gpu-node-01"
    ip: "10.254.43.66"
    roles: [gpu_node]
    storage:
      type: "single"
      device: "/dev/nvme0n1"
      mount_point: "/ssd"
      format_disk: false
```

### 3. 配置版本

编辑 `config/versions.yaml`:

```yaml
cuda:
  version: "12.8"

nvidia_driver:
  version: "590.48.01"

kernel:
  mode: "keep"  # 或 "specify" 指定版本

mlnx_ofed:
  version: "24.10-2.1.8.0"
```

### 4. 执行部署

```bash
# 预检查模式
python -m src.main --dry-run

# 完整部署
python -m src.main

# 只执行特定阶段
python -m src.main --phase 1 --phase 2

# 使用新CLI（模块化执行）
python -m src.main --new-cli --categories gpu,network
```

## 命令行参数

### 传统CLI

```
usage: main.py [-h] [--config-dir CONFIG_DIR] [--phase PHASE] [--step STEP]
               [--dry-run] [--report-only] [--log-level {DEBUG,INFO,WARNING,ERROR}]
               [--log-dir LOG_DIR]

optional arguments:
  --config-dir, -c     配置文件目录 (默认: config)
  --phase, -p          只执行指定阶段（可多次指定）
  --step, -s           只执行指定步骤（可多次指定）
  --dry-run            预检查模式，不执行实际部署
  --report-only        只生成部署报告
  --log-level          日志级别 (默认: INFO)
  --log-dir            日志目录 (默认: logs)
```

### 新CLI (模块化执行)

```
usage: main.py --new-cli [-h] [--config-dir CONFIG_DIR]
                         [--categories CATEGORIES] [--modules MODULES]
                         [--plan PLAN] [--dry-run] [--report-format FORMAT]

optional arguments:
  --new-cli            启用新CLI模式
  --categories         按分类执行：system,network,storage,gpu,security
  --modules            按模块ID执行，逗号分隔
  --plan               从YAML文件加载执行计划
  --report-format      报告格式：text,json,markdown (默认: text)
```

## 新功能详解

### 1. 批量节点配置

使用hosts格式批量定义节点：

```yaml
cluster:
  name: gpu-cluster

node_batch:
  enabled: true
  hosts_file: hosts.txt  # 或使用 hosts_content 直接嵌入
  roles:
    - gpu_node
  storage_template:
    type: single
    device: /dev/nvme0n1
    mount_point: /ssd
    format_disk: false
  auth_template:
    type: key
    username: root
    private_key: /root/.ssh/id_rsa

# 覆盖特定节点
nodes_override:
  - hostname: gpu-node-01
    roles:
      - gpu_node
      - master
```

**hosts.txt:**
```
192.168.1.1 gpu-node-01
192.168.1.2 gpu-node-02
192.168.1.3 gpu-node-03
```

### 2. 设备一致性检查

部署前自动检查所有节点的设备序列一致性：

- RDMA设备 (mlx5_*)
- 以太网设备 (ens*)
- GPU拓扑和NUMA亲和性

检查结果会生成详细报告，包含修复建议。

### 3. 模块化执行

支持灵活的执行方式：

```bash
# 按分类执行
python -m src.main --new-cli --categories network,storage

# 执行特定模块
python -m src.main --new-cli --modules step_25_nvidia_driver,step_27_cuda

# 从计划文件执行
python -m src.main --new-cli --plan config/plans/gpu-only.yaml
```

**执行计划示例 (config/plans/gpu-only.yaml):**
```yaml
name: gpu-deployment
description: GPU相关部署步骤
modules:
  - module_id: step_25_nvidia_driver
    name: NVIDIA Driver
    category: gpu
  - module_id: step_27_cuda
    name: CUDA Toolkit
    category: gpu
```

### 4. 网络配置增强

支持选择性网卡重命名和非连续设备映射：

```yaml
network:
  rdma:
    enabled: true
    rename_pattern: "ib{index}"
    # 只重命名指定设备
    devices:
      - mlx5_0
      - mlx5_1
      - mlx5_2
      - mlx5_3

  ethernet:
    enabled: true
    rename_pattern: "eth{index}"
    devices:
      - ens2f0
      - ens2f1

  # 非连续映射
  mappings:
    - source: mlx5_0
      target: ib0
    - source: mlx5_2
      target: ib1
```

## 项目结构

```
gpu-cluster-deploy/
├── config/
│   ├── cluster.yaml          # 集群配置
│   ├── cluster_batch_example.yaml  # 批量配置示例
│   ├── versions.yaml         # 版本配置
│   └── plans/                # 执行计划
│       ├── gpu-only.yaml
│       └── full-deployment.yaml
├── src/
│   ├── main.py               # 主入口
│   ├── config_loader.py      # 配置加载器
│   ├── ssh_manager.py        # SSH管理器
│   ├── batch_executor.py     # 批量执行器
│   ├── cli/                  # 新CLI模块
│   │   ├── main.py           # CLI解析器
│   │   ├── execution_controller.py
│   │   └── progress_reporter.py
│   ├── deployment/           # 模块化执行框架
│   │   ├── core.py           # 基类和注册系统
│   │   ├── module_manager.py
│   │   ├── step_adapter.py
│   │   └── execution_plan.py
│   ├── network/              # 网络模块
│   │   ├── device_discovery.py
│   │   ├── device_checker.py
│   │   ├── nic_mapper.py
│   │   └── nic_renamer.py
│   ├── steps/                # 部署步骤
│   │   ├── step_0_device_check.py
│   │   ├── step_26_rdma_rename.py
│   │   └── step_26b_ethernet_rename.py
│   ├── utils/                # 工具模块
│   │   └── hosts_parser.py   # hosts解析器
│   └── models/               # 数据模型
│       ├── cluster.py
│       ├── device_check.py
│       ├── module.py
│       └── network.py
├── scripts/                  # 部署脚本
├── tests/                    # 单元测试
│   ├── integration/          # 集成测试
│   ├── test_batch_config.py
│   ├── test_device_check.py
│   ├── test_module_manager.py
│   ├── test_network_config.py
│   └── test_cli.py
├── docs/
│   └── config-examples.md    # 配置示例文档
├── logs/                     # 日志输出
└── requirements.txt          # Python依赖
```

## 配置说明

### 跳转服务器配置

```yaml
jumphost:
  host: "公网IP"
  port: 22
  auth:
    type: "key"           # key 或 password
    username: "ubuntu"
    private_key: "~/.ssh/id_rsa"
    # password: "密码"    # password认证时使用
  # 节点独立认证（可选）
  node_auth:
    type: "key"
    username: "root"
    private_key: "~/.ssh/node_key"
```

### 节点配置

```yaml
nodes:
  - hostname: "节点主机名"
    ip: "内网IP"
    roles:
      - gpu_node          # GPU计算节点
      - nfs_server        # NFS服务器
      - time_server       # 时间服务器
    storage:
      type: "single"      # single | raid1 | raid10 | lvm
      device: "/dev/nvme0n1"
      mount_point: "/ssd"
      format_disk: false  # 安全默认：不格式化
```

### 内核配置

```yaml
kernel:
  mode: "keep"            # 保持当前版本
  keep:
    lock_version: true
    update_grub: true

  # 或指定版本
  # mode: "specify"
  # specify:
  #   version: "5.15.0-91-generic"
```

## 日志与报告

- **日志文件**: `logs/deploy_YYYYMMDD_HHMMSS.log`
- **结构化日志**: `logs/deploy_YYYYMMDD_HHMMSS.jsonl`
- **HTML报告**: `logs/deployment_report.html`
- **进度报告**: `logs/progress_report.json`

## 测试

```bash
# 运行所有单元测试
python -m pytest tests/ -v

# 运行集成测试
python -m pytest tests/integration/ -v

# 运行带覆盖率报告
python -m pytest --cov=src --cov-report=html
```

## 注意事项

1. **驱动安装文件**: 需要预先下载 NVIDIA 驱动、CUDA Toolkit、MLNX_OFED 安装包
2. **重启要求**: 某些步骤需要重启才能生效（步骤 E、F）
3. **磁盘数据**: `format_disk` 默认为 false，防止意外数据丢失
4. **网络环境**: 确保跳转服务器和内网节点网络可达
5. **向后兼容**: 新功能保持向后兼容，旧配置文件无需修改

## 依赖

- Python 3.8+
- paramiko >= 3.0.0
- PyYAML >= 6.0
- colorama >= 0.4.6
- pdsh (目标节点需安装)

## 文档

- [配置示例文档](docs/config-examples.md)
- [发布检查清单](RELEASE-CHECKLIST.md)

## License

MIT License
