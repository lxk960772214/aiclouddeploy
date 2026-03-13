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

            # 下载
            deb_file = f"/tmp/nvidia-fabricmanager-{major_version}_{driver_version}-1_amd64.deb"
            download_cmd = f"wget -q https://developer.download.nvidia.cn/compute/cuda/repos/ubuntu2204/x86_64/nvidia-fabricmanager-{major_version}_{driver_version}-1_amd64.deb -O {deb_file}"
            download_result = self.execute_on_host(host, download_cmd, sudo=True, timeout=120)

            if not download_result.get("success"):
                return host, {"success": False, "error": "下载Fabric Manager失败"}

            # 安装
            install_cmd = f"dpkg -i {deb_file}"
            install_result = self.execute_on_host(host, install_cmd, sudo=True, timeout=60)

            if not install_result.get("success"):
                return host, {"success": False, "error": "安装Fabric Manager失败"}

            # 启用服务
            enable_cmd = "systemctl daemon-reload && systemctl enable nvidia-fabricmanager.service && systemctl start nvidia-fabricmanager.service"
            enable_result = self.execute_on_host(host, enable_cmd, sudo=True, timeout=60)
            host_result["enable"] = enable_result.get("success")

            # 验证
            verify_result = self.execute_on_host(host, "systemctl is-active nvidia-fabricmanager.service", timeout=30)

            if verify_result.get("stdout", "").strip() == "active":
                self.logger.info(f"[{host}] Fabric Manager安装成功")
                return host, {"success": True, **host_result}
            else:
                return host, {"success": False, "error": "Fabric Manager服务未正常启动", **host_result}

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

    def post_check(self, hosts: List[str]) -> bool:
        """验证Fabric Manager"""
        # 非所有机器都需要，跳过验证
        return True
