"""
步骤23: 安装nvidia-fabricmanager
"""

from typing import List
from src.steps.base import BaseStep, StepResult, StepStatus


class FabricManager(BaseStep):
    """安装nvidia-fabricmanager"""

    step_id = "23"
    step_name = "安装nvidia-fabricmanager"
    step_description = "安装NVIDIA Fabric Manager（NVLink显卡需要）"
    requires_sudo = True
    supports_batch = False
    can_skip = True  # 非NVLink显卡可跳过

    def _has_nvlink(self, host: str) -> bool:
        """检查是否有NVLink"""
        cmd = "nvidia-smi nvlink --status 2>/dev/null | grep -q 'GPU'"
        result = self.execute_on_host(host, cmd)
        return result.get("success", False)

    def execute(self, hosts: List[str]) -> StepResult:
        """执行Fabric Manager安装"""
        results = {}
        installed = []
        skipped = []

        driver_config = self.versions.nvidia_driver
        version = driver_config.version

        for host in hosts:
            # 检查是否有NVLink
            if not self._has_nvlink(host):
                self.logger.info(f"[{host}] 未检测到NVLink，跳过安装")
                skipped.append(host)
                results[host] = {"success": True, "skipped": True}
                continue

            self.logger.info(f"[{host}] 检测到NVLink，安装Fabric Manager...")

            # 获取驱动主版本号
            major_version = version.split('.')[0]

            # 下载并安装
            deb_file = f"/tmp/nvidia-fabricmanager-{major_version}_{version}-1_amd64.deb"
            download_cmd = f"wget -q https://developer.download.nvidia.cn/compute/cuda/repos/ubuntu2204/x86_64/nvidia-fabricmanager-{major_version}_{version}-1_amd64.deb -O {deb_file}"
            download_result = self.execute_on_host(host, download_cmd, sudo=True)

            if not download_result["success"]:
                results[host] = {"success": False, "error": "下载Fabric Manager失败"}
                continue

            # 安装
            install_cmd = f"dpkg -i {deb_file}"
            install_result = self.execute_on_host(host, install_cmd, sudo=True)

            if not install_result["success"]:
                results[host] = {"success": False, "error": "安装Fabric Manager失败"}
                continue

            # 启用服务
            enable_cmd = "systemctl daemon-reload && systemctl enable nvidia-fabricmanager.service && systemctl start nvidia-fabricmanager.service"
            enable_result = self.execute_on_host(host, enable_cmd, sudo=True)

            # 验证
            verify_cmd = "systemctl is-active nvidia-fabricmanager.service"
            verify_result = self.execute_on_host(host, verify_cmd)

            if verify_result.get("stdout", "").strip() == "active":
                results[host] = {"success": True}
                installed.append(host)
            else:
                results[host] = {"success": False, "error": "Fabric Manager服务未正常启动"}

        return StepResult(
            step_id=self.step_id,
            step_name=self.step_name,
            status=StepStatus.SUCCESS,
            message=f"Fabric Manager安装完成，已安装: {len(installed)}，跳过: {len(skipped)}",
            details={"installed": installed, "skipped": skipped},
            host_results=results
        )

    def post_check(self, hosts: List[str]) -> bool:
        """验证Fabric Manager"""
        # 非所有机器都需要，跳过验证
        return True
