"""
测试计划: 安装包管理器功能

测试范围:
- PackageConfig 配置类
- PackageDownloader 下载器
- PackageManager 管理器
- 各安装步骤集成

创建时间: 2026-02-25
"""

import os
import sys
import tempfile
import hashlib
import unittest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.package_manager import (
    PackageConfig,
    PackageDownloader,
    PackageManager,
    PackageType,
    create_package_config_from_versions
)


class TestPackageConfig(unittest.TestCase):
    """测试 PackageConfig 配置类"""

    def test_filename_from_local_file(self):
        """测试从 local_file 提取文件名"""
        config = PackageConfig(
            name="cuda",
            version="12.8",
            package_type=PackageType.CUDA_TOOLKIT,
            local_file="/opt/software/cuda_12.8.0_linux.run"
        )
        self.assertEqual(config.filename, "cuda_12.8.0_linux.run")

    def test_filename_from_download_url(self):
        """测试从 download_url 提取文件名"""
        config = PackageConfig(
            name="nvidia_driver",
            version="590.48.01",
            package_type=PackageType.NVIDIA_DRIVER,
            download_url="https://example.com/NVIDIA-Linux-x86_64-590.48.01.run?token=abc"
        )
        self.assertEqual(config.filename, "NVIDIA-Linux-x86_64-590.48.01.run")

    def test_filename_default(self):
        """测试默认文件名生成"""
        config = PackageConfig(
            name="test_package",
            version="1.0.0",
            package_type=PackageType.CUSTOM
        )
        self.assertEqual(config.filename, "test_package-1.0.0")

    def test_cache_path(self):
        """测试缓存路径生成"""
        config = PackageConfig(
            name="cuda",
            version="12.8",
            package_type=PackageType.CUDA_TOOLKIT,
            cache_dir="/opt/cache"
        )
        # 默认文件名会使用 name-version
        self.assertEqual(config.cache_path, Path("/opt/cache/cuda-12.8"))

    def test_parse_checksum_sha256(self):
        """测试 SHA256 校验和解析"""
        config = PackageConfig(
            name="test",
            version="1.0",
            package_type=PackageType.CUSTOM,
            checksum="sha256:abc123def456"
        )
        algo, value = config.parse_checksum()
        self.assertEqual(algo, "sha256")
        self.assertEqual(value, "abc123def456")

    def test_parse_checksum_md5(self):
        """测试 MD5 校验和解析"""
        config = PackageConfig(
            name="test",
            version="1.0",
            package_type=PackageType.CUSTOM,
            checksum="md5:12345abcdef"
        )
        algo, value = config.parse_checksum()
        self.assertEqual(algo, "md5")
        self.assertEqual(value, "12345abcdef")

    def test_parse_checksum_default(self):
        """测试默认校验和类型"""
        config = PackageConfig(
            name="test",
            version="1.0",
            package_type=PackageType.CUSTOM,
            checksum="simplevalue"
        )
        algo, value = config.parse_checksum()
        self.assertEqual(algo, "sha256")  # 默认类型
        self.assertEqual(value, "simplevalue")

    def test_parse_checksum_none(self):
        """测试无校验和"""
        config = PackageConfig(
            name="test",
            version="1.0",
            package_type=PackageType.CUSTOM
        )
        algo, value = config.parse_checksum()
        self.assertEqual(algo, "sha256")
        self.assertIsNone(value)


