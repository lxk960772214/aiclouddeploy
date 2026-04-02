"""
SSH连接管理器 - 支持跳转服务器、连接池、密钥/密码认证
"""

import os
import time
import socket
import paramiko
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
from contextlib import contextmanager
import logging

logger = logging.getLogger(__name__)


@dataclass
class SSHResult:
    """SSH命令执行结果"""
    success: bool
    exit_code: int
    stdout: str
    stderr: str
    host: str
    command: str
    duration: float = 0.0

    def __str__(self):
        status = "✓" if self.success else "✗"
        return f"{status} [{self.host}] exit={self.exit_code}, duration={self.duration:.2f}s"

    def get(self, key: str, default: Any = None) -> Any:
        """
        字典式访问支持，提供向后兼容性

        Args:
            key: 键名 (success, exit_code, stdout, stderr, host, command, duration)
            default: 默认值

        Returns:
            属性值或默认值
        """
        if hasattr(self, key):
            return getattr(self, key)
        return default

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "success": self.success,
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "host": self.host,
            "command": self.command,
            "duration": self.duration
        }


class SSHConnection:
    """SSH连接封装"""

    def __init__(self, host: str, port: int, username: str,
                 password: Optional[str] = None,
                 private_key: Optional[str] = None,
                 jump_client: Optional[paramiko.SSHClient] = None):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.private_key = private_key
        self.jump_client = jump_client
        self.client: Optional[paramiko.SSHClient] = None
        self._connected = False
        self._is_root: Optional[bool] = None  # 缓存 root 用户状态

    def connect(self, timeout: int = 30) -> bool:
        """建立SSH连接"""
        try:
            self.client = paramiko.SSHClient()
            self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            # 通过跳转服务器连接
            if self.jump_client:
                transport = self.jump_client.get_transport()
                if not transport:
                    raise ConnectionError("跳转服务器传输层未初始化")

                dest_addr = (self.host, self.port)
                local_addr = ('127.0.0.1', 22)
                channel = transport.open_channel('direct-tcpip', dest_addr, local_addr)

                if self.private_key:
                    # 密钥认证
                    key = paramiko.RSAKey.from_private_key_file(os.path.expanduser(self.private_key))
                    self.client.connect(
                        hostname=self.host,
                        port=self.port,
                        username=self.username,
                        pkey=key,
                        sock=channel,
                        timeout=timeout,
                        allow_agent=False,
                        look_for_keys=False
                    )
                elif self.password:
                    # 密码认证
                    self.client.connect(
                        hostname=self.host,
                        port=self.port,
                        username=self.username,
                        password=self.password,
                        sock=channel,
                        timeout=timeout,
                        allow_agent=False,
                        look_for_keys=False
                    )
                else:
                    # 免密登录：使用 SSH agent 或系统密钥
                    self.client.connect(
                        hostname=self.host,
                        port=self.port,
                        username=self.username,
                        sock=channel,
                        timeout=timeout,
                        allow_agent=True,
                        look_for_keys=True
                    )
            else:
                # 直连
                if self.private_key:
                    # 密钥认证
                    key = paramiko.RSAKey.from_private_key_file(os.path.expanduser(self.private_key))
                    self.client.connect(
                        hostname=self.host,
                        port=self.port,
                        username=self.username,
                        pkey=key,
                        timeout=timeout,
                        allow_agent=False,
                        look_for_keys=False
                    )
                elif self.password:
                    # 密码认证
                    self.client.connect(
                        hostname=self.host,
                        port=self.port,
                        username=self.username,
                        password=self.password,
                        timeout=timeout,
                        allow_agent=False,
                        look_for_keys=False
                    )
                else:
                    # 免密登录：使用 SSH agent 或系统密钥
                    self.client.connect(
                        hostname=self.host,
                        port=self.port,
                        username=self.username,
                        timeout=timeout,
                        allow_agent=True,
                        look_for_keys=True
                    )

            self._connected = True
            # 设置 keepalive，每30秒发送心跳包，防止长时间传输时连接断开
            transport = self.client.get_transport()
            if transport:
                transport.set_keepalive(30)
            logger.info(f"SSH连接成功: {self.username}@{self.host}:{self.port}")
            return True

        except Exception as e:
            logger.error(f"SSH连接失败: {self.host} - {e}")
            self._connected = False
            return False

    def disconnect(self):
        """断开连接"""
        if self.client:
            self.client.close()
            self.client = None
        self._connected = False
        self._is_root = None  # 重置 root 用户缓存
        logger.debug(f"SSH连接已断开: {self.host}")

    def is_connected(self) -> bool:
        """检查连接状态"""
        if not self._connected or not self.client:
            return False
        transport = self.client.get_transport()
        return transport is not None and transport.is_active()

    def _check_is_root(self) -> bool:
        """
        检查当前SSH用户是否为root

        Returns:
            bool: 是否为root用户
        """
        if self._is_root is not None:
            return self._is_root

        try:
            # 使用 id -u 命令检查，root 用户返回 0
            stdin, stdout, stderr = self.client.exec_command("id -u", timeout=5)
            exit_code = stdout.channel.recv_exit_status()
            stdout_str = stdout.read().decode('utf-8').strip()

            self._is_root = (exit_code == 0 and stdout_str == "0")
            if self._is_root:
                logger.debug(f"[{self.host}] 检测到 root 用户，将跳过 sudo 包装")
            return self._is_root
        except Exception as e:
            logger.warning(f"[{self.host}] 检测用户类型失败: {e}，假设非 root 用户")
            self._is_root = False
            return False

    def execute(self, command: str, timeout: int = 300,
                sudo: bool = False, sudo_password: Optional[str] = None) -> SSHResult:
        """执行命令"""
        if not self.is_connected():
            return SSHResult(
                success=False,
                exit_code=-1,
                stdout="",
                stderr="SSH连接未建立",
                host=self.host,
                command=command
            )

        start_time = time.time()

        try:
            # 检查是否需要 sudo 包装
            actual_sudo_needed = sudo and sudo_password

            # 如果需要 sudo，先检测用户是否为 root
            if actual_sudo_needed and self._check_is_root():
                # root 用户不需要 sudo 包装
                actual_sudo_needed = False
                logger.debug(f"[{self.host}] root 用户跳过 sudo 包装")

            if actual_sudo_needed:
                # 使用双引号包装命令，避免单引号嵌套问题
                # 转义命令中的双引号和特殊字符
                escaped_command = command.replace('\\', '\\\\').replace('"', '\\"').replace('$', '\\$')
                command = f"echo '{sudo_password}' | sudo -S sh -c \"{escaped_command}\""

            stdin, stdout, stderr = self.client.exec_command(command, timeout=timeout)

            exit_code = stdout.channel.recv_exit_status()
            stdout_str = stdout.read().decode('utf-8', errors='replace')
            stderr_str = stderr.read().decode('utf-8', errors='replace')

            duration = time.time() - start_time

            return SSHResult(
                success=exit_code == 0,
                exit_code=exit_code,
                stdout=stdout_str,
                stderr=stderr_str,
                host=self.host,
                command=command,
                duration=duration
            )

        except socket.timeout:
            duration = time.time() - start_time
            return SSHResult(
                success=False,
                exit_code=-1,
                stdout="",
                stderr=f"命令执行超时 ({timeout}s)",
                host=self.host,
                command=command,
                duration=duration
            )
        except Exception as e:
            duration = time.time() - start_time
            return SSHResult(
                success=False,
                exit_code=-1,
                stdout="",
                stderr=str(e),
                host=self.host,
                command=command,
                duration=duration
            )

    def put_file(self, local_path: str, remote_path: str) -> bool:
        """上传文件"""
        if not self.is_connected():
            logger.error("SSH连接未建立")
            return False

        try:
            sftp = self.client.open_sftp()
            sftp.put(local_path, remote_path)
            sftp.close()
            logger.info(f"文件上传成功: {local_path} -> {remote_path}")
            return True
        except Exception as e:
            logger.error(f"文件上传失败: {e}")
            return False

    def get_file(self, remote_path: str, local_path: str) -> bool:
        """下载文件"""
        if not self.is_connected():
            logger.error("SSH连接未建立")
            return False

        try:
            sftp = self.client.open_sftp()
            sftp.get(remote_path, local_path)
            sftp.close()
            logger.info(f"文件下载成功: {remote_path} -> {local_path}")
            return True
        except Exception as e:
            logger.error(f"文件下载失败: {e}")
            return False


