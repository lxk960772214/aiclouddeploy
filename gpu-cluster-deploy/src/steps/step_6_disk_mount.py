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

    def _mount_single_disk(self, host: str, device: str, mount_point: str) -> Dict[str, Any]:
        """单盘挂载"""
        results = {}

        # 1. 检查设备是否存在
        check_cmd = f"ls -la {device}"
        check_result = self.execute_on_host(host, check_cmd)
        if not check_result["success"]:
            return {"success": False, "error": f"设备 {device} 不存在"}

        # 2. 格式化设备
        format_cmd = f"mkfs.ext4 -F {device}"
        format_result = self.execute_on_host(host, format_cmd, sudo=True)
        results["format"] = format_result

        # 3. 获取UUID
        uuid_cmd = f"blkid {device} -s UUID -o value"
        uuid_result = self.execute_on_host(host, uuid_cmd, sudo=True)
        if not uuid_result["success"]:
            return {"success": False, "error": "获取UUID失败", "results": results}

        uuid = uuid_result["stdout"].strip()
        results["uuid"] = uuid

        # 4. 创建挂载点
        mkdir_cmd = f"mkdir -p {mount_point}"
        mkdir_result = self.execute_on_host(host, mkdir_cmd, sudo=True)
        results["mkdir"] = mkdir_result

        # 5. 添加到fstab
        fstab_entry = f"UUID={uuid} {mount_point} ext4 defaults,nofail 0 0"
        # 检查是否已存在
        check_fstab = f"grep '{fstab_entry}' /etc/fstab"
        check_result = self.execute_on_host(host, check_fstab, sudo=True)

        if not check_result["success"]:
            add_fstab_cmd = f"echo '{fstab_entry}' >> /etc/fstab"
            add_result = self.execute_on_host(host, add_fstab_cmd, sudo=True)
            results["fstab"] = add_result

        # 6. 挂载
        mount_cmd = "mount -a"
        mount_result = self.execute_on_host(host, mount_cmd, sudo=True)
        results["mount"] = mount_result

        # 7. 验证
        verify_cmd = f"df -h {mount_point}"
        verify_result = self.execute_on_host(host, verify_cmd)
        results["verify"] = verify_result

        return {
            "success": verify_result["success"],
            "results": results
        }

    def _mount_raid(self, host: str, devices: List[str], raid_level: int,
                    mount_point: str) -> Dict[str, Any]:
        """RAID挂载"""
        results = {}
        raid_device = "/dev/md0"

        # 1. 检查所有设备
        for dev in devices:
            check_cmd = f"ls -la {dev}"
            check_result = self.execute_on_host(host, check_cmd)
            if not check_result["success"]:
                return {"success": False, "error": f"设备 {dev} 不存在"}

        # 2. 清除现有分区表（可选，需谨慎）
        # 这里不自动执行，需要用户确认

        # 3. 创建RAID
        devices_str = " ".join(devices)
        create_cmd = f"mdadm --create {raid_device} --level={raid_level} --raid-devices={len(devices)} {devices_str} --force"
        create_result = self.execute_on_host(host, create_cmd, sudo=True)
        results["create_raid"] = create_result

        if not create_result["success"]:
            return {"success": False, "error": "RAID创建失败", "results": results}

        # 4. 保存RAID配置
        save_cmd = "mdadm --detail --scan >> /etc/mdadm/mdadm.conf"
        save_result = self.execute_on_host(host, save_cmd, sudo=True)
        results["save_raid"] = save_result

        # 5. 格式化
        format_cmd = f"mkfs.ext4 -F {raid_device}"
        format_result = self.execute_on_host(host, format_cmd, sudo=True)
        results["format"] = format_result

        # 6. 获取UUID并挂载
        uuid_cmd = f"blkid {raid_device} -s UUID -o value"
        uuid_result = self.execute_on_host(host, uuid_cmd, sudo=True)

        if uuid_result["success"]:
            uuid = uuid_result["stdout"].strip()
            results["uuid"] = uuid

            # 创建挂载点
            mkdir_cmd = f"mkdir -p {mount_point}"
            self.execute_on_host(host, mkdir_cmd, sudo=True)

            # 添加到fstab
            fstab_entry = f"UUID={uuid} {mount_point} ext4 defaults,nofail 0 0"
            add_fstab_cmd = f"echo '{fstab_entry}' >> /etc/fstab"
            self.execute_on_host(host, add_fstab_cmd, sudo=True)

            # 挂载
            mount_cmd = "mount -a"
            self.execute_on_host(host, mount_cmd, sudo=True)

        # 7. 验证
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
                if storage.type == StorageType.SINGLE.value or storage.type == "single":
                    result = self._mount_single_disk(
                        host,
                        storage.device,
                        storage.mount_point
                    )
                elif storage.type in [StorageType.RAID1.value, StorageType.RAID10.value, "raid1", "raid10"]:
                    raid_level = 1 if storage.type in ["raid1", StorageType.RAID1.value] else 10
                    result = self._mount_raid(
                        host,
                        storage.devices,
                        raid_level,
                        storage.mount_point
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
