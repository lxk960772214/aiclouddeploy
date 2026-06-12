"""
步骤0c: RDMA网络测试 - 独立测试步骤
"""

import time
from typing import List, Optional, Dict
from src.steps.base import BaseStep, StepResult, StepStatus
from src.network.rdma_detector import RDMADetector, RDMADeviceType
from src.network.ibandwidth_tester import IBWriteBWTester, BandwidthTestConfig
from src.network.three_phase_tester import ThreePhaseTester, ThreePhaseReport
from src.network.deployment_verifier import DeploymentVerifier, DeploymentVerificationReport
from src.network.roce_ping_tester import RoCEPingTester, PingTestReport


class NetworkRDMATest(BaseStep):
    """RDMA网络测试步骤

    支持独立执行网络测试，无需运行完整部署流程
    """

    step_id = "0c"
    step_name = "RDMA网络测试"
    step_description = "执行RDMA网络带宽测试和异常定位"
    requires_sudo = False
    supports_batch = False
    can_skip = True
    timeout = 1800  # 30分钟

    def __init__(self, config=None, ssh_manager=None, batch_executor=None, logger=None, versions=None):
        super().__init__(config, ssh_manager, batch_executor, logger, versions)

        # 初始化网络测试组件
        self.rdma_detector = RDMADetector(ssh_manager)
        self.bandwidth_tester = IBWriteBWTester(ssh_manager, self.rdma_detector)
        self.three_phase_tester = ThreePhaseTester(ssh_manager, self.rdma_detector, self.bandwidth_tester)
        self.deployment_verifier = DeploymentVerifier(ssh_manager)
        self.roce_ping_tester = RoCEPingTester(ssh_manager, self.rdma_detector)

        # 存储检测到的设备类型
        self.detected_device_type = "RoCE"

    def execute(self, hosts: List[str], network_type: str = "compute") -> StepResult:
        """执行RDMA网络测试

        Args:
            hosts: 主机列表
            network_type: 网络类型 (compute/storage)

        Returns:
            StepResult对象
        """
        start_time = time.time()

        self.logger.info(f"开始RDMA网络测试 (网络类型: {network_type})...")

        # 1. 部署验证
        self.logger.info("步骤1: 验证部署状态...")
        deployment_report = self._verify_deployment(hosts)
        if not deployment_report:
            return StepResult(
                step_id=self.step_id,
                step_name=self.step_name,
                status=StepStatus.FAILED,
                message="部署验证失败",
                errors=["无法完成部署验证"]
            )

        # 检查是否可以进行测试
        if not self.deployment_verifier.check_deployment_readiness(deployment_report):
            self.logger.warning("部署未完成，某些主机可能无法正常测试")

        # 2. 收集主机设备信息
        self.logger.info("步骤2: 收集RDMA设备信息...")
        hosts_info = self._collect_hosts_info(hosts, network_type)
        if not hosts_info:
            return StepResult(
                step_id=self.step_id,
                step_name=self.step_name,
                status=StepStatus.FAILED,
                message="无法收集RDMA设备信息",
                errors=["未找到任何RDMA设备"]
            )

        # 3. 检测设备类型
        self.detected_device_type = self._detect_device_type(hosts_info)
        self.logger.info(f"检测到设备类型: {self.detected_device_type}")

        # 4. 获取测试配置
        test_config = self._get_test_config(network_type)

        # 5. 执行RoCE Ping测试 (仅RoCE网络)
        ping_report = None
        if self.detected_device_type == "RoCE":
            self.logger.info("步骤3: 执行RoCE Ping连通性测试...")
            ping_report = self._execute_ping_test(hosts_info, network_type)

        # 6. 执行三轮带宽测试
        self.logger.info("步骤4: 执行三轮带宽测试...")
        test_report = self.three_phase_tester.execute(
            hosts_info=hosts_info,
            test_config=test_config,
            max_workers=4,
            skip_round2_if_all_normal=True,
            network_type=network_type
        )

        duration = time.time() - start_time

        # 7. 生成报告
        markdown_report = self.three_phase_tester.generate_markdown_report(test_report)

        # 确定状态
        if test_report.summary.get("all_normal", False):
            status = StepStatus.SUCCESS
            message = "所有RDMA设备测试正常"
        elif test_report.summary.get("abnormal_hosts", 0) > 0:
            status = StepStatus.FAILED
            message = f"发现 {test_report.summary.get('abnormal_hosts', 0)} 台主机存在异常设备"
        else:
            status = StepStatus.SUCCESS
            message = "测试完成，部分设备需要关注"

        result_details = {
            "deployment_report": deployment_report.to_dict(),
            "test_report": test_report.to_dict(),
            "markdown_report": markdown_report,
            "network_type": network_type,
            "device_type": self.detected_device_type
        }

        if ping_report:
            result_details["ping_report"] = ping_report.to_dict()

        return StepResult(
            step_id=self.step_id,
            step_name=self.step_name,
            status=status,
            message=message,
            duration=duration,
            details=result_details,
            host_results={
                host: {
                    "devices": info.get("devices", []),
                    "device_type": self.detected_device_type,
                    "status": "tested"
                }
                for host, info in zip(hosts, hosts_info)
            }
        )

    def _detect_device_type(self, hosts_info: List[Dict]) -> str:
        """检测设备类型

        Args:
            hosts_info: 主机信息列表

        Returns:
            设备类型字符串 (RoCE/InfiniBand)
        """
        if not hosts_info:
            return "RoCE"

        try:
            first_host = hosts_info[0].get("hostname", "")
            devices = hosts_info[0].get("devices", [])

            if first_host and devices:
                info = self.rdma_detector.detect_device_type(first_host, devices[0])
                device_type = str(info.device_type)
                if "infiniband" in device_type.lower():
                    return "InfiniBand"
                elif "roce" in device_type.lower():
                    return "RoCE"
        except Exception as e:
            self.logger.debug(f"检测设备类型失败: {e}")

        return "RoCE"

    def _execute_ping_test(self, hosts_info: List[Dict], network_type: str) -> Optional[PingTestReport]:
        """执行RoCE Ping连通性测试

        Args:
            hosts_info: 主机信息列表
            network_type: 网络类型

        Returns:
            PingTestReport对象，失败返回None
        """
        try:
            # 收集主机的网卡信息
            hosts_with_interfaces = []
            for host_info in hosts_info:
                hostname = host_info.get("hostname", "")
                if not hostname:
                    continue

                # 获取RDMA网卡
                interfaces = self.roce_ping_tester.get_rdma_interfaces(hostname)
                if not interfaces:
                    self.logger.warning(f"主机 {hostname} 未找到RDMA网卡，跳过Ping测试")
                    continue

                # 验证接口有效性
                if not isinstance(interfaces, dict) or len(interfaces) == 0:
                    self.logger.warning(f"主机 {hostname} 的网卡信息无效，跳过Ping测试")
                    continue

                hosts_with_interfaces.append({
                    "hostname": hostname,
                    "ip": host_info.get("ip", ""),
                    "interfaces": interfaces
                })

            if len(hosts_with_interfaces) < 2:
                self.logger.warning("有效主机数量不足，跳过Ping测试")
                return None

            # 执行Ping测试
            ping_report = self.roce_ping_tester.test_all_pairs(
                hosts_with_interfaces,
                network_type=network_type,
                device_type=self.detected_device_type
            )

            self.logger.info(f"Ping测试完成: {ping_report.passed_tests}/{ping_report.total_tests} 通过")
            return ping_report

        except Exception as e:
            self.logger.error(f"Ping测试失败: {e}")
            return None

    def _verify_deployment(self, hosts: List[str]) -> Optional[DeploymentVerificationReport]:
        """验证部署状态"""
        hosts_list = []
        for host in hosts:
            node = self.config.get_node_by_hostname(host) or self.config.get_node_by_ip(host)
            hosts_list.append({
                "hostname": host,
                "ip": node.ip if node else host
            })

        return self.deployment_verifier.verify_cluster(hosts_list)

    def _collect_hosts_info(self, hosts: List[str], network_type: str = "compute") -> List[Dict]:
        """收集主机RDMA设备信息

        Args:
            hosts: 主机列表
            network_type: 网络类型

        Returns:
            主机信息列表
        """
        hosts_info = []

        for host in hosts:
            # 获取RDMA设备列表
            devices = self.rdma_detector.get_all_devices(host)

            if not devices:
                self.logger.warning(f"主机 {host} 未找到RDMA设备")
                continue

            # 获取节点信息
            node = self.config.get_node_by_hostname(host) or self.config.get_node_by_ip(host)

            # 获取网络配置中的设备
            network_config = self.config.network
            configured_devices = []

            if network_config:
                # 根据网络类型获取对应的设备配置
                if network_type == "compute" and network_config.compute:
                    configured_devices = network_config.compute.rdma_devices or []
                elif network_type == "storage" and network_config.storage:
                    configured_devices = network_config.storage.rdma_devices or []
                # 兼容旧配置
                elif network_config.compute and network_config.compute.rdma_devices:
                    configured_devices = network_config.compute.rdma_devices
                elif network_config.storage and network_config.storage.rdma_devices:
                    configured_devices = network_config.storage.rdma_devices

            # 如果有配置设备，使用配置的；否则使用检测到的所有设备
            devices_to_test = configured_devices if configured_devices else devices

            hosts_info.append({
                "hostname": host,
                "ip": node.ip if node else host,
                "devices": devices_to_test,
                "all_devices": devices
            })

        return hosts_info

    def _get_test_config(self, network_type: str = "compute") -> Dict:
        """获取测试配置

        Args:
            network_type: 网络类型

        Returns:
            测试配置字典
        """
        network_config = self.config.network

        config = {
            "duration": 10,
            "size": 65536,
            "port_base": 18500,
            "min_bandwidth_percent": 90.0,
            "theoretical_bandwidth_gbps": 400.0
        }

        if network_config and network_config.ib_write_bw:
            ib_config = network_config.ib_write_bw
            config["duration"] = ib_config.duration
            config["size"] = ib_config.size
            config["port_base"] = ib_config.port_base
            config["min_bandwidth_percent"] = ib_config.min_bandwidth_percent

        # 从网络配置获取理论带宽
        if network_config:
            if network_type == "compute" and network_config.compute:
                config["theoretical_bandwidth_gbps"] = network_config.compute.theoretical_bandwidth_gbps
            elif network_type == "storage" and network_config.storage:
                config["theoretical_bandwidth_gbps"] = network_config.storage.theoretical_bandwidth_gbps

        return config

    def execute_test_only(self, hosts: Optional[List[str]] = None,
                          network_type: str = "compute",
                          output_format: str = "text") -> Dict:
        """
        独立测试模式 - 跳过部署直接测试

        Args:
            hosts: 指定测试的主机列表，None表示测试所有主机
            network_type: 网络类型 (compute/storage)
            output_format: 输出格式 (text/json/html)

        Returns:
            测试结果字典
        """
        if hosts is None:
            hosts = [node.hostname for node in self.config.nodes]

        result = self.execute(hosts, network_type)

        output = {
            "success": result.status == StepStatus.SUCCESS,
            "message": result.message,
            "duration": result.duration,
            "test_report": result.details.get("test_report", {}),
            "deployment_report": result.details.get("deployment_report", {}),
            "network_type": result.details.get("network_type", network_type),
            "device_type": result.details.get("device_type", "RoCE")
        }

        # 添加Ping测试报告
        ping_report = result.details.get("ping_report")
        if ping_report:
            output["ping_report"] = ping_report

        if output_format == "json":
            return output
        elif output_format == "html":
            output["html_report"] = self._generate_html_report(result)
            return output
        else:
            output["text_report"] = result.details.get("markdown_report", "")
            return output

    def _generate_html_report(self, result: StepResult) -> str:
        """生成HTML报告"""
        test_report_dict = result.details.get("test_report", {})
        ping_report_dict = result.details.get("ping_report", {})
        device_type = result.details.get("device_type", "RoCE")
        network_type = result.details.get("network_type", "compute")

        html = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>RDMA网络测试报告</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; }
        h1 { color: #333; }
        h2 { color: #666; border-bottom: 1px solid #ccc; padding-bottom: 5px; }
        table { border-collapse: collapse; width: 100%; margin: 10px 0; }
        th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }
        th { background-color: #f2f2f2; }
        .success { color: green; }
        .failed { color: red; }
        .warning { color: orange; }
        .summary { background-color: #f9f9f9; padding: 15px; border-radius: 5px; margin: 10px 0; }
        .config { background-color: #e8f4f8; padding: 10px; border-radius: 5px; margin: 10px 0; }
    </style>
</head>
<body>
    <h1>RDMA网络测试报告</h1>
"""
        # 测试配置
        html += f"""
    <div class="config">
        <h2>测试配置</h2>
        <p>网络类型: {network_type}</p>
        <p>设备类型: {device_type} (自动检测)</p>
        <p>理论带宽: {test_report_dict.get('theoretical_bandwidth_gbps', 400)} Gbps</p>
    </div>
"""

        # Ping测试结果 (仅RoCE)
        if ping_report_dict and ping_report_dict.get('results'):
            html += """
    <h2>Ping 连通性测试 (RoCE IP层)</h2>
    <table>
        <tr><th>源主机</th><th>源网卡</th><th>目标主机</th><th>目标网卡</th><th>状态</th><th>丢包率</th><th>延迟</th></tr>
"""
            for pr in ping_report_dict.get('results', []):
                status_class = "success" if pr.get('success') else "failed"
                status_text = "✓" if pr.get('success') else "✗"
                html += f"""
        <tr>
            <td>{pr.get('source_host', '')}</td>
            <td>{pr.get('source_interface', '')}</td>
            <td>{pr.get('target_host', '')}</td>
            <td>{pr.get('target_interface', '')}</td>
            <td class='{status_class}'>{status_text}</td>
            <td>{pr.get('packet_loss', 0):.0f}%</td>
            <td>{pr.get('avg_latency_ms', 0):.1f}ms</td>
        </tr>
"""
            html += f"""
    </table>
    <p>Ping测试结果: {ping_report_dict.get('passed_tests', 0)} 通过 / {ping_report_dict.get('failed_tests', 0)} 失败</p>
"""

        # 摘要
        summary = test_report_dict.get("summary", {})
        html += f"""
    <div class="summary">
        <h2>ib_write_bw 带宽测试摘要</h2>
        <p>总主机数: {summary.get('total_hosts', 0)}</p>
        <p>总设备数: {summary.get('total_devices', 0)}</p>
        <p>正常设备: <span class="success">{summary.get('normal_devices', 0)}</span></p>
        <p>疑似设备: <span class="warning">{summary.get('suspected_devices', 0)}</span></p>
        <p>异常设备: <span class="failed">{summary.get('abnormal_devices', 0)}</span></p>
        <p>执行轮次: {summary.get('rounds_executed', 0)}</p>
    </div>
"""

        # 异常设备
        abnormal_list = summary.get('abnormal_device_list', [])
        device_stats = test_report_dict.get("device_stats", {})

        if abnormal_list:
            html += """
    <h2>异常设备详情</h2>
"""
            for device in abnormal_list:
                parts = device.split(':')
                if len(parts) == 2:
                    hostname, dev = parts
                    stats = device_stats.get(hostname, {}).get(dev, {})
                    html += f"""
    <div class="failed">
        <p><strong>✗ {device}</strong> - 两轮测试均失败</p>
        <ul>
"""
                    for detail in stats.get('error_details', []):
                        html += f"            <li>{detail}</li>\n"
                    html += """        </ul>
    </div>
"""

        # 设备状态详情
        final_status = test_report_dict.get("final_status", {})
        if final_status:
            html += """
    <h2>设备状态详情</h2>
    <table>
        <tr><th>主机</th><th>设备</th><th>状态</th><th>测试次数</th><th>失败次数</th></tr>
"""
            for hostname, devices in sorted(final_status.items()):
                for device, status in sorted(devices.items()):
                    stats = device_stats.get(hostname, {}).get(device, {})
                    test_count = stats.get('test_count', 0)
                    fail_count = stats.get('fail_count', 0)
                    status_class = "success" if status == "normal" else \
                                  "failed" if status == "abnormal" else "warning"
                    status_text = "正常" if status == "normal" else \
                                 "异常" if status == "abnormal" else "疑似"
                    html += f"        <tr><td>{hostname}</td><td>{device}</td><td class='{status_class}'>{status_text}</td><td>{test_count}</td><td>{fail_count}</td></tr>\n"
            html += "    </table>\n"

        html += """
</body>
</html>
"""
        return html

    def post_check(self, hosts: List[str]) -> bool:
        """验证测试结果"""
        # 简单检查是否有异常设备
        result = self.execute(hosts)
        return result.status == StepStatus.SUCCESS

    def get_test_report(self, result: StepResult, format: str = "markdown") -> str:
        """
        获取测试报告

        Args:
            result: 步骤执行结果
            format: 报告格式 (markdown/json/html)

        Returns:
            报告字符串
        """
        if format == "json":
            import json
            return json.dumps(result.details.get("test_report", {}), indent=2)
        elif format == "html":
            return self._generate_html_report(result)
        else:
            return result.details.get("markdown_report", "")
