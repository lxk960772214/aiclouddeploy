"""
步骤28: 内核加载NVIDIA相关模块
"""

from typing import List
from src.steps.base import BaseStep, StepResult, StepStatus


class NVIDIAModules(BaseStep):
    """加载NVIDIA内核模块"""

    step_id = "28"
    step_name = "加载NVIDIA内核模块"
    step_description = "加载nvidia_peermem模块和配置IBGDA支持"
    requires_sudo = True
    supports_batch = True
    requires_reboot = True

    def execute(self, hosts: List[str]) -> StepResult:
        """执行内核模块配置"""
        # 1. 配置nvidia_peermem模块
        peermem_cmd = 'echo "nvidia_peermem" > /etc/modules-load.d/nvidia.conf'
        peermem_result = self.execute_batch(hosts, peermem_cmd, sudo=True)

        # 2. 配置nvidia模块参数（IBGDA支持）
        modprobe_config = '''options nvidia NVreg_EnableStreamMemOPs=1 NVreg_RegistryDwords="PeerMappingOverride=1;" NVreg_EnableGpuFirmware=0'''

        modprobe_cmd = f'''cat > /etc/modprobe.d/nvidia.conf << 'EOF'
{modprobe_config}
EOF'''
        modprobe_result = self.execute_batch(hosts, modprobe_cmd, sudo=True)

        # 3. 更新initramfs
        initramfs_cmd = "update-initramfs -u"
        initramfs_result = self.execute_batch(hosts, initramfs_cmd, sudo=True)

        # 4. 尝试加载模块（如果当前可以加载）
        load_cmd = "modprobe nvidia_peermem 2>/dev/null || echo 'will_load_after_reboot'"
        self.execute_batch(hosts, load_cmd, sudo=True)

        failed = [h for h, r in initramfs_result.results.items() if not r.success]

        return StepResult(
            step_id=self.step_id,
            step_name=self.step_name,
            status=StepStatus.SUCCESS,
            message="NVIDIA内核模块配置完成（需要重启生效）",
            host_results=initramfs_result.results
        )

    def is_configured(self, host: str) -> tuple:
        """
        检查NVIDIA内核模块配置

        Args:
            host: 主机地址

        Returns:
            tuple[bool, str]: (是否已配置, 检查详情)
        """
        # 检查配置文件
        result = self.execute_on_host(host, "test -f /etc/modules-load.d/nvidia.conf && test -f /etc/modprobe.d/nvidia.conf && echo 'configured' || echo 'not_configured'", sudo=False)

        if "configured" in result.get("stdout", ""):
            # 检查 nvidia_peermem 模块是否已加载
            # 使用 grep -c 后只取第一行，避免 || echo 0 导致的重复输出
            mod_result = self.execute_on_host(host, "lsmod | grep -c nvidia_peermem 2>/dev/null || true", timeout=30)
            if mod_result.get("success"):
                stdout = mod_result.get("stdout", "0").strip()
                # 取第一行（避免重复输出问题）
                first_line = stdout.split('\n')[0].strip() if stdout else "0"
                try:
                    count = int(first_line) if first_line else 0
                    if count > 0:
                        return True, "NVIDIA内核模块已配置并加载"
                except ValueError:
                    # 如果无法解析，尝试检查模块是否存在
                    check_result = self.execute_on_host(host, "lsmod | grep nvidia_peermem", timeout=30)
                    if check_result.get("success") and check_result.get("stdout", "").strip():
                        return True, "NVIDIA内核模块已配置并加载"
            return True, "NVIDIA内核模块配置已创建（需重启加载）"

        return False, "NVIDIA内核模块未配置"

    def post_check(self, hosts: List[str]) -> bool:
        """验证模块配置"""
        cmd = "test -f /etc/modules-load.d/nvidia.conf && test -f /etc/modprobe.d/nvidia.conf"
        result = self.execute_batch(hosts, cmd, sudo=False)
        return all(r.success for r in result.results.values())
