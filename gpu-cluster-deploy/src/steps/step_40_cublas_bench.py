"""
步骤40: CUBLAS Matmul 基准测试

测试每张GPU的CUBLAS矩阵乘法性能
"""

import os
from typing import List, Optional, Dict, Any
from pathlib import Path
from src.steps.base import BaseStep, StepResult, StepStatus


class CUBLASBenchmark(BaseStep):
    """CUBLAS Matmul基准测试"""

    step_id = "40"
    step_name = "CUBLAS基准测试"
    step_description = "测试每张GPU的CUBLAS矩阵乘法性能"
    requires_sudo = False
    supports_batch = True
    timeout = 600  # 10分钟

    def _get_cuda_home(self, host: str) -> str:
        """获取CUDA安装路径，优先使用/usr/local/cuda符号链接，若无效则查找cuda-版本目录"""
        # 检查/usr/local/cuda是否是有效路径（非悬空符号链接）
        check_cmd = "test -d /usr/local/cuda/include && echo 'valid' || echo 'invalid'"
        result = self.execute_on_host(host, check_cmd)
        if result.get("stdout", "").strip() == "valid":
            return "/usr/local/cuda"
        # 查找/usr/local/cuda-*目录，取最新版本
        find_cmd = "ls -d /usr/local/cuda-* 2>/dev/null | sort -V | tail -1"
        find_result = self.execute_on_host(host, find_cmd)
        cuda_path = find_result.get("stdout", "").strip()
        if cuda_path:
            self.logger.info(f"[{host}] /usr/local/cuda 无效，使用 {cuda_path}")
            return cuda_path
        # 回退到默认路径
        self.logger.warning(f"[{host}] 未找到有效的CUDA安装路径，使用默认 /usr/local/cuda")
        return "/usr/local/cuda"

    def _get_test_config(self):
        """获取测试配置"""
        if hasattr(self, 'versions') and self.versions and hasattr(self.versions, 'test_packages'):
            return self.versions.test_packages
        return None

    def _get_toolkit_dir(self) -> str:
        """获取工具包目录路径"""
        config = self._get_test_config()
        if config:
            return config.toolkit_dir
        return "/opt/gpu-test/toolkit"

    def _get_result_dir(self) -> str:
        """获取测试结果目录"""
        config = self._get_test_config()
        if config:
            return config.result_dir
        return "/opt/gpu-test/result"

    def is_configured(self, host: str) -> tuple:
        """检查测试工具是否存在"""
        toolkit_dir = self._get_toolkit_dir()
        check_cmd = f"test -f {toolkit_dir}/cublasMatmulBench && echo 'exists' || echo 'not_exists'"
        result = self.execute_on_host(host, check_cmd)
        if result.get("stdout", "").strip() == "exists":
            return True, "CUBLAS测试工具已存在"
        return False, "CUBLAS测试工具不存在"

    def _get_package_path(self, config_key: str, default_filename: str) -> Optional[str]:
        """获取工具包的本地绝对路径"""
        config = self._get_test_config()
        if config:
            pkg_value = getattr(config, config_key, None)
            if pkg_value:
                return pkg_value
        return os.path.join(os.getcwd(), "packages", default_filename)

    def _upload_cublas_tool(self, host: str) -> bool:
        """上传CUBLAS测试工具到远程节点"""
        toolkit_dir = self._get_toolkit_dir()

        # 获取本地包路径（已在配置加载时解析为绝对路径）
        local_path = self._get_package_path("cublas_bench", "cublasMatmulBench")

        if not local_path or not os.path.exists(local_path):
            self.logger.error(f"未找到cublasMatmulBench工具: {local_path}，请检查packages目录")
            return False

        self.logger.info(f"[{host}] 上传CUBLAS测试工具: {local_path}")

        # 创建目录
        mkdir_cmd = f"mkdir -p {toolkit_dir}"
        self.execute_on_host(host, mkdir_cmd)

        # 上传文件到共享工具目录
        remote_path = f"{toolkit_dir}/cublasMatmulBench"
        upload_results = self.put_file([host], local_path, remote_path)

        if not upload_results.get(host):
            self.logger.error(f"[{host}] 上传cublasMatmulBench失败")
            return False

        # 设置执行权限
        chmod_cmd = f"chmod +x {remote_path}"
        self.execute_on_host(host, chmod_cmd)

        self.logger.info(f"[{host}] CUBLAS测试工具上传成功")
        return True

    def _run_test_on_host(self, host: str) -> Dict[str, Any]:
        """在单个节点运行CUBLAS测试"""
        toolkit_dir = self._get_toolkit_dir()
        result_dir = self._get_result_dir()

        self.logger.info(f"[{host}] 开始CUBLAS基准测试...")

        # 获取GPU数量
        gpu_count_cmd = "nvidia-smi --query-gpu=count --format=csv,noheader | head -1"
        gpu_result = self.execute_on_host(host, gpu_count_cmd)
        if not gpu_result.get("success"):
            return {"success": False, "error": "获取GPU数量失败"}

        gpu_count = int(gpu_result.get("stdout", "0").strip())
        self.logger.info(f"[{host}] GPU数量: {gpu_count}")

        # 创建结果目录
        self.execute_on_host(host, f"mkdir -p {result_dir}")

        # 运行测试
        test_results = []
        for gpu_id in range(gpu_count):
            self.logger.info(f"[{host}] 测试 GPU {gpu_id}...")

            env_cmd = f"export CUDA_VISIBLE_DEVICES={gpu_id} && export PATH={self._get_cuda_home(host)}/bin:$PATH && export LD_LIBRARY_PATH={self._get_cuda_home(host)}/lib64:$LD_LIBRARY_PATH"

            test_items = [
                ("FP64", "-P=ddd -m=15360 -n=18176 -k=8192 -T=8"),
                ("FP32", "-P=sss -m=15360 -n=18176 -k=8192 -T=500"),
                ("TF32", "-P=sss_fast_tf32 -m=15360 -n=18176 -k=8192 -T=500"),
                ("FP16(hhh)", "-P=hhh -m=15360 -n=18176 -k=8192 -T=1000"),
                ("hsh", "-P=hsh -m=15360 -n=18176 -k=8192 -T=1000"),
                ("hss", "-P=hss -m=15360 -n=18176 -k=8192 -T=1000"),
                ("BF16", "-P=tst -m=15360 -n=18176 -k=8192 -T=1000"),
                ("FP8", "-P=qqssq -m=15360 -n=18176 -k=8192 -T=1000"),
            ]

            gpu_perf = {"gpu_id": gpu_id}
            for name, params in test_items:
                test_cmd = f"{env_cmd} && {toolkit_dir}/cublasMatmulBench {params} -ta=1 -B=0 -p=0 2>/dev/null | grep -i CUDA | awk '{{print $10}}'"
                perf_result = self.execute_on_host(host, test_cmd, timeout=120)
                perf_value = perf_result.get("stdout", "N/A").strip()
                gpu_perf[name] = perf_value

            test_results.append(gpu_perf)

        # 保存结果
        hostname_result = self.execute_on_host(host, "hostname")
        hostname = hostname_result.get("stdout", host).strip()

        result_lines = []
        for r in test_results:
            line = f"GPU {r['gpu_id']} | FP64: {r.get('FP64', 'N/A')} | FP32: {r.get('FP32', 'N/A')} | TF32: {r.get('TF32', 'N/A')} | FP16(hhh): {r.get('FP16(hhh)', 'N/A')} | hsh: {r.get('hsh', 'N/A')} | hss: {r.get('hss', 'N/A')} | BF16: {r.get('BF16', 'N/A')} | FP8: {r.get('FP8', 'N/A')}"
            result_lines.append(line)
            self.logger.info(f"[{host}] {line}")

        result_file = f"{result_dir}/cublas_{hostname}.log"
        write_cmd = f"cat > {result_file} << 'EOF'\n" + "\n".join(result_lines) + "\nEOF"
        self.execute_on_host(host, write_cmd)

        return {"success": True, "gpu_count": gpu_count, "results": test_results}

    def execute(self, hosts: List[str]) -> StepResult:
        """执行CUBLAS基准测试"""
        # 筛选有GPU的节点
        gpu_hosts = self._get_gpu_hosts(hosts)
        if not gpu_hosts:
            return StepResult(
                step_id=self.step_id,
                step_name=self.step_name,
                status=StepStatus.SKIPPED,
                message="没有GPU节点，跳过测试"
            )

        toolkit_dir = self._get_toolkit_dir()

        # 根据编译策略确定上传节点（串行上传）
        upload_hosts = self._get_compile_hosts(gpu_hosts)
        self.logger.info(f"编译策略: {self._get_compile_strategy()}, 上传节点: {upload_hosts}")

        for host in upload_hosts:
            check_tool_cmd = f"test -f {toolkit_dir}/cublasMatmulBench && echo 'exists' || echo 'not_exists'"
            tool_result = self.execute_on_host(host, check_tool_cmd)
            if "not_exists" in tool_result.get("stdout", ""):
                if not self._upload_cublas_tool(host):
                    return StepResult(
                        step_id=self.step_id,
                        step_name=self.step_name,
                        status=StepStatus.FAILED,
                        message="cublasMatmulBench工具上传失败"
                    )

        # 所有GPU节点并行运行测试
        self.logger.info("工具就绪，开始并行运行CUBLAS测试...")
        results = self._run_on_hosts_parallel(gpu_hosts, self._run_test_on_host)

        success_count = sum(1 for r in results.values() if r.get("success"))

        return StepResult(
            step_id=self.step_id,
            step_name=self.step_name,
            status=StepStatus.SUCCESS if success_count == len(results) else StepStatus.FAILED,
            message=f"CUBLAS测试完成，成功: {success_count}/{len(results)}",
            host_results=results
        )

    def post_check(self, hosts: List[str]) -> bool:
        """验证测试结果"""
        result_dir = self._get_result_dir()
        for host in hosts:
            check_cmd = f"ls {result_dir}/cublas_*.log >/dev/null 2>&1"
            result = self.execute_on_host(host, check_cmd)
            if not result.get("success"):
                return False
        return True
