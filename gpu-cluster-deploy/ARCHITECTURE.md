# GPU Cluster Deploy 代码架构

## 本文档的维护协议（先读这节）

这份文档的目标读者是**接手维护的 AI 或人类**，它是"代码看不出来的约束"的唯一存放地。代码本身能表达的（函数做什么、字段有哪些）不写在这里；只有"为什么这样设计、踩过什么坑、什么改动会牵连什么"才写。

维护规则：

1. **修一个 bug → 必须回写**：在对应步骤章节追加一条"常见坑"，格式固定为 `症状 → 根因 → 修复原则`。不复盘的 bug 等于没修——下次换个形式还会踩。
2. **重大事故 → 进"事故档案"**：带日期、带完整因果链。案例比原则好检索，LLM 和人都一样。
3. **改数据流/编排/认证 → 更新对应章节的图**：图过时比没有图更危险。
4. **每条坑只写约束，不写流水账**：一句话能说清的根因不要写成三段论。
5. **修改原则清单是改任何代码前的 checklist**（见文末），新增原则需注明动机。

诊断入口：**"部署报成功但实际没配置"** → 几乎必然是 `is_configured()` 误报 True，直接去该步骤的 `is_configured` 检查语义（是"目标状态已达成"还是"无需动作"，两者不能混）。真实案例见事故档案 2026-08-21。

## 陷阱速查索引

按"症状"组织，用于快速定位，详情见各章节：

| 症状/场景 | 根因 | 核心原则 |
|-----------|------|----------|
| 部署成功但目标没配置 | `is_configured` 把"配置缺失/异常"返回成 True | 配置缺失≠已配置；只有"明确无需动作"才返回 True |
| 步骤被莫名跳过 | echo 标记子串误判（`"found" in "not_found"` 为 True） | 标记用 `yes`/`no` 无歧义词，`==` 精确匹配 |
| `mode=keep` 时子选项没生效 | `is_configured` 只看 mode 不看子选项（如 `keep.lock_version`） | mode 与子选项必须联动判断 |
| `nfs.server` 写了不生效 | `nfs_server_node` 按角色查找，不看该字段 | 显式配置字段必须被消费，否则等于诱导误配 |
| RAID 每次运行多一份配置 | `mdadm --detail --scan >> mdadm.conf` 追加 | 幂等操作用覆盖（`>`）而非追加（`>>`） |
| mdadm create 报签名残留 | nvme 旧分区/超级块未清 | 先 wipe（zero-superblock + wipefs + dd 清头部）再 create |
| nvidia-smi 驱动用户态断裂 | `apt purge 'libcuda*'` 误伤驱动库 | 批量 purge 通配符先想清楚会命中谁 |
| `dpkg -l` 查不到已装的驱动库 | `.run` 包安装不走 dpkg | 验证手段要与安装手段同源（`ls`+`ldconfig -p`） |
| sed 替换出双重路径 | 目标串是其他串的子串（`/usr` ⊂ `/usr/local/cuda`） | sed 前确认目标串有唯一锚点 |
| PTX `unsupported toolchain` | toolkit 版本高于 driver 的 JIT 能力 | toolkit 与 driver 版本对齐，不追新 |
| fabricmanager 装完拓扑降级 | 分支与驱动主版本不一致 | 版本主分支严格对齐（590 驱动配 590 FM） |
| dpkg -i 装完包不可用 | 不解析依赖，包停在未配置态 | `dpkg -i ... || apt-get install -f -y` |
| 节点有密码却走了密钥认证 | 认证回退链中 password 传入后 private_key 被默认值覆盖 | 认证三层回退有隐式耦合，改 ssh_manager 前读"认证参数流转" |
| 重复执行覆盖用户自定义内容 | 全量覆盖 /etc/exports、rc.local 等 | 先备份，只追加/修改必要部分 |
| 命令执行正常，`put_file`/上传却 Permission denied | 跳板机上原生 `scp` 中转依赖 跳板机→节点 免密，未跑免密分发的集群必然失败 | 文件传输与命令执行必须走同一条隧道连接、同一套认证；见事故档案 2026-09-07 |
| 批量脚本秒退 exit_code=-1 且无 stderr、手动跑却正常 | `pkill -f xxx` 把执行脚本的 bash 自杀（bash -c 的命令行=脚本文本，脚本内任何位置出现关键字都会被匹配） | SSH 通道内禁用 `pkill -f`，按 PID 杀并跳过 `$$`；见事故档案 2026-09-11 |
| `.deb` 被 chmod +x 当脚本执行报 `!<arch>` | `versions.yaml` 的 `nvidia_driver.local_file` 错填了 fabricmanager 的 deb | 驱动安装包必须是 `.run` 安装器，配置里相邻字段极易复制错 |
| lsmod 里有模块、卸载却报 not found | `modprobe -r` 按 /lib/modules 文件查找，模块文件被清理后对内存中已加载模块失效 | 卸载已加载模块用 `rmmod`（直接操作内核），`modprobe -r` 作回退 |
| `format_disk: false` 却照样 wipefs/dd 清了盘 | RAID 路径的 format_disk 守卫只放在"RAID 已存在且正确"分支，RAID 不存在时无条件走重建清盘 | 破坏性操作的守卫必须在进入破坏流程**之前**，且单盘/RAID 两条路径都要有；见事故档案 2026-09-11 step 06 |
| `mdadm --create` 报 Device or resource busy，lsblk 却无挂载 | 成员盘被 LVM 的 dm 设备（如 workdirvg-workdirlv）持有，umount 管不到 dm 层 | 清盘前先释放 dm 占用：vgchange -an，PV 头已被清掉时兜底 dmsetup remove；见事故档案 2026-09-11 step 06 |
| LVM 明明刚释放，mdadm create 时又 busy 了 | wipefs/dd 的 udev 事件触发 LVM 自动激活（`pvscan --cache -aay`），签名未清的分区上的 VG 被重新拉起；dd 只清盘头 10MB，够不到深处分区的 PV 头 | wipe 必须覆盖全部子分区签名（`wipefs -a 盘*`）+ `partx -d` 强删内核分区表 + create 前"验证-重试"循环；见事故档案 2026-09-11 step 06 |
| 节点 RDMA 名字对齐了，重启后又乱了 | `rdma dev set` 只写运行时，无持久化机制；且默认枚举跨机型不一致（同号不同 rail），开机后必须重新收敛 | RDMA 改名必须配 systemd oneshot 自愈脚本（每次按 IP 重新推导 rail），`is_configured` 命名+持久化双条件；见事故档案 2026-09-12 |
| awk 匹配 rdma link 的设备名全落空 | `$2` 是 `mlx5_0/1`（含端口后缀），与 `mlx5_0/` 全等比较永假 | 提取设备名要么 `sub(/\/.*/,"")` 截断，要么用 `$2 ~ "^mlx5_N/"` 正则；见事故档案 2026-09-12 |

## 目录结构

```
gpu-cluster-deploy/
├── src/
│   ├── main.py              # 入口 + GPUDeploy 编排器（run_phase 按 --step/--phase/全量三种模式分流）
│   ├── config_loader.py     # YAML → ClusterConfig 解析（node_batch 展开、角色补全在此）
│   ├── ssh_manager.py       # SSH连接池 + 跳板机管理（认证默认值的中枢）
│   ├── batch_executor.py    # 批量执行器 (SSH/pdsh)
│   ├── package_manager.py   # apt/yum 包管理
│   ├── cli/  deployment/    # CLI 与部署辅助
│   ├── models/
│   │   ├── cluster.py       # 静态配置: ClusterConfig, NodeConfig, NFSConfig, 角色判定属性...
│   │   └── node.py          # 运行时状态: NodeInfo, ClusterInfo
│   ├── steps/
│   │   ├── base.py          # BaseStep 基类（run/pre_check/is_configured/post_check 生命周期）
│   │   ├── step_*.py        # 40+ 部署步骤（00~0f 基础 / 1~19 系统 / 20~28 GPU / 29~34 高级 / 40~45 测试）
│   │   └── step_final_verification.py  # 99 最终验证
│   ├── network/             # 连通性/设备发现/RDMA/IB测试/网卡改名/IPResolver 等 15 个模块
│   └── utils/               # logger（含进度/HTML报告）、hosts_parser
└── config/
    ├── cluster-*.yaml       # 每个集群一份（shunfeng-test / xihu / sailisi / kairui...）
    └── versions.yaml        # 版本集中管理（驱动/CUDA/NCCL/本地deb路径）
```

