"""
步骤09: 设置主机名和hosts绑定 + 节点间互相免密

职责:
1. 设置各节点主机名
2. 配置 /etc/hosts 使节点间可解析彼此主机名
3. 收集各节点公钥并互相添加到 authorized_keys，实现节点间用主机名免密跳转

注意:
- PROXY 模式下不添加 jumphost 到 /etc/hosts（节点通过IP连接跳板机，无需解析主机名）
- DIRECT 模式下添加控制机到 /etc/hosts（本机充当跳板，节点需解析控制机主机名）
"""

from typing import List, Dict
from src.steps.base import BaseStep, StepResult, StepStatus


class HostnameHosts(BaseStep):
    """设置主机名和hosts绑定"""

    step_id = "09"
    step_name = "设置主机名和hosts绑定"
    step_description = "设置节点主机名、同步hosts文件、配置节点间互相免密"
    requires_sudo = True
    supports_batch = False  # 每个节点配置不同

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _is_proxy_mode(self) -> bool:
        """判断是否为 PROXY（跳板机）模式"""
        return bool(
            self.ssh_manager
            and getattr(self.ssh_manager, 'is_proxy_mode', False)
        )

    def _get_ssh_dir(self, username: str) -> str:
        """获取用户 .ssh 目录路径"""
        if username == "root":
            return "/root/.ssh"
        return f"/home/{username}/.ssh"

    # ------------------------------------------------------------------
    # 主流程
    # ------------------------------------------------------------------

    def execute(self, hosts: List[str]) -> StepResult:
        """执行主机名、hosts 和互相免密设置"""
        all_results = {}

        # ========== 阶段1: 生成 hosts 条目 ==========
        hosts_entries = []
        for node in self.config.nodes:
            hosts_entries.append(f"{node.ip} {node.hostname}")

        # 仅 DIRECT 模式下添加控制机（本机）到 hosts
        # PROXY 模式下节点通过 IP 连接跳板机，无需解析主机名
        if not self._is_proxy_mode():
            # DIRECT 模式：本机即控制机，节点需要能解析控制机
            # 如果本机 IP 不在节点列表中，则添加
            existing_ips = [e.split()[0] for e in hosts_entries]
            import socket
            try:
                local_ip = socket.gethostbyname(socket.gethostname())
                if local_ip not in existing_ips:
                    local_hostname = socket.gethostname()
                    hosts_entries.append(f"{local_ip} {local_hostname}")
                    self.logger.info(f"DIRECT模式，添加控制机hosts条目: {local_ip} {local_hostname}")
            except Exception:
                pass  # 无法获取本机IP则跳过

        hosts_content = "\n".join(hosts_entries)

        # ========== 阶段2: 设置主机名 + 配置 hosts ==========
        for host in hosts:
            # 获取节点信息
            node = None
            for n in self.config.nodes:
                if n.ip == host:
                    node = n
                    break

            if not node:
                all_results[host] = {"success": False, "error": "节点未在配置中"}
                continue

            # 1. 设置主机名
            set_hostname_cmd = f"hostnamectl set-hostname {node.hostname}"
            hostname_result = self.execute_on_host(host, set_hostname_cmd, sudo=True)

            if not hostname_result["success"]:
                all_results[host] = {"success": False, "error": "设置主机名失败"}
                continue

            # 2. 移除127.0.1.1条目中的主机名
            remove_cmd = "sed -i '/127.0.1.1/d' /etc/hosts"
            self.execute_on_host(host, remove_cmd, sudo=True)

            # 3. PROXY 模式下清理旧版残留的 jumphost 条目
            #    旧版代码在 PROXY 模式也会添加 jumphost 到 /etc/hosts，新版不再添加
            #    需要清理掉这些旧条目
            if self._is_proxy_mode() and self.config and hasattr(self.config, 'jumphost') and self.config.jumphost:
                jh = self.config.jumphost
                jh_ip = getattr(jh, 'host', None)
                # 删除以 jumphost IP 开头的行
                if jh_ip:
                    jh_ip_escaped = jh_ip.replace('.', '\\.')
                    remove_jh_cmd = f"sed -i '/^{jh_ip_escaped}[[:space:]]/d' /etc/hosts"
                    self.execute_on_host(host, remove_jh_cmd, sudo=True)
                # 删除以 "jumphost" 结尾的行（旧版可能用 "jumphost" 作为 hostname）
                remove_jh_name_cmd = "sed -i '/[[:space:]]jumphost$/d' /etc/hosts"
                self.execute_on_host(host, remove_jh_name_cmd, sudo=True)

            # 4. 清理所有待添加条目对应的旧记录（包括节点改名后的旧hostname）
            for entry in hosts_entries:
                entry_ip, entry_hostname = entry.split(None, 1)
                remove_ip_cmd = f"sed -i '/^{entry_ip}[[:space:]]/d' /etc/hosts"
                self.execute_on_host(host, remove_ip_cmd, sudo=True)
                remove_name_cmd = f"sed -i '/[[:space:]]{entry_hostname}$/d' /etc/hosts"
                self.execute_on_host(host, remove_name_cmd, sudo=True)

            # 5. 添加hosts条目（逐条添加）
            add_success = True
            for entry in hosts_entries:
                entry_ip, entry_hostname = entry.split(None, 1)
                # 用 bash -c 包裹，避免管道和 sudo 嵌套问题
                add_cmd = f"bash -c 'echo \"{entry}\" >> /etc/hosts'"
                add_result = self.execute_on_host(host, add_cmd, sudo=True)
                if not add_result["success"]:
                    self.logger.warning(f"[{host}] 添加hosts条目失败: {entry}")
                    add_success = False
                    # 不 break，继续添加剩余条目

            # 6. 验证所有条目已写入
            if add_success:
                for entry in hosts_entries:
                    entry_ip, entry_hostname = entry.split(None, 1)
                    verify_cmd = f"grep -q '{entry_ip}.*{entry_hostname}' /etc/hosts"
                    verify_result = self.execute_on_host(host, verify_cmd, sudo=False)
                    if not verify_result.get("success"):
                        self.logger.warning(f"[{host}] hosts验证失败，条目未写入: {entry}")
                        add_success = False

            all_results[host] = {
                "success": add_success,
                "hostname": node.hostname
            }

        hosts_ok = sum(1 for r in all_results.values() if r.get("success"))
        if hosts_ok != len(hosts):
            return StepResult(
                step_id=self.step_id,
                step_name=self.step_name,
                status=StepStatus.FAILED,
                message=f"主机名和hosts设置失败，成功: {hosts_ok}/{len(hosts)}",
                details={"hosts_content": hosts_content},
                host_results=all_results
            )

        # ========== 阶段3: 节点间互相免密 ==========
        self.logger.info("开始配置节点间互相免密...")
        cross_ssh_result = self._setup_cross_ssh(hosts)
        self.logger.info(f"节点间互相免密结果: {cross_ssh_result}")

        return StepResult(
            step_id=self.step_id,
            step_name=self.step_name,
            status=StepStatus.SUCCESS,
            message=f"主机名、hosts和互相免密设置完成，成功: {hosts_ok}/{len(hosts)}",
            details={"hosts_content": hosts_content, "cross_ssh": cross_ssh_result},
            host_results=all_results
        )

    # ------------------------------------------------------------------
    # 节点间互相免密
    # ------------------------------------------------------------------

    def _setup_cross_ssh(self, hosts: List[str]) -> Dict[str, str]:
        """
        配置节点间互相免密登录

        流程:
        1. 在每个节点上确保部署用户有 SSH 密钥对
        2. 收集所有节点部署用户的公钥
        3. 将所有公钥添加到每个节点的 authorized_keys
        4. 配置 SSH 客户端 StrictHostKeyChecking no
        5. 验证节点间可用主机名互相 SSH

        Returns:
            每个主机的配置结果
        """
        results = {}

        # 确定部署用户
        deploy_user = self._get_deploy_user(hosts[0]) if hosts else "root"
        ssh_dir = self._get_ssh_dir(deploy_user)

        # 1. 确保每个节点有密钥对 + 收集公钥
        all_pubkeys = []
        for host in hosts:
            # 确保 .ssh 目录存在
            mkdir_cmd = f"mkdir -p {ssh_dir} && chown {deploy_user}:{deploy_user} {ssh_dir} && chmod 700 {ssh_dir}"
            self.execute_on_host(host, mkdir_cmd, sudo=True)

            # 检查是否已有密钥
            check_cmd = f"test -f {ssh_dir}/id_rsa && echo 'exists' || echo 'not_exists'"
            check_result = self.execute_on_host(host, check_cmd, sudo=True)

            if "not_exists" in check_result.get("stdout", ""):
                # 生成密钥对
                gen_cmd = f'ssh-keygen -q -t rsa -N "" -f {ssh_dir}/id_rsa'
                self.execute_on_host(host, gen_cmd, sudo=True)
                # 设置属主
                chown_cmd = f"chown -R {deploy_user}:{deploy_user} {ssh_dir}"
                self.execute_on_host(host, chown_cmd, sudo=True)
                self.logger.info(f"[{host}] 生成新SSH密钥对")

            # 确保公钥存在
            ensure_pubkey_cmd = f"test -f {ssh_dir}/id_rsa.pub || (ssh-keygen -y -f {ssh_dir}/id_rsa > {ssh_dir}/id_rsa.pub 2>/dev/null && chown {deploy_user}:{deploy_user} {ssh_dir}/id_rsa.pub)"
            self.execute_on_host(host, ensure_pubkey_cmd, sudo=True)

            # 收集公钥
            get_pubkey_cmd = f"cat {ssh_dir}/id_rsa.pub"
            pubkey_result = self.execute_on_host(host, get_pubkey_cmd, sudo=True)
            pubkey = pubkey_result.get("stdout", "").strip()
            if pubkey and pubkey.startswith("ssh-"):
                all_pubkeys.append(pubkey)
                self.logger.info(f"[{host}] 收集公钥成功")
            else:
                self.logger.warning(f"[{host}] 收集公钥失败")

        if not all_pubkeys:
            self.logger.warning("未收集到任何公钥，跳过互相免密配置")
            return {h: "no_pubkey" for h in hosts}

        # 去重
        all_pubkeys = list(dict.fromkeys(all_pubkeys))
        self.logger.info(f"共收集 {len(all_pubkeys)} 个公钥，开始分发...")

        # 2. 将所有公钥添加到每个节点的 authorized_keys
        for host in hosts:
            # 确保 authorized_keys 存在
            touch_cmd = f"touch {ssh_dir}/authorized_keys && chown {deploy_user}:{deploy_user} {ssh_dir}/authorized_keys && chmod 600 {ssh_dir}/authorized_keys"
            self.execute_on_host(host, touch_cmd, sudo=True)

            # 逐条添加公钥（避免重复）
            for pubkey in all_pubkeys:
                # 使用 grep 检查是否已存在，不存在则追加
                # 公钥中的空格和特殊字符需要用 grep -qF 精确匹配
                add_cmd = f"grep -qF '{pubkey}' {ssh_dir}/authorized_keys 2>/dev/null || echo '{pubkey}' >> {ssh_dir}/authorized_keys"
                self.execute_on_host(host, add_cmd, sudo=True)

            # 确保 authorized_keys 权限正确
            chmod_cmd = f"chown {deploy_user}:{deploy_user} {ssh_dir}/authorized_keys && chmod 600 {ssh_dir}/authorized_keys"
            self.execute_on_host(host, chmod_cmd, sudo=True)

            # 3. 配置 SSH 客户端
            config_cmd = (
                f"mkdir -p {ssh_dir} && "
                f"echo 'StrictHostKeyChecking no' > {ssh_dir}/config && "
                f"chown {deploy_user}:{deploy_user} {ssh_dir}/config && "
                f"chmod 600 {ssh_dir}/config"
            )
            self.execute_on_host(host, config_cmd, sudo=True)

            results[host] = "configured"

        # 4. 验证节点间可用主机名互相 SSH
        self.logger.info("验证节点间互相免密...")
        verify_ok = 0
        verify_fail = 0
        for host in hosts:
            node = self._get_node_config(host)
            if not node:
                continue
            # 随机选一个其他节点做验证
            for other_host in hosts:
                if other_host == host:
                    continue
                other_node = self._get_node_config(other_host)
                if not other_node:
                    continue
                # 用主机名 SSH 到对方
                verify_cmd = (
                    f"sudo -u {deploy_user} ssh -o BatchMode=yes "
                    f"-o StrictHostKeyChecking=no -o ConnectTimeout=5 "
                    f"-o PasswordAuthentication=no "
                    f"{deploy_user}@{other_node.hostname} 'hostname' 2>/dev/null"
                )
                verify_result = self.execute_on_host(host, verify_cmd, sudo=True)
                if verify_result.get("success") and other_node.hostname in verify_result.get("stdout", ""):
                    verify_ok += 1
                    self.logger.info(f"[{host}] → {other_node.hostname} 免密验证成功")
                else:
                    verify_fail += 1
                    self.logger.warning(
                        f"[{host}] → {other_node.hostname} 免密验证失败: "
                        f"{verify_result.get('stdout', '')} {verify_result.get('stderr', '')}"
                    )
                # 只验证一个目标节点即可
                break

        self.logger.info(f"免密验证结果: 成功={verify_ok}, 失败={verify_fail}")
        return results

    # ------------------------------------------------------------------
    # 配置检查
    # ------------------------------------------------------------------

    def is_configured(self, host: str) -> tuple:
        """
        检查主机名、hosts 和互相免密是否已配置

        Args:
            host: 主机地址

        Returns:
            tuple[bool, str]: (是否已配置, 检查详情)
        """
        node = self._get_node_config(host)
        if not node:
            return False, "节点未在配置中"

        # 1. 检查主机名
        hostname_result = self.execute_on_host(host, "hostname", sudo=False)
        current_hostname = hostname_result.get("stdout", "").strip()

        if current_hostname != node.hostname:
            return False, f"主机名不匹配: 当前={current_hostname}, 目标={node.hostname}"

        # 2. 检查hosts文件 — 所有节点条目都应存在
        for n in self.config.nodes:
            check_cmd = f"grep -q '{n.hostname}' /etc/hosts && echo 'yes' || echo 'no'"
            check_result = self.execute_on_host(host, check_cmd, sudo=False)
            stdout = check_result.get("stdout", "").strip()
            # 精确匹配，避免 "no" 被误判
            if stdout != "yes":
                return False, f"/etc/hosts 缺少节点条目: {n.hostname}"

        # 3. PROXY 模式下检查 /etc/hosts 不应有 jumphost 残留
        if self._is_proxy_mode():
            jh_check_cmd = "grep -q 'jumphost' /etc/hosts && echo 'yes' || echo 'no'"
            jh_result = self.execute_on_host(host, jh_check_cmd, sudo=False)
            jh_stdout = jh_result.get("stdout", "").strip()
            if jh_stdout == "yes":
                return False, "/etc/hosts 存在旧版 jumphost 残留条目，需要清理"

        # 4. 检查互相免密
        deploy_user = self._get_deploy_user(host)
        ssh_dir = self._get_ssh_dir(deploy_user)

        # 检查 authorized_keys 是否存在且非空
        check_auth_cmd = f"test -s {ssh_dir}/authorized_keys && echo 'yes' || echo 'no'"
        auth_result = self.execute_on_host(host, check_auth_cmd, sudo=True)
        if auth_result.get("stdout", "").strip() != "yes":
            return False, f"用户 {deploy_user} 的 authorized_keys 未配置"

        # 检查私钥是否存在
        check_key_cmd = f"test -f {ssh_dir}/id_rsa && echo 'yes' || echo 'no'"
        key_result = self.execute_on_host(host, check_key_cmd, sudo=True)
        if key_result.get("stdout", "").strip() != "yes":
            return False, f"用户 {deploy_user} 的SSH私钥不存在"

        # 抽检：能否用主机名 SSH 到另一个节点
        other_hosts = [n.ip for n in self.config.nodes if n.ip != host]

        if other_hosts:
            other_node = self._get_node_config(other_hosts[0])
            if other_node:
                verify_cmd = (
                    f"sudo -u {deploy_user} ssh -o BatchMode=yes "
                    f"-o StrictHostKeyChecking=no -o ConnectTimeout=5 "
                    f"-o PasswordAuthentication=no "
                    f"{deploy_user}@{other_node.hostname} 'hostname' 2>/dev/null"
                )
                verify_result = self.execute_on_host(host, verify_cmd, sudo=True)
                if not verify_result.get("success") or other_node.hostname not in verify_result.get("stdout", ""):
                    return False, f"节点间免密未配置（无法 SSH 到 {other_node.hostname}）"

        return True, f"主机名、hosts和互相免密已配置: {node.hostname}"

    def post_check(self, hosts: List[str]) -> bool:
        """验证hosts设置和节点间免密"""
        for host in hosts:
            node = self._get_node_config(host)
            if not node:
                return False

            # 检查主机名和hosts
            cmd = f"hostname && grep '{node.hostname}' /etc/hosts"
            result = self.execute_on_host(host, cmd)
            if not result["success"]:
                return False

        # 抽检节点间免密（至少检查一对）
        deploy_user = self._get_deploy_user(hosts[0]) if hosts else "root"
        checked = False
        for host in hosts:
            for other_host in hosts:
                if other_host == host:
                    continue
                other_node = self._get_node_config(other_host)
                if not other_node:
                    continue
                verify_cmd = (
                    f"sudo -u {deploy_user} ssh -o BatchMode=yes "
                    f"-o StrictHostKeyChecking=no -o ConnectTimeout=5 "
                    f"-o PasswordAuthentication=no "
                    f"{deploy_user}@{other_node.hostname} 'hostname' 2>/dev/null"
                )
                verify_result = self.execute_on_host(host, verify_cmd, sudo=True)
                if not verify_result.get("success") or other_node.hostname not in verify_result.get("stdout", ""):
                    self.logger.warning(f"[{host}] → {other_node.hostname} 免密验证失败")
                    return False
                checked = True
                break  # 只检查一个方向
            if checked:
                break

        return True
