#!/usr/bin/env python3
"""
GPU Cluster Deploy - 进度报告器
生成执行进度报告，支持JSON和Markdown格式输出
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any


@dataclass
class ModuleReport:
    """模块报告数据类"""
    module_id: str
    module_name: str
    status: str  # success, failed, skipped
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    duration_seconds: float = 0.0
    error: Optional[str] = None
    output: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "module_id": self.module_id,
            "module_name": self.module_name,
            "status": self.status,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration_seconds": self.duration_seconds,
            "error": self.error,
            "output": self.output,
        }


@dataclass
class DeploymentReport:
    """部署报告数据类"""
    cluster_name: str
    start_time: datetime
    end_time: Optional[datetime] = None
    duration_seconds: float = 0.0
    total_modules: int = 0
    completed_modules: int = 0
    failed_modules: int = 0
    skipped_modules: int = 0
    success: bool = False
    modules: List[ModuleReport] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    node_count: int = 0
    cuda_version: str = ""
    driver_version: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cluster_name": self.cluster_name,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration_seconds": self.duration_seconds,
            "total_modules": self.total_modules,
            "completed_modules": self.completed_modules,
            "failed_modules": self.failed_modules,
            "skipped_modules": self.skipped_modules,
            "success": self.success,
            "modules": [m.to_dict() for m in self.modules],
            "errors": self.errors,
            "warnings": self.warnings,
            "node_count": self.node_count,
            "cuda_version": self.cuda_version,
            "driver_version": self.driver_version,
        }


class ProgressReporter:
    """进度报告器

    生成执行进度报告，支持JSON和Markdown格式输出
    """

    def __init__(self, format: str = "text", output_file: Optional[str] = None):
        self.format = format
        self.output_file = output_file
        self.report: Optional[DeploymentReport] = None

    def generate(self, result, config=None, versions=None) -> DeploymentReport:
        """生成报告"""
        # 构建报告数据
        self.report = DeploymentReport(
            cluster_name=config.name if config else "Unknown",
            start_time=result.start_time,
            end_time=result.end_time,
            duration_seconds=result.duration_seconds,
            total_modules=result.total_modules,
            completed_modules=result.completed_modules,
            failed_modules=result.failed_modules,
            skipped_modules=result.skipped_modules,
            success=result.success,
            errors=result.errors,
            warnings=result.warnings,
            node_count=config.node_count if config else 0,
            cuda_version=versions.cuda.version if versions else "",
            driver_version=versions.nvidia_driver.version if versions else "",
        )

        # 添加模块报告
        for module_id, module_result in result.module_results.items():
            module_report = ModuleReport(
                module_id=module_id,
                module_name=module_result.get("name", module_id),
                status=module_result.get("status", "unknown"),
                start_time=module_result.get("start_time"),
                end_time=module_result.get("end_time"),
                duration_seconds=module_result.get("duration_seconds", 0.0),
                error=module_result.get("error"),
                output=module_result.get("output"),
            )
            self.report.modules.append(module_report)

        # 输出报告
        output = self._format_output()

        if self.output_file:
            self._write_file(output)
        else:
            print(output)

        return self.report

    def _format_output(self) -> str:
        """格式化输出"""
        if self.format == "json":
            return self._format_json()
        elif self.format == "markdown":
            return self._format_markdown()
        else:
            return self._format_text()

    def _format_json(self) -> str:
        """格式化为JSON"""
        return json.dumps(self.report.to_dict(), indent=2, ensure_ascii=False)

    def _format_markdown(self) -> str:
        """格式化为Markdown"""
        lines = [
            "# GPU集群部署报告",
            "",
            f"**集群名称**: {self.report.cluster_name}",
            f"**执行时间**: {self.report.start_time.strftime('%Y-%m-%d %H:%M:%S')}",
            f"**耗时**: {self.report.duration_seconds:.2f}秒",
            f"**状态**: {'✅ 成功' if self.report.success else '❌ 失败'}",
            "",
            "## 概要",
            "",
            "| 指标 | 值 |",
            "|------|-----|",
            f"| 节点数量 | {self.report.node_count} |",
            f"| 总模块数 | {self.report.total_modules} |",
            f"| 完成模块 | {self.report.completed_modules} |",
            f"| 失败模块 | {self.report.failed_modules} |",
            f"| 跳过模块 | {self.report.skipped_modules} |",
            f"| CUDA版本 | {self.report.cuda_version} |",
            f"| 驱动版本 | {self.report.driver_version} |",
            "",
        ]

        # 模块执行详情
        if self.report.modules:
            lines.extend([
                "## 模块执行详情",
                "",
                "| 模块ID | 模块名称 | 状态 | 耗时 |",
                "|--------|----------|------|------|",
            ])

            for module in self.report.modules:
                status_icon = "✅" if module.status == "success" else "❌" if module.status == "failed" else "⏭️"
                lines.append(
                    f"| {module.module_id} | {module.module_name} | {status_icon} {module.status} | {module.duration_seconds:.2f}s |"
                )

            lines.append("")

        # 错误信息
        if self.report.errors:
            lines.extend([
                "## 错误信息",
                "",
            ])
            for error in self.report.errors:
                lines.append(f"- {error}")
            lines.append("")

        # 警告信息
        if self.report.warnings:
            lines.extend([
                "## 警告信息",
                "",
            ])
            for warning in self.report.warnings:
                lines.append(f"- {warning}")
            lines.append("")

        return "\n".join(lines)

    def _format_text(self) -> str:
        """格式化为纯文本"""
        lines = [
            "=" * 60,
            "GPU集群部署报告",
            "=" * 60,
            "",
            f"集群名称: {self.report.cluster_name}",
            f"执行时间: {self.report.start_time.strftime('%Y-%m-%d %H:%M:%S')}",
            f"耗时: {self.report.duration_seconds:.2f}秒",
            f"状态: {'成功' if self.report.success else '失败'}",
            "",
            "概要:",
            f"  - 节点数量: {self.report.node_count}",
            f"  - 总模块数: {self.report.total_modules}",
            f"  - 完成模块: {self.report.completed_modules}",
            f"  - 失败模块: {self.report.failed_modules}",
            f"  - 跳过模块: {self.report.skipped_modules}",
            f"  - CUDA版本: {self.report.cuda_version}",
            f"  - 驱动版本: {self.report.driver_version}",
            "",
        ]

        # 模块执行详情
        if self.report.modules:
            lines.append("模块执行详情:")
            for module in self.report.modules:
                status = "✓" if module.status == "success" else "✗" if module.status == "failed" else "-"
                lines.append(
                    f"  [{status}] {module.module_id}: {module.module_name} ({module.duration_seconds:.2f}s)"
                )
            lines.append("")

        # 错误信息
        if self.report.errors:
            lines.append("错误信息:")
            for error in self.report.errors:
                lines.append(f"  - {error}")
            lines.append("")

        # 警告信息
        if self.report.warnings:
            lines.append("警告信息:")
            for warning in self.report.warnings:
                lines.append(f"  - {warning}")
            lines.append("")

        lines.append("=" * 60)

        return "\n".join(lines)

    def _write_file(self, content: str):
        """写入文件"""
        output_path = Path(self.output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(content, encoding="utf-8")

    def get_report(self) -> Optional[DeploymentReport]:
        """获取报告"""
        return self.report


class RealTimeProgressTracker:
    """实时进度跟踪器

    用于在执行过程中实时跟踪和显示进度
    """

    def __init__(self, total_modules: int = 0):
        self.total_modules = total_modules
        self.completed_modules = 0
        self.failed_modules = 0
        self.current_module: Optional[str] = None
        self.start_time = datetime.now()
        self._module_times: Dict[str, datetime] = {}

    def start_module(self, module_id: str):
        """开始模块执行"""
        self.current_module = module_id
        self._module_times[module_id] = datetime.now()

    def complete_module(self, module_id: str, success: bool = True):
        """完成模块执行"""
        if success:
            self.completed_modules += 1
        else:
            self.failed_modules += 1

        self.current_module = None

    def get_progress(self) -> Dict[str, Any]:
        """获取当前进度"""
        total = self.completed_modules + self.failed_modules
        progress_percent = (total / self.total_modules * 100) if self.total_modules > 0 else 0
        elapsed = (datetime.now() - self.start_time).total_seconds()

        return {
            "total_modules": self.total_modules,
            "completed_modules": self.completed_modules,
            "failed_modules": self.failed_modules,
            "progress_percent": progress_percent,
            "current_module": self.current_module,
            "elapsed_seconds": elapsed,
        }

    def format_progress(self) -> str:
        """格式化进度显示"""
        progress = self.get_progress()
        bar_length = 40
        filled = int(bar_length * progress["progress_percent"] / 100)
        bar = "=" * filled + "-" * (bar_length - filled)

        return (
            f"[{bar}] {progress['progress_percent']:.1f}% "
            f"({progress['completed_modules']}/{progress['total_modules']})"
        )