## 核心数据流

```
cluster.yaml → ConfigLoader → ClusterConfig
                                  │
                    ┌─────────────┼──────────────┐
                    ▼             ▼              ▼
              SSHManager    BatchExecutor    GPUDeploy
              (连接池)      (批量执行)       (步骤编排)
                    │             │              │
                    └──────┬──────┘              │
                           ▼                     ▼
                      BaseStep ←──── 30+ 具体步骤类
                    (execute_on_host)
                           │
                           ▼
                    SSHConnection (paramiko)
```

> **改动影响面判断**: ConfigLoader/ClusterConfig 是只读配置源，几乎不影响；SSHManager 是共享基础设施，改动需考虑所有步骤；BaseStep 是步骤基类，改动影响所有步骤；单个 step_\* 改动仅影响自身。

## 运行模式

**核心约定：DIRECT 模式下本机就是"跳板机"**

| 模式 | 触发条件 | 跳板机 | SSH路径 |
|------|----------|--------|---------|
| PROXY | 有 jumphost | 远程跳板机 | 本机 → 跳板机 → 内部节点 |
| DIRECT | 无 jumphost | **本机即跳板机** | 本机 → 内部节点直连 |

这意味着：
- 免密配置的源密钥统一从"跳板机"获取：PROXY 从远程跳板机，DIRECT 从本机
- 所有节点共享同一份密钥对，实现节点间免密互访
- 代码中涉及"跳板机"的逻辑，DIRECT 模式下应映射到本机

> **真实拓扑提醒**: PROXY 模式下跳板机可能同时就是集群节点之一（如 shunfeng-test 集群：公网 27.190.15.191:222 即内网节点 192.168.0.20）。跳板机 SSH 到"自己这个节点"是正常路径（ssh 自身内网 IP），无需特殊处理；但排查连通性/认证问题时记住这两条路径指向同一台机器。

## 认证参数流转

认证有三层解析，依次回退，**后一层依赖前一层的输出**：

```
① SSHManager 默认值 (ssh_manager.py __init__)
   _default_username    = jumphost_config.username (PROXY) / "ubuntu" (DIRECT)
   _default_password   = jumphost_config.password
   _default_private_key = jumphost_config.private_key (本机key)
                          → 连接跳板机后被覆盖为跳板机私钥本地临时副本

② get_connection / execute_on_host 回退 (ssh_manager.py)
   if username is None    → _default_username
   if password is None    → _default_password
   if private_key is None AND password is None  → _default_private_key
   # ↑ 有密码时不覆盖 private_key，避免密钥认证抢占密码认证

③ BaseStep.execute_on_host (base.py)
   username:
     use_login_user=True  → node.username
     use_login_user=False → deploy_user
   auth:
     use_login_user 或 deploy_user==login_user → node.password + node.private_key
     否则 → private_key=None (依赖 step_0d 已配置的免密)
```

> **常见坑**: 节点配了 password 但没配 private_key → password 传入后 private_key 保持 None → 不会触发默认私钥覆盖 → 走密码认证 ✓。但如果 password 也没配 → private_key 被默认值覆盖 → 走密钥认证，可能失败。

## 步骤编排 (main.py)

```
Phase 0: 设备检查  [00]
Phase 1: 初始化    [0d→0e→0f→09→01]  ← 0d完成后才有免密，后续步骤依赖此；0f DNS在01安装依赖前配置
Phase 2: 系统检查  [02,02b,03,04]
Phase 3: 系统配置  [05,06,07,08,15,16,17,18,19]
Phase 4: 用户权限  [10,12,13]
Phase 5: GPU驱动   [20-28]
Phase 6: 高级配置  [29,30,34]
Phase 7: 验证      [99]
```

> **依赖关系**: Phase 1 的 0d 是分水岭——0d 之前用密码/本机密钥连节点，0d 之后节点间免密互访。0f DNS 必须在 01 安装依赖之前，否则 apt 等包下载可能失败。

## step_0d SSH免密流程 (step_0d_ssh_key.py)

```
_get_ssh_users 优先级: ssh_key.users > deploy_user > 报错

execute(hosts):
  0. 验证每个host有login_user
  1. _create_deploy_user_if_needed (deploy_user ≠ login_user时创建)
  2. _get_ssh_users → 需要配置免密的用户列表
  2.5. 获取源密钥对:
       PROXY模式 → _get_jumphost_keypair():
         a) 读取/生成跳板机密钥对
         b) 跳板机公钥添加到自身authorized_keys
         c) 确保私钥下载到本地（自动检测或手动下载）
         d) 更新 ssh_manager._default_private_key
       DIRECT模式 → _get_local_keypair(): 从本机~/.ssh/读取
  3. 配置密钥:
       有源密钥 → 复用源密钥对写入所有节点 (不重新生成)
       无源密钥 → 每个节点 ssh-keygen 生成
  4. 收集公钥:
       有源密钥 → 跳过 (所有节点密钥相同)
       无源密钥 → 从每个节点收集
  5. 分发公钥 → authorized_keys (临时文件→去重→正式文件)
  6. 配置 SSH 客户端 (StrictHostKeyChecking no)
  7. 配置 sshd (ClientAliveInterval 等)
```

> **源密钥方法**: `_get_jumphost_keypair()` (PROXY) 和 `_get_local_keypair()` (DIRECT) 返回统一格式 `(pubkey, private_key_path)`，后续逻辑无需区分模式。

> **关键牵连**: PROXY模式下如果跳板机没有预存密钥，`_get_jumphost_keypair()` 会生成新密钥并手动下载私钥到本地，同时更新 `ssh_manager._default_private_key`。这确保后续所有步骤连接节点时使用正确的私钥。

## step_09 hosts绑定 + 节点间免密 (step_9_hostname_hosts.py)

```
hosts条目来源:
  1. config.nodes 中所有节点的 {ip} {hostname}
  2. DIRECT 模式下添加控制机（本机）到 hosts（本机IP不在节点列表时）
  3. PROXY 模式下不添加 jumphost 到 /etc/hosts（节点通过IP连接跳板机，无需解析主机名）

每节点执行:
  1. hostnamectl set-hostname
  2. 移除 127.0.1.1 条目
  3. PROXY 模式清理旧版 jumphost 残留条目（sed 按IP/hostname 删除）
  4. 清理所有待添加条目的旧记录（支持节点改名场景）
  5. 逐条添加 hosts 条目（bash -c 'echo "..." >> /etc/hosts', sudo=True）
  6. 验证所有条目已写入

节点间互相免密 (_setup_cross_ssh):
  1. 每个节点确保部署用户有 SSH 密钥对（已有则复用，否则 ssh-keygen）
  2. 收集所有节点公钥
  3. 去重后分发到每个节点的 authorized_keys（grep -qF 精确匹配去重）
  4. 配置 SSH 客户端 StrictHostKeyChecking no
  5. 验证：每个节点 SSH 到另一个节点用主机名免密登录

is_configured 检查项:
  1. hostname 匹配
  2. /etc/hosts 包含所有节点条目
  3. PROXY 模式下 /etc/hosts 不含 jumphost 残留
  4. authorized_keys 非空 + 私钥存在 + SSH 免密抽检
```

