#!/usr/bin/env python3
"""
CLI模块单元测试
"""

import pytest
from datetime import datetime
from unittest.mock import Mock, patch, MagicMock

import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.cli.main import (
    CLIConfig,
    ExecutionMode,
    create_parser,
    parse_args,
)
from src.cli.execution_controller import (
    ExecutionController,
    ExecutionState,
    ExecutionResult,
)
from src.cli.progress_reporter import (
    ProgressReporter,
    DeploymentReport,
    ModuleReport,
    RealTimeProgressTracker,
)


class TestCLIConfig:
    """CLIConfig数据类测试"""

    def test_default_config(self):
        """测试默认配置"""
        config = CLIConfig()

        assert config.config_dir == "config"
        assert config.log_level == "INFO"
        assert config.log_dir == "logs"
        assert config.dry_run is False
        assert config.report_only is False
        assert config.execution_mode == ExecutionMode.FULL
        assert config.phases == []
        assert config.steps == []
        assert config.modules == []
        assert config.categories == []

    def test_custom_config(self):
        """测试自定义配置"""
        config = CLIConfig(
            config_dir="/custom/config",
            log_level="DEBUG",
            dry_run=True,
            execution_mode=ExecutionMode.CATEGORIES,
            categories=["storage", "gpu"],
        )

        assert config.config_dir == "/custom/config"
        assert config.log_level == "DEBUG"
        assert config.dry_run is True
        assert config.execution_mode == ExecutionMode.CATEGORIES
        assert config.categories == ["storage", "gpu"]


class TestExecutionMode:
    """ExecutionMode枚举测试"""

    def test_execution_modes(self):
        """测试所有执行模式"""
        assert ExecutionMode.FULL.value == "full"
        assert ExecutionMode.PHASES.value == "phases"
        assert ExecutionMode.STEPS.value == "steps"
        assert ExecutionMode.MODULES.value == "modules"
        assert ExecutionMode.CATEGORIES.value == "categories"
        assert ExecutionMode.PLAN.value == "plan"


class TestArgParser:
    """参数解析器测试"""

    def test_create_parser(self):
        """测试创建解析器"""
        parser = create_parser()
        assert parser is not None
        assert parser.prog == "gpu-cluster-deploy"

    def test_parse_default_args(self):
        """测试解析默认参数"""
        config = parse_args([])

        assert config.config_dir == "config"
        assert config.log_level == "INFO"
        assert config.execution_mode == ExecutionMode.FULL

    def test_parse_config_dir(self):
        """测试解析配置目录参数"""
        config = parse_args(["--config-dir", "/custom/path"])

        assert config.config_dir == "/custom/path"

    def test_parse_phases(self):
        """测试解析阶段参数"""
        config = parse_args(["--phase", "1", "--phase", "2"])

        assert config.execution_mode == ExecutionMode.PHASES
        assert config.phases == [1, 2]

    def test_parse_steps(self):
        """测试解析步骤参数"""
        config = parse_args(["--step", "1.1", "--step", "1.2"])

        assert config.execution_mode == ExecutionMode.STEPS
        assert config.steps == ["1.1", "1.2"]

    def test_parse_modules(self):
        """测试解析模块参数"""
        config = parse_args(["--module", "disk_mount", "--module", "rdma_config"])

        assert config.execution_mode == ExecutionMode.MODULES
        assert config.modules == ["disk_mount", "rdma_config"]

    def test_parse_categories(self):
        """测试解析分类参数"""
        config = parse_args(["--category", "storage", "--category", "gpu"])

        assert config.execution_mode == ExecutionMode.CATEGORIES
        assert config.categories == ["storage", "gpu"]

    def test_parse_plan_file(self):
        """测试解析计划文件参数"""
        config = parse_args(["--plan", "config/plans/gpu-only.yaml"])

        assert config.execution_mode == ExecutionMode.PLAN
        assert config.plan_file == "config/plans/gpu-only.yaml"

    def test_parse_dry_run(self):
        """测试解析dry-run参数"""
        config = parse_args(["--dry-run"])

        assert config.dry_run is True

    def test_parse_parallel(self):
        """测试解析并行参数"""
        config = parse_args(["--parallel", "--max-parallel", "5"])

        assert config.parallel is True
        assert config.max_parallel == 5

    def test_parse_output_format(self):
        """测试解析输出格式参数"""
        config = parse_args(["--output", "json"])

        assert config.output_format == "json"

    def test_mutually_exclusive_targets(self):
        """测试互斥的执行目标参数"""
        # phases和steps是互斥的
        with pytest.raises(SystemExit):
            parse_args(["--phase", "1", "--step", "1.1"])


