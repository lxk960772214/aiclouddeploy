"""
步骤22: 安装NVIDIA GPU驱动

功能增强:
- 检测现有NVIDIA驱动版本
- 自动卸载不匹配的旧版本驱动
- 清理残留内核模块和文件
- 安装指定版本驱动
"""

from typing import List, Optional, Tuple
from src.steps.base import BaseStep, StepResult, StepStatus


class NVIDIADriver(BaseStep):
    """安装NVIDIA GPU驱动"""

    step_id = "22"
    step_name = "安装NVIDIA GPU驱动"
    step_description = "安装NVIDIA GPU驱动程序（支持自动卸载旧版本）"
    requires_sudo = True
    supports_batch = False
    requires_reboot = True
    timeout = 1800  # 30分钟（卸载+安装可能需要更长时间）

    def _detect_existing_driver(self, host: str) -> Tuple[bool, Optional[str]]:
        """
        检测节点上是否已安装NVIDIA驱动

        Returns:
            Tuple[bool, Optional[str]]: (是否安装, 版本号)
        """
        # 方法1: 使用 nvidia-smi 检测
        result = self.execute_on_host(host, "nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null | head -1")
        if result.get("success") and result.get("stdout", "").strip():
            version = result["stdout"].strip()
            self.logger.info(f"[{host}] 检测到已安装驱动版本: {version}")
            return True, version

        # 方法2: 检查 /proc/driver/nvidia/version
        result = self.execute_on_host(host, "cat /proc/driver/nvidia/version 2>/dev/null | grep 'NVRM version' | awk '{print $8}'")
        if result.get("success") and result.get("stdout", "").strip():
            version = result["stdout"].strip()
            self.logger.info(f"[{host}] 检测到已安装驱动版本: {version}")
            return True, version

        # 方法3: 检查内核模块
        result = self.execute_on_host(host, "modinfo nvidia 2>/dev/null | grep '^version:' | awk '{print $2}'")
        if result.get("success") and result.get("stdout", "").strip():
            version = result["stdout"].strip()
            self.logger.info(f"[{host}] 检测到内核模块版本: {version}")
            return True, version

        self.logger.info(f"[{host}] 未检测到已安装的NVIDIA驱动")
        return False, None

    def _uninstall_existing_driver(self, host: str, current_version: Optional[str] = None) -> dict:
        """
        卸载现有的NVIDIA驱动

        Args:
            host: 目标主机
            current_version: 当前驱动版本（用于日志）

        Returns:
            卸载结果
        """
        self.logger.info(f"[{host}] 开始卸载现有NVIDIA驱动{f' (版本: {current_version})' if current_version else ''}...")

        results = {}

        # 1. 停止使用GPU的进程
        self.logger.info(f"[{host}] 停止GPU相关进程...")
        stop_cmds = [
            "pkill -9 -f nvidia-persistenced || true",
            "pkill -9 -f fabricmanager || true",
            "systemctl stop nvidia-persistenced || true",
            "systemctl stop nvidia-fabricmanager || true",
        ]
        for cmd in stop_cmds:
            self.execute_on_host(host, cmd, sudo=True)

        # 2. 卸载内核模块（按依赖顺序反向卸载）
        self.logger.info(f"[{host}] 卸载NVIDIA内核模块...")
        modules = [
            "nvidia_uvm",
            "nvidia_drm",
            "nvidia_modeset",
            "nvidia_peermem",
            "nvidia_nvswitch",
            "nvidia"
        ]
        for module in modules:
            result = self.execute_on_host(host, f"modprobe -r {module} 2>/dev/null || true", sudo=True)
            self.logger.debug(f"[{host}] 卸载模块 {module}: {'成功' if result.get('success') else '跳过'}")

        # 3. 使用NVIDIA官方卸载工具（如果存在）
        self.logger.info(f"[{host}] 尝试使用官方卸载工具...")
        uninstall_result = self.execute_on_host(
            host,
            "test -f /usr/bin/nvidia-uninstall && /usr/bin/nvidia-uninstall -s || echo 'no_official_uninstaller'",
            sudo=True
        )
        results["official_uninstall"] = uninstall_result

        # 4. 清理apt安装的NVIDIA包
        self.logger.info(f"[{host}] 清理apt安装的NVIDIA包...")
        apt_purge_result = self.execute_on_host(
            host,
            "apt-get purge -y '*nvidia*' '*libnvidia*' '*cuda*' 2>/dev/null || true",
            sudo=True
        )
        results["apt_purge"] = apt_purge_result

        # 5. 清理残留文件
        self.logger.info(f"[{host}] 清理残留文件...")
        cleanup_cmds = [
            "rm -rf /usr/lib/nvidia-* 2>/dev/null || true",
            "rm -rf /usr/share/nvidia/ 2>/dev/null || true",
            "rm -rf /var/log/nvidia* 2>/dev/null || true",
            "rm -f /etc/modprobe.d/nvidia*.conf 2>/dev/null || true",
            "rm -f /usr/share/glvnd/egl_vendor.d/10_nvidia.json 2>/dev/null || true",
            "rm -f /etc/vulkan/icd.d/nvidia_icd.json 2>/dev/null || true",
            "rm -f /usr/share/vulkan/icd.d/nvidia_icd.json 2>/dev/null || true",
            "rm -f /etc/init.d/nvidia* 2>/dev/null || true",
            "rm -f /etc/systemd/system/nvidia*.service 2>/dev/null || true",
            "rm -f /lib/udev/rules.d/*nvidia*.rules 2>/dev/null || true",
        ]
        for cmd in cleanup_cmds:
            self.execute_on_host(host, cmd, sudo=True)

        # 6. 清理DKMS模块
        self.logger.info(f"[{host}] 清理DKMS模块...")
        dkms_result = self.execute_on_host(
            host,
            "for v in $(dkms status nvidia 2>/dev/null | awk '{print $2}'); do dkms remove nvidia/$v --all 2>/dev/null || true; done",
            sudo=True
        )
        results["dkms_cleanup"] = dkms_result

        # 7. 自动清理
        self.execute_on_host(host, "apt-get autoremove -y 2>/dev/null || true", sudo=True)

        # 8. 验证卸载结果
        verify_result = self.execute_on_host(host, "lsmod | grep nvidia || echo 'no_nvidia_modules'")
        if "no_nvidia_modules" in verify_result.get("stdout", ""):
            self.logger.info(f"[{host}] 卸载成功，无残留内核模块")
            results["success"] = True
        else:
            self.logger.warning(f"[{host}] 可能存在残留内核模块")
            results["success"] = True  # 继续安装，让安装器处理

        return results

    def _install_driver(self, host: str, version: str, driver_file: str) -> dict:
        """
        安装NVIDIA驱动

        Args:
            host: 目标主机
            version: 目标版本
            driver_file: 驱动安装文件路径

        Returns:
            安装结果
        """
        self.logger.info(f"[{host}] 开始安装NVIDIA驱动 {version}...")

        results = {}

        # 1. 安装依赖
        self.logger.info(f"[{host}] 安装依赖包...")
        deps_cmd = "apt-get update && apt-get install -y build-essential dkms libvulkan1 mesa-vulkan-drivers vulkan-tools libglvnd-dev"
        deps_result = self.execute_on_host(host, deps_cmd, sudo=True)
        results["deps"] = deps_result

        if not deps_result.get("success"):
            results["success"] = False
            results["error"] = "依赖安装失败"
            return results

        # 2. 检查驱动文件
        check_cmd = f"test -f {driver_file} && echo 'exists' || echo 'not_found'"
        check_result = self.execute_on_host(host, check_cmd)

        if "not_found" in check_result.get("stdout", ""):
            results["success"] = False
            results["error"] = f"驱动文件不存在: {driver_file}"
            return results

        # 3. 禁用nouveau（如果尚未禁用）
        self.logger.info(f"[{host}] 确保nouveau已禁用...")
        nouveau_check = self.execute_on_host(host, "lsmod | grep nouveau || echo 'nouveau_disabled'")
        if "nouveau_disabled" not in nouveau_check.get("stdout", ""):
            self.execute_on_host(host, "modprobe -r nouveau 2>/dev/null || true", sudo=True)

        # 4. 执行驱动安装
        self.logger.info(f"[{host}] 执行驱动安装...")
        install_cmd = f"chmod +x {driver_file} && {driver_file} -s --dkms --no-cc-version-check"
        install_result = self.execute_on_host(host, install_cmd, sudo=True, timeout=900)
        results["install"] = install_result

        if not install_result.get("success"):
            results["success"] = False
            results["error"] = f"驱动安装失败: {install_result.get('stderr', '未知错误')}"
            return results

        # 5. 复制vulkan配置
        vulkan_cmd = "mkdir -p /usr/share/vulkan/icd.d && cp /etc/vulkan/icd.d/nvidia_icd.json /usr/share/vulkan/icd.d/ 2>/dev/null || true"
        self.execute_on_host(host, vulkan_cmd, sudo=True)

        # 6. 加载内核模块
        self.logger.info(f"[{host}] 加载NVIDIA内核模块...")
        modprobe_result = self.execute_on_host(host, "modprobe nvidia", sudo=True)
        results["modprobe"] = modprobe_result

        # 7. 验证安装
        self.logger.info(f"[{host}] 验证驱动安装...")
        verify_result = self.execute_on_host(host, "nvidia-smi")
        results["verify"] = verify_result

        if verify_result.get("success"):
            # 获取安装后的版本
            version_result = self.execute_on_host(host, "nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null | head -1")
            installed_version = version_result.get("stdout", "").strip() if version_result.get("success") else "unknown"
            self.logger.info(f"[{host}] 驱动安装成功，版本: {installed_version}")
            results["success"] = True
            results["installed_version"] = installed_version
        else:
            results["success"] = False
            results["error"] = "nvidia-smi验证失败，可能需要重启"

        return results

    def execute(self, hosts: List[str]) -> StepResult:
        """执行NVIDIA驱动安装"""
        results = {}

        driver_config = self.versions.nvidia_driver
        target_version = driver_config.version
        driver_file = driver_config.local_file or f"/tmp/NVIDIA-Linux-x86_64-{target_version}.run"

        for host in hosts:
            self.logger.info(f"[{host}] ========== NVIDIA驱动安装流程开始 ==========")
            self.logger.info(f"[{host}] 目标版本: {target_version}")

            host_result = {"target_version": target_version}

            # 1. 检测现有驱动
            has_driver, current_version = self._detect_existing_driver(host)
            host_result["existing_driver"] = has_driver
            host_result["current_version"] = current_version

            # 2. 判断是否需要卸载
            need_uninstall = False
            if has_driver:
                if current_version:
                    # 版本比较（简化：直接字符串比较，实际可能需要更复杂的版本比较）
                    if current_version != target_version:
                        self.logger.info(f"[{host}] 检测到版本不匹配: 当前={current_version}, 目标={target_version}")
                        need_uninstall = True
                    else:
                        self.logger.info(f"[{host}] 版本匹配，跳过安装: {target_version}")
                        host_result["success"] = True
                        host_result["action"] = "skipped_version_match"
                        results[host] = host_result
                        continue
                else:
                    # 有驱动但无法确定版本，安全起见卸载
                    need_uninstall = True

            # 3. 卸载旧驱动（如果需要）
            if need_uninstall:
                self.logger.info(f"[{host}] 执行旧驱动卸载...")
                uninstall_result = self._uninstall_existing_driver(host, current_version)
                host_result["uninstall"] = uninstall_result

                # 等待系统稳定
                import time
                time.sleep(2)

            # 4. 安装新驱动
            install_result = self._install_driver(host, target_version, driver_file)
            host_result["install"] = install_result

            if install_result.get("success"):
                host_result["success"] = True
                host_result["action"] = "installed"
            else:
                host_result["success"] = False
                host_result["error"] = install_result.get("error", "安装失败")

            results[host] = host_result
            self.logger.info(f"[{host}] ========== NVIDIA驱动安装流程结束 ==========")

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
