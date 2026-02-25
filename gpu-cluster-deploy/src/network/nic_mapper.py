#!/usr/bin/env python3
"""
GPU Cluster Deploy - 网卡映射解析器
解析配置并生成具体的设备重命名规则，支持非连续映射
"""

import re
from dataclasses import dataclass, field
from fnmatch import fnmatch
from typing import Optional, List, Dict, Any, Tuple

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.models.network import (
    NICInfo,
    NICType,
    NICMapping,
    NICRenameRule,
    NICRenameConfig,
    NetworkTopology,
)


@dataclass
class MappingMatch:
    """映射匹配结果"""
    mapping: NICMapping
    matched_nics: List[NICInfo] = field(default_factory=list)
    generated_rules: List[NICRenameRule] = field(default_factory=list)


class NICMapper:
    """网卡映射解析器

    解析配置并生成具体的设备重命名规则，支持非连续映射
    """

    def __init__(self, config: Optional[NICRenameConfig] = None):
        self.config = config or NICRenameConfig()
        self._matches: List[MappingMatch] = []

    def generate_rules(
        self,
        topology: NetworkTopology,
        config: Optional[NICRenameConfig] = None
    ) -> List[NICRenameRule]:
        """根据拓扑和配置生成重命名规则"""
        if config:
            self.config = config

        if not self.config.enabled:
            return []

        rules = []
        self._matches = []

        # 获取所有网卡
        all_nics = self._get_all_nics(topology)

        # 按映射顺序处理
        for mapping in self.config.mappings:
            if not mapping.enabled:
                continue

            match = MappingMatch(mapping=mapping)

            # 找到匹配的网卡
            matched_nics = self._find_matching_nics(all_nics, mapping)
            match.matched_nics = matched_nics

            # 生成规则
            generated_rules = self._generate_rules_for_mapping(matched_nics, mapping)
            match.generated_rules = generated_rules

            rules.extend(generated_rules)
            self._matches.append(match)

        return rules

    def _get_all_nics(self, topology: NetworkTopology) -> List[NICInfo]:
        """获取拓扑中的所有网卡"""
        return topology.rdma_nics + topology.ethernet_nics

    def _find_matching_nics(
        self,
        nics: List[NICInfo],
        mapping: NICMapping
    ) -> List[NICInfo]:
        """找到匹配映射模式的网卡"""
        matched = []

        for nic in nics:
            # 检查类型匹配
            if nic.nic_type != mapping.nic_type:
                continue

            # 检查名称模式匹配
            if not self._match_pattern(nic.name, mapping.source_pattern):
                continue

            # 检查条件匹配
            if mapping.condition and not self._check_conditions(nic, mapping.condition):
                continue

            matched.append(nic)

        # 按名称排序以确保一致的映射顺序
        matched.sort(key=lambda n: n.name)

        return matched

    def _match_pattern(self, name: str, pattern: str) -> bool:
        """匹配名称模式

        支持:
        - 通配符: * 匹配任意字符
        - 正则表达式: 如果以 ^ 开头，则作为正则处理
        """
        if pattern.startswith("^"):
            # 正则表达式
            try:
                return bool(re.match(pattern, name))
            except re.error:
                return False
        else:
            # glob模式
            return fnmatch(name, pattern)

    def _check_conditions(self, nic: NICInfo, conditions: Dict[str, Any]) -> bool:
        """检查网卡是否满足条件"""
        for key, value in conditions.items():
            nic_value = getattr(nic, key, None)

            if nic_value is None:
                return False

            # 支持列表值（任一匹配即可）
            if isinstance(value, list):
                if nic_value not in value:
                    return False
            elif nic_value != value:
                return False

        return True

    def _generate_rules_for_mapping(
        self,
        nics: List[NICInfo],
        mapping: NICMapping
    ) -> List[NICRenameRule]:
        """为匹配的网卡生成重命名规则"""
        rules = []

        for index, nic in enumerate(nics):
            # 生成目标名称
            new_name = self._generate_target_name(mapping.target_name, nic, index)

            rule = NICRenameRule(
                original_name=nic.name,
                new_name=new_name,
                nic_type=nic.nic_type,
                pci_address=nic.pci_address,
                mac_address=nic.mac_address,
            )

            rules.append(rule)

        return rules

    def _generate_target_name(self, template: str, nic: NICInfo, index: int) -> str:
        """根据模板生成目标名称

        支持的变量:
        - {index}: 从0开始的序号
        - {index1}: 从1开始的序号
        - {pci}: PCI地址（去掉冒号和点）
        - {mac}: MAC地址（去掉冒号）
        - {type}: 网卡类型 (rdma/eth)
        - {driver}: 驱动名称
        """
        name = template

        # 替换变量
        name = name.replace("{index}", str(index))
        name = name.replace("{index1}", str(index + 1))

        if "{pci}" in name and nic.pci_address:
            pci_clean = nic.pci_address.replace(":", "").replace(".", "")
            name = name.replace("{pci}", pci_clean)

        if "{mac}" in name and nic.mac_address:
            mac_clean = nic.mac_address.replace(":", "")
            name = name.replace("{mac}", mac_clean)

        name = name.replace("{type}", nic.nic_type.value)
        name = name.replace("{driver}", nic.driver or "")

        return name

    def get_matches(self) -> List[MappingMatch]:
        """获取所有匹配结果"""
        return self._matches

    def preview(self, topology: NetworkTopology) -> Dict[str, Any]:
        """预览映射结果（不执行）"""
        rules = self.generate_rules(topology)

        return {
            "enabled": self.config.enabled,
            "total_mappings": len(self.config.mappings),
            "active_mappings": sum(1 for m in self.config.mappings if m.enabled),
            "total_rules": len(rules),
            "rules": [r.to_dict() for r in rules],
            "matches": [
                {
                    "pattern": m.mapping.source_pattern,
                    "target_template": m.mapping.target_name,
                    "matched_count": len(m.matched_nics),
                    "matched_names": [n.name for n in m.matched_nics],
                }
                for m in self._matches
            ],
        }


