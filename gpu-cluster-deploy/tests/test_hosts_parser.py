"""
HostsParser单元测试
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

# 添加src到路径
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from utils.hosts_parser import HostsParser, parse_hosts_content, generate_hosts_file


class TestHostsParser(unittest.TestCase):
    """HostsParser测试类"""

    def setUp(self):
        """初始化解析器"""
        self.parser = HostsParser()

    def test_parse_simple_content(self):
        """测试解析简单hosts内容"""
        content = """
# 测试配置
10.0.1.1 node01
10.0.1.2 node02
10.0.1.3 node03
"""
        nodes = self.parser.parse_content(content)
        self.assertEqual(len(nodes), 3)
        self.assertEqual(nodes[0]['ip'], '10.0.1.1')
        self.assertEqual(nodes[0]['hostname'], 'node01')
        self.assertEqual(nodes[1]['ip'], '10.0.1.2')
        self.assertEqual(nodes[2]['ip'], '10.0.1.3')

    def test_parse_with_fqdn(self):
        """测试解析带域名的主机名"""
        content = "10.0.1.1 node01.cluster.local node01"
        nodes = self.parser.parse_content(content)
        self.assertEqual(len(nodes), 2)  # 两个主机名
        self.assertEqual(nodes[0]['hostname'], 'node01')
        self.assertEqual(nodes[0]['full_hostname'], 'node01.cluster.local')

    def test_parse_with_comments(self):
        """测试解析带注释的内容"""
        content = """
