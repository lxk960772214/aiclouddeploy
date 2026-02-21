"""
步骤20: 安装Mellanox驱动
"""

from typing import List
from src.steps.base import BaseStep, StepResult, StepStatus


class MellanoxDriver(BaseStep):
    """安装Mellanox OFED驱动"""

    step_id = "20"
    step_name = "安装Mellanox驱动"
    step_description = "安装MLNX_OFED驱动"
    requires_sudo = True
    supports_batch = False  # 驱动安装需要逐个节点执行
    requires_reboot = True
    timeout = 1800  # 30分钟超时

    def execute(self, hosts: List[str]) -> StepResult:
        """执行Mellanox驱动安装"""
        results = {}

        # 获取驱动版本和文件
        mlnx_config = self.versions.mlnx_ofed
        version = mlnx_config.version

        # 驱动文件路径（需要预先上传或指定本地路径）
        driver_file = mlnx_config.local_file or f"/tmp/MLNX_OFED_LINUX-{version}-ubuntu22.04-x86_64.tgz"

        for host in hosts:
            self.logger.info(f"[{host}] 开始安装MLNX_OFED驱动...")

            # 1. 检查驱动文件是否存在
            check_cmd = f"test -f {driver_file} && echo 'exists' || echo 'not_found'"
            check_result = self.execute_on_host(host, check_cmd)

            if "not_found" in check_result.get("stdout", ""):
                results[host] = {"success": False, "error": f"驱动文件不存在: {driver_file}"}
                continue

            # 2. 解压驱动
            extract_dir = "/tmp/mlnx_ofed"
            extract_cmd = f"rm -rf {extract_dir} && mkdir -p {extract_dir} && tar -xzf {driver_file} -C {extract_dir} --strip-components=1"
            extract_result = self.execute_on_host(host, extract_cmd, sudo=True)

            if not extract_result["success"]:
                results[host] = {"success": False, "error": "解压驱动失败"}
                continue

            # 3. 安装驱动
            install_cmd = f"cd {extract_dir} && ./mlnxofedinstall --add-kernel-support --skip-distro-check --force --enable-opensm"
            install_result = self.execute_on_host(host, install_cmd, sudo=True)
            results[host] = {"install": install_result}

            # 4. 验证安装
            if install_result["success"]:
                verify_cmd = "ibstat"
                verify_result = self.execute_on_host(host, verify_cmd)
                results[host]["verify"] = verify_result

                if verify_result["success"] and "Active" in verify_result.get("stdout", ""):
                    results[host]["success"] = True
                else:
                    results[host]["success"] = False
                    results[host]["error"] = "IB设备状态异常"
            else:
                results[host]["success"] = False
                results[host]["error"] = "驱动安装失败"

        success_count = sum(1 for r in results.values() if r.get("success"))

        return StepResult(
            step_id=self.step_id,
            step_name=self.step_name,
            status=StepStatus.SUCCESS if success_count == len(hosts) else StepStatus.FAILED,
            message=f"MLNX_OFED驱动安装完成，成功: {success_count}/{len(hosts)}（需要重启）",
            host_results=results
        )

    def post_check(self, hosts: List[str]) -> bool:
        """验证驱动安装"""
        cmd = "ibstat | grep -q 'State: Active'"
        result = self.execute_batch(hosts, cmd, sudo=False)
        return all(r.success for r in result.results.values())
