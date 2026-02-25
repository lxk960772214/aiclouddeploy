"""
批量节点配置单元测试
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

# 添加src到路径
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from config_loader import (
    ConfigLoader, NodeBatchConfig, StorageConfig,
    NodeConfig, NodeAuthConfig, ClusterConfig
)


class TestNodeBatchConfig(unittest.TestCase):
    """NodeBatchConfig测试类"""

    def test_default_values(self):
        """测试默认值"""
        config = NodeBatchConfig()
        self.assertFalse(config.enabled)
        self.assertIsNone(config.hosts_file)
        self.assertIsNone(config.hosts_content)
        self.assertEqual(config.base_hostname_prefix, "node")
        self.assertEqual(config.base_ip_prefix, "10.0.0")
        self.assertEqual(config.count, 0)
        self.assertEqual(config.start_index, 1)
        self.assertEqual(config.roles, [])
        self.assertIsNone(config.storage_template)
        self.assertIsNone(config.auth_template)

    def test_with_storage_template(self):
        """测试带存储模板"""
        storage = StorageConfig(
            type="single",
            device="/dev/nvme0n1",
            mount_point="/ssd"
        )
        config = NodeBatchConfig(
            enabled=True,
            count=5,
            storage_template=storage
        )
        self.assertTrue(config.enabled)
        self.assertEqual(config.count, 5)
        self.assertIsNotNone(config.storage_template)
        self.assertEqual(config.storage_template.device, "/dev/nvme0n1")

    def test_with_auth_template(self):
        """测试带认证模板"""
        auth = NodeAuthConfig(
            auth_type="key",
            username="ubuntu",
            private_key="~/.ssh/id_rsa"
        )
        config = NodeBatchConfig(
            enabled=True,
            auth_template=auth
        )
        self.assertIsNotNone(config.auth_template)
        self.assertEqual(config.auth_template.username, "ubuntu")


class TestStorageConfigDefault(unittest.TestCase):
    """StorageConfig默认值测试"""

    def test_format_disk_default_is_false(self):
        """测试format_disk默认值为False"""
        config = StorageConfig()
        # 默认值应该是False，防止数据丢失
        self.assertFalse(config.format_disk)

    def test_format_disk_explicit_true(self):
        """测试显式设置format_disk为True"""
        config = StorageConfig(format_disk=True)
        self.assertTrue(config.format_disk)

    def test_format_disk_explicit_false(self):
        """测试显式设置format_disk为False"""
        config = StorageConfig(format_disk=False)
        self.assertFalse(config.format_disk)


class TestConfigLoaderBatchNodes(unittest.TestCase):
    """ConfigLoader批量节点测试"""

    def setUp(self):
        """创建临时配置目录"""
        self.temp_dir = tempfile.mkdtemp()
        self.config_dir = Path(self.temp_dir) / "config"
        self.config_dir.mkdir()

    def tearDown(self):
        """清理临时目录"""
        import shutil
        shutil.rmtree(self.temp_dir)

    def _create_versions_config(self):
        """创建版本配置文件"""
        versions_content = """
cuda:
  version: "12.8"
nvidia_driver:
  version: "590.48.01"
kernel:
  mode: "keep"
"""
        versions_file = self.config_dir / "versions.yaml"
        versions_file.write_text(versions_content)

    def test_load_batch_config_disabled(self):
        """测试批量配置禁用"""
        config_content = """
cluster:
  name: test-cluster

jumphost:
  host: "192.168.1.1"
  port: 22
  auth:
    type: "key"
    username: "ubuntu"
    private_key: "~/.ssh/id_rsa"

node_batch:
  enabled: false

nodes:
  - hostname: "node-01"
    ip: "10.0.0.1"
    roles:
      - gpu_node
"""
        config_file = self.config_dir / "cluster.yaml"
        config_file.write_text(config_content)
        self._create_versions_config()

        loader = ConfigLoader(str(self.config_dir))
        cluster = loader.load_cluster_config()

        self.assertFalse(cluster.node_batch.enabled)
        self.assertEqual(len(cluster.nodes), 1)
        self.assertEqual(cluster.nodes[0].hostname, "node-01")

    def test_load_batch_config_with_hosts_content(self):
        """测试使用hosts_content批量配置"""
        config_content = """
