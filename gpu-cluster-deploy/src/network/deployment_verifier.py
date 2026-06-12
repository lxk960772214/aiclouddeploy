"""
部署验证检查器 - 检查所有部署步骤是否完成
"""

import logging
from dataclasses import dataclass, field
from typing import Optional, List, Dict, TYPE_CHECKING
from enum import Enum

if TYPE_CHECKING:
    from src.ssh_manager import SSHManager
    from src.models.cluster import ClusterConfig

logger = logging.getLogger(__name__)


class CheckStatus(Enum):
    """检查状态"""
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    WARNING = "warning"


class CheckCategory(Enum):
    """检查类别"""
    SYSTEM = "system"
    NETWORK = "network"
    STORAGE = "storage"
    GPU = "gpu"
    SERVICE = "service"


@dataclass
class CheckItem:
    """检查项"""
    name: str
    category: CheckCategory
    description: str
    status: CheckStatus = CheckStatus.FAILED
    message: str = ""
    details: Dict = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "category": str(self.category),
            "description": self.description,
            "status": str(self.status),
            "message": self.message,
            "details": self.details
        }


@dataclass
class HostVerificationResult:
    """主机验证结果"""
    hostname: str
    ip: str
    checks: List[CheckItem] = field(default_factory=list)
    overall_status: CheckStatus = CheckStatus.FAILED
    completion_percent: float = 0.0

    def to_dict(self) -> Dict:
        return {
            "hostname": self.hostname,
            "ip": self.ip,
            "checks": [c.to_dict() for c in self.checks],
            "overall_status": str(self.overall_status),
            "completion_percent": round(self.completion_percent, 2)
        }


@dataclass
class DeploymentVerificationReport:
    """部署验证报告"""
    hosts: List[HostVerificationResult] = field(default_factory=list)
    summary: Dict = field(default_factory=dict)
    incomplete_items: List[Dict] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "hosts": [h.to_dict() for h in self.hosts],
            "summary": self.summary,
            "incomplete_items": self.incomplete_items
        }


