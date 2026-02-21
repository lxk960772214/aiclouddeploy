"""
批量执行器单元测试
"""

import unittest
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from batch_executor import (
    BatchResult, ExecutionSummary, PdshExecutor, BatchExecutor
)


class TestBatchResult(unittest.TestCase):
    """批量执行结果测试"""

    def test_success_result(self):
        """测试成功结果"""
        result = BatchResult(
            host="192.168.1.1",
            success=True,
            exit_code=0,
            stdout="output",
            stderr=""
        )
        self.assertTrue(result.success)

    def test_str_representation(self):
        """测试字符串表示"""
        result = BatchResult(
            host="192.168.1.1",
            success=False,
            exit_code=1,
            stdout="",
            stderr="error"
        )
        s = str(result)
        self.assertIn("192.168.1.1", s)
        self.assertIn("✗", s)


class TestExecutionSummary(unittest.TestCase):
    """执行摘要测试"""

    def test_empty_summary(self):
        """测试空摘要"""
        summary = ExecutionSummary()
        self.assertEqual(summary.total_hosts, 0)
        self.assertEqual(summary.success_rate, 0.0)

    def test_success_rate(self):
        """测试成功率计算"""
        summary = ExecutionSummary(
            total_hosts=10,
            successful=8,
            failed=2
        )
        self.assertEqual(summary.success_rate, 80.0)

    def test_get_failed_hosts(self):
        """测试获取失败主机"""
        summary = ExecutionSummary(total_hosts=3)
        summary.results = {
            "host1": BatchResult("host1", True, 0, "", ""),
            "host2": BatchResult("host2", False, 1, "", "error"),
            "host3": BatchResult("host3", True, 0, "", "")
        }
        summary.successful = 2
        summary.failed = 1

        failed = summary.get_failed_hosts()
        self.assertEqual(failed, ["host2"])


class TestPdshExecutor(unittest.TestCase):
    """Pdsh执行器测试"""

    def test_init(self):
        """测试初始化"""
        executor = PdshExecutor(
            ssh_user="ubuntu",
            ssh_port=22,
            max_parallel=10
        )
        self.assertEqual(executor.ssh_user, "ubuntu")
        self.assertEqual(executor.ssh_port, 22)

    def test_build_pdsh_command(self):
        """测试构建pdsh命令"""
        executor = PdshExecutor(ssh_user="ubuntu")
        cmd = executor._build_pdsh_command(
            hosts=["host1", "host2"],
            command="echo test",
            sudo=False
        )
        self.assertIn("pdsh", cmd)
        self.assertIn("ubuntu", cmd)
        self.assertIn("echo test", cmd)


class TestBatchExecutor(unittest.TestCase):
    """批量执行器测试"""

    def test_init_with_pdsh(self):
        """测试使用pdsh初始化"""
        executor = BatchExecutor(use_pdsh=True)
        self.assertIsNotNone(executor.pdsh_executor)

    def test_init_without_pdsh(self):
        """测试不使用pdsh初始化"""
        executor = BatchExecutor(use_pdsh=False, ssh_manager=Mock())
        self.assertIsNone(executor.pdsh_executor)


if __name__ == "__main__":
    unittest.main()
