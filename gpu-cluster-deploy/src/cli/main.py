#!/usr/bin/env python3
"""
GPU Cluster Deploy - CLI主模块
支持模块选择、分类执行、执行计划导入等新功能
"""

import argparse
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional, List, Dict, Any


class ExecutionMode(Enum):
    """执行模式枚举"""
    FULL = "full"  # 完整部署
    PHASES = "phases"  # 指定阶段
    STEPS = "steps"  # 指定步骤
    MODULES = "modules"  # 指定模块
    CATEGORIES = "categories"  # 分类执行
    PLAN = "plan"  # 执行计划文件


@dataclass
class CLIConfig:
    """CLI配置数据类"""
    config_dir: str = "config"
    log_level: str = "INFO"
    log_dir: str = "logs"
    dry_run: bool = False
    report_only: bool = False

    # 执行模式
    execution_mode: ExecutionMode = ExecutionMode.FULL

    # 执行目标
    phases: List[int] = field(default_factory=list)
    steps: List[str] = field(default_factory=list)
    modules: List[str] = field(default_factory=list)
    categories: List[str] = field(default_factory=list)
    plan_file: Optional[str] = None

    # 执行选项
    parallel: bool = False
    max_parallel: int = 3
    continue_on_error: bool = False
    skip_confirmation: bool = False

    # 输出选项
    output_format: str = "text"  # text, json, markdown
    output_file: Optional[str] = None
    verbose: bool = False


