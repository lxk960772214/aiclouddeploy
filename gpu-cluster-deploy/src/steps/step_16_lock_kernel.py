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

    def is_configured(self, host: str) -> tuple:
        """
        检查内核版本是否已固定

        Args:
            host: 主机地址

        Returns:
            tuple[bool, str]: (是否已配置, 检查详情)
        """
        kernel_config = self.versions.kernel if hasattr(self, 'versions') and self.versions else None

        # 如果kernel.mode == "keep"，表示不锁定，直接返回True跳过
        if kernel_config and getattr(kernel_config, 'mode', 'keep') == "keep":
            return True, "内核模式为keep，无需固定"

        # 检查GRUB_DEFAULT是否设置了Advanced options
        result = self.execute_on_host(host, "grep 'GRUB_DEFAULT=' /etc/default/grub 2>/dev/null", sudo=False)
        if result.get("success"):
            grub_default = result.get("stdout", "").strip()
            # 取第一行避免重复输出问题
            grub_default = grub_default.split('\n')[0].strip() if grub_default else ""

            # 检查是否包含内核版本锁定
            if "Advanced options" in grub_default:
                # 进一步检查是否锁定到具体内核版本
                check_kernel_cmd = "uname -r"
                kernel_result = self.execute_on_host(host, check_kernel_cmd)
                current_kernel_version = kernel_result.get("stdout", "").strip()

                if current_kernel_version and current_kernel_version in grub_default:
                    return True, f"内核已锁定到版本: {current_kernel_version}"
                else:
                    return True, "内核锁定配置已设置"

        return False, "内核版本未固定"

    def post_check(self, hosts: List[str]) -> bool:
        """验证GRUB配置"""
        # 检查GRUB_DEFAULT是否包含Advanced options
        cmd = "grep 'GRUB_DEFAULT=' /etc/default/grub | grep 'Advanced options'"
        result = self.execute_batch(hosts, cmd, sudo=False)

        # 如果kernel.mode == "keep"，则post_check返回True
        kernel_config = self.versions.kernel if hasattr(self, 'versions') and self.versions else None
        if kernel_config and getattr(kernel_config, 'mode', 'keep') == "keep":
            return True

        # 否则检查是否配置了内核锁定
        success_count = sum(1 for r in result.results.values() if r.success)
        return success_count == len(hosts)
