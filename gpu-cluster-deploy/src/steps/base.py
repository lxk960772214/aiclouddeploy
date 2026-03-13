"""
部署步骤基类
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Any
import time

from src.utils.logger import get_logger


class StepStatus(Enum):
    """步骤状态"""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    RETRY = "retry"


@dataclass
class StepResult:
    """步骤执行结果"""
    step_id: str
    step_name: str
    status: StepStatus
    message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)
    duration: float = 0.0
    host_results: Dict[str, Any] = field(default_factory=dict)  # 按主机的结果
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return self.status in (StepStatus.SUCCESS, StepStatus.SKIPPED)

    def to_dict(self) -> Dict:
        return {
            "step_id": self.step_id,
            "step_name": self.step_name,
            "status": self.status.value,
            "message": self.message,
            "details": self.details,
            "duration": self.duration,
            "host_results": self.host_results,
            "errors": self.errors
        }


class BaseStep(ABC):
    """部署步骤基类"""

    # 步骤元信息
    step_id: str = ""
    step_name: str = ""
    step_description: str = ""
    requires_sudo: bool = False
    requires_reboot: bool = False
    can_skip: bool = False
    max_retries: int = 3
    timeout: int = 300  # 秒

    # 批量执行配置
    supports_batch: bool = True  # 是否支持批量执行
    batch_size: int = 10  # 批量大小

    # 配置检查配置
    skip_if_configured: bool = True  # 如果已配置，是否跳过执行

    def __init__(self, config, ssh_manager, batch_executor, logger=None, versions=None):
        """
        初始化步骤

        Args:
            config: 集群配置
            ssh_manager: SSH管理器
            batch_executor: 批量执行器
            logger: 日志记录器
            versions: 版本配置
        """
        self.config = config
        self.ssh_manager = ssh_manager
        self.batch_executor = batch_executor
        self.logger = logger or get_logger()
        self.versions = versions
        self._status = StepStatus.PENDING
        self._retry_count = 0

    @property
    def status(self) -> StepStatus:
        return self._status

    @abstractmethod
    def execute(self, hosts: List[str]) -> StepResult:
        """
        执行步骤

        Args:
            hosts: 目标主机列表

        Returns:
            StepResult: 执行结果
        """
        pass

    def pre_check(self, hosts: List[str]) -> bool:
        """
        前置检查

        Args:
            hosts: 目标主机列表

        Returns:
            bool: 检查是否通过
        """
        return True

    def post_check(self, hosts: List[str]) -> bool:
        """
        后置检查

        Args:
            hosts: 目标主机列表

        Returns:
            bool: 检查是否通过
        """
        return True

    def is_configured(self, host: str) -> tuple:
        """
        检查单个主机上的配置是否已完成

        子类应重写此方法以实现具体的配置检查逻辑。

        Args:
            host: 主机地址

        Returns:
            tuple[bool, str]: (是否已配置, 检查详情/原因)
        """
        # 默认返回 False，强制子类实现具体检查逻辑
        return False, "未实现配置检查"

    def check_all_configured(self, hosts: List[str]) -> Dict[str, tuple]:
        """
        检查所有主机的配置状态

        Args:
            hosts: 主机列表

        Returns:
            Dict[str, tuple[bool, str]]: 每个主机的配置检查结果
        """
        results = {}
        for host in hosts:
            try:
                results[host] = self.is_configured(host)
            except Exception as e:
                self.logger.warning(
                    f"[{self.step_id}] [{host}] 配置检查异常: {e}"
                )
                results[host] = (False, f"检查异常: {str(e)}")
        return results

    def rollback(self, hosts: List[str]) -> bool:
        """
        回滚操作

        Args:
            hosts: 目标主机列表

        Returns:
            bool: 回滚是否成功
        """
        self.logger.warning(f"[{self.step_id}] 步骤不支持回滚")
        return True

    def run(self, hosts: List[str]) -> StepResult:
        """
        运行步骤（包含重试逻辑和配置检查）

        Args:
            hosts: 目标主机列表

        Returns:
            StepResult: 执行结果
        """
        start_time = time.time()
        self._status = StepStatus.RUNNING

        self.logger.start_step(self.step_id, self.step_name)

        # 前置检查
        if not self.pre_check(hosts):
            self._status = StepStatus.FAILED
            result = StepResult(
                step_id=self.step_id,
                step_name=self.step_name,
                status=StepStatus.FAILED,
                message="前置检查失败"
            )
            self.logger.end_step(self.step_id, success=False, message="前置检查失败")
            return result

        # 配置检查：如果已配置则跳过
        hosts_to_execute = hosts
        config_status = {}
        skipped_hosts = []

        if self.skip_if_configured:
            self.logger.info(f"[{self.step_id}] 检查配置状态...")
            config_status = self.check_all_configured(hosts)

            # 筛选需要执行的主机
            hosts_to_execute = [
                h for h, (configured, _) in config_status.items() if not configured
            ]
            skipped_hosts = [
                h for h, (configured, _) in config_status.items() if configured
            ]

            if skipped_hosts:
                skip_reasons = {
                    h: reason for h, (_, reason) in config_status.items() if h in skipped_hosts
                }
                self.logger.info(
                    f"[{self.step_id}] {len(skipped_hosts)} 台主机已配置，跳过: "
                    f"{', '.join(skipped_hosts[:5])}{'...' if len(skipped_hosts) > 5 else ''}"
                )

            # 如果所有主机都已配置，直接返回 SKIPPED
            if not hosts_to_execute:
                self._status = StepStatus.SKIPPED
                duration = time.time() - start_time
                result = StepResult(
                    step_id=self.step_id,
                    step_name=self.step_name,
                    status=StepStatus.SKIPPED,
                    message=f"所有 {len(hosts)} 台主机已配置，跳过执行",
                    duration=duration,
                    details={
                        "skipped_count": len(skipped_hosts),
                        "skip_reasons": skip_reasons
                    }
                )
                self.logger.end_step(
                    self.step_id,
                    success=True,
                    message=f"已跳过（所有 {len(hosts)} 台主机已配置）"
                )
                return result

        # 执行步骤（支持重试）
        result = None
        while self._retry_count < self.max_retries:
            try:
                result = self.execute(hosts_to_execute)

                if result.success:
                    # 后置检查
                    if self.post_check(hosts_to_execute):
                        self._status = StepStatus.SUCCESS
                        result.duration = time.time() - start_time

                        # 添加跳过信息
                        if skipped_hosts:
                            result.details["skipped_hosts"] = skipped_hosts
                            result.details["skipped_count"] = len(skipped_hosts)
                            result.message = (
                                f"{result.message} (跳过 {len(skipped_hosts)} 台已配置主机)"
                                if result.message else f"成功 (跳过 {len(skipped_hosts)} 台已配置主机)"
                            )

                        self.logger.end_step(
                            self.step_id,
                            success=True,
                            message=result.message,
                            details=result.details
                        )
                        return result
                    else:
                        # 后置检查失败，增加重试计数
                        self._retry_count += 1
                        result.status = StepStatus.FAILED
                        result.message = "后置检查失败"
                        if self._retry_count < self.max_retries:
                            self._status = StepStatus.RETRY
                            self.logger.warning(
                                f"[{self.step_id}] 后置检查失败，正在重试 ({self._retry_count}/{self.max_retries})"
                            )
                else:
                    self._retry_count += 1
                    if self._retry_count < self.max_retries:
                        self._status = StepStatus.RETRY
                        # 打印详细错误信息
                        error_msg = result.message or "未知错误"
                        if result.errors:
                            error_msg += f" | 错误详情: {'; '.join(result.errors)}"
                        self.logger.warning(
                            f"[{self.step_id}] 执行失败: {error_msg}"
                        )
                        self.logger.warning(
                            f"[{self.step_id}] 正在重试 ({self._retry_count}/{self.max_retries})"
                        )

            except Exception as e:
                self._retry_count += 1
                result = StepResult(
                    step_id=self.step_id,
                    step_name=self.step_name,
                    status=StepStatus.FAILED,
                    message=f"执行异常: {str(e)}",
                    errors=[str(e)]
                )
                self.logger.error(f"[{self.step_id}] 执行异常: {e}")

                if self._retry_count < self.max_retries:
                    self._status = StepStatus.RETRY
                    self.logger.warning(
                        f"[{self.step_id}] 正在重试 ({self._retry_count}/{self.max_retries})"
                    )

        # 所有重试都失败
        self._status = StepStatus.FAILED
        result.duration = time.time() - start_time
        self.logger.end_step(
            self.step_id,
            success=False,
            message=result.message,
            details={"retry_count": self._retry_count}
        )
        return result

    def execute_batch(self, hosts: List[str], command: str,
                      sudo: bool = False) -> Any:
        """
        批量执行命令的便捷方法

        Args:
            hosts: 主机列表
            command: 命令
            sudo: 是否使用sudo

        Returns:
            ExecutionSummary 对象
        """
        # 打印执行的完整命令
        full_command = f"sudo {command}" if sudo else command
        hosts_str = ",".join(hosts)
        self.logger.info(f"[{self.step_id}] 批量执行: pdsh -w {hosts_str} \"{full_command}\"")

        if self.batch_executor:
            return self.batch_executor.execute(hosts, command, sudo=sudo)
        else:
            # 逐个执行
            from src.batch_executor import BatchResult, ExecutionSummary
            results = {}
            for host in hosts:
                username, password = self._get_node_auth(host)
                result = self.ssh_manager.execute_on_host(
                    host, command, username=username, password=password, sudo=sudo
                )
                results[host] = BatchResult(
                    host=host,
                    success=result.success,
                    exit_code=result.exit_code,
                    stdout=result.stdout,
                    stderr=result.stderr
                )

            summary = ExecutionSummary(total_hosts=len(hosts))
            summary.results = results
            summary.successful = sum(1 for r in results.values() if r.success)
            summary.failed = len(hosts) - summary.successful
            return summary

    def execute_on_host(self, host: str, command: str,
                        sudo: bool = False, username: str = None,
                        password: str = None, timeout: int = None,
                        use_login_user: bool = False) -> Dict[str, Any]:
        """
        在单个主机上执行命令

        Args:
            host: 主机
            command: 命令
            sudo: 是否使用sudo
            username: 用户名（可选，默认使用部署用户）
            password: 密码（可选）
            timeout: 超时时间（秒），默认使用 self.timeout
            use_login_user: True = 使用登录用户（step 0-11 用）
                           False = 使用部署用户（后续步骤用，默认）

        Returns:
            执行结果字典
        """
        # 打印执行的完整命令（显示实际执行的格式）
        if sudo:
            # sudo 命令会被包装成: echo 'password' | sudo -S sh -c "command"
            # 日志中不显示密码，但显示完整的命令结构
            self.logger.info(f"[{self.step_id}] [{host}] 执行: sudo sh -c \"{command}\"")
        else:
            self.logger.info(f"[{self.step_id}] [{host}] 执行: {command}")

        # 使用传入的超时或默认超时
        if timeout is None:
            timeout = self.timeout

        # 获取登录用户和部署用户
        login_user = self._get_login_user(host)
        deploy_user = self._get_deploy_user(host)

        # 确定连接用户
        if username is None:
            if use_login_user:
                username = login_user
            else:
                username = deploy_user

        # 获取认证信息
        # 关键逻辑：当部署用户 = 登录用户时，仍需使用登录用户的认证信息
        if use_login_user or deploy_user == login_user:
            # 使用登录用户的认证信息
            if password is None:
                password = self._get_login_password(host)
            private_key = self._get_login_private_key(host)
        else:
            # 部署用户 ≠ 登录用户，且 use_login_user=False
            # 此时部署用户已配置免密登录（step_11 已完成），不需要密码/密钥
            private_key = None

        result = self.ssh_manager.execute_on_host(
            host, command,
            username=username,
            password=password,
            private_key=private_key,
            sudo=sudo,
            sudo_password=password,  # 使用相同的密码作为 sudo 密码
            timeout=timeout
        )

        # 打印执行结果
        result_dict = {
            "success": result.success,
            "exit_code": result.exit_code,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "duration": result.duration
        }

        # 打印输出
        if result.stdout and result.stdout.strip():
            # 如果输出超过20行，只打印前20行和总行数
            stdout_lines = result.stdout.strip().split('\n')
            if len(stdout_lines) > 20:
                self.logger.info(f"[{self.step_id}] [{host}] stdout (前20行/共{len(stdout_lines)}行):")
                for line in stdout_lines[:20]:
                    self.logger.info(f"  {line}")
                self.logger.info(f"  ... (省略 {len(stdout_lines) - 20} 行)")
            else:
                self.logger.info(f"[{self.step_id}] [{host}] stdout:")
                for line in stdout_lines:
                    self.logger.info(f"  {line}")

        if result.stderr and result.stderr.strip():
            stderr_lines = result.stderr.strip().split('\n')
            if len(stderr_lines) > 10:
                self.logger.warning(f"[{self.step_id}] [{host}] stderr (前10行/共{len(stderr_lines)}行):")
                for line in stderr_lines[:10]:
                    self.logger.warning(f"  {line}")
            else:
                self.logger.warning(f"[{self.step_id}] [{host}] stderr:")
                for line in stderr_lines:
                    self.logger.warning(f"  {line}")

        status = "✓" if result.success else "✗"
        self.logger.info(f"[{self.step_id}] [{host}] {status} exit_code={result.exit_code}, 耗时={result.duration:.2f}s")

        return result_dict

    def _get_node_config(self, host: str):
        """根据IP获取节点配置"""
        if not self.config:
            return None
        for node in self.config.nodes:
            if node.ip == host or node.hostname == host:
                return node
        return None

    def _get_login_user(self, host: str) -> str:
        """获取登录用户（必须指定）"""
        node = self._get_node_config(host)
        if node and hasattr(node, 'username') and node.username:
            return node.username
        return ""

    def _get_login_password(self, host: str) -> Optional[str]:
        """获取登录用户的密码"""
        node = self._get_node_config(host)
        if node and hasattr(node, 'password') and node.password:
            return node.password
        return None

    def _get_login_private_key(self, host: str) -> Optional[str]:
        """获取登录用户的私钥路径"""
        node = self._get_node_config(host)
        if node and hasattr(node, 'private_key') and node.private_key:
            return node.private_key
        return None

    def _get_deploy_user(self, host: str) -> str:
        """
        获取部署用户

        优先级:
        1. cluster.deploy_user
        2. nodes.username (登录用户)
        """
        # 优先使用集群级别的部署用户
        if self.config and hasattr(self.config, 'deploy_user') and self.config.deploy_user:
            return self.config.deploy_user

        # 否则使用登录用户
        return self._get_login_user(host)

    def put_file(self, hosts: List[str], local_path: str, remote_path: str) -> Dict[str, bool]:
        """
        上传文件到多个主机

        Args:
            hosts: 主机列表
            local_path: 本地文件路径
            remote_path: 远程文件路径

        Returns:
            每个主机的上传结果
        """
        return self.batch_executor.copy_file(hosts, local_path, remote_path)
