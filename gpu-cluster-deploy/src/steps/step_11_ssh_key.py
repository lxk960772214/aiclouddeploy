"""
步骤11: 设置SSH免密登录
"""

from typing import List
from src.steps.base import BaseStep, StepResult, StepStatus


class SSHKeySetup(BaseStep):
    """设置SSH免密登录"""

    step_id = "11"
    step_name = "设置SSH免密登录"
    step_description = "配置节点间SSH免密登录"
    requires_sudo = True
    supports_batch = False  # 需要逐个节点处理密钥交换

    def execute(self, hosts: List[str]) -> StepResult:
        """执行SSH免密配置"""
        results = {}

        # 1. 在所有节点生成SSH密钥对
        self.logger.info("生成SSH密钥对...")

        keygen_cmd = '''sudo -u ubuntu bash -c '
if [ ! -f ~/.ssh/id_rsa ]; then
    ssh-keygen -t rsa -N "" -f ~/.ssh/id_rsa
fi
chmod 700 ~/.ssh
cat ~/.ssh/id_rsa.pub >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
''''
        keygen_result = self.execute_batch(hosts, keygen_cmd, sudo=True)

        # 2. 收集所有节点的公钥
        self.logger.info("收集公钥...")
        all_pubkeys = {}

        for host in hosts:
            get_pubkey_cmd = "cat /home/ubuntu/.ssh/id_rsa.pub"
            result = self.execute_on_host(host, get_pubkey_cmd, sudo=True)
            if result["success"]:
                all_pubkeys[host] = result["stdout"].strip()

        # 3. 将所有公钥分发到所有节点
        self.logger.info("分发公钥到所有节点...")
        all_pubkeys_str = "\n".join(all_pubkeys.values())

        for host in hosts:
            # 获取节点主机名
            node_hostname = host
            for node in self.config.nodes:
                if node.ip == host:
                    node_hostname = node.hostname
                    break

            # 将所有公钥添加到authorized_keys
            add_keys_cmd = f'''sudo -u ubuntu bash -c '
for key in "$(cat <<EOF
{all_pubkeys_str}
EOF
)"; do
    if ! grep -q "$key" ~/.ssh/authorized_keys 2>/dev/null; then
        echo "$key" >> ~/.ssh/authorized_keys
    fi
done
chmod 600 ~/.ssh/authorized_keys
''''
            add_result = self.execute_on_host(host, add_keys_cmd, sudo=True)
            results[host] = {"success": add_result["success"]}

        # 4. 配置sshd
        self.logger.info("配置sshd...")
        sshd_config = '''
ClientAliveInterval 60
ClientAliveCountMax 3
MaxStartups 512
AuthorizedKeysFile .ssh/authorized_keys
'''
        sshd_cmd = f'''cat >> /etc/ssh/sshd_config << 'EOF'
{sshd_config}
EOF
systemctl restart sshd'''
        self.execute_batch(hosts, sshd_cmd, sudo=True)

        # 5. 配置ssh客户端
        ssh_config = "StrictHostKeyChecking no\n"
        ssh_client_cmd = f'''grep -q "StrictHostKeyChecking" /etc/ssh/ssh_config || echo "{ssh_config}" >> /etc/ssh/ssh_config'''
        self.execute_batch(hosts, ssh_client_cmd, sudo=True)

        # 6. 验证（可选：测试节点间免密登录）
        success_count = sum(1 for r in results.values() if r.get("success"))

        return StepResult(
            step_id=self.step_id,
            step_name=self.step_name,
            status=StepStatus.SUCCESS if success_count == len(hosts) else StepStatus.FAILED,
            message=f"SSH免密配置完成，成功: {success_count}/{len(hosts)}",
            host_results=results
        )

    def post_check(self, hosts: List[str]) -> bool:
        """验证SSH配置"""
        # 检查authorized_keys是否存在且权限正确
        cmd = "test -f /home/ubuntu/.ssh/authorized_keys && stat -c '%a' /home/ubuntu/.ssh/authorized_keys | grep -q '600'"
        result = self.execute_batch(hosts, cmd, sudo=False)
        return all(r.success for r in result.results.values())
