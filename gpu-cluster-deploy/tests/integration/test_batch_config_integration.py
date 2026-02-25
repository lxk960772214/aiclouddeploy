#!/usr/bin/env python3
"""
批量配置集成测试
测试hosts格式解析、批量节点生成和配置合并的端到端流程
"""

import pytest
import tempfile
import os
from pathlib import Path
import sys

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.config_loader import (
    ConfigLoader,
    ClusterConfig,
    NodeBatchConfig,
    StorageConfig,
    NodeAuthConfig,
)
from src.utils.hosts_parser import HostsParser


class TestBatchConfigIntegration:
    """批量配置集成测试"""

    def test_hosts_parser_integration(self):
        """测试HostsParser完整流程"""
        hosts_content = """
# GPU Cluster Nodes
192.168.1.1 node01
192.168.1.2 node02
192.168.1.3 node03

# Storage Nodes
192.168.2.1 storage01
192.168.2.2 storage02
"""

        parser = HostsParser()
        nodes = parser.parse_content(hosts_content)

        assert len(nodes) == 5
        assert nodes[0]["hostname"] == "node01"
        assert nodes[0]["ip"] == "192.168.1.1"
        assert nodes[3]["hostname"] == "storage01"

    def test_batch_config_from_hosts_file(self):
        """测试从hosts文件加载批量配置"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 创建hosts文件
            hosts_file = os.path.join(tmpdir, "hosts.txt")
            with open(hosts_file, "w") as f:
                f.write("10.0.0.1 gpu-node-01\n")
                f.write("10.0.0.2 gpu-node-02\n")
                f.write("10.0.0.3 gpu-node-03\n")

            # 创建配置文件
            config_file = os.path.join(tmpdir, "cluster.yaml")
            with open(config_file, "w") as f:
                f.write("""
cluster:
  name: test-cluster

node_batch:
  enabled: true
  hosts_file: hosts.txt
  roles:
    - gpu_node
  storage_template:
    type: single
    device: /dev/nvme0n1
    mount_point: /ssd
    format_disk: false
""")

            # 加载配置
            loader = ConfigLoader(tmpdir)
            cluster = loader.load_cluster_config("cluster.yaml")

            assert cluster.name == "test-cluster"
            assert len(cluster.nodes) == 3
            assert cluster.nodes[0].hostname == "gpu-node-01"
            assert cluster.nodes[0].ip == "10.0.0.1"
            assert "gpu_node" in cluster.nodes[0].roles
            assert cluster.nodes[0].storage is not None

    def test_batch_config_with_overrides(self):
        """测试批量配置与个别覆盖合并"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 创建hosts文件
            hosts_file = os.path.join(tmpdir, "hosts.txt")
            with open(hosts_file, "w") as f:
                f.write("10.0.0.1 node01\n")
                f.write("10.0.0.2 node02\n")
                f.write("10.0.0.3 node03\n")

            # 创建配置文件
            config_file = os.path.join(tmpdir, "cluster.yaml")
            with open(config_file, "w") as f:
                f.write("""
cluster:
  name: test-cluster

node_batch:
  enabled: true
  hosts_file: hosts.txt
  roles:
    - gpu_node

nodes_override:
  - hostname: node02
    ip: 10.0.100.2
    roles:
      - nfs_server
      - gpu_node
  - hostname: node04
    ip: 10.0.0.4
    roles:
      - time_server
""")

            # 加载配置
            loader = ConfigLoader(tmpdir)
            cluster = loader.load_cluster_config("cluster.yaml")

            assert len(cluster.nodes) == 4  # 3 from batch + 1 new

            # 检查覆盖是否生效
            node02 = next(n for n in cluster.nodes if n.hostname == "node02")
            assert node02.ip == "10.0.100.2"
            assert "nfs_server" in node02.roles

            # 检查新增节点
            node04 = next(n for n in cluster.nodes if n.hostname == "node04")
            assert node04 is not None
            assert "time_server" in node04.roles

    def test_storage_template_application(self):
        """测试存储模板应用到批量节点"""
        with tempfile.TemporaryDirectory() as tmpdir:
            hosts_file = os.path.join(tmpdir, "hosts.txt")
            with open(hosts_file, "w") as f:
                f.write("10.0.0.1 node01\n")

            config_file = os.path.join(tmpdir, "cluster.yaml")
            with open(config_file, "w") as f:
                f.write("""
cluster:
  name: test-cluster

node_batch:
  enabled: true
  hosts_file: hosts.txt
  storage_template:
    type: raid1
    devices:
      - /dev/nvme0n1
      - /dev/nvme1n1
    mount_point: /data
    filesystem: xfs
    format_disk: false
""")

            loader = ConfigLoader(tmpdir)
            cluster = loader.load_cluster_config("cluster.yaml")

            assert len(cluster.nodes) == 1
            storage = cluster.nodes[0].storage
            assert storage is not None
            assert storage.type == "raid1"
            assert len(storage.devices) == 2
            assert storage.mount_point == "/data"
            assert storage.filesystem == "xfs"

    def test_auth_template_application(self):
        """测试认证模板应用到批量节点"""
        with tempfile.TemporaryDirectory() as tmpdir:
            hosts_file = os.path.join(tmpdir, "hosts.txt")
            with open(hosts_file, "w") as f:
                f.write("10.0.0.1 node01\n")

            config_file = os.path.join(tmpdir, "cluster.yaml")
            with open(config_file, "w") as f:
                f.write("""
cluster:
  name: test-cluster

node_batch:
  enabled: true
  hosts_file: hosts.txt
  auth_template:
    type: key
    username: admin
    private_key: /home/admin/.ssh/id_rsa
""")

            loader = ConfigLoader(tmpdir)
            cluster = loader.load_cluster_config("cluster.yaml")

            assert cluster.node_batch.auth_template is not None
            assert cluster.node_batch.auth_template.auth_type == "key"
            assert cluster.node_batch.auth_template.username == "admin"

    def test_hosts_content_direct(self):
        """测试直接使用hosts_content"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = os.path.join(tmpdir, "cluster.yaml")
            with open(config_file, "w") as f:
                f.write("""
cluster:
  name: test-cluster

node_batch:
  enabled: true
  hosts_content: |
    192.168.1.1 server01
    192.168.1.2 server02
  roles:
    - gpu_node
""")

            loader = ConfigLoader(tmpdir)
            cluster = loader.load_cluster_config("cluster.yaml")

            assert len(cluster.nodes) == 2
            assert cluster.nodes[0].hostname == "server01"
            assert cluster.nodes[1].ip == "192.168.1.2"

    def test_backward_compatibility(self):
        """测试向后兼容性：不使用批量配置"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = os.path.join(tmpdir, "cluster.yaml")
            with open(config_file, "w") as f:
                f.write("""
cluster:
  name: legacy-cluster

nodes:
  - hostname: node01
    ip: 10.0.0.1
    roles:
      - nfs_server
  - hostname: node02
    ip: 10.0.0.2
    roles:
      - gpu_node
""")

            loader = ConfigLoader(tmpdir)
            cluster = loader.load_cluster_config("cluster.yaml")

            assert len(cluster.nodes) == 2
            assert cluster.node_batch.enabled is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
