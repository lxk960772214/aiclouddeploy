"""
步骤24: 安装CUDA Toolkit
"""

from typing import List
from src.steps.base import BaseStep, StepResult, StepStatus


class CUDAToolkit(BaseStep):
    """安装CUDA Toolkit"""

    step_id = "24"
    step_name = "安装CUDA Toolkit"
    step_description = "安装NVIDIA CUDA Toolkit"
    requires_sudo = True
    supports_batch = False
    timeout = 1800  # 30分钟

    def execute(self, hosts: List[str]) -> StepResult:
        """执行CUDA Toolkit安装"""
        results = {}

        cuda_config = self.versions.cuda
        version = cuda_config.version
        toolkit_file = cuda_config.local_file or f"/tmp/cuda_{version}_linux.run"

        for host in hosts:
            self.logger.info(f"[{host}] 开始安装CUDA Toolkit {version}...")

            # 1. 检查安装文件
            check_cmd = f"test -f {toolkit_file} && echo 'exists' || echo 'not_found'"
            check_result = self.execute_on_host(host, check_cmd)

            if "not_found" in check_result.get("stdout", ""):
                results[host] = {"success": False, "error": f"CUDA安装文件不存在: {toolkit_file}"}
                continue

            # 2. 安装CUDA Toolkit
            install_cmd = f"chmod +x {toolkit_file} && {toolkit_file} --toolkit --no-drm --silent"
            install_result = self.execute_on_host(host, install_cmd, sudo=True)
            results[host] = {"install": install_result}

            if not install_result["success"]:
                results[host]["success"] = False
                results[host]["error"] = "CUDA Toolkit安装失败"
                continue

            # 3. 配置环境变量
            cuda_path = "/usr/local/cuda"
            env_cmd = f'''
echo "export PATH={cuda_path}/bin:\\$PATH" >> /etc/profile
echo "export LD_LIBRARY_PATH={cuda_path}/lib64:\\$LD_LIBRARY_PATH" >> /etc/profile
'''
            self.execute_on_host(host, env_cmd, sudo=True)

            # 4. 验证
            verify_cmd = f"{cuda_path}/bin/nvcc -V"
            verify_result = self.execute_on_host(host, verify_cmd)
            results[host]["verify"] = verify_result

            if verify_result["success"] and version in verify_result.get("stdout", ""):
                results[host]["success"] = True
            else:
                results[host]["success"] = False
                results[host]["error"] = "CUDA版本验证失败"

        success_count = sum(1 for r in results.values() if r.get("success"))

        return StepResult(
            step_id=self.step_id,
            step_name=self.step_name,
            status=StepStatus.SUCCESS if success_count == len(hosts) else StepStatus.FAILED,
            message=f"CUDA Toolkit安装完成，成功: {success_count}/{len(hosts)}",
            host_results=results
        )

    def post_check(self, hosts: List[str]) -> bool:
        """验证CUDA安装"""
        cmd = "/usr/local/cuda/bin/nvcc -V | head -1"
        result = self.execute_batch(hosts, cmd, sudo=False)
        return all(r.success for r in result.results.values())
