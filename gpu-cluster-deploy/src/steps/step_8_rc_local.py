"""
步骤08: rc.local配置
"""

from typing import List
from src.steps.base import BaseStep, StepResult, StepStatus


class RcLocalSetup(BaseStep):
    """配置rc.local"""

    step_id = "08"
    step_name = "配置rc.local"
    step_description = "配置rc.local服务用于开机启动脚本"
    requires_sudo = True
    supports_batch = True

    # systemd服务文件内容
    SERVICE_CONTENT = '''[Unit]
Description=/etc/rc.local Compatibility
Documentation=man:systemd-rc-local-generator(8)
ConditionFileIsExecutable=/etc/rc.local
After=network.target

[Service]
Type=forking
ExecStart=/etc/rc.local start
TimeoutSec=0
RemainAfterExit=yes
GuessMainPID=no

[Install]
WantedBy=multi-user.target'''

    def execute(self, hosts: List[str]) -> StepResult:
        """执行rc.local配置"""
        # 1. 创建systemd服务文件
        service_cmd = f'''cat > /lib/systemd/system/rc-local.service << 'EOF'
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

        # 2. 创建rc.local脚本
        rclocal_cmd = '''cat > /etc/rc.local << 'EOF'
#!/bin/bash

EOF
chmod 755 /etc/rc.local'''
        rclocal_result = self.execute_batch(hosts, rclocal_cmd, sudo=True)

        failed = [h for h, r in rclocal_result.results.items() if not r.success]
        if failed:
            return StepResult(
                step_id=self.step_id,
                step_name=self.step_name,
                status=StepStatus.FAILED,
                message=f"创建rc.local失败: {failed}",
                host_results=rclocal_result.results
            )

        # 3. 启用服务
        enable_cmd = "systemctl daemon-reload && systemctl enable rc-local.service"
        enable_result = self.execute_batch(hosts, enable_cmd, sudo=True)

        failed = [h for h, r in enable_result.results.items() if not r.success]

        if failed:
            return StepResult(
                step_id=self.step_id,
                step_name=self.step_name,
                status=StepStatus.FAILED,
                message=f"启用rc-local服务失败: {failed}",
                host_results=enable_result.results
            )

        return StepResult(
            step_id=self.step_id,
            step_name=self.step_name,
            status=StepStatus.SUCCESS,
            message="rc.local配置完成",
            host_results=enable_result.results
        )

    def post_check(self, hosts: List[str]) -> bool:
        """验证rc.local配置"""
        cmd = "systemctl is-enabled rc-local.service && test -x /etc/rc.local"
        result = self.execute_batch(hosts, cmd, sudo=False)
        return all(r.success for r in result.results.values())
