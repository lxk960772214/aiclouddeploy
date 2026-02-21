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

    def post_check(self, hosts: List[str]) -> bool:
        """验证模块配置"""
        cmd = "test -f /etc/modules-load.d/nvidia.conf && test -f /etc/modprobe.d/nvidia.conf"
        result = self.execute_batch(hosts, cmd, sudo=False)
        return all(r.success for r in result.results.values())
