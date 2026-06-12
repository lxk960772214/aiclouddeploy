"""
步骤18: 禁用IPv6
"""

from typing import List
from src.steps.base import BaseStep, StepResult, StepStatus


class DisableIPv6(BaseStep):
    """禁用IPv6"""

    step_id = "18"
    step_name = "禁用IPv6"
    step_description = "在系统级别禁用IPv6"
    requires_sudo = True
    supports_batch = True

    def is_configured(self, host: str) -> tuple:
        """
        检查IPv6是否已禁用

        Args:
            host: 主机地址

        Returns:
            tuple[bool, str]: (是否已配置, 检查详情)
        """
        # 检查内核参数
        check_cmd = "cat /proc/sys/net/ipv6/conf/all/disable_ipv6"
        result = self.execute_on_host(host, check_cmd, sudo=False)

        if result.get("success"):
            value = result.get("stdout", "").strip()
            if value == "1":
                return True, "IPv6已禁用"
            else:
                return False, f"IPv6未禁用（当前值: {value}）"

        return False, "IPv6状态检查失败"

    def execute(self, hosts: List[str]) -> StepResult:
        """执行IPv6禁用"""
        # 1. 添加sysctl配置
        sysctl_cmd = '''grep -q "disable_ipv6" /etc/sysctl.conf || echo "net.ipv6.conf.all.disable_ipv6 = 1" >> /etc/sysctl.conf'''
        self.execute_batch(hosts, sysctl_cmd, sudo=True)

        # 2. 应用配置
        apply_cmd = "sysctl -p"
        apply_result = self.execute_batch(hosts, apply_cmd, sudo=True)

        # 3. 验证
        verify_cmd = "cat /proc/sys/net/ipv6/conf/all/disable_ipv6"
        verify_result = self.execute_batch(hosts, verify_cmd, sudo=False)

        success_hosts = []
        for host, res in verify_result.results.items():
            if res.success and res.stdout.strip() == "1":
                success_hosts.append(host)

        return StepResult(
            step_id=self.step_id,
            step_name=self.step_name,
            status=StepStatus.SUCCESS if len(success_hosts) == len(hosts) else StepStatus.FAILED,
            message=f"IPv6禁用完成，成功: {len(success_hosts)}/{len(hosts)}",
            host_results=verify_result.results
        )

    def post_check(self, hosts: List[str]) -> bool:
        """验证IPv6禁用"""
        cmd = "test $(cat /proc/sys/net/ipv6/conf/all/disable_ipv6) -eq 1"
        result = self.execute_batch(hosts, cmd, sudo=False)
        return all(r.success for r in result.results.values())
