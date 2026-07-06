# 实现计划：添加禁止SSH密码登录步骤（step_0e）

## 概述
新增部署步骤 `step_0e_disable_password_auth.py`，用于配置禁止SSH密码登录，增强集群安全性。

## 步骤编号选择
使用 `0e`，与 `0d`（SSH免密配置）相邻，因为两者都属于SSH安全配置，且禁止密码登录应在SSH免密配置完成后执行，避免锁死。

## 实现内容

### 1. 新建步骤文件 `src/steps/step_0e_disable_password_auth.py`
- 类名：`DisablePasswordAuth`
- step_id: `"0e"`
- step_name: `"禁止SSH密码登录"`
- requires_sudo: True
- supports_batch: True
- 实现逻辑：
  - `is_configured()`: 检查 `/etc/ssh/sshd_config` 和 `/etc/ssh/sshd_config.d/` 下是否已设置 `PasswordAuthentication no`
  - `execute()`:
    1. 修改 `/etc/ssh/sshd_config` 中 `PasswordAuthentication yes` → `PasswordAuthentication no`
    2. 修改 `/etc/ssh/sshd_config.d/50-cloud-init.conf` 中（如果存在）`PasswordAuthentication yes` → `PasswordAuthentication no`
    3. 检查并修改 sshd_config.d 目录下其他可能覆盖的配置文件
    4. 重启 sshd 服务
    5. 验证配置生效
  - `post_check()`: 验证 `PasswordAuthentication` 已设置为 `no`

### 2. 在 `src/steps/__init__.py` 中注册
- 添加 import
- 添加到 `ALL_STEPS` 列表（在 `SSHKeySetup` 之后）
- 添加到 `STEP_METADATA`
- 添加到 `__all__`

### 3. 更新 `run.sh`
- 在 base 组中添加 `--step 0e`

### 4. 更新 `README.md`
- 目录结构中添加 step_0e 文件
- 步骤分组表中添加说明
- 详细步骤说明表中添加条目
