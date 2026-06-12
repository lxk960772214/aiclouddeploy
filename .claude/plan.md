# 实现计划

## 任务1: versions.yaml 中 local_file 支持相对路径

### 问题
当前 `nccl`、`nvidia_driver`、`mlnx_ofed`、`cuda` 的 `local_file` 字段只支持绝对路径，不支持相对路径。用户希望把安装包都放在 `gpu-cluster-deploy/packages/` 目录下，在 `gpu-cluster-deploy/` 目录执行命令时，可以直接写 `packages/xxx.zip` 作为相对路径。

### 方案
在 `config_loader.py` 的 `_parse_versions_config` 方法中，解析完各配置后，统一对 `local_file` 字段做相对路径转换：

- 如果 `local_file` 不是绝对路径，则基于**项目根目录**（即 `config_dir` 的父目录）解析为绝对路径
- 项目根目录 = `self.config_dir.parent`（因为 `config_dir` 是 `config/`，其父目录就是 `gpu-cluster-deploy/`）
- 转换时机：在 `_parse_versions_config` 返回之前
- 转换后存储的是绝对路径，下游代码（`package_manager.py`、`step_25_nccl.py` 等）无需修改

### 修改文件

1. **`gpu-cluster-deploy/src/config_loader.py`**
   - 在 `_parse_versions_config` 方法末尾，返回前，添加 `_resolve_local_file_paths()` 辅助方法调用
   - 新增 `_resolve_local_file_paths(config: VersionsConfig)` 方法，遍历 `cuda`、`nvidia_driver`、`mlnx_ofed`、`nccl` 的 `local_file` 字段，如果是相对路径则转为绝对路径

2. **`gpu-cluster-deploy/config/versions.yaml`**
   - 将现有的绝对路径改为相对路径示例：
     - `nvidia_driver.local_file`: `"/home/ubuntu/sourcecode/NVIDIA-Linux-x86_64-595.80.run"` → `"packages/NVIDIA-Linux-x86_64-595.80.run"`
     - `nccl.local_file`: `"/home/ubuntu/gpu-cluster-deploy/packages/nccl-master.zip"` → `"packages/nccl-master.zip"`

3. **`gpu-cluster-deploy/config/versions_example.yaml`**
   - 注释中的示例路径改为相对路径形式

---

## 任务2: 添加 NFS 取消共享（unshare）功能

### 问题
当前 `step_34_nfs_config.py` 只实现了 NFS 共享（mount），没有取消共享（unmount）功能。Shell 脚本 `base_step5_deployServ.sh` 中有完整的 `NFS_FILE_UNSHARE` 实现可以参考。

### 方案
在 `NFSConfig` 数据模型中添加 `action` 字段（`share` / `unshare`，默认 `share`），然后在 `step_34_nfs_config.py` 的 `execute` 方法中根据 `action` 执行不同逻辑。

### 修改文件

1. **`gpu-cluster-deploy/src/models/cluster.py`**
   - `NFSConfig` dataclass 添加 `action: str = "share"` 字段
   - `to_dict()` 方法添加 `action` 字段

2. **`gpu-cluster-deploy/src/config_loader.py`**
   - `_parse_cluster_config` 中解析 `nfs.action` 字段

3. **`gpu-cluster-deploy/src/steps/step_34_nfs_config.py`**
   - 修改 `step_name` 和 `step_description` 支持动态显示
   - `execute` 方法中根据 `nfs_config.action` 分流：
     - `action == "share"`：执行现有挂载逻辑
     - `action == "unshare"`：执行取消共享逻辑
   - 新增 `_execute_unshare` 方法，参考 shell 脚本逻辑：
     1. 单节点检查，跳过
     2. 在服务器端：SSH 到每个客户端节点执行 umount（先普通 umount，失败则 umount -l）
     3. 清理 `/etc/exports` 中相关条目
     4. 在客户端：删除 fstab 条目
   - `is_configured` 方法适配 unshare 模式

4. **`gpu-cluster-deploy/config/cluste_nfs_example.yaml`**
   - 添加 `action` 字段示例和注释说明

5. **`gpu-cluster-deploy/config/versions_nfs_example.yaml`**
   - 如有需要，更新示例
