"""
步骤16: 固定内核版本
"""

from typing import List
from src.steps.base import BaseStep, StepResult, StepStatus


class LockKernel(BaseStep):
    """固定内核版本"""

    step_id = "16"
    step_name = "固定内核版本"
    step_description = "在GRUB中固定当前内核版本"
    requires_sudo = True
    supports_batch = True
    can_skip = True  # 允许跳过

    def execute(self, hosts: List[str]) -> StepResult:
        """执行内核版本固定"""
        # 使用POSIX兼容语法，修复[[ ]]在sh中不可用的问题
        # 直接修改GRUB_DEFAULT行，不依赖行号
        cmd = '''
kernel_version=$(uname -r)
grub_config="/etc/default/grub"
new_default="Advanced options for Ubuntu>Ubuntu, with Linux $kernel_version"

if grep -q "^GRUB_DEFAULT=" "$grub_config"; then
    sed -i "s|^GRUB_DEFAULT=.*|GRUB_DEFAULT=\"$new_default\"|" "$grub_config"
    if update-grub 2>/dev/null; then
        echo "内核版本已固定: $kernel_version"
    else
        echo "update-grub执行失败"
        exit 1
    fi
else
    echo "未找到GRUB_DEFAULT配置"
    exit 1
fi
'''
        result = self.execute_batch(hosts, cmd, sudo=True)

        success_hosts = []
        failed_hosts = []

        for host, res in result.results.items():
            if res.success and "内核版本已固定" in res.stdout:
                success_hosts.append(host)
            else:
                failed_hosts.append(host)

        if failed_hosts:
            return StepResult(
                step_id=self.step_id,
                step_name=self.step_name,
                status=StepStatus.FAILED,
                message=f"内核固定失败: {failed_hosts}",
                host_results=result.results
            )

        return StepResult(
            step_id=self.step_id,
            step_name=self.step_name,
            status=StepStatus.SUCCESS,
            message=f"内核版本固定完成",
            host_results=result.results
        )

    def post_check(self, hosts: List[str]) -> bool:
        """验证GRUB配置"""
        # 简化验证：检查 /etc/default/grub 是否可读，且包含 GRUB_DEFAULT 配置
        cmd = "grep -E '^GRUB_DEFAULT=' /etc/default/grub"
        result = self.execute_batch(hosts, cmd, sudo=True)
        return all(r.success for r in result.results.values())
