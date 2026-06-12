#!/usr/bin/env python3
"""
网络配置模块单元测试
"""

import pytest
from datetime import datetime
from unittest.mock import Mock, patch
import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.models.network import (
    NICInfo,
    NICType,
    NICStatus,
    NICMapping,
    NICRenameRule,
    NICRenameConfig,
    NetworkTopology,
    NetworkConfig,
    NICRenameResult,
)
from src.network.nic_mapper import (
    NICMapper,
    NonContiguousMapper,
    SelectiveMapper,
    create_mapper,
)
from src.network.nic_renamer import (
    NICRenamer,
    RDMARenamer,
    EthernetRenamer,
    create_renamer,
)


class TestNICInfo:
    """NICInfo数据类测试"""

    def test_default_nic_info(self):
        """测试默认网卡信息"""
        nic = NICInfo(name="eth0", nic_type=NICType.ETHERNET)

        assert nic.name == "eth0"
        assert nic.nic_type == NICType.ETHERNET
        assert nic.mac_address is None
        assert nic.status == NICStatus.UNKNOWN

    def test_nic_info_to_dict(self):
        """测试网卡信息转换为字典"""
        nic = NICInfo(
            name="mlx5_0",
            nic_type=NICType.RDMA,
            mac_address="00:11:22:33:44:55",
            pci_address="0000:3b:00.0",
            ib_device="mlx5_0",
            ib_port=1,
        )

        nic_dict = nic.to_dict()

        assert nic_dict["name"] == "mlx5_0"
        assert nic_dict["nic_type"] == "rdma"
        assert nic_dict["mac_address"] == "00:11:22:33:44:55"
        assert nic_dict["ib_device"] == "mlx5_0"


class TestNICMapping:
    """NICMapping数据类测试"""

    def test_default_mapping(self):
        """测试默认映射"""
        mapping = NICMapping(
            source_pattern="mlx5_*",
            target_name="rdma{index}",
            nic_type=NICType.RDMA,
        )

        assert mapping.source_pattern == "mlx5_*"
        assert mapping.target_name == "rdma{index}"
        assert mapping.nic_type == NICType.RDMA
        assert mapping.enabled is True

    def test_mapping_to_dict(self):
        """测试映射转换为字典"""
        mapping = NICMapping(
            source_pattern="ens*",
            target_name="eth{index1}",
            nic_type=NICType.ETHERNET,
            condition={"driver": "mlx5_core"},
            enabled=False,
        )

        mapping_dict = mapping.to_dict()

        assert mapping_dict["source_pattern"] == "ens*"
        assert mapping_dict["target_name"] == "eth{index1}"
        assert mapping_dict["nic_type"] == "ethernet"
        assert mapping_dict["condition"]["driver"] == "mlx5_core"
        assert mapping_dict["enabled"] is False


class TestNICRenameConfig:
    """NICRenameConfig数据类测试"""

    def test_default_config(self):
        """测试默认配置"""
        config = NICRenameConfig()

        assert config.enabled is False
        assert config.mappings == []
        assert config.create_udev_rules is True
        assert config.backup_original is True
        assert config.dry_run is False

    def test_config_from_dict(self):
        """测试从字典创建配置"""
        data = {
            "enabled": True,
            "mappings": [
                {
                    "source_pattern": "mlx5_*",
                    "target_name": "rdma{index}",
                    "nic_type": "rdma",
                    "enabled": True,
                }
            ],
            "create_udev_rules": False,
            "dry_run": True,
        }

        config = NICRenameConfig.from_dict(data)

        assert config.enabled is True
        assert len(config.mappings) == 1
        assert config.mappings[0].source_pattern == "mlx5_*"
        assert config.create_udev_rules is False
        assert config.dry_run is True


class TestNetworkTopology:
    """NetworkTopology数据类测试"""

    def test_default_topology(self):
        """测试默认拓扑"""
        topology = NetworkTopology(node_hostname="node01")

        assert topology.node_hostname == "node01"
        assert topology.rdma_nics == []
        assert topology.ethernet_nics == []
        assert topology.total_nics == 0

    def test_topology_with_nics(self):
        """测试带网卡的拓扑"""
        topology = NetworkTopology(
            node_hostname="node01",
            rdma_nics=[
                NICInfo(name="mlx5_0", nic_type=NICType.RDMA),
                NICInfo(name="mlx5_1", nic_type=NICType.RDMA),
            ],
            ethernet_nics=[
                NICInfo(name="eth0", nic_type=NICType.ETHERNET),
            ],
        )

        assert topology.total_nics == 3
        assert len(topology.rdma_nics) == 2
        assert len(topology.ethernet_nics) == 1


