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

    @property
    def success(self) -> bool:
        return self.status == StepStatus.SUCCESS

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

    def __init__(self, config, ssh_manager, batch_executor, logger=None):
        """
        初始化步骤

        Args:
            config: 集群配置
            ssh_manager: SSH管理器
            batch_executor: 批量执行器
            logger: 日志记录器
        """
        self.config = config
        self.ssh_manager = ssh_manager
        self.batch_executor = batch_executor
        self.logger = logger or get_logger()
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
        运行步骤（包含重试逻辑）

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

        # 执行步骤（支持重试）
        result = None
        while self._retry_count < self.max_retries:
            try:
                result = self.execute(hosts)

                if result.success:
                    # 后置检查
                    if self.post_check(hosts):
                        self._status = StepStatus.SUCCESS
                        result.duration = time.time() - start_time
                        self.logger.end_step(
                            self.step_id,
                            success=True,
                            message=result.message,
                            details=result.details
                        )
                        return result
                    else:
                        result.status = StepStatus.FAILED
                        result.message = "后置检查失败"
                else:
                    self._retry_count += 1
                    if self._retry_count < self.max_retries:
                        self._status = StepStatus.RETRY
                        self.logger.warning(
                            f"[{self.step_id}] 执行失败，正在重试 ({self._retry_count}/{self.max_retries})"
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
                      sudo: bool = False) -> Dict[str, Any]:
        """
        批量执行命令的便捷方法

        Args:
            hosts: 主机列表
            command: 命令
            sudo: 是否使用sudo

        Returns:
            执行结果字典
        """
        if self.supports_batch:
            return self.batch_executor.execute(hosts, command, sudo=sudo)
        else:
            # 逐个执行
            results = {}
            for host in hosts:
                result = self.ssh_manager.execute_on_host(host, command, sudo=sudo)
                results[host] = {
                    "success": result.success,
                    "exit_code": result.exit_code,
                    "stdout": result.stdout,
                    "stderr": result.stderr
                }
            return results

    def execute_on_host(self, host: str, command: str,
                        sudo: bool = False) -> Dict[str, Any]:
        """
        在单个主机上执行命令

        Args:
            host: 主机
            command: 命令
            sudo: 是否使用sudo

        Returns:
            执行结果字典
        """
        result = self.ssh_manager.execute_on_host(host, command, sudo=sudo)
        return {
            "success": result.success,
            "exit_code": result.exit_code,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "duration": result.duration
        }

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
