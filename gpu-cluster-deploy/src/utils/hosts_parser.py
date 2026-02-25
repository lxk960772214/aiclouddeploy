"""
hosts格式文件解析器
支持/etc/hosts格式解析，用于批量节点配置
"""

import re
import ipaddress
from typing import List, Dict, Tuple, Optional, Union
from pathlib import Path


class HostsParser:
    """hosts格式文件解析器"""

    def __init__(self, ip_validation: bool = True):
        """
        初始化hosts解析器

        Args:
            ip_validation: 是否验证IP地址格式
        """
        self.ip_validation = ip_validation

    def parse_file(self, filepath: Union[str, Path]) -> List[Dict[str, str]]:
        """
        解析hosts格式文件

        Args:
            filepath: 文件路径

        Returns:
            节点列表，每个节点包含 'ip' 和 'hostname' 字段
        """
        if isinstance(filepath, str):
            filepath = Path(filepath)

        if not filepath.exists():
            raise FileNotFoundError(f"hosts文件不存在: {filepath}")

        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()

        return self.parse_content(content)

    def parse_content(self, content: str) -> List[Dict[str, str]]:
        """
        解析hosts格式内容

        Args:
            content: hosts格式文本内容

        Returns:
            节点列表，每个节点包含 'ip' 和 'hostname' 字段
        """
        nodes = []
        lines = content.split('\n')

        for line_num, line in enumerate(lines, 1):
            line = line.strip()

            # 跳过空行和注释
            if not line or line.startswith('#'):
                continue

            # 移除行内注释
            if '#' in line:
                line = line.split('#')[0].strip()

            # 解析行内容
            parts = line.split()
            if len(parts) < 2:
                continue  # 跳过无效行

            ip_address = parts[0]
            hostnames = parts[1:]

            # 验证IP地址格式
            if self.ip_validation:
                if not self._validate_ip_address(ip_address):
                    print(f"警告: 行 {line_num} - 无效的IP地址格式: {ip_address}")
                    continue

            # 解析每个主机名
            for hostname in hostnames:
                # 检查主机名格式
                if not self._validate_hostname(hostname):
                    print(f"警告: 行 {line_num} - 无效的主机名格式: {hostname}")
                    continue

                # 检查是否有域名后缀
                if '.' in hostname:
                    short_hostname = hostname.split('.')[0]
                else:
                    short_hostname = hostname

                nodes.append({
                    'ip': ip_address,
                    'hostname': short_hostname,
                    'full_hostname': hostname,
                    'line': line_num
                })

        return nodes

    def parse_with_pattern(
        self,
        content: str,
        hostname_pattern: str = r'node(\d+)',
        ip_pattern: str = r'(\d+\.\d+\.\d+)\.(\d+)'
    ) -> List[Dict[str, str]]:
        """
        解析hosts内容并提取模式匹配的节点信息

        Args:
            content: hosts格式文本内容
            hostname_pattern: 主机名模式正则表达式，用于提取索引
            ip_pattern: IP地址模式正则表达式，用于提取网段和主机部分

        Returns:
            节点列表，每个节点包含 'ip', 'hostname', 'index', 'network' 字段
        """
        nodes = self.parse_content(content)
        enriched_nodes = []

        for node in nodes:
            # 提取主机名索引
            hostname = node['hostname']
            hostname_match = re.match(hostname_pattern, hostname)
            if hostname_match:
                index = int(hostname_match.group(1))
                node['index'] = index
            else:
                node['index'] = None

            # 提取IP地址网段
            ip_address = node['ip']
            ip_match = re.match(ip_pattern, ip_address)
            if ip_match:
                network_part = ip_match.group(1)
                host_part = ip_match.group(2)
                node['network'] = network_part
                node['host_part'] = host_part
            else:
                node['network'] = None
                node['host_part'] = None

            enriched_nodes.append(node)

        return enriched_nodes

    def generate_hosts_content(
        self,
        nodes: List[Dict[str, str]],
        header: str = "# 集群节点配置",
        sort_by_ip: bool = True
    ) -> str:
        """
        生成hosts格式内容

        Args:
            nodes: 节点列表，每个节点包含 'ip' 和 'hostname' 字段
            header: 文件头部注释
            sort_by_ip: 是否按IP地址排序

        Returns:
            hosts格式文本内容
        """
        if sort_by_ip:
            # 按IP地址排序
            try:
                nodes = sorted(nodes, key=lambda x: tuple(map(int, x['ip'].split('.'))))
            except (ValueError, AttributeError):
                pass

        lines = []
        if header:
            lines.append(header)
            lines.append("")

        # 按IP地址分组主机名
        ip_to_hostnames = {}
        for node in nodes:
            ip = node['ip']
            hostname = node.get('hostname', node.get('full_hostname', ''))
            if ip not in ip_to_hostnames:
                ip_to_hostnames[ip] = []
            ip_to_hostnames[ip].append(hostname)

        # 生成每行
        for ip, hostnames in ip_to_hostnames.items():
            if not hostnames:
                continue
            line = f"{ip}\t{' '.join(hostnames)}"
            lines.append(line)

        return '\n'.join(lines)

    def merge_with_individual_nodes(
        self,
        batch_nodes: List[Dict[str, str]],
        individual_nodes: List[Dict[str, str]],
        overwrite_individual: bool = True
    ) -> List[Dict[str, str]]:
        """
        合并批量节点和个别节点配置

        Args:
            batch_nodes: 批量节点列表
            individual_nodes: 个别节点列表
            overwrite_individual: 如果个别节点与批量节点冲突，是否覆盖批量节点

        Returns:
            合并后的节点列表
        """
        merged_nodes = []

        # 创建批量节点的查找字典
        batch_dict = {}
        for node in batch_nodes:
            hostname = node.get('hostname')
            if hostname:
                batch_dict[hostname] = node

        # 创建个别节点的查找字典
        individual_dict = {}
        for node in individual_nodes:
            hostname = node.get('hostname')
            if hostname:
                individual_dict[hostname] = node

        # 处理覆盖逻辑
        for hostname, node in batch_dict.items():
            if hostname in individual_dict:
                if overwrite_individual:
                    # 用个别节点覆盖批量节点
                    merged_nodes.append(individual_dict[hostname])
                else:
                    # 保留批量节点
                    merged_nodes.append(node)
            else:
                merged_nodes.append(node)

        # 添加不在批量节点中的个别节点
        for hostname, node in individual_dict.items():
            if hostname not in batch_dict:
                merged_nodes.append(node)

        return merged_nodes

    def _validate_ip_address(self, ip_address: str) -> bool:
        """
        验证IP地址格式

        Args:
            ip_address: IP地址字符串

        Returns:
            是否为有效的IP地址
        """
        try:
            ipaddress.ip_address(ip_address)
            return True
        except ValueError:
            return False

    def _validate_hostname(self, hostname: str) -> bool:
        """
        验证主机名格式

        Args:
            hostname: 主机名字符串

        Returns:
            是否为有效的主机名格式
        """
        # 基本验证：不能为空，不能包含非法字符
        if not hostname:
            return False

        # 检查长度
        if len(hostname) > 253:
            return False

        # 检查每个标签
        labels = hostname.split('.')
        for label in labels:
            if not label:
                return False
            if len(label) > 63:
                return False
            if not re.match(r'^[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?$', label):
                return False

        return True

    def find_node_by_ip(self, nodes: List[Dict[str, str]], ip: str) -> Optional[Dict[str, str]]:
        """
        根据IP地址查找节点

        Args:
            nodes: 节点列表
            ip: 要查找的IP地址

        Returns:
            匹配的节点或None
        """
        for node in nodes:
            if node.get('ip') == ip:
                return node
        return None

    def find_node_by_hostname(self, nodes: List[Dict[str, str]], hostname: str) -> Optional[Dict[str, str]]:
        """
        根据主机名查找节点

        Args:
            nodes: 节点列表
            hostname: 要查找的主机名

        Returns:
            匹配的节点或None
        """
        for node in nodes:
            if node.get('hostname') == hostname or node.get('full_hostname') == hostname:
                return node
        return None


