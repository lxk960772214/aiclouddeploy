"""
步骤09: 设置主机名和hosts绑定
"""

from typing import List, Dict
from src.steps.base import BaseStep, StepResult, StepStatus


class HostnameHosts(BaseStep):
    """设置主机名和hosts绑定"""

    step_id = "09"
    step_name = "设置主机名和hosts绑定"
    step_description = "设置节点主机名并同步hosts文件到所有机器"
    requires_sudo = True
    supports_batch = False  # 每个节点配置不同

    def execute(self, hosts: List[str]) -> StepResult:
        """执行主机名和hosts设置"""
        all_results = {}

        # 生成hosts条目
        hosts_entries = []
        for node in self.config.nodes:
            hosts_entries.append(f"{node.ip} {node.hostname}")

        hosts_content = "\n".join(hosts_entries)

        for host in hosts:
            # 获取节点信息
            node = None
            for n in self.config.nodes:
                if n.ip == host:
                    node = n
                    break

            if not node:
                all_results[host] = {"success": False, "error": "节点未在配置中"}
                continue

            # 1. 设置主机名
            set_hostname_cmd = f"hostnamectl set-hostname {node.hostname}"
            hostname_result = self.execute_on_host(host, set_hostname_cmd, sudo=True)

            if not hostname_result["success"]:
                all_results[host] = {"success": False, "error": "设置主机名失败"}
                continue

            # 2. 移除127.0.1.1条目中的主机名
            remove_cmd = "sed -i '/127.0.1.1/d' /etc/hosts"
            self.execute_on_host(host, remove_cmd, sudo=True)

            # 3. 检查是否已存在条目，避免重复添加
            check_cmd = f"grep '{node.hostname}' /etc/hosts"
            check_result = self.execute_on_host(host, check_cmd, sudo=False)

            if check_result["success"]:
                # 已存在，先删除旧条目
                for entry in hosts_entries:
                    entry_hostname = entry.split()[1]
                    remove_old = f"sed -i '/{entry_hostname}$/d' /etc/hosts"
                    self.execute_on_host(host, remove_old, sudo=True)

            # 4. 添加hosts条目（逐条添加，避免多行命令问题）
            add_success = True
            for entry in hosts_entries:
                # 使用 grep 检查条目是否已存在
                entry_ip, entry_hostname = entry.split(None, 1)
                check_entry = f"grep -q '^{entry_ip}[[:space:]]' /etc/hosts"
                check_result = self.execute_on_host(host, check_entry, sudo=False)

                if not check_result["success"]:
                    # 条目不存在，添加
                    add_cmd = f"echo '{entry}' | sudo tee -a /etc/hosts"
                    add_result = self.execute_on_host(host, add_cmd, sudo=False)
                    if not add_result["success"]:
                        add_success = False
                        break

            all_results[host] = {
                "success": add_success,
                "hostname": node.hostname
            }

        success_count = sum(1 for r in all_results.values() if r.get("success"))

        return StepResult(
            step_id=self.step_id,
            step_name=self.step_name,
            status=StepStatus.SUCCESS if success_count == len(hosts) else StepStatus.FAILED,
            message=f"主机名和hosts设置完成，成功: {success_count}/{len(hosts)}",
            details={"hosts_content": hosts_content},
            host_results=all_results
        )

    def is_configured(self, host: str) -> tuple:
        """
        检查主机名和hosts是否已配置

        Args:
            host: 主机地址

        Returns:
            tuple[bool, str]: (是否已配置, 检查详情)
        """
        # 获取节点信息
        node = None
        for n in self.config.nodes:
            if n.ip == host:
                node = n
                break

        if not node:
            return False, "节点未在配置中"

        # 检查主机名
        hostname_result = self.execute_on_host(host, "hostname", sudo=False)
        current_hostname = hostname_result.get("stdout", "").strip()

        if current_hostname != node.hostname:
            return False, f"主机名不匹配: 当前={current_hostname}, 目标={node.hostname}"

        # 检查hosts文件
        hosts_result = self.execute_on_host(host, f"grep -q '{node.hostname}' /etc/hosts && echo 'found' || echo 'not_found'", sudo=False)
        if "found" not in hosts_result.get("stdout", ""):
            return False, f"hosts文件中未找到 {node.hostname}"

        return True, f"主机名和hosts已配置: {node.hostname}"

    def post_check(self, hosts: List[str]) -> bool:
        """验证hosts设置"""
        for host in hosts:
            node = None
            for n in self.config.nodes:
                if n.ip == host:
                    node = n
                    break

            if node:
                cmd = f"hostname && grep '{node.hostname}' /etc/hosts"
                result = self.execute_on_host(host, cmd)
                if not result["success"]:
                    return False
        return True
