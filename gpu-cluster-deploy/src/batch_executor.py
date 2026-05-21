"""
批量执行器 - 封装pdsh，支持并行执行、超时控制
"""

import subprocess
import time
import re
from typing import Dict, List, Optional, Tuple, Any, Callable
import os
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor, as_completed
import logging
import os

# 使用统一的日志管理器
from src.utils.logger import get_logger
logger = get_logger()


@dataclass
class BatchResult:
    """批量执行结果"""
    host: str
    success: bool
    exit_code: int
    stdout: str
    stderr: str
    duration: float = 0.0

    def __str__(self):
        status = "✓" if self.success else "✗"
        return f"{status} [{self.host}] exit={self.exit_code}"


@dataclass
class ExecutionSummary:
    """执行摘要"""
    total_hosts: int = 0
    successful: int = 0
    failed: int = 0
    timeout: int = 0
    results: Dict[str, BatchResult] = field(default_factory=dict)
    total_duration: float = 0.0

    @property
    def success_rate(self) -> float:
        if self.total_hosts == 0:
            return 0.0
        return self.successful / self.total_hosts * 100

    def get_failed_hosts(self) -> List[str]:
        return [host for host, result in self.results.items() if not result.success]

    def get_successful_hosts(self) -> List[str]:
        return [host for host, result in self.results.items() if result.success]

    def __str__(self):
        return (f"执行摘要: 总计={self.total_hosts}, 成功={self.successful}, "
                f"失败={self.failed}, 超时={self.timeout}, 成功率={self.success_rate:.1f}%")


