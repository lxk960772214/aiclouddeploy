"""
步骤22: 安装NVIDIA GPU驱动

功能增强:
- 检测现有NVIDIA驱动版本
- 自动卸载不匹配的旧版本驱动
- 清理残留内核模块和文件
- 安装指定版本驱动
- 支持自动下载和分发安装包
- 批量并行执行
"""

from typing import List, Optional, Tuple, Dict
from src.steps.base import BaseStep, StepResult, StepStatus
from concurrent.futures import ThreadPoolExecutor, as_completed
import time


class NVIDIADriver(BaseStep):
    """安装NVIDIA GPU驱动"""

    step_id = "22"
    step_name = "安装NVIDIA GPU驱动"
    step_description = "安装NVIDIA GPU驱动程序（支持自动下载、卸载旧版本）"
    requires_sudo = True
    supports_batch = True  # 改为支持批量执行
    requires_reboot = True
    timeout = 2400  # 40分钟（下载+卸载+安装可能需要更长时间）

    def is_configured(self, host: str) -> tuple:
        """
        检查 NVIDIA 驱动是否已安装且版本匹配

        Args:
            host: 主机地址

        Returns:
            tuple[bool, str]: (是否已配置, 检查详情)
        """
        # 获取目标版本
        if not self.versions or not hasattr(self.versions, 'nvidia_driver'):
            return False, "未配置驱动版本信息"

        target_version = self.versions.nvidia_driver.version

        # 方法1: 使用 nvidia-smi 检测
        result = self.execute_on_host(
            host,
            "nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null | head -1"
        )
        if result.get("success") and result.get("stdout", "").strip():
            version = result["stdout"].strip()
            if version == target_version:
                return True, f"NVIDIA 驱动已安装且版本匹配: {version}"
            else:
                return False, f"NVIDIA 驱动版本不匹配: 当前={version}, 目标={target_version}"

        # 方法2: 检查 /proc/driver/nvidia/version
        result = self.execute_on_host(
            host,
            "cat /proc/driver/nvidia/version 2>/dev/null | grep 'NVRM version' | awk '{print $8}'"
        )
        if result.get("success") and result.get("stdout", "").strip():
            version = result["stdout"].strip()
            if version == target_version:
                return True, f"NVIDIA 驱动已安装且版本匹配: {version}"
            else:
                return False, f"NVIDIA 驱动版本不匹配: 当前={version}, 目标={target_version}"

        # 方法3: 检查内核模块
        result = self.execute_on_host(
            host,
            "modinfo nvidia 2>/dev/null | grep '^version:' | awk '{print $2}'"
        )
        if result.get("success") and result.get("stdout", "").strip():
            version = result["stdout"].strip()
            if version == target_version:
                return True, f"NVIDIA 内核模块已存在且版本匹配: {version}"
            else:
                return False, f"NVIDIA 内核模块版本不匹配: 当前={version}, 目标={target_version}"

        return False, "NVIDIA 驱动未安装"

    def _prepare_package(self, hosts: List[str]) -> dict:
        """
        准备驱动安装包

        Args:
            hosts: 目标主机列表

        Returns:
            dict: {host: (success, file_path)}
        """
        from src.package_manager import PackageManager, PackageConfig, PackageType

        driver_config = self.versions.nvidia_driver

        # 创建包配置
        package = PackageConfig(
            name="nvidia_driver",
            version=driver_config.version,
            package_type=PackageType.NVIDIA_DRIVER,
            local_file=driver_config.local_file,
            download_url=driver_config.download_url,
            checksum=driver_config.checksum,
            file_size=driver_config.file_size,
        )

        # 创建包管理器（传递配置以获取认证信息）
        manager = PackageManager(
            ssh_manager=self.ssh_manager,
            config=self.config,
            logger=self.logger
        )

        # 准备安装包（自动下载和分发）
        return manager.prepare_package(package, hosts, dest_path=f"/tmp/{package.filename}")

    def _detect_driver_batch(self, hosts: List[str]) -> Dict[str, Tuple[bool, Optional[str]]]:
        """
        批量检测节点上是否已安装NVIDIA驱动

        Returns:
            Dict[str, Tuple[bool, Optional[str]]]: {host: (是否安装, 版本号)}
        """
        self.logger.info(f"[{self.step_id}] 批量检测NVIDIA驱动安装状态...")
        results = {}

        def detect_single(host: str) -> Tuple[str, bool, Optional[str]]:
            # 方法1: 使用 nvidia-smi 检测
            result = self.execute_on_host(
                host, "nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null | head -1",
                timeout=30
            )
            if result.get("success") and result.get("stdout", "").strip():
                return host, True, result["stdout"].strip()

            # 方法2: 检查 /proc/driver/nvidia/version
            result = self.execute_on_host(
                host, "cat /proc/driver/nvidia/version 2>/dev/null | grep 'NVRM version' | awk '{print $8}'",
                timeout=30
            )
            if result.get("success") and result.get("stdout", "").strip():
                return host, True, result["stdout"].strip()

            # 方法3: 检查内核模块
            result = self.execute_on_host(
                host, "modinfo nvidia 2>/dev/null | grep '^version:' | awk '{print $2}'",
                timeout=30
            )
            if result.get("success") and result.get("stdout", "").strip():
                return host, True, result["stdout"].strip()

            return host, False, None

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = {executor.submit(detect_single, host): host for host in hosts}
            for future in as_completed(futures):
                host, has_driver, version = future.result()
                results[host] = (has_driver, version)
                if has_driver:
                    self.logger.info(f"[{host}] 检测到NVIDIA驱动版本: {version}")
                else:
                    self.logger.info(f"[{host}] 未检测到NVIDIA驱动")

        return results

    def _uninstall_driver_batch(self, hosts: List[str]) -> Dict[str, bool]:
        """批量卸载现有的NVIDIA驱动"""
        self.logger.info(f"[{self.step_id}] 批量卸载NVIDIA驱动（{len(hosts)}个节点）...")
        results = {}

        # 卸载脚本
        uninstall_script = '''
# 1. 停止GPU相关进程
pkill -9 -f nvidia-persistenced || true
pkill -9 -f fabricmanager || true
systemctl stop nvidia-persistenced || true
systemctl stop nvidia-fabricmanager || true

# 2. 卸载内核模块（按依赖顺序反向卸载）
for module in nvidia_uvm nvidia_drm nvidia_modeset nvidia_peermem nvidia_nvswitch nvidia; do
    modprobe -r $module 2>/dev/null || true
done

# 3. 使用NVIDIA官方卸载工具
test -f /usr/bin/nvidia-uninstall && /usr/bin/nvidia-uninstall -s || true

# 4. 清理处于rc状态的nvidia相关包（避免依赖解析失败）
dpkg --purge $(dpkg -l | grep -E '^rc.*nvidia|^rc.*linux-modules-nvidia' | awk '{print $2}') 2>/dev/null || true

# 5. 清理apt安装的NVIDIA包
apt-get purge -y 'nvidia*' 'libnvidia*' 'cuda*' 2>/dev/null || true

# 6. 清理残留文件
rm -rf /usr/lib/nvidia-* 2>/dev/null || true
rm -rf /usr/share/nvidia/ 2>/dev/null || true
rm -rf /var/log/nvidia* 2>/dev/null || true
rm -f /etc/modprobe.d/nvidia*.conf 2>/dev/null || true
rm -f /usr/share/glvnd/egl_vendor.d/10_nvidia.json 2>/dev/null || true
rm -f /etc/vulkan/icd.d/nvidia_icd.json 2>/dev/null || true
rm -f /usr/share/vulkan/icd.d/nvidia_icd.json 2>/dev/null || true
rm -f /etc/init.d/nvidia* 2>/dev/null || true
rm -f /etc/systemd/system/nvidia*.service 2>/dev/null || true
rm -f /lib/udev/rules.d/*nvidia*.rules 2>/dev/null || true

# 7. 清理DKMS模块
for v in $(dkms status nvidia 2>/dev/null | awk '{print $2}'); do
    dkms remove nvidia/$v --all 2>/dev/null || true
done

# 8. 自动清理
apt-get autoremove -y 2>/dev/null || true

# 9. 验证卸载
lsmod | grep nvidia || echo "UNINSTALL_DONE"
'''

        summary = self.execute_batch(hosts, uninstall_script, sudo=True)

        for host, result in summary.results.items():
            # 如果没有nvidia模块或者输出包含UNINSTALL_DONE，认为成功
            results[host] = "UNINSTALL_DONE" in result.stdout or "nvidia" not in result.stdout.lower()
            if results[host]:
                self.logger.info(f"[{host}] NVIDIA驱动卸载完成")
            else:
                self.logger.warning(f"[{host}] NVIDIA驱动卸载可能未完全成功")

        return results

    def _install_deps_batch(self, hosts: List[str]) -> Dict[str, bool]:
        """批量安装依赖"""
        self.logger.info(f"[{self.step_id}] 批量安装依赖（{len(hosts)}个节点）...")

        deps_cmd = "apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y build-essential dkms libvulkan1 mesa-vulkan-drivers vulkan-tools libglvnd-dev"
        summary = self.execute_batch(hosts, deps_cmd, sudo=True)

        results = {host: result.success for host, result in summary.results.items()}
        failed = [h for h, success in results.items() if not success]
        if failed:
            self.logger.warning(f"依赖安装失败的节点: {failed}")

        return results

    def _install_driver_batch(self, hosts: List[str], package_paths: Dict[str, str], target_version: str) -> Dict[str, dict]:
        """批量安装NVIDIA驱动"""
        self.logger.info(f"[{self.step_id}] 批量安装NVIDIA驱动 {target_version}（{len(hosts)}个节点）...")
        results = {}

        def install_single(host: str) -> Tuple[str, dict]:
            driver_file = package_paths.get(host)
            if not driver_file:
                return host, {"success": False, "error": "驱动文件不存在"}

            host_result = {"target_version": target_version}

            # 禁用nouveau（如果尚未禁用）
            nouveau_check = self.execute_on_host(host, "lsmod | grep nouveau || echo 'nouveau_disabled'", timeout=30)
            if "nouveau_disabled" not in nouveau_check.get("stdout", ""):
                self.execute_on_host(host, "modprobe -r nouveau 2>/dev/null || true", sudo=True, timeout=30)

            # 执行驱动安装
            self.logger.info(f"[{host}] 执行NVIDIA驱动安装...")
            install_cmd = f"chmod +x {driver_file} && {driver_file} -s --dkms --no-cc-version-check"
            install_result = self.execute_on_host(host, install_cmd, sudo=True, timeout=900)
            host_result["install"] = {"success": install_result.get("success"), "exit_code": install_result.get("exit_code")}

            if not install_result.get("success"):
                error_msg = f"驱动安装失败: exit_code={install_result.get('exit_code')}"
                stderr = install_result.get("stderr", "")
                if stderr:
                    error_msg += f", stderr={stderr[:500]}"
                return host, {"success": False, "error": error_msg, **host_result}

            # 复制vulkan配置
            self.execute_on_host(
                host,
                "mkdir -p /usr/share/vulkan/icd.d && cp /etc/vulkan/icd.d/nvidia_icd.json /usr/share/vulkan/icd.d/ 2>/dev/null || true",
                sudo=True, timeout=30
            )

            # 加载内核模块
            self.execute_on_host(host, "modprobe nvidia", sudo=True, timeout=30)

            # 验证安装
            verify_result = self.execute_on_host(host, "nvidia-smi", timeout=60)
            if verify_result.get("success"):
                version_result = self.execute_on_host(
                    host, "nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null | head -1",
                    timeout=30
                )
                installed_version = version_result.get("stdout", "").strip() if version_result.get("success") else "unknown"
                self.logger.info(f"[{host}] NVIDIA驱动安装成功，版本: {installed_version}")
                return host, {"success": True, "installed_version": installed_version, **host_result}
            else:
                return host, {"success": False, "error": "nvidia-smi验证失败，可能需要重启", **host_result}

        # 并行安装（限制并发数）
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {executor.submit(install_single, host): host for host in hosts}
            for future in as_completed(futures):
                host, result = future.result()
                results[host] = result
                status = "✓" if result.get("success") else "✗"
                self.logger.info(f"[{host}] {status} NVIDIA驱动安装{'成功' if result.get('success') else '失败'}")

        return results

    def execute(self, hosts: List[str]) -> StepResult:
        """执行NVIDIA驱动安装（批量模式）"""
        results = {}

        driver_config = self.versions.nvidia_driver
        target_version = driver_config.version
        mode = getattr(driver_config, 'mode', 'install')

        self.logger.info("=" * 60)
        self.logger.info("NVIDIA驱动安装流程（批量模式）")
        self.logger.info(f"模式: {mode}")
        self.logger.info(f"目标版本: {target_version}")
        self.logger.info(f"目标节点: {len(hosts)} 个")
        self.logger.info("=" * 60)

        # 1. 批量检测现有驱动
        driver_status = self._detect_driver_batch(hosts)

        # keep模式：保持现有版本，不安装
        if mode == "keep":
            for host, (has_driver, current_version) in driver_status.items():
                if has_driver:
                    self.logger.info(f"[{host}] NVIDIA驱动已安装，版本: {current_version}，keep模式跳过")
                    results[host] = {"success": True, "action": "kept", "current_version": current_version}
                else:
                    self.logger.info(f"[{host}] NVIDIA驱动未安装，keep模式跳过")
                    results[host] = {"success": True, "action": "skipped_no_install", "reason": "keep_mode"}

            return StepResult(
                step_id=self.step_id,
                step_name=self.step_name,
                status=StepStatus.SUCCESS,
                message=f"NVIDIA驱动 keep模式，跳过安装",
                host_results=results
            )

        # install模式：安装指定版本
        hosts_to_skip = []
        hosts_to_uninstall = []
        hosts_to_install = []

        for host, (has_driver, current_version) in driver_status.items():
            if has_driver:
                if current_version:
                    if current_version == target_version:
                        self.logger.info(f"[{host}] 版本匹配，跳过安装: {target_version}")
                        hosts_to_skip.append(host)
                        results[host] = {"success": True, "action": "skipped_version_match", "current_version": current_version}
                        continue
                    else:
                        self.logger.info(f"[{host}] 版本不匹配，需要卸载重装: 当前={current_version}, 目标={target_version}")
                        hosts_to_uninstall.append((host, current_version))
                else:
                    # 有驱动但无法确定版本，安全起见卸载
                    hosts_to_uninstall.append((host, None))
            else:
                hosts_to_install.append(host)

        self.logger.info(f"节点分组: 跳过={len(hosts_to_skip)}, 直接安装={len(hosts_to_install)}, 卸载重装={len(hosts_to_uninstall)}")

        # 2. 批量卸载需要重装的节点
        if hosts_to_uninstall:
            uninstall_hosts = [h for h, _ in hosts_to_uninstall]
            uninstall_results = self._uninstall_driver_batch(uninstall_hosts)
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
                message=f"NVIDIA驱动无需安装，跳过: {len(hosts_to_skip)}",
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

        # 5. 批量安装驱动
        install_results = self._install_driver_batch(hosts_deps_ok, package_paths, target_version)
        results.update(install_results)

        # 汇总结果
        success_count = sum(1 for r in results.values() if r.get("success"))
        failed_hosts = [h for h, r in results.items() if not r.get("success")]

        message = f"NVIDIA驱动处理完成，成功: {success_count}/{len(hosts)}"
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
        cmd = "nvidia-smi -L"
        result = self.execute_batch(hosts, cmd, sudo=False)
        return all(r.success for r in result.results.values())
