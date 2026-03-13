"""
网络连通性检查模块单元测试
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from src.network.connectivity_checker import (
    ConnectivityChecker,
    CheckType,
    CheckResult,
    HostConnectivityResult,
    generate_connectivity_report
)
from src.ssh_manager import SSHResult


class TestCheckResult:
    """CheckResult 测试"""

    def test_check_result_creation(self):
        """测试创建检查结果"""
        result = CheckResult(
            check_type=CheckType.IP,
            success=True,
            message="IP连通正常",
            latency_ms=15.5
        )
        assert result.check_type == CheckType.IP
        assert result.success is True
        assert result.message == "IP连通正常"
        assert result.latency_ms == 15.5

    def test_check_result_to_dict(self):
        """测试转换为字典"""
        result = CheckResult(
            check_type=CheckType.DNS,
            success=False,
            message="DNS解析失败",
            details={"error": "timeout"}
        )
        d = result.to_dict()
        assert d["check_type"] == "dns"
        assert d["success"] is False
        assert d["message"] == "DNS解析失败"
        assert d["details"]["error"] == "timeout"


class TestHostConnectivityResult:
    """HostConnectivityResult 测试"""

    def test_all_passed(self):
        """测试全部通过"""
        result = HostConnectivityResult(
            host="test-host",
            ip_check=CheckResult(CheckType.IP, True, "OK"),
            dns_check=CheckResult(CheckType.DNS, True, "OK"),
            http_check=CheckResult(CheckType.HTTP, True, "OK")
        )
        assert result.all_passed is True
        assert result.partial_passed is False

    def test_partial_passed(self):
        """测试部分通过"""
        result = HostConnectivityResult(
            host="test-host",
            ip_check=CheckResult(CheckType.IP, True, "OK"),
            dns_check=CheckResult(CheckType.DNS, False, "Failed"),
            http_check=CheckResult(CheckType.HTTP, True, "OK")
        )
        assert result.all_passed is False
        assert result.partial_passed is True

    def test_all_failed(self):
        """测试全部失败"""
        result = HostConnectivityResult(
            host="test-host",
            ip_check=CheckResult(CheckType.IP, False, "Failed"),
            dns_check=CheckResult(CheckType.DNS, False, "Failed"),
            http_check=CheckResult(CheckType.HTTP, False, "Failed")
        )
        assert result.all_passed is False
        assert result.partial_passed is False

    def test_to_dict(self):
        """测试转换为字典"""
        result = HostConnectivityResult(
            host="test-host",
            ip_check=CheckResult(CheckType.IP, True, "OK", 10.0),
            dns_check=CheckResult(CheckType.DNS, True, "OK", 20.0),
            http_check=CheckResult(CheckType.HTTP, False, "Failed")
        )
        d = result.to_dict()
        assert d["host"] == "test-host"
        assert d["all_passed"] is False
        assert "checks" in d
        assert d["checks"]["ip"]["success"] is True
        assert d["checks"]["dns"]["success"] is True
        assert d["checks"]["http"]["success"] is False


class TestConnectivityChecker:
    """ConnectivityChecker 测试"""

    @pytest.fixture
    def mock_ssh_manager(self):
        """创建 mock SSH 管理器"""
        manager = Mock()
        return manager

    @pytest.fixture
    def checker(self, mock_ssh_manager):
        """创建检查器实例"""
        return ConnectivityChecker(mock_ssh_manager)

    def test_check_ip_connectivity_success(self, checker, mock_ssh_manager):
        """测试 IP 连通性检查成功"""
        mock_result = Mock(spec=SSHResult)
        mock_result.success = True
        mock_result.stdout = """
PING 8.8.8.8 (8.8.8.8) 56(84) bytes of data.
64 bytes from 8.8.8.8: icmp_seq=1 ttl=117 time=10.5 ms
64 bytes from 8.8.8.8: icmp_seq=2 ttl=117 time=11.2 ms
64 bytes from 8.8.8.8: icmp_seq=3 ttl=117 time=10.8 ms

--- 8.8.8.8 ping statistics ---
3 packets transmitted, 3 received, 0% packet loss, time 2003ms
rtt min/avg/max/mdev = 10.5/10.8/11.2/0.3 ms
"""
        mock_result.stderr = ""
        mock_ssh_manager.execute_on_host.return_value = mock_result

        result = checker.check_ip_connectivity("test-host", "user", "pass")

        assert result.success is True
        assert result.check_type == CheckType.IP
        assert "连通正常" in result.message
        assert result.latency_ms > 0

    def test_check_ip_connectivity_failure(self, checker, mock_ssh_manager):
        """测试 IP 连通性检查失败"""
        mock_result = Mock(spec=SSHResult)
        mock_result.success = True
        mock_result.stdout = "ping: connect: Network is unreachable"
        mock_result.stderr = ""
        mock_ssh_manager.execute_on_host.return_value = mock_result

        result = checker.check_ip_connectivity("test-host", "user", "pass")

        assert result.success is False
        assert "失败" in result.message

    def test_check_dns_resolution_success(self, checker, mock_ssh_manager):
        """测试 DNS 解析检查成功"""
        mock_result = Mock(spec=SSHResult)
        mock_result.success = True
        mock_result.stdout = """
PING www.baidu.com (110.242.68.66) 56(84) bytes of data.
64 bytes from 110.242.68.66: icmp_seq=1 ttl=52 time=20.1 ms

