"""
步骤23: 安装nvidia-fabricmanager

功能增强:
- 批量并行执行
- 智能检测NVLink
"""

from typing import List, Dict, Tuple
from src.steps.base import BaseStep, StepResult, StepStatus
from concurrent.futures import ThreadPoolExecutor, as_completed


class FabricManager(BaseStep):
    """安装nvidia-fabricmanager"""

    step_id = "23"
    step_name = "安装nvidia-fabricmanager"
    step_description = "安装NVIDIA Fabric Manager（NVLink显卡需要）"
    requires_sudo = True
    supports_batch = True  # 改为支持批量执行
    can_skip = True  # 非NVLink显卡可跳过
    is_optional = True  # 标记为可选组件，失败不影响整体流程

    def _check_nvlink_batch(self, hosts: List[str]) -> Dict[str, bool]:
        """批量检查是否有NVLink"""
        self.logger.info(f"[{self.step_id}] 批量检查NVLink状态...")
        results = {}

        def check_single(host: str) -> Tuple[str, bool]:
            result = self.execute_on_host(
                host,
                "nvidia-smi nvlink --status 2>/dev/null | grep -q 'GPU' && echo 'yes' || echo 'no'",
                timeout=30
            )
            has_nvlink = "yes" in result.get("stdout", "")
            return host, has_nvlink

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = {executor.submit(check_single, host): host for host in hosts}
            for future in as_completed(futures):
                host, has_nvlink = future.result()
                results[host] = has_nvlink
                if has_nvlink:
                    self.logger.info(f"[{host}] 检测到NVLink")
                else:
                    self.logger.info(f"[{host}] 未检测到NVLink")

        return results

    def _install_fabricmanager_batch(self, hosts: List[str], driver_version: str) -> Dict[str, dict]:
        """批量安装Fabric Manager"""
        self.logger.info(f"[{self.step_id}] 批量安装Fabric Manager（{len(hosts)}个节点）...")
        results = {}

        # 获取驱动主版本号
        major_version = driver_version.split('.')[0]

        def install_single(host: str) -> Tuple[str, dict]:
            host_result = {}
            install_success = False

            # 检测系统版本和架构
            os_result = self.execute_on_host(host, "cat /etc/os-release | grep VERSION_ID | cut -d'\"' -f2", timeout=10)
            os_version = os_result.get("stdout", "22.04").strip()
            arch_result = self.execute_on_host(host, "dpkg --print-architecture", timeout=10)
            arch = arch_result.get("stdout", "amd64").strip()
            # Ubuntu 24.04 -> ubuntu2404, Ubuntu 22.04 -> ubuntu2204
            repo_name = f"ubuntu{os_version.replace('.', '')}"
            self.logger.info(f"[{host}] 检测到系统版本: Ubuntu {os_version}, 架构: {arch}, 使用仓库: {repo_name}")

            deb_file = f"/tmp/nvidia-fabricmanager-{major_version}_{driver_version}-1_{arch}.deb"

            # 方法1: 尝试从 NVIDIA 官方仓库下载（支持多个 Ubuntu 版本）
            download_urls = [
                # 当前系统版本的仓库
                f"https://developer.download.nvidia.com/compute/cuda/repos/{repo_name}/{arch}/nvidia-fabricmanager-{major_version}_{driver_version}-1_{arch}.deb",
                f"https://developer.download.nvidia.cn/compute/cuda/repos/{repo_name}/{arch}/nvidia-fabricmanager-{major_version}_{driver_version}-1_{arch}.deb",
                # 回退到常用版本的仓库
                f"https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2404/{arch}/nvidia-fabricmanager-{major_version}_{driver_version}-1_{arch}.deb",
                f"https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2204/{arch}/nvidia-fabricmanager-{major_version}_{driver_version}-1_{arch}.deb",
                f"https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2004/{arch}/nvidia-fabricmanager-{major_version}_{driver_version}-1_{arch}.deb",
            ]

            for url in download_urls:
                self.logger.info(f"[{host}] 尝试下载: {url}")
                # 使用智能下载（监控文件增长，无固定超时）
                download_result = self.smart_download(
                    host, url, deb_file,
                    sudo=True,
                    stall_timeout=120,  # FabricManager包较小，2分钟无增长即可判断失败
                    total_timeout=600   # 总超时10分钟
                )
                if download_result.get("success"):
                    self.logger.info(f"[{host}] 下载成功")
                    # 使用 dpkg 安装
                    install_cmd = f"dpkg -i {deb_file} 2>&1 || apt-get install -f -y"
                    install_result = self.execute_on_host(host, install_cmd, sudo=True, timeout=120)
                    if install_result.get("success"):
                        install_success = True
                        break
                else:
                    self.logger.warning(f"[{host}] 下载失败，尝试下一个源")

            # 方法2: 如果下载失败，尝试使用 apt 安装
            if not install_success:
                self.logger.info(f"[{host}] 尝试使用 apt 安装 fabricmanager...")
                # 添加 NVIDIA CUDA 仓库（使用智能下载）
                keyring_url = f"https://developer.download.nvidia.com/compute/cuda/repos/{repo_name}/{arch}/cuda-keyring_1.1-1_all.deb"
                keyring_result = self.smart_download(
                    host, keyring_url, "/tmp/cuda-keyring.deb",
                    sudo=True,
                    stall_timeout=60,
                    total_timeout=120
                )
                if keyring_result.get("success"):
                    self.execute_on_host(host, "dpkg -i /tmp/cuda-keyring.deb && apt-get update -qq", sudo=True, timeout=60)

                # 尝试安装 fabricmanager
                apt_packages = [
                    f"nvidia-fabricmanager-{major_version}",
                    f"cuda-drivers-fabricmanager-{major_version}",
                    "nvidia-fabricmanager-dev",
                ]
                for pkg in apt_packages:
                    apt_cmd = f"apt-get install -y {pkg} 2>&1"
                    apt_result = self.execute_on_host(host, apt_cmd, sudo=True, timeout=180)
                    if apt_result.get("success") and "unable to locate package" not in apt_result.get("stdout", "").lower():
                        self.logger.info(f"[{host}] apt 安装 {pkg} 成功")
                        install_success = True
                        break

            if not install_success:
                return host, {"success": False, "error": "Fabric Manager安装失败（所有方法均不可用）"}

            # 启用服务
            enable_cmd = "systemctl daemon-reload && systemctl enable nvidia-fabricmanager.service 2>/dev/null && systemctl start nvidia-fabricmanager.service 2>/dev/null"
            enable_result = self.execute_on_host(host, enable_cmd, sudo=True, timeout=60)
            host_result["enable"] = enable_result.get("success")

            # 验证
            verify_result = self.execute_on_host(host, "systemctl is-active nvidia-fabricmanager.service 2>/dev/null || echo 'inactive'", timeout=30)

            if verify_result.get("stdout", "").strip() == "active":
                self.logger.info(f"[{host}] Fabric Manager安装成功")
                return host, {"success": True, **host_result}
            else:
                # 服务可能需要重启才能启动
                self.logger.warning(f"[{host}] Fabric Manager服务未启动，可能需要重启")
                return host, {"success": True, "warning": "Fabric Manager服务未启动，可能需要重启", **host_result}

        # 并行安装
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {executor.submit(install_single, host): host for host in hosts}
            for future in as_completed(futures):
                host, result = future.result()
                results[host] = result
                status = "✓" if result.get("success") else "✗"
                self.logger.info(f"[{host}] {status} Fabric Manager安装{'成功' if result.get('success') else '失败'}")

        return results

    def execute(self, hosts: List[str]) -> StepResult:
        """执行Fabric Manager安装（批量模式）"""
        results = {}

        driver_config = self.versions.nvidia_driver
        version = driver_config.version

        self.logger.info("=" * 60)
        self.logger.info("Fabric Manager安装流程（批量模式）")
        self.logger.info(f"驱动版本: {version}")
        self.logger.info(f"目标节点: {len(hosts)} 个")
        self.logger.info("=" * 60)

        # 1. 批量检查NVLink
        nvlink_status = self._check_nvlink_batch(hosts)

        hosts_with_nvlink = [h for h, has_nvlink in nvlink_status.items() if has_nvlink]
        hosts_without_nvlink = [h for h, has_nvlink in nvlink_status.items() if not has_nvlink]

        # 标记无NVLink的节点为跳过
        for host in hosts_without_nvlink:
            results[host] = {"success": True, "skipped": True, "reason": "no_nvlink"}
            self.logger.info(f"[{host}] 未检测到NVLink，跳过安装")

        if not hosts_with_nvlink:
            self.logger.info("所有节点均无NVLink，跳过Fabric Manager安装")
            return StepResult(
                step_id=self.step_id,
                step_name=self.step_name,
                status=StepStatus.SUCCESS,
                message="跳过Fabric Manager安装（无NVLink设备）",
                host_results=results
            )

        self.logger.info(f"检测到 {len(hosts_with_nvlink)} 个节点有NVLink，开始安装...")

        # 2. 批量安装Fabric Manager
        install_results = self._install_fabricmanager_batch(hosts_with_nvlink, version)
        results.update(install_results)

        # 汇总结果
        installed = [h for h, r in results.items() if r.get("success") and not r.get("skipped")]
        skipped = [h for h, r in results.items() if r.get("skipped")]
        failed = [h for h, r in results.items() if not r.get("success")]

        message = f"Fabric Manager安装完成，已安装: {len(installed)}，跳过: {len(skipped)}"
        if failed:
            message += f"，失败: {failed}"

        return StepResult(
            step_id=self.step_id,
            step_name=self.step_name,
            status=StepStatus.SUCCESS if not failed else StepStatus.FAILED,
            message=message,
            details={"installed": installed, "skipped": skipped, "failed": failed},
            host_results=results
        )

    def is_configured(self, host: str) -> tuple:
        """
        检查Fabric Manager是否已配置

        Args:
            host: 主机地址

        Returns:
            tuple[bool, str]: (是否已配置, 检查详情)
        """
        # 先检查是否有NVLink
        nvlink_result = self.execute_on_host(
            host,
            "nvidia-smi nvlink --status 2>/dev/null | grep -q 'GPU' && echo 'yes' || echo 'no'",
            timeout=30
        )
        has_nvlink = "yes" in nvlink_result.get("stdout", "")

        if not has_nvlink:
            return True, "无NVLink设备，不需要Fabric Manager"

        # 检查服务状态
        result = self.execute_on_host(
            host,
            "systemctl is-active nvidia-fabricmanager 2>/dev/null || echo 'inactive'",
            timeout=30
        )
        status = result.get("stdout", "").strip()

        if status == "active":
            return True, "服务运行中"
        else:
            # 检查是否已安装但未运行
            check_result = self.execute_on_host(
                host,
                "which nvidia-fabricmanager 2>/dev/null || which nv-fabricmanager 2>/dev/null || echo 'not_installed'",
                timeout=10
            )
            if "not_installed" in check_result.get("stdout", ""):
                return False, "未安装"
            else:
                return False, f"已安装但服务{status}"

    def post_check(self, hosts: List[str]) -> bool:
        """验证Fabric Manager"""
        # 非所有机器都需要，跳过验证
        return True