class NonContiguousMapper(NICMapper):
    """非连续映射器

    支持非连续设备号的映射，例如:
    - mlx5_0 -> rdma0
    - mlx5_2 -> rdma1 (跳过mlx5_1)
    """

    def __init__(self, config: Optional[NICRenameConfig] = None):
        super().__init__(config)
        self._index_map: Dict[str, int] = {}

    def generate_rules(
        self,
        topology: NetworkTopology,
        config: Optional[NICRenameConfig] = None
    ) -> List[NICRenameRule]:
        """生成非连续映射规则"""
        # 重置索引映射
        self._index_map = {}

        return super().generate_rules(topology, config)

    def _generate_target_name(self, template: str, nic: NICInfo, index: int) -> str:
        """生成目标名称，使用连续索引"""
        # 为每个映射类型维护独立的索引
        mapping_key = f"{nic.nic_type.value}_{template}"

        if mapping_key not in self._index_map:
            self._index_map[mapping_key] = 0

        continuous_index = self._index_map[mapping_key]
        self._index_map[mapping_key] += 1

        name = template

        # 替换变量
        name = name.replace("{index}", str(continuous_index))
        name = name.replace("{index1}", str(continuous_index + 1))

        if "{pci}" in name and nic.pci_address:
            pci_clean = nic.pci_address.replace(":", "").replace(".", "")
            name = name.replace("{pci}", pci_clean)

        if "{mac}" in name and nic.mac_address:
            mac_clean = nic.mac_address.replace(":", "")
            name = name.replace("{mac}", mac_clean)

        name = name.replace("{type}", nic.nic_type.value)
        name = name.replace("{driver}", nic.driver or "")

        return name


class SelectiveMapper(NICMapper):
    """选择性映射器

    支持选择性配置特定网卡的重命名，可以:
    - 只重命名指定的网卡
    - 跳过指定的网卡
    """

    def __init__(self, config: Optional[NICRenameConfig] = None):
        super().__init__(config)
        self.include_patterns: List[str] = []
        self.exclude_patterns: List[str] = []

    def set_include_patterns(self, patterns: List[str]):
        """设置包含模式列表"""
        self.include_patterns = patterns

    def set_exclude_patterns(self, patterns: List[str]):
        """设置排除模式列表"""
        self.exclude_patterns = patterns

    def _find_matching_nics(
        self,
        nics: List[NICInfo],
        mapping: NICMapping
    ) -> List[NICInfo]:
        """找到匹配的网卡，应用包含/排除规则"""
        # 首先获取基本匹配
        matched = super()._find_matching_nics(nics, mapping)

        # 应用包含规则
        if self.include_patterns:
            matched = [
                nic for nic in matched
                if any(self._match_pattern(nic.name, p) for p in self.include_patterns)
            ]

        # 应用排除规则
        if self.exclude_patterns:
            matched = [
                nic for nic in matched
                if not any(self._match_pattern(nic.name, p) for p in self.exclude_patterns)
            ]

        return matched


def create_mapper(
    config: Optional[NICRenameConfig] = None,
    mapper_type: str = "default"
) -> NICMapper:
    """创建映射器工厂函数"""
    if mapper_type == "non_contiguous":
        return NonContiguousMapper(config)
    elif mapper_type == "selective":
        return SelectiveMapper(config)
    else:
        return NICMapper(config)
