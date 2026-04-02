"""
步骤04: 检查OpenSSH版本
"""

from typing import List, Dict, Any
import re
from src.steps.base import BaseStep, StepResult, StepStatus


class OpenSSHCheck(BaseStep):
    """检查OpenSSH版本（CVE-2024-6387漏洞）"""

    step_id = "04"
    step_name = "检查OpenSSH版本"
    step_description = "检查OpenSSH版本是否存在CVE-2024-6387漏洞"
    requires_sudo = False
    supports_batch = True

    # 安全版本阈值
    MIN_SAFE_VERSION = "1:8.9p1-3ubuntu0.10"

    def _compare_versions(self, v1: str, v2: str) -> int:
        """比较版本号，返回 -1, 0, 1"""
        def normalize(v):
            # 移除前缀如 "1:"
            if ':' in v:
                v = v.split(':', 1)[1]
            # 分割版本号各部分
            parts = re.split(r'[.~+-]', v)
            result = []
            for p in parts:
                # 尝试转换为数字
                match = re.match(r'(\d+)', p)
                if match:
                    result.append(int(match.group(1)))
                else:
                    result.append(0)
            return result

        n1, n2 = normalize(v1), normalize(v2)
        # 补齐长度
        max_len = max(len(n1), len(n2))
        n1.extend([0] * (max_len - len(n1)))
        n2.extend([0] * (max_len - len(n2)))

        for a, b in zip(n1, n2):
            if a < b:
                return -1
            elif a > b:
                return 1
        return 0

    def execute(self, hosts: List[str]) -> StepResult:
        """执行OpenSSH版本检查"""
        # 获取openssh-client版本
        cmd = "dpkg -l | grep 'openssh-client' | awk '{print $3}'"
        result = self.execute_batch(hosts, cmd, sudo=False)

        ssh_versions = {}
        vulnerable_hosts = []
        safe_hosts = []

        for host, res in result.results.items():
            if res.success:
                version = res.stdout.strip().split('\n')[0] if res.stdout.strip() else ""
                ssh_versions[host] = version

                # 比较版本
                if version and self._compare_versions(version, self.MIN_SAFE_VERSION) >= 0:
                    safe_hosts.append(host)
                else:
                    vulnerable_hosts.append(host)
            else:
                ssh_versions[host] = "ERROR"
                vulnerable_hosts.append(host)

        # 如果有漏洞主机，尝试升级
        if vulnerable_hosts and self.versions.openssh.auto_upgrade:
            self.logger.warning(f"发现低版本OpenSSH主机: {vulnerable_hosts}，尝试升级...")

            upgrade_cmd = "apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y openssh-client"
            upgrade_result = self.execute_batch(vulnerable_hosts, upgrade_cmd, sudo=True)

            # 重新检查
            recheck_cmd = "dpkg -l | grep 'openssh-client' | awk '{print $3}'"
            recheck_result = self.execute_batch(vulnerable_hosts, recheck_cmd, sudo=False)

            still_vulnerable = []
            for host, res in recheck_result.results.items():
                if res.success:
                    version = res.stdout.strip()
                    ssh_versions[host] = version
                    if version and self._compare_versions(version, self.MIN_SAFE_VERSION) >= 0:
                        safe_hosts.append(host)
                    else:
                        still_vulnerable.append(host)
                else:
                    still_vulnerable.append(host)

            if still_vulnerable:
                return StepResult(
                    step_id=self.step_id,
                    step_name=self.step_name,
                    status=StepStatus.FAILED,
                    message=f"OpenSSH升级后仍存在漏洞: {still_vulnerable}",
                    details={"versions": ssh_versions, "vulnerable": still_vulnerable}
                )

        if not vulnerable_hosts:
            return StepResult(
                step_id=self.step_id,
                step_name=self.step_name,
                status=StepStatus.SUCCESS,
                message=f"所有节点OpenSSH版本安全",
                details={"versions": ssh_versions}
            )
        else:
            return StepResult(
                step_id=self.step_id,
                step_name=self.step_name,
                status=StepStatus.FAILED,
                message=f"存在OpenSSH漏洞风险: {vulnerable_hosts}",
                details={"versions": ssh_versions, "vulnerable": vulnerable_hosts}
            )

    def is_configured(self, host: str) -> tuple:
        """
        检查OpenSSH版本安全性

        Args:
            host: 主机地址

        Returns:
            tuple[bool, str]: (是否已配置, 检查详情)
        """
        result = self.execute_on_host(host, "dpkg -l | grep 'openssh-client' | awk '{print $3}'", sudo=False)
        if result.get("success"):
            version = result.get("stdout", "").strip().split('\n')[0]
            if version and self._compare_versions(version, self.MIN_SAFE_VERSION) >= 0:
                return True, f"OpenSSH版本安全: {version}"
            else:
                return False, f"OpenSSH版本过低: {version}"
        return False, "无法获取OpenSSH版本"

    def post_check(self, hosts: List[str]) -> bool:
        """验证OpenSSH版本"""
        cmd = "ssh -V 2>&1"
        result = self.execute_batch(hosts, cmd, sudo=False)
        return all(r.success for r in result.results.values())
