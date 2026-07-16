"""
步骤06: 挂载数据盘
"""

from typing import List, Dict, Any, Optional
from src.steps.base import BaseStep, StepResult, StepStatus
from src.models.cluster import StorageConfig, StorageType


class DiskMount(BaseStep):
    """挂载数据盘"""

    step_id = "06"
    step_name = "挂载数据盘"
    step_description = "格式化并挂载数据盘（支持单盘和RAID）"
    requires_sudo = True
    supports_batch = False  # 每个节点配置可能不同，不支持批量
    timeout = 900  # RAID10 初始化需要更长时间

    def _get_node_storage(self, hostname: str) -> Optional[StorageConfig]:
        """获取节点存储配置"""
        for node in self.config.nodes:
            if node.hostname == hostname:
                return node.storage
        return None

    # ── 单盘挂载 ──────────────────────────────────────────

    def _mount_single_disk(self, host: str, device: str, mount_point: str,
                           filesystem: str = "ext4", format_disk: bool = True) -> Dict[str, Any]:
        """单盘挂载"""
        results = {}
        results["format_disk"] = format_disk

        # 1. 检查设备是否存在
        check_cmd = f"ls -la {device}"
        check_result = self.execute_on_host(host, check_cmd)
        if not check_result["success"]:
            return {"success": False, "error": f"设备 {device} 不存在"}

        # 2. 卸载现有挂载（该设备上的任何分区）
        self._unmount_device_partitions(host, device)

        # 3. 获取设备信息（检查是否已格式化）
        blkid_cmd = f"blkid {device}"
        blkid_result = self.execute_on_host(host, blkid_cmd, sudo=True)
        is_formatted = blkid_result["success"]
        results["already_formatted"] = is_formatted

        uuid = None
        # 4. 条件格式化
        if format_disk and not is_formatted:
            self.logger.info(f"[{host}] 格式化设备 {device} 为 {filesystem}")
            format_cmd = f"mkfs.{filesystem} -F {device}"
            format_result = self.execute_on_host(host, format_cmd, sudo=True)
            results["format"] = format_result

            if not format_result["success"]:
                return {"success": False, "error": f"格式化设备 {device} 失败", "results": results}
        elif format_disk and is_formatted:
            self.logger.warning(f"[{host}] 设备 {device} 已格式化，跳过格式化步骤")
            results["format"] = {"success": True, "message": "已格式化，跳过"}
        elif not format_disk:
            self.logger.info(f"[{host}] 配置为不格式化设备 {device}")
            results["format"] = {"success": True, "message": "配置不格式化，跳过"}

        # 5. 获取UUID（格式化后或已有）
        uuid_cmd = f"blkid {device} -s UUID -o value"
        uuid_result = self.execute_on_host(host, uuid_cmd, sudo=True)
        if not uuid_result["success"]:
            # 如果配置不格式化且没有UUID，尝试使用设备路径
            if not format_disk:
                self.logger.info(f"[{host}] 使用设备路径 {device} 代替UUID")
                uuid = device
            else:
                return {"success": False, "error": "获取UUID失败", "results": results}
        else:
            uuid = uuid_result["stdout"].strip()

        results["uuid"] = uuid

        # 6. 创建挂载点
        mkdir_cmd = f"mkdir -p {mount_point}"
        mkdir_result = self.execute_on_host(host, mkdir_cmd, sudo=True)
        results["mkdir"] = mkdir_result

        # 7. 检查现有挂载
        check_mount_cmd = f"mount | grep '{mount_point}'"
        check_mount_result = self.execute_on_host(host, check_mount_cmd)
        is_mounted = check_mount_result["success"]
        results["already_mounted"] = is_mounted

        if is_mounted:
            self.logger.info(f"[{host}] {mount_point} 已挂载，先卸载")
            umount_cmd = f"umount {mount_point}"
            self.execute_on_host(host, umount_cmd, sudo=True)

        # 8. 添加到fstab
        fstab_uuid = self._build_fstab_uuid(uuid, device)
        fstab_entry = f"{fstab_uuid} {mount_point} {filesystem} defaults,nofail 0 0"

        # 移除现有同挂载点条目
        self._remove_fstab_entry(host, mount_point)

        # 添加新条目
        add_fstab_cmd = f"echo '{fstab_entry}' >> /etc/fstab"
        add_result = self.execute_on_host(host, add_fstab_cmd, sudo=True)
        results["fstab"] = add_result

        # 9. 挂载
        mount_cmd = "mount -a"
        mount_result = self.execute_on_host(host, mount_cmd, sudo=True)
        results["mount"] = mount_result

        # 10. 验证
        verify_cmd = f"df -h {mount_point}"
        verify_result = self.execute_on_host(host, verify_cmd)
        results["verify"] = verify_result

        return {
            "success": verify_result["success"],
            "results": results
        }

    # ── RAID 挂载 ──────────────────────────────────────────

    def _unmount_device_partitions(self, host: str, device: str) -> None:
        """卸载指定设备上所有分区的现有挂载，并清理 fstab"""
        # 获取设备上所有分区（如 /dev/nvme0n1 → nvme0n1p1, nvme0n1p2 等）
        device_name = device.replace("/dev/", "")
        ls_partitions_cmd = f"lsblk -ln -o NAME,MOUNTPOINT {device} 2>/dev/null"
        result = self.execute_on_host(host, ls_partitions_cmd, sudo=True)

        if not result["success"]:
            return

        mounts_to_remove = []
        for line in result.get("stdout", "").strip().split("\n"):
            if not line.strip():
                continue
            parts = line.split()
            if len(parts) >= 2 and parts[1] and parts[1] != "/":
                # 分区有挂载点
                partition_name = parts[0]
                mount_point = parts[1]
                mounts_to_remove.append((partition_name, mount_point))

        for partition_name, mount_point in mounts_to_remove:
            self.logger.info(f"[{host}] 卸载分区 {partition_name} (挂载点: {mount_point})")
            # 卸载
            umount_cmd = f"umount {mount_point}"
            self.execute_on_host(host, umount_cmd, sudo=True)
            # 清理 fstab 中该挂载点的条目
            self._remove_fstab_entry(host, mount_point)

    def _wipe_devices(self, host: str, devices: List[str]) -> None:
        """彻底清除设备上的分区表、文件系统签名和 RAID 超级块"""
        for dev in devices:
            self.logger.info(f"[{host}] 清除设备 {dev} 的分区表和签名")

            # 1. 停止该设备上的 RAID 成员（如有）
            zero_superblock_cmd = f"mdadm --zero-superblock {dev} 2>/dev/null || true"
            self.execute_on_host(host, zero_superblock_cmd, sudo=True)
            # 也对分区清除超级块
            zero_part_cmd = f"mdadm --zero-superblock {dev}* 2>/dev/null || true"
            self.execute_on_host(host, zero_part_cmd, sudo=True)

            # 2. 清除文件系统签名和 RAID 元数据
            wipefs_cmd = f"wipefs -a {dev} 2>/dev/null || true"
            self.execute_on_host(host, wipefs_cmd, sudo=True)

            # 3. 删除所有分区
            # sfdisk 方式删除所有分区
            delete_parts_cmd = f"sfdisk --delete {dev} 2>/dev/null || true"
            self.execute_on_host(host, delete_parts_cmd, sudo=True)

            # 4. 用 dd 清零分区表头部（确保干净）
            dd_cmd = f"dd if=/dev/zero of={dev} bs=1M count=10 2>/dev/null || true"
            self.execute_on_host(host, dd_cmd, sudo=True)

            # 5. 再次 wipefs（清除 dd 后可能残留的签名）
            wipefs_cmd2 = f"wipefs -a {dev} 2>/dev/null || true"
            self.execute_on_host(host, wipefs_cmd2, sudo=True)

            # 6. 让内核重新读取分区表
            partprobe_cmd = f"partprobe {dev} 2>/dev/null || true"
            self.execute_on_host(host, partprobe_cmd, sudo=True)

    def _install_mdadm(self, host: str) -> bool:
        """安装 mdadm 工具"""
        check_cmd = "which mdadm 2>/dev/null"
        result = self.execute_on_host(host, check_cmd)
        if result["success"]:
            return True

        self.logger.info(f"[{host}] 安装 mdadm...")
        install_cmd = "apt-get update -qq && apt-get install -y -qq mdadm"
        install_result = self.execute_on_host(host, install_cmd, sudo=True, timeout=300)
        return install_result["success"]

    def _mount_raid(self, host: str, devices: List[str], raid_level: int,
                    mount_point: str, filesystem: str = "ext4", format_disk: bool = True) -> Dict[str, Any]:
        """RAID挂载（完整流程：卸载→清除分区→创建RAID→格式化→挂载）"""
        results = {}
        results["format_disk"] = format_disk
        raid_device = "/dev/md0"

        # 1. 检查所有设备是否存在
        for dev in devices:
            check_cmd = f"ls -la {dev}"
            check_result = self.execute_on_host(host, check_cmd)
            if not check_result["success"]:
                return {"success": False, "error": f"设备 {dev} 不存在"}

        # 2. 安装 mdadm
        if not self._install_mdadm(host):
            return {"success": False, "error": "mdadm 安装失败"}

        # 3. 检查 RAID 是否已存在且正确
        raid_exists = False
        raid_correct = False
        check_raid_cmd = f"mdadm --detail {raid_device} 2>/dev/null || true"
        check_raid_result = self.execute_on_host(host, check_raid_cmd, sudo=True)
        raid_output = check_raid_result.get("stdout", "")

        if "State :" in raid_output:
            raid_exists = True
            # 检查 RAID 是否与配置匹配
            raid_level_str = f"Raid Level : raid{raid_level}"
            if raid_level_str in raid_output:
                # 检查成员设备数量
                expected_count = len(devices)
                for line in raid_output.split("\n"):
                    if "Raid Devices :" in line:
                        try:
                            actual_count = int(line.split(":")[1].strip())
                            if actual_count == expected_count:
                                raid_correct = True
                        except (ValueError, IndexError):
                            pass
                        break

        if raid_exists and raid_correct and not format_disk:
            # RAID 已存在且正确，且不需要格式化 → 直接使用
            self.logger.info(f"[{host}] RAID设备 {raid_device} 已存在且配置正确，直接使用")
            results["raid_exists"] = True
            results["raid_correct"] = True
        else:
            # 需要重建 RAID
            if raid_exists:
                self.logger.info(f"[{host}] 停止现有 RAID 设备 {raid_device}")
                stop_cmd = f"mdadm --stop {raid_device} 2>/dev/null || true"
                self.execute_on_host(host, stop_cmd, sudo=True)
                # 等待设备释放
                import time
                time.sleep(2)

            # 4. 卸载所有成员设备上的现有挂载
            self.logger.info(f"[{host}] 卸载成员设备上的现有挂载")
            for dev in devices:
                self._unmount_device_partitions(host, dev)

            # 5. 清除所有成员设备上的分区表和签名
            self.logger.info(f"[{host}] 清除成员设备上的分区表和签名")
            self._wipe_devices(host, devices)

            # 6. 创建 RAID
            self.logger.info(f"[{host}] 创建 RAID{raid_level}: {', '.join(devices)}")
            devices_str = " ".join(devices)
            create_cmd = (
                f"mdadm --create {raid_device} --level={raid_level} "
                f"--raid-devices={len(devices)} {devices_str} --force --run"
            )
            create_result = self.execute_on_host(host, create_cmd, sudo=True)
            results["create_raid"] = create_result

            if not create_result["success"]:
                return {"success": False, "error": "RAID创建失败", "results": results}

            # 7. 保存 RAID 配置
            self.logger.info(f"[{host}] 保存 RAID 配置")
            # 先备份再覆盖，避免重复追加
            save_cmd = (
                f"mkdir -p /etc/mdadm && "
                f"cp /etc/mdadm/mdadm.conf /etc/mdadm/mdadm.conf.bak 2>/dev/null || true && "
                f"mdadm --detail --scan > /etc/mdadm/mdadm.conf"
            )
            save_result = self.execute_on_host(host, save_cmd, sudo=True)
            results["save_raid"] = save_result

            # 更新 initramfs，确保重启后 RAID 自动装配
            initramfs_cmd = "update-initramfs -u 2>/dev/null || true"
            self.execute_on_host(host, initramfs_cmd, sudo=True)

        # 8. 等待 RAID 设备就绪
        wait_cmd = f"ls -la {raid_device} && echo 'raid_ready'"
        wait_result = self.execute_on_host(host, wait_cmd, sudo=True)
        if "raid_ready" not in wait_result.get("stdout", ""):
            return {"success": False, "error": f"RAID设备 {raid_device} 未就绪"}

        # 9. 检查 RAID 是否已格式化
        blkid_cmd = f"blkid {raid_device}"
        blkid_result = self.execute_on_host(host, blkid_cmd, sudo=True)
        is_formatted = blkid_result["success"]
        results["already_formatted"] = is_formatted

        uuid = None
        # 10. 条件格式化
        if format_disk and not is_formatted:
            self.logger.info(f"[{host}] 格式化RAID设备 {raid_device} 为 {filesystem}")
            format_cmd = f"mkfs.{filesystem} -F {raid_device}"
            format_result = self.execute_on_host(host, format_cmd, sudo=True, timeout=600)
            results["format"] = format_result

            if not format_result["success"]:
                return {"success": False, "error": f"格式化RAID设备 {raid_device} 失败", "results": results}
        elif format_disk and is_formatted:
            self.logger.warning(f"[{host}] RAID设备 {raid_device} 已格式化，跳过格式化步骤")
            results["format"] = {"success": True, "message": "已格式化，跳过"}
        elif not format_disk:
            self.logger.info(f"[{host}] 配置为不格式化RAID设备 {raid_device}")
            results["format"] = {"success": True, "message": "配置不格式化，跳过"}

        # 11. 获取UUID（格式化后或已有）
        uuid_cmd = f"blkid {raid_device} -s UUID -o value"
        uuid_result = self.execute_on_host(host, uuid_cmd, sudo=True)
        if not uuid_result["success"]:
            if not format_disk:
                self.logger.info(f"[{host}] 使用RAID设备路径 {raid_device} 代替UUID")
                uuid = raid_device
            else:
                return {"success": False, "error": "获取RAID UUID失败", "results": results}
        else:
            uuid = uuid_result["stdout"].strip()

        results["uuid"] = uuid

        # 12. 创建挂载点
        mkdir_cmd = f"mkdir -p {mount_point}"
        mkdir_result = self.execute_on_host(host, mkdir_cmd, sudo=True)
        results["mkdir"] = mkdir_result

        # 13. 检查现有挂载
        check_mount_cmd = f"mount | grep '{mount_point}'"
        check_mount_result = self.execute_on_host(host, check_mount_cmd)
        is_mounted = check_mount_result["success"]
        results["already_mounted"] = is_mounted

        if is_mounted:
            self.logger.info(f"[{host}] {mount_point} 已挂载，先卸载")
            umount_cmd = f"umount {mount_point}"
            self.execute_on_host(host, umount_cmd, sudo=True)

        # 14. 添加到fstab
        fstab_uuid = self._build_fstab_uuid(uuid, raid_device)
        fstab_entry = f"{fstab_uuid} {mount_point} {filesystem} defaults,nofail 0 0"

        # 移除现有同挂载点条目
        self._remove_fstab_entry(host, mount_point)

        # 添加新条目
        add_fstab_cmd = f"echo '{fstab_entry}' >> /etc/fstab"
        add_result = self.execute_on_host(host, add_fstab_cmd, sudo=True)
        results["fstab"] = add_result

        # 15. 挂载
        mount_cmd = "mount -a"
        mount_result = self.execute_on_host(host, mount_cmd, sudo=True)
        results["mount"] = mount_result

        # 16. 验证
        verify_cmd = f"df -h {mount_point}"
        verify_result = self.execute_on_host(host, verify_cmd)
        results["verify"] = verify_result

        return {
            "success": verify_result["success"],
            "results": results
        }

    # ── 工具方法 ──────────────────────────────────────────

    def _build_fstab_uuid(self, uuid: Optional[str], fallback_device: str) -> str:
        """构建 fstab 的 UUID/设备路径字段"""
        if uuid and uuid != fallback_device and not uuid.startswith('/') and not uuid.startswith('UUID='):
            return f"UUID={uuid}"
        elif uuid and uuid.startswith('UUID='):
            return uuid
        elif uuid and uuid.startswith('/'):
            return uuid  # 设备路径直接使用
        else:
            return fallback_device  # 回退到设备路径

    def _remove_fstab_entry(self, host: str, mount_point: str) -> None:
        """移除 fstab 中指定挂载点的条目"""
        mount_point_escaped = mount_point.replace('/', '\\/')
        check_cmd = f"grep -E '^[^#]*{mount_point_escaped}[[:space:]]' /etc/fstab"
        check_result = self.execute_on_host(host, check_cmd, sudo=True)

        if check_result["success"]:
            self.logger.info(f"[{host}] 移除fstab中 {mount_point} 的现有条目")
            remove_cmd = (
                f"grep -v -E '^[^#]*{mount_point_escaped}[[:space:]]' /etc/fstab > /tmp/fstab.tmp && "
                f"cat /tmp/fstab.tmp > /etc/fstab && rm -f /tmp/fstab.tmp"
            )
            self.execute_on_host(host, remove_cmd, sudo=True)

    def _get_node_config_by_ip(self, host: str):
        """根据 IP 获取节点配置"""
        if not self.config:
            return None
        for node in self.config.nodes:
            if node.ip == host:
                return node
        return None

    # ── 主执行 ──────────────────────────────────────────

    def execute(self, hosts: List[str]) -> StepResult:
        """执行磁盘挂载"""
        all_results = {}
        errors = []

        for host in hosts:
            node = self._get_node_config_by_ip(host)

            if not node or not node.storage:
                self.logger.warning(f"[{host}] 未配置存储，跳过")
                all_results[host] = {"success": True, "skipped": True}
                continue

            storage = node.storage
            self.logger.info(f"[{host}] 配置存储: {storage.type}")

            try:
                filesystem = storage.filesystem if hasattr(storage, 'filesystem') else "ext4"
                format_disk = storage.format_disk if hasattr(storage, 'format_disk') else False

                if storage.type == StorageType.SINGLE.value or storage.type == "single":
                    result = self._mount_single_disk(
                        host,
                        storage.device,
                        storage.mount_point,
                        filesystem,
                        format_disk
                    )
                elif storage.type in [StorageType.RAID1.value, StorageType.RAID10.value, "raid1", "raid10"]:
                    raid_level = 1 if storage.type in ["raid1", StorageType.RAID1.value] else 10
                    result = self._mount_raid(
                        host,
                        storage.devices,
                        raid_level,
                        storage.mount_point,
                        filesystem,
                        format_disk
                    )
                else:
                    result = {"success": False, "error": f"未知存储类型: {storage.type}"}

                all_results[host] = result

                if not result.get("success"):
                    errors.append(f"{host}: {result.get('error', '未知错误')}")

            except Exception as e:
                errors.append(f"{host}: {str(e)}")
                all_results[host] = {"success": False, "error": str(e)}

        success_count = sum(1 for r in all_results.values() if r.get("success"))

        if errors:
            return StepResult(
                step_id=self.step_id,
                step_name=self.step_name,
                status=StepStatus.FAILED if success_count == 0 else StepStatus.SUCCESS,
                message=f"磁盘挂载完成，成功: {success_count}/{len(hosts)}",
                errors=errors,
                host_results=all_results
            )

        return StepResult(
            step_id=self.step_id,
            step_name=self.step_name,
            status=StepStatus.SUCCESS,
            message=f"磁盘挂载完成，成功: {success_count}/{len(hosts)}",
            host_results=all_results
        )

    # ── 配置检查 ──────────────────────────────────────────

    def is_configured(self, host: str) -> tuple:
        """
        检查数据盘是否已正确配置

        检查项:
        1. 存储配置是否存在
        2. RAID 模式: RAID 设备是否存在且正常
        3. 挂载点是否正确挂载
        4. fstab 条目是否正确

        Returns:
            tuple[bool, str]: (是否已配置, 检查详情)
        """
        node = self._get_node_config_by_ip(host)

        if not node or not node.storage:
            return True, "未配置存储，跳过"

        storage = node.storage
        mount_point = storage.mount_point

        # RAID 模式额外检查
        if storage.type in [StorageType.RAID1.value, StorageType.RAID10.value, "raid1", "raid10"]:
            raid_device = "/dev/md0"

            # 检查 RAID 设备是否存在且正常
            raid_cmd = f"mdadm --detail {raid_device} 2>/dev/null || echo 'RAID_NOT_FOUND'"
            raid_result = self.execute_on_host(host, raid_cmd, sudo=True)
            raid_output = raid_result.get("stdout", "")

            if "RAID_NOT_FOUND" in raid_output or "State :" not in raid_output:
                return False, f"RAID设备 {raid_device} 不存在"

            # 检查 RAID 级别是否匹配
            raid_level = 1 if storage.type in ["raid1", StorageType.RAID1.value] else 10
            raid_level_str = f"raid{raid_level}"
            if f"Raid Level : {raid_level_str}" not in raid_output:
                return False, f"RAID级别不匹配 (期望: {raid_level_str})"

            # 检查 RAID 状态（clean 或 active 都算正常）
            state_ok = False
            for line in raid_output.split("\n"):
                if "State :" in line:
                    state = line.split(":")[1].strip()
                    if state in ("clean", "active", "active, resyncing", "clean, resyncing"):
                        state_ok = True
                    break
            if not state_ok:
                return False, f"RAID状态异常"

            # 检查成员设备数量
            expected_count = len(storage.devices)
            for line in raid_output.split("\n"):
                if "Raid Devices :" in line:
                    try:
                        actual_count = int(line.split(":")[1].strip())
                        if actual_count != expected_count:
                            return False, f"RAID成员数量不匹配 (期望: {expected_count}, 实际: {actual_count})"
                    except (ValueError, IndexError):
                        pass
                    break

        # 检查挂载点
        mount_cmd = f"mountpoint -q {mount_point} && echo 'mounted' || echo 'not_mounted'"
        mount_result = self.execute_on_host(host, mount_cmd, sudo=False)
        stdout = mount_result.get("stdout", "").strip()
        if stdout != "mounted":
            return False, f"{mount_point} 未挂载"

        # 检查 fstab 条目
        fstab_cmd = f"grep -E '^[^#]*{mount_point}[[:space:]]' /etc/fstab"
        fstab_result = self.execute_on_host(host, fstab_cmd, sudo=True)
        if not fstab_result["success"]:
            return False, f"/etc/fstab 缺少 {mount_point} 挂载条目"

        return True, f"{mount_point} 已正确挂载"

    def post_check(self, hosts: List[str]) -> bool:
        """验证磁盘挂载"""
        for host in hosts:
            node = self._get_node_config_by_ip(host)

            if node and node.storage:
                mount_point = node.storage.mount_point

                # 验证挂载
                cmd = f"df -h {mount_point}"
                result = self.execute_on_host(host, cmd)
                if not result["success"]:
                    return False

                # RAID 模式额外验证
                if node.storage.type in [StorageType.RAID1.value, StorageType.RAID10.value, "raid1", "raid10"]:
                    raid_cmd = "mdadm --detail /dev/md0 2>/dev/null || echo 'FAIL'"
                    raid_result = self.execute_on_host(host, raid_cmd, sudo=True)
                    if "FAIL" in raid_result.get("stdout", ""):
                        self.logger.warning(f"[{host}] RAID设备 /dev/md0 验证失败")
                        return False

        return True
