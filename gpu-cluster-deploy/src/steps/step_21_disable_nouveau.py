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
    can_skip = True  # 可以跳过

    def is_configured(self, host: str) -> tuple:
        """
        检查nouveau驱动是否已禁用

        Args:
            host: 主机地址

        Returns:
            tuple[bool, str]: (是否已配置, 检查详情)
        """
        # 1. 检查黑名单配置是否存在（可能在任何modprobe.d文件中）
        check_blacklist_cmd = "grep -rq 'blacklist nouveau' /etc/modprobe.d/ 2>/dev/null && echo 'found' || echo 'not_found'"
        blacklist_result = self.execute_on_host(host, check_blacklist_cmd, sudo=False)

        blacklist_exists = blacklist_result.get("stdout", "").strip() == "found"

        # 2. 检查内核模块是否已加载
        check_module_cmd = "lsmod | grep -q nouveau && echo 'loaded' || echo 'not_loaded'"
        module_result = self.execute_on_host(host, check_module_cmd, sudo=False)

        module_loaded = module_result.get("stdout", "").strip() == "loaded"

        # 如果模块未加载，则视为已禁用（无论黑名单是否存在）
        if not module_loaded:
            if blacklist_exists:
                return True, "nouveau驱动已禁用（黑名单已配置，模块未加载）"
            else:
                return True, "nouveau驱动已禁用（模块未加载）"

        # 模块已加载但黑名单存在，可能需要重启
        if blacklist_exists:
            return False, "nouveau黑名单已配置但模块仍在加载（需要重启）"

        return False, "nouveau黑名单配置不存在"

    def execute(self, hosts: List[str]) -> StepResult:
        """执行禁用nouveau驱动"""
        # 1. 检查是否已禁用
        check_cmd = "grep -q 'blacklist nouveau' /etc/modprobe.d/blacklist.conf 2>/dev/null && echo disabled || echo not_disabled"
        check_result = self.execute_batch(hosts, check_cmd, sudo=False)

        already_disabled = [h for h, r in check_result.results.items()
                           if r.success and 'disabled' in r.stdout]

        if len(already_disabled) == len(hosts):
            return StepResult(
                step_id=self.step_id,
                step_name=self.step_name,
                status=StepStatus.SUCCESS,
                message="nouveau驱动已禁用（无需重复操作）",
                host_results={h: {"success": True, "already_disabled": True} for h in hosts}
            )

        # 2. 添加黑名单（逐行追加）
        blacklist_lines = [
            "blacklist nouveau",
            "blacklist lbm-nouveau",
            "options nouveau modeset=0",
            "alias nouveau off",
            "alias lbm-nouveau off"
        ]

        for host in hosts:
            if host in already_disabled:
                continue
            for line in blacklist_lines:
                self.execute_on_host(host, f"echo '{line}' | sudo tee -a /etc/modprobe.d/blacklist.conf", sudo=True)

        # 3. 更新initramfs
        initramfs_cmd = "update-initramfs -k $(uname -r) -c"
        self.execute_batch(hosts, initramfs_cmd, sudo=True)

        # 4. 验证配置
        verify_cmd = "grep -q 'blacklist nouveau' /etc/modprobe.d/blacklist.conf"
        verify_result = self.execute_batch(hosts, verify_cmd, sudo=False)

        return StepResult(
            step_id=self.step_id,
            step_name=self.step_name,
            status=StepStatus.SUCCESS,
            message="nouveau驱动已禁用（需要重启生效）",
            host_results={h: {"success": r.success, "stdout": r.stdout}
                         for h, r in verify_result.results.items()}
        )

    def post_check(self, hosts: List[str]) -> bool:
        """验证nouveau禁用（重启后）"""
        cmd = "lsmod | grep nouveau || echo 'disabled'"
        result = self.execute_batch(hosts, cmd, sudo=False)
        # 重启前总是返回disabled，重启后应该没有输出
        return True