class DeploymentVerifier:
    """部署验证检查器

    检查所有关键部署步骤是否完成
    """

    # 关键检查项定义
    CHECK_ITEMS = [
        # 系统基础检查
        {
            "name": "kernel_version",
            "category": CheckCategory.SYSTEM,
            "description": "检查内核版本",
            "command": "uname -r",
            "expected_pattern": r"\d+\.\d+",
        },
        {
            "name": "glibc_version",
            "category": CheckCategory.SYSTEM,
            "description": "检查glibc版本",
            "command": "ldd --version | head -1",
            "expected_pattern": r"GLIBC",
        },
        {
            "name": "ssh_version",
            "category": CheckCategory.SYSTEM,
            "description": "检查OpenSSH版本",
            "command": "ssh -V 2>&1",
            "expected_pattern": r"OpenSSH",
        },

        # 网络检查
        {
            "name": "rdma_tools",
            "category": CheckCategory.NETWORK,
            "description": "检查RDMA工具",
            "command": "which ibv_devinfo && which ib_write_bw",
            "expected_pattern": r"/usr/bin|/usr/sbin",
        },
        {
            "name": "rdma_devices",
            "category": CheckCategory.NETWORK,
            "description": "检查RDMA设备",
            "command": "ls /sys/class/infiniband/ | wc -l",
            "expected_output": lambda x: int(x.strip()) > 0,
        },
        {
            "name": "network_interfaces",
            "category": CheckCategory.NETWORK,
            "description": "检查网络接口",
            "command": "ip link show | grep -c 'state UP'",
            "expected_output": lambda x: int(x.strip()) >= 1,
        },

        # GPU检查
        {
            "name": "nvidia_driver",
            "category": CheckCategory.GPU,
            "description": "检查NVIDIA驱动",
            "command": "nvidia-smi -L 2>/dev/null || echo 'NOT_FOUND'",
            "expected_pattern": r"GPU \d+:",
        },
        {
            "name": "cuda_installed",
            "category": CheckCategory.GPU,
            "description": "检查CUDA安装",
            "command": "nvcc --version 2>/dev/null || echo 'NOT_FOUND'",
            "expected_pattern": r"release",
        },

        # 服务检查
        {
            "name": "ssh_service",
            "category": CheckCategory.SERVICE,
            "description": "检查SSH服务",
            "command": "systemctl is-active sshd || systemctl is-active ssh",
            "expected_output": lambda x: x.strip() == "active",
        },
        {
            "name": "nfs_client",
            "category": CheckCategory.SERVICE,
            "description": "检查NFS客户端",
            "command": "dpkg -l | grep nfs-common || rpm -qa | grep nfs-utils",
            "expected_pattern": r"nfs",
            "optional": True,
        },

        # 存储检查
        {
            "name": "storage_mounted",
            "category": CheckCategory.STORAGE,
            "description": "检查存储挂载",
            "command": "df -h | grep -E '/ssd|/data' || echo 'NOT_MOUNTED'",
            "expected_pattern": r"/ssd|/data",
            "optional": True,
        },
    ]

    def __init__(self, ssh_manager: Optional["SSHManager"] = None):
        """
        初始化验证器

        Args:
            ssh_manager: SSH管理器实例
        """
        self.ssh_manager = ssh_manager

    def check_item(self, host: str, item: Dict) -> CheckItem:
        """
        执行单个检查项

        Args:
            host: 主机名或IP
            item: 检查项定义

        Returns:
            CheckItem对象
        """
        check = CheckItem(
            name=item["name"],
            category=item["category"],
            description=item["description"]
        )

        if not self.ssh_manager:
            check.status = CheckStatus.SKIPPED
            check.message = "SSH管理器未初始化"
            return check

        try:
            result = self.ssh_manager.execute_on_host(
                host, item["command"], timeout=30
            )

            if not result.success:
                if item.get("optional"):
                    check.status = CheckStatus.SKIPPED
                    check.message = "可选检查项执行失败"
                else:
                    check.status = CheckStatus.FAILED
                    check.message = f"命令执行失败: {result.stderr}"
                return check

            output = result.stdout.strip()
            check.details["output"] = output

            # 检查预期输出
            if "expected_output" in item:
                expected_fn = item["expected_output"]
                if expected_fn(output):
                    check.status = CheckStatus.PASSED
                    check.message = "检查通过"
                else:
                    check.status = CheckStatus.FAILED
                    check.message = f"输出不符合预期: {output[:100]}"

            # 检查预期模式
            elif "expected_pattern" in item:
                import re
                pattern = item["expected_pattern"]
                if re.search(pattern, output):
                    check.status = CheckStatus.PASSED
                    check.message = "检查通过"
                else:
                    check.status = CheckStatus.FAILED
                    check.message = f"未找到预期模式: {output[:100]}"

            else:
                check.status = CheckStatus.PASSED
                check.message = "命令执行成功"

        except Exception as e:
            check.status = CheckStatus.FAILED
            check.message = f"检查异常: {e}"
            logger.error(f"检查项异常 [{host}] {item['name']}: {e}")

        return check

    def verify_host(self, host: str, ip: str = "",
                    check_categories: Optional[List[CheckCategory]] = None) -> HostVerificationResult:
        """
        验证单个主机

        Args:
            host: 主机名或IP
            ip: IP地址（可选）
            check_categories: 要检查的类别列表，None表示检查全部

        Returns:
            HostVerificationResult对象
        """
        result = HostVerificationResult(
            hostname=host,
            ip=ip or host
        )

        # 筛选检查项
        items_to_check = self.CHECK_ITEMS
        if check_categories:
            items_to_check = [
                item for item in self.CHECK_ITEMS
                if item["category"] in check_categories
            ]

        # 执行检查
        for item in items_to_check:
            check = self.check_item(host, item)
            result.checks.append(check)

        # 计算完成度
        total = len(result.checks)
        passed = sum(1 for c in result.checks if c.status == CheckStatus.PASSED)
        skipped = sum(1 for c in result.checks if c.status == CheckStatus.SKIPPED)

        # 排除跳过的项目
        effective_total = total - skipped
        if effective_total > 0:
            result.completion_percent = (passed / effective_total) * 100

        # 确定整体状态
        failed = sum(1 for c in result.checks
                     if c.status == CheckStatus.FAILED and not self._is_optional_check(c.name))

        if failed == 0:
            result.overall_status = CheckStatus.PASSED
        elif passed > 0:
            result.overall_status = CheckStatus.WARNING
        else:
            result.overall_status = CheckStatus.FAILED

        return result

    def _is_optional_check(self, name: str) -> bool:
        """检查是否为可选检查项"""
        for item in self.CHECK_ITEMS:
            if item["name"] == name:
                return item.get("optional", False)
        return False

    def verify_cluster(self, hosts: List[Dict],
                       check_categories: Optional[List[CheckCategory]] = None) -> DeploymentVerificationReport:
        """
        验证整个集群

        Args:
            hosts: 主机列表 [{"hostname": ..., "ip": ...}, ...]
            check_categories: 要检查的类别列表

        Returns:
            DeploymentVerificationReport对象
        """
        report = DeploymentVerificationReport()

        # 验证每个主机
        for host_info in hosts:
            host = host_info.get("hostname", host_info.get("ip", ""))
            ip = host_info.get("ip", "")
            result = self.verify_host(host, ip, check_categories)
            report.hosts.append(result)

        # 生成摘要
        total_hosts = len(report.hosts)
        passed_hosts = sum(1 for h in report.hosts if h.overall_status == CheckStatus.PASSED)
        warning_hosts = sum(1 for h in report.hosts if h.overall_status == CheckStatus.WARNING)
        failed_hosts = sum(1 for h in report.hosts if h.overall_status == CheckStatus.FAILED)

        # 收集所有检查项
        all_checks = []
        for host in report.hosts:
            for check in host.checks:
                all_checks.append((host.hostname, check))

        # 统计检查项
        total_checks = len(all_checks)
        passed_checks = sum(1 for _, c in all_checks if c.status == CheckStatus.PASSED)
        failed_checks = sum(1 for _, c in all_checks if c.status == CheckStatus.FAILED)
        skipped_checks = sum(1 for _, c in all_checks if c.status == CheckStatus.SKIPPED)

        report.summary = {
            "total_hosts": total_hosts,
            "passed_hosts": passed_hosts,
            "warning_hosts": warning_hosts,
            "failed_hosts": failed_hosts,
            "total_checks": total_checks,
            "passed_checks": passed_checks,
            "failed_checks": failed_checks,
            "skipped_checks": skipped_checks,
            "overall_completion_percent": round(
                sum(h.completion_percent for h in report.hosts) / total_hosts, 2
            ) if total_hosts > 0 else 0
        }

        # 收集未完成项
        for host in report.hosts:
            for check in host.checks:
                if check.status == CheckStatus.FAILED:
                    report.incomplete_items.append({
                        "hostname": host.hostname,
                        "check_name": check.name,
                        "category": str(check.category),
                        "message": check.message
                    })

        return report

    def generate_markdown_report(self, report: DeploymentVerificationReport) -> str:
        """
        生成Markdown格式的验证报告

        Args:
            report: 验证报告

        Returns:
            Markdown格式字符串
        """
        lines = [
            "# 部署验证报告\n",
            "## 摘要\n",
            f"- 总主机数: {report.summary.get('total_hosts', 0)}",
            f"- 通过主机: {report.summary.get('passed_hosts', 0)}",
            f"- 警告主机: {report.summary.get('warning_hosts', 0)}",
            f"- 失败主机: {report.summary.get('failed_hosts', 0)}",
            f"- 总检查项: {report.summary.get('total_checks', 0)}",
            f"- 通过检查: {report.summary.get('passed_checks', 0)}",
            f"- 失败检查: {report.summary.get('failed_checks', 0)}",
            f"- 跳过检查: {report.summary.get('skipped_checks', 0)}",
            f"- 完成度: {report.summary.get('overall_completion_percent', 0)}%",
            "",
        ]

        # 未完成项
        if report.incomplete_items:
            lines.append("## 未完成项\n")
            lines.append("| 主机 | 检查项 | 类别 | 说明 |")
            lines.append("|------|--------|------|------|")
            for item in report.incomplete_items:
                lines.append(
                    f"| {item['hostname']} | {item['check_name']} | "
                    f"{item['category']} | {item['message'][:50]} |"
                )
            lines.append("")

        # 主机详情
        lines.append("## 主机详情\n")
        for host in report.hosts:
            status_emoji = "✓" if host.overall_status == CheckStatus.PASSED else \
                          "⚠" if host.overall_status == CheckStatus.WARNING else "✗"
            lines.append(f"### {status_emoji} {host.hostname} ({host.ip})\n")
            lines.append(f"完成度: {host.completion_percent:.1f}%\n")
            lines.append("| 检查项 | 类别 | 状态 | 说明 |")
            lines.append("|--------|------|------|------|")

            for check in host.checks:
                status_str = "✓" if check.status == CheckStatus.PASSED else \
                            "✗" if check.status == CheckStatus.FAILED else \
                            "○" if check.status == CheckStatus.SKIPPED else "⚠"
                lines.append(
                    f"| {check.name} | {check.category} | {status_str} | "
                    f"{check.message[:40]} |"
                )
            lines.append("")

        return "\n".join(lines)

    def check_deployment_readiness(self, report: DeploymentVerificationReport) -> bool:
        """
        检查是否可以进行网络测试

        Args:
            report: 验证报告

        Returns:
            是否可以进行测试
        """
        # 必须所有主机都通过基础检查
        for host in report.hosts:
            if host.overall_status == CheckStatus.FAILED:
                return False

        # 必须有RDMA设备
        for host in report.hosts:
            rdma_check = next(
                (c for c in host.checks if c.name == "rdma_devices"),
                None
            )
            if rdma_check and rdma_check.status != CheckStatus.PASSED:
                logger.warning(f"主机 {host.hostname} 没有RDMA设备")
                return False

        return True