--- www.baidu.com ping statistics ---
3 packets transmitted, 3 received, 0% packet loss
rtt min/avg/max/mdev = 20.1/20.5/21.0/0.4 ms
"""
        mock_result.stderr = ""
        mock_ssh_manager.execute_on_host.return_value = mock_result

        result = checker.check_dns_resolution("test-host", "user", "pass")

        assert result.success is True
        assert result.check_type == CheckType.DNS

    def test_check_dns_resolution_failure(self, checker, mock_ssh_manager):
        """测试 DNS 解析失败"""
        mock_result = Mock(spec=SSHResult)
        mock_result.success = True
        mock_result.stdout = "ping: www.baidu.com: Name or service not known"
        mock_result.stderr = ""
        mock_ssh_manager.execute_on_host.return_value = mock_result

        result = checker.check_dns_resolution("test-host", "user", "pass")

        assert result.success is False
        assert "DNS解析失败" in result.message

    def test_check_http_connection_success(self, checker, mock_ssh_manager):
        """测试 HTTP 连接检查成功"""
        mock_result = Mock(spec=SSHResult)
        mock_result.success = True
        mock_result.stdout = "200"
        mock_result.stderr = ""
        mock_ssh_manager.execute_on_host.return_value = mock_result

        result = checker.check_http_connection("test-host", "user", "pass")

        assert result.success is True
        assert result.check_type == CheckType.HTTP
        assert "200" in result.message

    def test_check_http_connection_failure(self, checker, mock_ssh_manager):
        """测试 HTTP 连接失败"""
        mock_result = Mock(spec=SSHResult)
        mock_result.success = True
        mock_result.stdout = "500"
        mock_result.stderr = ""
        mock_ssh_manager.execute_on_host.return_value = mock_result

        result = checker.check_http_connection("test-host", "user", "pass")

        assert result.success is False
        assert "500" in result.message

    def test_check_host_parallel(self, checker, mock_ssh_manager):
        """测试单台主机的所有检查（并行）"""
        # 设置 mock 返回不同结果
        results = [
            Mock(spec=SSHResult, success=True, stdout="0% packet loss\nrtt min/avg/max/mdev = 10/11/12/1 ms", stderr=""),
            Mock(spec=SSHResult, success=True, stdout="0% packet loss\nrtt min/avg/max/mdev = 20/21/22/1 ms", stderr=""),
            Mock(spec=SSHResult, success=True, stdout="200", stderr=""),
        ]
        mock_ssh_manager.execute_on_host.side_effect = results

        result = checker.check_host("test-host", "user", "pass")

        assert isinstance(result, HostConnectivityResult)
        assert result.host == "test-host"
        assert mock_ssh_manager.execute_on_host.call_count == 3

    def test_parse_ping_latency(self, checker):
        """测试 ping 延迟解析"""
        output = "rtt min/avg/max/mdev = 10.5/11.2/12.0/0.5 ms"
        latency = checker._parse_ping_latency(output)
        assert latency == 11.2

    def test_parse_ping_error_destination_unreachable(self, checker):
        """测试 ping 错误解析 - 目标不可达"""
        output = "Destination Host Unreachable"
        error = checker._parse_ping_error(output)
        assert "不可达" in error

    def test_parse_ping_error_network_unreachable(self, checker):
        """测试 ping 错误解析 - 网络不可达"""
        output = "Network is unreachable"
        error = checker._parse_ping_error(output)
        assert "不可达" in error

    def test_parse_ping_error_packet_loss(self, checker):
        """测试 ping 错误解析 - 丢包"""
        output = "3 packets transmitted, 0 received, 100% packet loss"
        error = checker._parse_ping_error(output)
        assert "丢包" in error


class TestGenerateConnectivityReport:
    """报告生成测试"""

    def test_generate_report_all_passed(self):
        """测试生成全部通过的报告"""
        results = {
            "host1": HostConnectivityResult(
                host="host1",
                ip_check=CheckResult(CheckType.IP, True, "OK"),
                dns_check=CheckResult(CheckType.DNS, True, "OK"),
                http_check=CheckResult(CheckType.HTTP, True, "OK")
            ),
            "host2": HostConnectivityResult(
                host="host2",
                ip_check=CheckResult(CheckType.IP, True, "OK"),
                dns_check=CheckResult(CheckType.DNS, True, "OK"),
                http_check=CheckResult(CheckType.HTTP, True, "OK")
            )
        }

        report = generate_connectivity_report(results)

        assert "# 网络连通性检查报告" in report
        assert "host1" in report
        assert "host2" in report
        assert "2 全部通过" in report

    def test_generate_report_mixed_results(self):
        """测试生成混合结果的报告"""
        results = {
            "host1": HostConnectivityResult(
                host="host1",
                ip_check=CheckResult(CheckType.IP, True, "OK"),
                dns_check=CheckResult(CheckType.DNS, True, "OK"),
                http_check=CheckResult(CheckType.HTTP, True, "OK")
            ),
            "host2": HostConnectivityResult(
                host="host2",
                ip_check=CheckResult(CheckType.IP, True, "OK"),
                dns_check=CheckResult(CheckType.DNS, False, "DNS failed"),
                http_check=CheckResult(CheckType.HTTP, False, "HTTP failed")
            )
        }

        report = generate_connectivity_report(results)

        assert "1 全部通过" in report
        assert "1 部分通过" in report
        assert "失败详情" in report


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
