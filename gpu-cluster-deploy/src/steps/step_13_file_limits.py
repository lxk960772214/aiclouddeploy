"""
步骤13: 设置文件描述符
"""

from typing import List
from src.steps.base import BaseStep, StepResult, StepStatus


class FileLimits(BaseStep):
    """设置文件描述符限制"""

    step_id = "13"
    step_name = "设置文件描述符"
    step_description = "设置系统文件描述符限制"
    requires_sudo = True
    supports_batch = True

    def is_configured(self, host: str) -> tuple:
        """
        检查文件描述符限制是否已配置

        Args:
            host: 主机地址

        Returns:
            tuple[bool, str]: (是否已配置, 检查详情)
        """
        # 1. 检查 limits.conf 中的 nofile 配置
        check_limits_cmd = "grep -c 'nofile 1000000' /etc/security/limits.conf 2>/dev/null || echo 0"
        limits_result = self.execute_on_host(host, check_limits_cmd, sudo=False)

        if limits_result.get("success"):
            try:
                count = int(limits_result.get("stdout", "0").strip())
                if count < 2:  # 至少需要 soft 和 hard 两条
                    return False, "limits.conf 中 nofile 配置不完整"
            except ValueError:
                return False, "limits.conf 检查失败"

        # 2. 检查 systemd 用户会话限制配置
        check_systemd_cmd = "test -f /etc/systemd/system/user@.service.d/limits.conf && grep -q 'LimitNOFILE=1000000' /etc/systemd/system/user@.service.d/limits.conf"
        systemd_result = self.execute_on_host(host, check_systemd_cmd, sudo=False)

        if not systemd_result.get("success"):
            return False, "systemd 用户会话限制未配置"

        # 3. 检查 PAM 配置
        check_pam_cmd = "grep -q 'pam_limits.so' /etc/pam.d/common-session"
        pam_result = self.execute_on_host(host, check_pam_cmd, sudo=False)

        if not pam_result.get("success"):
            return False, "PAM limits 配置未启用"

        return True, "文件描述符限制已配置（nofile=1000000）"

    # limits.conf 内容
    LIMITS_CONTENT = '''* soft nofile 1000000
* hard nofile 1000000
* soft nproc 2000000
* hard nproc 2000000
* soft memlock unlimited
* hard memlock unlimited
* soft stack unlimited
* hard stack unlimited
root soft nofile 1000000
root hard nofile 1000000
root soft nproc 2000000
root hard nproc 2000000
root soft memlock unlimited
root hard memlock unlimited
root soft stack unlimited
root hard stack unlimited'''

    def execute(self, hosts: List[str]) -> StepResult:
        """执行文件描述符设置"""
        # 1. 备份原配置
        backup_cmd = "cp /etc/security/limits.conf /etc/security/limits.conf.bak 2>/dev/null || true"
        self.execute_batch(hosts, backup_cmd, sudo=True)

        # 2. 写入新配置（逐行写入，避免echo -e兼容性问题）
        self.logger.info("写入limits.conf配置...")
        for host in hosts:
            # 清空文件并写入新内容
            self.execute_on_host(host, "sudo truncate -s 0 /etc/security/limits.conf", sudo=True)
            for line in self.LIMITS_CONTENT.strip().split('\n'):
                self.execute_on_host(host, f"echo '{line}' | sudo tee -a /etc/security/limits.conf", sudo=False)

        # 3. 配置systemd用户会话限制（逐行写入）
        systemd_lines = [
            "[Service]",
            "LimitNOFILE=1000000",
            "LimitNPROC=2000000"
        ]
        for host in hosts:
            self.execute_on_host(host, "sudo mkdir -p /etc/systemd/system/user@.service.d", sudo=True)
            self.execute_on_host(host, "sudo truncate -s 0 /etc/systemd/system/user@.service.d/limits.conf", sudo=True)
            for line in systemd_lines:
                self.execute_on_host(host, f"echo '{line}' | sudo tee -a /etc/systemd/system/user@.service.d/limits.conf", sudo=False)

        # 4. 配置pam_limits
        pam_cmd = '''grep -q "pam_limits.so" /etc/pam.d/common-session || echo "session required pam_limits.so" | sudo tee -a /etc/pam.d/common-session'''
        self.execute_batch(hosts, pam_cmd, sudo=True)

        # 5. 验证配置文件
        verify_cmd = "grep 'nofile' /etc/security/limits.conf | head -2"
        verify_result = self.execute_batch(hosts, verify_cmd, sudo=False)

        success_count = sum(1 for r in verify_result.results.values() if r.success)

        return StepResult(
            step_id=self.step_id,
            step_name=self.step_name,
            status=StepStatus.SUCCESS,
            message=f"文件描述符设置完成（需要重启生效）",
            details={"limits_content": self.LIMITS_CONTENT},
            host_results={h: {"success": r.success, "stdout": r.stdout}
                         for h, r in verify_result.results.items()}
        )

    def post_check(self, hosts: List[str]) -> bool:
        """验证配置文件"""
        cmd = "grep -q 'nofile 1000000' /etc/security/limits.conf"
        result = self.execute_batch(hosts, cmd, sudo=False)
        return all(r.success for r in result.results.values())
