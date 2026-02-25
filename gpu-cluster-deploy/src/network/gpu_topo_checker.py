"""
GPU拓扑检查器
检查GPU与RDMA设备的NUMA亲和性和拓扑一致性
"""

import re
from typing import List, Dict, Any, Optional, Callable
from dataclasses import dataclass, field

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from models.device_check import (
    GPUTopologyInfo, TopologyCheckResult, DeviceInfo, DeviceType
)


class GPUTopologyChecker:
    """GPU拓扑检查器"""

    def __init__(self, execute_func: Optional[Callable] = None):
        """
        初始化拓扑检查器

        Args:
            execute_func: 执行远程命令的函数
        """
        self.execute_func = execute_func

    def check_node_topology(self, hostname: str) -> TopologyCheckResult:
        """
        检查单个节点的GPU拓扑

        Args:
            hostname: 节点主机名

        Returns:
            TopologyCheckResult: 拓扑检查结果
        """
        result = TopologyCheckResult(hostname=hostname)

        try:
            # 获取GPU拓扑信息
            result.gpu_topologies = self._get_gpu_topologies(hostname)

            # 检查NUMA一致性
            result.numa_consistency, numa_issues = self._check_numa_consistency(result.gpu_topologies)
            result.issues.extend(numa_issues)

            # 检查NVLink连接
            nvlink_issues = self._check_nvlink_connections(hostname, result.gpu_topologies)
            result.issues.extend(nvlink_issues)

        except Exception as e:
            result.issues.append(f"GPU拓扑检查失败: {str(e)}")

        return result

    def _get_gpu_topologies(self, hostname: str) -> List[GPUTopologyInfo]:
        """获取GPU拓扑信息"""
        topologies = []

        # 使用nvidia-smi获取GPU信息
        gpu_result = self._execute(
            hostname,
            "nvidia-smi --query-gpu=index,name,pci.bus_id --format=csv,noheader 2>/dev/null || true"
        )

        if not gpu_result.get("success"):
            return topologies

        lines = gpu_result.get("stdout", "").strip().split("\n")

        for line in lines:
            if not line.strip():
                continue

            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 3:
                continue

            try:
                gpu_index = int(parts[0])
                gpu_name = parts[1]
                pci_address = parts[2]

                # 获取NUMA节点
                numa_node = self._get_gpu_numa_node(hostname, pci_address)

                # 获取连接的RDMA设备
                connected_rdma = self._get_connected_rdma(hostname, pci_address, numa_node)

                # 获取NVLink连接
                nvlink_connections = self._get_nvlink_connections(hostname, gpu_index)

                topology = GPUTopologyInfo(
                    gpu_index=gpu_index,
                    gpu_name=gpu_name,
                    pci_address=pci_address,
                    numa_node=numa_node,
                    connected_rdma=connected_rdma,
                    nvlink_connections=nvlink_connections
                )
                topologies.append(topology)

            except (ValueError, IndexError):
                continue

        return topologies

    def _get_gpu_numa_node(self, hostname: str, pci_address: str) -> int:
        """获取GPU的NUMA节点"""
        numa_result = self._execute(
            hostname,
            f"cat /sys/bus/pci/devices/{pci_address}/numa_node 2>/dev/null || echo -1"
        )

        if numa_result.get("success"):
            try:
                return int(numa_result.get("stdout", "-1").strip())
            except ValueError:
                return -1
        return -1

    def _get_connected_rdma(self, hostname: str, gpu_pci: str, gpu_numa: int) -> List[str]:
        """
        获取与GPU连接的RDMA设备

        基于NUMA亲和性判断GPU和RDMA设备的连接关系
        """
        connected = []

        # 获取所有RDMA设备
        rdma_result = self._execute(
            hostname,
            "ls -1 /sys/class/infiniband/ 2>/dev/null || true"
        )

        if not rdma_result.get("success"):
            return connected

        rdma_devices = rdma_result.get("stdout", "").strip().split("\n")
        rdma_devices = [d.strip() for d in rdma_devices if d.strip()]

        for rdma_name in rdma_devices:
            # 获取RDMA设备的PCI地址
            pci_result = self._execute(
                hostname,
                f"readlink -f /sys/class/infiniband/{rdma_name}/device 2>/dev/null | xargs basename 2>/dev/null || true"
            )

            if not pci_result.get("success"):
                continue

            rdma_pci = pci_result.get("stdout", "").strip()
            if not rdma_pci:
                continue

            # 获取RDMA设备的NUMA节点
            numa_result = self._execute(
                hostname,
                f"cat /sys/bus/pci/devices/{rdma_pci}/numa_node 2>/dev/null || echo -1"
            )

            if numa_result.get("success"):
                try:
                    rdma_numa = int(numa_result.get("stdout", "-1").strip())
                    # 如果NUMA节点相同且有效，则认为连接
                    if gpu_numa >= 0 and rdma_numa >= 0 and gpu_numa == rdma_numa:
                        connected.append(rdma_name)
                except ValueError:
                    pass

        return connected

    def _get_nvlink_connections(self, hostname: str, gpu_index: int) -> List[int]:
        """获取NVLink连接的GPU索引"""
        connections = []

        # 使用nvidia-smi获取NVLink状态
        nvlink_result = self._execute(
            hostname,
            f"nvidia-smi nvlink --status -i {gpu_index} 2>/dev/null || true"
        )

        if not nvlink_result.get("success"):
            return connections

        output = nvlink_result.get("stdout", "")

        # 解析NVLink连接
        # 典型格式: GPU 0: NVIDIA A100-SXM4-80GB (UUID: ...)
        #          Link 0: 25 GB/s to GPU 1
        pattern = re.compile(r'Link\s+\d+:\s+\d+\s+GB/s\s+to\s+GPU\s+(\d+)', re.IGNORECASE)

        for match in pattern.finditer(output):
            try:
                connected_gpu = int(match.group(1))
                if connected_gpu not in connections:
                    connections.append(connected_gpu)
            except ValueError:
                continue

        return connections

    def _check_numa_consistency(
        self,
        topologies: List[GPUTopologyInfo]
    ) -> tuple[bool, List[str]]:
        """
        检查NUMA一致性

        Returns:
            (是否一致, 问题列表)
        """
        issues = []

        if not topologies:
            return True, issues

        # 检查所有GPU是否在有效NUMA节点上
        invalid_numa_gpus = [
            t for t in topologies if t.numa_node < 0
        ]

        if invalid_numa_gpus:
            gpu_names = [f"GPU{t.gpu_index}" for t in invalid_numa_gpus]
            issues.append(f"以下GPU没有有效的NUMA节点: {', '.join(gpu_names)}")

        # 检查NUMA节点分布是否均匀
        numa_counts: Dict[int, int] = {}
        for t in topologies:
            if t.numa_node >= 0:
                numa_counts[t.numa_node] = numa_counts.get(t.numa_node, 0) + 1

        if numa_counts:
            counts = list(numa_counts.values())
            max_count = max(counts)
            min_count = min(counts)

            # 如果NUMA分布不均匀（差异超过1）
            if max_count - min_count > 1:
                issues.append(
                    f"GPU NUMA分布不均匀: {numa_counts}"
                )

        # 检查每个GPU是否有连接的RDMA设备
        gpus_without_rdma = [
            t for t in topologies
            if t.numa_node >= 0 and not t.connected_rdma
        ]

        if gpus_without_rdma:
            gpu_names = [f"GPU{t.gpu_index}" for t in gpus_without_rdma]
            issues.append(f"以下GPU没有同NUMA的RDMA设备: {', '.join(gpu_names)}")

        return len(issues) == 0, issues

    def _check_nvlink_connections(
        self,
        hostname: str,
        topologies: List[GPUTopologyInfo]
    ) -> List[str]:
        """检查NVLink连接"""
        issues = []

        if len(topologies) < 2:
            return issues

        # 检查NVLink连接的对称性
        for t in topologies:
            for connected_idx in t.nvlink_connections:
                # 检查连接的GPU是否也连接回来
                connected_gpu = next(
                    (gt for gt in topologies if gt.gpu_index == connected_idx),
                    None
                )

                if connected_gpu and t.gpu_index not in connected_gpu.nvlink_connections:
                    issues.append(
                        f"NVLink连接不对称: GPU{t.gpu_index} -> GPU{connected_idx} "
                        f"但GPU{connected_idx}没有连接到GPU{t.gpu_index}"
                    )

        # 检查是否所有GPU都有NVLink连接（多GPU系统）
        gpus_without_nvlink = [
            t for t in topologies if not t.nvlink_connections
        ]

        if gpus_without_nvlink and len(topologies) > 1:
            gpu_names = [f"GPU{t.gpu_index}" for t in gpus_without_nvlink]
            issues.append(f"以下GPU没有NVLink连接: {', '.join(gpu_names)}")

        return issues

    def _execute(self, hostname: str, command: str) -> Dict[str, Any]:
        """执行远程命令"""
        if self.execute_func:
            return self.execute_func(hostname, command)

        return {
            "success": False,
            "stdout": "",
            "stderr": "No execute function provided",
            "error": "No execute function provided"
        }

    def check_cluster_topology(
        self,
        hostnames: List[str]
    ) -> Dict[str, TopologyCheckResult]:
        """
        检查集群所有节点的GPU拓扑

        Args:
            hostnames: 节点主机名列表

        Returns:
            字典，key为主机名，value为拓扑检查结果
        """
        results = {}

        for hostname in hostnames:
            results[hostname] = self.check_node_topology(hostname)

        return results

    def compare_cluster_topology(
        self,
        hostnames: List[str]
    ) -> Dict[str, Any]:
        """
        比较集群各节点的GPU拓扑一致性

        Args:
            hostnames: 节点主机名列表

        Returns:
            比较结果
        """
        cluster_results = self.check_cluster_topology(hostnames)

        # 收集每个节点的GPU数量
        gpu_counts = {
            hostname: len(result.gpu_topologies)
            for hostname, result in cluster_results.items()
        }

        # 检查GPU数量是否一致
        counts = list(gpu_counts.values())
        consistent_gpu_count = len(set(counts)) == 1 if counts else True

        # 收集NUMA配置
        numa_configs = {}
        for hostname, result in cluster_results.items():
            numa_configs[hostname] = [
                t.numa_node for t in result.gpu_topologies
            ]

        # 检查NUMA配置是否一致
        numa_values = list(numa_configs.values())
        consistent_numa = all(config == numa_values[0] for config in numa_values) if numa_values else True

        # 收集所有问题
        all_issues = {}
        for hostname, result in cluster_results.items():
            if result.issues:
                all_issues[hostname] = result.issues

        return {
            "consistent_gpu_count": consistent_gpu_count,
            "consistent_numa": consistent_numa,
            "gpu_counts": gpu_counts,
            "numa_configs": numa_configs,
            "issues_by_node": all_issues,
            "total_issues": sum(len(issues) for issues in all_issues.values())
        }


def check_gpu_topology(
    hostname: str,
    execute_func: Callable
) -> TopologyCheckResult:
    """检查GPU拓扑的便捷函数"""
    checker = GPUTopologyChecker(execute_func=execute_func)
    return checker.check_node_topology(hostname)
