"""
步骤42: NCCL显卡两两配对测试

测试显卡之间的两两配对通信性能
"""

import os
from typing import List, Optional, Dict, Any
from src.steps.base import BaseStep, StepResult, StepStatus


class NCCLCardPairTest(BaseStep):
    """NCCL显卡两两配对测试"""

    step_id = "42"
    step_name = "NCCL显卡配对测试"
    step_description = "测试显卡之间的两两配对通信性能"
    requires_sudo = False
    supports_batch = True
    timeout = 600

    def _get_cuda_home(self, host: str) -> str:
        """获取CUDA安装路径，优先使用/usr/local/cuda符号链接，若无效则查找cuda-版本目录"""
        check_cmd = "test -d /usr/local/cuda/include && echo 'valid' || echo 'invalid'"
        result = self.execute_on_host(host, check_cmd)
        if result.get("stdout", "").strip() == "valid":
            return "/usr/local/cuda"
        find_cmd = "ls -d /usr/local/cuda-* 2>/dev/null | sort -V | tail -1"
        find_result = self.execute_on_host(host, find_cmd)
        cuda_path = find_result.get("stdout", "").strip()
        if cuda_path:
            self.logger.info(f"[{host}] /usr/local/cuda 无效，使用 {cuda_path}")
            return cuda_path
        self.logger.warning(f"[{host}] 未找到有效的CUDA安装路径，使用默认 /usr/local/cuda")
        return "/usr/local/cuda"

    def _get_toolkit_dir(self) -> str:
        """获取工具包目录路径"""
        if hasattr(self, 'versions') and self.versions and hasattr(self.versions, 'test_packages'):
            return self.versions.test_packages.toolkit_dir
        return "/opt/gpu-test/toolkit"

    def _get_result_dir(self) -> str:
        """获取测试结果目录"""
        if hasattr(self, 'versions') and self.versions and hasattr(self.versions, 'test_packages'):
            return self.versions.test_packages.result_dir
        return "/opt/gpu-test/result"

    def is_configured(self, host: str) -> tuple:
        """检查测试工具是否存在"""
        toolkit_dir = self._get_toolkit_dir()
        check_cmd = f"test -f {toolkit_dir}/nccl-tests-master/build/all_reduce_perf && echo 'exists' || echo 'not_exists'"
        result = self.execute_on_host(host, check_cmd)
        if result.get("stdout", "").strip() == "exists":
            return True, "NCCL测试工具已存在"
        return False, "NCCL测试工具不存在"

    def _get_gpu_count(self, host: str) -> int:
        """获取GPU数量"""
        count_cmd = "nvidia-smi --query-gpu=count --format=csv,noheader | head -1"
        result = self.execute_on_host(host, count_cmd)
        if result.get("success"):
            return int(result.get("stdout", "0").strip())
        return 0

    def _run_test_on_host(self, host: str) -> Dict[str, Any]:
        """在单个节点运行显卡配对测试"""
        toolkit_dir = self._get_toolkit_dir()
        result_dir = self._get_result_dir()

        self.logger.info(f"[{host}] 开始NCCL显卡两两配对测试...")

        # 1. 获取GPU数量
        gpu_count = self._get_gpu_count(host)

        if gpu_count < 2:
            self.logger.warning(f"[{host}] GPU数量不足({gpu_count})，跳过测试")
            return {"success": True, "skipped": True, "reason": "GPU数量不足"}

        self.logger.info(f"[{host}] GPU数量: {gpu_count}")

        # 2. 检查测试工具
        check_cmd = f"test -f {toolkit_dir}/nccl-tests-master/build/all_reduce_perf && echo 'exists' || echo 'not_exists'"
        tool_result = self.execute_on_host(host, check_cmd)

        if tool_result.get("stdout", "").strip() == "not_exists":
            return {"success": False, "error": "NCCL-tests工具不存在，请先运行步骤41"}

        # 3. 创建结果目录
        self.execute_on_host(host, f"mkdir -p {result_dir}")

        # 4. 生成配对列表（相邻卡配对 + 首尾配对）
        pairs = []
        for i in range(gpu_count - 1):
            pairs.append(f"{i},{i+1}")
        pairs.append(f"{gpu_count-1},0")  # 首尾配对

        self.logger.info(f"[{host}] 测试配对: {pairs}")

        # 5. 设置环境变量
        cuda_home = self._get_cuda_home(host)
        env_cmd = f"export LD_LIBRARY_PATH={toolkit_dir}/nccl/lib:{cuda_home}/lib64:$LD_LIBRARY_PATH"

        test_results = {}
        hostname_cmd = "hostname"
        hostname_result = self.execute_on_host(host, hostname_cmd)
        hostname = hostname_result.get("stdout", host).strip()

        for pair in pairs:
            self.logger.info(f"[{host}] 测试配对 GPU {pair}...")

            # 使用CUDA_VISIBLE_DEVICES隔离测试GPU
            test_cmd = f"{env_cmd} && CUDA_VISIBLE_DEVICES={pair} {toolkit_dir}/nccl-tests-master/build/all_reduce_perf -b 8 -e 1G -f 2 -g 2 > {result_dir}/all_reduce_perf_pair_{pair}_{hostname}.log 2>&1"
            test_result = self.execute_on_host(host, test_cmd, timeout=60)

            if test_result.get("success"):
                # 读取结果摘要
                read_cmd = f"tail -5 {result_dir}/all_reduce_perf_pair_{pair}_{hostname}.log"
                summary_result = self.execute_on_host(host, read_cmd)
                summary = summary_result.get("stdout", "")
                self.logger.info(f"[{host}] GPU {pair} 测试完成")
                test_results[pair] = {"success": True, "summary": summary}
            else:
                self.logger.error(f"[{host}] GPU {pair} 测试失败")
                test_results[pair] = {"success": False}

        return {"success": True, "gpu_count": gpu_count, "pairs": test_results}

    def execute(self, hosts: List[str]) -> StepResult:
        """执行显卡两两配对测试"""
        # 筛选有GPU的节点
        gpu_hosts = self._get_gpu_hosts(hosts)
        if not gpu_hosts:
            return StepResult(
                step_id=self.step_id,
                step_name=self.step_name,
                status=StepStatus.SKIPPED,
                message="没有GPU节点，跳过测试"
            )

        # 并行运行测试
        self.logger.info("开始并行运行NCCL显卡配对测试...")
        results = self._run_on_hosts_parallel(gpu_hosts, self._run_test_on_host)

        success_count = sum(1 for r in results.values() if r.get("success"))

        return StepResult(
            step_id=self.step_id,
            step_name=self.step_name,
            status=StepStatus.SUCCESS if success_count == len(results) else StepStatus.FAILED,
            message=f"NCCL显卡配对测试完成，成功: {success_count}/{len(results)}",
            host_results=results
        )

    def post_check(self, hosts: List[str]) -> bool:
        """验证测试结果"""
        result_dir = self._get_result_dir()
        for host in hosts:
            check_cmd = f"ls {result_dir}/all_reduce_perf_pair_*_*.log 2>/dev/null | wc -l | grep -q '[1-9]'"
            result = self.execute_on_host(host, check_cmd)
            if not result.get("success"):
                return False
        return True
