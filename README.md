# AI Cloud Deploy

AI 云平台自动化部署工具集，提供 GPU 集群环境配置、设备检查和模块化部署能力。

## 项目

### [gpu-cluster-deploy](./gpu-cluster-deploy)

GPU 集群环境自动化部署工具，支持大规模 GPU 集群的批量配置、设备一致性检查和模块化部署。

**核心功能：**

| 功能 | 描述 |
|------|------|
| 跳转服务器支持 | 通过堡垒机访问内网集群，支持密钥/密码认证 |
| 批量节点配置 | hosts 文件、模板生成、YAML 配置三种方式 |
| 设备一致性检查 | 部署前检查 RDMA/GPU/NVMe 设备集群一致性 |
| 模块化部署 | 按阶段/步骤/模块/分类/计划灵活执行 |
| 磁盘格式化选项 | 支持 single/RAID1/RAID10，可配置格式化策略 |
| 多版本软件栈 | CUDA、NVIDIA 驱动、MLNX_OFED 版本可配置 |

**支持的部署步骤：**

- 系统检查（依赖、内核、glibc、OpenSSH）
- 基础配置（sudo、磁盘、MSR、主机名）
- 网络驱动（MLNX_OFED、NVIDIA 驱动）
- GPU 环境（CUDA、NCCL、Fabric Manager）
- 高级配置（NFS、时间同步、ACS）

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

详细文档请参阅 [gpu-cluster-deploy/README.md](./gpu-cluster-deploy/README.md)。

## 系统要求

- Python 3.8+
- paramiko >= 3.0.0
- PyYAML >= 6.0
- colorama >= 0.4.6

## 许可证

MIT License
