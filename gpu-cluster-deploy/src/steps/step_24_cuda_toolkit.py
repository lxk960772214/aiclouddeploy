"""
步骤24: 安装CUDA Toolkit

功能增强:
- 支持自动下载和分发安装包
- 智能检测已安装版本
- 跳过已安装相同版本
"""

from typing import List, Optional, Tuple
from src.steps.base import BaseStep, StepResult, StepStatus


class CUDAToolkit(BaseStep):
    """安装CUDA Toolkit"""

    step_id = "24"
    step_name = "安装CUDA Toolkit"
    step_description = "安装NVIDIA CUDA Toolkit（支持自动下载）"
    requires_sudo = True
    supports_batch = False
    timeout = 2400  # 40分钟（下载+安装可能需要更长时间）

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

        # 创建包管理器
        manager = PackageManager(
            ssh_manager=self.ssh_manager,
            logger=self.logger
        )

        # 准备安装包
        return manager.prepare_package(package, hosts, dest_path=f"/tmp/{package.filename}")

    def _detect_existing_cuda(self, host: str) -> Tuple[bool, Optional[str]]:
        """
        检测节点上是否已安装CUDA Toolkit

        Returns:
            Tuple[bool, Optional[str]]: (是否安装, 版本号)
        """
        # 方法1: 使用 nvcc 检测
        result = self.execute_on_host(host, "/usr/local/cuda/bin/nvcc -V 2>/dev/null | grep 'release' | awk '{print $6}'")
        if result.get("success") and result.get("stdout", "").strip():
            version = result["stdout"].strip().replace(",", "")
            self.logger.info(f"[{host}] 检测到已安装CUDA版本: {version}")
            return True, version

        # 方法2: 检查 /usr/local/cuda/version.txt
        result = self.execute_on_host(host, "cat /usr/local/cuda/version.txt 2>/dev/null | awk '{print $NF}'")
        if result.get("success") and result.get("stdout", "").strip():
            version = result["stdout"].strip()
            self.logger.info(f"[{host}] 检测到已安装CUDA版本: {version}")
            return True, version

        # 方法3: 检查版本文件
        result = self.execute_on_host(host, "ls -d /usr/local/cuda-* 2>/dev/null | tail -1 | sed 's|.*/cuda-||'")
        if result.get("success") and result.get("stdout", "").strip():
            version = result["stdout"].strip()
            self.logger.info(f"[{host}] 检测到CUDA目录版本: {version}")
            return True, version

        self.logger.info(f"[{host}] 未检测到已安装的CUDA Toolkit")
        return False, None

    def _uninstall_existing_cuda(self, host: str) -> dict:
        """
        卸载现有的CUDA Toolkit

        Args:
            host: 目标主机

        Returns:
            卸载结果
        """
        self.logger.info(f"[{host}] 开始卸载现有CUDA Toolkit...")

        results = {}

        # 1. 运行CUDA卸载工具（如果存在）
        uninstall_result = self.execute_on_host(
            host,
            "test -f /usr/local/cuda/bin/cuda-uninstaller && /usr/local/cuda/bin/cuda-uninstaller -s || echo 'no_uninstaller'",
            sudo=True
        )
        results["cuda_uninstaller"] = uninstall_result

        # 2. 清理apt安装的CUDA包
        apt_result = self.execute_on_host(
            host,
            "apt-get purge -y '*cuda*' '*libcuda*' '*nvidia-cuda*' 2>/dev/null || true",
            sudo=True
        )
        results["apt_purge"] = apt_result

        # 3. 清理残留文件
        cleanup_cmds = [
            "rm -rf /usr/local/cuda-* 2>/dev/null || true",
            "rm -rf /usr/local/cuda 2>/dev/null || true",
            "rm -f /etc/profile.d/cuda.sh 2>/dev/null || true",
        ]
        for cmd in cleanup_cmds:
            self.execute_on_host(host, cmd, sudo=True)

        # 4. 清理环境变量
        self.execute_on_host(
            host,
            "sed -i '/\\/usr\\/local\\/cuda/d' /etc/profile 2>/dev/null || true",
            sudo=True
        )

        results["success"] = True
        self.logger.info(f"[{host}] CUDA卸载完成")
        return results

    def _install_cuda(self, host: str, version: str, toolkit_file: str) -> dict:
        """
        安装CUDA Toolkit

        Args:
            host: 目标主机
            version: 目标版本
            toolkit_file: 安装文件路径

        Returns:
            安装结果
        """
        self.logger.info(f"[{host}] 开始安装CUDA Toolkit {version}...")

        results = {}

        # 1. 安装依赖
        self.logger.info(f"[{host}] 安装依赖包...")
        deps_cmd = "apt-get update && apt-get install -y build-essential libglu1-mesa libxi-dev libxmu-dev libglu1-mesa-dev"
        deps_result = self.execute_on_host(host, deps_cmd, sudo=True)
        results["deps"] = deps_result

        # 2. 检查安装文件
        check_cmd = f"test -f {toolkit_file} && echo 'exists' || echo 'not_found'"
        check_result = self.execute_on_host(host, check_cmd)

        if "not_found" in check_result.get("stdout", ""):
            results["success"] = False
            results["error"] = f"CUDA安装文件不存在: {toolkit_file}"
            return results

        # 3. 安装CUDA Toolkit
        self.logger.info(f"[{host}] 执行CUDA安装...")
        install_cmd = f"chmod +x {toolkit_file} && {toolkit_file} --toolkit --no-drm --silent"
        install_result = self.execute_on_host(host, install_cmd, sudo=True, timeout=1200)
        results["install"] = install_result

        if not install_result.get("success"):
            results["success"] = False
            results["error"] = f"CUDA安装失败: {install_result.get('stderr', '未知错误')}"
            return results

        # 4. 创建符号链接
        self.logger.info(f"[{host}] 创建符号链接...")
        symlink_cmd = f"ln -sf /usr/local/cuda-{version.split('.')[0]}.{version.split('.')[1]} /usr/local/cuda"
        self.execute_on_host(host, symlink_cmd, sudo=True)

        # 5. 配置环境变量
        cuda_path = "/usr/local/cuda"
        env_cmd = f'''
grep -q 'export PATH={cuda_path}/bin' /etc/profile || echo "export PATH={cuda_path}/bin:\\$PATH" >> /etc/profile
grep -q 'export LD_LIBRARY_PATH={cuda_path}/lib64' /etc/profile || echo "export LD_LIBRARY_PATH={cuda_path}/lib64:\\$LD_LIBRARY_PATH" >> /etc/profile
'''
        self.execute_on_host(host, env_cmd, sudo=True)

        # 6. 验证安装
        self.logger.info(f"[{host}] 验证CUDA安装...")
        verify_result = self.execute_on_host(host, f"{cuda_path}/bin/nvcc -V")
        results["verify"] = verify_result

        if verify_result.get("success") and version.split('.')[0] in verify_result.get("stdout", ""):
            self.logger.info(f"[{host}] CUDA安装成功，版本: {version}")
            results["success"] = True
            results["installed_version"] = version
        else:
            results["success"] = False
            results["error"] = "CUDA版本验证失败"

        return results

    def execute(self, hosts: List[str]) -> StepResult:
        """执行CUDA Toolkit安装"""
        results = {}

        cuda_config = self.versions.cuda
        target_version = cuda_config.version

        self.logger.info("=" * 60)
        self.logger.info("CUDA Toolkit安装流程")
        self.logger.info(f"目标版本: {target_version}")
        self.logger.info(f"目标节点: {len(hosts)} 个")
        self.logger.info("=" * 60)

        # 1. 准备安装包
        self.logger.info("步骤1: 准备安装包...")
        package_paths = self._prepare_package(hosts)

        # 检查准备失败的节点
        failed_prep = [h for h, path in package_paths.items() if path is None]
        if failed_prep:
            self.logger.error(f"安装包准备失败的节点: {failed_prep}")
            for host in failed_prep:
                results[host] = {
                    "success": False,
                    "error": "安装包准备失败",
                    "target_version": target_version
                }

        # 只处理准备成功的节点
        hosts_to_install = [h for h in hosts if package_paths.get(h)]
        self.logger.info(f"需要安装的节点: {len(hosts_to_install)} 个")

        for host in hosts_to_install:
            self.logger.info(f"[{host}] ========== CUDA安装流程开始 ==========")
            self.logger.info(f"[{host}] 目标版本: {target_version}")

            host_result = {"target_version": target_version}
            toolkit_file = package_paths[host]

            # 2. 检测现有CUDA
            has_cuda, current_version = self._detect_existing_cuda(host)
            host_result["existing_cuda"] = has_cuda
            host_result["current_version"] = current_version

            # 3. 判断是否需要安装
            if has_cuda and current_version:
                # 简化版本比较：主版本号匹配即可
                target_major = target_version.split('.')[0]
                current_major = current_version.split('.')[0] if current_version else ""

                if current_major == target_major:
                    self.logger.info(f"[{host}] CUDA主版本匹配，跳过安装: {current_version}")
                    host_result["success"] = True
                    host_result["action"] = "skipped_version_match"
                    results[host] = host_result
                    continue
                else:
                    self.logger.info(f"[{host}] 检测到版本不匹配: 当前={current_version}, 目标={target_version}")
                    # 卸载旧版本
                    uninstall_result = self._uninstall_existing_cuda(host)
                    host_result["uninstall"] = uninstall_result

            # 4. 安装CUDA
            install_result = self._install_cuda(host, target_version, toolkit_file)
            host_result["install"] = install_result

            if install_result.get("success"):
                host_result["success"] = True
                host_result["action"] = "installed"
            else:
                host_result["success"] = False
                host_result["error"] = install_result.get("error", "安装失败")

            results[host] = host_result
            self.logger.info(f"[{host}] ========== CUDA安装流程结束 ==========")

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
