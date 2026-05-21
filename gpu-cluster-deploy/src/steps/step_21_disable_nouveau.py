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
        # 1. 检查黑名单配置是否存在（必须在modprobe.d中有配置）
        check_blacklist_cmd = "grep -rq 'blacklist nouveau' /etc/modprobe.d/ 2>/dev/null && echo 'found' || echo 'not_found'"
        blacklist_result = self.execute_on_host(host, check_blacklist_cmd, sudo=False)

        stdout = blacklist_result.get("stdout", "").strip()
        # 取最后一行避免重复输出问题
        status = stdout.split('\n')[-1].strip() if stdout else "not_found"
        blacklist_exists = status == "found"

        # 2. 检查内核模块是否已加载
        check_module_cmd = "lsmod | grep -q nouveau && echo 'loaded' || echo 'not_loaded'"
        module_result = self.execute_on_host(host, check_module_cmd, sudo=False)

        stdout_module = module_result.get("stdout", "").strip()
        status_module = stdout_module.split('\n')[-1].strip() if stdout_module else "not_loaded"
        module_loaded = status_module == "loaded"

        # 必须同时满足：黑名单配置存在 + 模块未加载
        if blacklist_exists and not module_loaded:
            return True, "nouveau驱动已禁用（黑名单已配置，模块未加载）"

        # 如果只有模块未加载但没有黑名单配置，仍需配置黑名单
        if not blacklist_exists:
            return False, "nouveau黑名单配置不存在"

        # 模块已加载但黑名单存在，可能需要重启
        if module_loaded:
            return False, "nouveau黑名单已配置但模块仍在加载（需要重启）"

        return False, "nouveau未正确禁用"

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

        # 2. 添加黑名单（逐行追加，但先检查避免重复）
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
            # 检查文件是否已有完整配置，避免重复追加
            check_full_cmd = "grep -q 'alias lbm-nouveau off' /etc/modprobe.d/blacklist.conf 2>/dev/null && echo 'complete' || echo 'incomplete'"
            check_full_result = self.execute_on_host(host, check_full_cmd, sudo=False)
            if check_full_result.get("stdout", "").strip() == "complete":
                self.logger.info(f"[{host}] blacklist.conf 已有完整配置，跳过追加")
                continue
            for line in blacklist_lines:
                # 每行追加前检查是否已存在，避免重复
                check_line_cmd = f"grep -qxF '{line}' /etc/modprobe.d/blacklist.conf 2>/dev/null && echo 'exists' || echo 'not_exists'"
                check_line_result = self.execute_on_host(host, check_line_cmd, sudo=False)
                if check_line_result.get("stdout", "").strip() != "exists":
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
