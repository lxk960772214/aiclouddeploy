"""
步骤44: GPU Burn 性能稳定性测试

编译并运行GPU Burn测试，验证GPU性能和稳定性
"""

import os
from typing import List, Optional
from src.steps.base import BaseStep, StepResult, StepStatus


class GPUBurnTest(BaseStep):
    """GPU Burn性能稳定性测试"""

    step_id = "44"
    step_name = "GPU Burn测试"
    step_description = "编译并运行GPU Burn测试，验证GPU性能和稳定性"
    requires_sudo = False
    supports_batch = True
    timeout = 900  # 15分钟（包含600秒测试时间）

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

    def _get_log_dir(self) -> str:
        """获取编译日志目录"""
        if hasattr(self, 'versions') and self.versions and hasattr(self.versions, 'test_packages'):
            return self.versions.test_packages.log_dir
        return "/opt/gpu-test/logs"

    def _get_gpuburn_duration(self) -> int:
        """获取GPU Burn测试时长"""
        if hasattr(self, 'versions') and self.versions and hasattr(self.versions, 'test_packages'):
            return self.versions.test_packages.gpuburn_duration
        return 600

    def _get_compile_jobs_arg(self) -> str:
        """获取编译并行参数，-jN 或 -j$(nproc)"""
        if hasattr(self, 'versions') and self.versions and hasattr(self.versions, 'test_packages'):
            config = self.versions.test_packages
            if config.compile_jobs:
                return f"-j{config.compile_jobs}"
        return "-j$(nproc)"
        return 600

    def _get_cuda_version(self, host: str) -> Optional[str]:
        """获取CUDA版本"""
        version_cmd = "nvcc --version | grep release | awk '{print $5}' | cut -d',' -f1"
        result = self.execute_on_host(host, version_cmd)
        if result.get("success"):
            return result.get("stdout", "").strip()
        return None

    def _get_compute_cap(self, host: str) -> Optional[int]:
        """获取GPU计算能力"""
        cap_cmd = "nvidia-smi --query-gpu=compute_cap --format=csv,noheader | head -1"
        result = self.execute_on_host(host, cap_cmd)
        if result.get("success"):
            cap_str = result.get("stdout", "").strip().replace(".", "")
            return int(cap_str) if cap_str.isdigit() else None
        return None

    def _get_gpu_count(self, host: str) -> int:
        """获取GPU数量"""
        count_cmd = "nvidia-smi --query-gpu=count --format=csv,noheader | head -1"
        result = self.execute_on_host(host, count_cmd)
        if result.get("success"):
            return int(result.get("stdout", "0").strip())
        return 0

    def _upload_and_build_gpuburn(self, host: str, compute_cap: int, cuda_version: str) -> bool:
        """上传并编译GPU Burn"""
        toolkit_dir = self._get_toolkit_dir()
        log_dir = self._get_log_dir()

        # 创建目录
        self.execute_on_host(host, f"mkdir -p {toolkit_dir} {log_dir}")

        # 获取本地包路径
        local_pkg = os.path.join(os.getcwd(), "packages", "gpu-burn-master.zip")
        if not os.path.exists(local_pkg):
            self.logger.error(f"[{host}] GPU Burn源码包不存在: {local_pkg}")
            return False

        # 检查是否已解压
        check_src_cmd = f"test -d {toolkit_dir}/gpu-burn-master && echo 'exists' || echo 'not_exists'"
        src_result = self.execute_on_host(host, check_src_cmd)

        if "not_exists" in src_result.get("stdout", ""):
            # 上传zip文件
            remote_zip = f"{toolkit_dir}/gpu-burn-master.zip"
            self.logger.info(f"[{host}] 上传GPU Burn源码...")
            upload_result = self.put_file([host], local_pkg, remote_zip)

            if not upload_result.get(host):
                self.logger.error(f"[{host}] 上传GPU Burn源码失败")
                return False

            # 解压
            self.logger.info(f"[{host}] 解压GPU Burn源码...")
            unzip_cmd = f"cd {toolkit_dir} && unzip -q gpu-burn-master.zip"
            unzip_result = self.execute_on_host(host, unzip_cmd)
            if not unzip_result.get("success"):
                self.logger.error(f"[{host}] 解压GPU Burn源码失败")
                return False

        # 修改Makefile
        self.logger.info(f"[{host}] 配置Makefile...")
        gpuburn_dir = f"{toolkit_dir}/gpu-burn-master"

        # 备份Makefile
        backup_cmd = f"cd {gpuburn_dir} && test -f Makefile_bk || cp Makefile Makefile_bk"
        self.execute_on_host(host, backup_cmd)

        # 修改CUDA路径
        sed_cuda = f"cd {gpuburn_dir} && sed -i 's|CUDAPATH ?= /usr|CUDAPATH ?= /usr/local/cuda|' Makefile"
        self.execute_on_host(host, sed_cuda)

        # 修改计算能力
        sed_compute = f"cd {gpuburn_dir} && sed -i 's|COMPUTE      ?= 75|COMPUTE      ?= {compute_cap}|' Makefile"
        self.execute_on_host(host, sed_compute)

        # 修改CUDA版本（补齐.0）
        cuda_version_full = cuda_version if cuda_version.count('.') >= 2 else f"{cuda_version}.0"
        sed_version = f"cd {gpuburn_dir} && sed -i 's|CUDA_VERSION ?= 11.8.0|CUDA_VERSION ?= {cuda_version_full}|' Makefile"
        self.execute_on_host(host, sed_version)

        # 清理并编译（日志输出到文件）
        self.logger.info(f"[{host}] 编译GPU Burn...")
        clean_cmd = f"cd {gpuburn_dir} && make clean > /dev/null 2>&1 || true"
        self.execute_on_host(host, clean_cmd)

        compile_cmd = f"cd {gpuburn_dir} && make {self._get_compile_jobs_arg()} > {log_dir}/build_gpuburn.log 2>&1"
        compile_result = self.execute_on_host(host, compile_cmd, timeout=300)

        if not compile_result.get("success"):
            self.logger.error(f"[{host}] GPU Burn编译失败，日志: {log_dir}/build_gpuburn.log")
            return False

        self.logger.info(f"[{host}] GPU Burn编译完成")
        return True

    def is_configured(self, host: str) -> tuple:
        """检查gpu-burn工具是否存在"""
        toolkit_dir = self._get_toolkit_dir()
        check_cmd = f"test -f {toolkit_dir}/gpu-burn-master/gpu_burn && echo 'exists' || echo 'not_exists'"
        result = self.execute_on_host(host, check_cmd)
        if result.get("stdout", "").strip() == "exists":
            return True, "GPU Burn工具已编译"
        return False, "GPU Burn工具未编译"

    def execute(self, hosts: List[str]) -> StepResult:
        """执行GPU Burn测试"""
        results = {}
        toolkit_dir = self._get_toolkit_dir()
        result_dir = self._get_result_dir()
        duration = self._get_gpuburn_duration()

        for host in hosts:
            self.logger.info(f"[{host}] 开始GPU Burn测试...")

            # 1. 获取GPU信息
            compute_cap = self._get_compute_cap(host)
            cuda_version = self._get_cuda_version(host)
            gpu_count = self._get_gpu_count(host)

            if not compute_cap or not cuda_version:
                results[host] = {"success": False, "error": "无法获取GPU/CUDA信息"}
                continue

            if gpu_count < 1:
                results[host] = {"success": False, "error": "未检测到GPU"}
                continue

            self.logger.info(f"[{host}] GPU: {gpu_count}, 计算能力: {compute_cap}, CUDA: {cuda_version}")

            # 2. 检查并编译GPU Burn（如果需要）
            check_cmd = f"test -f {toolkit_dir}/gpu-burn-master/gpu_burn && echo 'exists' || echo 'not_exists'"
            check_result = self.execute_on_host(host, check_cmd)

            if "not_exists" in check_result.get("stdout", ""):
                if not self._upload_and_build_gpuburn(host, compute_cap, cuda_version):
                    results[host] = {"success": False, "error": "GPU Burn编译失败"}
                    continue

            # 3. 运行测试
            self.execute_on_host(host, f"mkdir -p {result_dir}")

            hostname_cmd = "hostname"
            hostname_result = self.execute_on_host(host, hostname_cmd)
            hostname = hostname_result.get("stdout", host).strip()

            self.logger.info(f"[{host}] 运行GPU Burn测试 (时长: {duration}秒)...")
            test_cmd = f"cd {toolkit_dir}/gpu-burn-master && ./gpu_burn -tc {duration} > {result_dir}/gpuburn_{hostname}.log 2>&1"
            test_result = self.execute_on_host(host, test_cmd, timeout=duration + 300)

            if test_result.get("success"):
                # 读取结果摘要
                read_cmd = f"tail -20 {result_dir}/gpuburn_{hostname}.log"
                summary_result = self.execute_on_host(host, read_cmd)
                summary = summary_result.get("stdout", "")
                self.logger.info(f"[{host}] GPU Burn测试完成")
                results[host] = {"success": True, "duration": duration, "summary": summary}
            else:
                self.logger.error(f"[{host}] GPU Burn测试失败")
                results[host] = {"success": False, "error": "GPU Burn测试失败"}

        success_count = sum(1 for r in results.values() if r.get("success"))

        return StepResult(
            step_id=self.step_id,
            step_name=self.step_name,
            status=StepStatus.SUCCESS if success_count == len(hosts) else StepStatus.FAILED,
            message=f"GPU Burn测试完成，成功: {success_count}/{len(hosts)}",
            host_results=results
        )

    def post_check(self, hosts: List[str]) -> bool:
        """验证测试结果"""
        result_dir = self._get_result_dir()
        for host in hosts:
            check_cmd = f"test -f {result_dir}/gpuburn_*.log"
            result = self.execute_on_host(host, check_cmd)
            if not result.get("success"):
                return False
        return True