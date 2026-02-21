# GPU Cluster Deploy

自动化GPU集群环境部署工具，支持通过跳转服务器批量部署GPU集群。

## 功能特性

- **跳转服务器支持**: 支持密码认证和密钥认证
- **批量操作**: 使用pdsh进行并行批量部署
- **完整部署流程**: 34个标准化部署步骤
- **灵活配置**: YAML配置文件，支持自定义版本
- **详细日志**: 结构化日志、进度追踪、HTML报告

## 部署步骤

| Group | 步骤 | 描述 |
|-------|------|------|
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

  - hostname: "gpu-node-01"
    ip: "10.254.43.66"
    roles: [gpu_node]
    storage:
      type: "single"
      device: "/dev/nvme0n1"
      mount_point: "/ssd"
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
```

## 命令行参数

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

## 项目结构

```
gpu-cluster-deploy/
├── config/
│   ├── cluster.yaml          # 集群配置
│   └── versions.yaml         # 版本配置
├── src/
│   ├── main.py               # 主入口
│   ├── config_loader.py      # 配置加载器
│   ├── ssh_manager.py        # SSH管理器
│   ├── batch_executor.py     # 批量执行器
│   ├── steps/                # 部署步骤
│   ├── utils/                # 工具模块
│   └── models/               # 数据模型
├── scripts/                  # 部署脚本
├── tests/                    # 单元测试
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
      type: "single"      # single | raid1 | raid10
      device: "/dev/nvme0n1"
      mount_point: "/ssd"
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

## 注意事项

1. **驱动安装文件**: 需要预先下载 NVIDIA 驱动、CUDA Toolkit、MLNX_OFED 安装包
2. **重启要求**: 某些步骤需要重启才能生效（步骤 E、F）
3. **磁盘数据**: 磁盘挂载操作会格式化设备，请确保数据安全
4. **网络环境**: 确保跳转服务器和内网节点网络可达

## 依赖

- Python 3.8+
- paramiko >= 3.0.0
- PyYAML >= 6.0
- pdsh (目标节点需安装)

## License

MIT License