> **牵连**: NFS/时间同步等引用跳板机hostname的场景依赖此步骤的hosts绑定。PROXY模式不添加jumphost到hosts，节点通过IP直接访问跳板机。

> **常见坑**: `is_configured()` 中的 echo 标记必须用无歧义词（如 `yes`/`no`）并精确匹配。用 `found`/`not_found` 会导致 `"found" in "not_found"` 为 True，子串匹配误判，跳过应执行的步骤。

## step_06 磁盘挂载 (step_6_disk_mount.py)

```
存储类型:
  single → _mount_single_disk: 检查设备 → 卸载现有挂载 → 条件格式化 → fstab → mount
  raid1/raid10 → _mount_raid: 完整流程如下

_mount_raid 完整流程:
  1. 检查所有设备存在
  2. _install_mdadm: 自动安装 mdadm（如未安装）
  3. 检查现有 RAID 是否匹配配置（级别+成员数）
     匹配且 format_disk=false → 直接使用
     不匹配或 format_disk=true → 重建
  4. 停止旧 RAID → 卸载成员设备挂载(_unmount_device_partitions) → 清除分区表(_wipe_devices)
  5. mdadm --create --run（立即启动不等同步）
  6. mdadm --detail --scan > /etc/mdadm/mdadm.conf（覆盖，不追加）
  7. update-initramfs -u（确保重启后RAID自动装配）
  8. 条件格式化 mkfs.ext4
  9. 清理旧 fstab 条目 → 写入新 fstab 条目（UUID）
  10. mount -a → df -h 验证

_unmount_device_partitions:
  lsblk -ln -o NAME,MOUNTPOINT → 逐分区 umount + 清理 fstab

_wipe_devices (对每个设备):
  mdadm --zero-superblock → wipefs -a → sfdisk --delete → dd bs=1M count=10 → wipefs -a → partprobe

is_configured 检查项:
  RAID模式: RAID设备存在 + 级别匹配 + 成员数匹配 + 状态正常(clean/active)
  所有模式: mountpoint -q + fstab 条目存在
```

> **常见坑**: 节点上的 nvme 设备已有分区（如 nvme0n1p1 挂载在 /home/nvme01），必须先卸载并清除分区表才能创建 RAID。`_wipe_devices` 用 dd 清零分区表头部，确保 mdadm --create 不会因残留签名失败。

> **常见坑**: `mdadm --detail --scan >> mdadm.conf`（追加）会导致重复条目，每次运行都多一份。改为 `>` 覆盖写入。

> **配置兼容**: `node_batch.storage` 和 `node_batch.storage_template` 两种写法都能被 ConfigLoader 正确解析。

## step_08 rc-local (step_8_rc_local.py)

```
执行逻辑:
  1. 创建 systemd 服务文件（仅在不存在时创建，避免覆盖）
  2. 创建 /etc/rc.local 脚本（仅在不存在时创建，已有则确保有#!/bin/bash头和755权限）
  3. systemctl daemon-reload + enable + restart（restart 使配置立即生效）
```

> **防覆盖**: rc.local 只在不存在时创建，避免清空已有自定义内容。添加 `systemctl restart` 使服务立即生效。

## step_16 内核固定 (step_16_lock_kernel.py)

```
is_configured 判断:
  mode=keep + lock_version=false → True (跳过)
  mode=keep + lock_version=true  → 检查GRUB配置
  mode=specify                   → 检查GRUB配置

execute 逻辑:
  mode=keep + lock_version=false → SKIP
  mode=keep + lock_version=true  → 执行GRUB锁定 + update-grub(受update_grub配置控制)
  mode=specify                   → 执行GRUB锁定
```

> **常见坑**: `is_configured()` 在 `mode=keep` 时不能直接返回 True，必须检查 `keep.lock_version`。否则 `lock_version=true` 的场景下步骤会被跳过，GRUB配置不会被修改。

## step_26 RDMA设备rail统一命名 (step_26_rdma_rename.py)

目标：所有节点上 rail 口（netdev IP = `10.100.<rail>.<节点号>`，rail=0..7）的 RDMA 设备统一命名为 `mlx5_0..7`，跨节点同号即同 rail，`NCCL_IB_HCA=mlx5_0,1,2,3` 这类按名选卡才有意义。

```
命名规则:
  rail N (IP 10.100.N.x)   → mlx5_N
  非 rail 的多余 RDMA 设备  → mlx5_extra_<n> (按 netdev 名排序编号, 不占用 mlx5_0..7)
  bond 设备 (mlx5_bond_*)  → 不动 (driver 自动命名)

rail 判定 (以 IP 为准, 网卡名表只做交叉校验):
  IP 10.100.<rail>.<node> 直接给出 rail —— 对所有机型成立
  名表: enp 机型 enp156/188/204/220/94/77/26/60 = rail0-7; ens 机型 ens8/7/6/5/4/3/2/1 = rail0-7
  (反例: .9 的 enp33/36/71/... 不在表内但 IP 规律成立 —— 名表当主依据会漏机型)

节点侧 /usr/local/bin/rdma-rail-rename.sh (自愈式):
  每次运行按当前 IP 重新推导 rail → 两阶段改名(先全部腾位 railtmp_/extratmp_, 再落最终名)
  → 校验 mlx5_N 的 netdev IP 必须 10.100.N.x, 不满足 exit 非零
  开机时等 rail IP 就绪(凑满8个或连续3次计数不变, 最多60s)再执行; 幂等可重复

持久化: systemd oneshot rdma-rail-rename.service (After=network-online, enabled)
  不用 udev 逐设备 rename 的原因: 开机默认枚举会循环占名(rail5 默认叫 mlx5_0,
  rail0 默认叫 mlx5_5...), udev 并行处理事件时循环换名会随机失败且结果不确定

无 rail 口的节点 (如 k8s 节点 10.100.11.11): 发现后直接跳过, 不写任何东西
is_configured: 命名对齐 + 持久化(脚本+unit)齐全 才算已配置
```

> **常见坑 1**: 改 RDMA 设备名用的是 `rdma dev set <dev> name <new>`（RDMA 子系统），和 netdev 改名（udev `SUBSYSTEM=="net"` + `NAME=`）是两个不相干的命名空间。`nic_renamer.py` 里的 `RDMARenamer` 用 `ip link set` 改 RDMA 设备名——机制错误，勿用；`step_26b_ethernet_rename.py` 未注册进 `ALL_STEPS`（死代码），且会把所有网卡（含 bond）改成 ethN，勿启用。
> **常见坑 2**: `is_configured` 只查命名结果不查持久化，会让"手工改过名但没装 unit"的节点被跳过——重启后命名即丢失。见事故档案 2026-09-12。

## step_34 NFS配置 (step_34_nfs_config.py)

```
share 流程:
  服务器端: 安装nfs-kernel-server → 创建导出目录 → 备份exports → 只追加缺失条目(不删除已有)
  客户端:   安装nfs-common → 创建挂载点 → 检查是否已挂载 → mount(失败则重试) → 写入fstab → 验证mountpoint

unshare 流程:
  客户端:   cd /root → umount(失败则umount -l) → sleep 2 → 验证卸载 → 清理fstab
  服务器端: 备份exports → sed删除相关行 → 验证清理 → exportfs -arv
```

> **防覆盖**: share模式不再"先删所有再逐个添加"，而是只追加缺失条目，避免丢失其他NFS配置。修改前备份 /etc/exports。

> **挂载验证**: 使用 `mountpoint -q` 验证挂载状态，而非简单的 `df -h`。挂载失败时带选项重试。

