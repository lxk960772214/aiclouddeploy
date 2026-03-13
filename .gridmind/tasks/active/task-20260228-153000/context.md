# GPU集群部署配置检查功能审计

## 目标

审计所有部署步骤的配置检查功能，确保每个步骤能够正确检测是否已配置，避免重复执行已完成的配置。

---

## 一、所有步骤配置检查方法实现状态

### 已实现 `is_configured()` 方法的步骤

| 步骤ID | 步骤名称 | 检查方法 | 检查逻辑 |
|--------|----------|----------|----------|
| 01 | 安装依赖软件包 | ✓ 已实现 | 检查关键包(build-essential, gcc, make, dkms, pdsh, git, cmake)是否已安装 |
| 12 | 设置CPU性能模式 | ✓ 已实现 | 检查所有CPU核心的governor是否为performance |
| 22 | 安装NVIDIA GPU驱动 | ✓ 已实现 | 通过nvidia-smi、/proc/driver/nvidia/version、内核模块三种方式检测版本 |

### 未实现 `is_configured()` 方法的步骤

| 步骤ID | 步骤名称 | 建议检查方法 |
|--------|----------|--------------|
| 00 | 设备一致性检查 | 检查类 - 每次都执行，无需配置检查 |
| 0b | 网络连通性检查 | 检查类 - 每次都执行，无需配置检查 |
| 02 | 检查内核版本一致性 | 检查类 - 无需配置检查 |
| 03 | 检查glibc版本一致性 | 检查类 - 无需配置检查 |
| 04 | 检查OpenSSH版本 | 检查类 - 无需配置检查 |
| **05** | **设置sudo免密** | **需要添加** - `sudo -n true` 测试 |
| 06 | 挂载数据盘 | 检查fstab挂载点是否存在 |
| 07 | 设置MSR | 特定机型检测，需要添加 |
| 08 | 配置rc.local | 检查服务是否启用 |
| 09 | 设置主机名和hosts绑定 | 检查主机名和hosts文件 |
| **10** | **创建ubuntu用户** | **需要添加** - `id ubuntu` 检查 |
| **11** | **设置SSH免密登录** | **需要添加** - 检查authorized_keys文件 |
| 13 | 设置文件描述符 | 检查limits.conf配置 |
| 15 | 禁止系统自动更新 | 检查unattended-upgrades服务状态 |
| 16 | 固定内核版本 | 检查GRUB配置 |
| 17 | 更改时区和更新系统时间 | 检查时区设置 |
| 18 | 禁用IPv6 | 检查sysctl配置 |
| 19 | 触发vmcore日志和禁止系统休眠 | 检查sleep.target状态 |
| 20 | 安装Mellanox驱动 | 内部已实现版本检测逻辑 |
| 21 | 禁用nouveau驱动 | 检查blacklist配置 |
| 23 | 安装nvidia-fabricmanager | 检查服务状态 |
| 24 | 安装CUDA Toolkit | 内部已实现版本检测逻辑 |
| 25 | 安装NCCL通信库 | 检查安装目录 |
| 26 | IB/RoCE网卡重命名 | 检查网卡名称 |
| 26b | 以太网网卡重命名 | 检查网卡名称 |
| 27 | 设置GPU持久模式 | 检查服务状态 |
| 28 | 内核加载NVIDIA相关模块 | 检查配置文件 |
| 29 | 关闭ACS | 检查脚本是否存在 |
| 30 | 配置时间同步服务器 | 检查chrony配置 |
| 34 | 配置NFS网络存储 | 检查NFS挂载 |

---

## 二、现有 `is_configured()` 方法评估

### 步骤01: 安装依赖软件包

**检查逻辑**:
```bash
dpkg -l <packages> 2>/dev/null | grep -c '^ii'
```

**评估**: ✅ 正确
- 检查关键包是否安装
- 返回缺失包列表

**问题**: 无

---

### 步骤12: 设置CPU性能模式

**检查逻辑**:
```bash
cat /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor
```

**评估**: ✅ 正确
- 检查所有CPU核心
- 处理不支持cpufreq的情况

**问题**: 无

---

### 步骤22: 安装NVIDIA GPU驱动

**检查逻辑**:
1. `nvidia-smi --query-gpu=driver_version`
2. `/proc/driver/nvidia/version`
3. `modinfo nvidia`

**评估**: ✅ 正确
- 多种检测方式保证准确性
- 版本匹配检查

**问题**: 无

---

## 三、需要添加 `is_configured()` 的关键步骤

### 优先级高（影响重复执行效率）

| 步骤 | 建议实现 |
|------|----------|
| **05-sudo免密** | `sudo -n true 2>/dev/null && echo 'ok' \|\| echo 'need_password'` |
| **11-SSH免密** | `test -s /home/ubuntu/.ssh/authorized_keys` |
| **10-创建用户** | `id ubuntu 2>/dev/null && echo 'exists' \|\| echo 'not_exists'` |

### 优先级中

