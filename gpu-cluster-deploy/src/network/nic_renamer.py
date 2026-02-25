#!/usr/bin/env python3
"""
GPU Cluster Deploy - 网卡重命名器
执行RDMA和以太网设备的选择性重命名操作
"""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, List, Dict, Any, Callable

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.models.network import (
    NICInfo,
    NICType,
    NICRenameRule,
    NICRenameConfig,
    NICRenameResult,
    NetworkTopology,
)
from src.network.nic_mapper import NICMapper, create_mapper


@dataclass
class RenameExecution:
    """重命名执行结果"""
    rule: NICRenameRule
    success: bool = False
    error: Optional[str] = None
    output: Optional[str] = None
    rollback_command: Optional[str] = None


class NICRenamer:
    """网卡重命名器

    执行RDMA和以太网设备的选择性重命名操作
    """

    def __init__(self, config: Optional[NICRenameConfig] = None):
        self.config = config or NICRenameConfig()
        self.mapper = create_mapper(config, mapper_type="non_contiguous")
        self._results: List[RenameExecution] = []

        # 回调函数
        self._on_rename_start: Optional[Callable] = None
        self._on_rename_complete: Optional[Callable] = None

    def set_callbacks(
        self,
        on_rename_start: Optional[Callable] = None,
        on_rename_complete: Optional[Callable] = None
    ):
        """设置回调函数"""
        self._on_rename_start = on_rename_start
        self._on_rename_complete = on_rename_complete

    def plan(
        self,
        topology: NetworkTopology,
        config: Optional[NICRenameConfig] = None
    ) -> List[NICRenameRule]:
        """规划重命名操作（不执行）"""
        if config:
            self.config = config
            self.mapper = create_mapper(config, mapper_type="non_contiguous")

        return self.mapper.generate_rules(topology, config)

    def execute(
        self,
        topology: NetworkTopology,
        ssh_executor: Optional[Any] = None,
        host: Optional[str] = None,
        config: Optional[NICRenameConfig] = None
    ) -> NICRenameResult:
        """执行重命名操作"""
        if config:
            self.config = config

        # 生成规则
        rules = self.plan(topology, config)
        self._results = []

        result = NICRenameResult(
            node_hostname=topology.node_hostname,
            rules=rules,
        )

        if not rules:
            result.success = True
            return result

        # 检查dry_run模式
        if self.config.dry_run:
            result.success = True
            return result

        try:
            # 执行每个规则
            for rule in rules:
                execution = self._execute_rule(rule, ssh_executor, host)
                self._results.append(execution)

                # 更新规则状态
                rule.executed = True
                rule.success = execution.success
                rule.error = execution.error

            # 计算整体结果
            result.success = all(e.success for e in self._results)

        except Exception as e:
            result.error = str(e)
            result.success = False

        return result

    def _execute_rule(
        self,
        rule: NICRenameRule,
        ssh_executor: Optional[Any],
        host: Optional[str]
    ) -> RenameExecution:
        """执行单个重命名规则"""
        execution = RenameExecution(rule=rule)

        try:
            # 回调
            if self._on_rename_start:
                self._on_rename_start(rule)

            # 检查目标名称是否已存在
            if self.config.skip_if_exists:
                if self._check_name_exists(rule.new_name, ssh_executor, host):
                    execution.success = True
                    execution.output = f"Skipped: {rule.new_name} already exists"
                    return execution

            # 创建udev规则
            if self.config.create_udev_rules:
                udev_result = self._create_udev_rule(rule, ssh_executor, host)
                if not udev_result["success"]:
                    execution.error = udev_result["error"]
                    execution.success = False
                    return execution

            # 执行ip link命令（临时重命名）
            if ssh_executor:
                cmd = self._build_rename_command(rule)
                result = ssh_executor.run_command(host, cmd)
                execution.output = result.get("output", "")
                execution.success = result.get("success", False)

                if not execution.success:
                    execution.error = result.get("error", "Command failed")
            else:
                # 本地执行（用于测试）
                execution.success = True
                execution.output = f"Would rename {rule.original_name} to {rule.new_name}"

            # 回调
            if self._on_rename_complete:
                self._on_rename_complete(rule, execution.success)

        except Exception as e:
            execution.error = str(e)
            execution.success = False

        return execution

    def _check_name_exists(
        self,
        name: str,
        ssh_executor: Optional[Any],
        host: Optional[str]
    ) -> bool:
        """检查网卡名称是否已存在"""
        if ssh_executor:
            cmd = f"ip link show {name} 2>/dev/null"
            result = ssh_executor.run_command(host, cmd)
            return result.get("success", False)
        return False

    def _create_udev_rule(
        self,
        rule: NICRenameRule,
        ssh_executor: Optional[Any],
        host: Optional[str]
    ) -> Dict[str, Any]:
        """创建udev规则"""
        if not rule.pci_address:
            return {"success": False, "error": "No PCI address available"}

        # 生成udev规则内容
        udev_content = self._generate_udev_rule_content(rule)
        udev_path = "/etc/udev/rules.d/70-persistent-net.rules"

        if ssh_executor:
            # 写入udev规则文件
            cmd = f"echo '{udev_content}' >> {udev_path}"
            result = ssh_executor.run_command(host, cmd)

            if not result.get("success", False):
                return {"success": False, "error": "Failed to write udev rule"}

            # 重新加载udev规则
            ssh_executor.run_command(host, "udevadm control --reload-rules")
            ssh_executor.run_command(host, "udevadm trigger")

        return {"success": True}

    def _generate_udev_rule_content(self, rule: NICRenameRule) -> str:
        """生成udev规则内容"""
        # 根据PCI地址匹配
        pci_path = rule.pci_address.replace(":", "/")
        return f'SUBSYSTEM=="net", KERNELS=="{pci_path}", NAME="{rule.new_name}"'

    def _build_rename_command(self, rule: NICRenameRule) -> str:
        """构建重命名命令"""
        return f"ip link set {rule.original_name} down && ip link set {rule.original_name} name {rule.new_name} && ip link set {rule.new_name} up"

    def rollback(self, ssh_executor: Optional[Any] = None, host: Optional[str] = None) -> bool:
        """回滚重命名操作"""
        success = True

        for execution in reversed(self._results):
            if not execution.success:
                continue

            try:
                # 执行回滚命令
                if execution.rollback_command and ssh_executor:
                    result = ssh_executor.run_command(host, execution.rollback_command)
                    if not result.get("success", False):
                        success = False

            except Exception:
                success = False

        return success

    def get_results(self) -> List[RenameExecution]:
        """获取执行结果"""
        return self._results

    def generate_report(self) -> Dict[str, Any]:
        """生成执行报告"""
        total = len(self._results)
        successful = sum(1 for r in self._results if r.success)
        failed = total - successful

        return {
            "total_operations": total,
            "successful_operations": successful,
            "failed_operations": failed,
            "success_rate": (successful / total * 100) if total > 0 else 0,
            "operations": [
                {
                    "original_name": r.rule.original_name,
                    "new_name": r.rule.new_name,
                    "success": r.success,
                    "error": r.error,
                }
                for r in self._results
            ],
        }