class TestNICMapper:
    """NICMapper测试"""

    def test_mapper_initialization(self):
        """测试映射器初始化"""
        mapper = NICMapper()

        assert mapper.config is not None
        assert mapper.config.enabled is False

    def test_match_pattern_glob(self):
        """测试glob模式匹配"""
        mapper = NICMapper()

        assert mapper._match_pattern("mlx5_0", "mlx5_*")
        assert mapper._match_pattern("mlx5_10", "mlx5_*")
        assert not mapper._match_pattern("eth0", "mlx5_*")

    def test_match_pattern_regex(self):
        """测试正则表达式匹配"""
        mapper = NICMapper()

        assert mapper._match_pattern("mlx5_0", "^mlx5_[0-9]+$")
        assert not mapper._match_pattern("mlx5_abc", "^mlx5_[0-9]+$")

    def test_generate_target_name(self):
        """测试目标名称生成"""
        mapper = NICMapper()
        nic = NICInfo(
            name="mlx5_0",
            nic_type=NICType.RDMA,
            pci_address="0000:3b:00.0",
            mac_address="00:11:22:33:44:55",
        )

        # 测试索引变量
        assert mapper._generate_target_name("rdma{index}", nic, 0) == "rdma0"
        assert mapper._generate_target_name("rdma{index1}", nic, 0) == "rdma1"

        # 测试PCI变量
        name = mapper._generate_target_name("nic_{pci}", nic, 0)
        assert "00003b000" in name

        # 测试MAC变量
        name = mapper._generate_target_name("nic_{mac}", nic, 0)
        assert "001122334455" in name

    def test_generate_rules(self):
        """测试生成规则"""
        config = NICRenameConfig(
            enabled=True,
            mappings=[
                NICMapping(
                    source_pattern="mlx5_*",
                    target_name="rdma{index}",
                    nic_type=NICType.RDMA,
                )
            ],
        )
        mapper = NICMapper(config)

        topology = NetworkTopology(
            node_hostname="node01",
            rdma_nics=[
                NICInfo(name="mlx5_0", nic_type=NICType.RDMA, pci_address="0000:3b:00.0"),
                NICInfo(name="mlx5_1", nic_type=NICType.RDMA, pci_address="0000:3b:00.1"),
            ],
        )

        rules = mapper.generate_rules(topology)

        assert len(rules) == 2
        assert rules[0].original_name == "mlx5_0"
        assert rules[0].new_name == "rdma0"
        assert rules[1].original_name == "mlx5_1"
        assert rules[1].new_name == "rdma1"

    def test_preview(self):
        """测试预览功能"""
        config = NICRenameConfig(
            enabled=True,
            mappings=[
                NICMapping(
                    source_pattern="mlx5_*",
                    target_name="rdma{index}",
                    nic_type=NICType.RDMA,
                )
            ],
        )
        mapper = NICMapper(config)

        topology = NetworkTopology(
            node_hostname="node01",
            rdma_nics=[
                NICInfo(name="mlx5_0", nic_type=NICType.RDMA),
            ],
        )

        preview = mapper.preview(topology)

        assert preview["enabled"] is True
        assert preview["total_rules"] == 1


class TestNonContiguousMapper:
    """NonContiguousMapper测试"""

    def test_non_contiguous_indexing(self):
        """测试非连续索引"""
        config = NICRenameConfig(
            enabled=True,
            mappings=[
                NICMapping(
                    source_pattern="mlx5_*",
                    target_name="rdma{index}",
                    nic_type=NICType.RDMA,
                )
            ],
        )
        mapper = NonContiguousMapper(config)

        topology = NetworkTopology(
            node_hostname="node01",
            rdma_nics=[
                NICInfo(name="mlx5_0", nic_type=NICType.RDMA),
                NICInfo(name="mlx5_2", nic_type=NICType.RDMA),  # 跳过mlx5_1
                NICInfo(name="mlx5_5", nic_type=NICType.RDMA),  # 跳过mlx5_3, mlx5_4
            ],
        )

        rules = mapper.generate_rules(topology)

        # 非连续映射器应该生成连续的目标名称
        assert len(rules) == 3
        assert rules[0].new_name == "rdma0"
        assert rules[1].new_name == "rdma1"
        assert rules[2].new_name == "rdma2"


