"""
步骤20: 安装Mellanox驱动

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


class MellanoxDriver(BaseStep):
    """安装Mellanox OFED驱动"""

    step_id = "20"
    step_name = "安装Mellanox驱动"
    step_description = "安装MLNX_OFED驱动（支持自动下载）"
    requires_sudo = True
    supports_batch = True  # 改为支持批量执行
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

        # 创建包管理器（传递配置以获取认证信息）
        manager = PackageManager(
            ssh_manager=self.ssh_manager,
            config=self.config,
            logger=self.logger
        )

        # 准备安装包
        return manager.prepare_package(package, hosts, dest_path=f"/tmp/{package.filename}")

    def is_configured(self, host: str) -> tuple:
        """
        检查MLNX_OFED驱动是否已安装

        Args:
            host: 主机地址

        Returns:
            tuple[bool, str]: (是否已配置, 检查详情)
        """
        # 检查 ofed_info 命令
        result = self.execute_on_host(host, "ofed_info -s 2>/dev/null | head -1", timeout=30)

        if result.get("success") and result.get("stdout", "").strip():
            raw_version = result["stdout"].strip()
            # 提取版本号
            import re
            match = re.search(r'MLNX_OFED_LINUX-(\d+\.\d+-[\d.]+)', raw_version)
            if match:
                version = match.group(1)
            else:
                match = re.search(r'(\d+\.\d+-[\d.]+)', raw_version)
                version = match.group(1) if match else raw_version

            # 检查版本是否匹配配置
            if hasattr(self, 'versions') and self.versions and self.versions.mlnx_ofed:
                target_version = self.versions.mlnx_ofed.version
                if target_version in version or version in target_version:
                    return True, f"MLNX_OFED已安装: {version}"
                else:
                    return True, f"MLNX_OFED已安装(版本不同): {version} (目标: {target_version})"

            return True, f"MLNX_OFED已安装: {version}"

        return False, "MLNX_OFED未安装"

    def _detect_mlnx_batch(self, hosts: List[str]) -> Dict[str, Tuple[bool, Optional[str]]]:
        """
        批量检测节点上是否已安装MLNX_OFED

        Returns:
            Dict[str, Tuple[bool, Optional[str]]]: {host: (是否安装, 版本号)}
        """
        self.logger.info(f"[{self.step_id}] 批量检测MLNX_OFED安装状态...")
        results = {}

        def extract_version(version_str: str) -> Optional[str]:
            """从版本字符串中提取版本号，处理各种格式"""
            if not version_str:
                return None
            # 处理 MLNX_OFED_LINUX-23.10-2.1.3.1 格式
            # 或 MLNX_OFED_LINUX-23.10-2.1.3.1-omg32.1ubuntu22.04 格式
            import re
            match = re.search(r'MLNX_OFED_LINUX-(\d+\.\d+-[\d.]+)', version_str)
            if match:
                return match.group(1)
            # 处理纯版本号格式如 23.10-2.1.3.1
            match = re.search(r'^(\d+\.\d+-[\d.]+)$', version_str.strip())
            if match:
                return match.group(1)
            # 其他情况，尝试提取类似版本号的部分
            match = re.search(r'(\d+\.\d+-[\d.]+)', version_str)
            if match:
                return match.group(1)
            return version_str.strip()

        def detect_single(host: str) -> Tuple[str, bool, Optional[str]]:
            # 方法1: 使用 ofed_info 检测
            result = self.execute_on_host(host, "ofed_info -s 2>/dev/null | head -1", timeout=30)
            if result.get("success") and result.get("stdout", "").strip():
                raw_version = result["stdout"].strip()
                version = extract_version(raw_version)
                return host, True, version or raw_version

            # 方法2: 检查 ibstat
            result = self.execute_on_host(host, "ibstat -V 2>/dev/null", timeout=30)
            if result.get("success") and result.get("stdout", "").strip():
                output = result["stdout"].strip()
                for line in output.split('\n'):
                    if 'version' in line.lower():
                        version = line.split()[-1]
                        return host, True, version

            # 方法3: 检查内核模块
            result = self.execute_on_host(host, "modinfo mlx5_core 2>/dev/null | grep '^version:' | awk '{print $2}'", timeout=30)
            if result.get("success") and result.get("stdout", "").strip():
                return host, True, result["stdout"].strip()

            return host, False, None

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = {executor.submit(detect_single, host): host for host in hosts}
            for future in as_completed(futures):
                host, has_mlnx, version = future.result()
                results[host] = (has_mlnx, version)
                if has_mlnx:
                    self.logger.info(f"[{host}] 检测到MLNX_OFED版本: {version}")
                else:
                    self.logger.info(f"[{host}] 未检测到MLNX_OFED")

        return results

    def _check_rdma_devices_batch(self, hosts: List[str]) -> Dict[str, bool]:
        """批量检查是否有RDMA设备"""
        self.logger.info(f"[{self.step_id}] 批量检查RDMA设备...")
        results = {}

        def check_single(host: str) -> Tuple[str, bool]:
            result = self.execute_on_host(
                host, "lspci | grep -qi 'mellanox\\|infiniband\\|connectx' && echo 'yes' || echo 'no'",
                timeout=30
            )
            has_rdma = "yes" in result.get("stdout", "")
            return host, has_rdma

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = {executor.submit(check_single, host): host for host in hosts}
            for future in as_completed(futures):
                host, has_rdma = future.result()
                results[host] = has_rdma

        return results

    def _uninstall_mlnx_batch(self, hosts: List[str]) -> Dict[str, bool]:
        """批量卸载现有的MLNX_OFED驱动"""
        self.logger.info(f"[{self.step_id}] 批量卸载MLNX_OFED（{len(hosts)}个节点）...")
        results = {}

        # 卸载脚本
        uninstall_script = '''
# 1. 运行MLNX卸载工具（如果存在）
test -f /usr/sbin/ofed_uninstall.sh && /usr/sbin/ofed_uninstall.sh -s --force || true

# 2. 使用 apt 卸载
apt-get purge -y 'ib-*' 'mlnx-*' '*ofed*' 2>/dev/null || true

# 3. 卸载内核模块
for module in ib_ipoib ib_umad ib_uverbs ib_core mlx5_ib mlx5_core mlx4_ib mlx4_core; do
    modprobe -r $module 2>/dev/null || true
done

# 4. 清理残留文件
rm -rf /usr/src/mlnx-ofed-kernel* 2>/dev/null || true
rm -rf /var/cache/mlnx-ofed 2>/dev/null || true
rm -f /etc/infiniband/openib.conf 2>/dev/null || true

echo "UNINSTALL_DONE"
'''

        summary = self.execute_batch(hosts, uninstall_script, sudo=True)

        for host, result in summary.results.items():
            results[host] = result.success and "UNINSTALL_DONE" in result.stdout
            if results[host]:
                self.logger.info(f"[{host}] MLNX_OFED卸载完成")
            else:
                self.logger.warning(f"[{host}] MLNX_OFED卸载可能未完全成功")

        return results

    def _install_deps_batch(self, hosts: List[str]) -> Dict[str, bool]:
        """批量安装依赖"""
        self.logger.info(f"[{self.step_id}] 批量安装依赖（{len(hosts)}个节点）...")

        deps_cmd = "apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y build-essential libnl-3-dev libnl-route-3-dev libnuma-dev"
        summary = self.execute_batch(hosts, deps_cmd, sudo=True)

        results = {host: result.success for host, result in summary.results.items()}
        failed = [h for h, success in results.items() if not success]
        if failed:
            self.logger.warning(f"依赖安装失败的节点: {failed}")

        return results

    def _install_mlnx_batch(self, hosts: List[str], package_paths: Dict[str, str], target_version: str) -> Dict[str, dict]:
        """批量安装MLNX_OFED驱动"""
        self.logger.info(f"[{self.step_id}] 批量安装MLNX_OFED {target_version}（{len(hosts)}个节点）...")
        results = {}

        def install_single(host: str) -> Tuple[str, dict]:
            driver_file = package_paths.get(host)
            if not driver_file:
                return host, {"success": False, "error": "安装文件不存在"}

            host_result = {"target_version": target_version}

            # 检查安装文件
            check_result = self.execute_on_host(host, f"test -f {driver_file} && echo 'exists' || echo 'not_found'")
            if "not_found" in check_result.get("stdout", ""):
                return host, {"success": False, "error": f"MLNX_OFED安装文件不存在: {driver_file}"}

            # 解压驱动
            # MLNX_OFED tar包结构: MLNX_OFED_LINUX-xxx/mlnxofedinstall
            # 解压后需要找到正确的子目录
            extract_base = "/tmp/mlnx_ofed"
            extract_cmd = f"rm -rf {extract_base} && mkdir -p {extract_base} && tar -xzf {driver_file} -C {extract_base}"
            extract_result = self.execute_on_host(host, extract_cmd, sudo=True, timeout=120)

            if not extract_result.get("success"):
                return host, {"success": False, "error": "解压驱动失败"}

            # 查找解压后的实际目录（tar包内包含一个子目录）
            find_dir_cmd = f"find {extract_base} -name 'mlnxofedinstall' -type f 2>/dev/null | head -1 | xargs dirname"
            find_result = self.execute_on_host(host, find_dir_cmd, timeout=30)
            actual_dir = find_result.get("stdout", "").strip()

            if not actual_dir:
                return host, {"success": False, "error": "找不到mlnxofedinstall脚本"}

            self.logger.info(f"[{host}] 找到安装目录: {actual_dir}")

            # 安装驱动
            self.logger.info(f"[{host}] 执行MLNX_OFED安装...")
            install_cmd = f"cd {actual_dir} && ./mlnxofedinstall --add-kernel-support --skip-distro-check --force --enable-opensm"
            install_result = self.execute_on_host(host, install_cmd, sudo=True, timeout=1800)
            host_result["install"] = {"success": install_result.get("success"), "exit_code": install_result.get("exit_code")}

            if not install_result.get("success"):
                return host, {"success": False, "error": f"MLNX_OFED安装失败: {install_result.get('stderr', '未知错误')[:500]}"}

            # 验证安装
            verify_result = self.execute_on_host(host, "ofed_info -s", timeout=60)
            if verify_result.get("success"):
                version_result = self.execute_on_host(host, "ofed_info -s | head -1", timeout=30)
                installed_version = version_result.get("stdout", "").strip() if version_result.get("success") else "unknown"
                self.logger.info(f"[{host}] MLNX_OFED安装成功，版本: {installed_version}")
                return host, {"success": True, "installed_version": installed_version, **host_result}
            else:
                return host, {"success": False, "error": "ofed_info验证失败，可能需要重启", **host_result}

        # 并行安装（限制并发数避免资源竞争）
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {executor.submit(install_single, host): host for host in hosts}
            for future in as_completed(futures):
                host, result = future.result()
                results[host] = result
                status = "✓" if result.get("success") else "✗"
                self.logger.info(f"[{host}] {status} MLNX_OFED安装{'成功' if result.get('success') else '失败'}")

        return results

    def execute(self, hosts: List[str]) -> StepResult:
        """执行Mellanox驱动安装（批量模式）"""
        results = {}

        # 检查是否启用
        mlnx_config = self.versions.mlnx_ofed if hasattr(self, 'versions') and self.versions else None
        if mlnx_config and hasattr(mlnx_config, 'enabled') and not mlnx_config.enabled:
            self.logger.info("MLNX_OFED 已禁用 (enabled=false)，跳过安装")
            return StepResult(
                step_id=self.step_id,
                step_name=self.step_name,
                status=StepStatus.SUCCESS,
                message="MLNX_OFED 已禁用，不安装网卡驱动",
                host_results={h: {"success": True, "skipped": True, "reason": "disabled"} for h in hosts}
            )

        # 检查是否有 versions 配置
        if not hasattr(self, 'versions') or self.versions is None:
            self.logger.info("未配置版本信息，跳过MLNX_OFED安装")
            return StepResult(
                step_id=self.step_id,
                step_name=self.step_name,
                status=StepStatus.SUCCESS,
                message="跳过MLNX_OFED安装（未配置版本）",
                host_results={h: {"success": True, "skipped": True, "reason": "no_version_config"} for h in hosts}
            )

        mlnx_config = self.versions.mlnx_ofed
        target_version = mlnx_config.version
        mode = getattr(mlnx_config, 'mode', 'install')

        self.logger.info("=" * 60)
        self.logger.info("MLNX_OFED驱动安装流程（批量模式）")
        self.logger.info(f"模式: {mode}")
        self.logger.info(f"目标版本: {target_version}")
        self.logger.info(f"目标节点: {len(hosts)} 个")
        self.logger.info("=" * 60)

        # 1. 批量检查RDMA设备
        rdma_status = self._check_rdma_devices_batch(hosts)
        hosts_with_rdma = [h for h, has_rdma in rdma_status.items() if has_rdma]
        hosts_no_rdma = [h for h, has_rdma in rdma_status.items() if not has_rdma]

        if not hosts_with_rdma:
            self.logger.info("未检测到Mellanox RDMA设备，跳过驱动安装")
            return StepResult(
                step_id=self.step_id,
                step_name=self.step_name,
                status=StepStatus.SUCCESS,
                message="跳过MLNX_OFED安装（无RDMA设备）",
                host_results={h: {"success": True, "skipped": True, "reason": "no_rdma_device"} for h in hosts}
            )

        # 标记无RDMA设备的节点为跳过
        for host in hosts_no_rdma:
            results[host] = {"success": True, "skipped": True, "reason": "no_rdma_device"}
            self.logger.info(f"[{host}] 无RDMA设备，跳过安装")

        # 2. 批量检测现有MLNX_OFED
        mlnx_status = self._detect_mlnx_batch(hosts_with_rdma)

        # keep模式：保持现有版本，不安装
        if mode == "keep":
            for host, (has_mlnx, current_version) in mlnx_status.items():
                if has_mlnx:
                    self.logger.info(f"[{host}] MLNX_OFED已安装，版本: {current_version}，keep模式跳过")
                    results[host] = {"success": True, "action": "kept", "current_version": current_version}
                else:
                    self.logger.info(f"[{host}] MLNX_OFED未安装，keep模式跳过")
                    results[host] = {"success": True, "action": "skipped_no_install", "reason": "keep_mode"}

            return StepResult(
                step_id=self.step_id,
                step_name=self.step_name,
                status=StepStatus.SUCCESS,
                message=f"MLNX_OFED keep模式，跳过安装",
                host_results=results
            )

        # install模式：安装指定版本
        hosts_to_skip = []
        hosts_to_install = []

        for host, (has_mlnx, current_version) in mlnx_status.items():
            if has_mlnx and current_version:
                # 精确版本匹配则跳过
                if current_version == target_version:
                    self.logger.info(f"[{host}] MLNX_OFED版本匹配，跳过安装: {current_version}")
                    hosts_to_skip.append(host)
                    results[host] = {"success": True, "action": "skipped_version_match", "current_version": current_version}
                    continue

                # 版本不匹配，需要安装（MLNX_OFED安装程序会自动处理旧版本）
                self.logger.info(f"[{host}] 版本不匹配，需要安装: 当前={current_version}, 目标={target_version}")
                hosts_to_install.append(host)
            else:
                hosts_to_install.append(host)

        self.logger.info(f"节点分组: 跳过={len(hosts_to_skip)}, 需要安装={len(hosts_to_install)}")

        if not hosts_to_install:
            self.logger.info("所有节点都已安装正确版本，无需操作")
            return StepResult(
                step_id=self.step_id,
                step_name=self.step_name,
                status=StepStatus.SUCCESS,
                message=f"MLNX_OFED无需安装，跳过: {len(hosts_to_skip)}，无RDMA: {len(hosts_no_rdma)}",
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

        # 5. 批量安装MLNX_OFED（安装程序会自动处理旧版本）
        install_results = self._install_mlnx_batch(hosts_deps_ok, package_paths, target_version)
        results.update(install_results)

        # 汇总结果
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
        # 先检查是否有 RDMA 设备
        has_rdma = False
        for host in hosts:
            check_result = self.execute_on_host(host, "lspci | grep -qi 'mellanox\\|infiniband\\|connectx' && echo 'yes' || echo 'no'")
            if "yes" in check_result.get("stdout", ""):
                has_rdma = True
                break

        # 如果没有 RDMA 设备，直接返回成功
        if not has_rdma:
            return True

        # 检查 ibstat 是否可用
        check_ibstat = "which ibstat 2>/dev/null || echo 'not_found'"
        ibstat_result = self.execute_batch(hosts, check_ibstat, sudo=False)
        if all('not_found' in r.stdout for r in ibstat_result.results.values()):
            return True  # ibstat 未安装，可能是跳过安装的情况

        cmd = "ibstat | grep -q 'State: Active'"
        result = self.execute_batch(hosts, cmd, sudo=False)
        return all(r.success for r in result.results.values())
