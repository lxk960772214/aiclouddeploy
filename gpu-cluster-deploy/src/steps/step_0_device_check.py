"""
步骤00: 设备一致性检查
在部署开始前检查所有节点的设备序列一致性
"""

from typing import List, Dict, Any, Optional
import json

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from steps.base import BaseStep, StepResult, StepStatus
from models.device_check import (
    DeviceCheckConfig, ConsistencyLevel, DeviceType, DeviceStatus
)
from network.device_checker import DeviceConsistencyChecker
from network.gpu_topo_checker import GPUTopologyChecker
from network.fix_suggestions import FixSuggestionGenerator


class Step0DeviceCheck(BaseStep):
    """设备一致性检查步骤"""

    step_id = "00"
    step_name = "设备一致性检查"
    step_description = "在部署开始前检查所有节点的RDMA、以太网和GPU设备一致性"
    requires_sudo = False
    supports_batch = False
    timeout = 300

    def __init__(self, config, ssh_manager, batch_executor=None, logger=None, device_check_config: Optional[DeviceCheckConfig] = None, versions=None):
        """
        初始化设备检查步骤

        Args:
            config: 集群配置
            ssh_manager: SSH管理器
            batch_executor: 批量执行器
            logger: 日志记录器
            device_check_config: 设备检查配置
            versions: 版本配置
        """
        super().__init__(config, ssh_manager, batch_executor, logger, versions)
        self.device_check_config = device_check_config or DeviceCheckConfig()

    def execute(self, hosts: List[str]) -> StepResult:
        """执行设备一致性检查"""
        all_results = {}
        errors = []
        warnings = []

        # 检查是否启用设备检查
        if not self.device_check_config.enabled:
            self.logger.info("设备一致性检查已禁用，跳过")
            return StepResult(
                step_id=self.step_id,
                step_name=self.step_name,
                status=StepStatus.SUCCESS,
                message="设备一致性检查已禁用，跳过",
                host_results={"skipped": True}
            )

        # 1. 创建设备检查器
        # 使用登录用户连接（step_0d 之前，部署用户可能不存在）
        def execute_with_login_user(host, command, **kwargs):
            return self.execute_on_host(host, command, use_login_user=True, **kwargs)

        checker = DeviceConsistencyChecker(
            execute_func=execute_with_login_user,
            config=self.device_check_config
        )

        # 2. 执行设备一致性检查
        self.logger.info("开始设备一致性检查...")
        report = checker.check_cluster(hosts, self.config.name)

        # 3. 执行GPU拓扑检查
        self.logger.info("开始GPU拓扑检查...")
        topo_checker = GPUTopologyChecker(execute_func=execute_with_login_user)
        topo_comparison = topo_checker.compare_cluster_topology(hosts)

        # 4. 生成修复建议
        fix_generator = FixSuggestionGenerator()
        suggestions = fix_generator.generate_suggestions(report)

        # 5. 整理结果
        all_results["consistency_report"] = report.to_dict()
        all_results["topology_comparison"] = topo_comparison
        all_results["fix_suggestions"] = [s.to_dict() for s in suggestions]

        # 6. 根据检查结果确定状态
        if report.overall_level == ConsistencyLevel.CRITICAL:
            errors.append(f"设备一致性严重问题: 发现 {report.critical_count} 个缺失设备")
            for diff in report.differences:
                if diff.status == DeviceStatus.MISSING:
                    errors.append(
                        f"  - {diff.device_type.value} 设备 {diff.device_name} "
                        f"在节点 {diff.affected_nodes} 上缺失"
                    )

        elif report.overall_level == ConsistencyLevel.INCONSISTENT:
            warnings.append(f"设备一致性问题: 发现 {report.difference_count} 个差异")
            for diff in report.differences[:5]:  # 只显示前5个
                warnings.append(
                    f"  - {diff.device_type.value} 设备 {diff.device_name}: {diff.details}"
                )

        elif report.overall_level == ConsistencyLevel.WARNING:
            warnings.append(f"设备一致性警告: 发现 {report.warning_count} 个多余设备")

        # 7. 检查GPU拓扑问题
        if not topo_comparison.get("consistent_gpu_count"):
            errors.append(
                f"GPU数量不一致: {topo_comparison.get('gpu_counts')}"
            )

        if topo_comparison.get("total_issues", 0) > 0:
            for hostname, issues in topo_comparison.get("issues_by_node", {}).items():
                for issue in issues[:3]:  # 每个节点最多显示3个问题
                    warnings.append(f"[{hostname}] {issue}")

        # 8. 输出摘要
        self.logger.info("=" * 60)
        self.logger.info("设备一致性检查摘要:")
        self.logger.info(f"  检查节点数: {report.node_count}")
        self.logger.info(f"  一致性级别: {report.overall_level.value}")
        self.logger.info(f"  差异数量: {report.difference_count}")
        self.logger.info(f"  GPU拓扑一致: {topo_comparison.get('consistent_gpu_count', 'N/A')}")
        self.logger.info("=" * 60)

        # 9. 根据容忍级别决定是否继续
        tolerance = self.device_check_config.tolerance_level
        should_fail = False

        if tolerance == "strict":
            should_fail = report.overall_level != ConsistencyLevel.CONSISTENT
        elif tolerance == "moderate":
            should_fail = report.overall_level in [ConsistencyLevel.CRITICAL, ConsistencyLevel.INCONSISTENT]
        else:  # lenient
            should_fail = report.overall_level == ConsistencyLevel.CRITICAL

        if should_fail:
            return StepResult(
                step_id=self.step_id,
                step_name=self.step_name,
                status=StepStatus.FAILED,
                message=f"设备一致性检查失败: {report.overall_level.value}",
                errors=errors,
                warnings=warnings,
                host_results=all_results
            )

        return StepResult(
            step_id=self.step_id,
            step_name=self.step_name,
            status=StepStatus.SUCCESS,
            message=f"设备一致性检查通过: {report.overall_level.value}",
            warnings=warnings,
            host_results=all_results
        )

    def is_configured(self, host: str) -> tuple:
        """
        检查设备一致性检查是否已执行

        Args:
            host: 主机地址

        Returns:
            tuple[bool, str]: (是否已配置, 检查详情)
        """
        # 设备检查是一次性检查，检查报告文件是否存在
        import glob
        report_files = glob.glob("reports/device_check_*.md")
        if report_files:
            return True, "设备检查报告已存在"
        return True, "设备检查（一次性检查，无持久配置）"

    def post_check(self, hosts: List[str]) -> bool:
        """验证检查（本步骤不需要post_check）"""
        return True

    def generate_report(self, hosts: List[str]) -> str:
        """生成可读的检查报告"""
        # 使用登录用户连接
        def execute_with_login_user(host, command, **kwargs):
            return self.execute_on_host(host, command, use_login_user=True, **kwargs)

        checker = DeviceConsistencyChecker(
            execute_func=execute_with_login_user,
            config=self.device_check_config
        )
        report = checker.check_cluster(hosts, self.config.name)

        lines = []
        lines.append("=" * 70)
        lines.append(f"GPU集群设备一致性检查报告")
        lines.append(f"集群名称: {report.cluster_name}")
        lines.append(f"检查时间: {report.check_time}")
        lines.append("=" * 70)
        lines.append("")

        # 节点摘要
        lines.append("## 节点设备摘要")
        lines.append("-" * 70)
        for snapshot in report.node_snapshots:
            lines.append(f"\n节点: {snapshot.hostname}")
            counts = snapshot.device_count
            lines.append(f"  RDMA设备: {counts['rdma']} 个")
            lines.append(f"  以太网设备: {counts['ethernet']} 个")
            lines.append(f"  GPU设备: {counts['gpu']} 个")
            lines.append(f"  NVMe设备: {counts['nvme']} 个")
            if snapshot.errors:
                lines.append(f"  错误: {', '.join(snapshot.errors)}")

        # 差异报告
        lines.append("")
        lines.append("## 设备差异报告")
        lines.append("-" * 70)
        if report.differences:
            for diff in report.differences:
                status_icon = {
                    DeviceStatus.MISSING: "❌",
                    DeviceStatus.EXTRA: "⚠️",
                    DeviceStatus.MISMATCH: "🔍",
                }.get(diff.status, "•")

                lines.append(f"\n{status_icon} [{diff.device_type.value}] {diff.device_name}")
                lines.append(f"   状态: {diff.status.value}")
                lines.append(f"   详情: {diff.details}")
                lines.append(f"   受影响节点: {', '.join(diff.affected_nodes)}")
        else:
            lines.append("\n✅ 未发现设备差异")

        # 总结
        lines.append("")
        lines.append("## 总结")
        lines.append("-" * 70)
        lines.append(f"整体一致性级别: {report.overall_level.value}")
        lines.append(f"总差异数: {report.difference_count}")
        lines.append(f"严重问题: {report.critical_count}")
        lines.append(f"警告问题: {report.warning_count}")

        lines.append("")
        lines.append("=" * 70)

        return "\n".join(lines)


def run_device_check(
    config,
    ssh_manager,
    hosts: List[str],
    device_check_config: Optional[DeviceCheckConfig] = None
) -> StepResult:
    """
    运行设备检查的便捷函数

    Args:
        config: 集群配置
        ssh_manager: SSH管理器
        hosts: 主机列表
        device_check_config: 设备检查配置

    Returns:
        StepResult: 检查结果
    """
    step = Step0DeviceCheck(config, ssh_manager, device_check_config)
    return step.execute(hosts)
