"""
sudo 策略单元测试

测试 SSH 连接中的 root 用户检测和 sudo 跳过逻辑
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from src.ssh_manager import SSHConnection, SSHResult


class TestSudoStrategy:
    """sudo 策略测试类"""

    def test_is_root_detection_with_root_user(self):
        """测试 root 用户检测 - root 用户返回 True"""
        conn = SSHConnection(
            host="test-host",
            port=22,
            username="root",
            password="test-password"
        )

        # Mock SSH 客户端
        mock_client = Mock()
        mock_stdout = Mock()
        mock_stdout.channel.recv_exit_status.return_value = 0
        mock_stdout.read.return_value = b"0"  # id -u 返回 0 表示 root
        mock_client.exec_command.return_value = (None, mock_stdout, Mock())

        conn.client = mock_client
        conn._connected = True

        # 测试检测
        result = conn._check_is_root()
        assert result is True
        assert conn._is_root is True

        # 验证只调用一次
        conn._check_is_root()
        mock_client.exec_command.assert_called_once()

    def test_is_root_detection_with_non_root_user(self):
        """测试 root 用户检测 - 非 root 用户返回 False"""
        conn = SSHConnection(
            host="test-host",
            port=22,
            username="ubuntu",
            password="test-password"
        )

        # Mock SSH 客户端
        mock_client = Mock()
        mock_stdout = Mock()
        mock_stdout.channel.recv_exit_status.return_value = 0
        mock_stdout.read.return_value = b"1000"  # id -u 返回 1000 表示普通用户
        mock_client.exec_command.return_value = (None, mock_stdout, Mock())

        conn.client = mock_client
        conn._connected = True

        # 测试检测
        result = conn._check_is_root()
        assert result is False
        assert conn._is_root is False

    def test_is_root_detection_on_error(self):
        """测试 root 用户检测 - 命令执行失败时返回 False"""
        conn = SSHConnection(
            host="test-host",
            port=22,
            username="ubuntu",
            password="test-password"
        )

        # Mock SSH 客户端 - 模拟异常
        mock_client = Mock()
        mock_client.exec_command.side_effect = Exception("Connection error")

        conn.client = mock_client
        conn._connected = True

        # 测试检测 - 异常时应返回 False
        result = conn._check_is_root()
        assert result is False
        assert conn._is_root is False

    def test_execute_skips_sudo_for_root_user(self):
        """测试 root 用户执行命令时跳过 sudo 包装"""
        conn = SSHConnection(
            host="test-host",
            port=22,
            username="root",
            password="test-password"
        )

        # Mock SSH 客户端
        mock_client = Mock()

        # Mock id -u 命令返回 root
        mock_id_stdout = Mock()
        mock_id_stdout.channel.recv_exit_status.return_value = 0
        mock_id_stdout.read.return_value = b"0"

        # Mock 实际命令执行
        mock_exec_stdout = Mock()
        mock_exec_stdout.channel.recv_exit_status.return_value = 0
        mock_exec_stdout.read.return_value = b"command output"
        mock_exec_stderr = Mock()
        mock_exec_stderr.read.return_value = b""

        call_count = [0]

        def exec_command_side_effect(cmd, timeout=None):
            call_count[0] += 1
            if "id -u" in cmd:
                return (None, mock_id_stdout, Mock())
            else:
                # 验证命令没有被 sudo 包装
                assert "sudo" not in cmd, f"命令不应包含 sudo: {cmd}"
                assert "echo" not in cmd, f"命令不应包含密码 echo: {cmd}"
                return (None, mock_exec_stdout, mock_exec_stderr)

        mock_client.exec_command.side_effect = exec_command_side_effect

        conn.client = mock_client
        conn._connected = True

        # 执行需要 sudo 的命令
        result = conn.execute("apt-get update", timeout=60, sudo=True, sudo_password="test-password")

        assert result.success is True
        assert "sudo" not in result.command  # 命令不应被修改

    def test_execute_uses_sudo_for_non_root_user(self):
        """测试非 root 用户执行命令时使用 sudo 包装"""
        conn = SSHConnection(
            host="test-host",
            port=22,
            username="ubuntu",
            password="test-password"
        )

        # Mock SSH 客户端
        mock_client = Mock()

        # Mock id -u 命令返回非 root
        mock_id_stdout = Mock()
        mock_id_stdout.channel.recv_exit_status.return_value = 0
        mock_id_stdout.read.return_value = b"1000"

        # Mock 实际命令执行
        mock_exec_stdout = Mock()
        mock_exec_stdout.channel.recv_exit_status.return_value = 0
        mock_exec_stdout.read.return_value = b"command output"
        mock_exec_stderr = Mock()
        mock_exec_stderr.read.return_value = b""

        def exec_command_side_effect(cmd, timeout=None):
            if "id -u" in cmd:
                return (None, mock_id_stdout, Mock())
            else:
                # 验证命令被 sudo 包装
                assert "sudo" in cmd, f"命令应包含 sudo: {cmd}"
                assert "echo" in cmd, f"命令应包含密码 echo: {cmd}"
                return (None, mock_exec_stdout, mock_exec_stderr)

        mock_client.exec_command.side_effect = exec_command_side_effect

        conn.client = mock_client
        conn._connected = True

        # 执行需要 sudo 的命令
        result = conn.execute("apt-get update", timeout=60, sudo=True, sudo_password="test-password")

        assert result.success is True

    def test_execute_without_sudo_flag(self):
        """测试不使用 sudo 标志时的行为"""
        conn = SSHConnection(
            host="test-host",
            port=22,
            username="ubuntu",
            password="test-password"
        )

        # Mock SSH 客户端
        mock_client = Mock()
        mock_stdout = Mock()
        mock_stdout.channel.recv_exit_status.return_value = 0
        mock_stdout.read.return_value = b"command output"
        mock_stderr = Mock()
        mock_stderr.read.return_value = b""

        def exec_command_side_effect(cmd, timeout=None):
            # 不应该调用 id -u
            assert "id -u" not in cmd
            # 不应该有 sudo 包装
            assert "sudo" not in cmd
            return (None, mock_stdout, mock_stderr)

        mock_client.exec_command.side_effect = exec_command_side_effect

        conn.client = mock_client
        conn._connected = True

        # 执行不需要 sudo 的命令
        result = conn.execute("ls -la", timeout=60, sudo=False)

        assert result.success is True

    def test_disconnect_resets_root_cache(self):
        """测试断开连接时重置 root 用户缓存"""
        conn = SSHConnection(
            host="test-host",
            port=22,
            username="root",
            password="test-password"
        )

        # Mock SSH 客户端
        mock_client = Mock()
        conn.client = mock_client
        conn._connected = True
        conn._is_root = True  # 设置缓存

        # 断开连接
        conn.disconnect()

        assert conn._is_root is None
        assert conn._connected is False
        mock_client.close.assert_called_once()

    def test_command_escaping_in_sudo(self):
        """测试 sudo 包装时的命令转义"""
        conn = SSHConnection(
            host="test-host",
            port=22,
            username="ubuntu",
            password="test-password"
        )

        # Mock SSH 客户端
        mock_client = Mock()

        # Mock id -u 返回非 root
        mock_id_stdout = Mock()
        mock_id_stdout.channel.recv_exit_status.return_value = 0
        mock_id_stdout.read.return_value = b"1000"

        # Mock 实际命令执行
        mock_exec_stdout = Mock()
        mock_exec_stdout.channel.recv_exit_status.return_value = 0
        mock_exec_stdout.read.return_value = b"output"
        mock_exec_stderr = Mock()
        mock_exec_stderr.read.return_value = b""

        captured_cmd = []

        def exec_command_side_effect(cmd, timeout=None):
            captured_cmd.append(cmd)
            if "id -u" in cmd:
                return (None, mock_id_stdout, Mock())
            else:
                return (None, mock_exec_stdout, mock_exec_stderr)

        mock_client.exec_command.side_effect = exec_command_side_effect

        conn.client = mock_client
        conn._connected = True

        # 执行包含特殊字符的命令
        result = conn.execute(
            'echo "test $VAR" && cat /path/to/file',
            timeout=60,
            sudo=True,
            sudo_password="secret"
        )

        # 验证命令被正确转义
        sudo_cmd = captured_cmd[-1]
        assert "sudo -S" in sudo_cmd
        # $VAR 应该被转义
        assert "\\$" in sudo_cmd or "\\$VAR" in sudo_cmd.replace("\\$", "$")


class TestSSHResult:
    """SSHResult 测试"""

    def test_result_success_property(self):
        """测试 success 属性"""
        result = SSHResult(
            success=True,
            exit_code=0,
            stdout="output",
            stderr="",
            host="test",
            command="ls"
        )
        assert result.success is True

    def test_result_to_dict(self):
        """测试 to_dict 方法"""
        result = SSHResult(
            success=True,
            exit_code=0,
            stdout="output",
            stderr="",
            host="test",
            command="ls",
            duration=1.5
        )
        d = result.to_dict()
        assert d["success"] is True
        assert d["exit_code"] == 0
        assert d["stdout"] == "output"
        assert d["host"] == "test"
        assert d["duration"] == 1.5

    def test_result_get_method(self):
        """测试 get 方法（向后兼容）"""
        result = SSHResult(
            success=True,
            exit_code=0,
            stdout="output",
            stderr="error",
            host="test",
            command="ls"
        )
        assert result.get("success") is True
        assert result.get("stdout") == "output"
        assert result.get("nonexistent", "default") == "default"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
