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

    def execute(self, hosts: List[str]) -> StepResult:
        """执行内核版本固定"""
        # 获取内核版本并更新GRUB
        cmd = '''
kernel_version=$(uname -r)
grub_config="/etc/default/grub"

if grep -q "^GRUB_DEFAULT=" "$grub_config"; then
    current_grub_default=$(sed -n '6p' "$grub_config")
    if [[ "$current_grub_default" == GRUB_DEFAULT=* ]]; then
        sed -i "6s|^GRUB_DEFAULT=.*|GRUB_DEFAULT=\"Advanced options for Ubuntu>Ubuntu, with Linux $kernel_version\"|" $grub_config
        update-grub
        echo "内核版本已固定: $kernel_version"
    else
        echo "GRUB配置格式不符合预期"
    fi
else
    echo "未找到GRUB_DEFAULT配置"
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
        cmd = "grep -q 'Advanced options for Ubuntu' /etc/default/grub"
        result = self.execute_batch(hosts, cmd, sudo=False)
        return all(r.success for r in result.results.values())
