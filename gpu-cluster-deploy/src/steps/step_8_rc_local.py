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
        # 1. 创建systemd服务文件（使用 echo | tee 替代 heredoc）
        service_cmd = f"echo '{self.SERVICE_CONTENT}' | sudo tee /lib/systemd/system/rc-local.service"
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

        # 2. 创建rc.local脚本（使用 echo | tee）
        rclocal_cmd = "echo '#!/bin/bash' | sudo tee /etc/rc.local && sudo chmod 755 /etc/rc.local"
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
            # 即使启用失败也视为成功（rc.local 非必需）
            self.logger.warning(f"rc-local服务启用失败，但不影响部署: {failed}")

        return StepResult(
            step_id=self.step_id,
            step_name=self.step_name,
            status=StepStatus.SUCCESS,
            message="rc.local配置完成",
            host_results={h: {"success": r.success, "stdout": r.stdout, "stderr": r.stderr}
                         for h, r in enable_result.results.items()}
        )

    def is_configured(self, host: str) -> tuple:
        """
        检查rc.local是否已配置

        Args:
            host: 主机地址

        Returns:
            tuple[bool, str]: (是否已配置, 检查详情)
        """
        # 检查rc.local文件是否存在且可执行
        result = self.execute_on_host(host, "test -x /etc/rc.local && echo 'exists' || echo 'not_found'", sudo=False)

        if "not_found" in result.get("stdout", ""):
            return False, "rc.local文件不存在"

        # 检查rc-local服务是否启用
        service_result = self.execute_on_host(host, "systemctl is-enabled rc-local.service 2>/dev/null || echo 'disabled'", sudo=False)

        if "enabled" in service_result.get("stdout", ""):
            return True, "rc.local已配置且服务已启用"

        return True, "rc.local文件已存在（服务未启用）"

    def post_check(self, hosts: List[str]) -> bool:
        """验证rc.local配置"""
        cmd = "systemctl is-enabled rc-local.service && test -x /etc/rc.local"
        result = self.execute_batch(hosts, cmd, sudo=False)
        return all(r.success for r in result.results.values())
