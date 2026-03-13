"""
步骤05: 设置sudo免密
"""

from typing import List
from src.steps.base import BaseStep, StepResult, StepStatus


class SudoNopasswd(BaseStep):
    """设置sudo免密"""

    step_id = "05"
    step_name = "设置sudo免密"
    step_description = "为ubuntu用户设置sudo免密（root账户跳过）"
    requires_sudo = True
    supports_batch = True
    can_skip = True  # root账户可跳过

    def is_configured(self, host: str) -> tuple:
        """
        检查sudo免密是否已配置

        Args:
            host: 主机地址

        Returns:
            tuple[bool, str]: (是否已配置, 检查详情)
        """
        # 检查当前用户是否为root
        whoami_result = self.execute_on_host(host, "whoami", sudo=False)
        if whoami_result.get("success") and whoami_result.get("stdout", "").strip() == "root":
            return True, "root账户无需配置sudo免密"

        # 使用 sudo -n 测试是否需要密码
        # -n 参数：非交互模式，需要密码时直接失败而不提示
        cmd = "sudo -n true 2>/dev/null && echo 'ok' || echo 'need_password'"
        result = self.execute_on_host(host, cmd, sudo=False)

        if result.get("success") and "ok" in result.get("stdout", ""):
            return True, "sudo免密已配置"
        return False, "sudo免密未配置"

    def execute(self, hosts: List[str]) -> StepResult:
        """执行sudo免密设置"""
        # 检查当前用户
        check_cmd = "whoami"
        check_result = self.execute_batch(hosts, check_cmd, sudo=False)

        # 需要设置的节点（非root）
        need_setup = []
        skipped = []

        for host, res in check_result.results.items():
            if res.success:
                user = res.stdout.strip()
                if user == "root":
                    skipped.append(host)
                    self.logger.info(f"[{host}] root账户，跳过sudo免密设置")
                else:
                    need_setup.append(host)
            else:
                need_setup.append(host)

        if not need_setup:
            return StepResult(
                step_id=self.step_id,
                step_name=self.step_name,
                status=StepStatus.SUCCESS,
                message="所有节点均为root账户，跳过sudo免密设置"
            )

        # 设置sudo免密
        setup_cmd = '''echo "ubuntu ALL=(ALL) NOPASSWD:ALL" | sudo tee /etc/sudoers.d/ubuntu && sudo chmod 440 /etc/sudoers.d/ubuntu'''
        result = self.execute_batch(need_setup, setup_cmd, sudo=True)

        failed = [h for h, r in result.results.items() if not r.success]

        if failed:
            return StepResult(
                step_id=self.step_id,
                step_name=self.step_name,
                status=StepStatus.FAILED,
                message=f"sudo免密设置失败: {failed}",
                host_results=result.results
            )

        return StepResult(
            step_id=self.step_id,
            step_name=self.step_name,
            status=StepStatus.SUCCESS,
            message=f"sudo免密设置完成，成功: {len(need_setup)}，跳过: {len(skipped)}",
            details={"setup_hosts": need_setup, "skipped_hosts": skipped}
        )

    def post_check(self, hosts: List[str]) -> bool:
        """验证sudo免密"""
        cmd = "sudo -n true 2>/dev/null && echo 'ok' || echo 'need_password'"
        result = self.execute_batch(hosts, cmd, sudo=False)
        return all(r.success and 'ok' in r.stdout for r in result.results.values())
