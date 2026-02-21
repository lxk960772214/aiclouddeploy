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

    def post_check(self, hosts: List[str]) -> bool:
        """验证GPU持久模式"""
        cmd = "nvidia-smi -q | grep -q 'Persistence Mode.*Enabled'"
        result = self.execute_batch(hosts, cmd, sudo=False)
        return all(r.success for r in result.results.values())