> **常见坑 (静默假成功)**: `nfs_server_node` 按 `nfs_server` **角色**查找，不看 `nfs.server` 字段。仅写 `nfs.server: xxx` 而节点无该角色时，`nfs_server_node` 为 None，`is_configured` 曾对"未配置NFS服务器"返回 True → 全部主机"已配置"跳过 → 部署假成功。现已两处修复: ① ConfigLoader 按 `nfs.server` 给匹配节点自动补 `nfs_server` 角色；② `is_configured` 在 `nfs_server_node` 为 None 时返回 False 并给出原因。核心原则: `is_configured` 中"配置缺失/异常"绝不能返回 True，只有"NFS未启用"这类确定无需动作的情况才返回 True。

> **常见坑（nfs.server 与角色脱节）**: `nfs_server_node` 按 `nfs_server` **角色**查找，不看 `nfs.server` 字段。只写 `nfs.server` 不给节点加角色时，`nfs_server_node` 为 None，`is_configured` 曾返回 `(True, "未配置NFS服务器")`——把配置缺失伪装成"已配置"，step_34 全部跳过却报"部署成功"。修复：config_loader 解析时若 `nfs.server` 匹配某节点则自动补 `nfs_server` 角色；`is_configured` 在找不到服务器节点时返回 False。教训：`is_configured` 对"配置缺失"类分支绝不能返回 True。

> **nfs.server 与角色映射 (关键坑)**: `nfs_server_node`/`client_nodes` 按 `nfs_server` **角色**查找，而 `nfs.server` 字段只存进 NFSConfig 不参与查找。仅写 `nfs.server: xxx` 不给节点加角色时，`nfs_server_node` 为 None，`is_configured` 曾把"未配置服务器"当作"已配置"返回 True → 3 台全部跳过 → **部署报成功但 NFS 实际什么都没做**。修复：ConfigLoader 解析时按 `nfs.server` 主机名自动补 `nfs_server` 角色；`is_configured` 遇 `nfs_server_node` 为 None 时返回 False。教训：`is_configured` 中任何"配置缺失/无法检查"的分支都不能返回 True，否则会伪装成部署成功。

> **常见坑（is_configured 静默跳过）**: `nfs_server_node` 按 `nfs_server` **角色**查找节点，与 `nfs.server` 字段无关。仅写 `nfs.server: xxx` 不给节点加角色时，`nfs_server_node` 为 None，`is_configured` 会返回 `(True, "未配置NFS服务器")`——把配置缺失当成"已配置"，所有主机被跳过且部署报成功。修复：① ConfigLoader 组装时按 `nfs.server` 主机名自动补 `nfs_server` 角色；② `is_configured` 遇 `nfs_server_node` 为 None 时返回 False，让配置缺失显式暴露而非静默跳过。

> **客户端检查只看挂载点**: share模式的客户端 `is_configured` 只检查 `mountpoint -q {client_mount}`，不校验挂载来源是否为目标NFS服务器。若挂载点已被其他NFS/本地盘占用（如手动挂了别的服务器），会被误判为已配置。测试环境避开方式：换一个不冲突的挂载路径。

> **nfs.server 必须映射到节点**: `nfs_server_node` 按 `nfs_server` **角色**查找节点，`nfs.server` 字段本身不参与查找。ConfigLoader 已做兜底：`nfs.server` 指向的节点若没有该角色会自动补上。但要生效，该节点必须出现在节点列表（node_batch/nodes）中——节点不在列表时 `nfs_server_node` 为 None，`is_configured` 会返回 False（修复前曾返回 True，导致 step 34 静默跳过还报"部署成功"）。原则：**配置缺失不能当作"已配置"**。

> **常见坑 (nfs.server 与角色脱节)**: `nfs_server_node` 按 `nfs_server` **角色**查找节点，早期版本不会根据 `nfs.server` 字段自动补角色。只写 `nfs.server` 而节点无该角色时，`nfs_server_node` 为 None，`is_configured` 对所有主机返回 `(True, "未配置NFS服务器")`——配置缺失被伪装成"已配置"，步骤整体跳过且最终报"部署成功"。已修复: ConfigLoader 会按 `nfs.server` 给匹配节点自动补 `nfs_server` 角色；`is_configured` 在找不到服务器节点时返回 False，让问题显式暴露。另注意: 客户端检查只看 `mountpoint -q {client_mount}`，不校验挂载来源是否为目标NFS服务器——若挂载点被其他NFS/本地盘占用（如同目录曾手动挂过别的服务器），会被误判为已配置。

> **nfs.server 必须映射到节点**: `nfs_server_node` 按 `nfs_server` **角色**查找，不看 `nfs.server` 字段。ConfigLoader 已在加载时按 `nfs.server` 自动给匹配节点补角色，但要求该节点在 `nodes`/`hosts_content` 列表里——列表没有它时 `nfs_server_node` 为 None。曾因 `is_configured` 在 None 时返回 True（把"未配置服务器"当"已配置"），3台机器全部静默跳过却报"部署成功"，现已改为返回 False 让配置错误显式暴露。

> **客户端检查只看挂载点**: `is_configured` 客户端分支只检查 `mountpoint -q {client_mount}`，不校验挂载来源是否为配置的NFS服务器。若挂载点被其他NFS（如手动测试环境）占用，会被误判为已配置。

> **nfs.server 必须映射到节点**: `nfs_server_node`/`client_nodes` 按 `nfs_server` **角色**查找节点，而 `nfs.server` 字段只存主机名。ConfigLoader 已在组装时自动给 `nfs.server` 指向的节点补 `nfs_server` 角色——前提是该节点必须在 nodes/node_batch 列表里，否则 `nfs_server_node` 为 None。历史上 `is_configured` 在 `nfs_server_node` 为 None 时返回 `True`（"未配置NFS服务器"），导致 3 台主机全部被误判"已配置"而静默跳过，最终报"部署成功"。现已改为返回 `False`，缺失服务器节点会显式暴露而不是伪装成已配置。

> **常见坑 (2026-08 修复)**: `nfs_server_node` 按 **角色** `nfs_server` 查找服务器节点，配置里的 `nfs.server` 字段原本不参与匹配。仅写 `nfs.server: xxx` 而不给节点加角色时，`nfs_server_node` 返回 None，`is_configured` 会把"未配置NFS服务器"当作"已配置"返回 True，step_34 整体静默跳过且最终报"部署成功"。修复：① config_loader 解析完节点后按 `nfs.server` 自动给匹配节点补 `nfs_server` 角色；② `is_configured` 找不到服务器节点时返回 False，让配置缺失显式暴露。另注意：客户端检查只验证 `mountpoint -q`，若客户端挂载点已被其他NFS(如手动测试环境)占用，会误判为已配置——测试时用不同挂载点(如 /share1)规避。

> **常见坑**: `nfs_server_node` 按 `nfs_server` **角色**查找，而配置里的 `nfs.server` 字段只是个字符串。若节点没有 `nfs_server` 角色（如 node_batch 场景忘了写 nodes_override），`nfs_server_node` 返回 None，`is_configured` 会把"未配置NFS服务器"当作"已配置"返回 True，step_34 静默跳过且部署报成功。修复：config_loader 组装 ClusterConfig 前按 `nfs.server` 自动补角色；`is_configured` 在无服务器节点时返回 False 暴露配置错误。另外客户端检查只看 `mountpoint -q {client_mount}`，不校验挂载来源——若挂载点是本地盘或其他服务器的NFS，也会被误判为已配置。

> **常见坑（nfs.server 必须能映射到节点）**: `nfs_server_node` 按 `nfs_server` **角色**查找节点，而配置里只写 `nfs.server: xxx` 不会自动建立映射。ConfigLoader 已修复：构建节点后按 `nfs.server` 主机名自动补 `nfs_server` 角色。但前提是该节点必须在 `node_batch` 节点列表中——服务器节点不在列表时 `nfs_server_node` 仍为 None。同时 `is_configured()` 在服务器节点缺失时返回 `False`（原来返回 True，会把配置缺失伪装成"已配置"，导致 step 34 静默跳过、部署却报成功）。