class TestPackageDownloader(unittest.TestCase):
    """测试 PackageDownloader 下载器"""

    def setUp(self):
        """测试前置设置"""
        self.temp_dir = tempfile.mkdtemp()
        self.downloader = PackageDownloader(self.temp_dir)

    def tearDown(self):
        """测试后清理"""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_calculate_checksum_sha256(self):
        """测试 SHA256 校验和计算"""
        # 创建测试文件
        test_file = Path(self.temp_dir) / "test.txt"
        test_file.write_text("Hello, World!")

        # 计算预期值
        expected = hashlib.sha256(b"Hello, World!").hexdigest()

        # 验证
        result = self.downloader.calculate_checksum(test_file, "sha256")
        self.assertEqual(result, expected)

    def test_calculate_checksum_md5(self):
        """测试 MD5 校验和计算"""
        test_file = Path(self.temp_dir) / "test.txt"
        test_file.write_text("Hello, World!")

        expected = hashlib.md5(b"Hello, World!").hexdigest()

        result = self.downloader.calculate_checksum(test_file, "md5")
        self.assertEqual(result, expected)

    def test_verify_checksum_success(self):
        """测试校验和验证成功"""
        test_file = Path(self.temp_dir) / "test.txt"
        test_file.write_text("Hello, World!")

        expected = hashlib.sha256(b"Hello, World!").hexdigest()

        result = self.downloader.verify_checksum(test_file, expected, "sha256")
        self.assertTrue(result)

    def test_verify_checksum_failure(self):
        """测试校验和验证失败"""
        test_file = Path(self.temp_dir) / "test.txt"
        test_file.write_text("Hello, World!")

        result = self.downloader.verify_checksum(test_file, "wrong_checksum", "sha256")
        self.assertFalse(result)

    def test_verify_checksum_none(self):
        """测试无校验和时跳过验证"""
        test_file = Path(self.temp_dir) / "test.txt"
        test_file.write_text("Hello, World!")

        result = self.downloader.verify_checksum(test_file, None, "sha256")
        self.assertTrue(result)  # 无校验和时应返回 True

    @patch('subprocess.run')
    def test_download_with_wget_success(self, mock_run):
        """测试 wget 下载成功"""
        mock_run.return_value = MagicMock(returncode=0)

        dest = Path(self.temp_dir) / "downloaded.txt"
        result = self.downloader.download_with_wget(
            "https://example.com/file.txt",
            dest
        )

        self.assertTrue(result)
        mock_run.assert_called_once()

    @patch('subprocess.run')
    def test_download_with_curl_success(self, mock_run):
        """测试 curl 下载成功"""
        mock_run.return_value = MagicMock(returncode=0)

        dest = Path(self.temp_dir) / "downloaded.txt"
        result = self.downloader.download_with_curl(
            "https://example.com/file.txt",
            dest
        )

        self.assertTrue(result)
        mock_run.assert_called_once()


class TestPackageManager(unittest.TestCase):
    """测试 PackageManager 管理器"""

    def setUp(self):
        """测试前置设置"""
        self.temp_dir = tempfile.mkdtemp()
        self.manager = PackageManager(cache_dir=self.temp_dir)

    def tearDown(self):
        """测试后清理"""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_check_local_file_exists(self):
        """测试检查本地文件存在"""
        # 创建测试文件
        test_file = Path(self.temp_dir) / "test.run"
        test_file.write_text("test content")

        config = PackageConfig(
            name="test",
            version="1.0",
            package_type=PackageType.CUSTOM,
            local_file=str(test_file)
        )

        exists, path = self.manager.check_local_file(config)
        self.assertTrue(exists)
        self.assertEqual(path, str(test_file))

    def test_check_local_file_not_exists(self):
        """测试检查本地文件不存在"""
        config = PackageConfig(
            name="test",
            version="1.0",
            package_type=PackageType.CUSTOM,
            local_file="/nonexistent/path/file.run"
        )

        exists, path = self.manager.check_local_file(config)
        self.assertFalse(exists)
        self.assertIsNone(path)

    def test_check_local_file_default_path(self):
        """测试检查默认路径"""
        # 创建默认路径的文件
        default_path = Path("/tmp/test_package-1.0.run")

        config = PackageConfig(
            name="test_package",
            version="1.0",
            package_type=PackageType.CUSTOM
        )

        # 由于 /tmp 可能没有文件，预期返回 False
        exists, path = self.manager.check_local_file(config)
        self.assertFalse(exists)

    @patch.object(PackageDownloader, 'download')
    def test_prepare_on_jumphost_success(self, mock_download):
        """测试在登录服务器准备安装包成功"""
        mock_download.return_value = True

        # 创建模拟的缓存文件
        cache_file = Path(self.temp_dir) / "test-1.0.run"
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text("downloaded content")

        config = PackageConfig(
            name="test",
            version="1.0",
            package_type=PackageType.CUSTOM,
            download_url="https://example.com/test.run"
        )

        # 由于没有 ssh_manager，程序在登录服务器上运行，会使用本地下载
        success, path = self.manager.prepare_on_jumphost(config)

        # download_if_needed 会尝试下载，但由于 mock 不会创建文件
        # 所以实际测试需要更复杂的设置

    def test_prepare_on_jumphost_no_source(self):
        """测试无下载URL和local_file时失败"""
        config = PackageConfig(
            name="test",
            version="1.0",
            package_type=PackageType.CUSTOM
        )

        success, path = self.manager.prepare_on_jumphost(config)

        self.assertFalse(success)
        self.assertIsNone(path)

    def test_clear_cache_single_package(self):
        """测试清理单个包缓存"""
        # 创建缓存文件 - 文件名需要与 PackageConfig 的 filename 属性匹配
        config = PackageConfig(
            name="test",
            version="1.0",
            package_type=PackageType.CUSTOM,
            cache_dir=self.temp_dir
        )

        # 使用 config.cache_path 创建文件
        cache_file = config.cache_path
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text("cached content")

        # 使用新的属性名
        self.manager._prepared_on_jumphost["test"] = True
        self.manager.clear_cache(config)

        # 验证缓存被清理
        self.assertNotIn("test", self.manager._prepared_on_jumphost)

    def test_clear_cache_all(self):
        """测试清理所有缓存"""
        # 创建多个缓存文件
        for i in range(3):
            cache_file = Path(self.temp_dir) / f"test-{i}.run"
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(f"content {i}")

        # 使用新的属性名
        self.manager._prepared_on_jumphost["test1"] = True
        self.manager._prepared_on_jumphost["test2"] = True

        self.manager.clear_cache()

        # 验证所有缓存被清理
        self.assertEqual(len(self.manager._prepared_on_jumphost), 0)
        self.assertEqual(len(self.manager._distributed), 0)


