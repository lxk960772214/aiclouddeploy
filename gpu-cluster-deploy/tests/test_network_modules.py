"""
网络配置模块单元测试
"""

import unittest
from unittest.mock import Mock, MagicMock, patch
from dataclasses import asdict

from src.models.cluster import (
    NetworkConfig,
    NetworkTypeConfig,
    IBWriteBWConfig,
    NICConfig
)


class TestNetworkTypeConfig(unittest.TestCase):
    """测试NetworkTypeConfig数据类"""

    def test_default_values(self):
        """测试默认值"""
        config = NetworkTypeConfig()
        self.assertEqual(config.description, "")
        self.assertEqual(config.interfaces, [])
        self.assertEqual(config.rdma_devices, [])
        self.assertTrue(config.enabled)
        self.assertFalse(config.skip_performance_test)
        self.assertFalse(config.skip_inter_host_test)
        self.assertEqual(config.theoretical_bandwidth_gbps, 100.0)

    def test_custom_values(self):
        """测试自定义值"""
        config = NetworkTypeConfig(
            description="计算网络",
            interfaces=["eth0", "eth1"],
            rdma_devices=["mlx5_0", "mlx5_1"],
            enabled=True,
            skip_performance_test=False,
            skip_inter_host_test=False,
            theoretical_bandwidth_gbps=400.0
        )
        self.assertEqual(config.description, "计算网络")
        self.assertEqual(config.interfaces, ["eth0", "eth1"])
        self.assertEqual(config.rdma_devices, ["mlx5_0", "mlx5_1"])
        self.assertEqual(config.theoretical_bandwidth_gbps, 400.0)

    def test_to_dict(self):
        """测试to_dict方法"""
        config = NetworkTypeConfig(description="测试网络")
        d = config.to_dict()
        self.assertIn("description", d)
        self.assertIn("interfaces", d)
        self.assertIn("enabled", d)


class TestIBWriteBWConfig(unittest.TestCase):
    """测试IBWriteBWConfig数据类"""

    def test_default_values(self):
        """测试默认值"""
        config = IBWriteBWConfig()
        self.assertEqual(config.duration, 10)
        self.assertEqual(config.size, 65536)
        self.assertEqual(config.port_base, 18500)
        self.assertEqual(config.min_bandwidth_percent, 90.0)

    def test_custom_values(self):
        """测试自定义值"""
        config = IBWriteBWConfig(
            duration=20,
            size=131072,
            port_base=19000,
            min_bandwidth_percent=95.0
        )
        self.assertEqual(config.duration, 20)
        self.assertEqual(config.size, 131072)


class TestNetworkConfig(unittest.TestCase):
    """测试NetworkConfig数据类"""

    def test_default_values(self):
        """测试默认值"""
        config = NetworkConfig()
        self.assertIsNone(config.management)
        self.assertIsNone(config.compute)
        self.assertIsNone(config.storage)
        self.assertIsNone(config.ib_write_bw)
        self.assertEqual(config.compute_nics, [])
        self.assertEqual(config.storage_nics, [])
        self.assertEqual(config.management_nics, [])

    def test_new_format(self):
        """测试新格式配置"""
        config = NetworkConfig(
            management=NetworkTypeConfig(description="管理网"),
            compute=NetworkTypeConfig(description="计算网", theoretical_bandwidth_gbps=400.0),
            storage=NetworkTypeConfig(description="存储网", theoretical_bandwidth_gbps=200.0)
        )
        self.assertIsNotNone(config.management)
        self.assertIsNotNone(config.compute)
        self.assertIsNotNone(config.storage)

    def test_old_format_compatibility(self):
        """测试旧格式兼容性"""
        config = NetworkConfig(
            compute_nics=["eth0", "eth1"],
            storage_nics=["eth2"],
            management_nics=["eth3"]
        )
        self.assertEqual(config.compute_nics, ["eth0", "eth1"])
        self.assertEqual(config.storage_nics, ["eth2"])
        self.assertEqual(config.management_nics, ["eth3"])

    def test_get_enabled_networks(self):
        """测试获取启用的网络"""
        config = NetworkConfig(
            management=NetworkTypeConfig(description="管理网", enabled=True),
            compute=NetworkTypeConfig(description="计算网", enabled=True),
            storage=NetworkTypeConfig(description="存储网", enabled=False)
        )
        enabled = config.get_enabled_networks()
        self.assertIn('management', enabled)
        self.assertIn('compute', enabled)
        self.assertNotIn('storage', enabled)

    def test_get_network_interfaces(self):
        """测试获取网络接口"""
        config = NetworkConfig(
            compute=NetworkTypeConfig(interfaces=["eth0", "eth1"])
        )
        interfaces = config.get_network_interfaces('compute')
        self.assertEqual(interfaces, ["eth0", "eth1"])

        # 测试旧格式回退
        config2 = NetworkConfig(compute_nics=["eth2"])
        interfaces2 = config2.get_network_interfaces('compute')
        self.assertEqual(interfaces2, ["eth2"])

    def test_has_network_config(self):
        """测试检查网络配置"""
        config = NetworkConfig(
            compute=NetworkTypeConfig(interfaces=["eth0"], enabled=True)
        )
        self.assertTrue(config.has_network_config('compute'))
        self.assertFalse(config.has_network_config('storage'))