cluster:
  name: test-cluster

jumphost:
  host: "192.168.1.1"
  port: 22
  auth:
    type: "key"
    username: "ubuntu"
    private_key: "~/.ssh/id_rsa"

node_batch:
  enabled: true
  hosts_content: |
    10.0.1.1 node01
    10.0.1.2 node02
    10.0.1.3 node03
  roles:
    - gpu_node
  storage_template:
    type: "single"
    device: "/dev/nvme0n1"
    mount_point: "/ssd"
"""
        config_file = self.config_dir / "cluster.yaml"
        config_file.write_text(config_content)
        self._create_versions_config()

        loader = ConfigLoader(str(self.config_dir))
        cluster = loader.load_cluster_config()

        self.assertTrue(cluster.node_batch.enabled)
        self.assertEqual(len(cluster.nodes), 3)
        self.assertEqual(cluster.nodes[0].hostname, "node01")
        self.assertEqual(cluster.nodes[0].ip, "10.0.1.1")
        self.assertIn("gpu_node", cluster.nodes[0].roles)
        # 验证存储模板应用
        self.assertIsNotNone(cluster.nodes[0].storage)
        self.assertEqual(cluster.nodes[0].storage.device, "/dev/nvme0n1")

    def test_load_batch_config_with_template(self):
        """测试使用模板生成批量节点"""
        config_content = """
cluster:
  name: test-cluster

jumphost:
  host: "192.168.1.1"
  port: 22
  auth:
    type: "key"
    username: "ubuntu"
    private_key: "~/.ssh/id_rsa"

node_batch:
  enabled: true
  base_hostname_prefix: "gpu-node-"
  base_ip_prefix: "10.0.0"
  count: 3
  start_index: 1
  roles:
    - gpu_node
  storage_template:
    type: "single"
    device: "/dev/nvme0n1"
    mount_point: "/ssd"
"""
        config_file = self.config_dir / "cluster.yaml"
        config_file.write_text(config_content)
        self._create_versions_config()

        loader = ConfigLoader(str(self.config_dir))
        cluster = loader.load_cluster_config()

        self.assertEqual(len(cluster.nodes), 3)
        # 验证生成的节点名称和IP
        self.assertEqual(cluster.nodes[0].hostname, "gpu-node-01")
        self.assertEqual(cluster.nodes[0].ip, "10.0.0.1")
        self.assertEqual(cluster.nodes[1].hostname, "gpu-node-02")
        self.assertEqual(cluster.nodes[1].ip, "10.0.0.2")
        self.assertEqual(cluster.nodes[2].hostname, "gpu-node-03")
        self.assertEqual(cluster.nodes[2].ip, "10.0.0.3")

    def test_load_batch_config_with_overrides(self):
        """测试批量配置与覆盖"""
        config_content = """
cluster:
  name: test-cluster

jumphost:
  host: "192.168.1.1"
  port: 22
  auth:
    type: "key"
    username: "ubuntu"
    private_key: "~/.ssh/id_rsa"

node_batch:
  enabled: true
  hosts_content: |
    10.0.1.1 node01
    10.0.1.2 node02
    10.0.1.3 node03
  roles:
    - gpu_node
  storage_template:
    type: "single"
    device: "/dev/nvme0n1"
    mount_point: "/ssd"

nodes_override:
  - hostname: "node02"
    storage:
      device: "/dev/nvme1n1"
      format_disk: false
  - hostname: "node03"
    roles:
      - gpu_node
      - nfs_server
"""
        config_file = self.config_dir / "cluster.yaml"
        config_file.write_text(config_content)
        self._create_versions_config()

        loader = ConfigLoader(str(self.config_dir))
        cluster = loader.load_cluster_config()

        # 验证node02的存储被覆盖
        node02 = next(n for n in cluster.nodes if n.hostname == "node02")
        self.assertEqual(node02.storage.device, "/dev/nvme1n1")
        self.assertFalse(node02.storage.format_disk)

        # 验证node03的角色被覆盖
        node03 = next(n for n in cluster.nodes if n.hostname == "node03")
        self.assertIn("nfs_server", node03.roles)

    def test_load_batch_config_merge_individual_nodes(self):
        """测试批量节点与独立节点合并"""
        config_content = """
cluster:
  name: test-cluster

