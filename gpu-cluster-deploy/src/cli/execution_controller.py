#!/usr/bin/env python3
"""
GPU Cluster Deploy - 执行控制器
协调模块管理器、SSH连接和执行流程的控制逻辑
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict, Any, Callable
from enum import Enum

from .main import CLIConfig, ExecutionMode


class ExecutionState(Enum):
    """执行状态枚举"""
    IDLE = "idle"
    INITIALIZING = "initializing"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class ExecutionResult:
    """执行结果数据类"""
    success: bool
    start_time: datetime
    end_time: Optional[datetime] = None
    total_modules: int = 0
    completed_modules: int = 0
    failed_modules: int = 0
    skipped_modules: int = 0
    module_results: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def duration_seconds(self) -> float:
        if self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration_seconds": self.duration_seconds,
            "total_modules": self.total_modules,
            "completed_modules": self.completed_modules,
            "failed_modules": self.failed_modules,
            "skipped_modules": self.skipped_modules,
            "module_results": self.module_results,
            "errors": self.errors,
            "warnings": self.warnings,
        }


class ExecutionController:
    """执行控制器

    协调模块管理器、SSH连接和执行流程的控制逻辑
    """

    def __init__(self, config: CLIConfig):
        self.config = config
        self.state = ExecutionState.IDLE
        self.result: Optional[ExecutionResult] = None

        # 组件（延迟初始化）
        self._config_loader = None
        self._ssh_manager = None
        self._batch_executor = None
        self._module_manager = None
        self._logger = None

        # 回调函数
        self._on_progress: Optional[Callable] = None
        self._on_module_start: Optional[Callable] = None
        self._on_module_complete: Optional[Callable] = None

    @property
    def config_loader(self):
        """延迟加载配置加载器"""
        if self._config_loader is None:
            from ..config_loader import ConfigLoader
            self._config_loader = ConfigLoader(self.config.config_dir)
        return self._config_loader

    @property
    def module_manager(self):
        """延迟加载模块管理器"""
        if self._module_manager is None:
            from ..deployment.module_manager import ModuleManager
            self._module_manager = ModuleManager()
        return self._module_manager

    @property
    def logger(self):
        """延迟加载日志器"""
        if self._logger is None:
            from ..utils.logger import DeployLogger
            self._logger = DeployLogger(
                log_dir=self.config.log_dir,
                log_level=self.config.log_level
            )
        return self._logger

    def set_callbacks(self,
                      on_progress: Optional[Callable] = None,
                      on_module_start: Optional[Callable] = None,
                      on_module_complete: Optional[Callable] = None):
        """设置回调函数"""
        self._on_progress = on_progress
        self._on_module_start = on_module_start
        self._on_module_complete = on_module_complete

    def run(self) -> bool:
        """执行部署"""
        self.state = ExecutionState.INITIALIZING
        self.result = ExecutionResult(start_time=datetime.now())

        try:
            # 1. 加载配置
            self.logger.info("正在加载配置...")
            if not self._load_config():
                return self._fail("配置加载失败")

            # 2. 预检查模式
            if self.config.dry_run:
                return self._dry_run()

            # 3. 只生成报告模式
            if self.config.report_only:
                return self._report_only()

            # 4. 初始化SSH
            self.logger.info("正在初始化SSH连接...")
            if not self._init_ssh():
                return self._fail("SSH初始化失败")

            # 5. 检查连通性
            self.logger.info("正在检查节点连通性...")
            if not self._check_connectivity():
                self.logger.warning("部分节点不可达")
                if not self.config.skip_confirmation:
                    if not self._confirm_continue():
                        return self._cancel()

            # 6. 执行部署
            self.state = ExecutionState.RUNNING
            success = self._execute()

            # 7. 生成报告
            self._generate_report()

            # 8. 清理
            self._cleanup()

            self.result.end_time = datetime.now()
            self.state = ExecutionState.COMPLETED if success else ExecutionState.FAILED
            self.result.success = success

            return success

        except KeyboardInterrupt:
            self.logger.warning("用户中断执行")
            self.state = ExecutionState.CANCELLED
            return self._cancel()
        except Exception as e:
            self.logger.error(f"执行异常: {e}")
            return self._fail(str(e))

    def _load_config(self) -> bool:
        """加载配置"""
        try:
            self._cluster_config = self.config_loader.load_cluster_config()
            self._versions_config = self.config_loader.load_versions_config()

            errors = self.config_loader.validate()
            if errors:
                for error in errors:
                    self.logger.error(f"配置错误: {error}")
                    self.result.errors.append(error)
                return False

            self.logger.info(f"配置加载成功: {self._cluster_config.name}")
            return True

        except Exception as e:
            self.logger.error(f"配置加载异常: {e}")
            self.result.errors.append(str(e))
            return False

    def _init_ssh(self) -> bool:
        """初始化SSH连接"""
        try:
            from ..ssh_manager import SSHManager, create_ssh_manager_from_config

            if self._cluster_config.jumphost:
                self._ssh_manager = create_ssh_manager_from_config(
                    self._cluster_config.jumphost
                )
                if not self._ssh_manager.connect_jumphost():
                    return False
            else:
                self._ssh_manager = SSHManager()

            from ..batch_executor import BatchExecutor
            self._batch_executor = BatchExecutor(
                ssh_manager=self._ssh_manager,
                use_pdsh=False,  # 初始使用SSH模式，不依赖免密
                ssh_user="ubuntu"
            )

            return True

        except Exception as e:
            self.logger.error(f"SSH初始化异常: {e}")
            self.result.errors.append(str(e))
            return False

    def _check_connectivity(self) -> bool:
        """检查节点连通性"""
        hosts = self._cluster_config.get_all_ips()
        results = self._batch_executor.check_hosts_connectivity(hosts)

        reachable = sum(1 for v in results.values() if v)
        total = len(results)

        self.logger.info(f"连通性检查: {reachable}/{total} 节点可达")

        if reachable < total:
            unreachable = [k for k, v in results.items() if not v]
            self.logger.warning(f"不可达节点: {unreachable}")
            self.result.warnings.append(f"不可达节点: {unreachable}")
            return False

        return True

    def _confirm_continue(self) -> bool:
        """确认是否继续"""
        self.logger.warning("是否继续? [y/N]")
        try:
            response = input().strip().lower()
            return response == 'y'
        except EOFError:
            return False

    def _dry_run(self) -> bool:
        """预检查模式"""
        self.logger.info("[DRY-RUN] 预检查模式，不执行实际部署")
        self._print_config_summary()
        self.result.success = True
        self.result.end_time = datetime.now()
        self.state = ExecutionState.COMPLETED
        return True

    def _report_only(self) -> bool:
        """只生成报告模式"""
        self.logger.info("只生成报告模式")
        self._generate_report()
        self.result.success = True
        self.result.end_time = datetime.now()
        self.state = ExecutionState.COMPLETED
        return True

    def _execute(self) -> bool:
        """执行部署"""
        self.logger.info("=" * 60)
        self.logger.info("开始执行部署")
        self.logger.info("=" * 60)

        # 根据执行模式选择执行策略
        if self.config.execution_mode == ExecutionMode.FULL:
            return self._execute_full()
        elif self.config.execution_mode == ExecutionMode.PHASES:
            return self._execute_phases()
        elif self.config.execution_mode == ExecutionMode.STEPS:
            return self._execute_steps()
        elif self.config.execution_mode == ExecutionMode.MODULES:
            return self._execute_modules()
        elif self.config.execution_mode == ExecutionMode.CATEGORIES:
            return self._execute_categories()
        elif self.config.execution_mode == ExecutionMode.PLAN:
            return self._execute_plan()
        else:
            self.logger.error(f"未知的执行模式: {self.config.execution_mode}")
            return False

    def _execute_full(self) -> bool:
        """执行完整部署"""
        self.logger.info("执行完整部署...")
        plan = self.module_manager.create_full_plan()
        return self._execute_plan_internal(plan)

    def _execute_phases(self) -> bool:
        """执行指定阶段"""
        self.logger.info(f"执行阶段: {self.config.phases}")
        plan = self.module_manager.create_plan_from_phases(self.config.phases)
        return self._execute_plan_internal(plan)

    def _execute_steps(self) -> bool:
        """执行指定步骤"""
        self.logger.info(f"执行步骤: {self.config.steps}")
        plan = self.module_manager.create_plan_from_steps(self.config.steps)
        return self._execute_plan_internal(plan)

    def _execute_modules(self) -> bool:
        """执行指定模块"""
        self.logger.info(f"执行模块: {self.config.modules}")
        plan = self.module_manager.create_plan_from_modules(self.config.modules)
        return self._execute_plan_internal(plan)

    def _execute_categories(self) -> bool:
        """按分类执行"""
        self.logger.info(f"执行分类: {self.config.categories}")
        plan = self.module_manager.create_plan_from_categories(self.config.categories)
        return self._execute_plan_internal(plan)

    def _execute_plan(self) -> bool:
        """从计划文件执行"""
        self.logger.info(f"从计划文件执行: {self.config.plan_file}")
        plan = self.module_manager.load_plan(self.config.plan_file)
        return self._execute_plan_internal(plan)

    def _execute_plan_internal(self, plan) -> bool:
        """执行计划内部实现"""
        from ..deployment.execution_plan import PlanExecutor

        self.result.total_modules = len(plan.modules)
        success = True

        executor = PlanExecutor(
            plan=plan,
            config=self._cluster_config,
            ssh_manager=self._ssh_manager,
            batch_executor=self._batch_executor,
            logger=self.logger
        )

        # 设置进度回调
        def on_module_progress(module_id, progress):
            if self._on_progress:
                self._on_progress(module_id, progress)

        def on_module_start(module_id, module_info):
            self.logger.info(f"开始执行模块: {module_id}")
            if self._on_module_start:
                self._on_module_start(module_id, module_info)

        def on_module_complete(module_id, result):
            self.result.completed_modules += 1
            if result.success:
                self.logger.info(f"模块完成: {module_id}")
            else:
                self.result.failed_modules += 1
                self.logger.error(f"模块失败: {module_id} - {result.error}")
                self.result.errors.append(f"{module_id}: {result.error}")
                if not self.config.continue_on_error:
                    nonlocal success
                    success = False

            if self._on_module_complete:
                self._on_module_complete(module_id, result)

        executor.set_callbacks(
            on_progress=on_module_progress,
            on_module_start=on_module_start,
            on_module_complete=on_module_complete
        )

        executor.run()

        return success

    def _print_config_summary(self):
        """打印配置摘要"""
        self.logger.info("\n配置摘要:")
        self.logger.info(f"  集群名称: {self._cluster_config.name}")
        self.logger.info(f"  节点数量: {self._cluster_config.node_count}")

        if self._cluster_config.jumphost:
            self.logger.info(
                f"  跳转服务器: {self._cluster_config.jumphost.host}:{self._cluster_config.jumphost.port}"
            )

        self.logger.info("\n节点列表:")
        for node in self._cluster_config.nodes:
            roles = ", ".join(node.roles) if node.roles else "无"
            self.logger.info(f"  - {node.hostname} ({node.ip}) [{roles}]")

        self.logger.info("\n软件版本:")
        self.logger.info(f"  CUDA: {self._versions_config.cuda.version}")
        self.logger.info(f"  NVIDIA驱动: {self._versions_config.nvidia_driver.version}")

    def _generate_report(self):
        """生成报告"""
        from .progress_reporter import ProgressReporter

        reporter = ProgressReporter(
            format=self.config.output_format,
            output_file=self.config.output_file
        )

        reporter.generate(
            result=self.result,
            config=self._cluster_config,
            versions=self._versions_config
        )

    def _cleanup(self):
        """清理资源"""
        if self._ssh_manager:
            self._ssh_manager.close_all()

    def _fail(self, message: str) -> bool:
        """标记失败"""
        self.result.errors.append(message)
        self.result.success = False
        self.result.end_time = datetime.now()
        self.state = ExecutionState.FAILED
        self.logger.error(f"执行失败: {message}")
        return False

    def _cancel(self) -> bool:
        """标记取消"""
        self.result.success = False
        self.result.end_time = datetime.now()
        self.state = ExecutionState.CANCELLED
        return False

    def get_status(self) -> Dict[str, Any]:
        """获取执行状态"""
        return {
            "state": self.state.value,
            "result": self.result.to_dict() if self.result else None,
        }
