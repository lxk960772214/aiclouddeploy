"""
步骤44: GPU Burn 性能稳定性测试

编译并运行GPU Burn测试，验证GPU性能和稳定性
"""

import os
from typing import List, Optional, Dict, Any
from src.steps.base import BaseStep, StepResult, StepStatus


class GPUBurnTest(BaseStep):
    """GPU Burn性能稳定性测试"""

    step_id = "44"
    step_name = "GPU Burn测试"
    step_description = "编译并运行GPU Burn测试，验证GPU性能和稳定性"
    requires_sudo = False
    supports_batch = True
    skip_if_configured = False  # 压测步骤: 始终运行, 不因 gpu_burn 二进制存在而跳过
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

    def _get_cuda_version(self, host: str) -> Optional[str]:
        """获取CUDA版本（自动检查 /usr/local/cuda 目录，存在则使用其 nvcc）"""
        # 自动检测 nvcc 路径：优先 /usr/local/cuda/bin/nvcc，回退到 PATH 中的 nvcc
        version_cmd = (
            "NVCC=$(test -x /usr/local/cuda/bin/nvcc && echo /usr/local/cuda/bin/nvcc || command -v nvcc); "
            "[ -n \"$NVCC\" ] && $NVCC --version | grep release | awk '{print $5}' | cut -d',' -f1"
        )
        result = self.execute_on_host(host, version_cmd)
        if result.get("success"):
            version = result.get("stdout", "").strip()
            return version if version else None
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

    def _get_compile_hosts(self, hosts: List[str]) -> List[str]:
        """根据编译策略确定编译节点"""
        compile_strategy = "single_node"
        compile_role = "test_compile"
        if hasattr(self, 'versions') and self.versions and hasattr(self.versions, 'test_packages'):
            compile_strategy = self.versions.test_packages.compile_strategy
            compile_role = self.versions.test_packages.compile_role

        if compile_strategy == "local":
            return hosts
        elif compile_strategy == "single_node":
            return [hosts[0]] if hosts else []
        elif compile_strategy == "role_based":
            compile_hosts = []
            for host in hosts:
                node = self._get_node_config(host)
                if node and hasattr(node, 'roles') and compile_role in node.roles:
                    compile_hosts.append(host)
            if not compile_hosts and hosts:
                self.logger.warning(f"没有节点具有 '{compile_role}' 角色，使用第一个节点编译")
                compile_hosts = [hosts[0]]
            return compile_hosts
        else:
            return [hosts[0]] if hosts else []

    def _upload_and_build_gpuburn(self, host: str, compute_cap: int, cuda_version: str) -> bool:
        """上传并编译GPU Burn"""
        toolkit_dir = self._get_toolkit_dir()
        log_dir = self._get_log_dir()

        # 创建目录
        self.execute_on_host(host, f"mkdir -p {toolkit_dir} {log_dir}")

        # 获取本地包路径（已在配置加载时解析为绝对路径）
        local_pkg = self._get_package_path("gpu_burn", "gpu-burn-master.zip")
        if not local_pkg or not os.path.exists(local_pkg):
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

        # 保证幂等：若存在备份则从备份恢复干净Makefile，否则首次备份
        backup_cmd = f"cd {gpuburn_dir} && test -f Makefile_bk && cp -f Makefile_bk Makefile || cp Makefile Makefile_bk"
        self.execute_on_host(host, backup_cmd)

        # Makefile 已内置 CUDAPATH 自动检测（/usr 或 /usr/local/cuda），无需修改

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

        compile_cmd = f"cd {gpuburn_dir} && make > {log_dir}/build_gpuburn.log 2>&1"
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

    def _get_package_path(self, config_key: str, default_filename: str) -> Optional[str]:
        """获取工具包的本地绝对路径"""
        if hasattr(self, 'versions') and self.versions and hasattr(self.versions, 'test_packages'):
            config = self.versions.test_packages
            pkg_value = getattr(config, config_key, None)
            if pkg_value:
                return pkg_value
        return os.path.join(os.getcwd(), "packages", default_filename)

    def _run_test_on_host(self, host: str) -> Dict[str, Any]:
        """在单个节点运行GPU Burn测试"""
        toolkit_dir = self._get_toolkit_dir()
        result_dir = self._get_result_dir()
        duration = self._get_gpuburn_duration()

        self.logger.info(f"[{host}] 开始GPU Burn测试...")

        # 1. 获取GPU信息
        compute_cap = self._get_compute_cap(host)
        cuda_version = self._get_cuda_version(host)
        gpu_count = self._get_gpu_count(host)

        if not compute_cap or not cuda_version:
            return {"success": False, "error": "无法获取GPU/CUDA信息"}

        if gpu_count < 1:
            return {"success": False, "error": "未检测到GPU"}

        self.logger.info(f"[{host}] GPU: {gpu_count}, 计算能力: {compute_cap}, CUDA: {cuda_version}")

        # 2. 检查并编译GPU Burn（如果需要）
        check_cmd = f"test -f {toolkit_dir}/gpu-burn-master/gpu_burn && echo 'exists' || echo 'not_exists'"
        check_result = self.execute_on_host(host, check_cmd)

        if "not_exists" in check_result.get("stdout", ""):
            if not self._upload_and_build_gpuburn(host, compute_cap, cuda_version):
                return {"success": False, "error": "GPU Burn编译失败"}

        # 3. 运行测试
        self.execute_on_host(host, f"mkdir -p {result_dir}")

        hostname_cmd = "hostname"
        hostname_result = self.execute_on_host(host, hostname_cmd)
        hostname = hostname_result.get("stdout", host).strip()

        self.logger.info(f"[{host}] 运行GPU Burn Tensor Core压测 (时长: {duration}秒)...")
        test_cmd = f"cd {toolkit_dir}/gpu-burn-master && ./gpu_burn -tc {duration} > {result_dir}/gpuburn_{hostname}.log 2>&1"
        test_result = self.execute_on_host(host, test_cmd, timeout=duration + 300)

        if test_result.get("success"):
            # 读取结果摘要
            read_cmd = f"tail -20 {result_dir}/gpuburn_{hostname}.log"
            summary_result = self.execute_on_host(host, read_cmd)
            summary = summary_result.get("stdout", "")
            self.logger.info(f"[{host}] GPU Burn测试完成")
            return {"success": True, "duration": duration, "summary": summary}
        else:
            self.logger.error(f"[{host}] GPU Burn测试失败")
            return {"success": False, "error": "GPU Burn测试失败"}

    def execute(self, hosts: List[str]) -> StepResult:
        """执行GPU Burn测试"""
        # 筛选有GPU的节点
        gpu_hosts = self._get_gpu_hosts(hosts)
        if not gpu_hosts:
            return StepResult(
                step_id=self.step_id,
                step_name=self.step_name,
                status=StepStatus.SKIPPED,
                message="没有GPU节点，跳过测试"
            )

        # 先在编译节点编译（串行，编译需要独占资源）
        compile_hosts = self._get_compile_hosts(gpu_hosts)
        self.logger.info(f"编译节点: {compile_hosts}")

        compile_ok = True
        for host in compile_hosts:
            compute_cap = self._get_compute_cap(host)
            cuda_version = self._get_cuda_version(host)
            if not compute_cap or not cuda_version:
                self.logger.error(f"[{host}] 无法获取GPU/CUDA信息")
                compile_ok = False
                continue

            # 始终重新编译: 确保使用当前 toolkit (如新装的 cuda 13.0) 重新生成
            # compare.ptx, 避免旧 toolkit 编出的二进制残留导致 "unsupported toolchain"
            if not self._upload_and_build_gpuburn(host, compute_cap, cuda_version):
                compile_ok = False
                continue

        if not compile_ok:
            return StepResult(
                step_id=self.step_id,
                step_name=self.step_name,
                status=StepStatus.FAILED,
                message="GPU Burn编译失败"
            )

        # 所有GPU节点并行运行测试
        self.logger.info("编译完成，开始并行运行GPU Burn测试...")
        results = self._run_on_hosts_parallel(gpu_hosts, self._run_test_on_host)

        success_count = sum(1 for r in results.values() if r.get("success"))

        return StepResult(
            step_id=self.step_id,
            step_name=self.step_name,
            status=StepStatus.SUCCESS if success_count == len(results) else StepStatus.FAILED,
            message=f"GPU Burn测试完成，成功: {success_count}/{len(results)}",
            host_results=results
        )

    def post_check(self, hosts: List[str]) -> bool:
        """验证测试结果"""
        result_dir = self._get_result_dir()
        for host in hosts:
            check_cmd = f"ls {result_dir}/gpuburn_*.log >/dev/null 2>&1"
            result = self.execute_on_host(host, check_cmd)
            if not result.get("success"):
                return False
        return True
