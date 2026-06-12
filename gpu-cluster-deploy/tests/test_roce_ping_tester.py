"""
RoCE Ping Tester单元测试
"""

import unittest
from unittest.mock import Mock, MagicMock, patch

from src.network.roce_ping_tester import (
    RoCEPingTester,
    PingResult,
    PingTestReport
)


class TestPingResult(unittest.TestCase):
    """测试PingResult数据类"""

    def test_default_values(self):
        """测试默认值"""
        result = PingResult(
            source_host="host1",
            source_interface="eth0",
            source_ip="10.0.0.1",
            target_host="host2",
            target_interface="eth0",
            target_ip="10.0.0.2",
            success=True
        )
        self.assertEqual(result.source_host, "host1")
        self.assertEqual(result.packet_loss, 0.0)
        self.assertEqual(result.avg_latency_ms, 0.0)
        self.assertEqual(result.error_message, "")

    def test_to_dict(self):
        """测试to_dict方法"""
        result = PingResult(
            source_host="host1",
            source_interface="eth0",
            source_ip="10.0.0.1",
            target_host="host2",
            target_interface="eth0",
            target_ip="10.0.0.2",
            success=False,
            packet_loss=100.0,
            avg_latency_ms=0.0,
            error_message="100% loss"
        )
        d = result.to_dict()
        self.assertEqual(d["source_host"], "host1")
        self.assertEqual(d["packet_loss"], 100.0)
        self.assertFalse(d["success"])
        self.assertEqual(d["error_message"], "100% loss")


class TestPingTestReport(unittest.TestCase):
    """测试PingTestReport数据类"""

    def test_default_values(self):
        """测试默认值"""
        report = PingTestReport()
        self.assertEqual(report.network_type, "compute")
        self.assertEqual(report.device_type, "RoCE")
        self.assertEqual(report.total_tests, 0)
        self.assertEqual(report.passed_tests, 0)
        self.assertEqual(report.failed_tests, 0)

    def test_to_dict(self):
        """测试to_dict方法"""
        result = PingResult(
            source_host="host1",
            source_interface="eth0",
            source_ip="10.0.0.1",
            target_host="host2",
            target_interface="eth0",
            target_ip="10.0.0.2",
            success=True
        )
        report = PingTestReport(
            network_type="storage",
            device_type="InfiniBand",
            results=[result],
            total_tests=1,
            passed_tests=1,
            failed_tests=0
        )
        d = report.to_dict()
        self.assertEqual(d["network_type"], "storage")
        self.assertEqual(d["device_type"], "InfiniBand")
        self.assertEqual(len(d["results"]), 1)


class TestRoCEPingTester(unittest.TestCase):
    """测试RoCEPingTester类"""

    def setUp(self):
        """测试前准备"""
        self.tester = RoCEPingTester()

    def test_init_without_ssh_manager(self):
        """测试无SSH管理器初始化"""
        self.assertIsNone(self.tester.ssh_manager)
        self.assertIsNone(self.tester.rdma_detector)

    def test_get_interface_ip_no_ssh_manager(self):
        """测试无SSH管理器时获取IP"""
        result = self.tester.get_interface_ip("host1", "eth0")
        self.assertIsNone(result)

    def test_get_interface_ip_invalid_interface(self):
        """测试无效网卡名称"""
        mock_ssh = Mock()
        self.tester.ssh_manager = mock_ssh
        result = self.tester.get_interface_ip("host1", "")
        self.assertIsNone(result)

        result = self.tester.get_interface_ip("host1", None)
        self.assertIsNone(result)

    def test_ping_test_no_ssh_manager(self):
        """测试无SSH管理器时ping测试"""
        result = self.tester.ping_test("host1", "eth0", "host2", "10.0.0.2")
        self.assertFalse(result.success)
        self.assertIn("IP", result.error_message)  # Updated to match new error message

    def test_generate_report_text_empty(self):
        """测试空报告生成"""
        report = PingTestReport()
        text = self.tester.generate_report_text(report)
        self.assertIn("Ping 连通性测试", text)
        self.assertIn("无测试结果", text)

    def test_generate_report_text_with_results(self):
        """测试有结果的报告生成"""
        result1 = PingResult(
            source_host="host1",
            source_interface="eth0",
            source_ip="10.0.0.1",
            target_host="host2",
            target_interface="eth0",
            target_ip="10.0.0.2",
            success=True,
            packet_loss=0.0,
            avg_latency_ms=0.5
        )
        result2 = PingResult(
            source_host="host2",
            source_interface="eth0",
            source_ip="10.0.0.2",
            target_host="host1",
            target_interface="eth0",
            target_ip="10.0.0.1",
            success=False,
            packet_loss=100.0,
            error_message="100% loss"
        )
        report = PingTestReport(
            results=[result1, result2],
            total_tests=2,
            passed_tests=1,
            failed_tests=1
        )
        text = self.tester.generate_report_text(report)
        self.assertIn("host1 <-> host2", text)
        self.assertIn("✓", text)
        self.assertIn("✗", text)
        self.assertIn("1 通过 / 1 失败", text)


