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

    def is_configured(self, host: str) -> tuple:
        """
        检查时区是否已配置

        Args:
            host: 主机地址

        Returns:
            tuple[bool, str]: (是否已配置, 检查详情)
        """
        # 获取目标时区
        target_timezone = "Asia/Shanghai"
        if self.config and hasattr(self.config, 'time_sync'):
            time_sync = self.config.time_sync
            if hasattr(time_sync, 'timezone'):
                target_timezone = time_sync.timezone

        # 检查当前时区
        check_cmd = "timedatectl show --no-pager 2>/dev/null | grep 'Timezone=' || timedatectl 2>/dev/null | grep 'Time zone'"
        result = self.execute_on_host(host, check_cmd, sudo=False)

        if result.get("success"):
            output = result.get("stdout", "").strip()
            # 解析时区（格式: Timezone=Asia/Shanghai 或 "Time zone: Asia/Shanghai"）
            if "Timezone=" in output:
                current_tz = output.split("Timezone=")[-1].strip()
            elif "Time zone:" in output:
                current_tz = output.split("Time zone:")[-1].strip().split()[0]
            else:
                current_tz = output

            if current_tz == target_timezone:
                return True, f"时区已配置为 {target_timezone}"
            else:
                return False, f"时区不匹配: 当前={current_tz}, 目标={target_timezone}"

        return False, "时区未配置"

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
