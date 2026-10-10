#!/bin/bash 

cd /Users/liuxinke/Nutstore\ Files/work/裸金属/aiclouddeploy/gpu-cluster-deploy

# tar -zxvf packages/uv-x86_64-unknown-linux-gnu.tar.gz -C packages/
# mv packages/uv-x86_64-unknown-linux-gnu/uv* /usr/local/bin/
# uv venv 
source .venv/bin/activate
# export UV_DEFAULT_INDEX=https://mirrors.aliyun.com/pypi/simple
#uv pip install -r requirements.txt
export PYTHONPATH=$(pwd):$PYTHONPATH

# base
# 检查网络连接、节点互通和节点名绑定
# python src/main.py --config config/cluster-henandianxin.yaml --step 0 
python src/main.py --config config/cluster-henandianxin.yaml --step 0b --step 0d --step 09
# 禁止密码登录
# python src/main.py --config config/cluster-henandianxin-B300.yaml --step 0e
# 其他基础配置，cpu gpu通用
# python src/main.py --config config/cluster-henandianxin-B300.yaml --step 01 --step 02 --step 03 --step 04 --step 05 --step 07 --step 08 --step 12 --step 13 --step 15 --step 16 --step 17 --step 18 --step 19 --step 29

# 磁盘 
# 06 挂载磁盘 34 配置nfs
# python src/main.py --config config/cluster-henandianxin-B300.yaml --step 06 
# python src/main.py --config config/cluster-henandianxin-B300.yaml --step 34

# 网络
# 20 Mellanox OFED 驱动 26 重命名 RDMA 网卡 
# python src/main.py  --config config/cluster-henandianxin-B300.yaml --step 20

# 时间
# 30 NTP时间同步
# python src/main.py --config config/cluster-henandianxin-B300.yaml --step 30

# gpu
# 21 禁用开源 NVIDIA 驱动 22 安装 NVIDIA 驱动 23 安装 NVLink Fabric Manager 24 安装 CUDA 工具包 25 安装 NCCL 通信库 27 启用 GPU 持久化模式 28 配置加载 NVIDIA 内核模块 
# 检查持久化 
# python src/main.py --config config/cluster-henandianxin-B300.yaml --step 21 --step 22 --step 23 --step 27 --step 28
# python src/main.py --config config/cluster-shunfeng.yaml --step 21 --step 22 --step 27 --step 28
# 安装cudatoolkit
# python src/main.py --config config/cluster-henandianxin-B300.yaml --step 24
# 安装nccl通信库
# python src/main.py --config config/cluster-shunfeng.yaml --step 25
# python src/main.py --config config/cluster-shunfeng.yaml --step 23


# 测试
# 41 NCCL 单机多卡测试 42 NCCL 显卡配对测试 43 Sysbench CPU 测试 44	GPU Burn 测试 45 NCCL 多节点测试
# python src/main.py --config config/cluster-shunfeng.yaml --step 40 --step 41 --step 42 --step 43 --step 44 --step 45
#单节点nccltest测试
# python src/main.py --config config/cluster-henandianxin-B300.yaml --step 41
#多节点nccltest测试
# python src/main.py --config config/cluster-henandianxin-B300.yaml --step 45
#GPUburn
# python src/main.py --config config/cluster-henandianxin-B300.yaml --step 44


