"""
步骤0b: 网络连通性检查

在部署开始前检查所有主机的网络连通性
"""

import os
from datetime import datetime
from typing import Dict, List, Any

from src.steps.base import BaseStep, StepResult, StepStatus
from src.network.connectivity_checker import ConnectivityChecker, generate_connectivity_report


class NetworkCheckStep(BaseStep):
    """网络连通性检查步骤"""

    step_id = "0b"
    step_name = "网络连通性检查"
    step_description = "检查所有主机的IP层、DNS、HTTP连通性"
    requires_sudo = False
    can_skip = True  # 可以跳过（离线环境）
    skip_if_configured = False  # 每次都执行，不检查配置状态
    max_retries = 1

    def __init__(self, config, ssh_manager, batch_executor, logger=None, versions=None):
        super().__init__(config, ssh_manager, batch_executor, logger, versions)
        self.checker = ConnectivityChecker(ssh_manager, batch_executor, logger)

    def execute(self, hosts: List[str]) -> StepResult:
        """执行网络连通性检查"""
        self.logger.info(f"[{self.step_id}] 开始网络连通性检查...")
        self.logger.info(f"[{self.step_id}] 检查 {len(hosts)} 台主机")

        # 准备主机认证信息
        host_auth_list = self._prepare_host_auth(hosts)

        # 执行检查
        results = self.checker.check_all_hosts(host_auth_list)

        # 统计结果
        all_passed_count = sum(1 for r in results.values() if r.all_passed)
        partial_passed_count = sum(1 for r in results.values() if r.partial_passed)
        failed_count = len(hosts) - all_passed_count - partial_passed_count

        # 生成报告
        report = generate_connectivity_report(results)

        # 记录到文件
        report_path = self._save_report(report)

        # 生成警告消息
        warnings = []
        for host, result in results.items():
            if not result.all_passed:
                issues = self._get_issues(result)
                warnings.append(f"{host}: {issues}")

        # 结果消息
        message = f"网络检查完成: {all_passed_count} 全部通过, {partial_passed_count} 部分通过, {failed_count} 失败"

        self.logger.info(f"[{self.step_id}] {message}")
        self.logger.info(f"[{self.step_id}] 报告已保存: {report_path}")

        return StepResult(
            step_id=self.step_id,
            step_name=self.step_name,
            status=StepStatus.SUCCESS,  # 网络检查不阻断部署
            message=message,
            details={
                "all_passed_count": all_passed_count,
                "partial_passed_count": partial_passed_count,
                "failed_count": failed_count,
                "report_path": report_path,
                "results": {h: r.to_dict() for h, r in results.items()}
            },
            warnings=warnings
        )

    def _prepare_host_auth(self, hosts: List[str]) -> List[tuple]:
        """准备主机认证信息列表（使用登录用户）"""
        host_auth_list = []

        for host in hosts:
            # 使用登录用户（必须在节点配置中指定）
            login_user = self._get_login_user(host)
            login_password = self._get_login_password(host)
            login_private_key = self._get_login_private_key(host)

            if not login_user:
                # 尝试从 jumphost.node_auth 获取默认认证
                if self.config.jumphost and self.config.jumphost.node_auth:
                    login_user = self.config.jumphost.node_auth.username
                    login_password = self.config.jumphost.node_auth.password
                    login_private_key = self.config.jumphost.node_auth.private_key

            if not login_user:
                # 最后的默认值
                login_user = "ubuntu"

            host_auth_list.append((host, login_user, login_password))

        return host_auth_list

    def _save_report(self, report: str) -> str:
        """保存报告到文件"""
        # 确保报告目录存在
        report_dir = "reports"
        os.makedirs(report_dir, exist_ok=True)

        # 使用时间戳命名
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = os.path.join(report_dir, f"network_check_{timestamp}.md")

        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report)

        return report_path

    def _get_issues(self, result) -> str:
        """生成问题摘要"""
        issues = []
        if not result.ip_check.success:
            issues.append(f"IP({result.ip_check.message})")
        if not result.dns_check.success:
            issues.append(f"DNS({result.dns_check.message})")
        if not result.http_check.success:
            issues.append(f"HTTP({result.http_check.message})")
        return "; ".join(issues)

    def is_configured(self, host: str) -> tuple:
        """
        检查网络连通性检查是否已执行

        Args:
            host: 主机地址

        Returns:
            tuple[bool, str]: (是否已配置, 检查详情)
        """
        # 网络检查是一次性检查，检查报告文件是否存在
        import glob
        report_files = glob.glob("reports/network_check_*.md")
        if report_files:
            return True, "网络检查报告已存在"
        return True, "网络检查（一次性检查，无持久配置）"

    def pre_check(self, hosts: List[str]) -> bool:
        """前置检查 - 检查是否有主机"""
        if not hosts:
            self.logger.warning(f"[{self.step_id}] 没有主机需要检查")
            return False
        return True