| 步骤 | 建议实现 |
|------|----------|
| 13-文件描述符 | `grep -q 'nofile 1000000' /etc/security/limits.conf` |
| 17-时区设置 | `timedatectl show \| grep -q 'Timezone=Asia/Shanghai'` |
| 18-禁用IPv6 | `test $(cat /proc/sys/net/ipv6/conf/all/disable_ipv6) -eq 1` |
| 21-禁用nouveau | `grep -q 'blacklist nouveau' /etc/modprobe.d/blacklist.conf` |

### 优先级低（执行时间短或需要每次执行）

| 步骤 | 建议 |
|------|------|
| 02/03/04 | 检查类步骤，无需配置检查 |
| 00/0b | 每次都需要检查，设置 `skip_if_configured = False` |

---

## 四、前置检查项目清单

部署开始前需要检查的项目：

### 1. 连接性检查
- [ ] 跳板机到所有节点的SSH连通性
- [ ] 节点之间的网络连通性
- [ ] 外网访问能力（用于下载软件包）

### 2. 权限检查
- [ ] SSH用户具有sudo权限
- [ ] SSH用户密码正确

### 3. 系统信息收集
- [ ] 所有节点操作系统版本一致
- [ ] 所有节点内核版本一致（多机环境）
- [ ] 所有节点glibc版本一致（多机环境）
- [ ] OpenSSH版本安全（无CVE漏洞）

### 4. 硬件检查
- [ ] RDMA设备一致性
- [ ] 以太网设备一致性
- [ ] GPU设备一致性
- [ ] NVMe设备一致性
- [ ] GPU拓扑一致性

### 5. 配置文件验证
- [ ] 集群配置文件格式正确
- [ ] 版本配置文件格式正确
- [ ] 必要的安装包路径或下载URL配置

---

## 五、后置报告检查项目清单

部署完成后需要验证的项目：

### 1. 基础系统配置

| 检查项 | 命令 |
|--------|------|
| sudo免密 | `sudo -n true` |
| SSH免密登录 | `ssh -o BatchMode=yes <host> 'echo ok'` |
| 主机名设置 | `hostname` |
| hosts绑定 | `grep <hostname> /etc/hosts` |
| 时区设置 | `timedatectl \| grep 'Time zone'` |
| 文件描述符 | `ulimit -n` |
| CPU性能模式 | `cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor` |
| IPv6禁用 | `cat /proc/sys/net/ipv6/conf/all/disable_ipv6` |
| 自动更新禁用 | `systemctl is-enabled unattended-upgrades` |

### 2. GPU相关配置

| 检查项 | 命令 |
|--------|------|
| NVIDIA驱动版本 | `nvidia-smi --query-gpu=driver_version --format=csv,noheader` |
| GPU持久模式 | `nvidia-smi -q \| grep 'Persistence Mode'` |
| CUDA版本 | `/usr/local/cuda/bin/nvcc -V` |
| Fabric Manager服务 | `systemctl is-active nvidia-fabricmanager` |
| NVIDIA内核模块 | `lsmod \| grep nvidia` |

### 3. RDMA/网络配置

| 检查项 | 命令 |
|--------|------|
| MLNX OFED驱动 | `ofed_info -s` |
| IB设备状态 | `ibstat \| grep 'State'` |
| RDMA网卡命名 | `rdma dev show` |
| 以太网网卡命名 | `ip link show` |

### 4. 服务状态

| 检查项 | 命令 |
|--------|------|
| chrony时间同步 | `chronyc tracking` |
| rc-local服务 | `systemctl is-enabled rc-local` |
| NFS挂载(如启用) | `df -h <mount_point>` |

### 5. 集群一致性验证

| 检查项 | 说明 |
|--------|------|
| 时间同步偏差 | 所有节点时间差 < 1秒 |
| 主机名解析 | 所有节点可以解析其他节点主机名 |
| SSH免密互通 | 所有节点之间可以免密SSH |

---

## 六、改进建议

### 1. 需要立即添加 `is_configured()` 的步骤

**优先级最高**:
- step_5_sudo_nopasswd.py
- step_10_create_user.py
- step_11_ssh_key.py

### 2. 需要改进现有检查方法的步骤

**步骤10 - 创建用户**:
- 当前只在 `post_check` 中检查
- 需要添加 `is_configured()` 方法

**步骤11 - SSH免密**:
- 当前 `post_check` 只检查文件存在
- 需要实际测试免密登录是否有效

### 3. 建议设置 `skip_if_configured = False` 的步骤

- step_0_device_check.py - 设备检查每次都要执行
- step_0b_network_check.py - 网络检查每次都要执行

### 4. 添加统一的配置检查报告生成器

建议创建一个报告生成器，在部署开始和结束时输出完整的配置状态报告。

---

## 决策记录

1. **为什么某些步骤不需要 `is_configured()`**:
   - 检查类步骤（02, 03, 04）每次都需要验证
   - 条件执行步骤（07, 20, 23, 25）内部已实现条件判断

2. **版本检测策略**:
   - 驱动类步骤使用版本匹配而非简单存在性检查
   - 确保版本与配置一致才跳过

3. **检查方法设计原则**:
   - 使用非破坏性命令
   - 检查结果可缓存
   - 支持单个主机检查