class TestRDMADetector(unittest.TestCase):
    """测试RDMA设备检测器"""

    def setUp(self):
        """测试前准备"""
        from src.network.rdma_detector import RDMADetector, RDMADeviceType, RDMADeviceInfo
        self.RDMADetector = RDMADetector
        self.RDMADeviceType = RDMADeviceType
        self.RDMADeviceInfo = RDMADeviceInfo

    def test_init_without_ssh_manager(self):
        """测试无SSH管理器初始化"""
        detector = self.RDMADetector()
        self.assertIsNone(detector.ssh_manager)

    def test_device_type_enum(self):
        """测试设备类型枚举"""
        self.assertEqual(str(self.RDMADeviceType.INFINIBAND), "infiniband")
        self.assertEqual(str(self.RDMADeviceType.ROCE), "roce")
        self.assertEqual(str(self.RDMADeviceType.UNKNOWN), "unknown")

    def test_device_info_to_dict(self):
        """测试设备信息转字典"""
        info = self.RDMADeviceInfo(
            device_name="mlx5_0",
            device_type=self.RDMADeviceType.ROCE,
            transport="InfiniBand",
            state="ACTIVE"
        )
        d = info.to_dict()
        self.assertEqual(d["device_name"], "mlx5_0")
        self.assertEqual(d["device_type"], "roce")


class TestIBWriteBWTester(unittest.TestCase):
    """测试ib_write_bw测试器"""

    def setUp(self):
        """测试前准备"""
        from src.network.ibandwidth_tester import IBWriteBWTester, BandwidthTestConfig, BandwidthTestResult
        self.IBWriteBWTester = IBWriteBWTester
        self.BandwidthTestConfig = BandwidthTestConfig
        self.BandwidthTestResult = BandwidthTestResult

    def test_default_config(self):
        """测试默认配置"""
        config = self.BandwidthTestConfig()
        self.assertEqual(config.duration, 10)
        self.assertEqual(config.size, 65536)
        self.assertEqual(config.port_base, 18500)

    def test_calculate_port(self):
        """测试端口计算"""
        tester = self.IBWriteBWTester()
        port1 = tester.calculate_port("mlx5_0", 18500)
        port2 = tester.calculate_port("mlx5_1", 18500)
        self.assertNotEqual(port1, port2)

    def test_result_to_dict(self):
        """测试结果转字典"""
        result = self.BandwidthTestResult(
            success=True,
            server_host="node01",
            client_host="node02",
            server_device="mlx5_0",
            client_device="mlx5_0",
            port=18500,
            bandwidth_gbps=380.5
        )
        d = result.to_dict()
        self.assertTrue(d["success"])
        self.assertEqual(d["bandwidth_gbps"], 380.5)


class TestThreePhaseTester(unittest.TestCase):
    """测试三轮测试策略"""

    def setUp(self):
        """测试前准备"""
        from src.network.three_phase_tester import (
            ThreePhaseTester,
            TestPhase,
            DeviceStatus,
            HostDevices
        )
        self.ThreePhaseTester = ThreePhaseTester
        self.TestPhase = TestPhase
        self.DeviceStatus = DeviceStatus
        self.HostDevices = HostDevices

    def test_host_devices(self):
        """测试主机设备信息"""
        host = self.HostDevices(
            hostname="node01",
            ip="10.0.0.1",
            devices=["mlx5_0", "mlx5_1"]
        )
        self.assertEqual(host.hostname, "node01")
        self.assertEqual(len(host.devices), 2)

    def test_phase_enum(self):
        """测试阶段枚举"""
        self.assertEqual(str(self.TestPhase.ROUND_1), "round1")
        self.assertEqual(str(self.TestPhase.ROUND_2), "round2")
        self.assertEqual(str(self.TestPhase.ROUND_3), "round3")


class TestDeploymentVerifier(unittest.TestCase):
    """测试部署验证检查器"""

    def setUp(self):
        """测试前准备"""
        from src.network.deployment_verifier import (
            DeploymentVerifier,
            CheckStatus,
            CheckCategory,
            CheckItem
        )
        self.DeploymentVerifier = DeploymentVerifier
        self.CheckStatus = CheckStatus
        self.CheckCategory = CheckCategory
        self.CheckItem = CheckItem

    def test_check_item(self):
        """测试检查项"""
        item = self.CheckItem(
            name="test_check",
            category=self.CheckCategory.SYSTEM,
            description="测试检查项"
        )
        self.assertEqual(item.name, "test_check")
        self.assertEqual(item.status, self.CheckStatus.FAILED)

    def test_check_item_to_dict(self):
        """测试检查项转字典"""
        item = self.CheckItem(
            name="test_check",
            category=self.CheckCategory.NETWORK,
            description="测试",
            status=self.CheckStatus.PASSED
        )
        d = item.to_dict()
        self.assertEqual(d["name"], "test_check")
        self.assertEqual(d["status"], "passed")


class TestIPResolver(unittest.TestCase):
    """测试IP解析器"""

    def setUp(self):
        """测试前准备"""
        from src.network.ip_resolver import IPResolver
        self.IPResolver = IPResolver

    def test_init_without_ssh_manager(self):
        """测试无SSH管理器初始化"""
        resolver = self.IPResolver()
        self.assertIsNone(resolver.ssh_manager)


if __name__ == '__main__':
    unittest.main()