# 便捷函数
def parse_hosts_file(filepath: Union[str, Path]) -> List[Dict[str, str]]:
    """解析hosts文件的便捷函数"""
    parser = HostsParser()
    return parser.parse_file(filepath)


def parse_hosts_content(content: str) -> List[Dict[str, str]]:
    """解析hosts内容的便捷函数"""
    parser = HostsParser()
    return parser.parse_content(content)


def generate_hosts_file(
    nodes: List[Dict[str, str]],
    output_path: Union[str, Path],
    header: str = "# 集群节点配置"
) -> None:
    """生成hosts文件的便捷函数"""
    parser = HostsParser()
    content = parser.generate_hosts_content(nodes, header)

    if isinstance(output_path, str):
        output_path = Path(output_path)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(content)


# 测试函数
def test_parser():
    """测试hosts解析器"""
    test_content = """# 测试集群节点配置
10.0.1.1 node01 node01.cluster.local
10.0.1.2 node02
10.0.1.3 node03 node03.cluster.local

# 无效行将被忽略
invalid-ip node04
10.0.1.4
"""

    print("测试hosts解析器...")
    parser = HostsParser()

    # 测试解析
    nodes = parser.parse_content(test_content)
    print(f"解析到的节点数: {len(nodes)}")

    for node in nodes:
        print(f"  IP: {node['ip']}, Hostname: {node['hostname']}, Full: {node.get('full_hostname')}")

    # 测试生成
    generated = parser.generate_hosts_content(nodes, "# 测试生成的配置")
    print("\n生成的hosts内容:")
    print(generated)

    # 测试合并
    batch_nodes = [
        {'ip': '10.0.1.1', 'hostname': 'node01'},
        {'ip': '10.0.1.2', 'hostname': 'node02'},
    ]

    individual_nodes = [
        {'ip': '10.0.1.2', 'hostname': 'node02-updated'},  # 更新node02
        {'ip': '10.0.1.3', 'hostname': 'node03'},  # 新增node03
    ]

    merged = parser.merge_with_individual_nodes(batch_nodes, individual_nodes)
    print("\n合并后的节点:")
    for node in merged:
        print(f"  IP: {node['ip']}, Hostname: {node['hostname']}")


if __name__ == "__main__":
    test_parser()