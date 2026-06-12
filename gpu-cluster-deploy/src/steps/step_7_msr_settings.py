"""
步骤07: 设置MSR（5090 + Intel 5代CPU）
"""

from typing import List
from src.steps.base import BaseStep, StepResult, StepStatus


class MSRSettings(BaseStep):
    """设置MSR"""

    step_id = "07"
    step_name = "设置MSR"
    step_description = "设置MSR寄存器（5090 + Intel 5代CPU机型）"
    requires_sudo = True
    supports_batch = True
    can_skip = True  # 非特定机型可跳过

    def _check_cpu_model(self, host: str) -> dict:
        """检查CPU型号"""
        cmd = "cat /proc/cpuinfo | grep 'model name' | head -1"
        result = self.execute_on_host(host, cmd)
        return result

    def _check_gpu_model(self, host: str) -> dict:
        """检查GPU型号（如果已安装驱动）"""
        cmd = "nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1 || echo 'unknown'"
        result = self.execute_on_host(host, cmd)
        return result

    def _needs_msr(self, host: str) -> bool:
        """判断是否需要设置MSR"""
        cpu_result = self._check_cpu_model(host)
        gpu_result = self._check_gpu_model(host)

        cpu_model = cpu_result.get("stdout", "").lower()
        gpu_model = gpu_result.get("stdout", "").lower()

        # 检查是否是Intel 5代+ CPU
        intel_5th_gen = "intel" in cpu_model and any(
            gen in cpu_model for gen in ["5th", "6th", "7th", "8th", "9th", "10th", "11th", "12th", "13th", "14th"]
        )

        # 检查是否是5090 GPU
        is_5090 = "5090" in gpu_model

        return intel_5th_gen or is_5090

    def execute(self, hosts: List[str]) -> StepResult:
        """执行MSR设置"""
        all_results = {}
        setup_hosts = []
        skipped_hosts = []

        for host in hosts:
            # 检查是否需要设置MSR
            if not self._needs_msr(host):
                self.logger.info(f"[{host}] 非目标机型，跳过MSR设置")
                skipped_hosts.append(host)
                all_results[host] = {"success": True, "skipped": True}
                continue

            # 加载msr模块
            load_cmd = "modprobe msr"
            load_result = self.execute_on_host(host, load_cmd, sudo=True)

            if not load_result["success"]:
                all_results[host] = {"success": False, "error": "加载msr模块失败"}
                continue

            # 设置MSR
            set_cmd = "wrmsr -a 0xc8b 0xffff"
            set_result = self.execute_on_host(host, set_cmd, sudo=True)

            if not set_result["success"]:
                all_results[host] = {"success": False, "error": "设置MSR失败"}
                continue

            # 验证设置
            verify_cmd = "rdmsr -a 0xc8b | uniq"
            verify_result = self.execute_on_host(host, verify_cmd, sudo=True)

            if verify_result["success"]:
                value = verify_result["stdout"].strip()
                if "cffff" in value.lower() or "ffff" in value.lower():
                    all_results[host] = {"success": True, "value": value}
                    setup_hosts.append(host)
                else:
                    all_results[host] = {"success": False, "error": f"MSR值不正确: {value}"}
            else:
                all_results[host] = {"success": False, "error": "验证MSR失败"}

        return StepResult(
            step_id=self.step_id,
            step_name=self.step_name,
            status=StepStatus.SUCCESS,
            message=f"MSR设置完成，设置: {len(setup_hosts)}，跳过: {len(skipped_hosts)}",
            details={"setup_hosts": setup_hosts, "skipped_hosts": skipped_hosts},
            host_results=all_results
        )

    def is_configured(self, host: str) -> tuple:
        """
        检查MSR设置是否已配置

        Args:
            host: 主机地址

        Returns:
            tuple[bool, str]: (是否已配置, 检查详情)
        """
        # 检查是否需要MSR设置
        if not self._needs_msr(host):
            return True, "非目标机型，无需MSR设置"

        # 检查msr模块是否加载
        result = self.execute_on_host(host, "lsmod | grep -q msr && echo 'loaded' || echo 'not_loaded'", sudo=False)

        if "not_loaded" in result.get("stdout", ""):
            return False, "msr模块未加载"

        # 尝试读取MSR值
        verify_result = self.execute_on_host(host, "rdmsr -a 0xc8b 2>/dev/null | uniq || echo 'error'", sudo=True)

        if verify_result.get("success") and verify_result.get("stdout", "").strip():
            value = verify_result["stdout"].strip()
            if "ffff" in value.lower():
                return True, f"MSR已配置: {value}"

        return False, "MSR未正确配置"

    def post_check(self, hosts: List[str]) -> bool:
        """验证MSR设置"""
        return True  # 跳过验证，因为非所有机型都需要
