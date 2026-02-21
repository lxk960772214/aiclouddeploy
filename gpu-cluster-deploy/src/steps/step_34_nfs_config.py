"""
步骤34: 配置NFS网络存储
"""

from typing import List
from src.steps.base import BaseStep, StepResult, StepStatus


class NFSConfig(BaseStep):
    """配置NFS网络存储"""

    step_id = "34"
    step_name = "配置NFS网络存储"
    step_description = "配置NFS服务器和客户端"
    requires_sudo = True
    supports_batch = False
    can_skip = True  # NFS是可选的

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

        server_ip = nfs_server.ip
        export_path = nfs_config.export_path
        client_mount = nfs_config.client_mount
        client_ips = [node.ip for node in self.config.client_nodes]

        self.logger.info(f"NFS服务器: {nfs_server.hostname} ({server_ip})")
        self.logger.info(f"导出路径: {export_path}, 客户端挂载: {client_mount}")

        # 1. 配置NFS服务器
        self.logger.info(f"[{server_ip}] 配置NFS服务器...")

        # 安装NFS服务器
        install_server_cmd = "apt-get install -y nfs-kernel-server"
        self.execute_on_host(server_ip, install_server_cmd, sudo=True)

        # 创建导出目录
        mkdir_cmd = f"mkdir -p {export_path} && chmod -R 777 {export_path}"
        self.execute_on_host(server_ip, mkdir_cmd, sudo=True)

        # 配置exports
        client_ips_str = ",".join(client_ips)
        exports_entry = f"{export_path} {client_ips_str}(rw,sync,no_subtree_check)"
        exports_cmd = f'echo "{exports_entry}" >> /etc/exports'
        self.execute_on_host(server_ip, exports_cmd, sudo=True)

        # 重启NFS服务
        restart_nfs_cmd = "systemctl restart nfs-server && systemctl enable nfs-server && exportfs -arv"
        server_result = self.execute_on_host(server_ip, restart_nfs_cmd, sudo=True)
        results[server_ip] = {"server": server_result}

        # 2. 配置NFS客户端
        for host in hosts:
            if host == server_ip:
                continue

            self.logger.info(f"[{host}] 配置NFS客户端...")

            # 安装NFS客户端
            install_client_cmd = "apt-get install -y nfs-common"
            self.execute_on_host(host, install_client_cmd, sudo=True)

            # 创建挂载点
            mkdir_cmd = f"mkdir -p {client_mount}"
            self.execute_on_host(host, mkdir_cmd, sudo=True)

            # 挂载NFS
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
                "client_mount": client_mount
            },
            host_results=results
        )

    def post_check(self, hosts: List[str]) -> bool:
        """验证NFS配置"""
        nfs_config = self.config.nfs
        if not nfs_config or not nfs_config.enabled:
            return True

        nfs_server = self.config.nfs_server_node
        if not nfs_server:
            return True

        # 检查服务器
        server_verify = f"showmount -e {nfs_server.ip}"
        result = self.execute_on_host(nfs_server.ip, server_verify)
        return result.get("success", False)
