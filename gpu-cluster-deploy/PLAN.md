# GPU Cluster Deploy 修复计划

## 问题0: SSH密钥逻辑 — 跳板机生成并分发

### 现状分析
当前 `step_0d_ssh_key.py` 的逻辑：
- PROXY模式：从跳板机获取已有公钥(`cat ~/.ssh/id_rsa.pub`)，如果不存在则`ssh-keygen`生成
- 但**私钥分发**是通过 `ssh_manager._detect_jumphost_key_for_nodes()` 下载到本地临时文件，再base64编码上传到各节点
- 问题是：当跳板机**没有**预存密钥时，`_get_jumphost_keypair()` 能生成，但 `private_key_path` 依赖 `ssh_manager._jumphost_key_temp_dir` 和 `_default_private_key`，这两个字段在跳板机上生成新密钥后**不会自动更新**

### 对比 conf-git shell脚本
`base_step1_copyId.sh` 的正确逻辑：
1. 在跳板机（本机）上 `ssh-keygen` 生成密钥对
2. 将 `~/.ssh/id_rsa`, `~/.ssh/id_rsa.pub`, `~/.ssh/authorized_keys` **整体scp同步**到所有其他节点
3. 所有节点共享同一份密钥文件

### 修复方案
在 `_get_jumphost_keypair()` 中：
1. 当跳板机没有密钥时，生成后**重新下载**私钥到本地临时目录
2. 确保生成的新密钥路径更新到 `ssh_manager._default_private_key`
3. 在跳板机上也将公钥添加到自己的 `authorized_keys`（当前缺失）
4. 确保 `use_source_key=True` 路径被优先使用，让所有节点拿到同一份密钥

**修改文件**: `step_0d_ssh_key.py`

---

## 问题1: NFS unshare bug + 挂载/取消挂载验证

### 现状分析
`_execute_unshare()` 的bug：
1. **unshare遍历的是hosts列表**（所有节点），但跳板机不在hosts中，所以计算节点的umount是通过部署工具直接执行的
2. 参考shell脚本，unshare在**服务器端**通过SSH到每个计算节点执行umount（避免cwd在NFS挂载目录内导致device busy）。Python版本用 `cd /root && umount` 解决了这个问题
3. 缺少挂载验证：`_execute_share()` 挂载后只做了简单的 `df -h` 验证，没有检查mountpoint
4. **unshare成功后**应该也卸载服务端的nfs-kernel-server，当前没有

### 修复方案
1. `_execute_share()`: 挂载后添加 `mountpoint -q` 验证 + fstab持久化（当前被注释掉了）
2. `_execute_unshare()`: 卸载成功后添加 `mountpoint -q` 验证确认已卸载
3. unshare时清理服务端后也检查nfs-server是否需要停止
4. 添加重试机制：mount/umount失败时重试

**修改文件**: `step_34_nfs_config.py`

---

## 问题2: rc-local 覆盖原有配置 + 缺少 systemctl restart

### 现状分析
`step_8_rc_local.py` 的问题：
1. **第52行**: `echo '#!/bin/bash' | sudo tee /etc/rc.local` — 使用 `tee` 会**覆盖**整个 `/etc/rc.local` 文件，如果已有自定义内容全部丢失
2. **缺少 `systemctl restart rc-local.service`** — 只做了 daemon-reload + enable，没有restart，意味着rc.local脚本不会立即生效
3. 服务文件使用 `echo | tee` 写入，没有检查已有服务文件是否不同

### 修复方案
1. 检查 `/etc/rc.local` 是否已存在，存在则只确保有 `#!/bin/bash` 头，不覆盖内容
2. 添加 `systemctl restart rc-local.service` 使配置立即生效
3. 服务文件写入前检查是否已存在相同内容，避免不必要的覆盖

**修改文件**: `step_8_rc_local.py`

---

## 问题3: /etc/hosts 缺少跳板机IP绑定

### 现状分析
`step_9_hostname_hosts.py` 只遍历 `self.config.nodes` 添加hosts条目，**不包含跳板机**。

在有跳板机的PROXY模式下，节点需要通过跳板机IP访问，如果hosts中没有跳板机的IP-主机名映射，可能导致：
- NFS配置中引用跳板机hostname时无法解析
- 时间同步配置中引用跳板机hostname时无法解析
- 其他需要解析跳板机hostname的场景失败

