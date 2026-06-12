"""
步骤19: 触发vmcore日志和禁止系统休眠
"""

from typing import List
from src.steps.base import BaseStep, StepResult, StepStatus


class VmcoreHibernate(BaseStep):
    """触发vmcore日志和禁止系统休眠"""

    step_id = "19"
    step_name = "触发vmcore日志和禁止系统休眠"
    step_description = "配置vmcore日志触发和禁止系统休眠"
    requires_sudo = True
    supports_batch = True

    def is_configured(self, host: str) -> tuple:
        """
        检查vmcore配置和休眠禁止是否已配置

        Args:
            host: 主机地址

        Returns:
            tuple[bool, str]: (是否已配置, 检查详情)
        """
        # 1. 检查休眠目标是否已屏蔽
        check_sleep_cmd = "systemctl is-enabled sleep.target 2>/dev/null || echo 'masked'"
        sleep_result = self.execute_on_host(host, check_sleep_cmd, sudo=False)

        if sleep_result.get("success"):
            # 处理多行输出（取第一行）
            stdout = sleep_result.get("stdout", "").strip()
            status = stdout.split('\n')[0].strip().lower()
            if status not in ["masked", "disabled", "not-found"]:
                return False, f"休眠目标未屏蔽（状态: {status}）"

        # 2. 检查sysctl配置是否存在
        check_sysctl_cmd = "grep -q 'hung_task_panic' /etc/sysctl.conf"
        sysctl_result = self.execute_on_host(host, check_sysctl_cmd, sudo=False)

        if not sysctl_result.get("success"):
            return False, "vmcore sysctl配置不存在"

        return True, "vmcore配置和休眠禁止已完成"

    def execute(self, hosts: List[str]) -> StepResult:
        """执行vmcore和休眠配置"""
        # 1. 配置vmcore触发
        vmcore_cmd = '''grep -q "hung_task_panic" /etc/sysctl.conf || echo "kernel.hung_task_panic=1" >> /etc/sysctl.conf
grep -q "softlockup_panic" /etc/sysctl.conf || echo "kernel.softlockup_panic=1" >> /etc/sysctl.conf
sysctl -p'''
        self.execute_batch(hosts, vmcore_cmd, sudo=True)

        # 2. 禁止系统休眠
        hibernate_cmd = "systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target"
        hibernate_result = self.execute_batch(hosts, hibernate_cmd, sudo=True)

        # 3. 验证
        verify_cmd = "systemctl status sleep.target 2>&1 | head -2"
        verify_result = self.execute_batch(hosts, verify_cmd, sudo=False)

        return StepResult(
            step_id=self.step_id,
            step_name=self.step_name,
            status=StepStatus.SUCCESS,
            message="vmcore配置和休眠禁止完成",
            host_results=verify_result.results
        )

    def post_check(self, hosts: List[str]) -> bool:
        """验证配置"""
        cmd = "systemctl is-enabled sleep.target 2>/dev/null || echo 'masked'"
        result = self.execute_batch(hosts, cmd, sudo=False)
        return all('masked' in r.stdout.lower() for r in result.results.values())
