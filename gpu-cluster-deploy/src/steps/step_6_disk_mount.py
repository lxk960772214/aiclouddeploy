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
    timeout = 600

    def _get_node_storage(self, hostname: str) -> Optional[StorageConfig]:
        """获取节点存储配置"""
        for node in self.config.nodes:
            if node.hostname == hostname:
                return node.storage
        return None

    def _mount_single_disk(self, host: str, device: str, mount_point: str, filesystem: str = "ext4", format_disk: bool = True) -> Dict[str, Any]:
        """单盘挂载"""
        results = {}
        results["format_disk"] = format_disk

        # 1. 检查设备是否存在
        check_cmd = f"ls -la {device}"
        check_result = self.execute_on_host(host, check_cmd)
        if not check_result["success"]:
            return {"success": False, "error": f"设备 {device} 不存在"}

        # 2. 获取设备信息（检查是否已格式化）
        blkid_cmd = f"blkid {device}"
        blkid_result = self.execute_on_host(host, blkid_cmd, sudo=True)
        is_formatted = blkid_result["success"]
        results["already_formatted"] = is_formatted

        uuid = None
        # 3. 条件格式化
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

        # 4. 获取UUID（格式化后或已有）
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

        # 5. 创建挂载点
        mkdir_cmd = f"mkdir -p {mount_point}"
        mkdir_result = self.execute_on_host(host, mkdir_cmd, sudo=True)
        results["mkdir"] = mkdir_result

        # 6. 检查现有挂载
        check_mount_cmd = f"mount | grep '{mount_point}'"
        check_mount_result = self.execute_on_host(host, check_mount_cmd)
        is_mounted = check_mount_result["success"]
        results["already_mounted"] = is_mounted

        if is_mounted:
            self.logger.info(f"[{host}] {mount_point} 已挂载，先卸载")
            umount_cmd = f"umount {mount_point}"
            self.execute_on_host(host, umount_cmd, sudo=True)

        # 7. 添加到fstab
        # 如果uuid是真正的UUID（不是设备路径），需要添加UUID=前缀
        if uuid and uuid != device and not uuid.startswith('/') and not uuid.startswith('UUID='):
            fstab_uuid = f"UUID={uuid}"
        elif uuid and uuid.startswith('UUID='):
            fstab_uuid = uuid
        elif uuid and uuid.startswith('/'):
            fstab_uuid = uuid  # 设备路径直接使用
        else:
            fstab_uuid = device  # 回退到设备路径

        fstab_entry = f"{fstab_uuid} {mount_point} {filesystem} defaults,nofail 0 0"

        # 检查是否已存在相同的挂载点条目
        check_fstab_mount_cmd = f"grep -E '^[^#]*{mount_point}[[:space:]]' /etc/fstab"
        check_fstab_mount_result = self.execute_on_host(host, check_fstab_mount_cmd, sudo=True)

        if check_fstab_mount_result["success"]:
            # 移除现有条目
            self.logger.info(f"[{host}] 移除现有fstab条目: {mount_point}")
            temp_cmd = f"grep -v -E '^[^#]*{mount_point}[[:space:]]' /etc/fstab > /tmp/fstab.tmp && cat /tmp/fstab.tmp > /etc/fstab && rm /tmp/fstab.tmp"
            self.execute_on_host(host, temp_cmd, sudo=True)

        # 添加新条目
        add_fstab_cmd = f"echo '{fstab_entry}' >> /etc/fstab"
        add_result = self.execute_on_host(host, add_fstab_cmd, sudo=True)
        results["fstab"] = add_result

        # 8. 挂载
        mount_cmd = "mount -a"
        mount_result = self.execute_on_host(host, mount_cmd, sudo=True)
        results["mount"] = mount_result

        # 9. 验证
        verify_cmd = f"df -h {mount_point}"
        verify_result = self.execute_on_host(host, verify_cmd)
        results["verify"] = verify_result

        return {
            "success": verify_result["success"],
            "results": results
        }

    def _mount_raid(self, host: str, devices: List[str], raid_level: int,
                    mount_point: str, filesystem: str = "ext4", format_disk: bool = True) -> Dict[str, Any]:
        """RAID挂载"""
        results = {}
        results["format_disk"] = format_disk
        raid_device = "/dev/md0"

        # 1. 检查所有设备
        for dev in devices:
            check_cmd = f"ls -la {dev}"
            check_result = self.execute_on_host(host, check_cmd)
            if not check_result["success"]:
                return {"success": False, "error": f"设备 {dev} 不存在"}

        # 2. 检查RAID是否已存在
        check_raid_cmd = f"mdadm --detail {raid_device} 2>/dev/null || true"
        check_raid_result = self.execute_on_host(host, check_raid_cmd, sudo=True)
        raid_exists = "State :" in check_raid_result.get("stdout", "")

        if raid_exists:
            self.logger.info(f"[{host}] RAID设备 {raid_device} 已存在")
            results["raid_exists"] = True

            if format_disk:
                self.logger.warning(f"[{host}] RAID已存在，但配置要求格式化。先停止RAID")
                stop_cmd = f"mdadm --stop {raid_device}"
                self.execute_on_host(host, stop_cmd, sudo=True)
                raid_exists = False
        else:
            results["raid_exists"] = False

        # 3. 清除现有分区表（可选，需谨慎）
        # 这里不自动执行，需要用户确认

        # 4. 创建RAID（如果不存在）
        if not raid_exists:
            devices_str = " ".join(devices)
            create_cmd = f"mdadm --create {raid_device} --level={raid_level} --raid-devices={len(devices)} {devices_str} --force"
            create_result = self.execute_on_host(host, create_cmd, sudo=True)
            results["create_raid"] = create_result

            if not create_result["success"]:
                return {"success": False, "error": "RAID创建失败", "results": results}

            # 保存RAID配置
            save_cmd = "mkdir -p /etc/mdadm && mdadm --detail --scan >> /etc/mdadm/mdadm.conf"
            save_result = self.execute_on_host(host, save_cmd, sudo=True)
            results["save_raid"] = save_result
        else:
            self.logger.info(f"[{host}] 使用现有RAID设备 {raid_device}")
            results["create_raid"] = {"success": True, "message": "使用现有RAID"}
            results["save_raid"] = {"success": True, "message": "RAID配置已存在"}

        # 5. 检查RAID是否已格式化
        blkid_cmd = f"blkid {raid_device}"
        blkid_result = self.execute_on_host(host, blkid_cmd, sudo=True)
        is_formatted = blkid_result["success"]
        results["already_formatted"] = is_formatted

        uuid = None
        # 6. 条件格式化
        if format_disk and not is_formatted:
            self.logger.info(f"[{host}] 格式化RAID设备 {raid_device} 为 {filesystem}")
            format_cmd = f"mkfs.{filesystem} -F {raid_device}"
            format_result = self.execute_on_host(host, format_cmd, sudo=True)
            results["format"] = format_result

            if not format_result["success"]:
                return {"success": False, "error": f"格式化RAID设备 {raid_device} 失败", "results": results}
        elif format_disk and is_formatted:
            self.logger.warning(f"[{host}] RAID设备 {raid_device} 已格式化，跳过格式化步骤")
            results["format"] = {"success": True, "message": "已格式化，跳过"}
        elif not format_disk:
            self.logger.info(f"[{host}] 配置为不格式化RAID设备 {raid_device}")
            results["format"] = {"success": True, "message": "配置不格式化，跳过"}

        # 7. 获取UUID（格式化后或已有）
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

        # 8. 创建挂载点
        mkdir_cmd = f"mkdir -p {mount_point}"
        mkdir_result = self.execute_on_host(host, mkdir_cmd, sudo=True)
        results["mkdir"] = mkdir_result

        # 9. 检查现有挂载
        check_mount_cmd = f"mount | grep '{mount_point}'"
        check_mount_result = self.execute_on_host(host, check_mount_cmd)
        is_mounted = check_mount_result["success"]
        results["already_mounted"] = is_mounted

        if is_mounted:
            self.logger.info(f"[{host}] {mount_point} 已挂载，先卸载")
            umount_cmd = f"umount {mount_point}"
            self.execute_on_host(host, umount_cmd, sudo=True)

        # 10. 添加到fstab
        # 如果uuid是真正的UUID（不是设备路径），需要添加UUID=前缀
        if uuid and uuid != raid_device and not uuid.startswith('/') and not uuid.startswith('UUID='):
            fstab_uuid = f"UUID={uuid}"
        elif uuid and uuid.startswith('UUID='):
            fstab_uuid = uuid
        elif uuid and uuid.startswith('/'):
            fstab_uuid = uuid  # 设备路径直接使用
        else:
            fstab_uuid = raid_device  # 回退到设备路径

        fstab_entry = f"{fstab_uuid} {mount_point} {filesystem} defaults,nofail 0 0"

        # 检查是否已存在相同的挂载点条目
        check_fstab_mount_cmd = f"grep -E '^[^#]*{mount_point}[[:space:]]' /etc/fstab"
        check_fstab_mount_result = self.execute_on_host(host, check_fstab_mount_cmd, sudo=True)

        if check_fstab_mount_result["success"]:
            # 移除现有条目
            self.logger.info(f"[{host}] 移除现有fstab条目: {mount_point}")
            temp_cmd = f"grep -v -E '^[^#]*{mount_point}[[:space:]]' /etc/fstab > /tmp/fstab.tmp && cat /tmp/fstab.tmp > /etc/fstab && rm /tmp/fstab.tmp"
            self.execute_on_host(host, temp_cmd, sudo=True)

        # 添加新条目
        add_fstab_cmd = f"echo '{fstab_entry}' >> /etc/fstab"
        add_result = self.execute_on_host(host, add_fstab_cmd, sudo=True)
        results["fstab"] = add_result

        # 11. 挂载
        mount_cmd = "mount -a"
        mount_result = self.execute_on_host(host, mount_cmd, sudo=True)
        results["mount"] = mount_result

        # 12. 验证
        verify_cmd = f"df -h {mount_point}"
        verify_result = self.execute_on_host(host, verify_cmd)
        results["verify"] = verify_result

        return {
            "success": verify_result["success"],
            "results": results
        }

    def execute(self, hosts: List[str]) -> StepResult:
        """执行磁盘挂载"""
        all_results = {}
        errors = []

        for host in hosts:
            # 获取节点信息
            node = None
            for n in self.config.nodes:
                if n.ip == host:
                    node = n
                    break

            if not node or not node.storage:
                self.logger.warning(f"[{host}] 未配置存储，跳过")
                all_results[host] = {"success": True, "skipped": True}
                continue

            storage = node.storage
            self.logger.info(f"[{host}] 配置存储: {storage.type}")

            try:
                # 获取文件系统和格式化选项
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

    def is_configured(self, host: str) -> tuple:
        """
        检查数据盘是否已挂载

        Args:
            host: 主机地址

        Returns:
            tuple[bool, str]: (是否已配置, 检查详情)
        """
        # 获取节点存储配置
        node = None
        for n in self.config.nodes:
            if n.ip == host:
                node = n
                break

        if not node or not node.storage:
            return True, "未配置存储，跳过"

        mount_point = node.storage.mount_point

        # 检查挂载点是否已挂载
        result = self.execute_on_host(host, f"mountpoint -q {mount_point} && echo 'mounted' || echo 'not_mounted'", sudo=False)

        stdout = result.get("stdout", "").strip()
        # 精确匹配，避免 "mounted" 在 "not_mounted" 中被误判
        if stdout == "mounted":
            return True, f"{mount_point} 已挂载"
        return False, f"{mount_point} 未挂载"

    def post_check(self, hosts: List[str]) -> bool:
        """验证磁盘挂载"""
        for host in hosts:
            node = None
            for n in self.config.nodes:
                if n.ip == host:
                    node = n
                    break

            if node and node.storage:
                cmd = f"df -h {node.storage.mount_point}"
                result = self.execute_on_host(host, cmd)
                if not result["success"]:
                    return False
        return True