> **客户端 is_configured 只查挂载点**: 客户端侧 `is_configured` 仅检查 `mountpoint -q {client_mount}`，不校验挂载来源是否为配置的 NFS 服务器。若挂载点被其他 NFS（如手动搭建的测试环境）占用，会被误判为已配置并跳过。测试时用不同的挂载路径（如 /share1）避开。

> **nfs.server与角色映射**: `nfs_server_node`/`client_nodes` 按 `nfs_server` **角色**查找，不看 `nfs.server` 字段。ConfigLoader 已修复为：`nfs.server` 指向的节点若无该角色则自动补上。此前只写 `nfs.server` 不加角色时，`is_configured` 会把"未配置NFS服务器"当作"已配置"返回 True，3 台全部跳过且报部署成功——配置缺失绝不能映射为"已配置"。

## step_10 创建用户 (step_10_create_user.py)

```
创建ubuntu用户: uid=1000 gid=1000 (Ubuntu默认第一个用户)
  groupadd -g 1000 → useradd -u 1000 -g 1000 -m -s /bin/bash → sudoers.d → .ssh目录
  默认不创建，需配置 create_users: true
```

> **uid/gid 1000**: Ubuntu系统默认第一个用户的uid/gid是1000，保持一致避免权限混乱。

## step_22/23/24 GPU驱动 + CUDA安装

### step_23 fabricmanager (step_23_fabricmanager.py)

```
安装优先级:
  方法0: fabricmanager_local_file 配置且文件存在 → put_file上传 → dpkg -i
  方法1: NVIDIA官方仓库 smart_download (多个Ubuntu版本URL回退) → dpkg -i
  方法2: apt安装 (cuda-keyring + apt-get install fabricmanager-*)

NVLink检测: nvidia-smi nvlink --status | grep GPU, 无NVLink的节点跳过
版本对齐: fabricmanager分支必须与nvidia驱动主版本一致 (590驱动配590 fabricmanager)
```

> **本地deb优先**: `fabricmanager_local_file` 配置在 `versions.yaml` 的 `nvidia_driver` 下,留空走在线下载。路径解析规则同 `local_file` (相对路径基于项目根目录)。在线下载失败时,本地deb是唯一可靠兜底。

> **版本错配风险**: fabricmanager与驱动不同分支时服务能起来、8卡也能被访问,但NVLink拓扑可能降级或日志告警,长期不稳定。装前确认 deb 版本与 `nvidia_driver.version` 主版本号一致。

> **dpkg -i不解析依赖**: `dpkg -i` 只装包本身,缺依赖时报错并留包于未配置状态,需 `apt-get install -f -y` 补。step_23 已将两步合并为 `dpkg -i ... || apt-get install -f -y`。

### step_24 CUDA Toolkit (step_24_cuda_toolkit.py)

```
安装流程:
  1. _detect_cuda_batch: nvcc -V / version.txt / /usr/local/cuda-* 三法检测
  2. 主版本匹配 → 跳过; 主版本不匹配 → 卸载重装; 无CUDA → 直接安装
  3. _uninstall_cuda_batch: cuda-uninstaller + 残留文件清理 + 环境变量清理
  4. _prepare_package: 本地/local_file/download_url 三选一准备安装包
  5. _install_cuda_batch: .run --toolkit --no-drm --silent → 软链/usr/local/cuda → /etc/profile环境变量 → nvcc -V验证

is_configured: mode=keep直接True; 否则按nvcc版本与目标版本主版本号比对
```

> **卸载不再用 apt purge (关键)**: 原 `_uninstall_cuda_batch` 含 `apt-get purge 'cuda*' 'libcuda*' 'nvidia-cuda*'`,已删除。原因: `'libcuda*'` 会误伤驱动的 `libcuda1` 用户态库 (nvidia-smi/fabricmanager/container toolkit 全依赖它),purge后驱动用户态断裂。toolkit通过 `cuda-uninstaller` + 残留文件清理即可干净卸载。`nvidia-fabricmanager` 包名不含cuda,本就不受这三个通配符影响。

> **安装前不再 apt 装依赖**: 原 `_install_deps_batch` (apt-get install build-essential libglu1-mesa ...) 已删除。CUDA `.run` 安装包 `--toolkit --silent` 自带所需依赖,无需预先apt安装。

> **.run安装的驱动不受dpkg管理**: `.run` 包安装的 `libcuda.so.1` 直接放在 `/usr/lib/x86_64-linux-gnu/` 下,不走dpkg,故 `dpkg -l | grep libcuda` 空输出是正常现象 (非被purge),用 `ls libcuda.so*` + `ldconfig -p` 验证才准确。

### step_44 GPU Burn压测 (step_44_gpuburn.py)

```
执行流程:
  1. _get_compile_hosts 按编译策略选编译节点 (single_node/role_based/local)
     —— 编译节点选择逻辑已统一到 BaseStep._get_compile_hosts，
        步骤 40/41/44/45 共用一份实现（2026-09-11 重构，四份拷贝合一）；
        step_44 额外支持 gpuburn_compile_strategy 覆盖全局值
  2. 编译节点: 获取compute_cap(nvidia-smi) + cuda_version(nvcc) → 强制重编
  3. _upload_and_build_gpuburn: 上传zip → 解压 → 恢复Makefile_bk → sed改COMPUTE/CUDA_VERSION → make
  4. 所有GPU节点并行 _run_test_on_host: gpu_burn -tc {duration} (Tensor Core压测)

nvcc自动检测: 优先 /usr/local/cuda/bin/nvcc, 回退 PATH 中的 nvcc
  (CUDA装在/usr/local/cuda但不在PATH时, nvcc命令不可用, 必须显式走绝对路径)
```

> **gpuburn_compile_strategy** (versions.yaml test_packages 段): GPU Burn 专属编译策略，覆盖全局 compile_strategy，仅 step_44 生效；留空跟随全局。典型用法：全局 role_based（NCCL 多节点测试按角色编译）+ gpuburn_compile_strategy: single_node（GPU Burn 只在第一台编，toolkit_dir 在 NFS 上全节点共享二进制）。注意 role_based 选的是**所有**带角色的节点而非第一台——"只编一次"的错觉来自 NFS 共享 + 各 build 函数的"已存在则跳过"检查。

> **skip_if_configured=False**: 压测步骤强制运行,不因 `gpu_burn` 二进制存在就跳过。否则toolkit版本变化后仍复用旧二进制,PTX不兼容。

> **强制重编**: 每次都 `_upload_and_build_gpuburn`,先 `make clean` 再 `make`。确保 `compare.ptx` 用当前toolkit重新生成,避免旧toolkit编出的PTX在新环境报 `unsupported toolchain`。

> **Makefile不修改CUDAPATH**: gpu-burn Makefile内置自动检测 (`/usr/bin/nvcc`→`/usr`,否则`/usr/local/cuda`)。原 `sed 's|CUDAPATH ?= /usr|...|/usr/local/cuda|'` 有缺陷: `CUDAPATH ?= /usr` 是 `CUDAPATH ?= /usr/local/cuda` 的子串,替换第二分支行会得到 `/usr/local/cuda/local/cuda` 双重路径。已删除该sed,仅改COMPUTE和CUDA_VERSION。

> **Makefile幂等**: 编译前从 `Makefile_bk` 恢复干净Makefile (备份存在则恢复,否则首次备份),避免重复执行复用被污染的Makefile。

> **PTX toolchain不兼容**: `cuModuleLoad` 报 `PTX was compiled with an unsupported toolchain` = 编译compare.ptx的nvcc工具链版本高于驱动能JIT的PTX ISA。根因是toolkit版本高于driver (如toolkit 13.1 + driver 580)。解决: 降toolkit到与driver匹配 (如13.0),强制重编重新生成PTX。

## BaseStep 生命周期 (base.py)

