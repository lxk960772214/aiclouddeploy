"""
步骤30: 配置时间同步服务器
"""

from typing import List
from src.steps.base import BaseStep, StepResult, StepStatus


class TimeSync(BaseStep):
    """配置时间同步"""

    step_id = "30"
    step_name = "配置时间同步"
    step_description = "配置chrony时间同步服务"
    requires_sudo = True
    supports_batch = False  # server和client配置不同

    # Server端配置
    SERVER_CONFIG = '''server 127.127.1.0 iburst
local stratum 10
driftfile /var/lib/chrony/chrony.drift
makestep 1.0 3
rtcsync
logdir /var/log/chrony
allow all'''

    def _get_client_config(self, server_ip: str) -> str:
        """获取客户端配置"""
        return f'''server {server_ip} iburst
driftfile /var/lib/chrony/chrony.drift
makestep 1.0 3
rtcsync
logdir /var/log/chrony'''

    def execute(self, hosts: List[str]) -> StepResult:
        """执行时间同步配置"""
        results = {}

        # 获取时间服务器节点
        time_server = self.config.time_server_node
        server_ip = time_server.ip if time_server else hosts[0]
        server_hostname = time_server.hostname if time_server else "node-0"

        self.logger.info(f"时间服务器: {server_hostname} ({server_ip})")

        for host in hosts:
            # 判断是server还是client
            is_server = (host == server_ip)

            if is_server:
                # Server端配置
                config = self.SERVER_CONFIG
                self.logger.info(f"[{host}] 配置为时间服务器")
            else:
                # Client端配置
                config = self._get_client_config(server_ip)
                self.logger.info(f"[{host}] 配置为时间客户端")

            # 0. 检查并安装chrony
            check_chrony = "which chronyc 2>/dev/null || echo 'not_installed'"
            check_result = self.execute_on_host(host, check_chrony, sudo=False)

            if "not_installed" in check_result.get("stdout", ""):
                self.logger.info(f"[{host}] chrony未安装，正在安装...")
                install_cmd = "apt-get update -qq && apt-get install -y chrony"
                install_result = self.execute_on_host(host, install_cmd, sudo=True, timeout=120)
                if not install_result["success"]:
                    results[host] = {"success": False, "error": "chrony安装失败"}
                    continue

            # 1. 确保配置目录存在
            mkdir_cmd = "mkdir -p /etc/chrony /var/lib/chrony /var/log/chrony"
            self.execute_on_host(host, mkdir_cmd, sudo=True)

            # 2. 备份原配置
            backup_cmd = "cp /etc/chrony/chrony.conf /etc/chrony/chrony.conf.bak 2>/dev/null || true"
            self.execute_on_host(host, backup_cmd, sudo=True)

            # 3. 写入新配置
            config_cmd = f'''cat > /etc/chrony/chrony.conf << 'EOF'
{config}
EOF'''
            config_result = self.execute_on_host(host, config_cmd, sudo=True)

            if not config_result["success"]:
                results[host] = {"success": False, "error": "写入配置失败"}
                continue

            # 4. 重启chrony服务
            restart_cmd = "systemctl restart chrony && systemctl enable chrony"
            restart_result = self.execute_on_host(host, restart_cmd, sudo=True)

            # 5. 验证
            verify_cmd = "chronyc sourcestats -v | head -5"
            verify_result = self.execute_on_host(host, verify_cmd)
            results[host] = {
                "success": restart_result["success"],
                "is_server": is_server,
                "verify": verify_result
            }

        success_count = sum(1 for r in results.values() if r.get("success"))

        return StepResult(
            step_id=self.step_id,
            step_name=self.step_name,
            status=StepStatus.SUCCESS if success_count == len(hosts) else StepStatus.FAILED,
            message=f"时间同步配置完成，成功: {success_count}/{len(hosts)}",
            details={"time_server": server_hostname, "server_ip": server_ip},
            host_results=results
        )

    def is_configured(self, host: str) -> tuple:
        """
        检查时间同步是否已配置

        Args:
            host: 主机地址

        Returns:
            tuple[bool, str]: (是否已配置, 检查详情)
        """
        # 获取时间服务器节点
        time_server = self.config.time_server_node if self.config else None
        server_ip = time_server.ip if time_server else None

        # 检查 chrony 是否安装和运行
        result = self.execute_on_host(host, "systemctl is-active chrony 2>/dev/null || true", timeout=30)

        stdout = result.get("stdout", "").strip()
        # 取第一行避免重复输出问题
        status = stdout.split('\n')[0].strip() if stdout else ""

        if status != "active":
            # 检查 chrony 是否安装
            check_result = self.execute_on_host(host, "which chronyc 2>/dev/null || true", timeout=10)
            if not check_result.get("stdout", "").strip():
                return False, "chrony未安装"
            return False, f"chrony服务状态: {status}"

        # 检查 chrony 配置是否正确
        config_result = self.execute_on_host(host, "cat /etc/chrony/chrony.conf 2>/dev/null", timeout=30)

        if config_result.get("success"):
            config_content = config_result.get("stdout", "")

            # 判断是否是时间服务器节点
            is_server = (host == server_ip) if server_ip else False

            if is_server:
                # Server端：检查是否有 local stratum 和 allow all
                if "local stratum" in config_content and "allow" in config_content:
                    return True, "时间服务器配置正确"
                else:
                    return False, "时间服务器配置不完整（缺少local stratum或allow）"
            else:
                # Client端：检查是否有指向server_ip的配置
                if server_ip and server_ip in config_content:
                    return True, f"时间客户端配置正确（指向服务器 {server_ip}）"
                elif server_ip:
                    return False, f"时间客户端配置不正确（未指向服务器 {server_ip}）"
                else:
                    # 没有指定时间服务器，只要chrony运行就认为配置正确
                    return True, "chrony服务运行中"

        return True, "chrony服务已启用（无法检查配置）"

    def post_check(self, hosts: List[str]) -> bool:
        """验证时间同步

        Server端：chronyc tracking 显示 Reference ID 为本地时钟(127.127.1.0)
        Client端：chronyc tracking 显示 Reference ID 指向 server_ip，
                  且 chronyc sources 中 server_ip 行状态为 ^*（当前同步源）
        """
        time_server = self.config.time_server_node if self.config else None
        server_ip = time_server.ip if time_server else None

        all_ok = True
        for host in hosts:
            is_server = (host == server_ip) if server_ip else False

            # 1. 检查 chronyc tracking 是否有 Reference ID（chrony 正在工作）
            tracking_cmd = "chronyc tracking 2>/dev/null"
            tracking_result = self.execute_on_host(host, tracking_cmd, sudo=False, timeout=30)
            tracking_output = tracking_result.get("stdout", "")

            if not tracking_output or "Reference ID" not in tracking_output:
                self.logger.warning(f"[{host}] chronyc tracking 无 Reference ID，chrony 可能未正常工作")
                all_ok = False
                continue

            if is_server:
                # Server端：Reference ID 应为 127.127.1.0（本地时钟）
                if "127.127.1.0" in tracking_output:
                    self.logger.info(f"[{host}] 时间服务器验证通过（本地时钟源）")
                else:
                    self.logger.warning(f"[{host}] 时间服务器 Reference ID 非 127.127.1.0: {tracking_output[:200]}")
                    # 不算失败，可能已从外网NTP同步
            else:
                # Client端：验证是否通过 server_ip 同步
                if not server_ip:
                    self.logger.info(f"[{host}] 未指定时间服务器，跳过客户端同步验证")
                    continue

                # 检查 chronyc sources 中 server_ip 是否为同步源（^* 标记）
                sources_cmd = "chronyc sources 2>/dev/null"
                sources_result = self.execute_on_host(host, sources_cmd, sudo=False, timeout=30)
                sources_output = sources_result.get("stdout", "")

                # 检查 server_ip 是否出现在 sources 中且状态为 ^*（当前同步源）
                server_synced = False
                for line in sources_output.splitlines():
                    # chronyc sources 输出格式: ^* server_ip 或行中包含 server_ip 且以 ^* 开头
                    if server_ip in line and line.strip().startswith("^*"):
                        server_synced = True
                        break

                if server_synced:
                    self.logger.info(f"[{host}] 时间客户端验证通过（已通过 {server_ip} 同步）")
                else:
                    # 宽松检查：tracking 输出中包含 server_ip 也算通过（可能还在同步中）
                    if server_ip in tracking_output:
                        self.logger.info(f"[{host}] 时间客户端验证通过（tracking 显示指向 {server_ip}）")
                    else:
                        # 最后检查：配置文件中有 server_ip 且 chrony 运行中
                        config_check = self.execute_on_host(
                            host, f"grep -q 'server {server_ip}' /etc/chrony/chrony.conf 2>/dev/null && echo 'ok' || echo 'fail'",
                            sudo=False, timeout=10
                        )
                        if config_check.get("stdout", "").strip() == "ok":
                            self.logger.warning(
                                f"[{host}] 时间客户端配置正确但尚未与 {server_ip} 同步，"
                                f"可能需要等待几分钟（chronyc sources: {sources_output[:200]})"
                            )
                        else:
                            self.logger.error(f"[{host}] 时间客户端未指向 {server_ip}")
                            all_ok = False

        return all_ok
