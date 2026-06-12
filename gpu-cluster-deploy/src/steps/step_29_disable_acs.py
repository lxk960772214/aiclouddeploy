"""
步骤29: 关闭ACS
"""

from typing import List
from src.steps.base import BaseStep, StepResult, StepStatus


class DisableACS(BaseStep):
    """关闭ACS"""

    step_id = "29"
    step_name = "关闭ACS"
    step_description = "禁用PCI ACS以优化GPU Direct RDMA"
    requires_sudo = True
    supports_batch = True

    # ACS禁用脚本
    ACS_SCRIPT = '''#!/bin/bash
# Copyright (c) 2018, NVIDIA CORPORATION. All rights reserved.

if [ "$EUID" -ne 0 ]; then
  echo "ERROR: $0 must be run as root"
  exit 1
fi

for BDF in $(lspci -d "*:*:*" | awk '{print $1}'); do
    setpci -v -s ${BDF} ECAP_ACS+0x6.w > /dev/null 2>&1
    if [ $? -ne 0 ]; then
        continue
    fi

    logger "Disabling ACS on $(lspci -s ${BDF})"
    setpci -v -s ${BDF} ECAP_ACS+0x6.w=0000
    if [ $? -ne 0 ]; then
        logger "Error disabling ACS on ${BDF}"
        continue
    fi
    NEW_VAL=$(setpci -v -s ${BDF} ECAP_ACS+0x6.w | awk '{print $NF}')
    if [ "${NEW_VAL}" != "0000" ]; then
        logger "Failed to disable ACS on ${BDF}"
        continue
    fi
done
exit 0
'''

    def execute(self, hosts: List[str]) -> StepResult:
        """执行ACS禁用"""
        # 1. 创建ACS禁用脚本
        script_path = "/usr/local/bin/disable_acs.sh"
        script_cmd = f'''cat > {script_path} << 'SCRIPT_EOF'
{self.ACS_SCRIPT}
SCRIPT_EOF
chmod +x {script_path}'''
        script_result = self.execute_batch(hosts, script_cmd, sudo=True)

        failed = [h for h, r in script_result.results.items() if not r.success]
        if failed:
            return StepResult(
                step_id=self.step_id,
                step_name=self.step_name,
                status=StepStatus.FAILED,
                message=f"创建ACS脚本失败: {failed}",
                host_results=script_result.results
            )

        # 2. 执行ACS禁用
        exec_result = self.execute_batch(hosts, f"bash {script_path}", sudo=True)

        # 3. 添加到rc.local（开机自动执行）
        rclocal_cmd = f'''grep -q "disable_acs.sh" /etc/rc.local || sed -i '/^#!/a bash {script_path}' /etc/rc.local'''
        self.execute_batch(hosts, rclocal_cmd, sudo=True)

        return StepResult(
            step_id=self.step_id,
            step_name=self.step_name,
            status=StepStatus.SUCCESS,
            message="ACS禁用配置完成",
            host_results=exec_result.results
        )

    def is_configured(self, host: str) -> tuple:
        """
        检查ACS是否已禁用

        Args:
            host: 主机地址

        Returns:
            tuple[bool, str]: (是否已配置, 检查详情)
        """
        # 检查脚本是否存在
        result = self.execute_on_host(host, "test -x /usr/local/bin/disable_acs.sh && echo 'script_exists' || echo 'no_script'", sudo=False)

        if "script_exists" not in result.get("stdout", ""):
            return False, "ACS禁用脚本不存在"

        # 检查ACS是否已禁用（当前状态）
        acs_result = self.execute_on_host(host, "lspci -vvv 2>/dev/null | grep -c 'ACSCtl.*SrcValid+' || echo 0", sudo=True, timeout=60)

        if acs_result.get("success"):
            stdout = acs_result.get("stdout", "0").strip()
            # 处理多行输出（如 "0\n0"），取第一行或求和
            try:
                # 如果是多行，每行代表一个设备的计数，求和
                lines = [l.strip() for l in stdout.split('\n') if l.strip()]
                count = sum(int(l) for l in lines if l.isdigit())
            except ValueError:
                count = 0
            if count == 0:
                return True, "ACS已禁用"
            else:
                return False, f"ACS未完全禁用: {count} 个设备启用"

        return True, "ACS禁用脚本已配置"

    def post_check(self, hosts: List[str]) -> bool:
        """验证ACS配置"""
        cmd = "test -x /usr/local/bin/disable_acs.sh"
        result = self.execute_batch(hosts, cmd, sudo=False)
        return all(r.success for r in result.results.values())
