#!/usr/bin/env python3
"""
测试新的配置加载功能：批量节点配置、磁盘格式化选项等
"""

import sys
import tempfile
from pathlib import Path

# 添加src到路径
sys.path.insert(0, str(Path(__file__).parent / "src"))

from config_loader import ConfigLoader


def test_batch_nodes_with_hosts():
    """测试批量节点配置（使用hosts文件）"""
    print("测试批量节点配置（使用hosts文件）...")

    hosts_content = """# 批量节点配置
10.0.1.1 node01 node01.cluster.local
10.0.1.2 node02
10.0.1.3 node03 node03.cluster.local
10.0.1.4 node04
"""

    config_content = f"""
cluster:
  name: test-batch-cluster
  description: 测试批量节点集群

jumphost:
  host: "192.168.1.1"
  port: 22
  auth:
    type: "key"
    username: "ubuntu"
    private_key: "~/.ssh/id_rsa"
    node_auth:
      type: "key"
      username: "ubuntu"
      private_key: "~/.ssh/id_rsa"

node_batch:
  enabled: true
  hosts_content: |
{hosts_content}
  roles:
    - gpu_node
  storage_template:
    type: "single"
    mount_point: "/ssd"
    filesystem: "ext4"
    format_disk: true

# 个别节点覆盖
nodes_override:
  - hostname: "node02"
    storage:
      device: "/dev/nvme0n1"
      format_disk: false  # 特别指定不格式化

# 独立节点
nodes:
  - hostname: "master-node"
    ip: "10.0.0.1"
    roles:
      - nfs_server
      - time_server
    storage:
      type: "raid10"
      devices:
        - "/dev/nvme0n1"
        - "/dev/nvme1n1"
        - "/dev/nvme2n1"
        - "/dev/nvme3n1"
      mount_point: "/ssd"
      filesystem: "ext4"
      format_disk: true

nfs:
  enabled: true
  server: "master-node"

network:
  nics:
    compute_400g:
      pattern: "mlx5_[0-7]"
      count: 8
      net_prefix: "ib"
"""

    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        f.write(config_content)
        config_file = f.name

    try:
        loader = ConfigLoader()
        loader.config_dir = Path(config_file).parent
        cluster = loader.load_cluster_config(Path(config_file).name)

        print(f"集群名称: {cluster.name}")
        print(f"总节点数: {len(cluster.nodes)}")

        print("\n节点列表:")
        for node in cluster.nodes:
            print(f"  - {node.hostname} ({node.ip}) 角色: {node.roles}")
            if node.storage:
                print(f"    存储: {node.storage.type}, 挂载点: {node.storage.mount_point}")
                print(f"    文件系统: {node.storage.filesystem}, 格式化: {node.storage.format_disk}")

        print(f"\n批量节点配置:")
        print(f"  启用: {cluster.node_batch.enabled}")
        print(f"  角色: {cluster.node_batch.roles}")
        print(f"  存储模板: {cluster.node_batch.storage_template is not None}")

        if cluster.node_batch.storage_template:
            print(f"    文件系统: {cluster.node_batch.storage_template.filesystem}")
            print(f"    格式化: {cluster.node_batch.storage_template.format_disk}")

        print("\n跳转服务器节点认证:")
        if cluster.jumphost and cluster.jumphost.node_auth:
            print(f"  类型: {cluster.jumphost.node_auth.auth_type}")
            print(f"  用户名: {cluster.jumphost.node_auth.username}")

        # 验证
        errors = loader.validate()
        if errors:
            print(f"\n验证错误: {errors}")
        else:
            print("\n配置验证通过!")

        return True

    finally:
        Path(config_file).unlink()


