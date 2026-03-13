"""
步骤0c: RDMA网络测试 - 独立测试步骤
"""

import time
from typing import List, Optional, Dict
from src.steps.base import BaseStep, StepResult, StepStatus
from src.network.rdma_detector import RDMADetector
from src.network.ibandwidth_tester import IBWriteBWTester, BandwidthTestConfig
from src.network.three_phase_tester import ThreePhaseTester, ThreePhaseReport
from src.network.deployment_verifier import DeploymentVerifier, DeploymentVerificationReport


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

    def execute(self, hosts: List[str]) -> StepResult:
        """执行RDMA网络测试"""
        start_time = time.time()

        self.logger.info("开始RDMA网络测试...")

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
        hosts_info = self._collect_hosts_info(hosts)
        if not hosts_info:
            return StepResult(
                step_id=self.step_id,
                step_name=self.step_name,
                status=StepStatus.FAILED,
                message="无法收集RDMA设备信息",
                errors=["未找到任何RDMA设备"]
            )

        # 3. 获取测试配置
        test_config = self._get_test_config()

        # 4. 执行三轮测试
        self.logger.info("步骤3: 执行三轮带宽测试...")
        test_report = self.three_phase_tester.execute(
            hosts_info=hosts_info,
            test_config=test_config,
            max_workers=4,
            skip_round2_if_all_normal=True
        )

        duration = time.time() - start_time

        # 5. 生成报告
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

        return StepResult(
            step_id=self.step_id,
            step_name=self.step_name,
            status=status,
            message=message,
            duration=duration,
            details={
                "deployment_report": deployment_report.to_dict(),
                "test_report": test_report.to_dict(),
                "markdown_report": markdown_report
            },
            host_results={
                host: {
                    "devices": info.get("devices", []),
                    "status": "tested"
                }
                for host, info in zip(hosts, hosts_info)
            }
        )

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

    def _collect_hosts_info(self, hosts: List[str]) -> List[Dict]:
        """收集主机RDMA设备信息"""
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
                # 获取compute网络的设备
                if network_config.compute and network_config.compute.rdma_devices:
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

    def _get_test_config(self) -> Dict:
        """获取测试配置"""
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
        if network_config and network_config.compute:
            config["theoretical_bandwidth_gbps"] = network_config.compute.theoretical_bandwidth_gbps

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

        result = self.execute(hosts)

        output = {
            "success": result.status == StepStatus.SUCCESS,
            "message": result.message,
            "duration": result.duration,
            "test_report": result.details.get("test_report", {}),
            "deployment_report": result.details.get("deployment_report", {})
        }

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
    </style>
</head>
<body>
    <h1>RDMA网络测试报告</h1>
"""

        # 摘要
        summary = test_report_dict.get("summary", {})
        html += f"""
    <div class="summary">
        <h2>测试摘要</h2>
        <p>总主机数: {summary.get('total_hosts', 0)}</p>
        <p>总设备数: {summary.get('total_devices', 0)}</p>
        <p>正常设备: <span class="success">{summary.get('normal_devices', 0)}</span></p>
        <p>异常设备: <span class="failed">{summary.get('abnormal_devices', 0)}</span></p>
        <p>执行轮次: {summary.get('rounds_executed', 0)}</p>
    </div>
"""

        # 异常设备
        abnormal_list = summary.get('abnormal_device_list', [])
        if abnormal_list:
            html += """
    <h2>异常设备列表</h2>
    <ul>
"""
            for device in abnormal_list:
                html += f"        <li class='failed'>{device}</li>\n"
            html += "    </ul>\n"

        # 设备状态详情
        final_status = test_report_dict.get("final_status", {})
        if final_status:
            html += """
    <h2>设备状态详情</h2>
    <table>
        <tr><th>主机</th><th>设备</th><th>状态</th></tr>
"""
            for hostname, devices in sorted(final_status.items()):
                for device, status in sorted(devices.items()):
                    status_class = "success" if status == "normal" else \
                                  "failed" if status == "abnormal" else "warning"
                    html += f"        <tr><td>{hostname}</td><td>{device}</td><td class='{status_class}'>{status}</td></tr>\n"
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
