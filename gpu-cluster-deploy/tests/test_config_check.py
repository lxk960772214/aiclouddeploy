"""
配置检查机制单元测试
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from src.steps.base import BaseStep, StepResult, StepStatus


class MockStep(BaseStep):
    """测试用的模拟步骤类"""

    step_id = "test"
    step_name = "测试步骤"
    step_description = "用于测试的步骤"

    def __init__(self, config=None, ssh_manager=None, batch_executor=None, logger=None, versions=None):
        super().__init__(config, ssh_manager, batch_executor, logger, versions)
        self._is_configured_results = {}

    def execute(self, hosts):
        return StepResult(
            step_id=self.step_id,
            step_name=self.step_name,
            status=StepStatus.SUCCESS,
            message="执行成功"
        )

    def set_is_configured_result(self, host, result):
        """设置 is_configured 的返回结果"""
        self._is_configured_results[host] = result

    def is_configured(self, host):
        """返回预设的结果"""
        return self._is_configured_results.get(host, (False, "未配置"))


class TestBaseStepIsConfigured:
    """BaseStep.is_configured 测试"""

    def test_default_is_configured_returns_false(self):
        """测试默认 is_configured 返回 False"""
        # 使用 MockStep 测试默认行为
        step = MockStep()
        # 清除预设结果，使用默认实现
        step._is_configured_results = {}

        # MockStep 覆盖了 is_configured，所以直接测试基类
        from src.steps.base import BaseStep
        # 创建一个最小的具体子类
        class MinimalStep(BaseStep):
            step_id = "minimal"
            step_name = "Minimal"
            def execute(self, hosts):
                pass

        step = MinimalStep(config=None, ssh_manager=None, batch_executor=None, logger=Mock())
        result, message = step.is_configured("test-host")

        assert result is False
        assert "未实现" in message


class TestCheckAllConfigured:
    """check_all_configured 测试"""

    def test_check_all_configured_all_true(self):
        """测试所有主机都已配置"""
        step = MockStep()
        step.set_is_configured_result("host1", (True, "已配置"))
        step.set_is_configured_result("host2", (True, "已配置"))
        step.set_is_configured_result("host3", (True, "已配置"))

        results = step.check_all_configured(["host1", "host2", "host3"])

        assert len(results) == 3
        assert all(r[0] for r in results.values())

    def test_check_all_configured_mixed(self):
        """测试部分主机已配置"""
        step = MockStep()
        step.set_is_configured_result("host1", (True, "已配置"))
        step.set_is_configured_result("host2", (False, "未配置"))
        step.set_is_configured_result("host3", (True, "已配置"))

        results = step.check_all_configured(["host1", "host2", "host3"])

        assert results["host1"][0] is True
        assert results["host2"][0] is False
        assert results["host3"][0] is True

    def test_check_all_configured_with_exception(self):
        """测试检查过程中的异常处理"""
        step = MockStep()
        step.set_is_configured_result("host1", (True, "已配置"))

        # Mock is_configured 抛出异常
        original_method = step.is_configured
        def mock_is_configured(host):
            if host == "host2":
                raise Exception("连接失败")
            return original_method(host)
        step.is_configured = mock_is_configured

        results = step.check_all_configured(["host1", "host2"])

        assert results["host1"][0] is True
        assert results["host2"][0] is False
        assert "异常" in results["host2"][1]


class TestRunWithConfigCheck:
    """run 方法配置检查测试"""

    @pytest.fixture
    def mock_logger(self):
        """创建 mock logger"""
        logger = Mock()
        logger.start_step = Mock()
        logger.end_step = Mock()
        logger.info = Mock()
        logger.warning = Mock()
        return logger

    def test_run_skips_all_configured(self, mock_logger):
        """测试所有主机已配置时跳过执行"""
        step = MockStep(logger=mock_logger)
        step.set_is_configured_result("host1", (True, "已配置"))
        step.set_is_configured_result("host2", (True, "已配置"))

        result = step.run(["host1", "host2"])

        assert result.status == StepStatus.SKIPPED
        assert "跳过" in result.message
        assert 2 in [result.details.get("skipped_count")]

    def test_run_executes_not_configured(self, mock_logger):
        """测试未配置主机正常执行"""
        step = MockStep(logger=mock_logger)
        step.set_is_configured_result("host1", (False, "未配置"))
        step.set_is_configured_result("host2", (False, "未配置"))

        result = step.run(["host1", "host2"])

        assert result.status == StepStatus.SUCCESS
        assert result.message == "执行成功"

    def test_run_partial_skip(self, mock_logger):
        """测试部分主机跳过"""
        step = MockStep(logger=mock_logger)
        step.set_is_configured_result("host1", (True, "已配置"))
        step.set_is_configured_result("host2", (False, "未配置"))

        result = step.run(["host1", "host2"])

        assert result.status == StepStatus.SUCCESS
        assert result.details.get("skipped_count") == 1
        assert "host1" in result.details.get("skipped_hosts", [])

    def test_run_skip_if_configured_false(self, mock_logger):
        """测试 skip_if_configured=False 时不跳过"""
        step = MockStep(logger=mock_logger)
        step.skip_if_configured = False
        step.set_is_configured_result("host1", (True, "已配置"))

        result = step.run(["host1"])

        # 不应该跳过，应该执行
        assert result.status == StepStatus.SUCCESS
        assert result.message == "执行成功"


class TestStepResult:
    """StepResult 测试"""

    def test_result_success_property(self):
        """测试 success 属性"""
        result = StepResult(
            step_id="test",
            step_name="Test",
            status=StepStatus.SUCCESS
        )
        assert result.success is True

    def test_result_skipped_is_success(self):
        """测试 SKIPPED 状态也被视为成功"""
        result = StepResult(
            step_id="test",
            step_name="Test",
            status=StepStatus.SKIPPED
        )
        assert result.success is True

    def test_result_to_dict(self):
        """测试 to_dict 方法"""
        result = StepResult(
            step_id="test",
            step_name="Test",
            status=StepStatus.SUCCESS,
            message="成功",
            duration=1.5,
            details={"key": "value"}
        )
        d = result.to_dict()

        assert d["step_id"] == "test"
        assert d["status"] == "success"
        assert d["message"] == "成功"
        assert d["duration"] == 1.5
        assert d["details"]["key"] == "value"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
