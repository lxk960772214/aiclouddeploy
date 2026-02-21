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
driftfile /var/lib/chrony/drift
makestep 1.0 3
rtcsync
logdir /var/log/chrony
allow all'''

    def _get_client_config(self, server_ip: str) -> str:
        """获取客户端配置"""
        return f'''server {server_ip} iburst
driftfile /var/lib/chrony/drift
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

            # 1. 备份原配置
            backup_cmd = "cp /etc/chrony/chrony.conf /etc/chrony/chrony.conf.bak 2>/dev/null || true"
            self.execute_on_host(host, backup_cmd, sudo=True)

            # 2. 写入新配置
            config_cmd = f'''cat > /etc/chrony/chrony.conf << 'EOF'
{config}
EOF'''
            config_result = self.execute_on_host(host, config_cmd, sudo=True)

            if not config_result["success"]:
                results[host] = {"success": False, "error": "写入配置失败"}
                continue

            # 3. 重启chrony服务
            restart_cmd = "systemctl restart chrony && systemctl enable chrony"
            restart_result = self.execute_on_host(host, restart_cmd, sudo=True)

            # 4. 验证
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

    def post_check(self, hosts: List[str]) -> bool:
        """验证时间同步"""
        cmd = "chronyc tracking | grep -q 'Reference ID'"
        result = self.execute_batch(hosts, cmd, sudo=False)
        return all(r.success for r in result.results.values())