```
run() → pre_check → check_all_configured → execute → post_check
         (可跳过)    (skip_if_configured)   (可重试)   (验证)
```

> **skip_if_configured 机制**: `is_configured()` 返回 True 的节点会被跳过，不再执行。新步骤必须实现 `is_configured()` 才能受益。

## 关键数据模型 (models/cluster.py)

| 模型 | 用途 |
|------|------|
| ClusterConfig | 顶层配置，聚合所有子配置 |
| JumphostConfig | 跳板机: host/port/auth/node_auth |
| NodeConfig | 节点: hostname/ip/username/password/roles/storage |
| SSHKeyConfig | 免密: enabled/users/private_key/public_key |
| TimeSyncConfig | 时间同步+DNS: server/timezone/dns_servers |
| DeploymentConfig | 部署: parallel/max_workers/timeout/retry |

> **SSHKeyConfig.private_key / public_key 字段已定义但未使用**——当前源密钥由运行时从跳板机/本机获取，不来自配置文件。

## 事故档案

### 2026-08-21 NFS "部署成功"但实际未配置（step_34）

现象：run.sh 输出 `[34] 3 台主机已配置，跳过` + `部署成功`，但登录节点检查发现 nfs-server 未安装、/etc/exports 为空、挂载点不存在。

因果链：
1. 配置只写了 `nfs.server: instance-jmr2u7tl`，没有任何节点带 `nfs_server` 角色
2. `ClusterConfig.nfs_server_node` 只按角色查找 → None
3. `step_34.is_configured` 对"服务器节点为 None"返回 `(True, "未配置NFS服务器")`——把配置缺失当作"无需配置"
4. BaseStep 的 skip_if_configured 机制把 True 固化解释为"目标已达成" → 步骤整体跳过 → 编排器判定成功

超越本 bug 的教训：
- **skip 机制会放大误报**：`is_configured` 返回 True 后没有任何二次验证，中间层任何"善意的默认值"都会变成静默假成功
- **不被消费的显式配置字段最危险**：`nfs.server` 看起来正确，排查者会本能跳过它去别处找问题。新配置字段要么被消费、要么加载时报错，不能沉默忽略
- **验证部署要用独立通道**：部署工具的"成功"只代表它的检查逻辑通过了；确认真实生效必须直接登录节点查 systemctl / mount / 文件内容

修复：① config_loader 按 `nfs.server` 给匹配节点补 `nfs_server` 角色；② `is_configured` 在服务器节点缺失时返回 False 并说明原因。

### 2026-09-07 GPU Burn 上传 Permission denied（step_44，h800-test9.7 集群）

现象：`put_file` 上传 gpu-burn 源码到 100.126.2.41 失败，stderr 为 `root@100.126.2.41: Permission denied (publickey,password)`；但同一节点上的命令执行（nvidia-smi、make 等）全部正常。31（跳板机自身）上传正常，只有走中转的目标节点失败。

因果链：
1. 该集群节点用密码认证（nodes[].password），且没跑过免密分发（step 08/ssh_key），跳板机→节点无密钥信任
2. `SSHManager.copy_file_to_host` 对"非跳板机目标"的实现是：SFTP 传到跳板机 → 在跳板机上执行**原生 `scp`** 推向目标节点
3. 跳板机上的 scp 只能用跳板机自己的密钥（无密码可填），节点不认 → 三次密码提示后拒绝
4. 命令执行路径没有此问题：`get_connection` 走 paramiko `direct-tcpip` 隧道 + 节点密码认证，所以"命令能通、上传不通"

超越本 bug 的教训：
- **同一节点的两条通道可以认证方式不同**：命令走隧道（paramiko + 节点密码），上传走跳板机中转（原生 scp + 跳板机密钥）。排查"一半功能正常"的问题时，先确认两条路径的认证链是否真的一致，不要因为命令能通就排除认证问题
- **文件传输应复用命令执行的连接**：连接池里已有认证成功的隧道连接，`conn.put_file`（paramiko SFTP over 同一 channel）天然继承同一套认证，没必要另起一条依赖外部免密状态的路径
- **看代码注释判断状态是危险的**：原代码注释写着"免密配置完成后，直接使用 scp 即可"——这是在"已跑过免密分发"的前提下写的，但调用方从未保证该前提。隐式前提必须在使用处校验，或干脆设计成不需要前提

修复：① `base.py put_file` 补传节点密码（`_get_login_password`），与 `execute_on_host` 的认证取值对齐；② `copy_file_to_host` 优先走隧道连接的 `conn.put_file`，跳板机 scp 中转降级为回退路径（免密已配置的集群仍可用）。重跑 step_44：41 上传成功，两节点 16 卡 GPU Burn 全部 OK。

### 2026-09-11 step 22 卸载秒退 + .deb 当驱动执行（xihu-h800 集群，10.100.9.1）

现象：step 22 批量卸载旧驱动，pdsh 行 0.13 秒内 `exit_code=-1`、无任何 stderr，随后日志却打印"NVIDIA驱动卸载完成"；继续安装时报 `/tmp/nvidia-fabricmanager_590.48.01-2ubuntu1_amd64.deb: line 1: syntax error near unexpected token` `!<arch>`（ar 归档魔数被 bash 解析）。用户反馈：同样的卸载脚本在节点上手动执行完全正常。

因果链（两个独立 bug 在同一次运行里叠加）：
1. **pkill 自杀**：卸载脚本第一行 `pkill -9 -f nvidia-persistenced`。通过 SSH exec 执行时，脚本文本就是 bash 进程自己的命令行（`bash -c "<整个脚本>"`），`-f` 按完整命令行匹配，脚本文本里天然含有 `nvidia-persistenced` 字样 → bash 把自己 SIGKILL。通道无退出码关闭，paramiko 抛异常 → exit_code=-1、stdout/stderr 全空。手动在节点上跑没事，是因为交互式 shell 里这段文本不在任何进程的命令行里（每行单独执行）
2. **空输出误判成功**：`_uninstall_driver_batch` 的判定是 `"UNINSTALL_DONE" in stdout or "nvidia" not in stdout.lower()`——stdout 为空时后者为 True，把"脚本被杀、什么都没跑"判成"卸载完成"，节点带着旧驱动进入了安装阶段
3. **包配置错填**：`versions.yaml` 的 `nvidia_driver.local_file` 写成了 `nvidia-fabricmanager_590.48.01-2ubuntu1_amd64.deb`（与相邻的 `fabricmanager_local_file` 同值，典型的复制粘贴错位）。包管理器按文件名原样分发，安装命令 `chmod +x xxx.deb && xxx.deb -s --dkms` 把 deb 归档当 shell 脚本执行，`!<arch>` 是 ar 归档的魔数

超越本 bug 的教训：
- **`pkill -f` 在 SSH 通道里默认是自杀指令**：脚本文本就是 `bash -c` 的完整命令行，`-f` 按命令行匹配，脚本里**任何位置**出现过目标关键字（哪怕只是 `systemctl stop nvidia-fabricmanager` 这样的正常命令行）都会命中执行脚本的 bash 自身。修复不能用 `[n]xxx` 方括号技巧——它只能防止模式匹配到模式自身，防不了脚本其他行的同词（第一次修复就栽在这里：改完仍秒退，因为 systemctl 行里有完整关键字）。正确写法是按 PID 杀并跳过自身：`for pid in $(pgrep -f xxx); do [ "$pid" != "$$" ] && kill -9 "$pid"; done`，已在节点上复现验证
- **"结果为空"和"结果正确"必须区分**：验证脚本的判定逻辑要写成肯定式（必须看到 `UNINSTALL_DONE`），否定式（"没看到 nvidia 字样"）在脚本压根没跑完时同样为真。这和 is_configured 误报 True 是同一类病：异常路径的输出恰好落在成功判定的盲区里
- **"空列表继续走"的分支要区分成因**：`hosts_to_install` 为空既可能是"全都版本匹配"（成功）也可能是"卸载全失败被剔除"（失败），按同一分支返回 SUCCESS 会把失败洗白。同理 `所有节点都已安装正确版本` 这类 message 必须与实际成因核对
- **配置文件里语义相近的相邻字段是高危区**：`local_file` 和 `fabricmanager_local_file` 值相同纯属笔误，但没有任何机制发现"驱动安装包是 deb"这一矛盾。文件类型校验（驱动包应为 `.run`）应在 `_prepare_package` 入口拦截

