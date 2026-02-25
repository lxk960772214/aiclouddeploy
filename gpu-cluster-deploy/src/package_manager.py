"""
安装包管理器

功能:
- 自动下载: 配置了 download_url 且本地文件不存在时自动下载
- 单次下载: 在跳转机下载一次，然后分发给所有节点
- 校验机制: 下载后验证 MD5/SHA256
- 缓存管理: 避免重复下载
"""

import os
import hashlib
import tempfile
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional, List, Dict, Any, Callable
import logging
import subprocess
import time

logger = logging.getLogger(__name__)


class PackageType(Enum):
    """安装包类型"""
    NVIDIA_DRIVER = "nvidia_driver"
    CUDA_TOOLKIT = "cuda_toolkit"
    MLNX_OFED = "mlnx_ofed"
    FABRICMANAGER = "fabricmanager"
    NCCL = "nccl"
    CUSTOM = "custom"


@dataclass
class PackageConfig:
    """安装包配置"""
    name: str
    version: str
    package_type: PackageType
    local_file: Optional[str] = None  # 节点上已有的文件路径
    download_url: Optional[str] = None  # 下载URL
    checksum: Optional[str] = None  # 校验和 (格式: md5:xxx 或 sha256:xxx)
    checksum_type: str = "sha256"  # 默认校验类型
    file_size: Optional[int] = None  # 文件大小(字节)
    cache_dir: str = "/opt/gpu-deploy/cache"  # 跳转机缓存目录

    @property
    def filename(self) -> str:
        """获取文件名"""
        if self.local_file:
            return Path(self.local_file).name
        if self.download_url:
            return self.download_url.split("/")[-1].split("?")[0]
        return f"{self.name}-{self.version}"

    @property
    def cache_path(self) -> Path:
        """缓存文件路径"""
        return Path(self.cache_dir) / self.filename

    def parse_checksum(self) -> tuple:
        """解析校验和配置"""
        if not self.checksum:
            return self.checksum_type, None

        if ":" in self.checksum:
            parts = self.checksum.split(":", 1)
            return parts[0], parts[1]
        return self.checksum_type, self.checksum


