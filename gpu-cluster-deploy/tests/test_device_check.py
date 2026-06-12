"""
设备检查模块单元测试
"""

import os
import sys
import unittest
from datetime import datetime
from unittest.mock import Mock, MagicMock

# 添加src到路径
sys.path.insert(0, str(os.path.join(os.path.dirname(__file__), "..", "src")))

from models.device_check import (
    DeviceInfo, DeviceType, DeviceStatus, ConsistencyLevel,
    NodeDeviceSnapshot, DeviceDifference, ConsistencyReport,
    DeviceCheckConfig, GPUTopologyInfo, TopologyCheckResult, FixSuggestion
)
from network.ibdev_parser import IbdevParser, IbdevMapping
from network.device_checker import DeviceConsistencyChecker
from network.fix_suggestions import FixSuggestionGenerator


class TestDeviceModels(unittest.TestCase):
    """设备数据模型测试"""

    def test_device_info_creation(self):
        """测试DeviceInfo创建"""
        device = DeviceInfo(
            name="mlx5_0",
            device_type=DeviceType.RDMA,
            pci_address="0000:17:00.0",
            numa_node=0
        )
        self.assertEqual(device.name, "mlx5_0")
        self.assertEqual(device.device_type, DeviceType.RDMA)
        self.assertEqual(device.numa_node, 0)

    def test_device_info_to_dict(self):
        """测试DeviceInfo序列化"""
        device = DeviceInfo(
            name="mlx5_0",
            device_type=DeviceType.RDMA,
            pci_address="0000:17:00.0"
        )
        d = device.to_dict()
        self.assertEqual(d["name"], "mlx5_0")
        self.assertEqual(d["device_type"], "rdma")

    def test_node_device_snapshot(self):
        """测试NodeDeviceSnapshot"""
        snapshot = NodeDeviceSnapshot(
            hostname="node01",
            timestamp=datetime.now().isoformat()
        )
        snapshot.rdma_devices.append(DeviceInfo(
            name="mlx5_0", device_type=DeviceType.RDMA
        ))
        snapshot.rdma_devices.append(DeviceInfo(
            name="mlx5_1", device_type=DeviceType.RDMA
        ))

        self.assertEqual(snapshot.hostname, "node01")
        self.assertEqual(len(snapshot.rdma_devices), 2)
        self.assertEqual(snapshot.device_count["rdma"], 2)

    def test_device_difference(self):
        """测试DeviceDifference"""
        diff = DeviceDifference(
            device_type=DeviceType.RDMA,
            device_name="mlx5_2",
            status=DeviceStatus.MISSING,
            affected_nodes=["node02", "node03"],
            details="设备缺失"
        )
        self.assertEqual(diff.status, DeviceStatus.MISSING)
        self.assertEqual(len(diff.affected_nodes), 2)

    def test_consistency_report(self):
        """测试ConsistencyReport"""
        report = ConsistencyReport(
            cluster_name="test-cluster",
            check_time=datetime.now().isoformat(),
            overall_level=ConsistencyLevel.CONSISTENT
        )

        # 添加节点快照
        for i in range(3):
            snapshot = NodeDeviceSnapshot(
                hostname=f"node0{i}",
                timestamp=datetime.now().isoformat()
            )
            report.node_snapshots.append(snapshot)

        self.assertEqual(report.node_count, 3)
        self.assertEqual(report.difference_count, 0)

    def test_device_check_config_defaults(self):
        """测试DeviceCheckConfig默认值"""
        config = DeviceCheckConfig()
        self.assertTrue(config.enabled)
        self.assertTrue(config.check_rdma)
        self.assertTrue(config.check_ethernet)
        self.assertEqual(config.tolerance_level, "strict")


