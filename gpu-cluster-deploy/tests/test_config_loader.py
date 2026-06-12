"""
配置加载器单元测试
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

# 添加src到路径
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from config_loader import (
    ConfigLoader, JumphostConfig, NodeConfig, StorageConfig,
    KernelConfig, CudaConfig, NvidiaDriverConfig
)


class TestJumphostConfig(unittest.TestCase):
    """跳转服务器配置测试"""

    def test_key_auth_config(self):
        """测试密钥认证配置"""
        config = JumphostConfig(
            host="192.168.1.1",
            port=22,
            auth_type="key",
            username="ubuntu",
            private_key="~/.ssh/id_rsa"
        )
        self.assertEqual(config.host, "192.168.1.1")
        self.assertEqual(config.auth_type, "key")

    def test_password_auth_config(self):
        """测试密码认证配置"""
        config = JumphostConfig(
            host="192.168.1.1",
            port=2222,
            auth_type="password",
            username="admin",
            password="secret"
        )
        self.assertEqual(config.port, 2222)
        self.assertEqual(config.auth_type, "password")

    def test_invalid_auth_type(self):
        """测试无效认证类型"""
        with self.assertRaises(ValueError):
            JumphostConfig(
                host="192.168.1.1",
                auth_type="invalid"
            )

    def test_missing_host(self):
        """测试缺少host"""
        with self.assertRaises(ValueError):
            JumphostConfig(host="")


class TestStorageConfig(unittest.TestCase):
    """存储配置测试"""

    def test_single_disk_config(self):
        """测试单盘配置"""
        config = StorageConfig(
            type="single",
            device="/dev/nvme0n1",
            mount_point="/ssd"
        )
        self.assertEqual(config.type, "single")
        self.assertEqual(config.device, "/dev/nvme0n1")

    def test_raid_config(self):
        """测试RAID配置"""
        config = StorageConfig(
            type="raid10",
            devices=["/dev/nvme0n1", "/dev/nvme1n1", "/dev/nvme2n1", "/dev/nvme3n1"],
            mount_point="/ssd"
        )
        self.assertEqual(config.type, "raid10")
        self.assertEqual(len(config.devices), 4)


class TestKernelConfig(unittest.TestCase):
    """内核配置测试"""

    def test_keep_mode(self):
        """测试保持默认模式"""
        config = KernelConfig(mode="keep")
        self.assertEqual(config.mode, "keep")
        self.assertTrue(config.keep.get("lock_version", True))

    def test_specify_mode(self):
        """测试指定版本模式"""
        config = KernelConfig(
            mode="specify",
            specify={"version": "5.15.0-91-generic"}
        )
        self.assertEqual(config.mode, "specify")
        self.assertEqual(config.specify.get("version"), "5.15.0-91-generic")


class TestConfigLoader(unittest.TestCase):
    """配置加载器测试"""

    def setUp(self):
        """创建临时配置目录"""
        self.temp_dir = tempfile.mkdtemp()
        self.config_dir = Path(self.temp_dir) / "config"
        self.config_dir.mkdir()

    def tearDown(self):
        """清理临时目录"""
        import shutil
        shutil.rmtree(self.temp_dir)

    def test_load_cluster_config(self):
        """测试加载集群配置"""
        # 创建测试配置文件
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

        loader = ConfigLoader(str(self.config_dir))
        cluster = loader.load_cluster_config()

        self.assertEqual(cluster.name, "test-cluster")
        self.assertEqual(len(cluster.nodes), 1)
        self.assertEqual(cluster.nodes[0].hostname, "node-01")

    def test_load_versions_config(self):
        """测试加载版本配置"""
        config_content = """
cuda:
  version: "12.8"

nvidia_driver:
  version: "590.48.01"

kernel:
  mode: "keep"
"""
        config_file = self.config_dir / "versions.yaml"
        config_file.write_text(config_content)

        loader = ConfigLoader(str(self.config_dir))
        versions = loader.load_versions_config()

        self.assertEqual(versions.cuda.version, "12.8")
        self.assertEqual(versions.nvidia_driver.version, "590.48.01")
        self.assertEqual(versions.kernel.mode, "keep")


if __name__ == "__main__":
    unittest.main()