### 修复方案
1. 在 `hosts_entries` 生成时，如果配置了jumphost，将jumphost的IP和hostname也加入
2. 需要处理jumphost可能没有hostname的情况（用host IP作为标识）

**修改文件**: `step_9_hostname_hosts.py`

---

## 问题4: 步骤16固定内核版本不生效

### 现状分析
`step_16_lock_kernel.py` 的问题：
1. `is_configured()` 中：当 `kernel.mode == "keep"` 时直接返回True跳过
2. 但 `versions.yaml` 中 `kernel.mode: "keep"` 且 `keep.lock_version: true` — 这意味着 **mode=keep + lock_version=true 应该执行锁定**
3. 当前的 `is_configured()` 逻辑没有检查 `lock_version`，导致 keep+lock 场景下步骤被跳过
4. `execute()` 方法也不检查 `lock_version`，直接执行GRUB修改，但如果is_configured已经返回True跳过了，execute根本不会执行

### 修复方案
1. 修改 `is_configured()`：当 `mode=keep` 时，检查 `keep.lock_version` 是否为True，如果是则需要验证GRUB配置
2. 修改 `execute()`：检查 `mode=keep` + `lock_version=False` 时跳过，`lock_version=True` 时执行
3. 添加 `keep.update_grub` 的检查：如果为True才执行 update-grub

**修改文件**: `step_16_lock_kernel.py`

---

## 问题5: NFS配置导致 /etc/exports 丢失

### 现状分析
`_execute_share()` 中的逻辑：
```python
# 检查exports是否已有该export_path条目
if check_result.get("stdout", "").strip() == "exists":
    # 先移除旧条目再添加新条目
    sed_cmd = f"sed -i '\\|{export_path}|d' /etc/exports"
    self.execute_on_host(server_ip, sed_cmd, sudo=True)
```

问题：`sed -i` 使用 `|` 分隔符，但 `{export_path}` 中如果包含 `/`（如 `/data/assets`），不会导致问题（`|` 不是路径字符）。但真正的问题是：
1. **没有备份** /etc/exports — 如果sed命令异常可能导致文件损坏
2. 先删除所有包含该路径的行，再逐个添加 — 如果执行中断，exports会丢失

### 修复方案
1. 在修改前备份 `/etc/exports`
2. 不采用"先删全部再逐个添加"的策略，改为只添加缺失的条目，只删除IP不再需要的旧条目
3. 对比shell脚本的逻辑：shell脚本只追加不存在的条目，不删除旧条目

**修改文件**: `step_34_nfs_config.py`

---

## 问题6: 更新 ARCHITECTURE.md

### 需求
1. 记录代码结构，帮助AI对代码有整体了解
2. 方便修改代码和添加删除功能
3. 不要流水账，要求整体概述和牵连关键点标记

### 修复方案
重写ARCHITECTURE.md，遵循以下原则：
1. **分层概述**：目录结构→数据流→核心模块→步骤详解
2. **关键牵连点标记**：模块间依赖、改动影响面、常见坑
3. **决策记录**：为什么这样设计而不是那样
4. **更新本次7个问题的修复要点**

**修改文件**: `ARCHITECTURE.md`

---

## 问题7: step_10_create_user ubuntu默认信息

### 现状分析
当前创建ubuntu用户时：
```python
group_cmd = "groupadd -g 1001 ubuntu 2>/dev/null || true"
user_cmd = "useradd -u 1001 -g 1001 -m -s /bin/bash ubuntu"
```

Ubuntu系统默认第一个用户的uid/gid是1000，所以ubuntu用户应该用：
- uid=1000, gid=1000

但当前硬编码为1001，这与Ubuntu默认不符。

### 修复方案
1. 修改默认uid/gid为1000（Ubuntu默认值）
2. 更新step_description中的描述
3. 添加注释说明为什么用1000（Ubuntu默认第一个用户）

**修改文件**: `step_10_create_user.py`

---

## 实施顺序

1. **问题7** (最简单) → step_10_create_user.py
2. **问题2** (简单) → step_8_rc_local.py
3. **问题3** (中等) → step_9_hostname_hosts.py
4. **问题4** (中等) → step_16_lock_kernel.py
5. **问题0** (复杂) → step_0d_ssh_key.py
6. **问题5 + 问题1** (复杂, 同一文件) → step_34_nfs_config.py
7. **问题6** (最后, 反映所有修改) → ARCHITECTURE.md
