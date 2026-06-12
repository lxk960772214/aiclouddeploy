"""
步骤03: 检查glibc版本一致性
"""

from typing import List, Dict, Any
from src.steps.base import BaseStep, StepResult, StepStatus


class GlibcCheck(BaseStep):
    """检查glibc版本一致性"""

    step_id = "03"
    step_name = "检查glibc版本一致性"
    step_description = "检查所有节点的glibc版本是否一致（多机环境）"
    requires_sudo = False
    supports_batch = True
    can_skip = True  # 单机可跳过

    def execute(self, hosts: List[str]) -> StepResult:
        """执行glibc版本检查"""
        # 单机跳过
        if len(hosts) <= 1:
            self.logger.info("单机环境，跳过glibc版本一致性检查")
            return StepResult(
                step_id=self.step_id,
                step_name=self.step_name,
                status=StepStatus.SUCCESS,
                message="单机环境，跳过检查"
            )

        # 获取所有节点的glibc版本
        cmd = "ldd --version | grep GLIBC | head -1"
        result = self.execute_batch(hosts, cmd, sudo=False)

        glibc_versions = {}
        for host, res in result.results.items():
            if res.success:
                # 解析版本号
                # 输出格式: ldd (Ubuntu GLIBC 2.35-0ubuntu3.1) 2.35
                output = res.stdout.strip()
                # 提取版本号
                import re
                match = re.search(r'(\d+\.\d+)', output)
                if match:
                    glibc_versions[host] = match.group(1)
                else:
                    glibc_versions[host] = output
            else:
                glibc_versions[host] = "ERROR"

        # 检查一致性
        versions = set(glibc_versions.values())
        if len(versions) == 1 and "ERROR" not in versions:
            version = list(versions)[0]
            return StepResult(
                step_id=self.step_id,
                step_name=self.step_name,
                status=StepStatus.SUCCESS,
                message=f"所有节点glibc版本一致: {version}",
                details={"glibc_version": version, "versions": glibc_versions}
            )
        else:
            return StepResult(
                step_id=self.step_id,
                step_name=self.step_name,
                status=StepStatus.FAILED,
                message=f"glibc版本不一致: {glibc_versions}",
                details={"versions": glibc_versions},
                errors=["多机环境glibc版本必须一致"]
            )

    def is_configured(self, host: str) -> tuple:
        """
        检查glibc版本一致性

        Args:
            host: 主机地址

        Returns:
            tuple[bool, str]: (是否已配置, 检查详情)
        """
        # glibc检查是一次性检查
        result = self.execute_on_host(host, "ldd --version | grep GLIBC | head -1", sudo=False)
        if result.get("success"):
            version_info = result.get("stdout", "").strip()
            return True, f"glibc: {version_info}"
        return True, "glibc检查（一次性检查）"

    def post_check(self, hosts: List[str]) -> bool:
        """验证检查完成"""
        return True
