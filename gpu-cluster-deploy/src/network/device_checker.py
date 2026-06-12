"""
设备一致性检查器
比较所有节点的设备序列，识别缺失、多余或不匹配的设备
"""

import re
from typing import List, Dict, Any, Optional, Callable
from datetime import datetime
from collections import defaultdict

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from models.device_check import (
    DeviceInfo, DeviceType, DeviceStatus, ConsistencyLevel,
    NodeDeviceSnapshot, DeviceDifference, ConsistencyReport, DeviceCheckConfig
)
from network.device_discovery import DeviceDiscovery


class DeviceConsistencyChecker:
    """设备一致性检查器"""

    def __init__(
        self,
        execute_func: Optional[Callable] = None,
        config: Optional[DeviceCheckConfig] = None
    ):
        """
        初始化检查器

        Args:
            execute_func: 执行远程命令的函数
            config: 设备检查配置
        """
        self.discovery = DeviceDiscovery(execute_func=execute_func)
        self.config = config or DeviceCheckConfig()

    def check_cluster(
        self,
        hostnames: List[str],
        cluster_name: str = "gpu-cluster"
    ) -> ConsistencyReport:
        """
        检查集群设备一致性

        Args:
            hostnames: 节点主机名列表
            cluster_name: 集群名称

        Returns:
            ConsistencyReport: 一致性检查报告
        """
        report = ConsistencyReport(
            cluster_name=cluster_name,
            check_time=datetime.now().isoformat(),
            overall_level=ConsistencyLevel.CONSISTENT
        )

        # 1. 收集所有节点的设备快照
        for hostname in hostnames:
            snapshot = self.discovery.discover_node_devices(hostname)
            report.node_snapshots.append(snapshot)

        # 2. 检查RDMA设备一致性
        if self.config.check_rdma:
            rdma_diffs = self._check_device_consistency(
                report.node_snapshots,
                DeviceType.RDMA,
                "rdma_devices"
            )
            report.differences.extend(rdma_diffs)

        # 3. 检查以太网设备一致性
        if self.config.check_ethernet:
            eth_diffs = self._check_device_consistency(
                report.node_snapshots,
                DeviceType.ETHERNET,
                "ethernet_devices"
            )
            report.differences.extend(eth_diffs)

        # 4. 检查GPU设备一致性
        if self.config.check_gpu:
            gpu_diffs = self._check_device_consistency(
                report.node_snapshots,
                DeviceType.GPU,
                "gpu_devices"
            )
            report.differences.extend(gpu_diffs)

        # 5. 检查NVMe设备一致性
        if self.config.check_nvme:
            nvme_diffs = self._check_device_consistency(
                report.node_snapshots,
                DeviceType.NVME,
                "nvme_devices"
            )
            report.differences.extend(nvme_diffs)

        # 6. 确定整体一致性级别
        report.overall_level = self._determine_consistency_level(report)

        # 7. 生成摘要
        report.summary = self._generate_summary(report)

        return report

    def _check_device_consistency(
        self,
        snapshots: List[NodeDeviceSnapshot],
        device_type: DeviceType,
        device_attr: str
    ) -> List[DeviceDifference]:
        """检查特定类型设备的一致性"""
        differences = []

        # 收集所有节点的设备名称
        all_device_names = defaultdict(list)

        for snapshot in snapshots:
            devices = getattr(snapshot, device_attr, [])
            for device in devices:
                all_device_names[device.name].append(snapshot.hostname)

        total_nodes = len(snapshots)
        all_hostnames = [s.hostname for s in snapshots]

        # 获取预期设备列表
        expected_devices = self._get_expected_devices(snapshots, device_type)

        # 检查缺失的设备
        for device_name in expected_devices:
            nodes_with_device = all_device_names.get(device_name, [])
            nodes_without_device = [h for h in all_hostnames if h not in nodes_with_device]

            if nodes_without_device:
                diff = DeviceDifference(
                    device_type=device_type,
                    device_name=device_name,
                    status=DeviceStatus.MISSING,
                    reference_node=nodes_with_device[0] if nodes_with_device else None,
                    affected_nodes=nodes_without_device,
                    details=f"设备 {device_name} 在 {len(nodes_without_device)} 个节点上缺失"
                )
                differences.append(diff)

        # 检查多余的设备
        for device_name, hostnames in all_device_names.items():
            if device_name not in expected_devices and len(hostnames) < total_nodes:
                diff = DeviceDifference(
                    device_type=device_type,
                    device_name=device_name,
                    status=DeviceStatus.EXTRA,
                    affected_nodes=hostnames,
                    details=f"设备 {device_name} 仅在 {len(hostnames)} 个节点上存在"
                )
                differences.append(diff)

        # 检查设备序列一致性
        seq_diffs = self._check_device_sequence(snapshots, device_type, device_attr)
        differences.extend(seq_diffs)

        return differences

    def _get_expected_devices(
        self,
        snapshots: List[NodeDeviceSnapshot],
        device_type: DeviceType
    ) -> List[str]:
        """获取预期的设备列表"""
        device_counts = defaultdict(int)

        for snapshot in snapshots:
            if device_type == DeviceType.RDMA:
                devices = snapshot.rdma_devices
            elif device_type == DeviceType.ETHERNET:
                devices = snapshot.ethernet_devices
            elif device_type == DeviceType.GPU:
                devices = snapshot.gpu_devices
            else:
                devices = snapshot.nvme_devices

            for device in devices:
                device_counts[device.name] += 1

        # 如果设备在大多数节点上存在，则认为是预期设备
        threshold = len(snapshots) * 0.5
        expected = [name for name, count in device_counts.items() if count >= threshold]

        return sorted(expected)

    def _check_device_sequence(
        self,
        snapshots: List[NodeDeviceSnapshot],
        device_type: DeviceType,
        device_attr: str
    ) -> List[DeviceDifference]:
        """检查设备序列的一致性"""
        differences = []
        pattern = self._get_pattern_for_device_type(device_type)

        for snapshot in snapshots:
            devices = getattr(snapshot, device_attr, [])
            device_names = sorted([d.name for d in devices])

            if not device_names:
                continue

            indices = []
            for name in device_names:
                match = pattern.match(name)
                if match:
                    try:
                        indices.append(int(match.group(1)))
                    except (ValueError, IndexError):
                        pass

            if indices:
                indices.sort()
                expected_indices = list(range(indices[0], indices[0] + len(indices)))
                if indices != expected_indices:
                    missing = set(expected_indices) - set(indices)
                    if missing:
                        diff = DeviceDifference(
                            device_type=device_type,
                            device_name=f"{device_type.value}_sequence",
                            status=DeviceStatus.MISMATCH,
                            affected_nodes=[snapshot.hostname],
                            details=f"设备序列不连续，缺失索引: {sorted(missing)}"
                        )
                        differences.append(diff)

        return differences

    def _get_pattern_for_device_type(self, device_type: DeviceType) -> re.Pattern:
        """获取设备类型的匹配模式"""
        patterns = {
            DeviceType.RDMA: re.compile(r'mlx5_(\d+)'),
            DeviceType.ETHERNET: re.compile(r'ens?\d+f?(\d+)'),
            DeviceType.GPU: re.compile(r'GPU(\d+)'),
            DeviceType.NVME: re.compile(r'nvme(\d+)'),
        }
        return patterns.get(device_type, re.compile(r'(\d+)'))

    def _determine_consistency_level(self, report: ConsistencyReport) -> ConsistencyLevel:
        """确定整体一致性级别"""
        tolerance = self.config.tolerance_level
        missing_count = sum(1 for d in report.differences if d.status == DeviceStatus.MISSING)
        mismatch_count = sum(1 for d in report.differences if d.status == DeviceStatus.MISMATCH)
        extra_count = sum(1 for d in report.differences if d.status == DeviceStatus.EXTRA)

        if tolerance == "strict":
            if missing_count > 0:
                return ConsistencyLevel.CRITICAL
            elif mismatch_count > 0:
                return ConsistencyLevel.INCONSISTENT
            elif extra_count > 0:
                return ConsistencyLevel.WARNING
            return ConsistencyLevel.CONSISTENT

        elif tolerance == "moderate":
            if missing_count > 2 or mismatch_count > 2:
                return ConsistencyLevel.CRITICAL
            elif missing_count > 0 or mismatch_count > 0:
                return ConsistencyLevel.INCONSISTENT
            elif extra_count > 0:
                return ConsistencyLevel.WARNING
            return ConsistencyLevel.CONSISTENT

        else:  # lenient
            if missing_count > 4 or mismatch_count > 4:
                return ConsistencyLevel.INCONSISTENT
            elif missing_count > 0 or mismatch_count > 0:
                return ConsistencyLevel.WARNING
            return ConsistencyLevel.CONSISTENT

    def _generate_summary(self, report: ConsistencyReport) -> Dict[str, Any]:
        """生成检查摘要"""
        by_type = defaultdict(lambda: {"missing": 0, "extra": 0, "mismatch": 0})
        for diff in report.differences:
            type_key = diff.device_type.value
            status_key = diff.status.value
            if status_key in by_type[type_key]:
                by_type[type_key][status_key] += 1

        affected_nodes = set()
        for diff in report.differences:
            affected_nodes.update(diff.affected_nodes)

        if report.node_snapshots:
            reference = report.node_snapshots[0]
            device_counts = reference.device_count
        else:
            device_counts = {}

        return {
            "total_nodes": report.node_count,
            "affected_nodes": list(affected_nodes),
            "affected_node_count": len(affected_nodes),
            "total_differences": report.difference_count,
            "by_device_type": dict(by_type),
            "reference_device_counts": device_counts,
            "consistency_level": report.overall_level.value
        }

    def quick_check(self, hostnames: List[str]) -> Dict[str, Any]:
        """快速检查，只返回摘要信息"""
        report = self.check_cluster(hostnames)
        return {
            "consistent": report.overall_level == ConsistencyLevel.CONSISTENT,
            "level": report.overall_level.value,
            "node_count": report.node_count,
            "difference_count": report.difference_count,
            "affected_nodes": report.summary.get("affected_nodes", []),
            "issues": [
                {
                    "type": d.device_type.value,
                    "device": d.device_name,
                    "status": d.status.value,
                    "nodes": d.affected_nodes
                }
                for d in report.differences[:10]
            ]
        }


def check_cluster_devices(
    hostnames: List[str],
    execute_func: Callable,
    config: Optional[DeviceCheckConfig] = None
) -> ConsistencyReport:
    """检查集群设备一致性的便捷函数"""
    checker = DeviceConsistencyChecker(execute_func=execute_func, config=config)
    return checker.check_cluster(hostnames)