class TestRoCEPingTesterWithMock(unittest.TestCase):
    """测试RoCEPingTester类（使用Mock）"""

    def setUp(self):
        """测试前准备"""
        self.mock_ssh = Mock()
        self.mock_detector = Mock()
        self.tester = RoCEPingTester(
            ssh_manager=self.mock_ssh,
            rdma_detector=self.mock_detector
        )

    def test_get_interface_ip_success(self):
        """测试成功获取IP"""
        mock_result = Mock()
        mock_result.success = True
        mock_result.stdout = "10.0.0.1\n"
        self.mock_ssh.execute_on_host.return_value = mock_result

        result = self.tester.get_interface_ip("host1", "eth0")
        self.assertEqual(result, "10.0.0.1")

    def test_get_interface_ip_failure(self):
        """测试获取IP失败"""
        mock_result = Mock()
        mock_result.success = False
        mock_result.stdout = ""
        self.mock_ssh.execute_on_host.return_value = mock_result

        result = self.tester.get_interface_ip("host1", "eth0")
        self.assertIsNone(result)

    def test_get_rdma_interfaces(self):
        """测试获取RDMA网卡"""
        self.mock_detector.get_all_devices.return_value = ["mlx5_0", "mlx5_1"]
        self.mock_detector.get_device_netdev.side_effect = lambda h, d: {
            "mlx5_0": "ens11np0",
            "mlx5_1": "ens12np0"
        }.get(d)

        mock_result = Mock()
        mock_result.success = True
        mock_result.stdout = "10.0.1.1\n"
        self.mock_ssh.execute_on_host.return_value = mock_result

        interfaces = self.tester.get_rdma_interfaces("host1")
        self.assertIn("ens11np0", interfaces)
        self.assertIn("ens12np0", interfaces)

    def test_get_rdma_interfaces_no_devices(self):
        """测试无RDMA设备"""
        self.mock_detector.get_all_devices.return_value = []

        interfaces = self.tester.get_rdma_interfaces("host1")
        self.assertEqual(interfaces, {})

    def test_ping_test_success(self):
        """测试成功的ping测试"""
        # Mock get_interface_ip
        mock_ip_result = Mock()
        mock_ip_result.success = True
        mock_ip_result.stdout = "10.0.0.1\n"

        # Mock ping command
        mock_ping_result = Mock()
        mock_ping_result.success = True
        mock_ping_result.stdout = """
PING 10.0.0.2 (10.0.0.2) from 10.0.0.1 eth0: 56(84) bytes of data.
64 bytes from 10.0.0.2: icmp_seq=1 ttl=64 time=0.5 ms
64 bytes from 10.0.0.2: icmp_seq=2 ttl=64 time=0.4 ms
64 bytes from 10.0.0.2: icmp_seq=3 ttl=64 time=0.6 ms

--- 10.0.0.2 ping statistics ---
3 packets transmitted, 3 received, 0% packet loss, time 2049ms
rtt min/avg/max/mdev = 0.4/0.5/0.6/0.1 ms
"""

        self.mock_ssh.execute_on_host.side_effect = [mock_ip_result, mock_ping_result]

        result = self.tester.ping_test("host1", "eth0", "host2", "10.0.0.2")

        self.assertTrue(result.success)
        self.assertEqual(result.packet_loss, 0.0)
        self.assertGreater(result.avg_latency_ms, 0)

    def test_ping_test_failure(self):
        """测试失败的ping测试"""
        # Mock get_interface_ip
        mock_ip_result = Mock()
        mock_ip_result.success = True
        mock_ip_result.stdout = "10.0.0.1\n"

        # Mock ping command with failure
        mock_ping_result = Mock()
        mock_ping_result.success = True
        mock_ping_result.stdout = """
PING 10.0.0.2 (10.0.0.2) from 10.0.0.1 eth0: 56(84) bytes of data.

--- 10.0.0.2 ping statistics ---
3 packets transmitted, 0 received, 100% packet loss, time 2049ms
"""

        self.mock_ssh.execute_on_host.side_effect = [mock_ip_result, mock_ping_result]

        result = self.tester.ping_test("host1", "eth0", "host2", "10.0.0.2")

        self.assertFalse(result.success)
        self.assertEqual(result.packet_loss, 100.0)


