# GPU Cluster Deploy 代码架构

## 目录结构

```
gpu-cluster-deploy/
├── src/
│   ├── main.py              # 入口 + GPUDeploy 编排器
│   ├── config_loader.py     # YAML → ClusterConfig 解析
│   ├── ssh_manager.py       # SSH连接池 + 跳板机管理
│   ├── batch_executor.py    # 批量执行器 (SSH/pdsh)
│   ├── package_manager.py   # apt/yum 包管理
│   ├── models/
│   │   ├── cluster.py       # 数据模型: ClusterConfig, JumphostConfig, NodeConfig, SSHKeyConfig...
│   │   └── node.py          # NodeInfo, ClusterInfo (运行时状态)
│   ├── steps/
│   │   ├── base.py          # BaseStep 基类
│   │   └── step_*.py        # 30+ 部署步骤
│   ├── network/             # 网络检测/测试 + IPResolver
│   └── utils/               # 日志等
└── config/
    └── cluster.yaml
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

## step_10 创建用户 (step_10_create_user.py)

```
创建ubuntu用户: uid=1000 gid=1000 (Ubuntu默认第一个用户)
  groupadd -g 1000 → useradd -u 1000 -g 1000 -m -s /bin/bash → sudoers.d → .ssh目录
  默认不创建，需配置 create_users: true
```

> **uid/gid 1000**: Ubuntu系统默认第一个用户的uid/gid是1000，保持一致避免权限混乱。

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

## 修改原则

1. **防覆盖**: 修改配置文件时，先检查已存在的内容，只追加/修改必要的部分，不做全量覆盖
2. **先备份**: 修改关键系统文件（/etc/exports, /etc/fstab等）前先备份
3. **验证闭环**: 每个操作后验证结果（mountpoint验证挂载、grep验证清理等），不做"发射后不管"
4. **mode与子选项联动**: `is_configured()` 不能只看mode，必须检查子选项（如 keep.lock_version）
5. **源密钥一致性**: SSH免密的源密钥必须从跳板机生成并分发到所有节点，所有节点共享同一密钥对
6. **is_configured 精确匹配**: echo 标记用无歧义词（`yes`/`no`），用 `==` 精确匹配，禁止子串匹配（`"found" in "not_found"` 是 True！）
7. **配置字段兼容**: ConfigLoader 解析 `node_batch` 的 `storage` 和 `storage_template` 两种写法，`auth` 和 `auth_template` 同理
