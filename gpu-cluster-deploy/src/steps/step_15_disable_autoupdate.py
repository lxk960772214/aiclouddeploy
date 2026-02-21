"""
步骤15: 禁止系统自动更新
"""

from typing import List
from src.steps.base import BaseStep, StepResult, StepStatus


class DisableAutoUpdate(BaseStep):
    """禁止系统自动更新"""

    step_id = "15"
    step_name = "禁止系统自动更新"
    step_description = "禁止系统自动更新和内核更新"
    requires_sudo = True
    supports_batch = True

    def execute(self, hosts: List[str]) -> StepResult:
        """执行禁止自动更新"""
        # 1. 删除unattended-upgrades配置
        rm_cmd = "rm -f /etc/apt/apt.conf.d/50unattended-upgrades"
        self.execute_batch(hosts, rm_cmd, sudo=True)

        # 2. 停止并禁用unattended-upgrades服务
        service_cmd = "systemctl stop unattended-upgrades.service && systemctl disable unattended-upgrades.service"
        self.execute_batch(hosts, service_cmd, sudo=True)

        # 3. 修改periodic配置
        periodic_cmd = '''sed -i '/Update-Package-Lists/s/1/0/' /etc/apt/apt.conf.d/10periodic
sed -i '/Unattended-Upgrade/s/1/0/' /etc/apt/apt.conf.d/10periodic
sed -i '/Update-Package-Lists/s/1/0/' /etc/apt/apt.conf.d/20auto-upgrades
sed -i '/Unattended-Upgrade/s/1/0/' /etc/apt/apt.conf.d/20auto-upgrades'''
        self.execute_batch(hosts, periodic_cmd, sudo=True)

        # 4. 创建内核锁定配置
        kernel_prefs = '''Package: linux-*
Pin: version *
Pin-Priority: -1'''
        prefs_cmd = f'''mkdir -p /etc/apt/preferences.d
cat > /etc/apt/preferences.d/nolinuxupgrades << 'EOF'
{kernel_prefs}
EOF'''
        self.execute_batch(hosts, prefs_cmd, sudo=True)

        # 5. 锁定内核相关包
        lock_cmd = '''for pkg in $(dpkg -l | grep -E "linux-(image|headers|modules)" | grep -v "linux-(generic|headers-generic|image-generic)" | awk "{print \\$2}" | grep generic); do
    apt-mark hold $pkg 2>/dev/null || true
done'''
        self.execute_batch(hosts, lock_cmd, sudo=True)

        # 6. 验证
        verify_cmd = "apt-mark showhold | grep linux | wc -l"
        verify_result = self.execute_batch(hosts, verify_cmd, sudo=False)

        return StepResult(
            step_id=self.step_id,
            step_name=self.step_name,
            status=StepStatus.SUCCESS,
            message="禁止系统自动更新配置完成",
            host_results=verify_result.results
        )

    def post_check(self, hosts: List[str]) -> bool:
        """验证配置"""
        cmd = "systemctl is-enabled unattended-upgrades.service 2>/dev/null || echo 'disabled'"
        result = self.execute_batch(hosts, cmd, sudo=False)
        return all('disabled' in r.stdout.lower() for r in result.results.values())