class TestIbdevParser(unittest.TestCase):
    """ibdev2netdev解析器测试"""

    def setUp(self):
        """初始化解析器"""
        self.parser = IbdevParser()

    def test_parse_standard_output(self):
        """测试解析标准输出"""
        output = """
mlx5_0 port 1 ==> ib0 (Active) 200Gbps(InfiniBand)
mlx5_1 port 1 ==> ib1 (Active) 200Gbps(InfiniBand)
mlx5_2 port 1 ==> eth2 (Active) 100Gbps(Ethernet)
"""
        mappings = self.parser.parse(output)
        self.assertEqual(len(mappings), 3)

        self.assertEqual(mappings[0].rdma_device, "mlx5_0")
        self.assertEqual(mappings[0].port, 1)
        self.assertEqual(mappings[0].netdev, "ib0")
        self.assertEqual(mappings[0].state, "Active")

    def test_parse_down_device(self):
        """测试解析Down状态设备"""
        output = "mlx5_0 port 1 ==> ib0 (Down)"
        mappings = self.parser.parse(output)
        self.assertEqual(len(mappings), 1)
        self.assertEqual(mappings[0].state, "Down")

    def test_parse_empty_output(self):
        """测试解析空输出"""
        mappings = self.parser.parse("")
        self.assertEqual(len(mappings), 0)

    def test_get_rdma_to_netdev_map(self):
        """测试获取RDMA到网络设备映射"""
        output = """
mlx5_0 port 1 ==> ib0 (Active)
mlx5_1 port 1 ==> ib1 (Active)
"""
        self.parser.parse(output)
        rdma_map = self.parser.get_rdma_to_netdev_map()

        self.assertEqual(rdma_map["mlx5_0"], "ib0")
        self.assertEqual(rdma_map["mlx5_1"], "ib1")

    def test_get_active_devices(self):
        """测试获取Active设备"""
        output = """
mlx5_0 port 1 ==> ib0 (Active)
mlx5_1 port 1 ==> ib1 (Down)
mlx5_2 port 1 ==> ib2 (Active)
"""
        self.parser.parse(output)
        active = self.parser.get_active_devices()
        self.assertEqual(len(active), 2)

    def test_device_summary(self):
        """测试设备摘要"""
        output = """
mlx5_0 port 1 ==> ib0 (Active) 200Gbps
mlx5_1 port 1 ==> eth1 (Active) 100Gbps
"""
        self.parser.parse(output)
        summary = self.parser.get_device_summary()

        self.assertEqual(summary["total_devices"], 2)
        self.assertEqual(summary["active_devices"], 2)
        self.assertEqual(summary["infiniband_devices"], 1)
        self.assertEqual(summary["ethernet_devices"], 1)


class TestDeviceConsistencyChecker(unittest.TestCase):
    """设备一致性检查器测试"""

    def _create_mock_execute_func(self, mock_data: dict):
        """创建模拟执行函数"""
        def mock_execute(hostname: str, command: str):
            # 根据命令返回模拟数据
            for key, value in mock_data.items():
                if key in command:
                    return {"success": True, "stdout": value}
            return {"success": False, "stdout": "", "stderr": "Not found"}

        return mock_execute

    def test_check_cluster_consistent(self):
        """测试检查一致的集群"""
        # 模拟所有节点有相同的设备
        mock_data = {
            "ls -1 /sys/class/infiniband/": "mlx5_0\nmlx5_1\nmlx5_2",
            "ls -1 /sys/class/net/": "lo\neth0\neth1\nens4f0\nens4f1",
            "nvidia-smi": "0, NVIDIA A100, 0000:17:00.0, 535.104.05",
        }

        checker = DeviceConsistencyChecker(
            execute_func=self._create_mock_execute_func(mock_data)
        )

        report = checker.check_cluster(["node01", "node02"])

        # 验证报告基本结构
        self.assertEqual(report.node_count, 2)
        self.assertIsNotNone(report.overall_level)

    def test_quick_check(self):
        """测试快速检查"""
        mock_data = {
            "ls -1 /sys/class/infiniband/": "mlx5_0\nmlx5_1",
            "ls -1 /sys/class/net/": "lo\neth0",
            "nvidia-smi": "0, NVIDIA A100, 0000:17:00.0",
        }

        checker = DeviceConsistencyChecker(
            execute_func=self._create_mock_execute_func(mock_data)
        )

        summary = checker.quick_check(["node01"])

        self.assertIn("consistent", summary)
        self.assertIn("level", summary)
        self.assertEqual(summary["node_count"], 1)