class TestBandwidthTestResultFields(unittest.TestCase):
    """测试BandwidthTestResult新增字段"""

    def test_new_fields(self):
        """测试新增的test_command和device_type字段"""
        from src.network.ibandwidth_tester import BandwidthTestResult

        result = BandwidthTestResult(
            success=True,
            server_host="host1",
            client_host="host2",
            server_device="mlx5_0",
            client_device="mlx5_0",
            port=18500,
            test_command="ib_write_bw -d mlx5_0 -R -F -s 65536 -D 10 -p 18500 host1",
            device_type="roce"
        )

        self.assertEqual(result.test_command, "ib_write_bw -d mlx5_0 -R -F -s 65536 -D 10 -p 18500 host1")
        self.assertEqual(result.device_type, "roce")

    def test_to_dict_includes_new_fields(self):
        """测试to_dict包含新字段"""
        from src.network.ibandwidth_tester import BandwidthTestResult

        result = BandwidthTestResult(
            success=True,
            server_host="host1",
            client_host="host2",
            server_device="mlx5_0",
            client_device="mlx5_0",
            port=18500,
            test_command="ib_write_bw ...",
            device_type="infiniband"
        )

        d = result.to_dict()
        self.assertIn("test_command", d)
        self.assertIn("device_type", d)
        self.assertEqual(d["test_command"], "ib_write_bw ...")
        self.assertEqual(d["device_type"], "infiniband")


class TestDeviceTestStats(unittest.TestCase):
    """测试DeviceTestStats数据类"""

    def test_default_values(self):
        """测试默认值"""
        from src.network.three_phase_tester import DeviceTestStats, DeviceStatus

        stats = DeviceTestStats()
        self.assertEqual(stats.status, DeviceStatus.UNKNOWN)
        self.assertEqual(stats.test_count, 0)
        self.assertEqual(stats.fail_count, 0)
        self.assertEqual(stats.error_details, [])

    def test_to_dict(self):
        """测试to_dict方法"""
        from src.network.three_phase_tester import DeviceTestStats, DeviceStatus

        stats = DeviceTestStats(
            status=DeviceStatus.ABNORMAL,
            test_count=2,
            fail_count=2,
            error_details=["Error 1", "Error 2"]
        )
        d = stats.to_dict()
        self.assertEqual(d["status"], "abnormal")
        self.assertEqual(d["test_count"], 2)
        self.assertEqual(d["fail_count"], 2)
        self.assertEqual(len(d["error_details"]), 2)


class TestThreePhaseReportNewFields(unittest.TestCase):
    """测试ThreePhaseReport新字段"""

    def test_new_fields(self):
        """测试新增字段"""
        from src.network.three_phase_tester import ThreePhaseReport

        report = ThreePhaseReport(
            network_type="compute",
            device_type="RoCE",
            theoretical_bandwidth_gbps=400.0,
            test_config={"duration": 10, "size": 65536}
        )

        self.assertEqual(report.network_type, "compute")
        self.assertEqual(report.device_type, "RoCE")
        self.assertEqual(report.theoretical_bandwidth_gbps, 400.0)
        self.assertEqual(report.test_config["duration"], 10)

    def test_to_dict_includes_new_fields(self):
        """测试to_dict包含新字段"""
        from src.network.three_phase_tester import ThreePhaseReport

        report = ThreePhaseReport(
            network_type="storage",
            device_type="InfiniBand",
            theoretical_bandwidth_gbps=200.0
        )
        d = report.to_dict()
        self.assertIn("network_type", d)
        self.assertIn("device_type", d)
        self.assertIn("theoretical_bandwidth_gbps", d)
        self.assertEqual(d["network_type"], "storage")
        self.assertEqual(d["device_type"], "InfiniBand")


if __name__ == '__main__':
    unittest.main()
