#!/usr/bin/env python3
"""
GPU Cluster Deploy - 主入口
自动化GPU集群环境部署工具

支持两种CLI模式:
1. 传统模式: python main.py [options] - 兼容原有参数
2. 新模式: python main.py --new-cli [options] - 支持模块选择、分类执行等新功能
"""

import argparse
import sys
from pathlib import Path
from typing import Optional, List

from src.config_loader import ConfigLoader, load_configs
from src.ssh_manager import SSHManager, create_ssh_manager_from_config
from src.batch_executor import BatchExecutor
from src.utils.logger import get_logger, DeployLogger
from src.steps.base import StepResult


def parse_args():
    """解析命令行参数（传统模式，保持向后兼容）"""
    parser = argparse.ArgumentParser(
        description="GPU集群环境部署工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 使用默认配置执行完整部署
  python main.py

  # 使用指定配置目录
  python main.py --config-dir /path/to/config

  # 只执行特定阶段
  python main.py --phase 1

  # 只执行特定步骤
  python main.py --step 1.1 --step 1.2

  # 预检查模式（不执行实际部署）
  python main.py --dry-run

  # 生成部署报告
  python main.py --report-only

  # 使用新CLI模式（支持模块选择、分类执行等）
  python main.py --new-cli --category storage --category gpu

  # 从执行计划文件执行
  python main.py --new-cli --plan config/plans/gpu-only.yaml
        """
    )

    # 新CLI模式开关
    parser.add_argument(
        "--new-cli",
        action="store_true",
        help="使用新CLI模式（支持模块选择、分类执行、计划文件等）"
    )

    parser.add_argument(
        "--config-dir", "-c",
        default="config",
        help="配置文件目录 (默认: config)"
    )

    parser.add_argument(
        "--phase", "-p",
        type=int,
        action="append",
        help="只执行指定阶段（可多次指定）"
    )

    parser.add_argument(
        "--step", "-s",
        action="append",
        help="只执行指定步骤（可多次指定）"
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="预检查模式，不执行实际部署"
    )

    parser.add_argument(
        "--report-only",
        action="store_true",
        help="只生成部署报告"
    )

    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="日志级别 (默认: INFO)"
    )

    parser.add_argument(
        "--log-dir",
        default="logs",
        help="日志目录 (默认: logs)"
    )

    # 新CLI参数（仅在--new-cli模式下有效）
    parser.add_argument(
        "--module", "-m",
        action="append",
        dest="modules",
        help="执行指定模块（可多次指定，需配合--new-cli）"
    )

    parser.add_argument(
        "--category",
        action="append",
        dest="categories",
        choices=["network", "storage", "gpu", "system", "security"],
        help="执行指定分类的所有模块（可多次指定，需配合--new-cli）"
    )

    parser.add_argument(
        "--plan",
        dest="plan_file",
        help="从执行计划文件执行（需配合--new-cli）"
    )

    parser.add_argument(
        "--parallel",
        action="store_true",
        help="启用并行执行（需配合--new-cli）"
    )

    parser.add_argument(
        "--output",
        choices=["text", "json", "markdown"],
        default="text",
        dest="output_format",
        help="输出格式 (默认: text)"
    )

    parser.add_argument(
        "--output-file", "-o",
        help="输出文件路径"
    )

    parser.add_argument(
        "--yes", "-y",
        action="store_true",
        dest="skip_confirmation",
        help="跳过确认提示"
    )

    return parser.parse_args()


class GPUClusterDeploy:
    """GPU集群部署主类"""

    def __init__(self, config_dir: str = "config", log_level: str = "INFO", log_dir: str = "logs"):
        self.config_dir = config_dir
        self.log_level = log_level
        self.log_dir = log_dir

        # 初始化日志
        self.logger = DeployLogger(log_dir=log_dir, log_level=log_level)

        # 加载配置
        self.config = None
        self.versions = None
        self.loader = None

        # SSH和批量执行器
        self.ssh_manager = None
        self.batch_executor = None

        # 步骤注册表
        self.steps = {}

    def load_config(self) -> bool:
        """加载配置"""
        self.logger.info("正在加载配置...")

        try:
            self.loader = ConfigLoader(self.config_dir)
            self.config = self.loader.load_cluster_config()
            self.versions = self.loader.load_versions_config()

            errors = self.loader.validate()
            if errors:
                for error in errors:
                    self.logger.error(f"配置错误: {error}")
                return False

            self.logger.info(f"配置加载成功: {self.config.name}")
            self.logger.info(f"节点数量: {self.config.node_count}")

            return True

        except Exception as e:
            self.logger.error(f"配置加载失败: {e}")
            return False

    def init_ssh(self) -> bool:
        """初始化SSH连接"""
        self.logger.info("正在初始化SSH连接...")

        try:
            if self.config.jumphost:
                self.ssh_manager = create_ssh_manager_from_config(self.config.jumphost)
                if not self.ssh_manager.connect_jumphost():
                    self.logger.error("跳转服务器连接失败")
                    return False
            else:
                self.ssh_manager = SSHManager()

            # 初始化批量执行器
            # 初始使用SSH模式，SSH免密配置完成后切换到pdsh模式
            self.batch_executor = BatchExecutor(
                ssh_manager=self.ssh_manager,
                use_pdsh=False,  # 初始使用SSH模式
                ssh_user="ubuntu",
                config=self.config  # 传递配置以获取节点认证信息
            )

            self.logger.info("SSH初始化成功")
            return True

        except Exception as e:
            self.logger.error(f"SSH初始化失败: {e}")
            return False

    def check_connectivity(self) -> bool:
        """检查节点连通性"""
        self.logger.info("正在检查节点连通性...")

        hosts = self.config.get_all_ips()
        results = self.batch_executor.check_hosts_connectivity(hosts)

        reachable = sum(1 for v in results.values() if v)
        total = len(results)

        self.logger.info(f"连通性检查完成: {reachable}/{total} 节点可达")

        if reachable < total:
            unreachable = [k for k, v in results.items() if not v]
            self.logger.warning(f"不可达节点: {unreachable}")
            return False

        return True

    def register_step(self, step_class):
        """注册步骤"""
        step = step_class(
            config=self.config,
            ssh_manager=self.ssh_manager,
            batch_executor=self.batch_executor,
            logger=self.logger,
            versions=self.versions
        )
        self.steps[step.step_id] = step

    def run_phase(self, phase_id: int, hosts: List[str]) -> bool:
        """运行指定阶段"""
        # 根据phase_id获取步骤 - 使用实际的步骤ID
        phase_steps = {
            0: ["00"],  # 设备检查
            1: ["0d", "09", "01"],  # 初始化配置（SSH免密、hosts、依赖）- SSH免密完成后可用密钥认证
            2: ["02", "02b", "03", "04"],  # 系统检查（内核、glibc、OpenSSH）
            3: ["05", "06", "07", "08", "15", "16", "17", "18", "19"],  # 系统基础配置
            4: ["10", "12", "13"],  # 用户和权限配置
            5: ["20", "21", "22", "23", "24", "25", "26", "27", "28"],  # GPU和网络驱动
            6: ["29", "30", "34"],  # 高级配置
            7: ["99"],  # 最终验证
        }

        steps = phase_steps.get(phase_id, [])

        if not steps:
            self.logger.warning(f"未找到阶段 {phase_id} 的步骤")
            return False

        self.logger.start_phase(phase_id, f"Phase {phase_id}")

        success = True
        for step_id in steps:
            if step_id not in self.steps:
                self.logger.warning(f"步骤 {step_id} 未注册")
                continue

            step = self.steps[step_id]
            result = step.run(hosts)

            # SSH免密和hosts都配置完成后，切换到pdsh模式
            # 注意：当通过跳转服务器访问内网节点时，pdsh 需要在跳转服务器上执行
            # 当前架构下继续使用 SSH 模式，通过 SSH 代理链执行命令
            if step_id == "09" and result.success:
                self.logger.info("SSH免密和hosts配置完成，继续使用SSH模式（通过跳转服务器访问内网节点）...")

            if not result.success:
                success = False
                # 可选步骤失败不中断流程
                if step.is_optional:
                    self.logger.warning(
                        f"[{step_id}] 可选步骤失败，继续执行后续步骤: {result.message}"
                    )
                    continue
                # 不可跳过的步骤失败则中断
                if not step.can_skip:
                    break

        self.logger.end_phase(phase_id, success)
        return success

    def run(self, phases: Optional[List[int]] = None,
            steps: Optional[List[str]] = None,
            dry_run: bool = False) -> bool:
        """执行部署"""
        self.logger.info("=" * 60)
        self.logger.info("开始GPU集群环境部署")
        self.logger.info("=" * 60)

        # 加载配置
        if not self.load_config():
            return False

        if dry_run:
            self.logger.info("[DRY-RUN] 预检查模式，不执行实际部署")
            self._print_config_summary()
            return True

        # 初始化SSH
        if not self.init_ssh():
            return False

        # 检查连通性
        if not self.check_connectivity():
            self.logger.warning("部分节点不可达，是否继续? [y/N]")
            response = input().strip().lower()
            if response != 'y':
                return False

        # 获取目标主机
        hosts = self.config.get_all_ips()

        # 注册所有步骤
        from src.steps import ALL_STEPS
        for step_class in ALL_STEPS:
            self.register_step(step_class)

        # 执行部署步骤（不含最终验证）
        deploy_steps = [sid for sid in self.steps.keys() if sid != "99"]

        # 执行部署
        success = True
        if steps:
            # 执行指定步骤
            for step_id in steps:
                if step_id in self.steps:
                    result = self.steps[step_id].run(hosts)
                    if not result.success:
                        success = False
                        break
        elif phases:
            # 执行指定阶段
            for phase_id in phases:
                if not self.run_phase(phase_id, hosts):
                    success = False
                    break
        else:
            # 执行完整部署（不含最终验证，验证在部署完成后单独执行）
            for phase_id in range(0, 7):  # 7个阶段 (0-6)
                if not self.run_phase(phase_id, hosts):
                    success = False
                    break

        # 执行最终验证（仅在完整部署时执行）
        if success and "99" in self.steps and not steps and not phases:
            self.logger.info("\n" + "=" * 60)
            self.logger.info("执行最终验证...")
            self.logger.info("=" * 60)

            # 创建验证步骤实例，传入步骤注册表
            from src.steps.step_final_verification import FinalVerification
            verification_step = FinalVerification(
                config=self.config,
                ssh_manager=self.ssh_manager,
                batch_executor=self.batch_executor,
                logger=self.logger,
                versions=self.versions,
                step_registry=self.steps  # 传入所有已注册的步骤
            )
            verification_result = verification_step.run(hosts)

            if not verification_result.success:
                self.logger.warning("最终验证发现问题，请检查报告")

        # 生成报告
        self.logger.save_progress_report()
        self.logger.generate_html_report()

        # 关闭连接
        self.ssh_manager.close_all()

        self.logger.info("=" * 60)
        self.logger.info(f"部署{'成功' if success else '失败'}")
        self.logger.info("=" * 60)

        return success

    def _print_config_summary(self):
        """打印配置摘要"""
        self.logger.info("\n配置摘要:")
        self.logger.info(f"  集群名称: {self.config.name}")
        self.logger.info(f"  节点数量: {self.config.node_count}")

        if self.config.jumphost:
            self.logger.info(f"  跳转服务器: {self.config.jumphost.host}:{self.config.jumphost.port}")

        self.logger.info("\n节点列表:")
        for node in self.config.nodes:
            roles = ", ".join(node.roles) if node.roles else "无"
            self.logger.info(f"  - {node.hostname} ({node.ip}) [{roles}]")

        self.logger.info("\n软件版本:")
        mlnx_status = f"{self.versions.mlnx_ofed.version} ({'启用' if self.versions.mlnx_ofed.enabled else '禁用-不安装'})"
        self.logger.info(f"  CUDA: {self.versions.cuda.version}")
        self.logger.info(f"  NVIDIA驱动: {self.versions.nvidia_driver.version}")
        self.logger.info(f"  MLNX_OFED: {mlnx_status}")
        self.logger.info(f"  内核模式: {self.versions.kernel.mode}")


def main():
    """主函数"""
    args = parse_args()

    # 新CLI模式
    if args.new_cli:
        return run_new_cli(args)

    # 传统模式（向后兼容）
    deploy = GPUClusterDeploy(
        config_dir=args.config_dir,
        log_level=args.log_level,
        log_dir=args.log_dir
    )

    if args.report_only:
        # 只生成报告
        deploy.load_config()
        deploy.logger.save_progress_report()
        deploy.logger.generate_html_report()
        return 0

    success = deploy.run(
        phases=args.phase,
        steps=args.step,
        dry_run=args.dry_run
    )

    return 0 if success else 1


def run_new_cli(args):
    """运行新CLI模式"""
    from src.cli.main import CLIConfig, ExecutionMode, main as cli_main

    # 确定执行模式
    execution_mode = ExecutionMode.FULL
    if args.phase:
        execution_mode = ExecutionMode.PHASES
    elif args.step:
        execution_mode = ExecutionMode.STEPS
    elif args.modules:
        execution_mode = ExecutionMode.MODULES
    elif args.categories:
        execution_mode = ExecutionMode.CATEGORIES
    elif args.plan_file:
        execution_mode = ExecutionMode.PLAN

    config = CLIConfig(
        config_dir=args.config_dir,
        log_level=args.log_level,
        log_dir=args.log_dir,
        dry_run=args.dry_run,
        report_only=args.report_only,
        execution_mode=execution_mode,
        phases=args.phase or [],
        steps=args.step or [],
        modules=args.modules or [],
        categories=args.categories or [],
        plan_file=args.plan_file,
        parallel=args.parallel,
        max_parallel=3,
        continue_on_error=False,
        skip_confirmation=args.skip_confirmation,
        output_format=args.output_format,
        output_file=args.output_file,
    )

    return cli_main_with_config(config)


def cli_main_with_config(config):
    """使用配置运行CLI"""
    from src.cli.execution_controller import ExecutionController

    controller = ExecutionController(config)
    success = controller.run()

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
