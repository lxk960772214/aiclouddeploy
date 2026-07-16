"""
步骤34: 配置NFS网络存储
"""

from typing import List, Optional
from src.steps.base import BaseStep, StepResult, StepStatus
from src.network.ip_resolver import IPResolver


class NFSConfig(BaseStep):
    """配置NFS网络存储"""

    step_id = "34"
    step_name = "配置NFS网络存储"
    step_description = "配置NFS服务器和客户端"
    requires_sudo = True
    supports_batch = False
    can_skip = True  # NFS是可选的

    def __init__(self, config=None, ssh_manager=None, batch_executor=None, logger=None, versions=None):
        super().__init__(config, ssh_manager, batch_executor, logger, versions)
        self.ip_resolver = IPResolver(ssh_manager)

    def _get_nfs_server_ip(self, nfs_server_hostname: str) -> Optional[str]:
        """
        获取NFS服务器的IP地址

        智能选择策略：
        1. 优先使用存储网IP（如果配置了存储网络）
        2. 回退到管理网IP

        Args:
            nfs_server_hostname: NFS服务器主机名

        Returns:
            IP地址字符串
        """
        network_config = self.config.network

        # 检查是否配置了存储网络
        if network_config and network_config.has_network_config("storage"):
            # 尝试获取存储网IP
            storage_ip = self.ip_resolver.get_network_ip(
                nfs_server_hostname,
                network_config,
                "storage"
            )
            if storage_ip:
                self.logger.info(f"使用存储网IP配置NFS: {storage_ip}")
                return storage_ip

        # 回退到管理网IP（使用节点配置中的默认IP）
        nfs_server = self.config.get_node_by_hostname(nfs_server_hostname)
        if nfs_server:
            self.logger.info(f"使用管理网IP配置NFS: {nfs_server.ip}")
            return nfs_server.ip

        return None

    def _get_client_ips_for_nfs(self) -> List[str]:
        """
        获取NFS客户端IP列表

        使用智能选择策略为每个客户端选择合适的IP

        Returns:
            客户端IP地址列表
        """
        client_ips = []
        network_config = self.config.network

        for node in self.config.client_nodes:
            # 优先使用存储网IP
            if network_config and network_config.has_network_config("storage"):
                storage_ip = self.ip_resolver.get_network_ip(
                    node.hostname,
                    network_config,
                    "storage"
                )
                if storage_ip:
                    client_ips.append(storage_ip)
                    self.logger.debug(f"客户端 {node.hostname} 使用存储网IP: {storage_ip}")
                    continue

            # 回退到节点默认IP
            client_ips.append(node.ip)
            self.logger.debug(f"客户端 {node.hostname} 使用管理网IP: {node.ip}")

        return client_ips

    def execute(self, hosts: List[str]) -> StepResult:
        """执行NFS配置"""
        # 检查是否启用NFS
        nfs_config = self.config.nfs
        if not nfs_config or not nfs_config.enabled:
            self.logger.info("NFS未启用，跳过配置")
            return StepResult(
                step_id=self.step_id,
                step_name=self.step_name,
                status=StepStatus.SKIPPED,
                message="NFS未启用，跳过配置"
            )

        # 根据action分流
        action = nfs_config.action
        if action == "unshare":
            return self._execute_unshare(hosts)
        else:
            # 默认执行共享
            return self._execute_share(hosts)

    def _execute_share(self, hosts: List[str]) -> StepResult:
        """执行NFS共享（挂载）"""
        results = {}

        # 获取NFS服务器节点
        nfs_server = self.config.nfs_server_node
        if not nfs_server:
            self.logger.warning("未配置NFS服务器节点，跳过")
            return StepResult(
                step_id=self.step_id,
                step_name=self.step_name,
                status=StepStatus.SKIPPED,
                message="未配置NFS服务器节点"
            )

        # 使用智能IP选择获取服务器IP
        server_ip = self._get_nfs_server_ip(nfs_server.hostname)
        if not server_ip:
            self.logger.error(f"无法获取NFS服务器 {nfs_server.hostname} 的IP地址")
            return StepResult(
                step_id=self.step_id,
                step_name=self.step_name,
                status=StepStatus.FAILED,
                message=f"无法获取NFS服务器 {nfs_server.hostname} 的IP地址"
            )

        export_path = self.config.nfs.export_path
        client_mount = self.config.nfs.client_mount

        # 使用智能IP选择获取客户端IP列表
        client_ips = self._get_client_ips_for_nfs()

        self.logger.info(f"NFS服务器: {nfs_server.hostname} ({server_ip})")
        self.logger.info(f"导出路径: {export_path}, 客户端挂载: {client_mount}")
        self.logger.info(f"客户端IP列表: {', '.join(client_ips)}")

        # 1. 配置NFS服务器
        self.logger.info(f"[{server_ip}] 配置NFS服务器...")

        # 安装NFS服务器
        install_server_cmd = "DEBIAN_FRONTEND=noninteractive apt-get install -y nfs-kernel-server"
        self.execute_on_host(server_ip, install_server_cmd, sudo=True)

        # 创建导出目录
        mkdir_cmd = f"mkdir -p {export_path}"
        self.execute_on_host(server_ip, mkdir_cmd, sudo=True)

        # 备份 /etc/exports
        backup_cmd = f"test -f /etc/exports.bak || cp /etc/exports /etc/exports.bak"
        self.execute_on_host(server_ip, backup_cmd, sudo=True)

        # 配置exports — 只追加缺失的条目，不删除已有条目（避免丢失其他NFS配置）
        for client_ip in client_ips:
            # 检查该客户端IP的条目是否已存在
            check_entry = f"grep -q '{export_path}.*{client_ip}' /etc/exports 2>/dev/null && echo 'exists' || echo 'not_exists'"
            check_result = self.execute_on_host(server_ip, check_entry, sudo=True)

            if check_result.get("stdout", "").strip() != "exists":
                # 条目不存在，追加
                exports_entry = f"{export_path} {client_ip}(rw,sync,no_subtree_check,no_root_squash)"
                exports_cmd = f'echo "{exports_entry}" >> /etc/exports'
                self.execute_on_host(server_ip, exports_cmd, sudo=True)
                self.logger.info(f"[{server_ip}] 添加exports条目: {client_ip}")
            else:
                self.logger.info(f"[{server_ip}] exports条目已存在: {client_ip}，跳过")

        # 重启NFS服务
        restart_nfs_cmd = "systemctl restart nfs-server && systemctl enable nfs-server && exportfs -arv"
        server_result = self.execute_on_host(server_ip, restart_nfs_cmd, sudo=True)
        results[server_ip] = {"success": server_result.get("success", False), "server": server_result}

        # 2. 配置NFS客户端
        for host in hosts:
            # 获取该客户端用于挂载的IP（存储网优先）
            client_node = self.config.get_node_by_ip(host) or self.config.get_node_by_hostname(host)
            if not client_node:
                self.logger.warning(f"未找到节点 {host}，跳过NFS客户端配置")
                continue

            # 跳过服务器自己
            if client_node.hostname == nfs_server.hostname:
                continue

            self.logger.info(f"[{host}] 配置NFS客户端...")

            # 安装NFS客户端
            install_client_cmd = "DEBIAN_FRONTEND=noninteractive apt-get install -y nfs-common"
            self.execute_on_host(host, install_client_cmd, sudo=True)

            # 创建挂载点
            mkdir_cmd = f"mkdir -p {client_mount}"
            self.execute_on_host(host, mkdir_cmd, sudo=True)

            # 检查是否已挂载
            check_mount_cmd = f"mountpoint -q {client_mount} && echo 'mounted' || echo 'not_mounted'"
            check_result = self.execute_on_host(host, check_mount_cmd, sudo=True)

            if check_result.get("stdout", "").strip() == "mounted":
                self.logger.info(f"[{host}] NFS已挂载，跳过挂载操作")
                results[host] = {"success": True, "message": "NFS已挂载"}
                continue

            # 挂载NFS（使用服务器存储网IP）
            mount_cmd = f"mount -t nfs {server_ip}:{export_path} {client_mount}"
            mount_result = self.execute_on_host(host, mount_cmd, sudo=True)

            if not mount_result.get("success", False):
                # 挂载失败，尝试带重试选项
                self.logger.warning(f"[{host}] 首次挂载失败，尝试带选项重试...")
                mount_cmd_retry = f"mount -t nfs -o rw,sync,hard,timeo=5,retrans=3 {server_ip}:{export_path} {client_mount}"
                mount_result = self.execute_on_host(host, mount_cmd_retry, sudo=True)

            # 添加到fstab（持久化挂载）
            fstab_entry = f"{server_ip}:{export_path} {client_mount} nfs rw,sync,hard,timeo=5,retrans=3 0 0"
            fstab_cmd = f'grep -q "{fstab_entry}" /etc/fstab || echo "{fstab_entry}" >> /etc/fstab'
            self.execute_on_host(host, fstab_cmd, sudo=True)

            # 验证挂载
            verify_cmd = f"mountpoint -q {client_mount} && echo 'mounted' || echo 'not_mounted'"
            verify_result = self.execute_on_host(host, verify_cmd, sudo=True)
            is_mounted = verify_result.get("stdout", "").strip() == "mounted"

            if not is_mounted:
                # 再次尝试df验证（mountpoint可能不可用）
                df_verify = f"df -h {client_mount} 2>/dev/null | grep -q '{server_ip}' && echo 'mounted' || echo 'not_mounted'"
                df_result = self.execute_on_host(host, df_verify, sudo=True)
                is_mounted = df_result.get("stdout", "").strip() == "mounted"

            results[host] = {
                "success": mount_result.get("success", False) and is_mounted,
                "mount": mount_result,
                "mounted": is_mounted
            }

        success_count = sum(1 for r in results.values() if r.get("success"))

        return StepResult(
            step_id=self.step_id,
            step_name=self.step_name,
            status=StepStatus.SUCCESS if success_count == len(results) else StepStatus.FAILED,
            message=f"NFS配置完成，成功: {success_count}/{len(results)}",
            details={
                "server_ip": server_ip,
                "export_path": export_path,
                "client_mount": client_mount,
                "client_ips": client_ips,
                "network_type": "storage" if self.config.network and self.config.network.has_network_config("storage") else "management"
            },
            host_results=results
        )

    def _execute_unshare(self, hosts: List[str]) -> StepResult:
        """
        执行NFS取消共享（卸载）

        参考 conf-git/deliveryTest/base_step5_deployServ.sh NFS_FILE_UNSHARE 逻辑：
        1. 单节点检查，跳过
        2. 在每个客户端节点上卸载NFS（cd /root避免device busy）
        3. 验证卸载成功
        4. 清理客户端fstab条目
        5. 清理服务器端/etc/exports中相关条目
        6. 验证服务器端exports已清理
        """
        nfs_config = self.config.nfs
        results = {}

        # 单节点检查
        if len(self.config.nodes) <= 1:
            self.logger.info("单节点无需卸载NFS服务")
            return StepResult(
                step_id=self.step_id,
                step_name=self.step_name,
                status=StepStatus.SKIPPED,
                message="单节点无需卸载NFS服务"
            )

        # 获取NFS服务器节点
        nfs_server = self.config.nfs_server_node
        if not nfs_server:
            self.logger.warning("未配置NFS服务器节点，跳过")
            return StepResult(
                step_id=self.step_id,
                step_name=self.step_name,
                status=StepStatus.SKIPPED,
                message="未配置NFS服务器节点"
            )

        # 获取服务器IP
        server_ip = self._get_nfs_server_ip(nfs_server.hostname)
        if not server_ip:
            self.logger.error(f"无法获取NFS服务器 {nfs_server.hostname} 的IP地址")
            return StepResult(
                step_id=self.step_id,
                step_name=self.step_name,
                status=StepStatus.FAILED,
                message=f"无法获取NFS服务器 {nfs_server.hostname} 的IP地址"
            )

        export_path = nfs_config.export_path
        client_mount = nfs_config.client_mount

        self.logger.info(f"取消NFS共享: 服务器 {nfs_server.hostname} ({server_ip})")
        self.logger.info(f"导出路径: {export_path}, 客户端挂载: {client_mount}")

        # 1. 在每个客户端节点上卸载NFS
        for host in hosts:
            client_node = self.config.get_node_by_ip(host) or self.config.get_node_by_hostname(host)
            if not client_node:
                self.logger.warning(f"未找到节点 {host}，跳过")
                continue

            # 跳过服务器自己
            if client_node.hostname == nfs_server.hostname:
                continue

            self.logger.info(f"[{host}] 卸载NFS挂载...")

            # 检查是否已挂载
            check_mount_cmd = f"mount | grep -q '{server_ip}:{export_path}' && echo 'mounted' || echo 'not_mounted'"
            check_result = self.execute_on_host(host, check_mount_cmd, sudo=True)
            mount_status = check_result.get("stdout", "").strip()

            if mount_status == "not_mounted":
                self.logger.info(f"[{host}] NFS未挂载，跳过卸载")
                results[host] = {"success": True, "message": "NFS未挂载，跳过"}
                # 仍然需要清理fstab
                self._remove_fstab_entry(host, server_ip, export_path, client_mount)
                continue

            # 执行卸载 - 先cd到/root避免cwd在NFS挂载目录内
            umount_cmd = f"cd /root && umount {client_mount}"
            umount_result = self.execute_on_host(host, umount_cmd, sudo=True)

            if not umount_result.get("success", False):
                # 正常卸载失败，尝试懒卸载
                self.logger.warning(f"[{host}] 正常卸载失败，尝试懒卸载(umount -l)...")
                lazy_umount_cmd = f"cd /root && umount -l {client_mount}"
                lazy_result = self.execute_on_host(host, lazy_umount_cmd, sudo=True)

                if not lazy_result.get("success", False):
                    self.logger.error(f"[{host}] 懒卸载也失败，请手动检查占用进程: lsof +D {client_mount}")
                    results[host] = {"success": False, "message": f"卸载失败，请手动检查: lsof +D {client_mount}"}
                    # 即使卸载失败，也清理fstab
                    self._remove_fstab_entry(host, server_ip, export_path, client_mount)
                    continue

            # 验证卸载是否成功（等待2秒让系统状态更新）
            import time
            time.sleep(2)
            verify_cmd = f"mount | grep -q '{server_ip}:{export_path}' && echo 'still_mounted' || echo 'unmounted'"
            verify_result = self.execute_on_host(host, verify_cmd, sudo=True)
            verify_status = verify_result.get("stdout", "").strip()

            if verify_status == "still_mounted":
                self.logger.error(f"[{host}] 卸载后仍处于挂载状态，请手动检查")
                results[host] = {"success": False, "message": "卸载后仍处于挂载状态"}
                self._remove_fstab_entry(host, server_ip, export_path, client_mount)
                continue

            # 删除挂载点目录（仅在目录为空时）
            rmdir_cmd = f"rmdir {client_mount} 2>/dev/null || true"
            self.execute_on_host(host, rmdir_cmd, sudo=True)

            # 清理fstab条目
            self._remove_fstab_entry(host, server_ip, export_path, client_mount)

            self.logger.info(f"[{host}] NFS卸载成功")
            results[host] = {"success": True, "message": "NFS卸载成功"}

        # 2. 在服务器端清理exports配置
        self.logger.info(f"[{server_ip}] 清理NFS服务器端exports配置...")
        check_exports_cmd = f"grep -q '{export_path}' /etc/exports 2>/dev/null && echo 'exists' || echo 'not_exists'"
        check_result = self.execute_on_host(server_ip, check_exports_cmd, sudo=True)

        if check_result.get("stdout", "").strip() == "exists":
            # 备份exports文件
            backup_cmd = f"test -f /etc/exports.bak || cp /etc/exports /etc/exports.bak"
            self.execute_on_host(server_ip, backup_cmd, sudo=True)

            # 从/etc/exports中移除包含export_path的行
            sed_cmd = f"sed -i '\\|{export_path}|d' /etc/exports"
            self.execute_on_host(server_ip, sed_cmd, sudo=True)

            # 验证exports已清理
            verify_exports_cmd = f"grep -q '{export_path}' /etc/exports 2>/dev/null && echo 'still_exists' || echo 'cleaned'"
            verify_exports_result = self.execute_on_host(server_ip, verify_exports_cmd, sudo=True)

            if verify_exports_result.get("stdout", "").strip() == "still_exists":
                self.logger.warning(f"[{server_ip}] exports条目仍存在，可能sed删除失败")
            else:
                self.logger.info(f"[{server_ip}] exports中相关条目已移除")

            # 刷新exports
            exportfs_cmd = "exportfs -arv"
            self.execute_on_host(server_ip, exportfs_cmd, sudo=True)
        else:
            self.logger.info(f"[{server_ip}] exports中无相关条目，跳过")

        results[server_ip] = {"success": True, "message": "服务器端exports已清理"}

        success_count = sum(1 for r in results.values() if r.get("success"))
        total_count = len(results)

        return StepResult(
            step_id=self.step_id,
            step_name=self.step_name,
            status=StepStatus.SUCCESS if success_count == total_count else StepStatus.FAILED,
            message=f"NFS取消共享完成，成功: {success_count}/{total_count}",
            details={
                "action": "unshare",
                "server_ip": server_ip,
                "export_path": export_path,
                "client_mount": client_mount,
            },
            host_results=results
        )

    def _remove_fstab_entry(self, host: str, server_ip: str, export_path: str, client_mount: str):
        """
        从客户端的fstab中移除NFS挂载条目

        Args:
            host: 客户端IP
            server_ip: NFS服务器IP
            export_path: 导出路径
            client_mount: 客户端挂载路径
        """
        # 使用多种模式匹配，确保能删除fstab中的NFS条目
        # 匹配 server_ip:export_path
        fstab_pattern = f"{server_ip}:{export_path}"
        sed_cmd = f"grep -q '{fstab_pattern}' /etc/fstab && sed -i '\\|{fstab_pattern}|d' /etc/fstab || true"
        self.execute_on_host(host, sed_cmd, sudo=True)
        self.logger.info(f"[{host}] fstab中NFS条目已清理")

    def is_configured(self, host: str) -> tuple:
        """
        检查NFS是否已配置

        Args:
            host: 主机地址

        Returns:
            tuple[bool, str]: (是否已配置, 检查详情)
        """
        nfs_config = self.config.nfs
        if not nfs_config or not nfs_config.enabled:
            return True, "NFS未启用，跳过"

        nfs_server = self.config.nfs_server_node
        if not nfs_server:
            return True, "未配置NFS服务器"

        # 获取服务器IP
        server_ip = self._get_nfs_server_ip(nfs_server.hostname)
        if not server_ip:
            return False, "无法获取NFS服务器IP"

        client_mount = nfs_config.client_mount

        # 检查当前节点是否是NFS服务器
        node = self.config.get_node_by_ip(host) or self.config.get_node_by_hostname(host)

        if nfs_config.action == "unshare":
            # unshare模式：检查是否已卸载
            if node and node.hostname == nfs_server.hostname:
                # 服务器端：检查exports中是否还有条目
                result = self.execute_on_host(host, f"grep -q '{nfs_config.export_path}' /etc/exports 2>/dev/null && echo 'has_exports' || echo 'no_exports'", timeout=30)
                stdout = result.get("stdout", "").strip()
                if stdout == "no_exports":
                    return True, "NFS服务器端exports已清理"
                return False, "NFS服务器端exports尚未清理"

            # 客户端：检查是否已卸载
            result = self.execute_on_host(host, f"mount | grep -q '{server_ip}:{nfs_config.export_path}' && echo 'mounted' || echo 'not_mounted'", timeout=30)
            stdout = result.get("stdout", "").strip()
            if stdout == "not_mounted":
                return True, f"NFS客户端已卸载: {client_mount}"
            return False, f"NFS客户端仍处于挂载状态: {client_mount}"

        # share模式（默认）
        if node and node.hostname == nfs_server.hostname:
            # 服务器端检查
            result = self.execute_on_host(host, "systemctl is-active nfs-server 2>/dev/null || echo 'inactive'", timeout=30)
            stdout = result.get("stdout", "").strip()
            # 精确匹配，避免 "active" 在 "inactive" 中被误判
            if stdout == "active":
                return True, "NFS服务器已配置"
            return False, "NFS服务器未运行"

        # 客户端检查
        result = self.execute_on_host(host, f"mountpoint -q {client_mount} && echo 'mounted' || echo 'not_mounted'", timeout=30)
        stdout = result.get("stdout", "").strip()
        # 精确匹配
        if stdout == "mounted":
            return True, f"NFS客户端已挂载: {client_mount}"

        return False, f"NFS客户端未挂载: {client_mount}"

    def post_check(self, hosts: List[str]) -> bool:
        """验证NFS配置"""
        nfs_config = self.config.nfs
        if not nfs_config or not nfs_config.enabled:
            return True

        nfs_server = self.config.nfs_server_node
        if not nfs_server:
            return True

        # 获取服务器IP（使用智能选择）
        server_ip = self._get_nfs_server_ip(nfs_server.hostname)
        if not server_ip:
            return False

        if nfs_config.action == "unshare":
            # unshare模式：验证已卸载
            # 检查exports是否已清理
            check_exports = f"grep -q '{nfs_config.export_path}' /etc/exports 2>/dev/null && echo 'has_exports' || echo 'no_exports'"
            result = self.execute_on_host(server_ip, check_exports)
            if result.get("stdout", "").strip() == "has_exports":
                self.logger.warning("服务器端exports尚未完全清理")
                return False
            return True

        # share模式：检查服务器
        server_verify = f"showmount -e {server_ip}"
        result = self.execute_on_host(server_ip, server_verify)
        return result.get("success", False)