class PdshExecutor:
    """pdsh封装执行器"""

    def __init__(self, pdsh_path: str = "pdsh",
                 default_timeout: int = 300,
                 max_parallel: int = 10,
                 ssh_user: str = "ubuntu",
                 ssh_port: int = 22,
                 ssh_options: Optional[List[str]] = None):
        """
        初始化pdsh执行器

        Args:
            pdsh_path: pdsh命令路径
            default_timeout: 默认超时时间（秒）
            max_parallel: 最大并行数
            ssh_user: SSH用户名
            ssh_port: SSH端口
            ssh_options: SSH额外选项
        """
        self.pdsh_path = pdsh_path
        self.default_timeout = default_timeout
        self.max_parallel = max_parallel
        self.ssh_user = ssh_user
        self.ssh_port = ssh_port
        self.ssh_options = ssh_options or [
            "-o StrictHostKeyChecking=no",
            "-o UserKnownHostsFile=/dev/null",
            "-o ConnectTimeout=30"
        ]

        # 检查pdsh是否可用
        self._check_pdsh_available()

    def _check_pdsh_available(self):
        """检查pdsh是否可用"""
        try:
            result = subprocess.run(
                [self.pdsh_path, "-V"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                logger.debug(f"pdsh可用: {result.stdout.split()[1]}")
            else:
                logger.warning("pdsh可能不可用")
        except FileNotFoundError:
            logger.warning(f"pdsh未找到: {self.pdsh_path}")
        except Exception as e:
            logger.warning(f"检查pdsh失败: {e}")

    def _build_pdsh_command(self, hosts: List[str], command: str,
                            timeout: Optional[int] = None,
                            sudo: bool = False,
                            sudo_password: Optional[str] = None) -> Tuple[List[str], Dict[str, str]]:
        """构建pdsh命令"""
        timeout = timeout or self.default_timeout

        # 主机列表格式
        host_list = ",".join(hosts)

        # 构建远程命令
        remote_cmd = command
        if sudo:
            if sudo_password:
                remote_cmd = f"echo '{sudo_password}' | sudo -S {command}"
            else:
                remote_cmd = f"sudo {command}"

        # pdsh命令
        pdsh_cmd = [
            self.pdsh_path,
            "-R", "ssh",  # 使用SSH
            "-l", self.ssh_user,  # 用户名
            "-w", host_list,  # 主机列表
            "-f", str(self.max_parallel),  # 并行数
            "-S",  # 返回最大退出码
            "-t", str(timeout),  # 连接超时
        ]

        # SSH选项通过环境变量传递
        ssh_opts = " ".join(self.ssh_options)
        env = {
            "PDSH_SSH_ARGS": f"-p {self.ssh_port} {ssh_opts}"
        }

        # 添加命令
        pdsh_cmd.append(remote_cmd)

        return pdsh_cmd, env

    def execute(self, hosts: List[str], command: str,
                timeout: Optional[int] = None,
                sudo: bool = False,
                sudo_password: Optional[str] = None) -> ExecutionSummary:
        """
        执行批量命令

        Args:
            hosts: 主机列表
            command: 要执行的命令
            timeout: 超时时间
            sudo: 是否使用sudo
            sudo_password: sudo密码

        Returns:
            ExecutionSummary: 执行摘要
        """
        start_time = time.time()
        summary = ExecutionSummary(total_hosts=len(hosts))

        if not hosts:
            logger.warning("主机列表为空")
            return summary

        pdsh_cmd, env = self._build_pdsh_command(hosts, command, timeout, sudo, sudo_password)

        # 打印完整的执行命令
        env_str = " ".join(f"{k}='{v}'" for k, v in env.items()) if env else ""
        cmd_str = " ".join(pdsh_cmd)
        full_cmd = f"{env_str} {cmd_str}" if env_str else cmd_str
        logger.info(f"执行命令: {full_cmd}")

        try:
            result = subprocess.run(
                pdsh_cmd,
                capture_output=True,
                text=True,
                timeout=(timeout or self.default_timeout) + 60,  # 额外60秒缓冲
                env={**os.environ, **env}  # 合并环境变量
            )

            # 解析pdsh输出
            summary.results = self._parse_pdsh_output(result.stdout, result.stderr)
            summary.exit_code = result.returncode

        except subprocess.TimeoutExpired:
            logger.error(f"pdsh执行超时")
            for host in hosts:
                summary.results[host] = BatchResult(
                    host=host,
                    success=False,
                    exit_code=-1,
                    stdout="",
                    stderr="执行超时",
                    duration=timeout or self.default_timeout
                )
                summary.timeout += 1

        except Exception as e:
            logger.error(f"pdsh执行异常: {e}")
            for host in hosts:
                summary.results[host] = BatchResult(
                    host=host,
                    success=False,
                    exit_code=-1,
                    stdout="",
                    stderr=str(e)
                )

        # 统计结果并打印每个主机的输出
        for host, result in summary.results.items():
            if result.success:
                summary.successful += 1
            else:
                summary.failed += 1

            # 打印每个主机的执行结果
            status = "✓" if result.success else "✗"
            logger.info(f"  [{status}] {host}: exit_code={result.exit_code}")
            if result.stdout and result.stdout.strip():
                # 限制输出长度，避免日志过长
                stdout_lines = result.stdout.strip().split('\n')
                if len(stdout_lines) > 10:
                    logger.info(f"      stdout (前10行):")
                    for line in stdout_lines[:10]:
                        logger.info(f"        {line}")
                    logger.info(f"        ... (共{len(stdout_lines)}行)")
                else:
                    for line in stdout_lines:
                        logger.info(f"      {line}")
            if result.stderr and result.stderr.strip():
                stderr_lines = result.stderr.strip().split('\n')
                for line in stderr_lines[:10]:  # stderr最多显示10行
                    logger.warning(f"      stderr: {line}")

        summary.total_duration = time.time() - start_time
        logger.info(str(summary))

        return summary

    def _parse_pdsh_output(self, stdout: str, stderr: str) -> Dict[str, BatchResult]:
        """解析pdsh输出"""
        results = {}

        # pdsh输出格式: hostname: output
        # 或者: hostname: stderr (pdsh错误)

        for line in stdout.strip().split('\n'):
            if not line:
                continue

            # 解析主机名和输出
            match = re.match(r'^([^:]+):\s*(.*)$', line)
            if match:
                host = match.group(1)
                output = match.group(2)

                if host not in results:
                    results[host] = BatchResult(
                        host=host,
                        success=True,
                        exit_code=0,
                        stdout=output,
                        stderr=""
                    )
                else:
                    results[host].stdout += "\n" + output

        # 解析stderr
        for line in stderr.strip().split('\n'):
            if not line:
                continue

            match = re.match(r'^([^:]+):\s*(.*)$', line)
            if match:
                host = match.group(1)
                error = match.group(2)

                # 检查是否是pdsh错误
                if "ssh exited with exit code" in error.lower():
                    exit_code = self._extract_exit_code(error)
                    if host in results:
                        results[host].success = exit_code == 0
                        results[host].exit_code = exit_code
                    else:
                        results[host] = BatchResult(
                            host=host,
                            success=exit_code == 0,
                            exit_code=exit_code,
                            stdout="",
                            stderr=error
                        )
                else:
                    if host in results:
                        results[host].stderr += "\n" + error
                    else:
                        results[host] = BatchResult(
                            host=host,
                            success=False,
                            exit_code=1,
                            stdout="",
                            stderr=error
                        )

        return results

    def _extract_exit_code(self, error: str) -> int:
        """从错误信息中提取退出码"""
        match = re.search(r'exit code\s+(\d+)', error)
        if match:
            return int(match.group(1))
        return 1

    def execute_script(self, hosts: List[str], script_path: str,
                       timeout: Optional[int] = None,
                       sudo: bool = False,
                       sudo_password: Optional[str] = None,
                       args: Optional[List[str]] = None) -> ExecutionSummary:
        """
        在远程主机上执行本地脚本

        Args:
            hosts: 主机列表
            script_path: 本地脚本路径
            timeout: 超时时间
            sudo: 是否使用sudo
            sudo_password: sudo密码
            args: 脚本参数

        Returns:
            ExecutionSummary: 执行摘要
        """
        # 读取脚本内容
        with open(script_path, 'r') as f:
            script_content = f.read()

        # 构建命令（通过stdin传递脚本）
        args_str = " ".join(args) if args else ""
        command = f"bash -s -- {args_str}"

        # 使用cat和bash执行
        full_command = f"cat << 'SCRIPT_EOF' | {command}\n{script_content}\nSCRIPT_EOF"

        return self.execute(hosts, full_command, timeout, sudo, sudo_password)


class ParallelExecutor:
    """并行执行器（不依赖pdsh）"""

    def __init__(self, max_workers: int = 10):
        self.max_workers = max_workers

    def execute(self, hosts: List[str], command: str,
                executor_func: Callable[[str, str], BatchResult],
                timeout: Optional[int] = None) -> ExecutionSummary:
        """
        并行执行命令

        Args:
            hosts: 主机列表
            command: 命令
            executor_func: 执行函数 (host, command) -> BatchResult
            timeout: 整体超时时间

        Returns:
            ExecutionSummary
        """
        start_time = time.time()
        summary = ExecutionSummary(total_hosts=len(hosts))

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {
                executor.submit(executor_func, host, command): host
                for host in hosts
            }

            for future in as_completed(futures, timeout=timeout):
                host = futures[future]
                try:
                    result = future.result(timeout=timeout)
                    summary.results[host] = result
                    if result.success:
                        summary.successful += 1
                    else:
                        summary.failed += 1
                except Exception as e:
                    summary.results[host] = BatchResult(
                        host=host,
                        success=False,
                        exit_code=-1,
                        stdout="",
                        stderr=str(e)
                    )
                    summary.failed += 1

        summary.total_duration = time.time() - start_time
        return summary


class BatchExecutor:
    """统一的批量执行器"""

    def __init__(self, ssh_manager=None, use_pdsh: bool = False, config=None, **kwargs):
        """
        初始化批量执行器

        Args:
            ssh_manager: SSH管理器实例
            use_pdsh: 是否使用pdsh（默认False，使用SSH模式）
                      注意：pdsh模式需要先配置SSH免密和hosts
            config: 集群配置（用于获取节点认证信息）
            **kwargs: 传递给PdshExecutor的参数
        """
        self.ssh_manager = ssh_manager
        self.use_pdsh = use_pdsh
        self.config = config
        self._pdsh_kwargs = kwargs  # 保存参数用于后续切换

        # 初始化并行执行器
        self.parallel_executor = ParallelExecutor(
            max_workers=kwargs.get('max_parallel', 10)
        )

        if use_pdsh:
            self.pdsh_executor = PdshExecutor(**kwargs)
        else:
            self.pdsh_executor = None

    def enable_pdsh(self, ssh_user: str = "ubuntu"):
        """
        启用pdsh模式（在SSH免密配置完成后调用）

        Args:
            ssh_user: SSH用户名
        """
        self.use_pdsh = True
        # 排除已存在的 ssh_user 参数，避免重复传入
        pdsh_kwargs = {k: v for k, v in self._pdsh_kwargs.items() if k != 'ssh_user'}

        # 添加跳转服务器的 ProxyJump 配置
        if self.config and self.config.jumphost:
            jh = self.config.jumphost
            jh_user = getattr(jh.auth, 'username', 'ubuntu') if hasattr(jh, 'auth') and jh.auth else 'ubuntu'
            jh_host = jh.host
            jh_port = getattr(jh, 'port', 22)
            proxy_jump = f"-o ProxyJump={jh_user}@{jh_host}:{jh_port}"

            # 获取或创建 ssh_options
            ssh_options = pdsh_kwargs.get('ssh_options', [
                "-o StrictHostKeyChecking=no",
                "-o UserKnownHostsFile=/dev/null",
                "-o ConnectTimeout=30"
            ])
            # 添加 ProxyJump 选项
            if proxy_jump not in ssh_options:
                ssh_options = list(ssh_options) + [proxy_jump]
            pdsh_kwargs['ssh_options'] = ssh_options
            logger.info(f"已配置跳转服务器 ProxyJump: {jh_user}@{jh_host}:{jh_port}")

        self.pdsh_executor = PdshExecutor(ssh_user=ssh_user, **pdsh_kwargs)
        logger.info("已切换到pdsh批量执行模式")

    def _get_node_auth(self, host: str) -> Tuple[str, str]:
        """获取节点认证信息"""
        username = 'ubuntu'
        password = None

        if self.config:
            for node in self.config.nodes:
                if node.ip == host:
                    if hasattr(node, 'username') and node.username:
                        username = node.username
                    if hasattr(node, 'password') and node.password:
                        password = node.password
                    break

            # 如果节点没有单独配置，尝试从jumphost.node_auth获取
            if password is None and self.config.jumphost and self.config.jumphost.node_auth:
                username = self.config.jumphost.node_auth.username or username
                password = self.config.jumphost.node_auth.password

        return username, password

    def execute(self, hosts: List[str], command: str,
                timeout: Optional[int] = None,
                sudo: bool = False,
                sudo_password: Optional[str] = None) -> ExecutionSummary:
        """执行批量命令"""
        if self.use_pdsh and self.pdsh_executor:
            return self.pdsh_executor.execute(hosts, command, timeout, sudo, sudo_password)
        elif self.ssh_manager:
            return self._execute_via_ssh(hosts, command, timeout, sudo, sudo_password)
        else:
            raise ValueError("需要配置ssh_manager或启用pdsh")

    def _execute_via_ssh(self, hosts: List[str], command: str,
                         timeout: Optional[int] = None,
                         sudo: bool = False,
                         sudo_password: Optional[str] = None) -> ExecutionSummary:
        """通过SSH管理器执行"""
        # 打印完整的执行命令
        full_command = f"sudo {command}" if sudo else command
        hosts_str = ",".join(hosts)
        logger.info(f"批量执行: pdsh -w {hosts_str} \"{full_command}\"")

        def executor_func(host: str, cmd: str) -> BatchResult:
            # 获取节点认证信息
            username, password = self._get_node_auth(host)

            result = self.ssh_manager.execute_on_host(
                host=host,
                command=cmd,
                username=username,
                password=password,
                timeout=timeout or 300,
                sudo=sudo,
                sudo_password=sudo_password or password
            )
            return BatchResult(
                host=host,
                success=result.success,
                exit_code=result.exit_code,
                stdout=result.stdout,
                stderr=result.stderr,
                duration=result.duration
            )

        summary = self.parallel_executor.execute(hosts, command, executor_func, timeout)

        # 打印每个主机的执行结果
        for host, result in summary.results.items():
            status = "✓" if result.success else "✗"
            logger.info(f"{host}: {status} exit_code={result.exit_code}, duration={result.duration:.2f}s")
            if result.stdout and result.stdout.strip():
                stdout_lines = result.stdout.strip().split('\n')
                if len(stdout_lines) > 20:
                    logger.info(f"{host}: stdout (前20行/共{len(stdout_lines)}行):")
                    for line in stdout_lines[:20]:
                        logger.info(f"{host}:   {line}")
                    logger.info(f"{host}:   ... (省略 {len(stdout_lines) - 20} 行)")
                else:
                    logger.info(f"{host}: stdout:")
                    for line in stdout_lines:
                        logger.info(f"{host}:   {line}")
            if result.stderr and result.stderr.strip():
                stderr_lines = result.stderr.strip().split('\n')
                logger.warning(f"{host}: stderr:")
                for line in stderr_lines[:10]:
                    logger.warning(f"{host}:   {line}")
                if len(stderr_lines) > 10:
                    logger.warning(f"{host}:   ... (共{len(stderr_lines)}行)")

        logger.info(f"执行摘要: 总计={summary.total_hosts}, 成功={summary.successful}, 失败={summary.failed}")
        return summary

    def check_hosts_connectivity(self, hosts: List[str]) -> Dict[str, bool]:
        """检查主机连通性"""
        results = {}

        def check_host(host: str) -> Tuple[str, bool]:
            try:
                if self.ssh_manager:
                    # 获取节点认证信息
                    username, password = self._get_node_auth(host)
                    conn = self.ssh_manager.get_connection(
                        host,
                        username=username,
                        password=password
                    )
                    if conn and conn.is_connected():
                        result = conn.execute("echo 'connectivity_check'")
                        return host, result.success
                elif self.pdsh_executor:
                    summary = self.pdsh_executor.execute([host], "echo 'connectivity_check'", timeout=10)
                    return host, summary.successful > 0
                return host, False
            except Exception as e:
                logger.debug(f"连接检查失败 {host}: {e}")
                return host, False

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = {executor.submit(check_host, host): host for host in hosts}

            for future in as_completed(futures):
                host, connected = future.result()
                results[host] = connected

        return results

    def copy_file(self, hosts: List[str], local_path: str, remote_path: str,
                  sudo: bool = False) -> Dict[str, bool]:
        """复制文件到远程主机"""
        results = {}

        if not self.ssh_manager:
            logger.error("文件复制需要SSH管理器")
            return {host: False for host in hosts}

        def copy_to_host(host: str) -> Tuple[str, bool]:
            try:
                conn = self.ssh_manager.get_connection(host)
                if not conn:
                    return host, False

                # 上传到临时位置
                temp_path = f"/tmp/{os.path.basename(local_path)}"
                if not conn.put_file(local_path, temp_path):
                    return host, False

                # 移动到目标位置（如果目标位置和临时位置不同）
                if temp_path != remote_path:
                    if sudo:
                        result = conn.execute(f"sudo mv {temp_path} {remote_path}", sudo=True)
                    else:
                        result = conn.execute(f"mv {temp_path} {remote_path}")

                    return host, result.success
                else:
                    # 目标位置和临时位置相同，上传即完成
                    return host, True
            except Exception as e:
                logger.error(f"复制文件到 {host} 失败: {e}")
                return host, False

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = {executor.submit(copy_to_host, host): host for host in hosts}

            for future in as_completed(futures):
                host, success = future.result()
                results[host] = success

        return results
