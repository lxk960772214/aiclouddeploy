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

        # 2. 写入新配置
        limits_cmd = f'''cat > /etc/security/limits.conf << 'EOF'
{self.LIMITS_CONTENT}
EOF'''
        limits_result = self.execute_batch(hosts, limits_cmd, sudo=True)

        failed = [h for h, r in limits_result.results.items() if not r.success]
        if failed:
            return StepResult(
                step_id=self.step_id,
                step_name=self.step_name,
                status=StepStatus.FAILED,
                message=f"写入limits.conf失败: {failed}",
                host_results=limits_result.results
            )

        # 3. 配置systemd用户会话限制
        systemd_limit_cmd = '''mkdir -p /etc/systemd/system/user@.service.d
cat > /etc/systemd/system/user@.service.d/limits.conf << 'EOF'
[Service]
LimitNOFILE=1000000
LimitNPROC=2000000
EOF'''
        self.execute_batch(hosts, systemd_limit_cmd, sudo=True)

        # 4. 配置pam_limits
        pam_cmd = '''grep -q "pam_limits.so" /etc/pam.d/common-session || echo "session required pam_limits.so" >> /etc/pam.d/common-session'''
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
            host_results=verify_result.results
        )

    def post_check(self, hosts: List[str]) -> bool:
        """验证配置文件"""
        cmd = "grep -q 'nofile 1000000' /etc/security/limits.conf"
        result = self.execute_batch(hosts, cmd, sudo=False)
        return all(r.success for r in result.results.values())
