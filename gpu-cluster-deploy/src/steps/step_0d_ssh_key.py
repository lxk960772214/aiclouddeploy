"""
步骤0d: 设置SSH免密登录

执行顺序要求：
1. 用登录用户连接节点
2. 如果部署用户 ≠ 登录用户，先创建部署用户并配置 sudo 免密
3. 为指定用户配置 SSH 免密
"""

import os
import base64
from typing import List, Dict, Optional
from src.steps.base import BaseStep, StepResult, StepStatus


class SSHKeySetup(BaseStep):
    """设置SSH免密登录"""

    step_id = "0d"
    step_name = "设置SSH免密登录"
    step_description = "配置节点间SSH免密登录"
    requires_sudo = True
    supports_batch = False  # 需要逐个节点处理密钥交换

    def _get_ssh_dir(self, username: str) -> str:
        """获取用户SSH目录路径"""
        if username == "root":
            return "/root/.ssh"
        return f"/home/{username}/.ssh"

    def _get_login_user(self, host: str) -> str:
        """获取登录用户（必须指定）"""
        node = self._get_node_config(host)
        if node and node.username:
            return node.username
        # 如果没有指定，返回空字符串（会在验证时报错）
        return ""

    def _get_deploy_user(self, host: str) -> str:
        """
        获取部署用户

        优先级:
        1. cluster.deploy_user
        2. nodes.username (登录用户)
        """
        # 优先使用集群级别的部署用户
        if self.config and hasattr(self.config, 'deploy_user') and self.config.deploy_user:
            return self.config.deploy_user

        # 否则使用登录用户
        return self._get_login_user(host)

    def _get_ssh_users(self, host: str) -> List[str]:
        """
        获取需要配置免密的用户列表

        优先级:
        1. 如果配置了 ssh_key.users → 使用配置的列表
        2. 否则使用 deploy_user
        3. 都没有 → 报错
        """
        # 1. 如果指定了用户列表
        if self.config and hasattr(self.config, 'ssh_key') and self.config.ssh_key:
            if self.config.ssh_key.enabled and self.config.ssh_key.users:
                return self.config.ssh_key.users

        # 2. 使用 deploy_user
        deploy_user = self._get_deploy_user(host)
        if deploy_user:
            return [deploy_user]

        # 3. 都没有 → 报错
        raise ValueError(
            f"节点 {host}: 未指定 ssh_key.users 也无法确定 deploy_user，"
            "请在配置中设置 ssh_key.users 或 cluster.deploy_user"
        )

    def _check_passwordless_supported(self, host: str, username: str) -> bool:
        """
        检测用户是否支持免密登录

        通过检查是否有私钥和 authorized_keys 来判断
        """
        login_user = self._get_login_user(host)
        ssh_dir = self._get_ssh_dir(username)

        # 检查私钥和 authorized_keys 是否存在
        check_cmd = f"test -f {ssh_dir}/id_rsa && test -s {ssh_dir}/authorized_keys && echo 'supported' || echo 'not_supported'"
        result = self.execute_on_host(host, check_cmd, sudo=True, use_login_user=True)

        return "supported" in result.get("stdout", "")

    def _get_node_auth(self, host: str) -> tuple:
        """获取节点认证信息"""
        node = self._get_node_config(host)
        if node:
            username = node.username if hasattr(node, 'username') and node.username else None
            password = node.password if hasattr(node, 'password') else None
            private_key = node.private_key if hasattr(node, 'private_key') else None
            return username, password, private_key
        return None, None, None

    def is_configured(self, host: str) -> tuple:
        """
        检查SSH免密登录是否已配置

        Args:
            host: 主机地址

        Returns:
            tuple[bool, str]: (是否已配置, 检查详情)
        """
        users = self._get_ssh_users(host)

        # 如果不需要配置免密
        if not users:
            return True, "部署用户已支持免密或已配置"

        login_user = self._get_login_user(host)

        # 检查每个用户
        for username in users:
            ssh_dir = self._get_ssh_dir(username)

            # 1. 检查authorized_keys文件是否存在且非空
            check_cmd = f"test -s {ssh_dir}/authorized_keys && echo 'configured' || echo 'not_configured'"
            result = self.execute_on_host(host, check_cmd, sudo=True, use_login_user=True)

            if not result.get("success") or "not_configured" in result.get("stdout", ""):
                return False, f"用户 {username}: authorized_keys文件不存在或为空"

            # 2. 检查私钥是否存在
            key_check_cmd = f"test -f {ssh_dir}/id_rsa && echo 'exists' || echo 'not_exists'"
            key_result = self.execute_on_host(host, key_check_cmd, sudo=True, use_login_user=True)

            if not key_result.get("success") or "not_exists" in key_result.get("stdout", ""):
                return False, f"用户 {username}: SSH私钥不存在"

        # 3. 获取集群中其他节点列表
        other_hosts = []
        if self.config and hasattr(self.config, 'nodes'):
            for node_item in self.config.nodes:
                node_ip = node_item.ip if hasattr(node_item, 'ip') else None
                if node_ip and node_ip != host:
                    other_hosts.append(node_ip)

        # 如果没有其他节点（单机），只检查文件配置
        if not other_hosts:
            return True, f"单机环境，{len(users)} 个用户的SSH免密文件已配置"

        # 4. 实际验证SSH免密登录（尝试连接到其他节点）
        success_count = 0
        failed_hosts = []

        # 只测试第一个用户和前3个节点
        test_username = users[0]
        for target_host in other_hosts[:3]:
            test_cmd = (
                f"sudo -u {test_username} ssh -o BatchMode=yes -o StrictHostKeyChecking=no "
                f"-o ConnectTimeout=5 -o PasswordAuthentication=no "
                f"{test_username}@{target_host} 'echo ok' 2>/dev/null"
            )
            test_result = self.execute_on_host(host, test_cmd, sudo=True, use_login_user=True)

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

    def _create_deploy_user_if_needed(self, hosts: List[str]) -> Dict[str, bool]:
        """
        如果部署用户不同于登录用户，创建部署用户并配置 sudo 免密

        Returns:
            每个主机的创建结果
        """
        results = {}

        for host in hosts:
            login_user = self._get_login_user(host)
            deploy_user = self._get_deploy_user(host)

            # 如果部署用户就是登录用户，跳过
            if deploy_user == login_user:
                results[host] = True
                continue

            self.logger.info(f"[{host}] 创建部署用户 '{deploy_user}' (登录用户: '{login_user}')")

            # 检查用户是否存在
            check_cmd = f"id {deploy_user} 2>/dev/null && echo 'exists' || echo 'not_exists'"
            result = self.execute_on_host(host, check_cmd, sudo=True, use_login_user=True)

            if 'not_exists' in result.get('stdout', ''):
                # 创建用户
                create_cmd = f"useradd -m -s /bin/bash {deploy_user}"
                create_result = self.execute_on_host(host, create_cmd, sudo=True, use_login_user=True)
                if not create_result.get("success"):
                    results[host] = False
                    continue

            # 如果不是 root，配置 sudo 免密
            if deploy_user != "root":
                sudoers_file = f"/etc/sudoers.d/{deploy_user}"
                sudoers_cmd = f"echo '{deploy_user} ALL=(ALL) NOPASSWD: ALL' > {sudoers_file} && chmod 440 {sudoers_file}"
                sudoers_result = self.execute_on_host(host, sudoers_cmd, sudo=True, use_login_user=True)
                if not sudoers_result.get("success"):
                    results[host] = False
                    continue

            results[host] = True

        return results

    def _get_jumphost_keypair(self) -> tuple:
        """
        获取跳板机的密钥对 (PROXY 模式)

        核心逻辑：
        1. 从跳板机获取/生成密钥对
        2. 确保私钥下载到本地（如果 ssh_manager 还没下载，则手动下载）
        3. 在跳板机上也将公钥添加到自己的 authorized_keys
        4. 返回 (pubkey, private_key_path) 供后续分发到所有节点

        Returns:
            (pubkey, private_key_path) 元组，无跳板机则返回 (None, None)
        """
        if not self.config or not hasattr(self.config, 'jumphost') or not self.config.jumphost:
            return None, None

        jumphost = self.config.jumphost
        if not hasattr(jumphost, 'host') or not jumphost.host:
            return None, None

        # 获取跳板机认证信息
        jh_user = "root"
        jh_password = None
        jh_port = 22

        if hasattr(jumphost, 'auth') and jumphost.auth:
            jh_user = getattr(jumphost.auth, 'username', 'root') or 'root'
            jh_password = getattr(jumphost.auth, 'password', None)
            jh_port = getattr(jumphost, 'port', 22) or 22
        elif hasattr(jumphost, 'username'):
            jh_user = jumphost.username or 'root'
            jh_password = getattr(jumphost, 'password', None)
            jh_port = getattr(jumphost, 'port', 22) or 22

        # 获取/生成公钥
        pubkey = None
        key_generated = False
        try:
            # 先尝试读取已有公钥
            result = self.ssh_manager.execute_on_jumphost(
                jumphost.host, jh_port, jh_user, jh_password,
                "cat ~/.ssh/id_rsa.pub 2>/dev/null"
            )
            if result.success and result.stdout.strip():
                pubkey = result.stdout.strip()
                self.logger.info("[跳板机] 获取已有公钥成功")
            else:
                # 没有密钥，在跳板机上生成
                self.logger.info("[跳板机] 未找到密钥，生成新密钥对...")
                gen_result = self.ssh_manager.execute_on_jumphost(
                    jumphost.host, jh_port, jh_user, jh_password,
                    "ssh-keygen -q -t rsa -N '' -f ~/.ssh/id_rsa && cat ~/.ssh/id_rsa.pub"
                )
                if gen_result.success and gen_result.stdout.strip():
                    pubkey = gen_result.stdout.strip()
                    key_generated = True
                    self.logger.info("[跳板机] 密钥对生成成功")
                else:
                    self.logger.warning(f"[跳板机] 生成密钥失败: {gen_result.stderr if gen_result else 'unknown'}")
                    return None, None
        except Exception as e:
            self.logger.warning(f"[跳板机] 获取/生成公钥失败: {e}")
            return None, None

        if not pubkey:
            return None, None

        # 在跳板机上确保公钥添加到自己的 authorized_keys
        try:
            self.ssh_manager.execute_on_jumphost(
                jumphost.host, jh_port, jh_user, jh_password,
                "mkdir -p ~/.ssh && chmod 700 ~/.ssh && "
                "grep -qF '" + pubkey + "' ~/.ssh/authorized_keys 2>/dev/null || "
                "echo '" + pubkey + "' >> ~/.ssh/authorized_keys && "
                "chmod 600 ~/.ssh/authorized_keys"
            )
            self.logger.info("[跳板机] 公钥已添加到 authorized_keys")
        except Exception as e:
            self.logger.warning(f"[跳板机] 添加公钥到 authorized_keys 失败: {e}")

        # 获取私钥本地路径
        # 如果 ssh_manager 已经下载了私钥（_detect_jumphost_key_for_nodes），直接使用
        # 否则需要手动下载
        private_key_path = getattr(self.ssh_manager, '_default_private_key', None)
        temp_dir_exists = getattr(self.ssh_manager, '_jumphost_key_temp_dir', None) is not None

        if private_key_path and os.path.isfile(private_key_path):
            self.logger.info(f"[跳板机] 使用已下载的私钥: {private_key_path}")
        elif self.ssh_manager and hasattr(self.ssh_manager, 'jump_client') and self.ssh_manager.jump_client:
            # 手动下载跳板机私钥到本地
            try:
                import tempfile
                sftp = self.ssh_manager.jump_client.open_sftp()
                temp_dir = tempfile.mkdtemp(prefix="gpu_deploy_jumphost_key_")
                local_key_path = os.path.join(temp_dir, "id_rsa")
                sftp.get(f"/root/.ssh/id_rsa" if jh_user == "root" else f"/home/{jh_user}/.ssh/id_rsa", local_key_path)
                sftp.close()
                os.chmod(local_key_path, 0o600)

                # 更新 ssh_manager 的默认私钥路径
                self.ssh_manager._default_private_key = local_key_path
                self.ssh_manager._jumphost_key_temp_dir = temp_dir
                private_key_path = local_key_path
                self.logger.info(f"[跳板机] 手动下载私钥到本地: {local_key_path}")
            except Exception as e:
                self.logger.warning(f"[跳板机] 下载私钥失败: {e}")
                private_key_path = None

        return pubkey, private_key_path

    def _get_local_keypair(self) -> tuple:
        """
        获取本机密钥对 (DIRECT 模式)
        无跳板机时，本机约等于跳板机，用本机密钥分发到所有节点。

        Returns:
            (pubkey, private_key_path) 元组，无可用密钥则返回 (None, None)
        """
        key_dir = os.path.expanduser("~/.ssh")
        key_filenames = ["id_rsa", "id_ed25519", "id_ecdsa"]

        private_key_path = None
        for key_name in key_filenames:
            key_path = os.path.join(key_dir, key_name)
            if os.path.isfile(key_path):
                private_key_path = key_path
                break

        if not private_key_path:
            self.logger.warning("[本机] 未找到可用私钥 (~/.ssh/id_rsa 等)")
            return None, None

        # 读取公钥
        pub_key_path = private_key_path + ".pub"
        pubkey = None
        if os.path.isfile(pub_key_path):
            with open(pub_key_path, 'r') as f:
                for line in f:
                    if line.startswith('ssh-'):
                        pubkey = line.strip()
                        break

        if not pubkey:
            self.logger.warning(f"[本机] 公钥文件无效或不存在: {pub_key_path}")
            return None, None

        self.logger.info(f"[本机] 获取密钥对成功: {private_key_path}")
        return pubkey, private_key_path

    def execute(self, hosts: List[str]) -> StepResult:
        """执行SSH免密配置"""
        results = {}

        # 0. 验证登录用户是否配置
        for host in hosts:
            login_user = self._get_login_user(host)
            if not login_user:
                return StepResult(
                    step_id=self.step_id,
                    step_name=self.step_name,
                    status=StepStatus.FAILED,
                    message=f"节点 {host} 未指定登录用户 (username)，必须在配置中指定"
                )

        # 1. 如果需要，创建部署用户并配置 sudo 免密
        deploy_user_results = self._create_deploy_user_if_needed(hosts)
        failed_hosts = [h for h, success in deploy_user_results.items() if not success]
        if failed_hosts:
            return StepResult(
                step_id=self.step_id,
                step_name=self.step_name,
                status=StepStatus.FAILED,
                message=f"创建部署用户失败: {failed_hosts}"
            )

        # 2. 获取需要配置免密的用户列表
        # 使用第一个主机的配置（假设所有主机配置相同）
        users = self._get_ssh_users(hosts[0] if hosts else "")

        if not users:
            self.logger.info("不需要配置SSH免密（部署用户已支持免密）")
            return StepResult(
                step_id=self.step_id,
                step_name=self.step_name,
                status=StepStatus.SUCCESS,
                message="部署用户已支持免密，无需配置"
            )

        self.logger.info(f"为 {len(users)} 个用户配置SSH免密: {users}")

        # 存储每个用户的公钥: {username: [pubkey1, pubkey2, ...]}
        all_pubkeys_by_user: Dict[str, List[str]] = {user: [] for user in users}

        # 2.5 获取源密钥对
        # PROXY 模式 → 跳板机密钥；DIRECT 模式 → 本机密钥
        # 源密钥会分发到所有节点，使所有节点共享同一份密钥对实现免密互访
        is_proxy_mode = self.ssh_manager and getattr(self.ssh_manager, 'is_proxy_mode', False)

        if is_proxy_mode:
            source_pubkey, source_private_key_path = self._get_jumphost_keypair()
        else:
            source_pubkey, source_private_key_path = self._get_local_keypair()

        use_source_key = (
            source_private_key_path
            and os.path.isfile(source_private_key_path)
            and source_pubkey
        )

        if source_pubkey:
            self.logger.info("获取源公钥成功，将添加到所有节点的 authorized_keys")
            for username in users:
                all_pubkeys_by_user[username].append(source_pubkey)

        # 3. 在所有节点为所有用户配置SSH密钥
        if use_source_key:
            # 有源密钥 → 直接复用源密钥对，不在工作节点重新生成
            source_name = "跳板机" if is_proxy_mode else "本机"
            self.logger.info(f"使用{source_name}密钥，直接配置到所有节点（不重新生成密钥）...")

            # 读取源私钥内容
            with open(source_private_key_path, 'r') as f:
                private_key_content = f.read()

            # Base64编码，避免shell转义问题
            private_key_b64 = base64.b64encode(private_key_content.encode()).decode()

            for host in hosts:
                for username in users:
                    ssh_dir = self._get_ssh_dir(username)

                    # 检查用户是否存在
                    check_user_cmd = f"id {username} 2>/dev/null && echo 'exists' || echo 'not_exists'"
                    user_result = self.execute_on_host(host, check_user_cmd, sudo=True, use_login_user=True)

                    if 'not_exists' in user_result.get('stdout', ''):
                        self.logger.warning(f"[{host}] 用户 {username} 不存在，跳过")
                        continue

                    # 确保.ssh目录存在
                    mkdir_cmd = f'mkdir -p {ssh_dir} && chown {username}:{username} {ssh_dir} && chmod 700 {ssh_dir}'
                    self.execute_on_host(host, mkdir_cmd, sudo=True, use_login_user=True)

                    # 写入私钥（使用base64避免shell转义问题）
                    write_key_cmd = f"echo '{private_key_b64}' | base64 -d > {ssh_dir}/id_rsa"
                    self.execute_on_host(host, write_key_cmd, sudo=True, use_login_user=True)

                    # 写入公钥
                    write_pubkey_cmd = f'printf "%s\\n" "{source_pubkey}" > {ssh_dir}/id_rsa.pub'
                    self.execute_on_host(host, write_pubkey_cmd, sudo=True, use_login_user=True)

                    # 设置权限
                    chmod_cmd = f'chown -R {username}:{username} {ssh_dir} && chmod 700 {ssh_dir} && chmod 600 {ssh_dir}/id_rsa && chmod 644 {ssh_dir}/id_rsa.pub'
                    self.execute_on_host(host, chmod_cmd, sudo=True, use_login_user=True)

        else:
            # 无源密钥 → 在每个节点生成新密钥对
            self.logger.info("生成SSH密钥对...")
            for host in hosts:
                for username in users:
                    ssh_dir = self._get_ssh_dir(username)

                    # 检查用户是否存在
                    check_user_cmd = f"id {username} 2>/dev/null && echo 'exists' || echo 'not_exists'"
                    user_result = self.execute_on_host(host, check_user_cmd, sudo=True, use_login_user=True)

                    if 'not_exists' in user_result.get('stdout', ''):
                        self.logger.warning(f"[{host}] 用户 {username} 不存在，跳过")
                        continue

                    # 检查并生成密钥
                    check_cmd = f'test -f {ssh_dir}/id_rsa && echo exists || echo not_exists'
                    result = self.execute_on_host(host, check_cmd, sudo=True, use_login_user=True)

                    if 'not_exists' in result.get('stdout', ''):
                        # 确保.ssh目录存在
                        mkdir_cmd = f'mkdir -p {ssh_dir} && chown {username}:{username} {ssh_dir}'
                        self.execute_on_host(host, mkdir_cmd, sudo=True, use_login_user=True)
                        # 使用 -q 静默模式生成密钥，避免输出 fingerprint 和 randomart
                        gen_cmd = f'su - {username} -c "ssh-keygen -q -t rsa -N \'\' -f {ssh_dir}/id_rsa"'
                        self.execute_on_host(host, gen_cmd, sudo=True, use_login_user=True)

                    # 确保公钥存在（从私钥提取），静默模式避免输出额外信息
                    ensure_pubkey_cmd = f'test -f {ssh_dir}/id_rsa.pub || (ssh-keygen -y -f {ssh_dir}/id_rsa 2>/dev/null > {ssh_dir}/id_rsa.pub)'
                    self.execute_on_host(host, ensure_pubkey_cmd, sudo=True, use_login_user=True)

                    # 设置权限
                    chmod_cmd = f'chown -R {username}:{username} {ssh_dir} && chmod 700 {ssh_dir} && chmod 600 {ssh_dir}/id_rsa'
                    self.execute_on_host(host, chmod_cmd, sudo=True, use_login_user=True)

        # 4. 收集所有节点所有用户的公钥
        if use_source_key:
            # 使用源密钥时，所有节点使用相同的公钥，已在阶段2.5收集，跳过此阶段
            self.logger.info("使用源密钥，跳过公钥收集（所有节点使用相同密钥）")
        else:
            self.logger.info("收集公钥...")
            for host in hosts:
                for username in users:
                    ssh_dir = self._get_ssh_dir(username)

                    # 只获取以ssh-开头的有效公钥行，过滤掉ssh-keygen的输出
                    get_pubkey_cmd = f"grep '^ssh-' {ssh_dir}/id_rsa.pub 2>/dev/null | head -1"
                    result = self.execute_on_host(host, get_pubkey_cmd, sudo=True, use_login_user=True)
                    if result["success"] and result["stdout"].strip():
                        pubkey = result["stdout"].strip()
                        # 验证公钥格式（必须是ssh-rsa或ssh-ed25519开头）
                        if pubkey.startswith('ssh-') and pubkey not in all_pubkeys_by_user[username]:
                            all_pubkeys_by_user[username].append(pubkey)

        # 5. 将公钥分发到所有节点的对应用户
        self.logger.info("分发公钥到所有节点...")

        for host in hosts:
            for username in users:
                ssh_dir = self._get_ssh_dir(username)

                # 检查用户是否存在
                check_user_cmd = f"id {username} 2>/dev/null && echo 'exists' || echo 'not_exists'"
                user_result = self.execute_on_host(host, check_user_cmd, sudo=True, use_login_user=True)

                if 'not_exists' in user_result.get('stdout', ''):
                    continue

                # 确保.ssh目录存在
                mkdir_cmd = f'mkdir -p {ssh_dir} && chown {username}:{username} {ssh_dir} && chmod 700 {ssh_dir}'
                self.execute_on_host(host, mkdir_cmd, sudo=True, use_login_user=True)

                # 使用临时文件写入，避免重复追加问题
                # 1. 先创建临时文件
                temp_auth_keys = f"{ssh_dir}/authorized_keys.tmp"
                self.execute_on_host(host, f'rm -f {temp_auth_keys}', sudo=True, use_login_user=True)

                # 2. 写入所有公钥到临时文件（只写入有效的ssh-开头的公钥）
                for pubkey in all_pubkeys_by_user[username]:
                    # 验证公钥格式后再写入
                    if pubkey.startswith('ssh-'):
                        # 使用printf避免echo的换行问题
                        add_cmd = f'printf "%s\\n" "{pubkey}" >> {temp_auth_keys}'
                        self.execute_on_host(host, add_cmd, sudo=True, use_login_user=True)

                # 3. 去重、过滤无效行，并移动到正式文件
                dedup_cmd = f"grep '^ssh-' {temp_auth_keys} | sort -u > {ssh_dir}/authorized_keys && rm -f {temp_auth_keys}"
                self.execute_on_host(host, dedup_cmd, sudo=True, use_login_user=True)

                self.execute_on_host(host, f'chown {username}:{username} {ssh_dir}/authorized_keys && chmod 600 {ssh_dir}/authorized_keys', sudo=True, use_login_user=True)

            results[host] = {"success": True}

        # 6. 配置ssh客户端（用户级别）
        self.logger.info("配置SSH客户端...")
        for host in hosts:
            for username in users:
                ssh_dir = self._get_ssh_dir(username)

                # 检查用户是否存在
                check_user_cmd = f"id {username} 2>/dev/null && echo 'exists' || echo 'not_exists'"
                user_result = self.execute_on_host(host, check_user_cmd, sudo=True, use_login_user=True)

                if 'not_exists' in user_result.get('stdout', ''):
                    continue

                # 创建config文件
                config_cmd = f'''mkdir -p {ssh_dir} && echo "StrictHostKeyChecking no" > {ssh_dir}/config && chown {username}:{username} {ssh_dir}/config && chmod 600 {ssh_dir}/config'''
                self.execute_on_host(host, config_cmd, sudo=True, use_login_user=True)

        # 7. 配置sshd（可选，只需执行一次）
        self.logger.info("配置sshd...")
        sshd_config = '''
ClientAliveInterval 60
ClientAliveCountMax 3
MaxStartups 512
'''
        for host in hosts:
            sshd_cmd = f'''grep -q "ClientAliveInterval" /etc/ssh/sshd_config || echo "{sshd_config}" >> /etc/ssh/sshd_config'''
            self.execute_on_host(host, sshd_cmd, sudo=True, use_login_user=True)

        # 8. 验证
        success_count = sum(1 for r in results.values() if r.get("success"))

        return StepResult(
            step_id=self.step_id,
            step_name=self.step_name,
            status=StepStatus.SUCCESS if success_count == len(hosts) else StepStatus.FAILED,
            message=f"SSH免密配置完成，用户: {users}，成功: {success_count}/{len(hosts)}",
            host_results=results
        )

    def post_check(self, hosts: List[str]) -> bool:
        """验证SSH配置"""
        users = self._get_ssh_users(hosts[0] if hosts else "")
        if not users:
            return True

        all_success = True

        for host in hosts:
            for username in users:
                ssh_dir = self._get_ssh_dir(username)

                # 检查authorized_keys是否存在且权限正确
                cmd = f"test -f {ssh_dir}/authorized_keys && stat -c '%a' {ssh_dir}/authorized_keys | grep -q '600'"
                result = self.execute_on_host(host, cmd, sudo=True, use_login_user=True)
                if not result.get("success"):
                    all_success = False
        return all_success
