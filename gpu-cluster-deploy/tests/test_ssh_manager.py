"""
SSH管理器单元测试
"""

import unittest
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path
import sys
import os

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ssh_manager import SSHManager, SSHConnection, SSHResult


class TestSSHResult(unittest.TestCase):
    """SSH结果测试"""

    def test_success_result(self):
        """测试成功结果"""
        result = SSHResult(
            success=True,
            exit_code=0,
            stdout="output",
            stderr="",
            host="192.168.1.1",
            command="echo test"
        )
        self.assertTrue(result.success)
        self.assertEqual(result.exit_code, 0)

    def test_failure_result(self):
        """测试失败结果"""
        result = SSHResult(
            success=False,
            exit_code=1,
            stdout="",
            stderr="error",
            host="192.168.1.1",
            command="false"
        )
        self.assertFalse(result.success)

    def test_get_method(self):
        """测试 get 方法（字典式访问）"""
        result = SSHResult(
            success=True,
            exit_code=0,
            stdout="output",
            stderr="error",
            host="192.168.1.1",
            command="echo test",
            duration=1.5
        )
        # 测试获取存在的属性
        self.assertTrue(result.get("success"))
        self.assertEqual(result.get("stdout"), "output")
        self.assertEqual(result.get("stderr"), "error")
        self.assertEqual(result.get("exit_code"), 0)
        self.assertEqual(result.get("host"), "192.168.1.1")
        self.assertEqual(result.get("command"), "echo test")
        self.assertEqual(result.get("duration"), 1.5)

        # 测试获取不存在的属性，返回默认值
        self.assertIsNone(result.get("nonexistent"))
        self.assertEqual(result.get("nonexistent", "default"), "default")

    def test_to_dict_method(self):
        """测试 to_dict 方法"""
        result = SSHResult(
            success=True,
            exit_code=0,
            stdout="output",
            stderr="error",
            host="192.168.1.1",
            command="echo test",
            duration=1.5
        )
        result_dict = result.to_dict()
        self.assertEqual(result_dict["success"], True)
        self.assertEqual(result_dict["exit_code"], 0)
        self.assertEqual(result_dict["stdout"], "output")
        self.assertEqual(result_dict["stderr"], "error")
        self.assertEqual(result_dict["host"], "192.168.1.1")
        self.assertEqual(result_dict["command"], "echo test")
        self.assertEqual(result_dict["duration"], 1.5)

    def test_str_method(self):
        """测试字符串表示"""
        result_success = SSHResult(
            success=True,
            exit_code=0,
            stdout="output",
            stderr="",
            host="192.168.1.1",
            command="echo test",
            duration=1.5
        )
        self.assertIn("✓", str(result_success))
        self.assertIn("192.168.1.1", str(result_success))

        result_failure = SSHResult(
            success=False,
            exit_code=1,
            stdout="",
            stderr="error",
            host="192.168.1.2",
            command="false"
        )
        self.assertIn("✗", str(result_failure))


class TestSSHManager(unittest.TestCase):
    """SSH管理器测试"""

    def test_init_without_jumphost(self):
        """测试无跳转服务器初始化"""
        manager = SSHManager()
        self.assertIsNone(manager.jumphost_config)
        self.assertIsNone(manager.jump_client)

    def test_init_with_jumphost(self):
        """测试带跳转服务器初始化"""
        config = {
            "host": "192.168.1.1",
            "port": 22,
            "username": "ubuntu",
            "private_key": "/tmp/test_key"
        }
        manager = SSHManager(config)
        self.assertEqual(manager.jumphost_config, config)

    @patch('ssh_manager.paramiko.SSHClient')
    @patch('ssh_manager.paramiko.RSAKey')
    @patch('os.path.expanduser')
    @patch('os.path.exists')
    def test_connect_jumphost_key_auth(self, mock_exists, mock_expanduser, mock_rsa_key, mock_ssh_client):
        """测试密钥认证连接跳转服务器"""
        # Mock 路径扩展
        mock_expanduser.return_value = "/home/test/.ssh/id_rsa"
        mock_exists.return_value = True

        config = {
            "host": "192.168.1.1",
            "port": 22,
            "username": "ubuntu",
            "private_key": "~/.ssh/id_rsa"
        }
        manager = SSHManager(config)

        # Mock SSH client
        mock_client = MagicMock()
        mock_ssh_client.return_value = mock_client

        # Mock RSA key
        mock_key = MagicMock()
        mock_rsa_key.from_private_key_file.return_value = mock_key

        result = manager.connect_jumphost()

        self.assertTrue(result)
        mock_client.connect.assert_called_once()

    def test_close_all(self):
        """测试关闭所有连接"""
        manager = SSHManager()

        # 添加模拟连接
        mock_conn = MagicMock()
        manager.connections["test"] = mock_conn

        manager.close_all()

        mock_conn.disconnect.assert_called_once()
        self.assertEqual(len(manager.connections), 0)


class TestSSHConnection(unittest.TestCase):
    """SSH连接测试"""

    def test_connection_init(self):
        """测试连接初始化"""
        conn = SSHConnection(
            host="192.168.1.1",
            port=22,
            username="ubuntu",
            private_key="/tmp/test_key"
        )
        self.assertEqual(conn.host, "192.168.1.1")
        self.assertEqual(conn.port, 22)
        self.assertFalse(conn._connected)


if __name__ == "__main__":
    unittest.main()
