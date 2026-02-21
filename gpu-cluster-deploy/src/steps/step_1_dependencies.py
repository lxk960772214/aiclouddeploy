"""
步骤01: 安装依赖软件包
"""

from typing import List, Dict, Any
from src.steps.base import BaseStep, StepResult, StepStatus


class InstallDependencies(BaseStep):
    """安装依赖软件包"""

    step_id = "01"
    step_name = "安装依赖软件包"
    step_description = "安装GPU集群部署所需的基础依赖软件包"
    requires_sudo = True
    supports_batch = True

    # 依赖包分组
    PACKAGE_GROUPS = [
        # 基础编译工具
        [
            "build-essential", "g++", "gcc", "make", "dkms", "ntpdate",
            "msr-tools", "traceroute", "wget", "sshpass", "pdsh",
            "cpufrequtils", "sysbench", "unzip"
        ],
        # 开发库
        [
            "cmake", "debhelper", "devscripts", "fakeroot", "git",
            "libaio-dev", "libboost-filesystem-dev", "libboost-program-options-dev",
            "libboost-thread-dev", "libcurl4-openssl-dev", "libncurses-dev",
            "libnuma-dev", "lintian", "libssl-dev", "uuid-dev", "zlib1g-dev"
        ],
        # Vulkan和图形库
        ["libvulkan1", "mesa-vulkan-drivers", "vulkan-tools", "libglvnd-dev"]
    ]

    def execute(self, hosts: List[str]) -> StepResult:
        """执行安装"""
        all_results = {}
        errors = []

        # 1. 更新apt缓存
        self.logger.info("更新apt缓存...")
        update_cmd = "apt update -y"
        update_result = self.execute_batch(hosts, update_cmd, sudo=True)

        failed_hosts = [h for h, r in update_result.results.items() if not r.success]
        if failed_hosts:
            return StepResult(
                step_id=self.step_id,
                step_name=self.step_name,
                status=StepStatus.FAILED,
                message=f"apt update失败: {failed_hosts}",
                host_results=update_result.results
            )

        # 2. 分组安装依赖包
        for i, packages in enumerate(self.PACKAGE_GROUPS):
            self.logger.info(f"安装依赖包组 {i+1}/{len(self.PACKAGE_GROUPS)}...")
            pkg_list = " ".join(packages)
            install_cmd = f"apt install -y {pkg_list}"

            result = self.execute_batch(hosts, install_cmd, sudo=True)
            all_results[f"group_{i+1}"] = result.results

            failed = [h for h, r in result.results.items() if not r.success]
            if failed:
                errors.append(f"包组{i+1}安装失败: {failed}")

        # 3. 验证关键包是否安装
        self.logger.info("验证关键包安装...")
        verify_cmd = "dpkg -l | grep -E 'build-essential|pdsh|git' | wc -l"
        verify_result = self.execute_batch(hosts, verify_cmd, sudo=True)

        success_hosts = []
        failed_hosts = []

        for host, result in verify_result.results.items():
            if result.success and result.stdout.strip().isdigit():
                count = int(result.stdout.strip())
                if count >= 3:
                    success_hosts.append(host)
                else:
                    failed_hosts.append(host)
            else:
                failed_hosts.append(host)

        if failed_hosts:
            return StepResult(
                step_id=self.step_id,
                step_name=self.step_name,
                status=StepStatus.FAILED,
                message=f"依赖安装验证失败: {failed_hosts}",
                errors=errors,
                host_results=all_results
            )

        return StepResult(
            step_id=self.step_id,
            step_name=self.step_name,
            status=StepStatus.SUCCESS,
            message=f"依赖安装完成，成功: {len(success_hosts)}/{len(hosts)}",
            host_results=all_results
        )

    def post_check(self, hosts: List[str]) -> bool:
        """验证依赖安装"""
        cmd = "which pdsh && which gcc && which git"
        result = self.execute_batch(hosts, cmd, sudo=False)
        return all(r.success for r in result.results.values())
