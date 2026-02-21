"""
步骤17: 更改时区和更新系统时间
"""

from typing import List
from src.steps.base import BaseStep, StepResult, StepStatus


class TimezoneSetup(BaseStep):
    """设置时区和时间同步"""

    step_id = "17"
    step_name = "更改时区和更新系统时间"
    step_description = "设置时区为Asia/Shanghai并同步时间"
    requires_sudo = True
    supports_batch = True

    def execute(self, hosts: List[str]) -> StepResult:
        """执行时区设置"""
        # 1. 设置时区
        timezone = self.config.time_sync.timezone if hasattr(self.config, 'time_sync') else "Asia/Shanghai"
        tz_cmd = f"timedatectl set-timezone {timezone}"
        tz_result = self.execute_batch(hosts, tz_cmd, sudo=True)

        failed = [h for h, r in tz_result.results.items() if not r.success]
        if failed:
            return StepResult(
                step_id=self.step_id,
                step_name=self.step_name,
                status=StepStatus.FAILED,
                message=f"设置时区失败: {failed}",
                host_results=tz_result.results
            )

        # 2. 同步时间
        ntp_cmd = "ntpdate -u ntp.aliyun.com || true"
        ntp_result = self.execute_batch(hosts, ntp_cmd, sudo=True)

        # 3. 验证
        verify_cmd = "timedatectl | grep 'Time zone'"
        verify_result = self.execute_batch(hosts, verify_cmd, sudo=False)

        return StepResult(
            step_id=self.step_id,
            step_name=self.step_name,
            status=StepStatus.SUCCESS,
            message=f"时区设置完成: {timezone}",
            details={"timezone": timezone},
            host_results=verify_result.results
        )

    def post_check(self, hosts: List[str]) -> bool:
        """验证时区"""
        cmd = "timedatectl | grep -q 'Asia/Shanghai'"
        result = self.execute_batch(hosts, cmd, sudo=False)
        return all(r.success for r in result.results.values())