def create_parser() -> argparse.ArgumentParser:
    """创建命令行参数解析器"""
    parser = argparse.ArgumentParser(
        prog="gpu-cluster-deploy",
        description="GPU集群环境自动化部署工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
执行模式:
  完整部署    默认模式，执行所有部署步骤
  阶段执行    --phase 1 --phase 2   执行指定阶段
  步骤执行    --step 1.1 --step 1.2 执行指定步骤
  模块执行    --module disk --module network 执行指定模块
  分类执行    --category storage --category gpu 按分类执行
  计划执行    --plan config/plans/gpu-only.yaml 从计划文件执行

示例:
  # 使用默认配置执行完整部署
  gpu-cluster-deploy

  # 使用指定配置目录
  gpu-cluster-deploy --config-dir /path/to/config

  # 只执行存储相关模块
  gpu-cluster-deploy --category storage

  # 执行GPU相关模块（并行执行）
  gpu-cluster-deploy --category gpu --parallel --max-parallel 4

  # 从执行计划文件执行
  gpu-cluster-deploy --plan config/plans/gpu-only.yaml

  # 执行指定模块
  gpu-cluster-deploy --module disk_mount --module rdma_config

  # 预检查模式（不执行实际部署）
  gpu-cluster-deploy --dry-run

  # 生成JSON格式的部署报告
  gpu-cluster-deploy --report-only --output json --output-file report.json
        """
    )

    # 基本选项
    basic_group = parser.add_argument_group("基本选项")
    basic_group.add_argument(
        "--config-dir", "-c",
        default="config",
        help="配置文件目录 (默认: config)"
    )
    basic_group.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="日志级别 (默认: INFO)"
    )
    basic_group.add_argument(
        "--log-dir",
        default="logs",
        help="日志目录 (默认: logs)"
    )
    basic_group.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="详细输出模式"
    )

    # 执行目标选项（互斥组）
    target_group = parser.add_argument_group("执行目标（选择其一）")
    target_exclusive = target_group.add_mutually_exclusive_group()

    target_exclusive.add_argument(
        "--phase", "-p",
        type=int,
        action="append",
        dest="phases",
        help="执行指定阶段（可多次指定）"
    )
    target_exclusive.add_argument(
        "--step", "-s",
        action="append",
        dest="steps",
        help="执行指定步骤（可多次指定）"
    )
    target_exclusive.add_argument(
        "--module", "-m",
        action="append",
        dest="modules",
        help="执行指定模块（可多次指定）"
    )
    target_exclusive.add_argument(
        "--category",
        action="append",
        dest="categories",
        choices=["network", "storage", "gpu", "system", "security"],
        help="执行指定分类的所有模块（可多次指定）"
    )
    target_exclusive.add_argument(
        "--plan",
        dest="plan_file",
        help="从执行计划文件执行"
    )

    # 执行选项
    exec_group = parser.add_argument_group("执行选项")
    exec_group.add_argument(
        "--dry-run",
        action="store_true",
        help="预检查模式，不执行实际部署"
    )
    exec_group.add_argument(
        "--report-only",
        action="store_true",
        help="只生成部署报告"
    )
    exec_group.add_argument(
        "--parallel",
        action="store_true",
        help="启用并行执行"
    )
    exec_group.add_argument(
        "--max-parallel",
        type=int,
        default=3,
        help="最大并行数 (默认: 3)"
    )
    exec_group.add_argument(
        "--continue-on-error",
        action="store_true",
        help="遇到错误时继续执行"
    )
    exec_group.add_argument(
        "--yes", "-y",
        action="store_true",
        dest="skip_confirmation",
        help="跳过确认提示"
    )

    # 输出选项
    output_group = parser.add_argument_group("输出选项")
    output_group.add_argument(
        "--output",
        choices=["text", "json", "markdown"],
        default="text",
        dest="output_format",
        help="输出格式 (默认: text)"
    )
    output_group.add_argument(
        "--output-file", "-o",
        help="输出文件路径"
    )

    # 子命令
    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # list 子命令
    list_parser = subparsers.add_parser("list", help="列出可用模块或分类")
    list_parser.add_argument(
        "type",
        choices=["modules", "categories", "steps", "plans"],
        help="要列出的类型"
    )

    # validate 子命令
    validate_parser = subparsers.add_parser("validate", help="验证配置文件")
    validate_parser.add_argument(
        "--strict",
        action="store_true",
        help="严格验证模式"
    )

    # export 子命令
    export_parser = subparsers.add_parser("export", help="导出执行计划")
    export_parser.add_argument(
        "--format",
        choices=["yaml", "json"],
        default="yaml",
        help="导出格式 (默认: yaml)"
    )
    export_parser.add_argument(
        "--output", "-o",
        required=True,
        help="输出文件路径"
    )

    return parser


def parse_args(args: Optional[List[str]] = None) -> CLIConfig:
    """解析命令行参数并返回CLI配置"""
    parser = create_parser()
    parsed = parser.parse_args(args)

    # 确定执行模式
    execution_mode = ExecutionMode.FULL
    if parsed.phases:
        execution_mode = ExecutionMode.PHASES
    elif parsed.steps:
        execution_mode = ExecutionMode.STEPS
    elif parsed.modules:
        execution_mode = ExecutionMode.MODULES
    elif parsed.categories:
        execution_mode = ExecutionMode.CATEGORIES
    elif parsed.plan_file:
        execution_mode = ExecutionMode.PLAN

    return CLIConfig(
        config_dir=parsed.config_dir,
        log_level=parsed.log_level,
        log_dir=parsed.log_dir,
        dry_run=parsed.dry_run,
        report_only=parsed.report_only,
        execution_mode=execution_mode,
        phases=parsed.phases or [],
        steps=parsed.steps or [],
        modules=parsed.modules or [],
        categories=parsed.categories or [],
        plan_file=parsed.plan_file,
        parallel=parsed.parallel,
        max_parallel=parsed.max_parallel,
        continue_on_error=parsed.continue_on_error,
        skip_confirmation=parsed.skip_confirmation,
        output_format=parsed.output_format,
        output_file=parsed.output_file,
        verbose=parsed.verbose,
    )


def main(args: Optional[List[str]] = None) -> int:
    """CLI主入口"""
    config = parse_args(args)

    # 处理子命令
    parser = create_parser()
    parsed = parser.parse_args(args)

    if parsed.command == "list":
        return handle_list_command(parsed, config)
    elif parsed.command == "validate":
        return handle_validate_command(parsed, config)
    elif parsed.command == "export":
        return handle_export_command(parsed, config)

    # 默认：执行部署
    from .execution_controller import ExecutionController

    controller = ExecutionController(config)
    success = controller.run()

    return 0 if success else 1


def handle_list_command(parsed, config: CLIConfig) -> int:
    """处理list子命令"""
    from ..deployment.module_manager import ModuleManager

    manager = ModuleManager()

    if parsed.type == "modules":
        modules = manager.list_modules()
        print("可用模块:")
        for module in modules:
            print(f"  - {module['id']}: {module['name']} [{module['category']}]")
    elif parsed.type == "categories":
        categories = manager.list_categories()
        print("可用分类:")
        for cat in categories:
            print(f"  - {cat['id']}: {cat['name']} ({cat['module_count']} 模块)")
    elif parsed.type == "steps":
        steps = manager.list_steps()
        print("可用步骤:")
        for step in steps:
            print(f"  - {step['id']}: {step['name']}")
    elif parsed.type == "plans":
        plan_dir = Path(config.config_dir) / "plans"
        if plan_dir.exists():
            print("可用执行计划:")
            for plan_file in plan_dir.glob("*.yaml"):
                print(f"  - {plan_file.name}")
            for plan_file in plan_dir.glob("*.json"):
                print(f"  - {plan_file.name}")
        else:
            print("未找到执行计划目录")

    return 0


def handle_validate_command(parsed, config: CLIConfig) -> int:
    """处理validate子命令"""
    from ..config_loader import ConfigLoader

    loader = ConfigLoader(config.config_dir)
    errors = loader.validate()

    if errors:
        print("配置验证失败:")
        for error in errors:
            print(f"  - {error}")
        return 1
    else:
        print("配置验证通过")
        return 0


def handle_export_command(parsed, config: CLIConfig) -> int:
    """处理export子命令"""
    from ..deployment.module_manager import ModuleManager
    from ..deployment.execution_plan import ExecutionPlanExporter

    manager = ModuleManager()
    exporter = ExecutionPlanExporter(manager)

    plan = manager.create_full_plan()
    exporter.export(plan, parsed.output, format=parsed.format)

    print(f"执行计划已导出到: {parsed.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
