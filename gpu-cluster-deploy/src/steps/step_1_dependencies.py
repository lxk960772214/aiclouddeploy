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

    # 关键包列表（用于配置检查）
    KEY_PACKAGES = [
        "build-essential", "gcc", "make", "dkms", "pdsh", "git", "cmake"
    ]

    def get_mirror_sources_list(self, mirror_url: str, codename: str) -> str:
        """
        根据镜像URL和Ubuntu版本代号生成sources.list内容

        Args:
            mirror_url: 镜像源URL
            codename: Ubuntu版本代号 (如 jammy, noble)

        Returns:
            sources.list内容
        """
        return f'''deb {mirror_url} {codename} main restricted universe multiverse
# deb-src {mirror_url} {codename} main restricted universe multiverse
deb {mirror_url} {codename}-updates main restricted universe multiverse
# deb-src {mirror_url} {codename}-updates main restricted universe multiverse
deb {mirror_url} {codename}-backports main restricted universe multiverse
# deb-src {mirror_url} {codename}-backports main restricted universe multiverse
deb {mirror_url} {codename}-security main restricted universe multiverse
# deb-src {mirror_url} {codename}-security main restricted universe multiverse
'''

    def is_configured(self, host: str) -> tuple:
        """
        检查依赖包是否已安装

        Args:
            host: 主机地址

        Returns:
            tuple[bool, str]: (是否已配置, 检查详情)
        """
        # 逐个检查关键包是否已安装
        missing = []
        installed = []

        for pkg in self.KEY_PACKAGES:
            check_cmd = f"dpkg -l {pkg} 2>/dev/null | grep '^ii' && echo 'installed' || echo 'not_installed'"
            check_result = self.execute_on_host(host, check_cmd)
            stdout = check_result.get("stdout", "").strip()
            # 取最后一行（避免重复输出问题）
            status_line = stdout.split('\n')[-1].strip() if stdout else "not_installed"
            if status_line == "installed":
                installed.append(pkg)
            else:
                missing.append(pkg)

        if not missing:
            return True, f"所有 {len(installed)} 个关键依赖包已安装"

        return False, f"缺失依赖包: {', '.join(missing[:5])}{'...' if len(missing) > 5 else ''}"

    def execute(self, hosts: List[str]) -> StepResult:
        """执行安装"""
        all_results = {}
        errors = []

        # 0. 检查是否需要换源
        apt_mirror_config = getattr(self.versions, 'apt_mirror', None)
        if apt_mirror_config and apt_mirror_config.enabled:
            self.logger.info("APT换源已启用...")

            # 获取镜像URL
            mirror_name = apt_mirror_config.mirror
            if mirror_name in apt_mirror_config.MIRRORS:
                mirror_url = apt_mirror_config.MIRRORS[mirror_name]
            else:
                # 自定义URL
                mirror_url = mirror_name

            self.logger.info(f"使用镜像源: {mirror_url}")

            # 获取Ubuntu版本代号
            for host in hosts:
                codename_result = self.execute_on_host(host, "lsb_release -cs 2>/dev/null || cat /etc/os-release | grep VERSION_CODENAME | cut -d= -f2")
                codename = codename_result.get("stdout", "").strip()
                if not codename:
                    codename = "jammy"  # 默认使用22.04
                    self.logger.warning(f"[{host}] 无法获取Ubuntu版本代号，使用默认: {codename}")
                else:
                    self.logger.info(f"[{host}] Ubuntu版本代号: {codename}")

                # 生成sources.list内容
                sources_content = self.get_mirror_sources_list(mirror_url, codename)

                # 替换sources.list
                sources_list_cmd = f'''cat << 'EOFAPT' > /etc/apt/sources.list
{sources_content}EOFAPT'''
                mirror_result = self.execute_on_host(host, sources_list_cmd, sudo=True)

                if not mirror_result.get("success"):
                    self.logger.error(f"[{host}] APT换源失败")
                    errors.append(f"[{host}] APT换源失败")
                    all_results[f"mirror_{host}"] = {"success": False}
                    continue

                all_results[f"mirror_{host}"] = {"success": True}
                self.logger.info(f"[{host}] APT换源成功")

        # 1. 更新apt缓存
        self.logger.info("更新apt缓存...")
        update_cmd = "DEBIAN_FRONTEND=noninteractive apt update -y"
        update_result = self.execute_batch(hosts, update_cmd, sudo=True)

        failed_hosts = [h for h, r in update_result.results.items() if not r.success]
        if failed_hosts:
            return StepResult(
                step_id=self.step_id,
                step_name=self.step_name,
                status=StepStatus.FAILED,
                message=f"apt update失败: {failed_hosts}",
                host_results={h: {"success": r.success, "stdout": r.stdout, "stderr": r.stderr}
                             for h, r in update_result.results.items()}
            )

        # 2. 分组安装依赖包
        for i, packages in enumerate(self.PACKAGE_GROUPS):
            self.logger.info(f"安装依赖包组 {i+1}/{len(self.PACKAGE_GROUPS)}...")
            pkg_list = " ".join(packages)
            install_cmd = f"DEBIAN_FRONTEND=noninteractive apt install -y {pkg_list}"

            result = self.execute_batch(hosts, install_cmd, sudo=True)
            all_results[f"group_{i+1}"] = {h: {"success": r.success, "stdout": r.stdout}
                                           for h, r in result.results.items()}

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
