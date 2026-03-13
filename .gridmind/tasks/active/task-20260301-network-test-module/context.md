# 网络配置重构和测试模块 - 决策背景

## 项目背景

### 当前状态
gpu-cluster-deploy项目当前的网络配置格式过于简单，仅支持pattern匹配方式定义网卡：
```yaml
network:
  nics:
    compute_400g:
      pattern: "mlx5_[0-7]"
      count: 8
      net_prefix: "ib"
```

### 问题分析
1. **配置不够直观**：无法明确指定哪些网卡属于管理网、计算网、存储网
2. **IP选择策略缺失**：NFS配置和软件包传输需要根据网络类型选择不同IP
3. **缺少独立测试能力**：部署和测试耦合在一起，无法单独运行网络测试
4. **RoCE/IB检测不完善**：无法自动区分网络类型并采用相应测试方法

## 需求分析

### 需求1：网络配置格式重构

**目标格式**：
```yaml
# ib_write_bw测试参数
ib_write_bw:
  duration: 10
  size: 65536
  port_base: 18500
  min_bandwidth_percent: 90

# 管理网络 (25G bond网络)
management:
  description: "管理网络 (25G bond网络)"
  interfaces:
    - ens19f0np0
  rdma_devices:
    - mlx5_bond_0
  enabled: true
  skip_performance_test: true
  skip_inter_host_test: true
  theoretical_bandwidth_gbps: 25

# 计算网络 (400G RoCE网络)
compute:
  description: "计算网络 (400G RoCE网络)"
  interfaces:
    - ens11np0
    - ens12np0
    ...
  rdma_devices:
    - mlx5_0
    - mlx5_1
    ...
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

**关键设计决策**：
- 每个网络类型独立配置，包含interfaces和rdma_devices
- enabled字段控制是否检查该网络
- skip_performance_test跳过带宽测试（管理网通常不需要）
- skip_inter_host_test跳过跨主机测试
- theoretical_bandwidth_gbps定义理论带宽用于计算百分比

### 需求2：智能IP选择策略

**规则**：
1. 存储NFS配置：优先使用存储网IP，无存储网时使用管理网IP
2. 软件包传输：始终使用管理网IP
3. 常规通信：使用管理网IP

**实现方案**：
```python
def get_ip_for_purpose(host, purpose):
    if purpose == "storage_nfs":
        # 尝试存储网
        storage_ip = get_network_ip(host, "storage")
        if storage_ip:
            return storage_ip
        # 回退到管理网
        return get_network_ip(host, "management")
    elif purpose == "package_transfer":
        return get_network_ip(host, "management")
    else:
        return get_network_ip(host, "management")
```

### 需求3：独立测试模块

**功能要求**：
1. 检查所有部署步骤是否完成
2. RoCE/InfiniBand网络检测和测试
3. 三轮测试策略定位异常

**三轮测试策略**：

| 轮次 | 配对方式 | 目的 |
|------|---------|------|
| 第一轮 | 相邻配对 (1,2), (3,4)... | 初步检测 |
| 第二轮 | 错位配对 (2,3), (4,5)... | 交叉验证 |
| 第三轮 | 正常主机 vs 异常主机 | 精确定位 |

**测试流程**：
1. RoCE网络：ping -I 网卡名称 IP
2. RoCE/IB网络：ib_write_bw测试带宽
3. 记录结果，分析异常

## 技术方案

### 模块架构

```
src/network/
├── ip_resolver.py           # IP获取工具
├── rdma_detector.py         # RDMA设备类型检测
├── ibandwidth_tester.py     # ib_write_bw测试封装
├── three_phase_tester.py    # 三轮测试策略
├── deployment_verifier.py   # 部署验证检查
└── connectivity_checker.py  # 现有连通性检查

src/steps/
├── step_0c_network_rdma_test.py  # 独立测试步骤
└── step_34_nfs_config.py         # NFS配置(修改)
```

### 数据流

```
配置文件加载
    ↓
NetworkConfig解析
    ↓
┌──────────────────┐
│ IP智能选择       │
│ - 存储NFS        │
│ - 软件包传输     │
│ - 常规通信       │
└──────────────────┘
    ↓
部署步骤执行
    ↓
┌──────────────────┐
│ 独立测试模块     │
│ - 部署验证       │
│ - 网络测试       │
│ - 三轮定位       │
└──────────────────┘
```

## 风险评估

### 技术风险

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| 向后兼容问题 | 高 | 保留旧配置格式解析，添加迁移脚本 |
| 并发测试端口冲突 | 中 | 基于网卡名称计算唯一端口号 |
| 远程执行超时 | 中 | 设置合理超时，支持重试 |
| RDMA工具缺失 | 低 | 提前检查工具可用性 |

### 兼容性考虑

1. **配置文件兼容**：
   - 新代码能解析旧配置格式
   - 旧配置自动转换为新格式

2. **API兼容**：
   - 保留现有接口
   - 新增接口不破坏现有功能

## 参考资源

### 现有代码参考
- `/mnt/e/github/roce-checker/roce_checker.py`：完整的RoCE/IB检测和测试实现
- `/mnt/e/github/roce-checker/config.yaml`：网络配置格式参考
- `src/network/connectivity_checker.py`：现有连通性检查实现
- `src/steps/step_final_verification.py`：部署验证实现参考

### 关键实现参考

**RDMA设备类型检测**：
```python
# 方法1: 检查transport类型
cat /sys/class/infiniband/{device}/transport

# 方法2: 使用ibv_devinfo
ibv_devinfo -v

# 方法3: 使用rdma link
rdma link show
```

**ib_write_bw测试**：
```python
# InfiniBand模式
server: ib_write_bw -d {device} -F -s {size} -D {duration} -p {port}
client: ib_write_bw -d {device} -F -s {size} -D {duration} -p {port} {server_hostname}

# RoCE模式
server: ib_write_bw -d {device} -R -F -s {size} -D {duration} -p {port}
client: ib_write_bw -d {device} -R -F -s {size} -D {duration} -p {port} {server_hostname}
```

## 实施顺序

1. **Phase 1**：数据模型重构（Steps 1-3）
2. **Phase 2**：IP智能选择（Steps 4-5）
3. **Phase 3**：网络测试模块（Steps 6-10）
4. **Phase 4**：CLI集成（Step 11）
5. **Phase 5**：测试和文档（Step 12）

## 验收标准

1. 所有单元测试通过，覆盖率>80%
2. 配置文件格式转换正确
3. NFS配置使用正确的网络IP
4. 三轮测试能够定位异常网卡
5. 生成完整的测试报告
