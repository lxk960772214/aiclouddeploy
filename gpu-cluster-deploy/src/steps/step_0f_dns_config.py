"""
步骤0f: 配置DNS

在SSH免密配置完成后执行，配置/etc/systemd/resolved.conf的DNS服务器，
确保后续包下载和网络操作能正常解析域名。
"""

from typing import List
from src.steps.base import BaseStep, StepResult, StepStatus


class DNSConfig(BaseStep):
    """配置DNS服务器"""

    step_id = "0f"
    step_name = "配置DNS"
    step_description = "配置systemd-resolved DNS服务器，确保域名解析正常"
    requires_sudo = True
    supports_batch = True

    def _get_dns_servers(self) -> str:
        """从配置获取DNS服务器地址，默认223.5.5.5"""
        if self.config and hasattr(self.config, 'time_sync'):
            dns = getattr(self.config.time_sync, 'dns_servers', None)
            if dns:
                return dns
        return "223.5.5.5"

    def is_configured(self, host: str) -> tuple:
        """
        检查DNS是否已配置

        检查 /etc/systemd/resolved.conf 中 DNS 是否已设置为期望值。

        Args:
            host: 主机地址

        Returns:
            tuple[bool, str]: (是否已配置, 检查详情)
        """
        target_dns = self._get_dns_servers()

        # 检查 resolved.conf 中的 DNS 配置
        check_cmd = "grep '^DNS=' /etc/systemd/resolved.conf 2>/dev/null"
        result = self.execute_on_host(host, check_cmd, sudo=True)

        if result.get("success") and result.get("stdout", "").strip():
            current_dns = result["stdout"].strip()
            # 格式: DNS=223.5.5.5 或 DNS=223.5.5.5 8.8.8.8
            dns_value = current_dns.split("=", 1)[-1].strip() if "=" in current_dns else ""
            if target_dns in dns_value:
                return True, f"DNS已配置: {current_dns}"
            else:
                return False, f"DNS不匹配: 当前={current_dns}, 目标包含={target_dns}"

        return False, "DNS未配置（/etc/systemd/resolved.conf 中无 DNS 行）"

    def execute(self, hosts: List[str]) -> StepResult:
        """执行DNS配置"""
        dns_servers = self._get_dns_servers()
        self.logger.info(f"[{self.step_id}] 配置DNS服务器: {dns_servers}")

        # 1. 修改 /etc/systemd/resolved.conf
        # 替换已存在的 DNS 行（包括被注释的）
        sed_cmd = (
            f"sed -i 's/^[# ]*DNS=.*/DNS={dns_servers}/' /etc/systemd/resolved.conf"
        )
        self.execute_batch(hosts, sed_cmd, sudo=True)

        # 如果没有 DNS 行（包括被注释的），追加一行
        ensure_cmd = (
            f"grep -q '^DNS=' /etc/systemd/resolved.conf || "
            f"echo 'DNS={dns_servers}' >> /etc/systemd/resolved.conf"
        )
        self.execute_batch(hosts, ensure_cmd, sudo=True)

        # 2. 重启 systemd-resolved 服务
        self.logger.info(f"[{self.step_id}] 重启 systemd-resolved ...")
        restart_cmd = "systemctl restart systemd-resolved"
        restart_result = self.execute_batch(hosts, restart_cmd, sudo=True)

        # 3. 验证配置文件
        self.logger.info(f"[{self.step_id}] 验证DNS配置 ...")
        verify_cmd = "grep '^DNS=' /etc/systemd/resolved.conf"
        verify_result = self.execute_batch(hosts, verify_cmd, sudo=True)

        success_hosts = []
        failed_hosts = []
        for host, res in verify_result.results.items():
            if res.success and res.stdout.strip():
                dns_value = res.stdout.strip()
                if dns_servers in dns_value:
                    success_hosts.append(host)
                else:
                    failed_hosts.append(host)
            else:
                failed_hosts.append(host)

        # 检查 restart 结果
        for host, res in restart_result.results.items():
            if not res.success and host not in failed_hosts:
                failed_hosts.append(host)

        if not failed_hosts:
            return StepResult(
                step_id=self.step_id,
                step_name=self.step_name,
                status=StepStatus.SUCCESS,
                message=f"DNS配置完成: DNS={dns_servers}，成功: {len(success_hosts)}/{len(hosts)}",
                details={"dns_servers": dns_servers},
                host_results=verify_result.results
            )
        else:
            return StepResult(
                step_id=self.step_id,
                step_name=self.step_name,
                status=StepStatus.FAILED,
                message=f"DNS配置失败，成功: {len(success_hosts)}/{len(hosts)}，失败: {failed_hosts}",
                details={"dns_servers": dns_servers},
                host_results=verify_result.results
            )

    def post_check(self, hosts: List[str]) -> bool:
        """验证DNS配置已生效"""
        dns_servers = self._get_dns_servers()

        # 使用 resolvectl status 检查当前生效的 DNS
        cmd = "resolvectl status 2>/dev/null"
        result = self.execute_batch(hosts, cmd, sudo=False)

        all_configured = True
        for host, res in result.results.items():
            if res.success and res.stdout.strip():
                output = res.stdout.strip()
                # 检查输出中是否包含配置的 DNS 服务器
                # resolvectl status 输出格式:
                #   DNS Servers: 223.5.5.5
                if dns_servers in output:
                    continue
                else:
                    self.logger.warning(f"[{host}] DNS未生效: 未找到 {dns_servers}")
                    all_configured = False
            else:
                # resolvectl 可能需要权限，降级检查配置文件
                fallback_cmd = "grep '^DNS=' /etc/systemd/resolved.conf 2>/dev/null"
                fallback_result = self.execute_on_host(host, fallback_cmd, sudo=True)
                if fallback_result.get("success") and fallback_result.get("stdout", "").strip():
                    if dns_servers in fallback_result["stdout"]:
                        continue
                self.logger.warning(f"[{host}] DNS验证失败")
                all_configured = False

        return all_configured