class TestExecutionResult:
    """ExecutionResult数据类测试"""

    def test_default_result(self):
        """测试默认结果"""
        result = ExecutionResult(success=False, start_time=datetime.now())

        assert result.success is False
        assert result.total_modules == 0
        assert result.completed_modules == 0
        assert result.failed_modules == 0
        assert result.skipped_modules == 0
        assert result.module_results == {}
        assert result.errors == []
        assert result.warnings == []

    def test_result_duration(self):
        """测试结果耗时计算"""
        start = datetime(2026, 2, 25, 10, 0, 0)
        end = datetime(2026, 2, 25, 10, 5, 30)
        result = ExecutionResult(start_time=start, end_time=end)

        assert result.duration_seconds == 330.0

    def test_result_to_dict(self):
        """测试结果转换为字典"""
        start = datetime(2026, 2, 25, 10, 0, 0)
        result = ExecutionResult(
            start_time=start,
            success=True,
            total_modules=5,
            completed_modules=5,
        )

        result_dict = result.to_dict()

        assert result_dict["success"] is True
        assert result_dict["total_modules"] == 5
        assert result_dict["completed_modules"] == 5
        assert "start_time" in result_dict


class TestExecutionController:
    """ExecutionController测试"""

    def test_controller_initialization(self):
        """测试控制器初始化"""
        config = CLIConfig()
        controller = ExecutionController(config)

        assert controller.config == config
        assert controller.state == ExecutionState.IDLE
        assert controller.result is None

    def test_controller_lazy_loading(self):
        """测试控制器延迟加载"""
        config = CLIConfig()
        controller = ExecutionController(config)

        # 延迟加载的组件应该为None
        assert controller._config_loader is None
        assert controller._module_manager is None
        assert controller._logger is None

    @patch('src.cli.execution_controller.ConfigLoader')
    def test_get_status(self, mock_loader_class):
        """测试获取状态"""
        config = CLIConfig()
        controller = ExecutionController(config)

        status = controller.get_status()

        assert status["state"] == "idle"
        assert status["result"] is None


class TestProgressReporter:
    """ProgressReporter测试"""

    def test_reporter_initialization(self):
        """测试报告器初始化"""
        reporter = ProgressReporter()

        assert reporter.format == "text"
        assert reporter.output_file is None
        assert reporter.report is None

    def test_reporter_custom_format(self):
        """测试自定义格式"""
        reporter = ProgressReporter(format="json", output_file="/tmp/report.json")

        assert reporter.format == "json"
        assert reporter.output_file == "/tmp/report.json"

    def test_format_json(self):
        """测试JSON格式化"""
        reporter = ProgressReporter(format="json")
        reporter.report = DeploymentReport(
            cluster_name="test-cluster",
            start_time=datetime(2026, 2, 25, 10, 0, 0),
            success=True,
        )

        output = reporter._format_json()

        assert '"cluster_name": "test-cluster"' in output
        assert '"success": true' in output

    def test_format_markdown(self):
        """测试Markdown格式化"""
        reporter = ProgressReporter(format="markdown")
        reporter.report = DeploymentReport(
            cluster_name="test-cluster",
            start_time=datetime(2026, 2, 25, 10, 0, 0),
            success=True,
            total_modules=5,
            completed_modules=5,
        )

        output = reporter._format_markdown()

        assert "# GPU集群部署报告" in output
        assert "test-cluster" in output
        assert "| 总模块数 | 5 |" in output

    def test_format_text(self):
        """测试文本格式化"""
        reporter = ProgressReporter(format="text")
        reporter.report = DeploymentReport(
            cluster_name="test-cluster",
            start_time=datetime(2026, 2, 25, 10, 0, 0),
            success=True,
            total_modules=5,
        )

        output = reporter._format_text()

        assert "GPU集群部署报告" in output
        assert "test-cluster" in output


