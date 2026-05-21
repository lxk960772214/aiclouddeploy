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
        results = {}

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

        export_path = nfs_config.export_path
        client_mount = nfs_config.client_mount

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
        mkdir_cmd = f"mkdir -p {export_path} && chmod -R 777 {export_path}"
        self.execute_on_host(server_ip, mkdir_cmd, sudo=True)

        # 配置exports（避免重复添加）
        client_ips_str = ",".join(client_ips)
        exports_entry = f"{export_path} {client_ips_str}(rw,sync,no_subtree_check)"
        # 先检查是否已存在相同的exports条目
        check_exports_cmd = f"grep -q '{export_path}' /etc/exports 2>/dev/null && echo 'exists' || echo 'not_exists'"
        check_result = self.execute_on_host(server_ip, check_exports_cmd, sudo=True)

        if check_result.get("stdout", "").strip() != "exists":
            exports_cmd = f'echo "{exports_entry}" >> /etc/exports'
            self.execute_on_host(server_ip, exports_cmd, sudo=True)
        else:
            self.logger.info(f"[{server_ip}] exports条目已存在，跳过添加")

        # 重启NFS服务
        restart_nfs_cmd = "systemctl restart nfs-server && systemctl enable nfs-server && exportfs -arv"
        server_result = self.execute_on_host(server_ip, restart_nfs_cmd, sudo=True)
        results[server_ip] = {"server": server_result}

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

            # 挂载NFS（使用服务器存储网IP）
            mount_cmd = f"mount -t nfs -o rw,sync,hard,intr,timeo=5,retrans=3 {server_ip}:{export_path} {client_mount}"
            mount_result = self.execute_on_host(host, mount_cmd, sudo=True)

            # 添加到fstab
            fstab_entry = f"{server_ip}:{export_path} {client_mount} nfs rw,sync,hard,intr,timeo=5,retrans=3 0 0"
            fstab_cmd = f'grep -q "{fstab_entry}" /etc/fstab || echo "{fstab_entry}" >> /etc/fstab'
            self.execute_on_host(host, fstab_cmd, sudo=True)

            # 验证挂载
            verify_cmd = f"df -h {client_mount}"
            verify_result = self.execute_on_host(host, verify_cmd)

            results[host] = {
                "success": mount_result["success"] and verify_result["success"],
                "mount": mount_result,
                "verify": verify_result
            }

        success_count = sum(1 for r in results.values() if r.get("success"))

        return StepResult(
            step_id=self.step_id,
            step_name=self.step_name,
            status=StepStatus.SUCCESS if success_count == len(hosts) else StepStatus.FAILED,
            message=f"NFS配置完成，成功: {success_count}/{len(hosts)}",
            details={
                "server_ip": server_ip,
                "export_path": export_path,
                "client_mount": client_mount,
                "client_ips": client_ips,
                "network_type": "storage" if self.config.network and self.config.network.has_network_config("storage") else "management"
            },
            host_results=results
        )

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

        # 检查服务器
        server_verify = f"showmount -e {server_ip}"
        result = self.execute_on_host(server_ip, server_verify)
        return result.get("success", False)