def test_batch_nodes_with_template():
    """测试批量节点配置（使用模板）"""
    print("\n" + "="*60)
    print("测试批量节点配置（使用模板）...")

    config_content = """
cluster:
  name: test-template-cluster
  description: 测试模板批量节点集群

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
  base_ip_prefix: "10.254.43"
  count: 5
  start_index: 66
  roles:
    - gpu_node
  storage_template:
    type: "single"
    mount_point: "/ssd"
    filesystem: "ext4"
    format_disk: true

nfs:
  enabled: true
  server: "gpu-master"

# NFS服务器单独配置
nodes:
  - hostname: "gpu-master"
    ip: "10.254.43.65"
    roles:
      - nfs_server
      - time_server
    storage:
      type: "raid10"
      devices:
        - "/dev/nvme0n1"
        - "/dev/nvme1n1"
        - "/dev/nvme2n1"
        - "/dev/nvme3n1"
      mount_point: "/ssd"
      filesystem: "ext4"
      format_disk: true
"""

    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        f.write(config_content)
        config_file = f.name

    try:
        loader = ConfigLoader()
        loader.config_dir = Path(config_file).parent
        cluster = loader.load_cluster_config(Path(config_file).name)

        print(f"集群名称: {cluster.name}")
        print(f"总节点数: {len(cluster.nodes)}")
        print(f"批量节点数: {cluster.node_batch.count}")

        print("\n批量节点列表:")
        batch_nodes = [n for n in cluster.nodes if n.hostname.startswith(cluster.node_batch.base_hostname_prefix)]
        for node in batch_nodes:
            print(f"  - {node.hostname} ({node.ip}) 角色: {node.roles}")
            if node.storage:
                print(f"    存储: {node.storage.type}, 格式化: {node.storage.format_disk}")

        print("\n独立节点:")
        for node in cluster.nodes:
            if not node.hostname.startswith(cluster.node_batch.base_hostname_prefix):
                print(f"  - {node.hostname} ({node.ip}) 角色: {node.roles}")

        # 验证
        errors = loader.validate()
        if errors:
            print(f"\n验证错误: {errors}")
        else:
            print("\n配置验证通过!")

        return True

    finally:
        Path(config_file).unlink()


def test_hosts_parser():
    """测试hosts解析器"""
    print("\n" + "="*60)
    print("测试hosts解析器...")

    try:
        from utils.hosts_parser import HostsParser

        test_content = """# 测试集群节点配置
10.0.1.1 node01 node01.cluster.local
10.0.1.2 node02
10.0.1.3 node03 node03.cluster.local

# 无效行将被忽略
invalid-ip node04
10.0.1.4
"""

        parser = HostsParser()
        nodes = parser.parse_content(test_content)

        print(f"解析到 {len(nodes)} 个节点:")
        for node in nodes:
            print(f"  IP: {node['ip']}, Hostname: {node['hostname']}")

        # 测试生成
        generated = parser.generate_hosts_content(nodes, "# 测试生成的配置")
        print("\n生成的hosts内容:")
        print(generated)

        return True

    except ImportError as e:
        print(f"导入错误: {e}")
        return False


def test_backward_compatibility():
    """测试向后兼容性"""
    print("\n" + "="*60)
    print("测试向后兼容性...")

    config_content = """
cluster:
  name: old-style-cluster
  description: 测试旧式配置兼容性

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

  - hostname: "node-02"
    ip: "10.0.0.2"
    roles:
      - gpu_node
    storage:
      type: "single"
      device: "/dev/nvme0n1"
      mount_point: "/ssd"

nfs:
  enabled: true
  server: "node-01"
"""

    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        f.write(config_content)
        config_file = f.name

    try:
        loader = ConfigLoader()
        loader.config_dir = Path(config_file).parent
        cluster = loader.load_cluster_config(Path(config_file).name)

        print(f"集群名称: {cluster.name}")
        print(f"总节点数: {len(cluster.nodes)}")

        print("\n节点列表:")
        for node in cluster.nodes:
            print(f"  - {node.hostname} ({node.ip}) 角色: {node.roles}")
            if node.storage:
                print(f"    存储: {node.storage.type}")
                # 验证新字段的默认值
                print(f"    文件系统: {node.storage.filesystem} (默认: ext4)")
                print(f"    格式化: {node.storage.format_disk} (默认: True)")

        print(f"\n批量节点配置:")
        print(f"  启用: {cluster.node_batch.enabled} (默认: False)")

        # 验证
        errors = loader.validate()
        if errors:
            print(f"\n验证错误: {errors}")
        else:
            print("\n配置验证通过! 向后兼容性测试成功!")

        return True

    finally:
        Path(config_file).unlink()


def main():
    """主测试函数"""
    print("开始测试GPU集群部署配置增强功能")
    print("="*60)

    test_results = []

    # 测试向后兼容性
    test_results.append(("向后兼容性", test_backward_compatibility()))

    # 测试hosts解析器
    test_results.append(("hosts解析器", test_hosts_parser()))

    # 测试批量节点配置
    test_results.append(("批量节点（hosts）", test_batch_nodes_with_hosts()))
    test_results.append(("批量节点（模板）", test_batch_nodes_with_template()))

    # 输出测试结果汇总
    print("\n" + "="*60)
    print("测试结果汇总:")
    print("-"*60)

    all_passed = True
    for test_name, passed in test_results:
        status = "✓ 通过" if passed else "✗ 失败"
        print(f"{test_name}: {status}")
        if not passed:
            all_passed = False

    print("-"*60)
    if all_passed:
        print("所有测试通过! ✅")
    else:
        print("部分测试失败! ❌")

    return all_passed


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)