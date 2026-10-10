"""
步骤41: NCCL单机多卡通信测试

编译NCCL和NCCL-tests，测试单机多卡通信性能
支持单节点编译策略：只在第一个节点编译，其他节点直接使用共享工具目录中的工具
"""

import os
from typing import Dict, List, Optional, Tuple
from pathlib import Path
from src.steps.base import BaseStep, StepResult, StepStatus


class NCCLSingleNodeTest(BaseStep):
    """NCCL单机多卡通信测试"""

    step_id = "41"
    step_name = "NCCL单机多卡测试"
    step_description = "编译NCCL并测试单机多卡通信性能"
    requires_sudo = True
    supports_batch = True
    timeout = 1800  # 30分钟（包含编译时间）

    # 测试项目
    # TEST_ITEMS = ['all_reduce_perf', 'all_gather_perf', 'alltoall_perf']
    TEST_ITEMS = ['all_reduce_perf' ]


    def _get_test_config(self):
        """获取测试配置"""
        if hasattr(self, 'versions') and self.versions and hasattr(self.versions, 'test_packages'):
            return self.versions.test_packages
        return None

    def _get_build_dir(self) -> str:
        """获取本地编译目录"""
        config = self._get_test_config()
        if config:
            return config.build_dir
        return "/tmp/gpu-test-build"

    def _get_toolkit_dir(self) -> str:
        """获取共享工具目录"""
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

    def _get_log_dir(self) -> str:
        """获取编译日志目录"""
        config = self._get_test_config()
        if config:
            return config.log_dir
        return "/opt/gpu-test/logs"

    def _get_nccl_test_size(self) -> str:
        """获取NCCL测试数据大小"""
        config = self._get_test_config()
        if config:
            return config.nccl_test_size
        return "8G"

    def _get_package_path(self, config_key: str, default_filename: str) -> Optional[str]:
        """获取工具包的本地绝对路径

        Args:
            config_key: test_packages中的配置键名（如nccl, nccl_tests）
            default_filename: 默认文件名（配置中未指定时使用）

        Returns:
            本地包文件的绝对路径，如果找不到返回None
        """
        config = self._get_test_config()
        if config:
            pkg_value = getattr(config, config_key, None)
            if pkg_value:
                return pkg_value  # 已在配置加载时解析为绝对路径
        # 回退到默认路径
        return os.path.join(os.getcwd(), "packages", default_filename)

    def _get_compile_jobs_arg(self) -> str:
        """获取编译并行参数，-jN 或 -j$(nproc)"""
        config = self._get_test_config()
        if config and config.compile_jobs:
            return f"-j{config.compile_jobs}"
        return "-j$(nproc)"

    def is_configured(self, host: str) -> tuple:
        """测试步骤每次都应执行，不跳过

        编译阶段内部已有跳过逻辑（检查libnccl.so和all_reduce_perf是否存在），
        但测试本身必须每次运行以获取最新结果。
        """
        return False, "测试步骤需要执行"

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

    def _get_compute_cap(self, host: str) -> Optional[int]:
        """获取GPU计算能力"""
        cap_cmd = "nvidia-smi --query-gpu=compute_cap --format=csv,noheader 2>/dev/null | head -1"
        cap_result = self.execute_on_host(host, cap_cmd)
        if cap_result.get("success"):
            cap_str = cap_result.get("stdout", "").strip().replace(".", "")
            return int(cap_str) if cap_str.isdigit() else None
        return None

    def _get_gpu_count(self, host: str) -> int:
        """获取GPU数量"""
        count_cmd = "nvidia-smi --query-gpu=count --format=csv,noheader 2>/dev/null | head -1"
        result = self.execute_on_host(host, count_cmd)
        if result.get("success"):
            stdout = result.get("stdout", "0").strip()
            if stdout and stdout.isdigit():
                return int(stdout)
        return 0

    def _upload_and_unzip(self, host: str, local_path: str, toolkit_dir: str, zip_name: str) -> bool:
        """上传并解压工具包到共享工具目录"""
        # 创建目录
        self.execute_on_host(host, f"mkdir -p {toolkit_dir}")

        # 检查是否已存在
        check_cmd = f"test -d {toolkit_dir}/{zip_name.replace('.zip', '')} && echo 'exists' || echo 'not_exists'"
        check_result = self.execute_on_host(host, check_cmd)

        if check_result.get("stdout", "").strip() == "exists":
            self.logger.info(f"[{host}] {zip_name.replace('.zip', '')} 已存在，跳过解压")
            return True

        # 检查zip文件是否已上传
        remote_zip = f"{toolkit_dir}/{zip_name}"
        check_zip_cmd = f"test -f {remote_zip} && echo 'exists' || echo 'not_exists'"
        zip_result = self.execute_on_host(host, check_zip_cmd)

        if "not_exists" in zip_result.get("stdout", ""):
            # 上传zip文件
            self.logger.info(f"[{host}] 上传 {zip_name}...")
            upload_result = self.put_file([host], local_path, remote_zip)
            if not upload_result.get(host):
                self.logger.error(f"[{host}] 上传 {zip_name} 失败")
                return False

        # 解压到共享工具目录
        self.logger.info(f"[{host}] 解压 {zip_name}...")
        unzip_cmd = f"cd {toolkit_dir} && unzip -q {remote_zip}"
        unzip_result = self.execute_on_host(host, unzip_cmd, sudo=True)

        if not unzip_result.get("success"):
            self.logger.error(f"[{host}] 解压 {zip_name} 失败")
            return False

        return True

    def _build_nccl_local(self, host: str, compute_cap: int) -> bool:
        """编译NCCL，直接安装到toolkit_dir"""
        toolkit_dir = self._get_toolkit_dir()
        log_dir = self._get_log_dir()
        nccl_dir = f"{toolkit_dir}/nccl"
        cuda_home = self._get_cuda_home(host)

        # 创建目标目录和日志目录
        self.execute_on_host(host, f"mkdir -p {nccl_dir} {log_dir}")

        # 检查源码是否在共享工具目录
        src_dir = f"{toolkit_dir}/nccl-master"
        check_src_cmd = f"test -d {src_dir} && echo 'exists' || echo 'not_exists'"
        src_result = self.execute_on_host(host, check_src_cmd)

        if "not_exists" in src_result.get("stdout", ""):
            # 从配置获取NCCL包路径
            local_pkg = self._get_package_path("nccl", "nccl-master.zip")
            if not local_pkg or not os.path.exists(local_pkg):
                self.logger.error(f"[{host}] NCCL源码包不存在: {local_pkg}")
                return False
            if not self._upload_and_unzip(host, local_pkg, toolkit_dir, "nccl-master.zip"):
                return False

        # BUILDDIR直接指向toolkit_dir/nccl，编译产物直接到位
        self.logger.info(f"[{host}] 编译NCCL (计算能力: {compute_cap}, CUDA_HOME: {cuda_home})...")
        compile_cmd = f"cd {src_dir} && make {self._get_compile_jobs_arg()} src.build BUILDDIR={nccl_dir} CUDA_HOME={cuda_home} NVCC_GENCODE='-gencode=arch=compute_{compute_cap},code=sm_{compute_cap}' > {log_dir}/build_nccl_{host.replace('.', '_')}.log 2>&1"
        compile_result = self.execute_on_host(host, compile_cmd, sudo=True, timeout=1200)

        if not compile_result.get("success"):
            self.logger.error(f"[{host}] NCCL编译失败，日志: {log_dir}/build_nccl_{host.replace('.', '_')}.log")
            return False

        self.logger.info(f"[{host}] NCCL编译完成")
        return True

    def _build_nccl_tests_local(self, host: str) -> bool:
        """在本地编译目录编译NCCL-tests"""
        build_dir = self._get_build_dir()
        toolkit_dir = self._get_toolkit_dir()
        log_dir = self._get_log_dir()
        cuda_home = self._get_cuda_home(host)

        # 检查源码是否在共享工具目录
        src_dir = f"{toolkit_dir}/nccl-tests-master"
        check_src_cmd = f"test -d {src_dir} && echo 'exists' || echo 'not_exists'"
        src_result = self.execute_on_host(host, check_src_cmd)

        if "not_exists" in src_result.get("stdout", ""):
            local_pkg = self._get_package_path("nccl_tests", "nccl-tests-master.zip")
            if not local_pkg or not os.path.exists(local_pkg):
                self.logger.error(f"[{host}] NCCL-tests源码包不存在: {local_pkg}")
                return False
            if not self._upload_and_unzip(host, local_pkg, toolkit_dir, "nccl-tests-master.zip"):
                return False

        # 在本地目录编译（避免NFS冲突）
        self.logger.info(f"[{host}] 在本地目录编译NCCL-tests (CUDA_HOME: {cuda_home})...")
        compile_cmd = f"cd {src_dir} && make {self._get_compile_jobs_arg()} CUDA_HOME={cuda_home} NCCL_HOME={toolkit_dir}/nccl > {log_dir}/build_nccl_tests_{host.replace('.', '_')}.log 2>&1"
        compile_result = self.execute_on_host(host, compile_cmd, sudo=True, timeout=600)

        if not compile_result.get("success"):
            self.logger.error(f"[{host}] NCCL-tests编译失败，日志: {log_dir}/build_nccl_tests_{host.replace('.', '_')}.log")
            return False

        # NCCL-tests的build目录在源码目录下，已经是共享的
        self.logger.info(f"[{host}] NCCL-tests编译完成")
        return True

    def _get_gpu_hosts(self, hosts: List[str]) -> List[str]:
        """筛选有GPU的节点（排除跳转服务器等无GPU节点）"""
        gpu_hosts = []
        for host in hosts:
            gpu_count = self._get_gpu_count(host)
            if gpu_count > 0:
                gpu_hosts.append(host)
            else:
                self.logger.info(f"[{host}] 无GPU，跳过测试")
        return gpu_hosts

    def execute(self, hosts: List[str]) -> StepResult:
        """执行NCCL单机多卡测试"""
        results = {}
        toolkit_dir = self._get_toolkit_dir()
        result_dir = self._get_result_dir()

        # 筛选有GPU的节点
        gpu_hosts = self._get_gpu_hosts(hosts)
        if not gpu_hosts:
            return StepResult(
                step_id=self.step_id,
                step_name=self.step_name,
                status=StepStatus.SKIPPED,
                message="没有GPU节点，跳过测试"
            )

        # 根据编译策略确定编译节点（从GPU节点中筛选）
        compile_hosts = self._get_compile_hosts(gpu_hosts)
        self.logger.info(f"编译策略: {self._get_compile_strategy()}, 编译节点: {compile_hosts}")

        # 1. 在指定节点编译（串行，编译需要独占资源）
        compile_ok = True
        for host in compile_hosts:
            self.logger.info(f"[{host}] 开始编译NCCL和NCCL-tests...")

            # 获取GPU计算能力（用于编译）
            compute_cap = self._get_compute_cap(host)
            if not compute_cap:
                results[host] = {"success": False, "error": "无法获取GPU计算能力"}
                compile_ok = False
                continue

            self.logger.info(f"[{host}] 计算能力: {compute_cap}")

            # 检查是否已编译
            check_nccl_cmd = f"test -f {toolkit_dir}/nccl/lib/libnccl.so && echo 'exists' || echo 'not_exists'"
            nccl_result = self.execute_on_host(host, check_nccl_cmd)

            if "not_exists" in nccl_result.get("stdout", ""):
                if not self._build_nccl_local(host, compute_cap):
                    results[host] = {"success": False, "error": "NCCL编译失败"}
                    compile_ok = False
                    continue

            check_tests_cmd = f"test -f {toolkit_dir}/nccl-tests-master/build/all_reduce_perf && echo 'exists' || echo 'not_exists'"
            tests_result = self.execute_on_host(host, check_tests_cmd)

            if "not_exists" in tests_result.get("stdout", ""):
                if not self._build_nccl_tests_local(host):
                    results[host] = {"success": False, "error": "NCCL-tests编译失败"}
                    compile_ok = False
                    continue

            results[host] = {"success": True, "compiled": True}

        if not compile_ok:
            return StepResult(
                step_id=self.step_id,
                step_name=self.step_name,
                status=StepStatus.FAILED,
                message="编译失败",
                host_results=results
            )

        # 2. 所有GPU节点并行运行测试
        self.logger.info("编译完成，开始并行运行测试...")

        import concurrent.futures

        def run_test_on_host(host: str) -> Tuple[str, Dict]:
            """在单个节点运行NCCL测试"""
            gpu_count = self._get_gpu_count(host)

            if gpu_count < 1:
                return host, {"success": True, "skipped": True, "reason": "GPU数量不足"}

            self.logger.info(f"[{host}] GPU数量: {gpu_count}, 开始运行NCCL测试...")

            # 创建结果目录
            self.execute_on_host(host, f"mkdir -p {result_dir}")

            # 获取hostname
            hostname_result = self.execute_on_host(host, "hostname")
            hostname = hostname_result.get("stdout", host).strip()

            # 设置环境变量
            cuda_home = self._get_cuda_home(host)
            env_cmd = f"export LD_LIBRARY_PATH={toolkit_dir}/nccl/lib:{cuda_home}/lib64:$LD_LIBRARY_PATH"

            # 确定测试数据大小
            test_total = self._get_nccl_test_size()
            compute_cap = self._get_compute_cap(host)
            test_config = self._get_test_config()
            user_specified = test_config and test_config.nccl_test_size != "8G"
            if not user_specified and compute_cap and (compute_cap == 120 or compute_cap == 89):
                test_total = "2G"

            test_results = {}
            for test_item in self.TEST_ITEMS:
                self.logger.info(f"[{host}] 运行 {test_item} 测试...")
                test_cmd = f"{env_cmd} && {toolkit_dir}/nccl-tests-master/build/{test_item} -b 8 -e {test_total} -f 2 -g {gpu_count} > {result_dir}/{test_item}_{hostname}.log 2>&1"
                test_result = self.execute_on_host(host, test_cmd, timeout=300)

                if test_result.get("success"):
                    read_cmd = f"tail -20 {result_dir}/{test_item}_{hostname}.log"
                    summary_result = self.execute_on_host(host, read_cmd)
                    summary = summary_result.get("stdout", "")
                    self.logger.info(f"[{host}] {test_item} 测试完成")
                    test_results[test_item] = {"success": True, "summary": summary}
                else:
                    self.logger.error(f"[{host}] {test_item} 测试失败")
                    test_results[test_item] = {"success": False}

            return host, {"success": all(r.get("success") for r in test_results.values()),
                          "gpu_count": gpu_count, "tests": test_results}

        # 并行运行测试
        max_workers = getattr(self.config, 'deployment', None)
        max_workers = max_workers.max_workers if max_workers else 2
        max_workers = min(len(gpu_hosts), max_workers)
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(run_test_on_host, host): host for host in gpu_hosts}
            for future in concurrent.futures.as_completed(futures):
                host, result = future.result()
                results[host] = result

        success_count = sum(1 for r in results.values() if r.get("success"))

        return StepResult(
            step_id=self.step_id,
            step_name=self.step_name,
            status=StepStatus.SUCCESS if success_count == len(results) else StepStatus.FAILED,
            message=f"NCCL单机多卡测试完成，成功: {success_count}/{len(results)}",
            host_results=results
        )

    def post_check(self, hosts: List[str]) -> bool:
        """验证测试结果"""
        result_dir = self._get_result_dir()
        for host in hosts:
            # 用 ls + grep 而非 test -f，避免通配符展开 too many arguments
            check_cmd = f"ls {result_dir}/all_reduce_perf_*.log >/dev/null 2>&1"
            result = self.execute_on_host(host, check_cmd)
            if not result.get("success"):
                return False
        return True