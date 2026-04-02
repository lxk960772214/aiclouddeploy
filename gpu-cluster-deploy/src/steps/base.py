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
    is_optional: bool = False  # 是否为可选步骤，失败不影响整体流程

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

                # 区分代码错误和网络错误
                # 代码错误（NameError, AttributeError, TypeError, SyntaxError 等）不应重试
                is_code_error = isinstance(e, (
                    NameError, AttributeError, TypeError, SyntaxError,
                    ValueError, KeyError, IndexError, ImportError,
                    NotImplementedError, AssertionError
                ))

                if is_code_error:
                    # 代码错误，直接失败，不重试
                    self.logger.error(
                        f"[{self.step_id}] 代码级错误，跳过重试: {type(e).__name__}: {e}"
                    )
                    break

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
            # 此时部署用户已配置免密登录（step_0d 已完成），不需要密码/密钥
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

    def smart_download(self, host: str, url: str, dest: str,
                       sudo: bool = False, stall_timeout: int = 300,
                       total_timeout: int = 7200) -> Dict[str, Any]:
        """
        智能下载：监控文件增长，只有长时间不增长才超时

        Args:
            host: 目标主机
            url: 下载URL
            dest: 目标文件路径
            sudo: 是否使用sudo
            stall_timeout: 停滞超时（秒），默认5分钟无增长则终止
            total_timeout: 总超时（秒），默认2小时

        Returns:
            下载结果字典
        """
        # 创建监控脚本
        # 注意：使用普通字符串拼接而非 f-string，避免 shell 变量 ${VAR} 被 Python 解释
        monitor_script = '''
set -e

DEST_FILE="''' + dest + '''"
URL="''' + url + '''"
STALL_TIMEOUT=''' + str(stall_timeout) + '''

# 检查下载工具
if command -v wget >/dev/null 2>&1; then
    HAS_WGET=1
else
    HAS_WGET=0
fi

if command -v curl >/dev/null 2>&1; then
    HAS_CURL=1
else
    HAS_CURL=0
fi

if [ "$HAS_WGET" -eq 0 ] && [ "$HAS_CURL" -eq 0 ]; then
    echo "ERROR: 未找到 wget 或 curl"
    exit 1
fi

# 启动下载（不设置超时，由监控脚本控制）
if [ "$HAS_WGET" -eq 1 ]; then
    wget -q -c -O "$DEST_FILE" --timeout=0 --tries=0 "$URL" 2>/dev/null &
else
    curl -s -L -C - -o "$DEST_FILE" --connect-timeout 60 --retry 0 -f "$URL" 2>/dev/null &
fi
DOWNLOAD_PID=$!

# 监控文件增长
LAST_SIZE=0
LAST_PROGRESS=$(date +%s)
START_TIME=$(date +%s)

while kill -0 $DOWNLOAD_PID 2>/dev/null; do
    if [ -f "$DEST_FILE" ]; then
        CURRENT_SIZE=$(stat -c%s "$DEST_FILE" 2>/dev/null || echo 0)
        CURRENT_TIME=$(date +%s)

        if [ "$CURRENT_SIZE" -gt "$LAST_SIZE" ]; then
            LAST_SIZE=$CURRENT_SIZE
            LAST_PROGRESS=$CURRENT_TIME
            # 每10MB打印进度
            SIZE_MB=$((CURRENT_SIZE / 1048576))
            if [ $((SIZE_MB % 10)) -eq 0 ] && [ "$LAST_SIZE" -ne "$CURRENT_SIZE" ]; then
                echo "PROGRESS: ${SIZE_MB} MB"
            fi
        else
            # 检查停滞超时
            STALLED=$((CURRENT_TIME - LAST_PROGRESS))
            if [ "$STALLED" -gt "$STALL_TIMEOUT" ]; then
                echo "ERROR: 下载停滞超时 ($STALL_TIMEOUT 秒无数据增长)"
                echo "ERROR: 已下载 $((LAST_SIZE / 1048576)) MB"
                echo "ERROR: 建议: 检查网络连接或使用其他下载源"
                kill $DOWNLOAD_PID 2>/dev/null || true
                exit 1
            fi
        fi
    fi
    sleep 2
done

# 检查下载结果
wait $DOWNLOAD_PID
EXIT_CODE=$?

if [ $EXIT_CODE -ne 0 ]; then
    echo "ERROR: 下载进程退出码: $EXIT_CODE"
    exit 1
fi

if [ ! -f "$DEST_FILE" ] || [ ! -s "$DEST_FILE" ]; then
    echo "ERROR: 下载后文件不存在或为空"
    exit 1
fi

FINAL_SIZE=$(stat -c%s "$DEST_FILE")
echo "SUCCESS: 下载完成 $((FINAL_SIZE / 1048576)) MB"
exit 0
'''
        self.logger.info(f"[{host}] 智能下载: {url}")
        self.logger.info(f"[{host}] 目标: {dest} (停滞超时: {stall_timeout}秒)")

        result = self.execute_on_host(host, monitor_script, sudo=sudo, timeout=total_timeout)

        # 解析输出
        stdout = result.get("stdout", "")
        success = result.get("success", False) and "SUCCESS:" in stdout

        if not success:
            # 提取错误信息
            for line in stdout.split('\n'):
                if "ERROR:" in line:
                    self.logger.error(f"[{host}] {line}")
        else:
            for line in stdout.split('\n'):
                if "SUCCESS:" in line:
                    self.logger.info(f"[{host}] ✅ {line}")

        return {
            "success": success,
            "stdout": stdout,
            "stderr": result.get("stderr", ""),
            "dest": dest
        }