# 这是注释
10.0.1.1 node01  # 行内注释
# 另一个注释
10.0.1.2 node02
"""
        nodes = self.parser.parse_content(content)
        self.assertEqual(len(nodes), 2)

    def test_parse_empty_content(self):
        """测试解析空内容"""
        nodes = self.parser.parse_content("")
        self.assertEqual(len(nodes), 0)

    def test_parse_file(self):
        """测试解析文件"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.hosts', delete=False) as f:
            f.write("10.0.1.1 node01\n")
            f.write("10.0.1.2 node02\n")
            temp_path = f.name

        try:
            nodes = self.parser.parse_file(temp_path)
            self.assertEqual(len(nodes), 2)
            self.assertEqual(nodes[0]['hostname'], 'node01')
        finally:
            os.unlink(temp_path)

    def test_parse_nonexistent_file(self):
        """测试解析不存在的文件"""
        with self.assertRaises(FileNotFoundError):
            self.parser.parse_file("/nonexistent/path/hosts")

    def test_ip_validation(self):
        """测试IP地址验证"""
        content = """
10.0.1.1 node01
invalid-ip node02
10.0.1.3 node03
"""
        nodes = self.parser.parse_content(content)
        # 无效IP应该被跳过
        self.assertEqual(len(nodes), 2)

    def test_hostname_validation(self):
        """测试主机名验证"""
        content = """
10.0.1.1 valid-host
10.0.1.2 -invalid-host
10.0.1.3 another-valid
"""
        nodes = self.parser.parse_content(content)
        # 无效主机名应该被跳过
        self.assertEqual(len(nodes), 2)

    def test_generate_hosts_content(self):
        """测试生成hosts内容"""
        nodes = [
            {'ip': '10.0.1.1', 'hostname': 'node01'},
            {'ip': '10.0.1.2', 'hostname': 'node02'},
        ]
        content = self.parser.generate_hosts_content(nodes)
        self.assertIn('10.0.1.1', content)
        self.assertIn('node01', content)
        self.assertIn('node02', content)

    def test_generate_with_sort(self):
        """测试生成时按IP排序"""
        nodes = [
            {'ip': '10.0.1.3', 'hostname': 'node03'},
            {'ip': '10.0.1.1', 'hostname': 'node01'},
            {'ip': '10.0.1.2', 'hostname': 'node02'},
        ]
        content = self.parser.generate_hosts_content(nodes, sort_by_ip=True)
        lines = [l for l in content.split('\n') if l and not l.startswith('#')]
        # 验证排序（第一行应该是最小的IP）
        self.assertTrue(lines[0].startswith('10.0.1.1'))

    def test_merge_with_individual_nodes(self):
        """测试合并批量节点和个别节点"""
        batch_nodes = [
            {'ip': '10.0.1.1', 'hostname': 'node01'},
            {'ip': '10.0.1.2', 'hostname': 'node02'},
        ]
        individual_nodes = [
            {'ip': '10.0.1.20', 'hostname': 'node02'},  # 同名覆盖（更新IP）
            {'ip': '10.0.1.3', 'hostname': 'node03'},  # 新增
        ]

        # 测试覆盖模式
        merged = self.parser.merge_with_individual_nodes(
            batch_nodes, individual_nodes, overwrite_individual=True
        )
        self.assertEqual(len(merged), 3)
        # node02应该被覆盖（使用个别节点的配置，IP更新为10.0.1.20）
        node02 = next(n for n in merged if n['hostname'] == 'node02')
        self.assertIsNotNone(node02)
        self.assertEqual(node02['ip'], '10.0.1.20')

    def test_merge_without_overwrite(self):
        """测试合并不覆盖模式"""
        batch_nodes = [
            {'ip': '10.0.1.1', 'hostname': 'node01'},
            {'ip': '10.0.1.2', 'hostname': 'node02'},
        ]
        individual_nodes = [
            {'ip': '10.0.1.20', 'hostname': 'node02'},  # 同名但不覆盖
        ]

        merged = self.parser.merge_with_individual_nodes(
            batch_nodes, individual_nodes, overwrite_individual=False
        )
        # 应该保留批量节点（不覆盖）
        node02 = next(n for n in merged if n['hostname'] == 'node02')
        self.assertIsNotNone(node02)
        self.assertEqual(node02['ip'], '10.0.1.2')  # 保持原来的IP

    def test_find_node_by_ip(self):
        """测试根据IP查找节点"""
        nodes = [
            {'ip': '10.0.1.1', 'hostname': 'node01'},
            {'ip': '10.0.1.2', 'hostname': 'node02'},
        ]
        node = self.parser.find_node_by_ip(nodes, '10.0.1.1')
        self.assertEqual(node['hostname'], 'node01')

        # 不存在的IP
        node = self.parser.find_node_by_ip(nodes, '10.0.1.99')
        self.assertIsNone(node)

    def test_find_node_by_hostname(self):
        """测试根据主机名查找节点"""
        nodes = [
            {'ip': '10.0.1.1', 'hostname': 'node01'},
            {'ip': '10.0.1.2', 'hostname': 'node02'},
        ]
        node = self.parser.find_node_by_hostname(nodes, 'node01')
        self.assertEqual(node['ip'], '10.0.1.1')

        # 不存在的主机名
        node = self.parser.find_node_by_hostname(nodes, 'node99')
        self.assertIsNone(node)

    def test_parse_with_pattern(self):
        """测试带模式匹配的解析"""
        content = """
10.0.1.1 node01
10.0.1.2 node02
10.0.1.3 server01
"""
        nodes = self.parser.parse_with_pattern(content)
        # node01和node02应该有索引
        node01 = next(n for n in nodes if n['hostname'] == 'node01')
        self.assertEqual(node01.get('index'), 1)
        node02 = next(n for n in nodes if n['hostname'] == 'node02')
        self.assertEqual(node02.get('index'), 2)


class TestConvenienceFunctions(unittest.TestCase):
    """便捷函数测试"""

    def test_parse_hosts_content(self):
        """测试parse_hosts_content便捷函数"""
        content = "10.0.1.1 node01\n10.0.1.2 node02"
        nodes = parse_hosts_content(content)
        self.assertEqual(len(nodes), 2)

    def test_generate_hosts_file(self):
        """测试generate_hosts_file便捷函数"""
        nodes = [
            {'ip': '10.0.1.1', 'hostname': 'node01'},
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "test.hosts"
            generate_hosts_file(nodes, output_path)
            self.assertTrue(output_path.exists())
            content = output_path.read_text()
            self.assertIn('node01', content)


if __name__ == "__main__":
    unittest.main()