修复：① step_22 卸载脚本的 pkill 改为 pgrep+PID 排除 `$$`；② 内核模块卸载改为 `rmmod`（`modprobe -r` 在模块文件已被清理、模块仍驻留内核时必然失效——本例中 610 驱动的模块文件已被用户手动清理，但模块仍在内存中，`modprobe -r` 报 not found 后被 `2>/dev/null || true` 静默吞掉，lsmod 一直不干净）；③ 卸载成功判定改为 `result.success and "UNINSTALL_DONE" in result.stdout`；④ `hosts_to_install` 为空时若存在卸载失败节点则返回 FAILED；⑤ versions.yaml 的 nvidia_driver.local_file 改回 `NVIDIA-Linux-x86_64-590.48.01.run`。

### 2026-09-11 step 06 format_disk=false 仍清盘 + mdadm create 报 Device or resource busy（xihu-h800 集群，10.100.9.1）

现象：配置 `storage_template.format_disk: false`，运行 step 06。日志先对 4 块 nvme 逐块执行了 zero-superblock / wipefs / sfdisk --delete / dd 清零头部 10MB（nvme0n1 上原有 LVM 卷 workdirvg-workdirlv 的 PV 头被抹掉），随后 `mdadm --create /dev/md0 --level=10` 失败：`mdadm: cannot open /dev/nvme0n1: Device or resource busy`，exit_code=2。最终"成功: 0/1"部署失败。

因果链（两个 bug 叠加，前者破坏数据、后者让流程失败）：
1. **format_disk 守卫放错了分支**：`_mount_raid` 只在"RAID 已存在且配置正确"时才检查 `not format_disk`（直接复用）；RAID 不存在时落入 else 分支**无条件执行**停旧RAID→卸载→wipe→dd 清盘，format_disk=false 形同虚设。要到第 10 步 mkfs/校验阶段才再看 format_disk——那时盘已经被清空了，"拒绝挂载"为时已晚。单盘路径 `_mount_single_disk` 早有"未格式化且 format_disk=false → 拒绝"的守卫，RAID 路径漏了
2. **清盘流程不认得 LVM**：`_unmount_device_partitions` 只处理文件系统挂载（umount + 清 fstab）。nvme0n1 上是 LVM 逻辑卷（dm 设备 workdirvg-workdirlv），无挂载点，umount 无从下手；内核 dm 层仍持有该盘 → mdadm --create 报 busy。更麻烦的是步骤 1 的 wipefs 已把 PV 头抹掉，`pvs`/`vgchange -an workdirvg` 全部 "not found"，规范释放路径失效，只能 `dmsetup remove workdirvg-workdirlv` 兜底（已在节点上验证有效）

超越本 bug 的教训：
- **破坏性开关的守卫必须在破坏动作之前**，而不是流程后段的"格式化开关"。凡是"先清场后施工"的流程，把守卫放在清场入口处检查一次；放在施工阶段等于允许"先毁掉再反悔"
- **同一开关在所有代码路径上语义一致**：format_disk=false 在单盘路径=拒绝破坏，在 RAID 路径却=照样清盘只是不 mkfs。用户对开关的理解只有一份，任何一条路径单独缩小语义都是事故。新加守卫后两条路径要对照测试
- **"设备占用"要分层排查**：umount 只管文件系统层，LVM(dm) / 多路径 / loop / 持有 fd 的进程都持有设备。lsblk 的 TYPE 列（lvm/mpath/loop）就是占用来源清单；mdadm 报 busy 而 lsblk 无 MOUNTPOINT 时，先看 dm
- **元数据被清后，规范工具会"失明"**：PV 头被 wipefs 抹掉后 pvs/vgs/vgchange 都看不见该 VG，但内核 dm 设备还在。清理工具链要带兜底路径（dmsetup remove -f），不能假设规范命令一定能看到要清理的对象

修复：① `_mount_raid` 重建分支入口加 format_disk 守卫：RAID 不存在/不匹配且 format_disk=false 时直接拒绝，报错信息说明"重建会清空全部成员设备数据"；② 新增 `_release_lvm_on_device`：lsblk 找 lvm 类型 dm 子设备 → 卸载其挂载并清 fstab → `vgchange -an <vg>`（PV 元数据完好时）→ 复查残留后 `dmsetup remove -f` 兜底（PV 头已丢失时），在 wipe 之前对每块成员盘调用；③ 回写陷阱索引 2 行。

续（同日，新节点 10.100.9.3，LVM 自动激活竞态）：上述修复部署后对 .3/.7/.8 重跑 step 06（format_disk=true）。.7/.8 成功；.3 失败——释放逻辑当时确实生效了（日志中 lsblk 已无 dm 子设备），但 `mdadm --create` 仍报 `super1.x cannot open /dev/nvme4n1: Device or resource busy`。事后检查：分区 p1/p2 和两个 dm 设备（nfsvg-nfslv、workdirvg-workdirlv）全部"复活"。

根因是释放与清盘之间的**竞态**：`_wipe_devices` 原来只对盘本身 `wipefs -a`、`dd` 只清盘头 10MB——nvme4n1p2（workdirvg 的 PV，位于 4.9T 偏移处）的 LVM2_member 签名没有被清掉。清盘过程中 wipefs/dd/sfdisk 的 udev 事件触发 LVM 自动激活（`pvscan --cache -aay`），扫到 p2 上完好的 PV 签名 → workdirvg 被重新拉起 → dm 占住磁盘 → 分区在内核里删不掉 → mdadm 独占打开失败。验证方式：手动释放后 `wipefs -a /dev/nvme4n1*`（输出显示 p2 偏移 0x218 处的 LVM2_member 签名被擦除）→ `partx -d` → 裸盘 → mdadm --create 成功。

超越本 bug 的教训：
- **清除"签名"要全覆盖，清除"状态"要防复活**：释放 dm 是清状态，但状态可以随事件被重建，重建的燃料是磁盘上的签名。只清盘头（dd 10MB）对深处分区的 PV 头无效；wipe 必须枚举全部子设备（`wipefs -a 盘*`）
- **udev 是隐形输入**：块设备上的每个写操作都会触发 udev 事件，事件处理器（LVM 自动激活、multipath、mdadm 增量装配）会在你不知道的时刻改状态。"释放→操作"之间任何时刻都可能被第三方重新占用，破坏性操作前必须重新验证（verify-before-act），重试循环直到收敛
- **partprobe 不是删除分区的工具**：它只重新读取分区表，对仍被占用的分区静默无效；强制内核丢弃分区表项要用 `partx -d`

修复（续）：④ `_wipe_devices` 在 zero-superblock 之后增加 `wipefs -a {dev}*`（覆盖全部分区+盘本身的 PV/fs/GPT 签名），sfdisk --delete 之后增加 `partx -d`；⑤ 新增 `_ensure_device_released(host, device)`：以 `lsblk -ln` 检查设备无任何子设备，发现残留（含 swap 分区）则重跑 释放+清签名+partx -d，最多 3 次重试收敛，仍失败则拒绝 mdadm create；在 `_mount_raid` 创建 RAID 前对每块成员盘调用。.3 已按同序列手动修复（RAID10 4/4 UUUU、14T ext4 挂载 /ssd、fstab/initramfs 已配）。