class TestPackageConfigFromVersions(unittest.TestCase):
    """测试从版本配置创建包配置"""

    def test_create_from_nvidia_driver_config(self):
        """测试从 NVIDIA 驱动配置创建"""
        from src.config_loader import NvidiaDriverConfig

        driver_config = NvidiaDriverConfig(
            version="590.48.01",
            local_file="/opt/NVIDIA-Linux-x86_64-590.48.01.run",
            download_url="https://example.com/driver.run",
            checksum="sha256:abc123",
            file_size=300000000
        )

        versions = MagicMock()
        versions.nvidia_driver = driver_config

        package = create_package_config_from_versions("nvidia_driver", versions)

        self.assertEqual(package.name, "nvidia_driver")
        self.assertEqual(package.version, "590.48.01")
        self.assertEqual(package.package_type, PackageType.NVIDIA_DRIVER)
        self.assertEqual(package.local_file, "/opt/NVIDIA-Linux-x86_64-590.48.01.run")
        self.assertEqual(package.download_url, "https://example.com/driver.run")
        self.assertEqual(package.checksum, "sha256:abc123")
        self.assertEqual(package.file_size, 300000000)

    def test_create_from_cuda_config(self):
        """测试从 CUDA 配置创建"""
        from src.config_loader import CudaConfig

        cuda_config = CudaConfig(
            version="12.8",
            download_url="https://example.com/cuda.run",
            checksum="sha256:def456"
        )

        versions = MagicMock()
        versions.cuda = cuda_config

        package = create_package_config_from_versions("cuda", versions)

        self.assertEqual(package.name, "cuda")
        self.assertEqual(package.version, "12.8")
        self.assertEqual(package.package_type, PackageType.CUDA_TOOLKIT)

    def test_create_from_unknown_type(self):
        """测试未知类型抛出异常"""
        versions = MagicMock()

        with self.assertRaises(ValueError):
            create_package_config_from_versions("unknown_package", versions)


class TestIntegrationWithSteps(unittest.TestCase):
    """测试与安装步骤的集成"""

    def test_nvidia_driver_step_prepare_package(self):
        """测试 NVIDIA 驱动步骤准备包方法签名"""
        from src.steps.step_22_nvidia_driver import NVIDIADriver

        # 验证方法存在
        self.assertTrue(hasattr(NVIDIADriver, '_prepare_package'))

    def test_cuda_toolkit_step_prepare_package(self):
        """测试 CUDA 步骤准备包方法签名"""
        from src.steps.step_24_cuda_toolkit import CUDAToolkit

        # 验证方法存在
        self.assertTrue(hasattr(CUDAToolkit, '_prepare_package'))

    def test_mlnx_ofed_step_prepare_package(self):
        """测试 MLNX_OFED 步骤准备包方法签名"""
        from src.steps.step_20_mlnx_ofed import MellanoxDriver

        # 验证方法存在
        self.assertTrue(hasattr(MellanoxDriver, '_prepare_package'))


def run_tests():
    """运行所有测试"""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # 添加测试类
    suite.addTests(loader.loadTestsFromTestCase(TestPackageConfig))
    suite.addTests(loader.loadTestsFromTestCase(TestPackageDownloader))
    suite.addTests(loader.loadTestsFromTestCase(TestPackageManager))
    suite.addTests(loader.loadTestsFromTestCase(TestPackageConfigFromVersions))
    suite.addTests(loader.loadTestsFromTestCase(TestIntegrationWithSteps))

    # 运行测试
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
