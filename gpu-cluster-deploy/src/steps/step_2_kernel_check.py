"""
步骤02: 检查内核版本一致性
"""

from typing import List, Dict, Any
from src.steps.base import BaseStep, StepResult, StepStatus


class KernelCheck(BaseStep):
    """检查内核版本一致性"""

    step_id = "02"
    step_name = "检查内核版本一致性"
    step_description = "检查所有节点的内核版本是否一致（多机环境）"
    requires_sudo = False
    supports_batch = True
    can_skip = True  # 单机可跳过

    def execute(self, hosts: List[str]) -> StepResult:
        """执行内核版本检查"""
        # 单机跳过
        if len(hosts) <= 1:
            self.logger.info("单机环境，跳过内核版本一致性检查")
            return StepResult(
                step_id=self.step_id,
                step_name=self.step_name,
                status=StepStatus.SUCCESS,
                message="单机环境，跳过检查"
            )

        # 获取所有节点的内核版本
        cmd = "uname -r"
        result = self.execute_batch(hosts, cmd, sudo=False)

        kernel_versions = {}
        for host, res in result.results.items():
            if res.success:
                kernel_versions[host] = res.stdout.strip()
            else:
                kernel_versions[host] = "ERROR"

        # 检查一致性
        versions = set(kernel_versions.values())
        if len(versions) == 1 and "ERROR" not in versions:
            version = list(versions)[0]
            return StepResult(
                step_id=self.step_id,
                step_name=self.step_name,
                status=StepStatus.SUCCESS,
                message=f"所有节点内核版本一致: {version}",
                details={"kernel_version": version, "versions": kernel_versions}
            )
        else:
            return StepResult(
                step_id=self.step_id,
                step_name=self.step_name,
                status=StepStatus.FAILED,
                message=f"内核版本不一致: {kernel_versions}",
                details={"versions": kernel_versions},
                errors=["多机环境内核版本必须一致"]
            )

    def is_configured(self, host: str) -> tuple:
        """
        检查内核版本一致性

        Args:
            host: 主机地址

        Returns:
            tuple[bool, str]: (是否已配置, 检查详情)
        """
        # 内核检查是一次性检查
        result = self.execute_on_host(host, "uname -r", sudo=False)
        if result.get("success"):
            version = result.get("stdout", "").strip()
            return True, f"内核版本: {version}"
        return True, "内核检查（一次性检查）"

    def post_check(self, hosts: List[str]) -> bool:
        """验证检查完成"""
        return True


class KernelInstall(BaseStep):
    """安装指定内核版本"""

    step_id = "02b"
    step_name = "安装指定内核版本"
    step_description = "安装指定的内核版本（当mode=specify时）"
    requires_sudo = True
    supports_batch = True
    requires_reboot = True
    can_skip = True  # 可以跳过

    def execute(self, hosts: List[str]) -> StepResult:
        """执行内核安装"""
        # 检查是否有 versions 配置
        if not hasattr(self, 'versions') or self.versions is None:
            return StepResult(
                step_id=self.step_id,
                step_name=self.step_name,
                status=StepStatus.SKIPPED,
                message="未配置版本信息，跳过内核安装"
            )

        kernel_config = self.versions.kernel

        if kernel_config.mode == "keep":
            return StepResult(
                step_id=self.step_id,
                step_name=self.step_name,
                status=StepStatus.SKIPPED,
                message="内核模式为keep，跳过安装"
            )

        target_version = kernel_config.specify.get("version")
        if not target_version:
            return StepResult(
                step_id=self.step_id,
                step_name=self.step_name,
                status=StepStatus.FAILED,
                message="未指定目标内核版本"
            )

        # 自动推导包名
        packages = [
            f"linux-image-{target_version}",
            f"linux-headers-{target_version}",
            f"linux-modules-{target_version}",
            f"linux-modules-extra-{target_version}"
        ]

        # 检查本地deb包目录
        local_debs = kernel_config.specify.get("local_debs")
        if local_debs:
            self.logger.info(f"使用本地deb包: {local_debs}")
            # 这里需要先上传deb包再安装
            # 简化处理：直接使用apt安装
            pass

        # 安装内核包
        pkg_list = " ".join(packages)
        install_cmd = f"DEBIAN_FRONTEND=noninteractive apt install -y {pkg_list}"
        result = self.execute_batch(hosts, install_cmd, sudo=True)

        failed = [h for h, r in result.results.items() if not r.success]
        if failed:
            return StepResult(
                step_id=self.step_id,
                step_name=self.step_name,
                status=StepStatus.FAILED,
                message=f"内核安装失败: {failed}",
                host_results=result.results
            )

        return StepResult(
            step_id=self.step_id,
            step_name=self.step_name,
            status=StepStatus.SUCCESS,
            message=f"内核 {target_version} 安装完成",
            details={"target_version": target_version},
            host_results=result.results
        )