class PackageDownloader:
    """安装包下载器"""

    def __init__(self, cache_dir: str = "/opt/gpu-deploy/cache"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def calculate_checksum(self, filepath: Path, algorithm: str = "sha256") -> str:
        """计算文件校验和"""
        hash_func = hashlib.new(algorithm)
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                hash_func.update(chunk)
        return hash_func.hexdigest()

    def verify_checksum(self, filepath: Path, expected_checksum: str, algorithm: str = "sha256") -> bool:
        """验证文件校验和"""
        if not expected_checksum:
            logger.warning(f"未配置校验和，跳过验证: {filepath}")
            return True

        actual = self.calculate_checksum(filepath, algorithm)
        if actual.lower() == expected_checksum.lower():
            logger.info(f"校验和验证通过: {filepath}")
            return True
        else:
            logger.error(f"校验和验证失败: {filepath}")
            logger.error(f"  期望: {expected_checksum}")
            logger.error(f"  实际: {actual}")
            return False

    def download_with_wget(self, url: str, dest: Path, timeout: int = 3600) -> bool:
        """使用 wget 下载"""
        cmd = [
            "wget", "-c",  # 断点续传
            "-O", str(dest),
            "--timeout=60",
            "--tries=3",
            url
        ]
        try:
            result = subprocess.run(cmd, timeout=timeout, capture_output=True, text=True)
            return result.returncode == 0
        except subprocess.TimeoutExpired:
            logger.error(f"下载超时: {url}")
            return False
        except Exception as e:
            logger.error(f"下载失败: {e}")
            return False

    def download_with_curl(self, url: str, dest: Path, timeout: int = 3600) -> bool:
        """使用 curl 下载"""
        cmd = [
            "curl", "-L",  # 跟随重定向
            "-C", "-",  # 断点续传
            "-o", str(dest),
            "--connect-timeout", "60",
            "--retry", "3",
            "-f",  # 失败时返回错误码
            url
        ]
        try:
            result = subprocess.run(cmd, timeout=timeout, capture_output=True, text=True)
            return result.returncode == 0
        except subprocess.TimeoutExpired:
            logger.error(f"下载超时: {url}")
            return False
        except Exception as e:
            logger.error(f"下载失败: {e}")
            return False

    def download(self, url: str, dest: Path, timeout: int = 3600) -> bool:
        """下载文件（自动选择工具）"""
        logger.info(f"开始下载: {url}")
        logger.info(f"目标路径: {dest}")

        # 确保目标目录存在
        dest.parent.mkdir(parents=True, exist_ok=True)

        start_time = time.time()

        # 优先使用 wget，其次 curl
        success = False
        if shutil.which("wget"):
            success = self.download_with_wget(url, dest, timeout)
        elif shutil.which("curl"):
            success = self.download_with_curl(url, dest, timeout)
        else:
            logger.error("未找到 wget 或 curl，无法下载")
            return False

        elapsed = time.time() - start_time

        if success:
            size_mb = dest.stat().st_size / (1024 * 1024)
            speed_mbps = size_mb / elapsed if elapsed > 0 else 0
            logger.info(f"下载完成: {size_mb:.2f} MB, 耗时 {elapsed:.1f}s, 速度 {speed_mbps:.2f} MB/s")
        else:
            logger.error(f"下载失败: {url}")
            if dest.exists():
                dest.unlink()

        return success


import shutil


class PackageManager:
    """
    安装包管理器

    负责管理所有安装包的下载、缓存、校验和分发。
    采用"跳转机下载一次，分发给所有节点"的策略。
    """

    def __init__(self,
                 cache_dir: str = "/opt/gpu-deploy/cache",
                 ssh_manager=None,
                 logger: Optional[logging.Logger] = None):
        """
        初始化包管理器

        Args:
            cache_dir: 跳转机上的缓存目录
            ssh_manager: SSH管理器，用于分发文件到节点
            logger: 日志器
        """
        self.cache_dir = Path(cache_dir)
        self.ssh_manager = ssh_manager
        self.logger = logger or logging.getLogger(__name__)
        self.downloader = PackageDownloader(cache_dir)

        # 下载状态跟踪
        self._downloaded: Dict[str, bool] = {}
        self._distributed: Dict[str, Dict[str, bool]] = {}

    def check_local_file(self, package: PackageConfig, host: str = None) -> tuple:
        """
        检查文件是否存在

        Args:
            package: 安装包配置
            host: 目标主机（None表示本地/跳转机）

        Returns:
            tuple: (是否存在, 文件路径)
        """
        # 优先检查配置的 local_file
        if package.local_file:
            if host and self.ssh_manager:
                # 检查远程节点
                check_cmd = f"test -f {package.local_file} && echo 'exists' || echo 'not_found'"
                result = self.ssh_manager.execute_on_host(host, check_cmd)
                if "exists" in result.get("stdout", ""):
                    return True, package.local_file
            else:
                # 检查本地
                if Path(package.local_file).exists():
                    return True, package.local_file

        # 检查默认位置
        default_path = f"/tmp/{package.filename}"
        if host and self.ssh_manager:
            check_cmd = f"test -f {default_path} && echo 'exists' || echo 'not_found'"
            result = self.ssh_manager.execute_on_host(host, check_cmd)
            if "exists" in result.get("stdout", ""):
                return True, default_path
        else:
            if Path(default_path).exists():
                return True, default_path

        return False, None

    def download_if_needed(self, package: PackageConfig, force: bool = False) -> tuple:
        """
        下载安装包（如果需要）

        在跳转机上下载，供后续分发使用。

        Args:
            package: 安装包配置
            force: 是否强制重新下载

        Returns:
            tuple: (是否成功, 文件路径)
        """
        cache_key = package.name

        # 检查是否已下载
        if not force and self._downloaded.get(cache_key):
            if package.cache_path.exists():
                self.logger.info(f"安装包已缓存: {package.cache_path}")
                return True, package.cache_path

        # 检查缓存目录是否已有文件
        if not force and package.cache_path.exists():
            # 验证校验和
            algo, expected = package.parse_checksum()
            if expected:
                if self.downloader.verify_checksum(package.cache_path, expected, algo):
                    self.logger.info(f"缓存文件校验通过: {package.cache_path}")
                    self._downloaded[cache_key] = True
                    return True, package.cache_path
                else:
                    self.logger.warning(f"缓存文件校验失败，重新下载")
                    package.cache_path.unlink()

        # 检查是否配置了下载URL
        if not package.download_url:
            self.logger.error(f"未配置下载URL，无法下载: {package.name}")
            return False, None

        # 执行下载
        self.logger.info(f"开始下载安装包: {package.name} v{package.version}")
        self.logger.info(f"下载地址: {package.download_url}")

        # 确保缓存目录存在
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # 下载文件
        success = self.downloader.download(
            package.download_url,
            package.cache_path
        )

        if not success:
            return False, None

        # 验证校验和
        algo, expected = package.parse_checksum()
        if expected:
            if not self.downloader.verify_checksum(package.cache_path, expected, algo):
                return False, None

        self._downloaded[cache_key] = True
        self.logger.info(f"安装包下载成功: {package.cache_path}")
        return True, package.cache_path

    def distribute_to_host(self, package: PackageConfig, host: str, dest_path: str = None) -> tuple:
        """
        将安装包分发到目标主机

        Args:
            package: 安装包配置
            host: 目标主机
            dest_path: 目标路径（默认 /tmp/filename）

        Returns:
            tuple: (是否成功, 目标路径)
        """
        if not self.ssh_manager:
            self.logger.error("未配置SSH管理器，无法分发文件")
            return False, None

        dest_path = dest_path or f"/tmp/{package.filename}"
        cache_key = f"{package.name}:{host}"

        # 检查节点是否已有文件
        exists, existing_path = self.check_local_file(package, host)
        if exists:
            self.logger.info(f"[{host}] 文件已存在: {existing_path}")
            return True, existing_path

        # 检查是否已分发
        if self._distributed.get(cache_key):
            return True, dest_path

        # 确保跳转机已下载
        success, local_path = self.download_if_needed(package)
        if not success:
            return False, None

        self.logger.info(f"[{host}] 分发安装包: {package.filename}")

        # 使用 SCP 分发文件
        try:
            success = self.ssh_manager.copy_file_to_host(
                str(local_path),
                dest_path,
                host
            )

            if success:
                self._distributed[cache_key] = True
                self.logger.info(f"[{host}] 分发完成: {dest_path}")
                return True, dest_path
            else:
                self.logger.error(f"[{host}] 分发失败")
                return False, None

        except Exception as e:
            self.logger.error(f"[{host}] 分发异常: {e}")
            return False, None

    def distribute_to_hosts(self,
                            package: PackageConfig,
                            hosts: List[str],
                            dest_path: str = None,
                            parallel: bool = True,
                            progress_callback: Optional[Callable] = None) -> Dict[str, tuple]:
        """
        批量分发安装包到多个主机

        Args:
            package: 安装包配置
            hosts: 目标主机列表
            dest_path: 目标路径
            parallel: 是否并行分发
            progress_callback: 进度回调函数

        Returns:
            Dict[str, tuple]: {host: (success, path)}
        """
        results = {}
        dest_path = dest_path or f"/tmp/{package.filename}"

        self.logger.info(f"开始分发安装包到 {len(hosts)} 个节点: {package.filename}")

        # 先确保跳转机已下载
        success, local_path = self.download_if_needed(package)
        if not success:
            for host in hosts:
                results[host] = (False, None)
            return results

        if parallel and len(hosts) > 1:
            # 并行分发
            from concurrent.futures import ThreadPoolExecutor, as_completed

            with ThreadPoolExecutor(max_workers=min(4, len(hosts))) as executor:
                futures = {
                    executor.submit(self.distribute_to_host, package, host, dest_path): host
                    for host in hosts
                }

                for future in as_completed(futures):
                    host = futures[future]
                    try:
                        success, path = future.result()
                        results[host] = (success, path)
                        if progress_callback:
                            progress_callback(host, success, path)
                    except Exception as e:
                        self.logger.error(f"[{host}] 分发异常: {e}")
                        results[host] = (False, None)
        else:
            # 串行分发
            for i, host in enumerate(hosts):
                self.logger.info(f"分发进度: {i+1}/{len(hosts)}")
                success, path = self.distribute_to_host(package, host, dest_path)
                results[host] = (success, path)
                if progress_callback:
                    progress_callback(host, success, path)

        # 统计结果
        success_count = sum(1 for s, _ in results.values() if s)
        self.logger.info(f"分发完成: {success_count}/{len(hosts)} 成功")

        return results

    def prepare_package(self,
                        package: PackageConfig,
                        hosts: List[str],
                        dest_path: str = None,
                        parallel: bool = True) -> Dict[str, str]:
        """
        准备安装包（智能处理）

        处理逻辑:
        1. 检查节点是否已有文件 (local_file 配置)
        2. 如果没有，在跳转机下载一次
        3. 分发到所有需要的节点

        Args:
            package: 安装包配置
            hosts: 目标主机列表
            dest_path: 目标路径
            parallel: 是否并行分发

        Returns:
            Dict[str, str]: {host: 文件路径}，失败的节点值为 None
        """
        results = {}
        hosts_need_distribute = []

        # 1. 检查各节点是否已有文件
        self.logger.info(f"检查节点文件状态: {package.name}")

        for host in hosts:
            exists, path = self.check_local_file(package, host)
            if exists:
                results[host] = path
                self.logger.info(f"[{host}] 文件已存在: {path}")
            else:
                hosts_need_distribute.append(host)

        if not hosts_need_distribute:
            self.logger.info("所有节点已有安装包文件")
            return results

        self.logger.info(f"需要分发的节点: {len(hosts_need_distribute)}/{len(hosts)}")

        # 2. 下载并分发
        if package.download_url or package.cache_path.exists():
            distribute_results = self.distribute_to_hosts(
                package, hosts_need_distribute, dest_path, parallel
            )
            for host, (success, path) in distribute_results.items():
                results[host] = path if success else None
        else:
            self.logger.error(f"无法准备安装包: 未配置 download_url 且缓存中无文件")
            for host in hosts_need_distribute:
                results[host] = None

        return results

    def clear_cache(self, package: PackageConfig = None):
        """清理缓存"""
        if package:
            if package.cache_path.exists():
                package.cache_path.unlink()
                self.logger.info(f"已清理缓存: {package.cache_path}")
            self._downloaded.pop(package.name, None)
        else:
            import shutil
            if self.cache_dir.exists():
                shutil.rmtree(self.cache_dir)
                self.logger.info(f"已清理所有缓存: {self.cache_dir}")
            self._downloaded.clear()
            self._distributed.clear()


def create_package_config_from_versions(name: str, versions_config: Any) -> PackageConfig:
    """
    从版本配置创建安装包配置

    Args:
        name: 包名称 (nvidia_driver, cuda, mlnx_ofed 等)
        versions_config: 版本配置对象

    Returns:
        PackageConfig
    """
    type_mapping = {
        "nvidia_driver": PackageType.NVIDIA_DRIVER,
        "cuda": PackageType.CUDA_TOOLKIT,
        "mlnx_ofed": PackageType.MLNX_OFED,
        "fabricmanager": PackageType.FABRICMANAGER,
        "nccl": PackageType.NCCL,
    }

    # 获取对应的配置对象
    config_map = {
        "nvidia_driver": getattr(versions_config, 'nvidia_driver', None),
        "cuda": getattr(versions_config, 'cuda', None),
        "mlnx_ofed": getattr(versions_config, 'mlnx_ofed', None),
        "fabricmanager": getattr(versions_config, 'fabricmanager', None),
        "nccl": getattr(versions_config, 'nccl', None),
    }

    config = config_map.get(name)
    if not config:
        raise ValueError(f"未知的安装包类型: {name}")

    return PackageConfig(
        name=name,
        version=getattr(config, 'version', 'unknown'),
        package_type=type_mapping.get(name, PackageType.CUSTOM),
        local_file=getattr(config, 'local_file', None),
        download_url=getattr(config, 'download_url', None),
        checksum=getattr(config, 'checksum', None),
        file_size=getattr(config, 'file_size', None),
    )