jumphost:
  host: "192.168.1.1"
  port: 22
  auth:
    type: "key"
    username: "ubuntu"
    private_key: "~/.ssh/id_rsa"

node_batch:
  enabled: true
  hosts_content: |
    10.0.1.1 node01
    10.0.1.2 node02
  roles:
    - gpu_node

nodes:
  - hostname: "master"
    ip: "10.0.1.100"
    roles:
      - nfs_server
"""
        config_file = self.config_dir / "cluster.yaml"
        config_file.write_text(config_content)
        self._create_versions_config()

        loader = ConfigLoader(str(self.config_dir))
        cluster = loader.load_cluster_config()

        # 应该有3个节点：2个批量节点 + 1个独立节点
        self.assertEqual(len(cluster.nodes), 3)
        hostnames = [n.hostname for n in cluster.nodes]
        self.assertIn("node01", hostnames)
        self.assertIn("node02", hostnames)
        self.assertIn("master", hostnames)

    def test_format_disk_default_in_config(self):
        """测试配置中format_disk的默认值"""
        config_content = """
cluster:
  name: test-cluster

jumphost:
  host: "192.168.1.1"
  port: 22
  auth:
    type: "key"
    username: "ubuntu"
    private_key: "~/.ssh/id_rsa"

nodes:
  - hostname: "node-01"
    ip: "10.0.0.1"
    roles:
      - gpu_node
    storage:
      type: "single"
      device: "/dev/nvme0n1"
      mount_point: "/ssd"
"""
        config_file = self.config_dir / "cluster.yaml"
        config_file.write_text(config_content)
        self._create_versions_config()

        loader = ConfigLoader(str(self.config_dir))
        cluster = loader.load_cluster_config()

        # 未显式指定format_disk时，默认应该是False
        self.assertFalse(cluster.nodes[0].storage.format_disk)

    def test_format_disk_explicit_in_config(self):
        """测试配置中显式指定format_disk"""
        config_content = """
cluster:
  name: test-cluster

jumphost:
  host: "192.168.1.1"
  port: 22
  auth:
    type: "key"
    username: "ubuntu"
    private_key: "~/.ssh/id_rsa"

node_batch:
  enabled: true
  hosts_content: |
    10.0.1.1 node01
  roles:
    - gpu_node
  storage_template:
    type: "single"
    device: "/dev/nvme0n1"
    mount_point: "/ssd"
    format_disk: true
"""
        config_file = self.config_dir / "cluster.yaml"
        config_file.write_text(config_content)
        self._create_versions_config()

        loader = ConfigLoader(str(self.config_dir))
        cluster = loader.load_cluster_config()

        # 显式指定format_disk为true
        self.assertTrue(cluster.nodes[0].storage.format_disk)


class TestJumphostNodeAuth(unittest.TestCase):
    """跳转服务器节点认证测试"""

    def setUp(self):
        """创建临时配置目录"""
        self.temp_dir = tempfile.mkdtemp()
        self.config_dir = Path(self.temp_dir) / "config"
        self.config_dir.mkdir()

    def tearDown(self):
        """清理临时目录"""
        import shutil
        shutil.rmtree(self.temp_dir)

    def test_jumphost_with_node_auth(self):
        """测试跳转服务器带节点认证配置"""
        config_content = """
cluster:
  name: test-cluster

jumphost:
  host: "192.168.1.1"
  port: 22
  auth:
    type: "key"
    username: "ubuntu"
    private_key: "~/.ssh/id_rsa"
    node_auth:
      type: "password"
      username: "admin"
      password: "secret"

nodes:
  - hostname: "node-01"
    ip: "10.0.0.1"
"""
        versions_content = """
cuda:
  version: "12.8"
kernel:
  mode: "keep"
"""
        config_file = self.config_dir / "cluster.yaml"
        config_file.write_text(config_content)
        versions_file = self.config_dir / "versions.yaml"
        versions_file.write_text(versions_content)

        loader = ConfigLoader(str(self.config_dir))
        cluster = loader.load_cluster_config()

        self.assertIsNotNone(cluster.jumphost.node_auth)
        self.assertEqual(cluster.jumphost.node_auth.auth_type, "password")
        self.assertEqual(cluster.jumphost.node_auth.username, "admin")


if __name__ == "__main__":
    unittest.main()
