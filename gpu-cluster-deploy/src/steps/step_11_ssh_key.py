"""
步骤11: 设置SSH免密登录
"""

from typing import List
from src.steps.base import BaseStep, StepResult, StepStatus


class SSHKeySetup(BaseStep):
    """设置SSH免密登录"""

    step_id = "11"
    step_name = "设置SSH免密登录"
    step_description = "配置节点间SSH免密登录"
    requires_sudo = True
    supports_batch = False  # 需要逐个节点处理密钥交换

    def _get_ssh_dir(self, username: str) -> str:
        """获取用户SSH目录路径"""
        if username == "root":
            return "/root/.ssh"
        return f"/home/{username}/.ssh"

    def is_configured(self, host: str) -> tuple:
        """
        检查SSH免密登录是否已配置（包含实际连接验证）

        Args:
            host: 主机地址

        Returns:
            tuple[bool, str]: (是否已配置, 检查详情)
        """
        # 获取节点配置的用户名
        node = self._get_node_config(host)
        username = node.username if node and hasattr(node, 'username') else 'ubuntu'
        ssh_dir = self._get_ssh_dir(username)

        # 1. 检查authorized_keys文件是否存在且非空
        check_cmd = f"test -s {ssh_dir}/authorized_keys && echo 'configured' || echo 'not_configured'"
        result = self.execute_on_host(host, check_cmd, sudo=False, username=username,
                                       password=node.password if node and hasattr(node, 'password') else None)

        if not result.get("success") or "not_configured" in result.get("stdout", ""):
            return False, "authorized_keys文件不存在或为空"

        # 2. 检查私钥是否存在
        key_check_cmd = f"test -f {ssh_dir}/id_rsa && echo 'exists' || echo 'not_exists'"
        key_result = self.execute_on_host(host, key_check_cmd, sudo=False, username=username,
                                           password=node.password if node and hasattr(node, 'password') else None)

        if not key_result.get("success") or "not_exists" in key_result.get("stdout", ""):
            return False, "SSH私钥不存在"

        # 3. 获取集群中其他节点列表
        other_hosts = []
        if self.config and hasattr(self.config, 'nodes'):
            for node_item in self.config.nodes:
                node_ip = node_item.ip if hasattr(node_item, 'ip') else None
                if node_ip and node_ip != host:
                    other_hosts.append(node_ip)

        # 如果没有其他节点（单机），只检查文件配置
        if not other_hosts:
            return True, "单机环境，SSH免密文件已配置"

        # 4. 实际验证SSH免密登录（尝试连接到其他节点）
        # 使用 BatchMode=yes 确保不提示输入密码
        # 使用 ConnectTimeout=5 避免长时间等待
        success_count = 0
        failed_hosts = []

        for target_host in other_hosts[:3]:  # 只测试前3个节点，避免耗时过长
            # 获取目标节点的用户名
            target_node = self._get_node_config(target_host)
            target_username = target_node.username if target_node and hasattr(target_node, 'username') else 'ubuntu'

            test_cmd = (
                f"ssh -o BatchMode=yes -o StrictHostKeyChecking=no "
                f"-o ConnectTimeout=5 -o PasswordAuthentication=no "
                f"{target_username}@{target_host} 'echo ok' 2>/dev/null"
            )
            test_result = self.execute_on_host(host, test_cmd, sudo=False, username=username,
                                               password=node.password if node and hasattr(node, 'password') else None)

            if test_result.get("success") and "ok" in test_result.get("stdout", ""):
                success_count += 1
            else:
                failed_hosts.append(target_host)

        # 5. 判断结果
        if success_count > 0:
            return True, f"SSH免密已验证（成功连接{success_count}个节点）"
        elif failed_hosts:
            return False, f"SSH免密验证失败，无法连接到: {failed_hosts[:3]}"
        else:
            return False, "SSH免密未配置"

    def execute(self, hosts: List[str]) -> StepResult:
        """执行SSH免密配置"""
        results = {}

        # 1. 在所有节点生成SSH密钥对
        self.logger.info("生成SSH密钥对...")
        for host in hosts:
            node = self._get_node_config(host)
            username = node.username if node and hasattr(node, 'username') else 'ubuntu'
            password = node.password if node and hasattr(node, 'password') else None
            ssh_dir = self._get_ssh_dir(username)

            # 检查并生成密钥
            check_cmd = f'test -f {ssh_dir}/id_rsa && echo exists || echo not_exists'
            result = self.execute_on_host(host, check_cmd, username=username, password=password)

            if 'not_exists' in result.get('stdout', ''):
                # 确保.ssh目录存在
                mkdir_cmd = f'mkdir -p {ssh_dir}'
                self.execute_on_host(host, mkdir_cmd, username=username, password=password)
                gen_cmd = f'ssh-keygen -t rsa -N "" -f {ssh_dir}/id_rsa'
                self.execute_on_host(host, gen_cmd, username=username, password=password)

            # 确保公钥存在
            ensure_pubkey_cmd = f'test -f {ssh_dir}/id_rsa.pub || ssh-keygen -y -f {ssh_dir}/id_rsa > {ssh_dir}/id_rsa.pub'
            self.execute_on_host(host, ensure_pubkey_cmd, username=username, password=password)

            # 设置权限
            chmod_cmd = f'chmod 700 {ssh_dir} && chmod 600 {ssh_dir}/id_rsa'
            self.execute_on_host(host, chmod_cmd, username=username, password=password)

        # 2. 收集所有节点的公钥
        self.logger.info("收集公钥...")
        all_pubkeys = []

        for host in hosts:
            node = self._get_node_config(host)
            username = node.username if node and hasattr(node, 'username') else 'ubuntu'
            password = node.password if node and hasattr(node, 'password') else None
            ssh_dir = self._get_ssh_dir(username)

            get_pubkey_cmd = f"cat {ssh_dir}/id_rsa.pub"
            result = self.execute_on_host(host, get_pubkey_cmd, username=username, password=password)
            if result["success"] and result["stdout"].strip():
                all_pubkeys.append(result["stdout"].strip())

        # 3. 将所有公钥分发到所有节点
        self.logger.info("分发公钥到所有节点...")

        for host in hosts:
            node = self._get_node_config(host)
            username = node.username if node and hasattr(node, 'username') else 'ubuntu'
            password = node.password if node and hasattr(node, 'password') else None
            ssh_dir = self._get_ssh_dir(username)

            # 清空并重建authorized_keys
            self.execute_on_host(host, f'rm -f {ssh_dir}/authorized_keys', username=username, password=password)

            for pubkey in all_pubkeys:
                add_cmd = f'echo "{pubkey}" >> {ssh_dir}/authorized_keys'
                self.execute_on_host(host, add_cmd, username=username, password=password)

            self.execute_on_host(host, f'chmod 600 {ssh_dir}/authorized_keys', username=username, password=password)
            results[host] = {"success": True}

        # 4. 配置ssh客户端（用户级别）
        self.logger.info("配置SSH客户端...")
        for host in hosts:
            node = self._get_node_config(host)
            username = node.username if node and hasattr(node, 'username') else 'ubuntu'
            password = node.password if node and hasattr(node, 'password') else None
            ssh_dir = self._get_ssh_dir(username)

            # 创建config文件
            config_cmd = f'''mkdir -p {ssh_dir} && echo "StrictHostKeyChecking no" > {ssh_dir}/config && chmod 600 {ssh_dir}/config'''
            self.execute_on_host(host, config_cmd, username=username, password=password)

        # 5. 配置sshd（可选）
        self.logger.info("配置sshd...")
        sshd_config = '''
ClientAliveInterval 60
ClientAliveCountMax 3
MaxStartups 512
'''
        for host in hosts:
            node = self._get_node_config(host)
            username = node.username if node and hasattr(node, 'username') else 'ubuntu'
            password = node.password if node and hasattr(node, 'password') else None

            sshd_cmd = f'''grep -q "ClientAliveInterval" /etc/ssh/sshd_config || echo "{sshd_config}" >> /etc/ssh/sshd_config'''
            self.execute_on_host(host, sshd_cmd, sudo=True, username=username, password=password)

        # 6. 验证
        success_count = sum(1 for r in results.values() if r.get("success"))

        return StepResult(
            step_id=self.step_id,
            step_name=self.step_name,
            status=StepStatus.SUCCESS if success_count == len(hosts) else StepStatus.FAILED,
            message=f"SSH免密配置完成，成功: {success_count}/{len(hosts)}",
            host_results=results
        )

    def post_check(self, hosts: List[str]) -> bool:
        """验证SSH配置"""
        all_success = True
        for host in hosts:
            node = self._get_node_config(host)
            username = node.username if node and hasattr(node, 'username') else 'ubuntu'
            ssh_dir = self._get_ssh_dir(username)

            # 检查authorized_keys是否存在且权限正确
            cmd = f"test -f {ssh_dir}/authorized_keys && stat -c '%a' {ssh_dir}/authorized_keys | grep -q '600'"
            result = self.execute_on_host(host, cmd, sudo=False, username=username,
                                          password=node.password if node and hasattr(node, 'password') else None)
            if not result.get("success"):
                all_success = False
        return all_success
