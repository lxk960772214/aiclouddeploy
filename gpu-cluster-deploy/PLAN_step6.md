# Step 06 磁盘挂载优化方案

## 问题分析

当前节点 `lsblk` 状态：
```
nvme0n1 → nvme0n1p1 挂载在 /home/nvme01
nvme1n1 → nvme1n1p1 挂载在 /home/nvme02
nvme2n1 → nvme2n1p1 (未挂载但有分区)
nvme3n1 → nvme3n1p1 (未挂载但有分区)
```

目标配置：
```yaml
storage:
  type: "raid10"
  devices: ["/dev/nvme0n1", "/dev/nvme1n1", "/dev/nvme2n1", "/dev/nvme3n1"]
  mount_point: "/ssd"
  filesystem: "ext4"
  format_disk: true
```

## 现有代码缺陷

1. **不处理已有分区**: `_mount_raid` 直接对裸盘 `mdadm --create`，但设备已有分区表 → 失败或数据损坏
2. **不卸载现有挂载**: `/home/nvme01`, `/home/nvme02` 未卸载 → 无法清除分区
3. **is_configured 过于简单**: 只检查 `mountpoint -q /ssd`，不检查 RAID 状态、fstab 正确性
4. **RAID 已存在时的重入逻辑不完善**: 停止 RAID 后不清理成员设备分区
5. **缺少 mdadm 安装**: RAID 模式未检查/安装 mdadm
6. **fstab 残留不清理**: 旧挂载点 `/home/nvme01` 等的 fstab 条目未清理

## 改造方案

### _mount_raid 重写流程

```
1. 安装 mdadm（如未安装）
2. 检查并卸载所有成员设备上的现有挂载
   - 遍历 devices，检查 mount | grep 设备或分区
   - umount 所有相关挂载
3. 清除所有成员设备上的分区表和超级块
   - mdadm --stop /dev/md0 (如已有RAID)
   - mdadm --zero-superblock 对每个设备
   - wipefs -a 对每个设备（清除分区表+文件系统签名）
   - sfdisk --delete 或 fdisk 删除分区
4. 创建 RAID
   - mdadm --create /dev/md0 --level=10 --raid-devices=N ...
   - 等待同步完成（可选，mdadm --wait 或直接跳过）
5. 保存 RAID 配置
   - mdadm --detail --scan > /etc/mdadm/mdadm.conf
   - update-initramfs -u（确保重启后RAID自动装配）
6. 格式化
   - mkfs.ext4 /dev/md0
7. 清理旧 fstab 条目
   - 移除所有成员设备相关挂载条目（/home/nvme01 等）
8. 写入新 fstab 条目（UUID=/ssd）
9. 挂载 + 验证
```

### is_configured 增强

检查 3 项：
1. **RAID 设备存在且正常**: `mdadm --detail /dev/md0` 且 State 包含 "clean"
2. **挂载点正确**: `mountpoint -q /ssd`
3. **fstab 条目正确**: grep /ssd /etc/fstab 存在且指向正确的 UUID

任意一项不满足 → 返回 False，触发重新配置。

### post_check 增强

验证每个节点：
1. `mdadm --detail /dev/md0` 正常
2. `df -h /ssd` 显示空间
3. `mountpoint -q /ssd` 通过

### 代码改动清单

- [x] `step_6_disk_mount.py` — 重写 `_mount_raid`、增强 `is_configured`、增强 `post_check`
- [ ] 无其他文件改动
