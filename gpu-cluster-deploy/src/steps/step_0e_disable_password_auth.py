"""
步骤0e: 禁止SSH密码登录

在SSH免密配置完成后执行，禁止密码登录以增强集群安全性。
修改 /etc/ssh/sshd_config 和 /etc/ssh/sshd_config.d/ 下的配置文件。
"""

from typing import List
from src.steps.base import BaseStep, StepResult, StepStatus


class DisablePasswordAuth(BaseStep):
    """禁止SSH密码登录"""

    step_id = "0e"
    step_name = "禁止SSH密码登录"
    step_description = "配置禁止SSH密码登录，增强集群安全性"
    requires_sudo = True
    supports_batch = True

    def is_configured(self, host: str) -> tuple:
        """
        检查SSH密码登录是否已禁止

        检查 /etc/ssh/sshd_config 和 /etc/ssh/sshd_config.d/ 下
        所有配置文件中 PasswordAuthentication 的设置。

        Args:
            host: 主机地址

        Returns:
            tuple[bool, str]: (是否已配置, 检查详情)
        """
        # 1. 检查主配置文件 sshd_config
        # 使用 grep -i 忽略大小写，匹配 PasswordAuthentication 行
        # 如果存在 PasswordAuthentication no（忽略注释行），则视为已配置
        check_main = "grep -ri '^PasswordAuthentication' /etc/ssh/sshd_config 2>/dev/null"
        result_main = self.execute_on_host(host, check_main, sudo=True)

        main_configured = False
        main_value = ""
        if result_main.get("success") and result_main.get("stdout", "").strip():
            lines = result_main["stdout"].strip().split('\n')
            for line in lines:
                line_lower = line.strip().lower()
                if 'passwordauthentication' in line_lower and not line_lower.startswith('#'):
                    if 'no' in line_lower.split()[-1]:
                        main_configured = True
                    main_value = line.strip()

        # 2. 检查 sshd_config.d/ 目录下的配置文件
        check_subdir = "grep -ri '^PasswordAuthentication' /etc/ssh/sshd_config.d/ 2>/dev/null"
        result_subdir = self.execute_on_host(host, check_subdir, sudo=True)

        subdir_issues = []
        if result_subdir.get("success") and result_subdir.get("stdout", "").strip():
            lines = result_subdir["stdout"].strip().split('\n')
            for line in lines:
                line_lower = line.strip().lower()
                if 'passwordauthentication' in line_lower and not line_lower.startswith('#'):
                    if 'yes' in line_lower.split()[-1]:
                        # sshd_config.d 中的 yes 会覆盖主配置的 no
                        subdir_issues.append(line.strip())

        # 3. 综合判断
        # 如果主配置已设为 no，且子目录没有 yes 覆盖，则视为已配置
        if main_configured and not subdir_issues:
            return True, f"SSH密码登录已禁止（{main_value}）"

        if subdir_issues:
            return False, f"sshd_config.d 中存在覆盖配置: {subdir_issues}"

        if not main_configured and main_value:
            return False, f"PasswordAuthentication 未设为 no（当前: {main_value}）"

        # 没有显式配置时，默认值为 yes（Ubuntu 默认允许密码登录）
        return False, "PasswordAuthentication 未配置（默认允许密码登录）"

    def execute(self, hosts: List[str]) -> StepResult:
        """执行禁止SSH密码登录配置"""
        # 1. 修改主配置文件 /etc/ssh/sshd_config
        self.logger.info(f"[{self.step_id}] 修改 /etc/ssh/sshd_config ...")

        # 替换 PasswordAuthentication yes 为 no
        sed_main_cmd = (
            "sed -i '/PasswordAuthentication/s/yes/no/g' /etc/ssh/sshd_config"
        )
        self.execute_batch(hosts, sed_main_cmd, sudo=True)

        # 如果没有 PasswordAuthentication 行，添加一行
        ensure_main_cmd = (
            "grep -qi '^PasswordAuthentication' /etc/ssh/sshd_config || "
            "echo 'PasswordAuthentication no' >> /etc/ssh/sshd_config"
        )
        self.execute_batch(hosts, ensure_main_cmd, sudo=True)

        # 2. 修改 sshd_config.d/ 目录下的覆盖配置
        self.logger.info(f"[{self.step_id}] 修改 sshd_config.d/ 下的覆盖配置 ...")

        # 查找 sshd_config.d 目录下所有包含 PasswordAuthentication yes 的文件并修改
        # 常见文件: 50-cloud-init.conf, 50-ubuntu-cloud-init.conf 等
        fix_subdir_cmd = (
            "for f in /etc/ssh/sshd_config.d/*.conf; do "
            "  if [ -f \"$f\" ] && grep -qi '^PasswordAuthentication.*yes' \"$f\"; then "
            "    sed -i '/PasswordAuthentication/s/yes/no/g' \"$f\"; "
            "  fi; "
            "done"
        )
        self.execute_batch(hosts, fix_subdir_cmd, sudo=True)

        # 特别处理 50-cloud-init.conf（云环境常见）
        fix_cloud_init_cmd = (
            "test -f /etc/ssh/sshd_config.d/50-cloud-init.conf && "
            "sed -i '/PasswordAuthentication/s/yes/no/g' /etc/ssh/sshd_config.d/50-cloud-init.conf || true"
        )
        self.execute_batch(hosts, fix_cloud_init_cmd, sudo=True)

        # 3. 重启 sshd 服务
        self.logger.info(f"[{self.step_id}] 重启 sshd 服务 ...")
        restart_cmd = "systemctl restart sshd"
        restart_result = self.execute_batch(hosts, restart_cmd, sudo=True)

        # 4. 验证配置生效
        self.logger.info(f"[{self.step_id}] 验证配置 ...")
        verify_cmd = "grep -ri '^PasswordAuthentication' /etc/ssh/sshd_config /etc/ssh/sshd_config.d/ 2>/dev/null"
        verify_result = self.execute_batch(hosts, verify_cmd, sudo=True)

        success_hosts = []
        failed_hosts = []
        for host, res in verify_result.results.items():
            if res.success and res.stdout.strip():
                # 检查所有行都是 no
                lines = res.stdout.strip().split('\n')
                all_no = True
                for line in lines:
                    if 'passwordauthentication' in line.lower():
                        parts = line.strip().split()
                        if parts and parts[-1].lower() != 'no':
                            all_no = False
                            break
                if all_no:
                    success_hosts.append(host)
                else:
                    failed_hosts.append(host)
            else:
                # 没有输出说明没有显式配置，但我们在步骤1中已经添加了，所以应该有输出
                failed_hosts.append(host)

        # 检查 sshd 重启结果
        for host, res in restart_result.results.items():
            if not res.success and host not in failed_hosts:
                failed_hosts.append(host)

        if not failed_hosts:
            return StepResult(
                step_id=self.step_id,
                step_name=self.step_name,
                status=StepStatus.SUCCESS,
                message=f"SSH密码登录已禁止，成功: {len(success_hosts)}/{len(hosts)}",
                host_results=verify_result.results
            )
        else:
            return StepResult(
                step_id=self.step_id,
                step_name=self.step_name,
                status=StepStatus.FAILED if not success_hosts else StepStatus.FAILED,
                message=f"SSH密码登录禁止完成，成功: {len(success_hosts)}/{len(hosts)}，失败: {failed_hosts}",
                host_results=verify_result.results
            )

    def post_check(self, hosts: List[str]) -> bool:
        """验证SSH密码登录已禁止"""
        # 检查 sshd 实际生效的配置
        cmd = (
            "sshd -T 2>/dev/null | grep -i 'passwordauthentication' | awk '{print $2}'"
        )
        result = self.execute_batch(hosts, cmd, sudo=False)

        all_configured = True
        for host, res in result.results.items():
            if res.success:
                value = res.stdout.strip().lower()
                if value != 'no':
                    self.logger.warning(f"[{host}] PasswordAuthentication = {value}（期望 no）")
                    all_configured = False
            else:
                # sshd -T 可能需要 root 权限，降级检查配置文件
                fallback_cmd = "grep -ri '^PasswordAuthentication' /etc/ssh/sshd_config /etc/ssh/sshd_config.d/ 2>/dev/null"
                fallback_result = self.execute_on_host(host, fallback_cmd, sudo=True)
                if fallback_result.get("success") and fallback_result.get("stdout", "").strip():
                    lines = fallback_result["stdout"].strip().split('\n')
                    for line in lines:
                        if 'passwordauthentication' in line.lower():
                            parts = line.strip().split()
                            if parts and parts[-1].lower() != 'no':
                                all_configured = False
                                break
                else:
                    all_configured = False

        return all_configured
