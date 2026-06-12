"""
步骤24: 安装CUDA Toolkit

功能增强:
- 支持自动下载和分发安装包
- 智能检测已安装版本
- 跳过已安装相同版本
- 批量并行执行
"""

from typing import List, Optional, Tuple, Dict
from src.steps.base import BaseStep, StepResult, StepStatus
from concurrent.futures import ThreadPoolExecutor, as_completed
import time


class CUDAToolkit(BaseStep):
    """安装CUDA Toolkit"""

    step_id = "24"
    step_name = "安装CUDA Toolkit"
    step_description = "安装NVIDIA CUDA Toolkit（支持自动下载）"
    requires_sudo = True
    supports_batch = True  # 改为支持批量执行
    timeout = 2400  # 40分钟（下载+安装可能需要更长时间）

    def is_configured(self, host: str) -> tuple:
        """
        检查CUDA Toolkit是否已安装

        Args:
            host: 主机地址

        Returns:
            tuple[bool, str]: (是否已配置, 检查详情)
        """
        cuda_config = self.versions.cuda if hasattr(self, 'versions') and self.versions else None

        # 如果cuda配置的mode为keep，检查是否已有CUDA
        if cuda_config and getattr(cuda_config, 'mode', 'install') == "keep":
            result = self.execute_on_host(
                host, "/usr/local/cuda/bin/nvcc -V 2>/dev/null | grep 'release' | awk '{print $6}'",
                timeout=30
            )
            if result.get("success") and result.get("stdout", "").strip():
                return True, "CUDA已安装（keep模式）"
            # keep模式但没有安装，也返回True跳过安装
            return True, "CUDA未安装但keep模式跳过"

        # 检查 nvcc 命令获取版本
        result = self.execute_on_host(
            host, "/usr/local/cuda/bin/nvcc -V 2>/dev/null | grep 'release' | awk '{print $6}'",
            timeout=30
        )

        if result.get("success") and result.get("stdout", "").strip():
            stdout = result.get("stdout", "").strip()
            # 取第一行避免重复输出问题
            version_line = stdout.split('\n')[0].strip() if stdout else ""
            version = version_line.replace(",", "")

            # 检查版本是否匹配配置的目标版本
            target_version = getattr(cuda_config, 'version', None) if cuda_config else None
            if target_version:
                # 精确匹配版本号
                if version == target_version or target_version in version:
                    return True, f"CUDA已安装: {version}（匹配目标版本）"
                # 检查主版本是否匹配
                target_major = target_version.split('.')[0]
                current_major = version.split('.')[0] if version else ""
                if target_major == current_major:
                    return True, f"CUDA已安装: {version}（主版本匹配）"
                else:
                    return False, f"CUDA版本不匹配: 当前={version}, 目标={target_version}"

            return True, f"CUDA已安装: {version}"

        # 检查 /usr/local/cuda 符号链接
        result = self.execute_on_host(host, "ls -la /usr/local/cuda 2>/dev/null", timeout=30)
        if result.get("success") and "cuda" in result.get("stdout", ""):
            return True, "CUDA目录存在"

        return False, "CUDA未安装"

    def _prepare_package(self, hosts: List[str]) -> dict:
        """
        准备CUDA安装包

        Args:
            hosts: 目标主机列表

        Returns:
            dict: {host: file_path}
        """
        from src.package_manager import PackageManager, PackageConfig, PackageType

        cuda_config = self.versions.cuda

        # 创建包配置
        package = PackageConfig(
            name="cuda_toolkit",
            version=cuda_config.version,
            package_type=PackageType.CUDA_TOOLKIT,
            local_file=cuda_config.local_file,
            download_url=cuda_config.download_url,
            checksum=cuda_config.checksum,
            file_size=cuda_config.file_size,
        )

        # 创建包管理器（传递配置以获取认证信息）
        manager = PackageManager(
            ssh_manager=self.ssh_manager,
            config=self.config,
            logger=self.logger
        )

        # 准备安装包
        return manager.prepare_package(package, hosts, dest_path=f"/tmp/{package.filename}")

    def _detect_cuda_batch(self, hosts: List[str]) -> Dict[str, Tuple[bool, Optional[str]]]:
        """
        批量检测节点上是否已安装CUDA Toolkit

        Returns:
            Dict[str, Tuple[bool, Optional[str]]]: {host: (是否安装, 版本号)}
        """
        self.logger.info(f"[{self.step_id}] 批量检测CUDA安装状态...")
        results = {}

        def detect_single(host: str) -> Tuple[str, bool, Optional[str]]:
            # 方法1: 使用 nvcc 检测
            result = self.execute_on_host(
                host, "/usr/local/cuda/bin/nvcc -V 2>/dev/null | grep 'release' | awk '{print $6}'",
                timeout=30
            )
            if result.get("success") and result.get("stdout", "").strip():
                version = result["stdout"].strip().replace(",", "")
                return host, True, version

            # 方法2: 检查 /usr/local/cuda/version.txt
            result = self.execute_on_host(
                host, "cat /usr/local/cuda/version.txt 2>/dev/null | awk '{print $NF}'",
                timeout=30
            )
            if result.get("success") and result.get("stdout", "").strip():
                return host, True, result["stdout"].strip()

            # 方法3: 检查版本文件
            result = self.execute_on_host(
                host, "ls -d /usr/local/cuda-* 2>/dev/null | tail -1 | sed 's|.*/cuda-||'",
                timeout=30
            )
            if result.get("success") and result.get("stdout", "").strip():
                return host, True, result["stdout"].strip()

            return host, False, None

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = {executor.submit(detect_single, host): host for host in hosts}
            for future in as_completed(futures):
                host, has_cuda, version = future.result()
                results[host] = (has_cuda, version)
                if has_cuda:
                    self.logger.info(f"[{host}] 检测到CUDA版本: {version}")
                else:
                    self.logger.info(f"[{host}] 未检测到CUDA")

        return results

    def _uninstall_cuda_batch(self, hosts: List[str]) -> Dict[str, bool]:
        """批量卸载现有的CUDA Toolkit"""
        self.logger.info(f"[{self.step_id}] 批量卸载CUDA（{len(hosts)}个节点）...")
        results = {}

        uninstall_script = '''
# 1. 运行CUDA卸载工具（如果存在）
test -f /usr/local/cuda/bin/cuda-uninstaller && /usr/local/cuda/bin/cuda-uninstaller -s || true

# 2. 清理处于rc状态的cuda相关包（避免依赖解析失败）
dpkg --purge $(dpkg -l | grep -E '^rc.*cuda|^rc.*nvidia-cuda' | awk '{print $2}') 2>/dev/null || true

# 3. 清理apt安装的CUDA包
apt-get purge -y 'cuda*' 'libcuda*' 'nvidia-cuda*' 2>/dev/null || true

# 4. 清理残留文件
rm -rf /usr/local/cuda-* 2>/dev/null || true
rm -rf /usr/local/cuda 2>/dev/null || true
rm -f /etc/profile.d/cuda.sh 2>/dev/null || true

# 5. 清理环境变量
sed -i '/\\/usr\\/local\\/cuda/d' /etc/profile 2>/dev/null || true

echo "UNINSTALL_DONE"
'''

        summary = self.execute_batch(hosts, uninstall_script, sudo=True)

        for host, result in summary.results.items():
            results[host] = result.success and "UNINSTALL_DONE" in result.stdout
            if results[host]:
                self.logger.info(f"[{host}] CUDA卸载完成")
            else:
                self.logger.warning(f"[{host}] CUDA卸载可能未完全成功")

        return results

    def _install_deps_batch(self, hosts: List[str]) -> Dict[str, bool]:
        """批量安装依赖"""
        self.logger.info(f"[{self.step_id}] 批量安装依赖（{len(hosts)}个节点）...")

        deps_cmd = "apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y build-essential libglu1-mesa libxi-dev libxmu-dev libglu1-mesa-dev"
        summary = self.execute_batch(hosts, deps_cmd, sudo=True)

        results = {host: result.success for host, result in summary.results.items()}
        failed = [h for h, success in results.items() if not success]
        if failed:
            self.logger.warning(f"依赖安装失败的节点: {failed}")

        return results

    def _install_cuda_batch(self, hosts: List[str], package_paths: Dict[str, str], target_version: str) -> Dict[str, dict]:
        """批量安装CUDA Toolkit"""
        self.logger.info(f"[{self.step_id}] 批量安装CUDA {target_version}（{len(hosts)}个节点）...")
        results = {}

        def install_single(host: str) -> Tuple[str, dict]:
            toolkit_file = package_paths.get(host)
            if not toolkit_file:
                return host, {"success": False, "error": "CUDA安装文件不存在"}

            host_result = {"target_version": target_version}

            # 检查安装文件
            check_result = self.execute_on_host(host, f"test -f {toolkit_file} && echo 'exists' || echo 'not_found'")
            if "not_found" in check_result.get("stdout", ""):
                return host, {"success": False, "error": f"CUDA安装文件不存在: {toolkit_file}"}

            # 安装CUDA Toolkit
            self.logger.info(f"[{host}] 执行CUDA安装...")
            install_cmd = f"chmod +x {toolkit_file} && {toolkit_file} --toolkit --no-drm --silent"
            install_result = self.execute_on_host(host, install_cmd, sudo=True, timeout=1200)
            host_result["install"] = {"success": install_result.get("success"), "exit_code": install_result.get("exit_code")}

            if not install_result.get("success"):
                return host, {"success": False, "error": f"CUDA安装失败: {install_result.get('stderr', '未知错误')[:500]}"}

            # 创建符号链接
            version_parts = target_version.split('.')
            cuda_path = f"/usr/local/cuda-{version_parts[0]}.{version_parts[1]}"
            symlink_cmd = f"ln -sf {cuda_path} /usr/local/cuda"
            self.execute_on_host(host, symlink_cmd, sudo=True, timeout=30)

            # 配置环境变量
            env_cmd = '''
grep -q 'export PATH=/usr/local/cuda/bin' /etc/profile || echo "export PATH=/usr/local/cuda/bin:$PATH" >> /etc/profile
grep -q 'export LD_LIBRARY_PATH=/usr/local/cuda/lib64' /etc/profile || echo "export LD_LIBRARY_PATH=/usr/local/cuda/lib64:$LD_LIBRARY_PATH" >> /etc/profile
'''
            self.execute_on_host(host, env_cmd, sudo=True, timeout=30)

            # 验证安装
            verify_result = self.execute_on_host(host, "/usr/local/cuda/bin/nvcc -V", timeout=60)
            if verify_result.get("success") and version_parts[0] in verify_result.get("stdout", ""):
                self.logger.info(f"[{host}] CUDA安装成功，版本: {target_version}")
                return host, {"success": True, "installed_version": target_version, **host_result}
            else:
                return host, {"success": False, "error": "CUDA版本验证失败", **host_result}

        # 并行安装
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {executor.submit(install_single, host): host for host in hosts}
            for future in as_completed(futures):
                host, result = future.result()
                results[host] = result
                status = "✓" if result.get("success") else "✗"
                self.logger.info(f"[{host}] {status} CUDA安装{'成功' if result.get('success') else '失败'}")

        return results

    def execute(self, hosts: List[str]) -> StepResult:
        """执行CUDA Toolkit安装（批量模式）"""
        results = {}

        cuda_config = self.versions.cuda
        target_version = cuda_config.version
        mode = getattr(cuda_config, 'mode', 'install')

        self.logger.info("=" * 60)
        self.logger.info("CUDA Toolkit安装流程（批量模式）")
        self.logger.info(f"模式: {mode}")
        self.logger.info(f"目标版本: {target_version}")
        self.logger.info(f"目标节点: {len(hosts)} 个")
        self.logger.info("=" * 60)

        # 1. 批量检测现有CUDA
        cuda_status = self._detect_cuda_batch(hosts)

        # keep模式：保持现有版本，不安装
        if mode == "keep":
            for host, (has_cuda, current_version) in cuda_status.items():
                if has_cuda:
                    self.logger.info(f"[{host}] CUDA已安装，版本: {current_version}，keep模式跳过")
                    results[host] = {"success": True, "action": "kept", "current_version": current_version}
                else:
                    self.logger.info(f"[{host}] CUDA未安装，keep模式跳过")
                    results[host] = {"success": True, "action": "skipped_no_install", "reason": "keep_mode"}

            return StepResult(
                step_id=self.step_id,
                step_name=self.step_name,
                status=StepStatus.SUCCESS,
                message=f"CUDA keep模式，跳过安装",
                host_results=results
            )

        # install模式：安装指定版本
        hosts_to_skip = []
        hosts_to_uninstall = []
        hosts_to_install = []

        target_major = target_version.split('.')[0]
        for host, (has_cuda, current_version) in cuda_status.items():
            if has_cuda and current_version:
                current_major = current_version.split('.')[0] if current_version else ""

                if current_major == target_major:
                    self.logger.info(f"[{host}] CUDA主版本匹配，跳过安装: {current_version}")
                    hosts_to_skip.append(host)
                    results[host] = {"success": True, "action": "skipped_version_match", "current_version": current_version}
                    continue
                else:
                    self.logger.info(f"[{host}] 版本不匹配，需要卸载重装: 当前={current_version}, 目标={target_version}")
                    hosts_to_uninstall.append(host)
            else:
                hosts_to_install.append(host)

        self.logger.info(f"节点分组: 跳过={len(hosts_to_skip)}, 直接安装={len(hosts_to_install)}, 卸载重装={len(hosts_to_uninstall)}")

        # 2. 批量卸载需要重装的节点
        if hosts_to_uninstall:
            uninstall_results = self._uninstall_cuda_batch(hosts_to_uninstall)
            # 卸载失败的节点标记为失败
            for host, success in uninstall_results.items():
                if not success:
                    results[host] = {"success": False, "error": "卸载旧版本失败"}
            # 卸载成功的节点加入安装列表
            hosts_to_install.extend([h for h, success in uninstall_results.items() if success])
            time.sleep(2)  # 等待系统稳定

        if not hosts_to_install:
            self.logger.info("所有节点都已安装正确版本，无需操作")
            return StepResult(
                step_id=self.step_id,
                step_name=self.step_name,
                status=StepStatus.SUCCESS,
                message=f"CUDA无需安装，跳过: {len(hosts_to_skip)}",
                host_results=results
            )

        # 3. 准备安装包
        self.logger.info("步骤1: 准备安装包...")
        package_paths = self._prepare_package(hosts_to_install)

        # 检查准备失败的节点
        for host in hosts_to_install:
            if package_paths.get(host) is None:
                results[host] = {"success": False, "error": "安装包准备失败"}

        hosts_ready = [h for h in hosts_to_install if package_paths.get(h)]
        if not hosts_ready:
            return StepResult(
                step_id=self.step_id,
                step_name=self.step_name,
                status=StepStatus.FAILED,
                message="所有节点的安装包准备失败",
                host_results=results
            )

        # 4. 批量安装依赖
        deps_results = self._install_deps_batch(hosts_ready)
        hosts_deps_ok = [h for h, success in deps_results.items() if success]
        for host in hosts_ready:
            if host not in hosts_deps_ok:
                results[host] = {"success": False, "error": "依赖安装失败"}

        if not hosts_deps_ok:
            return StepResult(
                step_id=self.step_id,
                step_name=self.step_name,
                status=StepStatus.FAILED,
                message="所有节点的依赖安装失败",
                host_results=results
            )

        # 5. 批量安装CUDA
        install_results = self._install_cuda_batch(hosts_deps_ok, package_paths, target_version)
        results.update(install_results)

        # 汇总结果
        success_count = sum(1 for r in results.values() if r.get("success"))
        failed_hosts = [h for h, r in results.items() if not r.get("success")]

        message = f"CUDA Toolkit安装完成，成功: {success_count}/{len(hosts)}"
        if failed_hosts:
            message += f"，失败: {failed_hosts}"

        return StepResult(
            step_id=self.step_id,
            step_name=self.step_name,
            status=StepStatus.SUCCESS if success_count == len(hosts) else StepStatus.FAILED,
            message=message,
            host_results=results
        )

    def post_check(self, hosts: List[str]) -> bool:
        """验证CUDA安装"""
        cmd = "/usr/local/cuda/bin/nvcc -V | head -1"
        result = self.execute_batch(hosts, cmd, sudo=False)
        return all(r.success for r in result.results.values())
