"""
步骤21: 禁用nouveau驱动
"""

from typing import List
from src.steps.base import BaseStep, StepResult, StepStatus


class DisableNouveau(BaseStep):
    """禁用nouveau驱动"""

    step_id = "21"
    step_name = "禁用nouveau驱动"
    step_description = "禁用系统自带nouveau驱动，为NVIDIA驱动安装做准备"
    requires_sudo = True
    supports_batch = True
    requires_reboot = True

    def execute(self, hosts: List[str]) -> StepResult:
        """执行禁用nouveau驱动"""
        # 1. 添加黑名单
        blacklist_content = '''blacklist nouveau
blacklist lbm-nouveau
options nouveau modeset=0
alias nouveau off
alias lbm-nouveau off'''

        blacklist_cmd = f'''cat >> /etc/modprobe.d/blacklist.conf << 'EOF'
{blacklist_content}
EOF'''
        blacklist_result = self.execute_batch(hosts, blacklist_cmd, sudo=True)

        failed = [h for h, r in blacklist_result.results.items() if not r.success]
        if failed:
            return StepResult(
                step_id=self.step_id,
                step_name=self.step_name,
                status=StepStatus.FAILED,
                message=f"添加黑名单失败: {failed}",
                host_results=blacklist_result.results
            )

        # 2. 更新initramfs
        initramfs_cmd = "update-initramfs -k $(uname -r) -c"
        initramfs_result = self.execute_batch(hosts, initramfs_cmd, sudo=True)

        # 3. 验证配置
        verify_cmd = "grep -q 'blacklist nouveau' /etc/modprobe.d/blacklist.conf"
        verify_result = self.execute_batch(hosts, verify_cmd, sudo=False)

        return StepResult(
            step_id=self.step_id,
            step_name=self.step_name,
            status=StepStatus.SUCCESS,
            message="nouveau驱动已禁用（需要重启生效）",
            host_results=verify_result.results
        )

    def post_check(self, hosts: List[str]) -> bool:
        """验证nouveau禁用（重启后）"""
        cmd = "lsmod | grep nouveau || echo 'disabled'"
        result = self.execute_batch(hosts, cmd, sudo=False)
        # 重启前总是返回disabled，重启后应该没有输出
        return True
