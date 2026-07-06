#!/bin/bash 

# tar -zxvf packages/uv-x86_64-unknown-linux-gnu.tar.gz -C packages/
# mv packages/uv-x86_64-unknown-linux-gnu/uv* /usr/local/bin/
# uv venv 
source .venv/bin/activate
# export UV_DEFAULT_INDEX=https://mirrors.aliyun.com/pypi/simple
#uv pip install -r requirements.txt
export PYTHONPATH=$(pwd):$PYTHONPATH

# base
# 包含基础网络配置，比如dns，http联通性；上海时区设置
# python src/main.py --step 0 --step 0b --step 0d --step 0e --step 01 --step 02 --step 03 --step 04 --step 05 --step 07 --step 08 --step 09 --step 10 --step 12 --step 13 --step 15 --step 16 --step 17 --step 18 --step 19 --step 29

python src/main.py --step 0e

# 磁盘 
# 06 挂载磁盘 34 配置nfs
# python src/main.py --step 06 --step 34
# python src/main.py --step 34

# 网络
# 20 Mellanox OFED 驱动 26 重命名 RDMA 网卡 
# python src/main.py  --step 20

# 时间
# 30 NTP时间同步
# python src/main.py --step 30

# gpu
# 21 禁用开源 NVIDIA 驱动 22 安装 NVIDIA 驱动 23 安装 NVLink Fabric Manager 24 安装 CUDA 工具包 25 安装 NCCL 通信库 27 启用 GPU 持久化模式 28 配置加载 NVIDIA 内核模块 
# python src/main.py --step 21 --step 22 --step 24 --step 25 --step 27 --step 28

# 测试
# 41 NCCL 单机多卡测试 42 NCCL 显卡配对测试 43 Sysbench CPU 测试 44	GPU Burn 测试 45 NCCL 多节点测试
# python src/main.py --step 40 --step 41 --step 42 --step 43 --step 44 --step 45 
# python src/main.py --step 41



