"""
步骤27: 设置GPU持久模式
"""

from typing import List
from src.steps.base import BaseStep, StepResult, StepStatus


class GPUPersistence(BaseStep):
    """设置GPU持久模式"""

    step_id = "27"
    step_name = "设置GPU持久模式"
    step_description = "设置NVIDIA GPU持久模式服务"
    requires_sudo = True
    supports_batch = True

    # systemd服务文件
    SERVICE_CONTENT = '''[Unit]
Description=Enable NVIDIA GPU Persistence Mode
After=display-manager.service
Wants=sysinit.target

[Service]
Type=oneshot
ExecStart=/usr/bin/nvidia-smi -pm 1
User=root

[Install]
WantedBy=multi-user.target'''

    def execute(self, hosts: List[str]) -> StepResult:
        """执行GPU持久模式设置"""
        # 1. 创建systemd服务
        service_cmd = f'''cat > /etc/systemd/system/nvidia-persistence-mode.service << 'EOF'
{self.SERVICE_CONTENT}
EOF'''
        service_result = self.execute_batch(hosts, service_cmd, sudo=True)

        failed = [h for h, r in service_result.results.items() if not r.success]
        if failed:
            return StepResult(
                step_id=self.step_id,
                step_name=self.step_name,
                status=StepStatus.FAILED,
                message=f"创建服务文件失败: {failed}",
                host_results=service_result.results
            )

        # 2. 启用并启动服务
        enable_cmd = "systemctl daemon-reload && systemctl enable nvidia-persistence-mode.service && systemctl start nvidia-persistence-mode.service"
        enable_result = self.execute_batch(hosts, enable_cmd, sudo=True)

        # 3. 验证
        verify_cmd = "systemctl is-active nvidia-persistence-mode.service && nvidia-smi -q | grep 'Persistence Mode' | head -1"
        verify_result = self.execute_batch(hosts, verify_cmd, sudo=False)

        return StepResult(
            step_id=self.step_id,
            step_name=self.step_name,
            status=StepStatus.SUCCESS,
            message="GPU持久模式设置完成",
            host_results=verify_result.results
        )

    def is_configured(self, host: str) -> tuple:
        """
        检查GPU持久模式是否已配置

        Args:
            host: 主机地址

        Returns:
            tuple[bool, str]: (是否已配置, 检查详情)
        """
        # 检查持久模式服务
        result = self.execute_on_host(host, "systemctl is-enabled nvidia-persistence-mode.service 2>/dev/null || echo 'disabled'", timeout=30)

        if "enabled" in result.get("stdout", ""):
            # 验证持久模式是否生效
            pm_result = self.execute_on_host(host, "nvidia-smi -q 2>/dev/null | grep -c 'Persistence Mode.*Enabled'", timeout=30)
            count = int(pm_result.get("stdout", "0").strip())
            if count > 0:
                return True, f"GPU持久模式已配置: {count} GPU"
            return True, "持久模式服务已启用"

        # 检查当前持久模式状态
        result = self.execute_on_host(host, "nvidia-smi -q 2>/dev/null | grep -c 'Persistence Mode.*Enabled'", timeout=30)
        if result.get("success"):
            count = int(result.get("stdout", "0").strip())
            if count > 0:
                return True, f"GPU持久模式已启用: {count} GPU (服务未配置)"

        return False, "GPU持久模式未配置"

    def post_check(self, hosts: List[str]) -> bool:
        """验证GPU持久模式"""
        cmd = "nvidia-smi -q | grep -q 'Persistence Mode.*Enabled'"
        result = self.execute_batch(hosts, cmd, sudo=False)
        return all(r.success for r in result.results.values())
