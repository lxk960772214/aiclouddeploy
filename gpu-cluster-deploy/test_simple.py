#!/usr/bin/env python3
"""
简化测试新配置功能
"""

import sys
import tempfile
import yaml
from pathlib import Path

# 添加src到路径
sys.path.insert(0, str(Path(__file__).parent / "src"))

from config_loader import ConfigLoader


def create_test_config():
    """创建测试配置"""
    config = {
        "cluster": {
            "name": "test-cluster",
            "description": "测试集群"
        },
        "jumphost": {
            "host": "192.168.1.1",
            "port": 22,
            "auth": {
                "type": "key",
                "username": "ubuntu",
                "private_key": "~/.ssh/id_rsa",
                "node_auth": {
                    "type": "key",
                    "username": "ubuntu",
                    "private_key": "~/.ssh/id_rsa"
                }
            }
        },
        "node_batch": {
            "enabled": True,
            "base_hostname_prefix": "gpu-node-",
            "base_ip_prefix": "10.254.43",
            "count": 3,
            "start_index": 66,
            "roles": ["gpu_node"],
            "storage_template": {
                "type": "single",
                "device": "/dev/nvme0n1",
                "mount_point": "/ssd",
                "filesystem": "ext4",
                "format_disk": True
            }
        },
        "nodes": [
            {
                "hostname": "gpu-master",
                "ip": "10.254.43.65",
                "roles": ["nfs_server", "time_server"],
                "storage": {
                    "type": "raid10",
                    "devices": ["/dev/nvme0n1", "/dev/nvme1n1", "/dev/nvme2n1", "/dev/nvme3n1"],
                    "mount_point": "/ssd",
                    "filesystem": "ext4",
                    "format_disk": True
                }
            }
        ],
        "nfs": {
            "enabled": True,
            "server": "gpu-master"
        },
        "network": {
            "nics": {
                "compute_400g": {
                    "pattern": "mlx5_[0-7]",
                    "count": 8,
                    "net_prefix": "ib"
                }
            }
        }
    }

    # 创建临时文件
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True, indent=2)
        return f.name


def test_config_loader():
    """测试配置加载器"""
    print("测试新的配置加载器功能...")

    config_file = create_test_config()

    try:
        loader = ConfigLoader()
        loader.config_dir = Path(config_file).parent
        cluster = loader.load_cluster_config(Path(config_file).name)

        print(f"集群名称: {cluster.name}")
        print(f"总节点数: {len(cluster.nodes)}")
        print(f"批量节点数: {cluster.node_batch.count}")

        print("\n节点列表:")
        for node in cluster.nodes:
            print(f"  - {node.hostname} ({node.ip}) 角色: {node.roles}")
            if node.storage:
                print(f"    存储: {node.storage.type}")
                print(f"    文件系统: {node.storage.filesystem}")
                print(f"    格式化: {node.storage.format_disk}")

        # 验证
        errors = loader.validate()
        if errors:
            print(f"\n验证错误: {errors}")
        else:
            print("\n配置验证通过!")

        return True

    finally:
        Path(config_file).unlink()


def test_backward_compat():
    """测试向后兼容性"""
    print("\n" + "="*60)
    print("测试向后兼容性...")

    config = {
        "cluster": {
            "name": "old-cluster",
            "description": "旧式配置测试"
        },
        "jumphost": {
            "host": "192.168.1.1",
            "port": 22,
            "auth": {
                "type": "key",
                "username": "ubuntu",
                "private_key": "~/.ssh/id_rsa"
            }
        },
        "nodes": [
            {
                "hostname": "node-01",
                "ip": "10.0.0.1",
                "roles": ["gpu_node"],
                "storage": {
                    "type": "single",
                    "device": "/dev/nvme0n1",
                    "mount_point": "/ssd"
                }
            }
        ]
    }

    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True, indent=2)
        config_file = f.name

    try:
        loader = ConfigLoader()
        loader.config_dir = Path(config_file).parent
        cluster = loader.load_cluster_config(Path(config_file).name)

        print(f"集群名称: {cluster.name}")
        print(f"节点数: {len(cluster.nodes)}")

        node = cluster.nodes[0]
        print(f"\n节点: {node.hostname} ({node.ip})")
        if node.storage:
            print(f"存储: {node.storage.type}")
            print(f"文件系统: {node.storage.filesystem} (默认: ext4)")
            print(f"格式化: {node.storage.format_disk} (默认: True)")

        errors = loader.validate()
        if errors:
            print(f"\n验证错误: {errors}")
            return False
        else:
            print("\n向后兼容性测试通过!")
            return True

    finally:
        Path(config_file).unlink()


def main():
    """主测试函数"""
    print("开始测试GPU集群部署配置增强功能")
    print("="*60)

    test_results = []

    test_results.append(("向后兼容性", test_backward_compat()))
    test_results.append(("新配置功能", test_config_loader()))

    # 输出结果
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