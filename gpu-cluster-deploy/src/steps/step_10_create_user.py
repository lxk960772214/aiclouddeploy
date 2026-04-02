"""
步骤10: 创建ubuntu用户
"""

from typing import List
from src.steps.base import BaseStep, StepResult, StepStatus


class CreateUser(BaseStep):
    """创建ubuntu用户"""

    step_id = "10"
    step_name = "创建ubuntu用户"
    step_description = "创建ubuntu用户（uid 1001, gid 1001），配置免密sudo"
    requires_sudo = True
    supports_batch = True

    def is_configured(self, host: str) -> tuple:
        """
        检查ubuntu用户是否已创建并配置sudo免密

        Args:
            host: 主机地址

        Returns:
            tuple[bool, str]: (是否已配置, 检查详情)
        """
        # 检查ubuntu用户是否存在
        check_user_cmd = "id ubuntu 2>/dev/null && echo 'exists' || echo 'not_exists'"
        user_result = self.execute_on_host(host, check_user_cmd, sudo=False)

        if not user_result.get("success") or "not_exists" in user_result.get("stdout", ""):
            return False, "ubuntu用户不存在"

        # 检查sudo免密是否已配置
        check_sudo_cmd = "sudo -u ubuntu sudo -n true 2>/dev/null && echo 'ok' || echo 'need_password'"
        sudo_result = self.execute_on_host(host, check_sudo_cmd, sudo=False)

        if sudo_result.get("success") and "ok" in sudo_result.get("stdout", ""):
            return True, "ubuntu用户已创建且sudo免密已配置"

        return False, "ubuntu用户已存在但sudo免密未配置"

    def execute(self, hosts: List[str]) -> StepResult:
        """执行用户创建"""
        results = {}

        # 默认不创建ubuntu用户，除非配置中明确指定
        # 检查是否有配置要求创建用户
        create_user_enabled = False
        if self.config and hasattr(self.config, 'create_users'):
            create_user_enabled = self.config.create_users

        # 如果没有明确要求创建用户，跳过此步骤
        if not create_user_enabled:
            self.logger.info("默认不创建ubuntu用户，跳过此步骤（如需创建，请在配置中设置 create_users: true）")
            return StepResult(
                step_id=self.step_id,
                step_name=self.step_name,
                status=StepStatus.SUCCESS,
                message="跳过用户创建（默认不创建，如需创建请在配置中设置 create_users: true）",
                host_results=results
            )

        # 1. 检查用户是否已存在
        check_cmd = "id ubuntu 2>/dev/null && echo 'exists' || echo 'not_exists'"
        check_result = self.execute_batch(hosts, check_cmd, sudo=False)

        need_create = []
        already_exists = []

        for host, res in check_result.results.items():
            if res.success and "exists" in res.stdout and "not_exists" not in res.stdout:
                already_exists.append(host)
            else:
                need_create.append(host)

        self.logger.info(f"需要创建用户的节点: {len(need_create)}，已存在: {len(already_exists)}")

        if need_create:
            # 2. 创建用户组
            group_cmd = "groupadd -g 1001 ubuntu 2>/dev/null || true"
            self.execute_batch(need_create, group_cmd, sudo=True)

            # 3. 创建用户
            user_cmd = "useradd -u 1001 -g 1001 -m -s /bin/bash ubuntu"
            user_result = self.execute_batch(need_create, user_cmd, sudo=True)

            for host, res in user_result.results.items():
                if not res.success:
                    results[host] = {"success": False, "error": f"创建用户失败: {res.stderr}"}

            # 4. 设置免密sudo
            sudo_cmd = "echo 'ubuntu ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/ubuntu && chmod 440 /etc/sudoers.d/ubuntu"
            self.execute_batch(need_create, sudo_cmd, sudo=True)

            # 5. 创建.ssh目录
            ssh_dir_cmd = "mkdir -p /home/ubuntu/.ssh && chown ubuntu:ubuntu /home/ubuntu/.ssh && chmod 700 /home/ubuntu/.ssh"
            self.execute_batch(need_create, ssh_dir_cmd, sudo=True)

        # 验证
        verify_cmd = "id ubuntu"
        verify_result = self.execute_batch(hosts, verify_cmd, sudo=False)

        success_hosts = []
        failed_hosts = []

        for host, res in verify_result.results.items():
            if res.success:
                success_hosts.append(host)
                results[host] = {"success": True}
            else:
                failed_hosts.append(host)
                results[host] = {"success": False, "error": "验证失败"}

        if failed_hosts:
            return StepResult(
                step_id=self.step_id,
                step_name=self.step_name,
                status=StepStatus.FAILED,
                message=f"用户创建失败: {failed_hosts}",
                host_results=results
            )

        return StepResult(
            step_id=self.step_id,
            step_name=self.step_name,
            status=StepStatus.SUCCESS,
            message=f"ubuntu用户配置完成，成功: {len(success_hosts)}/{len(hosts)}",
            host_results=results
        )

    def post_check(self, hosts: List[str]) -> bool:
        """验证用户创建"""
        cmd = "id ubuntu && sudo -u ubuntu sudo -n true"
        result = self.execute_batch(hosts, cmd, sudo=False)
        return all(r.success for r in result.results.values())
