"""
修复建议生成器
根据设备序列差异生成具体的修复建议和报告
"""

from typing import List, Optional
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from models.device_check import (
    DeviceDifference, DeviceStatus, DeviceType, ConsistencyReport, FixSuggestion
)


class FixSuggestionGenerator:
    """修复建议生成器"""

    def generate_suggestions(
        self,
        report: ConsistencyReport
    ) -> List[FixSuggestion]:
        """
        根据一致性报告生成修复建议

        Args:
            report: 一致性检查报告

        Returns:
            修复建议列表
        """
        suggestions = []

        for i, diff in enumerate(report.differences):
            suggestion = self._generate_suggestion_for_diff(diff, i + 1)
            if suggestion:
                suggestions.append(suggestion)

        # 按优先级排序
        suggestions.sort(key=lambda s: s.priority)

        return suggestions

    def _generate_suggestion_for_diff(
        self,
        diff: DeviceDifference,
        index: int
    ) -> Optional[FixSuggestion]:
        """
        为单个设备差异生成修复建议

        Args:
            diff: 设备差异
            index: 索引

        Returns:
            修复建议或None
        """
        if diff.status == DeviceStatus.MISSING:
            return self._generate_missing_device_suggestion(diff, index)
        elif diff.status == DeviceStatus.EXTRA:
            return self._generate_extra_device_suggestion(diff, index)
        elif diff.status == DeviceStatus.MISMATCH:
            return self._generate_mismatch_device_suggestion(diff, index)

        return None

    def _generate_missing_device_suggestion(
        self,
        diff: DeviceDifference,
        index: int
    ) -> FixSuggestion:
        """生成缺失设备的修复建议"""
        commands = []
        action = ""
        risk_level = "high"
        requires_reboot = False
        notes = ""

        if diff.device_type == DeviceType.RDMA:
            action = f"检查并修复缺失的RDMA设备 {diff.device_name}"
            commands = [
                "# 1. 检查设备是否存在但未加载驱动",
                f"ls -la /sys/class/infiniband/{diff.device_name} 2>/dev/null || echo 'Device not found'",
                "",
                "# 2. 检查PCI设备是否存在",
                "lspci | grep -i 'mellanox\\|infiniband'",
                "",
                "# 3. 重新加载RDMA驱动",
                "sudo modprobe -r ib_uverbs mlx5_core",
                "sudo modprobe mlx5_core",
                "",
                "# 4. 检查驱动状态",
                "dmesg | grep -i mlx5 | tail -20",
            ]
            notes = (
                "RDMA设备缺失可能原因:\n"
                "1. 驱动未正确加载\n"
                "2. PCI设备被禁用或故障\n"
                "3. 固件问题\n"
                "4. 硬件故障"
            )
            risk_level = "high"

        elif diff.device_type == DeviceType.ETHERNET:
            action = f"检查并修复缺失的以太网设备 {diff.device_name}"
            commands = [
                "# 1. 检查网络接口",
                f"ip link show {diff.device_name} 2>/dev/null || echo 'Interface not found'",
                "",
                "# 2. 检查PCI网络设备",
                "lspci | grep -i ethernet",
                "",
                "# 3. 检查驱动绑定",
                f"cat /sys/class/net/{diff.device_name}/device/driver/module 2>/dev/null || echo 'No driver bound'",
                "",
                "# 4. 尝试重新绑定驱动",
                "# 注意: 需要知道正确的驱动名称和PCI地址",
                "# echo '<pci_address>' > /sys/bus/pci/drivers/<driver_name>/bind",
            ]
            notes = (
                "以太网设备缺失可能原因:\n"
                "1. 驱动未加载或未绑定\n"
                "2. 网卡被禁用\n"
                "3. PCI设备故障"
            )
            risk_level = "medium"

        elif diff.device_type == DeviceType.GPU:
            action = f"检查并修复缺失的GPU设备 {diff.device_name}"
            commands = [
                "# 1. 检查GPU状态",
                "nvidia-smi -L 2>/dev/null || echo 'nvidia-smi not available'",
                "",
                "# 2. 检查NVIDIA驱动",
                "cat /proc/driver/nvidia/version 2>/dev/null || echo 'Driver not loaded'",
                "",
                "# 3. 检查PCI GPU设备",
                "lspci | grep -i nvidia",
                "",
                "# 4. 重新加载NVIDIA驱动",
                "sudo rmmod nvidia_uvm nvidia_drm nvidia_modeset nvidia",
                "sudo modprobe nvidia",
            ]
            notes = (
                "GPU设备缺失可能原因:\n"
                "1. NVIDIA驱动未加载\n"
                "2. GPU被禁用\n"
                "3. 电源管理问题\n"
                "4. GPU硬件故障"
            )
            risk_level = "critical"
            requires_reboot = True

        else:  # NVMe
            action = f"检查缺失的NVMe设备 {diff.device_name}"
            commands = [
                "# 1. 检查NVMe设备",
                "ls -la /dev/nvme* 2>/dev/null || echo 'No NVMe devices found'",
                "",
                "# 2. 检查PCI NVMe设备",
                "lspci | grep -i nvme",
                "",
                "# 3. 重新扫描PCI总线",
                "echo 1 | sudo tee /sys/bus/pci/rescan",
            ]
            notes = "NVMe设备缺失可能需要检查硬件连接或更换设备"
            risk_level = "high"

        # 计算优先级
        priority = self._calculate_priority(diff)

        return FixSuggestion(
            priority=priority,
            device_difference=diff,
            action=action,
            commands=commands,
            risk_level=risk_level,
            requires_reboot=requires_reboot,
            notes=notes
        )

    def _generate_extra_device_suggestion(
        self,
        diff: DeviceDifference,
        index: int
    ) -> FixSuggestion:
        """生成多余设备的修复建议"""
        commands = []
        action = ""
        risk_level = "low"
        notes = ""

        if diff.device_type == DeviceType.RDMA:
            action = f"确认多余RDMA设备 {diff.device_name} 是否需要处理"
            commands = [
                "# 检查设备状态",
                f"cat /sys/class/infiniband/{diff.device_name}/device/uevent",
                "",
                "# 如果设备确实多余，可以考虑禁用",
                "# 注意: 这通常需要检查是否影响其他功能",
            ]
            notes = "多余的RDMA设备可能表示硬件配置不一致，需要确认是否影响部署"

        elif diff.device_type == DeviceType.ETHERNET:
            action = f"确认多余以太网设备 {diff.device_name} 状态"
            commands = [
                "# 检查接口配置",
                f"ip addr show {diff.device_name}",
                "",
                "# 检查接口状态",
                f"cat /sys/class/net/{diff.device_name}/operstate",
            ]
            notes = "多余的以太网接口可能是备用接口，通常不影响部署"

        else:
            action = f"确认多余设备 {diff.device_name}"
            commands = ["# 检查设备详情", f"ls -la /sys/class/*/"]
            notes = "多余设备可能需要进一步调查"

        priority = self._calculate_priority(diff) + 10  # 多余设备优先级较低

        return FixSuggestion(
            priority=priority,
            device_difference=diff,
            action=action,
            commands=commands,
            risk_level=risk_level,
            requires_reboot=False,
            notes=notes
        )

    def _generate_mismatch_device_suggestion(
        self,
        diff: DeviceDifference,
        index: int
    ) -> FixSuggestion:
        """生成不匹配设备的修复建议"""
        action = f"修复设备序列不一致问题: {diff.device_name}"
        commands = [
            "# 设备序列不一致通常需要手动检查和配置",
            "# 请检查以下内容:",
            "",
            "# 1. 确认设备实际存在",
            f"# 相关节点: {', '.join(diff.affected_nodes)}",
            "",
            "# 2. 检查设备命名规则",
            "# 某些系统可能使用不同的命名规则",
            "",
            "# 3. 检查udev规则",
            "cat /etc/udev/rules.d/*.rules 2>/dev/null | grep -i 'mlx\\|eth'",
            "",
            "# 4. 如需重命名设备，请参考系统文档",
        ]

        priority = self._calculate_priority(diff) + 5

        return FixSuggestion(
            priority=priority,
            device_difference=diff,
            action=action,
            commands=commands,
            risk_level="medium",
            requires_reboot=False,
            notes=f"设备序列不一致详情: {diff.details}"
        )

    def _calculate_priority(self, diff: DeviceDifference) -> int:
        """计算修复优先级"""
        base_priority = {
            DeviceStatus.MISSING: 1,
            DeviceStatus.MISMATCH: 10,
            DeviceStatus.EXTRA: 20,
        }.get(diff.status, 50)

        # 根据设备类型调整
        type_modifier = {
            DeviceType.GPU: 0,      # GPU最重要
            DeviceType.RDMA: 1,     # RDMA次之
            DeviceType.ETHERNET: 2,  # 以太网
            DeviceType.NVME: 3,     # NVMe
        }.get(diff.device_type, 5)

        # 根据影响节点数量调整
        affected_modifier = min(len(diff.affected_nodes), 5)

        return base_priority * 10 + type_modifier * 10 + affected_modifier

    def generate_report(self, suggestions: List[FixSuggestion]) -> str:
        """
        生成可读的修复建议报告

        Args:
            suggestions: 修复建议列表

        Returns:
            报告字符串
        """
        lines = []
        lines.append("=" * 70)
        lines.append("设备修复建议报告")
        lines.append("=" * 70)
        lines.append("")

        if not suggestions:
            lines.append("无需修复建议")
            return "\n".join(lines)

        # 按优先级分组
        critical = [s for s in suggestions if s.risk_level == "critical"]
        high = [s for s in suggestions if s.risk_level == "high"]
        medium = [s for s in suggestions if s.risk_level == "medium"]
        low = [s for s in suggestions if s.risk_level == "low"]

        # 严重问题
        if critical:
            lines.append("## 严重问题 (需立即处理)")
            lines.append("-" * 70)
            for s in critical:
                lines.extend(self._format_suggestion(s))

        # 高风险问题
        if high:
            lines.append("\n## 高风险问题")
            lines.append("-" * 70)
            for s in high:
                lines.extend(self._format_suggestion(s))

        # 中等风险问题
        if medium:
            lines.append("\n## 中等风险问题")
            lines.append("-" * 70)
            for s in medium:
                lines.extend(self._format_suggestion(s))

        # 低风险问题
        if low:
            lines.append("\n## 低风险问题")
            lines.append("-" * 70)
            for s in low:
                lines.extend(self._format_suggestion(s))

        lines.append("")
        lines.append("=" * 70)
        lines.append(f"总计: {len(suggestions)} 个修复建议")
        lines.append("=" * 70)

        return "\n".join(lines)

    def _format_suggestion(self, suggestion: FixSuggestion) -> List[str]:
        """格式化单个建议"""
        lines = []
        diff = suggestion.device_difference

        lines.append(f"\n[{suggestion.priority}] {diff.device_type.value.upper()}: {diff.device_name}")
        lines.append(f"   问题: {diff.details}")
        lines.append(f"   受影响节点: {', '.join(diff.affected_nodes)}")
        lines.append(f"   建议: {suggestion.action}")
        lines.append(f"   风险级别: {suggestion.risk_level}")
        lines.append(f"   需要重启: {'是' if suggestion.requires_reboot else '否'}")

        if suggestion.commands:
            lines.append("   执行命令:")
            for cmd in suggestion.commands:
                lines.append(f"     {cmd}")

        if suggestion.notes:
            lines.append(f"   备注: {suggestion.notes}")

        return lines


def generate_fix_suggestions(report: ConsistencyReport) -> List[FixSuggestion]:
    """生成修复建议的便捷函数"""
    generator = FixSuggestionGenerator()
    return generator.generate_suggestions(report)
