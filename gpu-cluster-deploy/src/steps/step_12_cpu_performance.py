"""
步骤12: 设置CPU性能模式
"""

from typing import List
from src.steps.base import BaseStep, StepResult, StepStatus


class CPUPerformance(BaseStep):
    """设置CPU性能模式"""

    step_id = "12"
    step_name = "设置CPU性能模式"
    step_description = "设置CPU为性能模式"
    requires_sudo = True
    supports_batch = True

    def execute(self, hosts: List[str]) -> StepResult:
        """执行CPU性能模式设置"""
        # 1. 配置cpufrequtils
        config_cmd = '''echo 'GOVERNOR="performance"' > /etc/default/cpufrequtils'''
        config_result = self.execute_batch(hosts, config_cmd, sudo=True)

        failed = [h for h, r in config_result.results.items() if not r.success]
        if failed:
            return StepResult(
                step_id=self.step_id,
                step_name=self.step_name,
                status=StepStatus.FAILED,
                message=f"配置cpufrequtils失败: {failed}",
                host_results=config_result.results
            )

        # 2. 重启cpufrequtils服务
        restart_cmd = "systemctl restart cpufrequtils && systemctl enable cpufrequtils"
        restart_result = self.execute_batch(hosts, restart_cmd, sudo=True)

        # 3. 验证
        verify_cmd = "cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor"
        verify_result = self.execute_batch(hosts, verify_cmd, sudo=False)

        success_hosts = []
        failed_hosts = []

        for host, res in verify_result.results.items():
            if res.success and "performance" in res.stdout.lower():
                success_hosts.append(host)
            else:
                failed_hosts.append(host)

        return StepResult(
            step_id=self.step_id,
            step_name=self.step_name,
            status=StepStatus.SUCCESS if not failed_hosts else StepStatus.FAILED,
            message=f"CPU性能模式设置完成，成功: {len(success_hosts)}/{len(hosts)}",
            details={"failed": failed_hosts},
            host_results=verify_result.results
        )

    def post_check(self, hosts: List[str]) -> bool:
        """验证CPU性能模式"""
        cmd = "cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor | grep -q performance"
        result = self.execute_batch(hosts, cmd, sudo=False)
        return all(r.success for r in result.results.values())
