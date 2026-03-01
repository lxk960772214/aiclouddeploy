# AI Cloud Deploy

AI 云平台自动化部署工具集，提供 GPU 集群环境配置、设备检查、网络测试和模块化部署能力。

## 项目

### [gpu-cluster-deploy](./gpu-cluster-deploy)

GPU 集群环境自动化部署工具，支持大规模 GPU 集群的批量配置、设备一致性检查、网络测试和模块化部署。

**核心功能：**

| 功能 | 描述 |
|------|------|
| 跳转服务器支持 | 通过堡垒机访问内网集群，支持密钥/密码认证 |
| 批量节点配置 | hosts 文件、模板生成、YAML 配置三种方式 |
| 设备一致性检查 | 部署前检查 RDMA/GPU/NVMe 设备集群一致性 |
| 网络测试模块 | 三轮测试策略定位异常 RDMA 设备，带宽测试 |
| 模块化部署 | 按阶段/步骤/模块/分类/计划灵活执行 |
| 安装包管理器 | 自动下载、分发、校验，支持多种来源配置 |
| 磁盘格式化选项 | 支持 single/RAID1/RAID10，可配置格式化策略 |
| 多版本软件栈 | CUDA、NVIDIA 驱动、MLNX_OFED 版本可配置 |

**支持的部署步骤：**

- 系统检查（依赖、内核、glibc、OpenSSH）
- 网络检查（连通性测试、RDMA 带宽测试）
- 基础配置（sudo、磁盘、MSR、主机名）
- 网络驱动（MLNX_OFED、NVIDIA 驱动）
- GPU 环境（CUDA、NCCL、Fabric Manager）
- 高级配置（NFS、时间同步、ACS）
- 部署验证（网络配置验证、服务状态检查）

**快速开始：**

```bash
cd gpu-cluster-deploy
pip install -r requirements.txt

# 配置集群
vim config/cluster.yaml
vim config/versions.yaml

# 执行部署
python src/main.py --dry-run
python src/main.py
```

**安装包配置方式：**

支持多种方式指定驱动和软件包位置：

| 方式 | 配置字段 | 说明 |
|------|----------|------|
| 登录服务器下载 | `download_url: "https://..."` | 在登录服务器下载后分发到 GPU 节点 |
| 本机文件上传 | `local_file: "/home/user/xxx.run"` | 从本机上传到登录服务器再分发 |
| 集群节点已有 | `local_file: "/opt/software/xxx.run"` | 推荐方式，预先放到集群节点 |

示例配置 (`config/versions.yaml`)：

```yaml
# 方式一：登录服务器下载（推荐）
cuda:
  version: "12.8"
  download_url: "https://developer.download.nvidia.com/compute/cuda/12.8.0/local_installers/cuda_12.8.0_570.86.10_linux.run"

# 方式二：本机文件上传
nvidia_driver:
  version: "590.48.01"
  local_file: "/home/user/software/NVIDIA-Linux-x86_64-590.48.01.run"
```

**网络测试命令：**

```bash
# 执行 RDMA 网络测试
python -m src.cli.network_test_cli --config config/cluster.yaml

# 指定主机和网络类型
python -m src.cli.network_test_cli --config config/cluster.yaml --hosts node01,node02 --network compute

# 生成 HTML 报告
python -m src.cli.network_test_cli --config config/cluster.yaml --format html --output report.html
```

详细文档请参阅 [gpu-cluster-deploy/README.md](./gpu-cluster-deploy/README.md)。

## 系统要求

- Python 3.8+
- paramiko >= 3.0.0
- PyYAML >= 6.0
- colorama >= 0.4.6

## 许可证

MIT License
