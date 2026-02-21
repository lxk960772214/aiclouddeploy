"""
步骤22: 安装NVIDIA GPU驱动
"""

from typing import List
from src.steps.base import BaseStep, StepResult, StepStatus


class NVIDIADriver(BaseStep):
    """安装NVIDIA GPU驱动"""

    step_id = "22"
    step_name = "安装NVIDIA GPU驱动"
    step_description = "安装NVIDIA GPU驱动程序"
    requires_sudo = True
    supports_batch = False
    requires_reboot = True
    timeout = 1200  # 20分钟

    def execute(self, hosts: List[str]) -> StepResult:
        """执行NVIDIA驱动安装"""
        results = {}

        driver_config = self.versions.nvidia_driver
        version = driver_config.version
        driver_file = driver_config.local_file or f"/tmp/NVIDIA-Linux-x86_64-{version}.run"

        for host in hosts:
            self.logger.info(f"[{host}] 开始安装NVIDIA驱动 {version}...")

            # 1. 安装依赖
            deps_cmd = "apt-get install -y libvulkan1 mesa-vulkan-drivers vulkan-tools libglvnd-dev"
            deps_result = self.execute_on_host(host, deps_cmd, sudo=True)

            # 2. 检查驱动文件
            check_cmd = f"test -f {driver_file} && echo 'exists' || echo 'not_found'"
            check_result = self.execute_on_host(host, check_cmd)

            if "not_found" in check_result.get("stdout", ""):
                results[host] = {"success": False, "error": f"驱动文件不存在: {driver_file}"}
                continue

            # 3. 安装驱动
            install_cmd = f"chmod +x {driver_file} && {driver_file} -s --dkms"
            install_result = self.execute_on_host(host, install_cmd, sudo=True)
            results[host] = {"install": install_result}

            # 4. 复制vulkan配置
            vulkan_cmd = "cp /etc/vulkan/icd.d/nvidia_icd.json /usr/share/vulkan/icd.d/ 2>/dev/null || true"
            self.execute_on_host(host, vulkan_cmd, sudo=True)

            # 5. 验证
            if install_result["success"]:
                verify_cmd = "nvidia-smi"
                verify_result = self.execute_on_host(host, verify_cmd)
                results[host]["verify"] = verify_result

                if verify_result["success"]:
                    results[host]["success"] = True
                else:
                    results[host]["success"] = False
                    results[host]["error"] = "nvidia-smi验证失败"
            else:
                results[host]["success"] = False
                results[host]["error"] = "驱动安装失败"

        success_count = sum(1 for r in results.values() if r.get("success"))

        return StepResult(
            step_id=self.step_id,
            step_name=self.step_name,
            status=StepStatus.SUCCESS if success_count == len(hosts) else StepStatus.FAILED,
            message=f"NVIDIA驱动安装完成，成功: {success_count}/{len(hosts)}",
            host_results=results
        )

    def post_check(self, hosts: List[str]) -> bool:
        """验证驱动安装"""
        cmd = "nvidia-smi -L"
        result = self.execute_batch(hosts, cmd, sudo=False)
        return all(r.success for r in result.results.values())