### 2026-09-12 step 26 重写：RDMA rail 统一命名缺持久化 + 校验永假（xihu-h800 集群，10.100.9.3/.7/.8）

背景：12 台节点分 3 种机型（ens / enp / enp 异类 .9），开机默认枚举跨机型不一致——同号不同 rail（.1 的 mlx5_0=rail5、.3 的 mlx5_0=rail6、.9 的 mlx5_0=rail0），旧版 step 26 按"当前序号+速率"排序改名，语义上无法达成"同号即同 rail"；且 `rdma dev set` 只写运行时、无任何持久化（全集群无 udev 规则/unit/cron），旧版 `execute()` 无条件 `success=True`、脚本 `|| true` 吞错、`is_configured` 见到任何 `mlx5_N` 即认为已配置。集群上还有前人手工改名的半成品残留（.4/.5/.6 的 `mlx5_orig5_x`、.11/.12 的 `mlx5_tmp2`）。

症状（重写过程中自己踩到，测试期拦下）：
1. .7 首次真实执行：改名全部成功，校验却 8 个 `RAIL_FAIL netdev= ip=` 全空——校验 awk 用 `$2==l` 与 `"mlx5_0/"` 全等比较，而 `rdma link show` 的 `$2` 实际是 `mlx5_0/1`（带端口后缀），永假。改 `$2 ~ "^mlx5_$rail/"` 后全 RAIL_OK。
2. CLI 首跑 .3/.8 装齐了脚本+unit，.7 却什么都没装——.7 此前被手工测试改过名，`is_configured` 只查命名结果即返回 True，框架 `skip_if_configured` 跳过该节点，持久化缺失被掩盖（重启即丢名）。修复：`_verify_host` 增加 `test -x 脚本 && systemctl is-enabled unit` 双条件，命名+持久化齐全才算已配置。

超越本 bug 的教训：
- **运行态改名类状态，"当前正确"≠"已配置"**：没有持续性保障（unit/脚本）的正确结果，重启后归零。幂等检查必须把"结果"和"达成结果的手段"都纳入目标状态
- **持久化机制选型要看竞态**：udev 逐设备 rename（`SUBSYSTEM=="rdma", ATTR{rename}=`）规则本身持久，但开机默认枚举循环占名（rail5 默认叫 mlx5_0 而 rail0 默认叫 mlx5_5），udev 并行处理事件时循环换名随机失败；systemd oneshot 等设备/IP 齐了再两阶段（全腾位→落位）是确定性的
- **自愈优于快照**：节点脚本每次运行按 IP（`10.100.<rail>.<node>` 规划）重新推导 rail，而非沿用部署时写死的映射——重启后枚举变化、换卡、新机型都不会破坏收敛；IP 是比网卡名表更普适的锚点（.9 的 enp 命名不在任何名表内）
- **k8s 节点安全边界**：无 rail 口的节点（如 10.100.11.11，cilium/bond0 环境）发现后直接跳过、零写入；RDMA 设备名与 netdev 名是两个命名空间，改前者不碰后者，不影响 k8s 数据面

修复：step 26 整体重写（发现程序收集 dev/netdev/IP/PCI → IP 推导 rail + 名表交叉校验 → 自愈脚本 + systemd oneshot 持久化 → RAIL_OK/FAIL 强校验）；.3/.7/.8 已执行验证（mlx5_0..7 ↔ rail0..7 一一对应、unit enabled），.11（k8s 节点）安全跳过。

## 修改原则

1. **防覆盖**: 修改配置文件时，先检查已存在的内容，只追加/修改必要的部分，不做全量覆盖
2. **先备份**: 修改关键系统文件（/etc/exports, /etc/fstab等）前先备份
3. **验证闭环**: 每个操作后验证结果（mountpoint验证挂载、grep验证清理等），不做"发射后不管"
4. **mode与子选项联动**: `is_configured()` 不能只看mode，必须检查子选项（如 keep.lock_version）
5. **源密钥一致性**: SSH免密的源密钥必须从跳板机生成并分发到所有节点，所有节点共享同一密钥对
6. **is_configured 精确匹配**: echo 标记用无歧义词（`yes`/`no`），用 `==` 精确匹配，禁止子串匹配（`"found" in "not_found"` 是 True！）
7. **配置字段兼容**: ConfigLoader 解析 `node_batch` 的 `storage` 和 `storage_template` 两种写法，`auth` 和 `auth_template` 同理
8. **apt purge 通配符风险**: 批量 `apt-get purge 'libcuda*'` 会误伤驱动的 `libcuda1` 用户态库,破坏 nvidia-smi 等依赖它的组件。`.run` 安装的包不走 dpkg,apt purge 对它无效但会误伤 apt 装的同名包。卸载 toolkit 用官方 `cuda-uninstaller`,不要用 apt 通配 purge
9. **sed 子串陷阱**: `sed 's|CUDAPATH ?= /usr|...|'` 中 `/usr` 是 `/usr/local/cuda` 的前缀子串,会误匹配后者的前半段。做 sed 替换前先确认目标串不是其他串的子串,或改用更精确的匹配锚定
10. **is_configured 的 True 语义必须唯一**: True 只表示"目标状态已达成"或"明确无需动作"（如功能未启用）。"找不到服务器""检查异常""无法判断"一律返回 False——让步骤走执行路径，把问题以 WARNING/SKIPPED 形式暴露在日志里，而不是静默吞掉（来源：2026-08-21 NFS 事故）
11. **新配置字段必须有消费方**: ConfigLoader 解析了但不被任何运行时逻辑使用的字段（如曾经的 `nfs.server`、`SSHKeyConfig.private_key/public_key`），要么补上消费逻辑、要么删掉。留着它等于给未来的配置错误埋雷
12. **上传与命令同通道**: `put_file`/文件传输必须复用命令执行的隧道连接和认证（`conn.put_file`），不得依赖"跳板机上原生 scp"这类需要额外前提（免密分发）的旁路；调用方传认证参数时密码/密钥/用户名要与 `execute_on_host` 完全对齐（来源：2026-09-07 上传事故）
13. **SSH 通道内 pkill -f 必须防自杀**: 远程执行的多行脚本中，`pkill -f <模式>` 的模式串若出现在脚本文本里（bash -c 的命令行=脚本文本），会把执行脚本的 bash 自己杀掉，表现为 exit_code=-1、stdout/stderr 全空的秒退。一律写 `[x]模式` 方括号形式；脚本结尾的验证标记用肯定式判定（必须看到标记），禁止"没看到 X 就算成功"（来源：2026-09-11 step 22 事故）
14. **破坏性开关的守卫必须在破坏动作之前且覆盖全部路径**: wipefs/dd/mkfs/mdadm create 这类不可逆操作的开关（如 format_disk=false）必须在进入清场流程前拦截，且单盘/RAID 等所有代码路径语义一致；"设备不干净"时先分层释放占用（挂载→LVM/dm→兜底强制移除）再清盘（来源：2026-09-11 step 06 事故）
15. **"已配置"必须包含持续性保障**: 对依赖重启后重建的配置（RDMA 改名、开机自愈脚本、systemd unit），`is_configured` 只查当前结果不算完成——脚本/unit 的存在性属于目标状态的一部分，否则"手工/部分达成结果"的节点会被幂等跳过，重启后状态丢失（来源：2026-09-12 step 26 事故）
16. **运行态改名必须有自愈来源**: 改名/改号类操作（RDMA 设备、网络接口）不要硬编码"当次发现的映射"，持久化脚本每次运行时按稳定锚点（如 IP 规划）重新推导目标——重启后枚举顺序变化、换卡、机型差异都不会破坏收敛；校验用正则前缀匹配而非与带后缀的实际值全等（`$2` 是 `mlx5_0/1`，与 `mlx5_0/` 永不相等）（来源：2026-09-12 step 26 事故）