class SSHManager:
    """SSH连接管理器"""

    def __init__(self, jumphost_config: Optional[Dict] = None):
        """
        初始化SSH管理器

        Args:
            jumphost_config: 跳转服务器配置
                {
                    "host": "公网IP",
                    "port": 22,
                    "username": "用户名",
                    "password": "密码",  # 可选
                    "private_key": "私钥路径"  # 可选
                }
        """
        self.jumphost_config = jumphost_config
        self.jump_client: Optional[paramiko.SSHClient] = None
        self.connections: Dict[str, SSHConnection] = {}
        self._jump_connected = False
        # 保存默认认证信息（来自 jumphost 配置，用于连接内部节点）
        if jumphost_config:
            self._default_username = jumphost_config.get("username", "ubuntu")
            self._default_private_key = jumphost_config.get("private_key")
            self._default_password = jumphost_config.get("password")
        else:
            self._default_username = "ubuntu"
            self._default_private_key = None
            self._default_password = None

    def connect_jumphost(self, timeout: int = 30) -> bool:
        """连接跳转服务器"""
        if not self.jumphost_config:
            logger.debug("未配置跳转服务器，将使用直连模式")
            self._jump_connected = True
            return True

        try:
            self.jump_client = paramiko.SSHClient()
            self.jump_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            host = self.jumphost_config["host"]
            port = self.jumphost_config.get("port", 22)
            username = self.jumphost_config.get("username", "ubuntu")
            password = self.jumphost_config.get("password")
            private_key = self.jumphost_config.get("private_key")

            if private_key:
                key = paramiko.RSAKey.from_private_key_file(os.path.expanduser(private_key))
                self.jump_client.connect(
                    hostname=host,
                    port=port,
                    username=username,
                    pkey=key,
                    timeout=timeout,
                    allow_agent=False,
                    look_for_keys=False
                )
            else:
                self.jump_client.connect(
                    hostname=host,
                    port=port,
                    username=username,
                    password=password,
                    timeout=timeout,
                    allow_agent=False,
                    look_for_keys=False
                )

            self._jump_connected = True
            # 设置 keepalive，每30秒发送心跳包，防止长时间传输时连接断开
            transport = self.jump_client.get_transport()
            if transport:
                transport.set_keepalive(30)
            logger.info(f"跳转服务器连接成功: {username}@{host}:{port}")
            return True

        except Exception as e:
            logger.error(f"跳转服务器连接失败: {e}")
            self._jump_connected = False
            return False

    def disconnect_jumphost(self):
        """断开跳转服务器连接"""
        # 先断开所有内网连接
        for conn in self.connections.values():
            conn.disconnect()
        self.connections.clear()

        # 再断开跳转服务器
        if self.jump_client:
            self.jump_client.close()
            self.jump_client = None
        self._jump_connected = False
        logger.info("跳转服务器连接已断开")

    def get_connection(self, host: str, port: int = 22,
                       username: Optional[str] = None,
                       password: Optional[str] = None,
                       private_key: Optional[str] = None,
                       timeout: int = 30) -> Optional[SSHConnection]:
        """获取或创建SSH连接

        Args:
            host: 目标主机
            port: SSH端口
            username: 用户名（默认使用 jumphost 的用户名）
            password: 密码（默认使用 jumphost 的密码）
            private_key: 私钥路径（默认使用 jumphost 的私钥）
            timeout: 连接超时时间

        Returns:
            SSHConnection 或 None
        """
        # 使用默认认证信息（来自 jumphost 配置）
        if username is None:
            username = self._default_username
        if password is None:
            password = self._default_password
        if private_key is None:
            private_key = self._default_private_key

        conn_key = f"{username}@{host}:{port}"

        # 检查现有连接
        if conn_key in self.connections:
            conn = self.connections[conn_key]
            if conn.is_connected():
                return conn
            else:
                conn.disconnect()
                del self.connections[conn_key]

        # 确保跳转服务器已连接
        if self.jumphost_config and not self._jump_connected:
            if not self.connect_jumphost(timeout):
                return None

        # 创建新连接
        conn = SSHConnection(
            host=host,
            port=port,
            username=username,
            password=password,
            private_key=private_key,
            jump_client=self.jump_client
        )

        if conn.connect(timeout):
            self.connections[conn_key] = conn
            return conn
        else:
            return None

    def execute_on_host(self, host: str, command: str,
                        port: int = 22,
                        username: Optional[str] = None,
                        password: Optional[str] = None,
                        private_key: Optional[str] = None,
                        timeout: int = 300,
                        sudo: bool = False,
                        sudo_password: Optional[str] = None) -> SSHResult:
        """在指定主机上执行命令

        Args:
            host: 目标主机
            command: 要执行的命令
            port: SSH端口
            username: 用户名（默认使用 jumphost 的用户名）
            password: 密码（默认使用 jumphost 的密码）
            private_key: 私钥路径（默认使用 jumphost 的私钥）
            timeout: 超时时间
            sudo: 是否使用 sudo
            sudo_password: sudo 密码

        Returns:
            SSHResult: 执行结果
        """
        # 使用默认认证信息（来自 jumphost 配置）
        if username is None:
            username = self._default_username
        if password is None:
            password = self._default_password
        if private_key is None:
            private_key = self._default_private_key

        conn = self.get_connection(
            host=host,
            port=port,
            username=username,
            password=password,
            private_key=private_key
        )

        if not conn:
            return SSHResult(
                success=False,
                exit_code=-1,
                stdout="",
                stderr="无法建立SSH连接",
                host=host,
                command=command
            )

        # 如果没有提供 sudo_password，使用连接密码
        if sudo and not sudo_password:
            sudo_password = password

        return conn.execute(command, timeout, sudo, sudo_password)

    def execute_on_hosts(self, hosts: List[str], command: str,
                         port: int = 22,
                         username: Optional[str] = None,
                         password: Optional[str] = None,
                         private_key: Optional[str] = None,
                         timeout: int = 300,
                         sudo: bool = False,
                         sudo_password: Optional[str] = None) -> Dict[str, SSHResult]:
        """在多个主机上执行命令（并行）"""
        # 使用默认认证信息（来自 jumphost 配置）
        if username is None:
            username = self._default_username
        if password is None:
            password = self._default_password
        if private_key is None:
            private_key = self._default_private_key

        import concurrent.futures

        results = {}

        def execute_single(host: str) -> Tuple[str, SSHResult]:
            result = self.execute_on_host(
                host=host,
                command=command,
                port=port,
                username=username,
                password=password,
                private_key=private_key,
                timeout=timeout,
                sudo=sudo,
                sudo_password=sudo_password
            )
            return host, result

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = {executor.submit(execute_single, host): host for host in hosts}

            for future in concurrent.futures.as_completed(futures):
                host, result = future.result()
                results[host] = result

        return results

    def copy_file_to_host(self, local_path: str, remote_path: str, host: str,
                          port: int = 22, username: str = "ubuntu",
                          password: Optional[str] = None,
                          private_key: Optional[str] = None,
                          timeout: int = None) -> bool:
        """
        复制本地文件到远程主机（通过跳转服务器）

        Args:
            local_path: 本地文件路径
            remote_path: 远程目标路径
            host: 目标主机
            port: SSH端口
            username: 用户名
            password: 密码
            private_key: 私钥路径
            timeout: 连接超时时间（传输本身不设超时，让传输自然完成）

        Returns:
            bool: 是否成功
        """
        # 默认连接超时30秒，但传输过程不设超时
        if timeout is None:
            timeout = 30
        import os

        if not os.path.exists(local_path):
            logger.error(f"本地文件不存在: {local_path}")
            return False

        # 获取连接
        conn = self.get_connection(
            host=host,
            port=port,
            username=username,
            password=password,
            private_key=private_key,
            timeout=timeout
        )

        if not conn:
            logger.error(f"无法连接到主机: {host}")
            return False

        try:
            # 通过跳转服务器传输文件
            if self.jump_client:
                # 检查目标主机是否是跳转服务器本身
                # 获取跳转服务器的所有 IP 地址
                stdin, stdout, stderr = self.jump_client.exec_command("hostname -I 2>/dev/null || hostname -i")
                jump_ips = stdout.read().decode().strip().split()
                jump_public_ip = self.jumphost_config.get("host", "") if self.jumphost_config else ""

                logger.info(f"跳转服务器 IPs: {jump_ips}")
                logger.info(f"跳转服务器公网 IP: {jump_public_ip}")
                logger.info(f"目标主机: {host}")

                is_jump_server_target = host in jump_ips or host == jump_public_ip
                logger.info(f"是否跳转服务器本身: {is_jump_server_target}")

                if is_jump_server_target:
                    # 目标就是跳转服务器本身，直接上传到目标路径
                    logger.info(f"目标主机 {host} 是跳转服务器本身，直接上传到目标路径")
                    sftp = self.jump_client.open_sftp()
                    sftp.put(local_path, remote_path)
                    sftp.close()
                    logger.info(f"文件已直接上传到跳转服务器: {remote_path}")
                    return True
                else:
                    # 使用SCP通过跳转服务器
                    # 先传输到跳转服务器，再传输到目标主机
                    jump_temp_path = f"/tmp/{os.path.basename(local_path)}"

                    # 上传到跳转服务器
                    sftp = self.jump_client.open_sftp()
                    sftp.put(local_path, jump_temp_path)
                    sftp.close()
                    logger.info(f"文件已上传到跳转服务器: {jump_temp_path}")

                    # 检查跳转服务器上的文件大小
                    check_cmd = f"ls -la {jump_temp_path}"
                    stdin, stdout, stderr = self.jump_client.exec_command(check_cmd)
                    ls_output = stdout.read().decode().strip()
                    logger.info(f"跳转服务器文件状态: {ls_output}")

                    # 从跳转服务器传输到目标主机
                    # 免密配置完成后，直接使用 scp 即可，不需要 sshpass
                    # 注意：不设置传输超时，让传输自然完成
                    # ServerAliveInterval 保持连接活跃，避免因空闲断开
                    scp_cmd = f"scp -o StrictHostKeyChecking=no -o ConnectTimeout=30 -o ServerAliveInterval=30 -o ServerAliveCountMax=3 {jump_temp_path} {username}@{host}:{remote_path}"
                    logger.info(f"开始 SCP 传输: {jump_temp_path} -> {host}:{remote_path}")
                    logger.debug(f"执行 SCP: {scp_cmd}")
                    # exec_command 的 timeout=None 表示不设置超时，让传输自然完成
                    stdin, stdout, stderr = self.jump_client.exec_command(scp_cmd, timeout=None)
                    exit_code = stdout.channel.recv_exit_status()

                    # 读取输出
                    scp_stdout = stdout.read().decode()
                    scp_stderr = stderr.read().decode()

                    if scp_stdout:
                        logger.info(f"SCP stdout: {scp_stdout}")
                    if scp_stderr:
                        logger.warning(f"SCP stderr: {scp_stderr}")

                    # 清理跳转服务器上的临时文件
                    self.jump_client.exec_command(f"rm -f {jump_temp_path}")

                    if exit_code == 0:
                        # 验证目标文件是否存在
                        logger.info(f"SCP 返回成功，验证目标文件...")
                        return True
                    else:
                        logger.error(f"SCP 失败: exit_code={exit_code}, stderr={scp_stderr}")
                        return False
            else:
                # 没有跳转服务器，程序可能在跳转服务器上运行
                logger.info(f"无跳转服务器连接，检查目标主机是否是本机...")

                # 检查目标主机是否是本机
                import socket
                local_ips = []
                try:
                    # 获取本机所有 IP
                    hostname = socket.gethostname()
                    local_ips.append(socket.gethostbyname(hostname))
                    # 也添加内网 IP
                    for ip in socket.gethostbyname_ex(hostname)[2]:
                        if ip not in local_ips:
                            local_ips.append(ip)
                except:
                    pass

                logger.info(f"本机 IPs: {local_ips}")
                logger.info(f"目标主机: {host}")

                if host in local_ips or host == "127.0.0.1" or host == "localhost":
                    # 目标是本机，直接复制文件
                    logger.info(f"目标主机 {host} 是本机，直接复制文件")
                    import shutil
                    try:
                        # 确保目标目录存在
                        import os
                        os.makedirs(os.path.dirname(remote_path), exist_ok=True)
                        shutil.copy2(local_path, remote_path)
                        logger.info(f"文件已复制到: {remote_path}")
                        return True
                    except Exception as e:
                        logger.error(f"复制文件失败: {e}")
                        return False
                else:
                    # 通过 SSH 直接传输到目标主机
                    logger.info(f"通过 SSH 传输到目标主机: {host}")
                    return conn.put_file(local_path, remote_path)

        except Exception as e:
            logger.error(f"文件传输异常: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False

    def execute_on_jumphost(self, host: str, port: int, username: str,
                           password: Optional[str], command: str,
                           timeout: int = 30) -> SSHResult:
        """
        在跳板机上执行命令

        Args:
            host: 跳板机主机
            port: 跳板机端口
            username: 用户名
            password: 密码
            command: 要执行的命令
            timeout: 超时时间

        Returns:
            SSHResult: 执行结果
        """
        # 确保跳板机已连接
        if not self._jump_connected or not self.jump_client:
            # 临时更新 jumphost_config 以连接
            original_config = self.jumphost_config
            self.jumphost_config = {
                "host": host,
                "port": port,
                "username": username,
                "password": password
            }
            if not self.connect_jumphost(timeout):
                return SSHResult(
                    success=False,
                    exit_code=-1,
                    stdout="",
                    stderr="无法连接跳板机",
                    host=host,
                    command=command
                )
            self.jumphost_config = original_config

        try:
            stdin, stdout, stderr = self.jump_client.exec_command(command, timeout=timeout)
            exit_code = stdout.channel.recv_exit_status()
            stdout_str = stdout.read().decode('utf-8', errors='replace')
            stderr_str = stderr.read().decode('utf-8', errors='replace')

            return SSHResult(
                success=exit_code == 0,
                exit_code=exit_code,
                stdout=stdout_str,
                stderr=stderr_str,
                host=host,
                command=command
            )
        except Exception as e:
            return SSHResult(
                success=False,
                exit_code=-1,
                stdout="",
                stderr=str(e),
                host=host,
                command=command
            )

    def close_all(self):
        """关闭所有连接"""
        for conn in self.connections.values():
            conn.disconnect()
        self.connections.clear()

        if self.jump_client:
            self.jump_client.close()
            self.jump_client = None
        self._jump_connected = False
        logger.info("所有SSH连接已关闭")

    @contextmanager
    def connection(self, host: str, port: int = 22,
                   username: str = "ubuntu",
                   password: Optional[str] = None,
                   private_key: Optional[str] = None,
                   timeout: int = 30):
        """上下文管理器方式使用连接"""
        conn = self.get_connection(
            host=host,
            port=port,
            username=username,
            password=password,
            private_key=private_key,
            timeout=timeout
        )
        try:
            yield conn
        finally:
            # 连接保留在连接池中，不主动断开
            pass


def create_ssh_manager_from_config(jumphost_config) -> SSHManager:
    """从配置创建SSH管理器"""
    if not jumphost_config:
        return SSHManager()

    config = {
        "host": jumphost_config.host,
        "port": jumphost_config.port,
        "username": jumphost_config.username,
        "password": jumphost_config.password,
        "private_key": jumphost_config.private_key
    }

    return SSHManager(config)
