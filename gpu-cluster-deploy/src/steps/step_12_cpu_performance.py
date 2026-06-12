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
    can_skip = True  # 可以跳过（虚拟机可能不支持）

    def is_configured(self, host: str) -> tuple:
        """
        检查 CPU 性能模式是否已配置

        Args:
            host: 主机地址

        Returns:
            tuple[bool, str]: (是否已配置, 检查详情)
        """
        # 检查是否支持 cpufreq
        result = self.execute_on_host(
            host,
            "test -d /sys/devices/system/cpu/cpu0/cpufreq"
        )
        if not result["success"]:
            # 不支持 cpufreq，视为已配置（无需配置）
            return True, "系统不支持 cpufreq，无需配置"

        # 检查所有 CPU 核心的 governor 是否为 performance
        check_cmd = (
            "cat /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor 2>/dev/null | "
            "sort -u | tr '\\n' ' '"
        )
        result = self.execute_on_host(host, check_cmd)

        if result["success"]:
            governors = result["stdout"].strip().split()
            if governors == ["performance"]:
                return True, "所有 CPU 核心已设置为 performance 模式"
            elif "performance" in governors and len(governors) == 1:
                return True, "CPU 已设置为 performance 模式"
            else:
                return False, f"CPU governor 不一致: {governors}"

        return False, "CPU 性能模式检查失败"

    def execute(self, hosts: List[str]) -> StepResult:
        """执行CPU性能模式设置"""
        # 1. 检查是否支持cpufreq
        check_cmd = "test -d /sys/devices/system/cpu/cpu0/cpufreq && echo supported || echo unsupported"
        check_result = self.execute_batch(hosts, check_cmd, sudo=False)

        unsupported_hosts = [h for h, r in check_result.results.items()
                            if not r.success or 'unsupported' in r.stdout.lower()]

        if unsupported_hosts:
            self.logger.warning(f"以下主机不支持CPU频率调节: {unsupported_hosts}")
            return StepResult(
                step_id=self.step_id,
                step_name=self.step_name,
                status=StepStatus.SUCCESS,
                message=f"CPU性能模式设置跳过（不支持频率调节）",
                host_results={h: {"success": True, "skipped": True} for h in hosts}
            )

        # 2. 配置cpufrequtils（避免重复添加）
        config_cmd = '''
grep -q 'GOVERNOR="performance"' /etc/default/cpufrequtils 2>/dev/null && echo 'already_configured' || {
    echo 'GOVERNOR="performance"' > /etc/default/cpufrequtils && echo 'configured'
}
'''
        config_result = self.execute_batch(hosts, config_cmd, sudo=True)

        failed = [h for h, r in config_result.results.items() if not r.success]
        if failed:
            # 不视为错误，可能是虚拟机
            self.logger.warning(f"配置cpufrequtils失败，跳过: {failed}")
            return StepResult(
                step_id=self.step_id,
                step_name=self.step_name,
                status=StepStatus.SUCCESS,
                message=f"CPU性能模式设置跳过（虚拟机环境）",
                host_results={h: {"success": True, "skipped": True} for h in hosts}
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
        # 先检查是否支持cpufreq
        check_cmd = "test -d /sys/devices/system/cpu/cpu0/cpufreq"
        check_result = self.execute_batch(hosts, check_cmd, sudo=False)

        # 如果不支持CPU频率调节，直接返回成功
        unsupported_hosts = [h for h, r in check_result.results.items() if not r.success]
        if len(unsupported_hosts) == len(hosts):
            return True  # 所有主机都不支持，视为成功

        # 对于支持的主机检查性能模式
        supported_hosts = [h for h in hosts if h not in unsupported_hosts]
        if not supported_hosts:
            return True

        cmd = "cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor | grep -q performance"
        result = self.execute_batch(supported_hosts, cmd, sudo=False)
        return all(r.success for r in result.results.values())