class RDMARenamer(NICRenamer):
    """RDMA网卡重命名器

    专门处理RDMA设备 (mlx5_*) 的重命名
    """

    def __init__(self, config: Optional[NICRenameConfig] = None):
        super().__init__(config)
        self.rdma_prefix = "rdma"

    def _build_rename_command(self, rule: NICRenameRule) -> str:
        """构建RDMA重命名命令"""
        # RDMA设备需要特殊的处理
        return f"""
# Rename RDMA interface
ip link set {rule.original_name} down 2>/dev/null || true
ip link set {rule.original_name} name {rule.new_name} 2>/dev/null || true
ip link set {rule.new_name} up 2>/dev/null || true

# Update RDMA device name if applicable
if [ -d /sys/class/infiniband/{rule.original_name} ]; then
    echo '{rule.new_name}' > /sys/class/infiniband/{rule.original_name}/device/uevent 2>/dev/null || true
fi
"""

    def _generate_udev_rule_content(self, rule: NICRenameRule) -> str:
        """生成RDMA udev规则"""
        if rule.pci_address:
            pci_path = rule.pci_address.replace(":", "/")
            return f'SUBSYSTEM=="net", KERNELS=="{pci_path}", NAME="{rule.new_name}"'
        elif rule.mac_address:
            return f'SUBSYSTEM=="net", ATTR{{address}}=="{rule.mac_address}", NAME="{rule.new_name}"'
        else:
            return f'# Manual rule for {rule.original_name} -> {rule.new_name}\n# Please add PCI or MAC address'


class EthernetRenamer(NICRenamer):
    """以太网网卡重命名器

    专门处理以太网设备 (ens*) 的重命名
    """

    def __init__(self, config: Optional[NICRenameConfig] = None):
        super().__init__(config)
        self.ethernet_prefix = "eth"

    def _build_rename_command(self, rule: NICRenameRule) -> str:
        """构建以太网重命名命令"""
        return f"""
# Rename Ethernet interface
ip link set {rule.original_name} down 2>/dev/null || true
ip link set {rule.original_name} name {rule.new_name} 2>/dev/null || true
ip link set {rule.new_name} up 2>/dev/null || true
"""

    def _generate_udev_rule_content(self, rule: NICRenameRule) -> str:
        """生成以太网udev规则"""
        if rule.pci_address:
            pci_path = rule.pci_address.replace(":", "/")
            return f'SUBSYSTEM=="net", ACTION=="add", KERNELS=="{pci_path}", NAME="{rule.new_name}"'
        elif rule.mac_address:
            return f'SUBSYSTEM=="net", ACTION=="add", ATTR{{address}}=="{rule.mac_address}", NAME="{rule.new_name}"'
        else:
            return f'# Manual rule for {rule.original_name} -> {rule.new_name}\n# Please add PCI or MAC address'


def create_renamer(
    config: Optional[NICRenameConfig] = None,
    nic_type: NICType = NICType.UNKNOWN
) -> NICRenamer:
    """创建重命名器工厂函数"""
    if nic_type == NICType.RDMA:
        return RDMARenamer(config)
    elif nic_type == NICType.ETHERNET:
        return EthernetRenamer(config)
    else:
        return NICRenamer(config)
