"""
网络测试CLI - 独立的网络测试命令行接口
"""

import argparse
import json
import sys
import logging
from typing import Optional, List

from src.config_loader import ConfigLoader
from src.ssh_manager import SSHManager
from src.steps.step_0c_network_rdma_test import NetworkRDMATest


logger = logging.getLogger(__name__)


def setup_logging(verbose: bool = False):
    """配置日志"""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )


def create_parser() -> argparse.ArgumentParser:
    """创建命令行参数解析器"""
    parser = argparse.ArgumentParser(
        description='RDMA网络测试工具 - 执行独立的网络带宽测试',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 测试所有主机的RDMA网络
  python -m src.cli.network_test_cli --config config/cluster.yaml

  # 测试指定主机
  python -m src.cli.network_test_cli --config config/cluster.yaml --hosts node01,node02

  # 指定网络类型和输出格式
  python -m src.cli.network_test_cli --config config/cluster.yaml --network compute --format json

  # 生成HTML报告
  python -m src.cli.network_test_cli --config config/cluster.yaml --format html --output report.html
"""
    )

    # 必需参数
    parser.add_argument(
        '--config', '-c',
        required=True,
        help='集群配置文件路径 (YAML格式)'
    )

    # 主机选择
    parser.add_argument(
        '--hosts',
        help='指定测试的主机列表，逗号分隔 (默认: 所有主机)'
    )

    # 测试配置
    parser.add_argument(
        '--network', '-n',
        choices=['compute', 'storage', 'all'],
        default='compute',
        help='测试的网络类型 (默认: compute)'
    )

    parser.add_argument(
        '--rounds',
        type=int,
        choices=[1, 2, 3],
        default=3,
        help='测试轮次 (默认: 3)'
    )

    parser.add_argument(
        '--skip-deployment-check',
        action='store_true',
        help='跳过部署验证'
    )

    # 输出配置
    parser.add_argument(
        '--format', '-f',
        choices=['text', 'json', 'html'],
        default='text',
        help='输出格式 (默认: text)'
    )

    parser.add_argument(
        '--output', '-o',
        help='输出文件路径 (默认: 标准输出)'
    )

    # 调试选项
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='详细输出模式'
    )

    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='模拟运行，不执行实际测试'
    )

    return parser


def load_config(config_path: str):
    """加载配置文件"""
    loader = ConfigLoader()
    cluster_config = loader.load_cluster_config(config_path)
    return cluster_config, loader


def create_ssh_manager(cluster_config) -> SSHManager:
    """创建SSH管理器"""
    jumphost_config = None
    if cluster_config.jumphost:
        jumphost_config = {
            'host': cluster_config.jumphost.host,
            'port': cluster_config.jumphost.port,
            'username': cluster_config.jumphost.username,
            'password': cluster_config.jumphost.password,
            'private_key': cluster_config.jumphost.private_key
        }

    return SSHManager(jumphost_config)


def run_test(args) -> dict:
    """执行测试"""
    # 加载配置
    cluster_config, loader = load_config(args.config)

    # 创建SSH管理器
    ssh_manager = create_ssh_manager(cluster_config)

    # 连接跳转服务器
    if ssh_manager.jumphost_config:
        if not ssh_manager.connect_jumphost():
            return {
                'success': False,
                'error': '无法连接跳转服务器'
            }

    # 确定测试主机
    if args.hosts:
        host_list = [h.strip() for h in args.hosts.split(',')]
    else:
        host_list = [node.hostname for node in cluster_config.nodes]

    # 创建测试步骤
    test_step = NetworkRDMATest(
        config=cluster_config,
        ssh_manager=ssh_manager,
        batch_executor=None,
        logger=logger
    )

    # 如果是模拟运行
    if args.dry_run:
        return {
            'success': True,
            'message': '模拟运行完成',
            'hosts': host_list,
            'network': args.network,
            'format': args.format
        }

    # 执行测试
    result = test_step.execute_test_only(
        hosts=host_list,
        network_type=args.network,
        output_format=args.format
    )

    return result


def format_output(result: dict, output_format: str) -> str:
    """格式化输出"""
    if output_format == 'json':
        return json.dumps(result, indent=2, ensure_ascii=False)

    elif output_format == 'html':
        return result.get('html_report', '<html><body>No HTML report generated</body></html>')

    else:  # text
        lines = []

        # 标题
        lines.append("=" * 70)
        lines.append("RDMA网络测试报告")
        lines.append("=" * 70)
        lines.append("")

        # 摘要
        test_report = result.get('test_report', {})
        summary = test_report.get('summary', {})

        lines.append("## 测试摘要")
        lines.append(f"  总主机数: {summary.get('total_hosts', 0)}")
        lines.append(f"  总设备数: {summary.get('total_devices', 0)}")
        lines.append(f"  正常设备: {summary.get('normal_devices', 0)}")
        lines.append(f"  疑似设备: {summary.get('suspected_devices', 0)}")
        lines.append(f"  异常设备: {summary.get('abnormal_devices', 0)}")
        lines.append(f"  执行轮次: {summary.get('rounds_executed', 0)}")
        lines.append("")

        # 结果状态
        if result.get('success'):
            lines.append("测试结果: ✓ 通过")
        else:
            lines.append("测试结果: ✗ 失败")
        lines.append("")

        # 异常设备
        abnormal_list = summary.get('abnormal_device_list', [])
        if abnormal_list:
            lines.append("## 异常设备列表 (确定有问题)")
            for device in abnormal_list:
                lines.append(f"  ✗ {device}")
            lines.append("")

        # 疑似设备
        suspected_list = summary.get('suspected_device_list', [])
        if suspected_list:
            lines.append("## 疑似设备列表 (需要关注)")
            for device in suspected_list:
                lines.append(f"  ? {device}")
            lines.append("")

        # 收集错误详情
        error_details = {}  # {(host, device): [error_messages]}
        for phase_key in ['round1', 'round2', 'round3']:
            phase_result = test_report.get(phase_key, {})
            if not phase_result:
                continue

            phase_name = {
                'round1': '第一轮',
                'round2': '第二轮',
                'round3': '第三轮'
            }.get(phase_key, phase_key)

            for item in phase_result.get('results', []):
                test_result = item.get('result', {})
                pair = item.get('pair', {})

                if not test_result.get('success', False):
                    server_host = pair.get('server_host', '')
                    client_host = pair.get('client_host', '')
                    server_device = pair.get('server_device', '')
                    client_device = pair.get('client_device', '')
                    error_msg = test_result.get('error_message', '未知错误')
                    bandwidth = test_result.get('bandwidth_gbps', 0)
                    bandwidth_percent = test_result.get('bandwidth_percent', 0)

                    # 构建错误信息
                    if bandwidth > 0:
                        detail = f"带宽 {bandwidth:.1f}Gbps ({bandwidth_percent:.0f}%)"
                    else:
                        detail = error_msg if error_msg else "测试失败"

                    # 记录服务器端设备错误
                    key_s = (server_host, server_device)
                    if key_s not in error_details:
                        error_details[key_s] = []
                    error_details[key_s].append(f"[{phase_name}] 与 {client_host}:{client_device} 测试 - {detail}")

                    # 记录客户端设备错误
                    key_c = (client_host, client_device)
                    if key_c not in error_details:
                        error_details[key_c] = []
                    error_details[key_c].append(f"[{phase_name}] 与 {server_host}:{server_device} 测试 - {detail}")

        # 错误详情
        if error_details:
            lines.append("## 错误详情")
            lines.append(f"{'主机':<15} {'设备':<12} {'错误信息'}")
            lines.append("-" * 90)
            for (host, device), errors in sorted(error_details.items()):
                # 显示第一条错误，如果有多条则显示数量
                first_error = errors[0] if len(errors[0]) <= 80 else errors[0][:77] + "..."
                lines.append(f"{host:<15} {device:<12} {first_error}")
                if len(errors) > 1:
                    for err in errors[1:3]:  # 最多显示3条
                        err_short = err if len(err) <= 80 else err[:77] + "..."
                        lines.append(f"{'':<15} {'':<12}   {err_short}")
                    if len(errors) > 3:
                        lines.append(f"{'':<15} {'':<12}   ... 还有 {len(errors)-3} 条错误")
            lines.append("")

        # 设备状态详情
        final_status = test_report.get('final_status', {})
        if final_status:
            lines.append("## 设备状态详情")
            lines.append(f"{'主机':<15} {'设备':<12} {'状态':<10}")
            lines.append("-" * 45)

            for hostname, devices in sorted(final_status.items()):
                for device, status in sorted(devices.items()):
                    status_str = "✓ 正常" if status == "normal" else \
                                "✗ 异常" if status == "abnormal" else \
                                "? 疑似" if status == "suspected" else \
                                "- 未知"
                    lines.append(f"{hostname:<15} {device:<12} {status_str:<10}")
            lines.append("")

        return "\n".join(lines)


def write_output(content: str, output_path: Optional[str]):
    """写入输出"""
    if output_path:
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"报告已保存到: {output_path}")
    else:
        print(content)


def main():
    """主函数"""
    parser = create_parser()
    args = parser.parse_args()

    # 配置日志
    setup_logging(args.verbose)

    try:
        # 执行测试
        result = run_test(args)

        # 格式化输出
        output = format_output(result, args.format)

        # 写入输出
        write_output(output, args.output)

        # 设置退出码
        sys.exit(0 if result.get('success', False) else 1)

    except FileNotFoundError as e:
        print(f"错误: 配置文件不存在 - {e}", file=sys.stderr)
        sys.exit(2)

    except Exception as e:
        print(f"错误: {e}", file=sys.stderr)
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
