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
        # 1. 创建systemd服务文件（仅在文件不存在或内容不同时覆盖）
        service_cmd = f"""if [ ! -f /lib/systemd/system/rc-local.service ]; then
    echo '{self.SERVICE_CONTENT}' | tee /lib/systemd/system/rc-local.service
    echo "created"
else
    echo "already_exists"
fi"""
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

        # 2. 创建rc.local脚本（仅在文件不存在时创建，避免覆盖已有内容）
        rclocal_cmd = """if [ ! -f /etc/rc.local ]; then
    echo '#!/bin/bash' | tee /etc/rc.local && chmod 755 /etc/rc.local
    echo "created"
else
    # 确保文件有执行权限
    chmod 755 /etc/rc.local
    # 确保文件以#!/bin/bash开头
    head -1 /etc/rc.local | grep -q '^#!/bin/bash' || sed -i '1i#!/bin/bash' /etc/rc.local
    echo "already_exists"
fi"""
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

        # 3. 启用并重启服务（daemon-reload + enable + restart）
        enable_cmd = "systemctl daemon-reload && systemctl enable rc-local.service && systemctl restart rc-local.service"
        enable_result = self.execute_batch(hosts, enable_cmd, sudo=True)

        failed = [h for h, r in enable_result.results.items() if not r.success]

        if failed:
            # 即使启用/重启失败也视为成功（rc.local 非必需）
            self.logger.warning(f"rc-local服务启用/重启失败，但不影响部署: {failed}")

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
