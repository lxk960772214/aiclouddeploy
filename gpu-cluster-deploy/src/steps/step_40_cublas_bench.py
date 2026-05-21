"""
步骤40: CUBLAS Matmul 基准测试

测试每张GPU的CUBLAS矩阵乘法性能
"""

import os
from typing import List
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

    def _get_compile_strategy(self) -> str:
        """获取编译策略"""
        config = self._get_test_config()
        if config:
            return config.compile_strategy
        return "single_node"

    def _get_compile_role(self) -> str:
        """获取编译角色名称"""
        config = self._get_test_config()
        if config:
            return config.compile_role
        return "test_compile"

    def _get_compile_hosts(self, hosts: List[str]) -> List[str]:
        """根据编译策略确定哪些节点需要编译"""
        strategy = self._get_compile_strategy()

        if strategy == "local":
            return hosts
        elif strategy == "single_node":
            return [hosts[0]] if hosts else []
        elif strategy == "role_based":
            compile_role = self._get_compile_role()
            compile_hosts = []
            for host in hosts:
                node = self._get_node_config(host)
                if node and hasattr(node, 'roles') and compile_role in node.roles:
                    compile_hosts.append(host)
            if not compile_hosts and hosts:
                self.logger.warning(f"没有节点具有 '{compile_role}' 角色，使用第一个节点上传")
                compile_hosts = [hosts[0]]
            return compile_hosts
        else:
            return [hosts[0]] if hosts else []

    def is_configured(self, host: str) -> tuple:
        """检查测试工具是否存在"""
        toolkit_dir = self._get_toolkit_dir()
        check_cmd = f"test -f {toolkit_dir}/cublasMatmulBench && echo 'exists' || echo 'not_exists'"
        result = self.execute_on_host(host, check_cmd)
        if result.get("stdout", "").strip() == "exists":
            return True, "CUBLAS测试工具已存在"
        return False, "CUBLAS测试工具不存在"

    def _upload_cublas_tool(self, host: str) -> bool:
        """上传CUBLAS测试工具到远程节点"""
        toolkit_dir = self._get_toolkit_dir()
        config = self._get_test_config()

        # 获取本地包路径
        local_path = None
        if config and config.cublas_bench:
            pkg_dir = config.packages_dir
            if not os.path.isabs(pkg_dir):
                pkg_dir = os.path.join(os.getcwd(), pkg_dir)
            local_path = os.path.join(pkg_dir, config.cublas_bench)

        # 如果配置中没有指定，使用默认位置
        if not local_path or not os.path.exists(local_path):
            default_path = os.path.join(os.getcwd(), "packages", "cublasMatmulBench")
            if os.path.exists(default_path):
                local_path = default_path
            else:
                self.logger.error(f"未找到cublasMatmulBench工具，请检查packages目录")
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

    def execute(self, hosts: List[str]) -> StepResult:
        """执行CUBLAS基准测试"""
        results = {}
        toolkit_dir = self._get_toolkit_dir()
        result_dir = self._get_result_dir()

        # 根据编译策略确定上传节点
        upload_hosts = self._get_compile_hosts(hosts)
        self.logger.info(f"编译策略: {self._get_compile_strategy()}, 上传节点: {upload_hosts}")

        for host in upload_hosts:
            check_tool_cmd = f"test -f {toolkit_dir}/cublasMatmulBench && echo 'exists' || echo 'not_exists'"
            tool_result = self.execute_on_host(host, check_tool_cmd)
            if "not_exists" in tool_result.get("stdout", ""):
                if not self._upload_cublas_tool(host):
                    results[host] = {"success": False, "error": "cublasMatmulBench工具上传失败"}
                    continue

        # 所有节点运行测试
        for host in hosts:
            self.logger.info(f"[{host}] 开始CUBLAS基准测试...")

            # 获取GPU数量
            gpu_count_cmd = "nvidia-smi --query-gpu=count --format=csv,noheader | head -1"
            gpu_result = self.execute_on_host(host, gpu_count_cmd)
            if not gpu_result.get("success"):
                results[host] = {"success": False, "error": "获取GPU数量失败"}
                continue

            gpu_count = int(gpu_result.get("stdout", "0").strip())
            self.logger.info(f"[{host}] GPU数量: {gpu_count}")

            # 创建结果目录
            self.execute_on_host(host, f"mkdir -p {result_dir}")

            # 运行测试
            test_results = []
            for gpu_id in range(gpu_count):
                self.logger.info(f"[{host}] 测试 GPU {gpu_id}...")

                env_cmd = f"export CUDA_VISIBLE_DEVICES={gpu_id} && export PATH=/usr/local/cuda/bin:$PATH && export LD_LIBRARY_PATH=/usr/local/cuda/lib64:$LD_LIBRARY_PATH"

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

            results[host] = {"success": True, "gpu_count": gpu_count, "results": test_results}

        success_count = sum(1 for r in results.values() if r.get("success"))

        return StepResult(
            step_id=self.step_id,
            step_name=self.step_name,
            status=StepStatus.SUCCESS if success_count == len(hosts) else StepStatus.FAILED,
            message=f"CUBLAS测试完成，成功: {success_count}/{len(hosts)}",
            host_results=results
        )

    def post_check(self, hosts: List[str]) -> bool:
        """验证测试结果"""
        result_dir = self._get_result_dir()
        for host in hosts:
            check_cmd = f"test -f {result_dir}/cublas_*.log"
            result = self.execute_on_host(host, check_cmd)
            if not result.get("success"):
                return False
        return True