class TestSelectiveMapper:
    """SelectiveMapper测试"""

    def test_include_patterns(self):
        """测试包含模式"""
        config = NICRenameConfig(
            enabled=True,
            mappings=[
                NICMapping(
                    source_pattern="mlx5_*",
                    target_name="rdma{index}",
                    nic_type=NICType.RDMA,
                )
            ],
        )
        mapper = SelectiveMapper(config)
        mapper.set_include_patterns(["mlx5_0", "mlx5_2"])

        topology = NetworkTopology(
            node_hostname="node01",
            rdma_nics=[
                NICInfo(name="mlx5_0", nic_type=NICType.RDMA),
                NICInfo(name="mlx5_1", nic_type=NICType.RDMA),
                NICInfo(name="mlx5_2", nic_type=NICType.RDMA),
            ],
        )

        rules = mapper.generate_rules(topology)

        assert len(rules) == 2
        assert rules[0].original_name == "mlx5_0"
        assert rules[1].original_name == "mlx5_2"

    def test_exclude_patterns(self):
        """测试排除模式"""
        config = NICRenameConfig(
            enabled=True,
            mappings=[
                NICMapping(
                    source_pattern="mlx5_*",
                    target_name="rdma{index}",
                    nic_type=NICType.RDMA,
                )
            ],
        )
        mapper = SelectiveMapper(config)
        mapper.set_exclude_patterns(["mlx5_1"])

        topology = NetworkTopology(
            node_hostname="node01",
            rdma_nics=[
                NICInfo(name="mlx5_0", nic_type=NICType.RDMA),
                NICInfo(name="mlx5_1", nic_type=NICType.RDMA),
                NICInfo(name="mlx5_2", nic_type=NICType.RDMA),
            ],
        )

        rules = mapper.generate_rules(topology)

        assert len(rules) == 2
        assert "mlx5_1" not in [r.original_name for r in rules]


class TestNICRenamer:
    """NICRenamer测试"""

    def test_renamer_initialization(self):
        """测试重命名器初始化"""
        renamer = NICRenamer()

        assert renamer.config is not None
        assert renamer.mapper is not None

    def test_plan(self):
        """测试规划功能"""
        config = NICRenameConfig(
            enabled=True,
            mappings=[
                NICMapping(
                    source_pattern="mlx5_*",
                    target_name="rdma{index}",
                    nic_type=NICType.RDMA,
                )
            ],
        )
        renamer = NICRenamer(config)

        topology = NetworkTopology(
            node_hostname="node01",
            rdma_nics=[
                NICInfo(name="mlx5_0", nic_type=NICType.RDMA, pci_address="0000:3b:00.0"),
            ],
        )

        rules = renamer.plan(topology)

        assert len(rules) == 1
        assert rules[0].original_name == "mlx5_0"
        assert rules[0].new_name == "rdma0"

    def test_dry_run(self):
        """测试预览模式"""
        config = NICRenameConfig(
            enabled=True,
            dry_run=True,
            mappings=[
                NICMapping(
                    source_pattern="mlx5_*",
                    target_name="rdma{index}",
                    nic_type=NICType.RDMA,
                )
            ],
        )
        renamer = NICRenamer(config)

        topology = NetworkTopology(
            node_hostname="node01",
            rdma_nics=[
                NICInfo(name="mlx5_0", nic_type=NICType.RDMA),
            ],
        )

        result = renamer.execute(topology)

        assert result.success is True
        assert len(result.rules) == 1


class TestCreateMapper:
    """create_mapper工厂函数测试"""

    def test_create_default_mapper(self):
        """测试创建默认映射器"""
        mapper = create_mapper()
        assert isinstance(mapper, NICMapper)

    def test_create_non_contiguous_mapper(self):
        """测试创建非连续映射器"""
        mapper = create_mapper(mapper_type="non_contiguous")
        assert isinstance(mapper, NonContiguousMapper)

    def test_create_selective_mapper(self):
        """测试创建选择性映射器"""
        mapper = create_mapper(mapper_type="selective")
        assert isinstance(mapper, SelectiveMapper)


class TestCreateRenamer:
    """create_renamer工厂函数测试"""

    def test_create_default_renamer(self):
        """测试创建默认重命名器"""
        renamer = create_renamer()
        assert isinstance(renamer, NICRenamer)

    def test_create_rdma_renamer(self):
        """测试创建RDMA重命名器"""
        renamer = create_renamer(nic_type=NICType.RDMA)
        assert isinstance(renamer, RDMARenamer)

    def test_create_ethernet_renamer(self):
        """测试创建以太网重命名器"""
        renamer = create_renamer(nic_type=NICType.ETHERNET)
        assert isinstance(renamer, EthernetRenamer)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
