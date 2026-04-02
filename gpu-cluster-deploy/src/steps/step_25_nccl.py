"""
步骤25: 安装NCCL通信库
"""

from typing import List
from src.steps.base import BaseStep, StepResult, StepStatus


class NCCLInstall(BaseStep):
    """安装NCCL通信库"""

    step_id = "25"
    step_name = "安装NCCL通信库"
    step_description = "安装NCCL通信库（可选）"
    requires_sudo = True
    supports_batch = False
    can_skip = True
    timeout = 1800  # 30分钟

    def is_configured(self, host: str) -> tuple:
        """
        检查NCCL是否已安装

        Args:
            host: 主机地址

        Returns:
            tuple[bool, str]: (是否已配置, 检查详情)
        """
        nccl_config = self.versions.nccl if hasattr(self, 'versions') and self.versions else None

        if not nccl_config or not nccl_config.enabled:
            return True, "NCCL未启用，跳过"

        install_path = nccl_config.install_path

        # 检查NCCL库文件
        result = self.execute_on_host(host, f"test -d {install_path}/lib && ls {install_path}/lib/ 2>/dev/null | head -3", timeout=30)

        if result.get("success") and result.get("stdout", "").strip():
            return True, f"NCCL已安装: {install_path}"

        return False, "NCCL未安装"

    def execute(self, hosts: List[str]) -> StepResult:
        """执行NCCL安装"""
        results = {}

        nccl_config = self.versions.nccl

        if not nccl_config.enabled:
            self.logger.info("NCCL未启用，跳过安装")
            return StepResult(
                step_id=self.step_id,
                step_name=self.step_name,
                status=StepStatus.SKIPPED,
                message="NCCL未启用，跳过安装"
            )

        install_path = nccl_config.install_path

        for host in hosts:
            self.logger.info(f"[{host}] 开始安装NCCL...")

            # 1. 获取GPU计算能力
            cap_cmd = "nvidia-smi --query-gpu=compute_cap --format=csv,noheader | head -1"
            cap_result = self.execute_on_host(host, cap_cmd)

            if not cap_result["success"]:
                results[host] = {"success": False, "error": "获取GPU计算能力失败"}
                continue

            compute_cap = cap_result["stdout"].strip().replace(".", "")
            self.logger.info(f"[{host}] GPU计算能力: {compute_cap}")

            # 2. 克隆NCCL源码
            clone_cmd = f"rm -rf /tmp/nccl && cd /tmp && git clone https://github.com/NVIDIA/nccl.git"
            clone_result = self.execute_on_host(host, clone_cmd, sudo=True)

            if not clone_result["success"]:
                results[host] = {"success": False, "error": "克隆NCCL源码失败"}
                continue

            # 3. 编译NCCL
            compile_cmd = f'''
cd /tmp/nccl
mkdir -p {install_path}
make -j$(nproc) src.build BUILDDIR={install_path} CUDA_HOME=/usr/local/cuda NVCC_GENCODE="-gencode=arch=compute_{compute_cap},code=sm_{compute_cap}"
'''
            compile_result = self.execute_on_host(host, compile_cmd, sudo=True, timeout=1200)
            results[host] = {"compile": compile_result}

            if not compile_result["success"]:
                results[host]["success"] = False
                results[host]["error"] = "NCCL编译失败"
                continue

            # 4. 配置环境变量
            env_cmd = f'''
grep -q "NCCL" /etc/profile || echo "export LD_LIBRARY_PATH=\\$LD_LIBRARY_PATH:{install_path}/lib" >> /etc/profile
grep -q "NCCL" /etc/profile || echo "export PATH=\\$PATH:{install_path}/bin" >> /etc/profile
'''
            self.execute_on_host(host, env_cmd, sudo=True)

            # 5. 验证
            verify_cmd = f"test -d {install_path}/lib && ls {install_path}/lib/"
            verify_result = self.execute_on_host(host, verify_cmd)
            results[host]["verify"] = verify_result

            if verify_result["success"]:
                results[host]["success"] = True
            else:
                results[host]["success"] = False
                results[host]["error"] = "NCCL库验证失败"

        success_count = sum(1 for r in results.values() if r.get("success"))

        return StepResult(
            step_id=self.step_id,
            step_name=self.step_name,
            status=StepStatus.SUCCESS if success_count == len(hosts) else StepStatus.FAILED,
            message=f"NCCL安装完成，成功: {success_count}/{len(hosts)}",
            details={"install_path": install_path},
            host_results=results
        )

    def post_check(self, hosts: List[str]) -> bool:
        """验证NCCL安装"""
        # 可选步骤，跳过验证
        return True