class TestModuleReport:
    """ModuleReport数据类测试"""

    def test_module_report_default(self):
        """测试模块报告默认值"""
        report = ModuleReport(
            module_id="test_module",
            module_name="Test Module",
            status="success",
        )

        assert report.module_id == "test_module"
        assert report.module_name == "Test Module"
        assert report.status == "success"
        assert report.error is None

    def test_module_report_to_dict(self):
        """测试模块报告转换为字典"""
        report = ModuleReport(
            module_id="test_module",
            module_name="Test Module",
            status="failed",
            error="Test error",
        )

        report_dict = report.to_dict()

        assert report_dict["module_id"] == "test_module"
        assert report_dict["status"] == "failed"
        assert report_dict["error"] == "Test error"


class TestDeploymentReport:
    """DeploymentReport数据类测试"""

    def test_deployment_report_default(self):
        """测试部署报告默认值"""
        report = DeploymentReport(
            cluster_name="test-cluster",
            start_time=datetime.now(),
        )

        assert report.cluster_name == "test-cluster"
        assert report.success is False
        assert report.modules == []
        assert report.errors == []

    def test_deployment_report_to_dict(self):
        """测试部署报告转换为字典"""
        report = DeploymentReport(
            cluster_name="test-cluster",
            start_time=datetime(2026, 2, 25, 10, 0, 0),
            success=True,
            total_modules=5,
            completed_modules=5,
            cuda_version="12.0",
        )

        report_dict = report.to_dict()

        assert report_dict["cluster_name"] == "test-cluster"
        assert report_dict["success"] is True
        assert report_dict["cuda_version"] == "12.0"


class TestRealTimeProgressTracker:
    """RealTimeProgressTracker测试"""

    def test_tracker_initialization(self):
        """测试跟踪器初始化"""
        tracker = RealTimeProgressTracker(total_modules=10)

        assert tracker.total_modules == 10
        assert tracker.completed_modules == 0
        assert tracker.failed_modules == 0
        assert tracker.current_module is None

    def test_tracker_start_module(self):
        """测试开始模块"""
        tracker = RealTimeProgressTracker(total_modules=5)
        tracker.start_module("module_1")

        assert tracker.current_module == "module_1"
        assert "module_1" in tracker._module_times

    def test_tracker_complete_module(self):
        """测试完成模块"""
        tracker = RealTimeProgressTracker(total_modules=5)
        tracker.start_module("module_1")
        tracker.complete_module("module_1", success=True)

        assert tracker.completed_modules == 1
        assert tracker.failed_modules == 0
        assert tracker.current_module is None

    def test_tracker_fail_module(self):
        """测试失败模块"""
        tracker = RealTimeProgressTracker(total_modules=5)
        tracker.start_module("module_1")
        tracker.complete_module("module_1", success=False)

        assert tracker.completed_modules == 0
        assert tracker.failed_modules == 1

    def test_tracker_get_progress(self):
        """测试获取进度"""
        tracker = RealTimeProgressTracker(total_modules=10)
        tracker.start_module("module_1")
        tracker.complete_module("module_1", success=True)
        tracker.start_module("module_2")
        tracker.complete_module("module_2", success=True)

        progress = tracker.get_progress()

        assert progress["total_modules"] == 10
        assert progress["completed_modules"] == 2
        assert progress["progress_percent"] == 20.0

    def test_tracker_format_progress(self):
        """测试格式化进度"""
        tracker = RealTimeProgressTracker(total_modules=5)
        tracker.start_module("module_1")
        tracker.complete_module("module_1", success=True)

        formatted = tracker.format_progress()

        assert "20.0%" in formatted
        assert "1/5" in formatted


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