class TestFixSuggestionGenerator(unittest.TestCase):
    """修复建议生成器测试"""

    def setUp(self):
        """初始化生成器"""
        self.generator = FixSuggestionGenerator()

    def test_generate_missing_device_suggestion(self):
        """测试生成缺失设备建议"""
        report = ConsistencyReport(
            cluster_name="test-cluster",
            check_time=datetime.now().isoformat(),
            overall_level=ConsistencyLevel.INCONSISTENT
        )

        diff = DeviceDifference(
            device_type=DeviceType.RDMA,
            device_name="mlx5_2",
            status=DeviceStatus.MISSING,
            affected_nodes=["node02"],
            details="设备缺失"
        )
        report.differences.append(diff)

        suggestions = self.generator.generate_suggestions(report)

        self.assertEqual(len(suggestions), 1)
        self.assertIn("mlx5_2", suggestions[0].action)
        self.assertEqual(suggestions[0].risk_level, "high")

    def test_generate_extra_device_suggestion(self):
        """测试生成多余设备建议"""
        report = ConsistencyReport(
            cluster_name="test-cluster",
            check_time=datetime.now().isoformat(),
            overall_level=ConsistencyLevel.WARNING
        )

        diff = DeviceDifference(
            device_type=DeviceType.ETHERNET,
            device_name="eth3",
            status=DeviceStatus.EXTRA,
            affected_nodes=["node03"],
            details="多余设备"
        )
        report.differences.append(diff)

        suggestions = self.generator.generate_suggestions(report)

        self.assertEqual(len(suggestions), 1)
        self.assertEqual(suggestions[0].risk_level, "low")

    def test_priority_ordering(self):
        """测试优先级排序"""
        report = ConsistencyReport(
            cluster_name="test-cluster",
            check_time=datetime.now().isoformat(),
            overall_level=ConsistencyLevel.INCONSISTENT
        )

        # 添加多个差异，不同优先级
        report.differences.append(DeviceDifference(
            device_type=DeviceType.ETHERNET,
            device_name="eth3",
            status=DeviceStatus.EXTRA,
            affected_nodes=["node01"]
        ))
        report.differences.append(DeviceDifference(
            device_type=DeviceType.GPU,
            device_name="GPU1",
            status=DeviceStatus.MISSING,
            affected_nodes=["node02"]
        ))
        report.differences.append(DeviceDifference(
            device_type=DeviceType.RDMA,
            device_name="mlx5_0",
            status=DeviceStatus.MISSING,
            affected_nodes=["node01", "node02"]
        ))

        suggestions = self.generator.generate_suggestions(report)

        # 验证排序：缺失设备优先级高于多余设备
        self.assertEqual(suggestions[0].device_difference.status, DeviceStatus.MISSING)
        self.assertEqual(suggestions[-1].device_difference.status, DeviceStatus.EXTRA)

    def test_generate_report(self):
        """测试生成报告"""
        report = ConsistencyReport(
            cluster_name="test-cluster",
            check_time=datetime.now().isoformat(),
            overall_level=ConsistencyLevel.INCONSISTENT
        )

        diff = DeviceDifference(
            device_type=DeviceType.RDMA,
            device_name="mlx5_2",
            status=DeviceStatus.MISSING,
            affected_nodes=["node02"],
            details="设备缺失"
        )
        report.differences.append(diff)

        suggestions = self.generator.generate_suggestions(report)
        report_text = self.generator.generate_report(suggestions)

        self.assertIn("设备修复建议报告", report_text)
        self.assertIn("mlx5_2", report_text)


class TestGPUTopologyInfo(unittest.TestCase):
    """GPU拓扑信息测试"""

    def test_topology_info_creation(self):
        """测试拓扑信息创建"""
        topo = GPUTopologyInfo(
            gpu_index=0,
            gpu_name="NVIDIA A100-SXM4-80GB",
            pci_address="0000:17:00.0",
            numa_node=0,
            connected_rdma=["mlx5_0", "mlx5_1"],
            nvlink_connections=[1, 2]
        )

        self.assertEqual(topo.gpu_index, 0)
        self.assertEqual(len(topo.connected_rdma), 2)
        self.assertEqual(len(topo.nvlink_connections), 2)

    def test_topology_info_to_dict(self):
        """测试拓扑信息序列化"""
        topo = GPUTopologyInfo(
            gpu_index=0,
            gpu_name="NVIDIA A100",
            pci_address="0000:17:00.0",
            numa_node=0
        )

        d = topo.to_dict()
        self.assertEqual(d["gpu_index"], 0)
        self.assertEqual(d["gpu_name"], "NVIDIA A100")


class TestTopologyCheckResult(unittest.TestCase):
    """拓扑检查结果测试"""

    def test_topology_result(self):
        """测试拓扑检查结果"""
        result = TopologyCheckResult(hostname="node01")
        result.gpu_topologies.append(GPUTopologyInfo(
            gpu_index=0,
            gpu_name="NVIDIA A100",
            pci_address="0000:17:00.0",
            numa_node=0
        ))
        result.issues.append("GPU NUMA分布不均匀")

        self.assertEqual(result.hostname, "node01")
        self.assertEqual(len(result.gpu_topologies), 1)
        self.assertEqual(len(result.issues), 1)


if __name__ == "__main__":
    unittest.main()
