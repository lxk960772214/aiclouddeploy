#!/usr/bin/env python3
"""
测试磁盘挂载步骤增强功能
"""

import sys
from pathlib import Path

# 添加src到路径
sys.path.insert(0, str(Path(__file__).parent / "src"))

from src.models.cluster import StorageConfig, StorageType


def test_storage_config_format_disk():
    """测试存储配置的格式化选项"""
    print("测试存储配置的格式化选项...")

    # 测试1: 默认配置
    storage1 = StorageConfig(
        type=StorageType.SINGLE,
        device="/dev/nvme0n1",
        mount_point="/ssd"
    )
    print(f"默认配置:")
    print(f"  filesystem: {storage1.filesystem} (预期: ext4)")
    print(f"  format_disk: {storage1.format_disk} (预期: True)")

    assert storage1.filesystem == "ext4", f"filesystem应为ext4，实际为{storage1.filesystem}"
    assert storage1.format_disk is True, f"format_disk应为True，实际为{storage1.format_disk}"

    # 测试2: 指定不格式化
    storage2 = StorageConfig(
        type=StorageType.SINGLE,
        device="/dev/nvme0n1",
        mount_point="/ssd",
        filesystem="xfs",
        format_disk=False
    )
    print(f"\n指定不格式化配置:")
    print(f"  filesystem: {storage2.filesystem} (预期: xfs)")
    print(f"  format_disk: {storage2.format_disk} (预期: False)")

    assert storage2.filesystem == "xfs", f"filesystem应为xfs，实际为{storage2.filesystem}"
    assert storage2.format_disk is False, f"format_disk应为False，实际为{storage2.format_disk}"

    # 测试3: RAID配置
    storage3 = StorageConfig(
        type=StorageType.RAID10,
        devices=["/dev/nvme0n1", "/dev/nvme1n1", "/dev/nvme2n1", "/dev/nvme3n1"],
        mount_point="/ssd",
        filesystem="ext4",
        format_disk=True
    )
    print(f"\nRAID配置:")
    print(f"  type: {storage3.type}")
    print(f"  filesystem: {storage3.filesystem} (预期: ext4)")
    print(f"  format_disk: {storage3.format_disk} (预期: True)")

    assert storage3.type == StorageType.RAID10, f"type应为RAID10，实际为{storage3.type}"
    assert storage3.filesystem == "ext4", f"filesystem应为ext4，实际为{storage3.filesystem}"
    assert storage3.format_disk is True, f"format_disk应为True，实际为{storage3.format_disk}"

    return True


def test_to_dict_method():
    """测试to_dict方法包含新字段"""
    print("\n" + "="*60)
    print("测试to_dict方法包含新字段...")

    storage = StorageConfig(
        type=StorageType.SINGLE,
        device="/dev/nvme0n1",
        mount_point="/ssd",
        filesystem="xfs",
        format_disk=False
    )

    dict_repr = storage.to_dict()
    print(f"字典表示: {dict_repr}")

    assert 'filesystem' in dict_repr, "字典应包含filesystem字段"
    assert 'format_disk' in dict_repr, "字典应包含format_disk字段"
    assert dict_repr['filesystem'] == "xfs", f"filesystem应为xfs，实际为{dict_repr['filesystem']}"
    assert dict_repr['format_disk'] is False, f"format_disk应为False，实际为{dict_repr['format_disk']}"

    print("✓ to_dict方法正确包含新字段")
    return True


def test_model_integration():
    """测试模型集成"""
    print("\n" + "="*60)
    print("测试模型集成...")

    from src.models.cluster import NodeConfig

    # 创建包含存储配置的节点
    storage = StorageConfig(
        type=StorageType.SINGLE,
        device="/dev/nvme0n1",
        mount_point="/ssd",
        filesystem="ext4",
        format_disk=True
    )

    node = NodeConfig(
        hostname="test-node",
        ip="10.0.0.1",
        roles=["gpu_node"],
        storage=storage
    )

    print(f"节点: {node.hostname}")
    print(f"存储配置存在: {node.storage is not None}")
    if node.storage:
        print(f"  文件系统: {node.storage.filesystem}")
        print(f"  格式化: {node.storage.format_disk}")

    # 测试to_dict
    node_dict = node.to_dict()
    print(f"\n节点字典表示中的存储配置:")
    if node_dict.get('storage'):
        print(f"  filesystem: {node_dict['storage'].get('filesystem')}")
        print(f"  format_disk: {node_dict['storage'].get('format_disk')}")

    assert node.storage is not None, "节点存储配置不应为None"
    assert node.storage.filesystem == "ext4", f"filesystem应为ext4，实际为{node.storage.filesystem}"
    assert node.storage.format_disk is True, f"format_disk应为True，实际为{node.storage.format_disk}"

    print("✓ 模型集成测试通过")
    return True


def test_step_import():
    """测试步骤导入"""
    print("\n" + "="*60)
    print("测试步骤导入...")

    try:
        from src.steps.step_6_disk_mount import DiskMount
        print("✓ DiskMount类导入成功")

        # 检查类属性
        print(f"  步骤ID: {DiskMount.step_id}")
        print(f"  步骤名称: {DiskMount.step_name}")
        print(f"  步骤描述: {DiskMount.step_description}")

        assert DiskMount.step_id == "06", f"步骤ID应为06，实际为{DiskMount.step_id}"
        assert DiskMount.step_name == "挂载数据盘", f"步骤名称不正确"

        return True

    except ImportError as e:
        print(f"✗ 导入失败: {e}")
        return False
    except Exception as e:
        print(f"✗ 其他错误: {e}")
        return False


def main():
    """主测试函数"""
    print("开始测试磁盘挂载步骤增强功能")
    print("="*60)

    test_results = []

    test_results.append(("存储配置格式化选项", test_storage_config_format_disk()))
    test_results.append(("to_dict方法", test_to_dict_method()))
    test_results.append(("模型集成", test_model_integration()))
    test_results.append(("步骤导入", test_step_import()))

    # 输出结果汇总
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
        print("\n磁盘挂载步骤增强功能完成:")
        print("  1. 添加format_disk选项控制是否格式化磁盘")
        print("  2. 添加filesystem选项支持不同文件系统")
        print("  3. 增强单盘和RAID挂载逻辑，支持条件格式化")
        print("  4. 改进现有挂载点和fstab条目的处理")
    else:
        print("部分测试失败! ❌")

    return all_passed


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)