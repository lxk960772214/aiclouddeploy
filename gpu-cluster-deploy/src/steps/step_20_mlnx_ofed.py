"""
步骤20: 安装Mellanox驱动

功能增强:
- 支持自动下载和分发安装包
- 智能检测已安装版本
- 跳过已安装相同版本
"""

from typing import List, Optional, Tuple
from src.steps.base import BaseStep, StepResult, StepStatus


class MellanoxDriver(BaseStep):
    """安装Mellanox OFED驱动"""

    step_id = "20"
    step_name = "安装Mellanox驱动"
    step_description = "安装MLNX_OFED驱动（支持自动下载）"
    requires_sudo = True
    supports_batch = False
    requires_reboot = True
    timeout = 2400  # 40分钟（下载+安装可能需要更长时间）

    def _prepare_package(self, hosts: List[str]) -> dict:
        """
        准备MLNX_OFED安装包

        Args:
            hosts: 目标主机列表

        Returns:
            dict: {host: file_path}
        """
        from src.package_manager import PackageManager, PackageConfig, PackageType

        mlnx_config = self.versions.mlnx_ofed

        # 创建包配置
        package = PackageConfig(
            name="mlnx_ofed",
            version=mlnx_config.version,
            package_type=PackageType.MLNX_OFED,
            local_file=mlnx_config.local_file,
            download_url=mlnx_config.download_url,
            checksum=mlnx_config.checksum,
            file_size=mlnx_config.file_size,
        )

        # 创建包管理器
        manager = PackageManager(
            ssh_manager=self.ssh_manager,
            logger=self.logger
        )

        # 准备安装包
        return manager.prepare_package(package, hosts, dest_path=f"/tmp/{package.filename}")

    def _detect_existing_mlnx(self, host: str) -> Tuple[bool, Optional[str]]:
        """
        检测节点上是否已安装MLNX_OFED

        Returns:
            Tuple[bool, Optional[str]]: (是否安装, 版本号)
        """
        # 方法1: 使用 ofed_info 检测
        result = self.execute_on_host(host, "ofed_info -s 2>/dev/null | head -1")
        if result.get("success") and result.get("stdout", "").strip():
            version = result["stdout"].strip()
            self.logger.info(f"[{host}] 检测到已安装MLNX_OFED版本: {version}")
            return True, version

        # 方法2: 检查 ibstat
        result = self.execute_on_host(host, "ibstat -V 2>/dev/null")
        if result.get("success") and result.get("stdout", "").strip():
            output = result["stdout"].strip()
            # 提取版本信息
            for line in output.split('\n'):
                if 'version' in line.lower():
                    version = line.split()[-1]
                    self.logger.info(f"[{host}] 检测到MLNX_OFED版本: {version}")
                    return True, version

        # 方法3: 检查内核模块
        result = self.execute_on_host(host, "modinfo mlx5_core 2>/dev/null | grep '^version:' | awk '{print $2}'")
        if result.get("success") and result.get("stdout", "").strip():
            version = result["stdout"].strip()
            self.logger.info(f"[{host}] 检测到mlx5_core模块版本: {version}")
            return True, version

        self.logger.info(f"[{host}] 未检测到已安装的MLNX_OFED驱动")
        return False, None

    def _uninstall_existing_mlnx(self, host: str) -> dict:
        """
        卸载现有的MLNX_OFED驱动

        Args:
            host: 目标主机

        Returns:
            卸载结果
        """
        self.logger.info(f"[{host}] 开始卸载现有MLNX_OFED驱动...")

        results = {}

        # 1. 运行MLNX卸载工具（如果存在）
        uninstall_result = self.execute_on_host(
            host,
            "test -f /usr/sbin/ofed_uninstall.sh && /usr/sbin/ofed_uninstall.sh -s --force || echo 'no_uninstaller'",
            sudo=True,
            timeout=300
        )
        results["ofed_uninstaller"] = uninstall_result

        # 2. 使用 apt 卸载
        apt_result = self.execute_on_host(
            host,
            "apt-get purge -y 'ib-*' 'mlnx-*' '*ofed*' 2>/dev/null || true",
            sudo=True
        )
        results["apt_purge"] = apt_result

        # 3. 卸载内核模块
        modules = [
            "ib_ipoib",
            "ib_umad",
            "ib_uverbs",
            "ib_core",
            "mlx5_ib",
            "mlx5_core",
            "mlx4_ib",
            "mlx4_core",
        ]
        for module in modules:
            self.execute_on_host(host, f"modprobe -r {module} 2>/dev/null || true", sudo=True)

        # 4. 清理残留文件
        cleanup_cmds = [
            "rm -rf /usr/src/mlnx-ofed-kernel* 2>/dev/null || true",
            "rm -rf /var/cache/mlnx-ofed 2>/dev/null || true",
            "rm -f /etc/infiniband/openib.conf 2>/dev/null || true",
        ]
        for cmd in cleanup_cmds:
            self.execute_on_host(host, cmd, sudo=True)

        results["success"] = True
        self.logger.info(f"[{host}] MLNX_OFED卸载完成")
        return results

    def _install_mlnx(self, host: str, version: str, driver_file: str) -> dict:
        """
        安装MLNX_OFED驱动

        Args:
            host: 目标主机
            version: 目标版本
            driver_file: 安装文件路径

        Returns:
            安装结果
        """
        self.logger.info(f"[{host}] 开始安装MLNX_OFED {version}...")

        results = {}

        # 1. 安装依赖
        self.logger.info(f"[{host}] 安装依赖包...")
        deps_cmd = "apt-get update && apt-get install -y build-essential libnl-3-dev libnl-route-3-dev libnuma-dev"
        deps_result = self.execute_on_host(host, deps_cmd, sudo=True)
        results["deps"] = deps_result

        # 2. 检查安装文件
        check_cmd = f"test -f {driver_file} && echo 'exists' || echo 'not_found'"
        check_result = self.execute_on_host(host, check_cmd)

        if "not_found" in check_result.get("stdout", ""):
            results["success"] = False
            results["error"] = f"MLNX_OFED安装文件不存在: {driver_file}"
            return results

        # 3. 解压驱动
        self.logger.info(f"[{host}] 解压驱动包...")
        extract_dir = "/tmp/mlnx_ofed"
        extract_cmd = f"rm -rf {extract_dir} && mkdir -p {extract_dir} && tar -xzf {driver_file} -C {extract_dir} --strip-components=1"
        extract_result = self.execute_on_host(host, extract_cmd, sudo=True)

        if not extract_result.get("success"):
            results["success"] = False
            results["error"] = "解压驱动失败"
            return results

        # 4. 安装驱动
        self.logger.info(f"[{host}] 执行MLNX_OFED安装（这可能需要较长时间）...")
        install_cmd = f"cd {extract_dir} && ./mlnxofedinstall --add-kernel-support --skip-distro-check --force --enable-opensm"
        install_result = self.execute_on_host(host, install_cmd, sudo=True, timeout=1800)
        results["install"] = install_result

        if not install_result.get("success"):
            results["success"] = False
            results["error"] = f"MLNX_OFED安装失败: {install_result.get('stderr', '未知错误')}"
            return results

        # 5. 验证安装
        self.logger.info(f"[{host}] 验证MLNX_OFED安装...")
        verify_result = self.execute_on_host(host, "ofed_info -s")
        results["verify"] = verify_result

        if verify_result.get("success"):
            # 获取安装后的版本
            version_result = self.execute_on_host(host, "ofed_info -s | head -1")
            installed_version = version_result.get("stdout", "").strip() if version_result.get("success") else "unknown"
            self.logger.info(f"[{host}] MLNX_OFED安装成功，版本: {installed_version}")
            results["success"] = True
            results["installed_version"] = installed_version
        else:
            results["success"] = False
            results["error"] = "ofed_info验证失败，可能需要重启"

        return results

    def execute(self, hosts: List[str]) -> StepResult:
        """执行Mellanox驱动安装"""
        results = {}

        mlnx_config = self.versions.mlnx_ofed
        target_version = mlnx_config.version

        self.logger.info("=" * 60)
        self.logger.info("MLNX_OFED驱动安装流程")
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
            self.logger.info(f"[{host}] ========== MLNX_OFED安装流程开始 ==========")
            self.logger.info(f"[{host}] 目标版本: {target_version}")

            host_result = {"target_version": target_version}
            driver_file = package_paths[host]

            # 2. 检测现有MLNX_OFED
            has_mlnx, current_version = self._detect_existing_mlnx(host)
            host_result["existing_mlnx"] = has_mlnx
            host_result["current_version"] = current_version

            # 3. 判断是否需要安装
            if has_mlnx and current_version:
                # 简化版本比较：检查主版本号
                target_parts = target_version.split('-')[0].split('.')
                current_parts = current_version.split('-')[0].split('.') if current_version else []

                if len(current_parts) >= 2 and len(target_parts) >= 2:
                    if current_parts[0] == target_parts[0] and current_parts[1] == target_parts[1]:
                        self.logger.info(f"[{host}] MLNX_OFED主版本匹配，跳过安装: {current_version}")
                        host_result["success"] = True
                        host_result["action"] = "skipped_version_match"
                        results[host] = host_result
                        continue

                self.logger.info(f"[{host}] 检测到版本不匹配: 当前={current_version}, 目标={target_version}")
                # 卸载旧版本
                uninstall_result = self._uninstall_existing_mlnx(host)
                host_result["uninstall"] = uninstall_result

                # 等待系统稳定
                import time
                time.sleep(2)

            # 4. 安装MLNX_OFED
            install_result = self._install_mlnx(host, target_version, driver_file)
            host_result["install"] = install_result

            if install_result.get("success"):
                host_result["success"] = True
                host_result["action"] = "installed"
            else:
                host_result["success"] = False
                host_result["error"] = install_result.get("error", "安装失败")

            results[host] = host_result
            self.logger.info(f"[{host}] ========== MLNX_OFED安装流程结束 ==========")

        success_count = sum(1 for r in results.values() if r.get("success"))
        failed_hosts = [h for h, r in results.items() if not r.get("success")]

        message = f"MLNX_OFED驱动安装完成，成功: {success_count}/{len(hosts)}（需要重启）"
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
        """验证驱动安装"""
        cmd = "ibstat | grep -q 'State: Active'"
        result = self.execute_batch(hosts, cmd, sudo=False)
        return all(r.success for r in result.results.values())
