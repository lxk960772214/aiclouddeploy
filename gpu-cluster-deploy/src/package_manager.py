"""
安装包管理器

功能:
- 双模式分发: download_url 在登录服务器下载，local_file 从本机上传
- 智能跳过: 登录服务器同时是GPU节点时跳过本机传输
- 单次下载: 在登录服务器下载一次，然后分发给所有节点
- 校验机制: 下载后验证 MD5/SHA256
- 缓存管理: 避免重复下载
- 智能超时: 监控文件增长，只有长时间不增长才超时
"""

import os
import hashlib
import tempfile
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional, List, Dict, Any, Callable, Set
import logging
import subprocess
import time
import shutil
import threading

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
    local_file: Optional[str] = None  # 运行程序的本机上的文件路径
    download_url: Optional[str] = None  # 下载URL（在登录服务器下载）
    checksum: Optional[str] = None  # 校验和 (格式: md5:xxx 或 sha256:xxx)
    checksum_type: str = "sha256"  # 默认校验类型
    file_size: Optional[int] = None  # 文件大小(字节)
    cache_dir: str = "/tmp/gpu-deploy/cache"  # 登录服务器上的缓存目录

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
        """登录服务器上的缓存文件路径"""
        return Path(self.cache_dir) / self.filename

    @property
    def jumphost_tmp_path(self) -> str:
        """登录服务器上的临时文件路径（/tmp目录）"""
        return f"/tmp/{self.filename}"

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

    # 临时文件后缀
    TEMP_SUFFIX = ".downloading"

    def __init__(self, cache_dir: str = "/tmp/gpu-deploy/cache"):
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

    def download_with_wget(self, url: str, dest: Path, timeout: int = 7200, stall_timeout: int = 300) -> bool:
        """
        使用 wget 下载，监控文件增长智能超时

        Args:
            url: 下载URL
            dest: 目标文件路径
            timeout: 总超时时间（秒），默认2小时
            stall_timeout: 文件停滞超时（秒），默认5分钟无增长则终止

        Returns:
            bool: 是否下载成功
        """
        # 使用临时文件下载，完成后重命名
        temp_dest = Path(str(dest) + self.TEMP_SUFFIX)

        # 不设置wget自身的timeout，完全由监控脚本控制
        cmd = [
            "wget", "-c",  # 断点续传
            "-O", str(temp_dest),
            "--timeout=0",    # 禁用wget自身超时，由监控控制
            "--tries=0",      # 无限重试（由我们的监控控制）
            url
        ]

        try:
            # 启动下载进程
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

            last_size = 0
            last_progress_time = time.time()
            start_time = time.time()

            while process.poll() is None:
                current_time = time.time()

                # 检查总超时
                if current_time - start_time > timeout:
                    process.terminate()
                    process.wait(timeout=5)
                    logger.error(f"❌ 下载总超时（{timeout}秒），已终止下载")
                    logger.error(f"   URL: {url}")
                    logger.error(f"   文件: {dest}")
                    logger.error(f"   已下载: {last_size / 1024 / 1024:.2f} MB")
                    # 清理临时文件
                    if temp_dest.exists():
                        temp_dest.unlink()
                    return False

                # 检查文件大小
                try:
                    if temp_dest.exists():
                        current_size = temp_dest.stat().st_size
                        if current_size > last_size:
                            last_size = current_size
                            last_progress_time = current_time
                            # 每10MB打印一次进度
                            if last_size % (10 * 1024 * 1024) < 1024 * 1024:
                                logger.info(f"📥 下载中: {last_size / 1024 / 1024:.2f} MB")
                        elif current_time - last_progress_time > stall_timeout:
                            # 文件长时间不增长
                            process.terminate()
                            process.wait(timeout=5)
                            logger.error(f"❌ 下载停滞超时（{stall_timeout}秒无数据增长）")
                            logger.error(f"   URL: {url}")
                            logger.error(f"   文件: {dest}")
                            logger.error(f"   已下载: {last_size / 1024 / 1024:.2f} MB")
                            logger.error(f"   建议: 检查网络连接或使用其他下载源")
                            # 清理临时文件
                            if temp_dest.exists():
                                temp_dest.unlink()
                            return False
                except Exception as e:
                    logger.debug(f"检查文件大小失败: {e}")

                time.sleep(2)  # 每2秒检查一次

            # 进程结束，检查结果
            returncode = process.poll()
            if returncode != 0:
                _, stderr = process.communicate()
                logger.error(f"❌ wget 下载失败: returncode={returncode}")
                if stderr:
                    logger.error(f"   错误信息: {stderr[:500]}")
                # 清理临时文件
                if temp_dest.exists():
                    temp_dest.unlink()
                return False

            # 下载成功，重命名临时文件为目标文件
            try:
                temp_dest.rename(dest)
                logger.info(f"✅ 下载完成: {dest} ({last_size / 1024 / 1024:.2f} MB)")
                return True
            except Exception as e:
                logger.error(f"❌ 重命名临时文件失败: {e}")
                if temp_dest.exists():
                    temp_dest.unlink()
                return False

        except Exception as e:
            logger.error(f"❌ 下载失败: {e}")
            logger.error(f"   URL: {url}")
            logger.error(f"   文件: {dest}")
            # 清理临时文件
            if temp_dest.exists():
                temp_dest.unlink()
            return False

    def download_with_curl(self, url: str, dest: Path, timeout: int = 7200, stall_timeout: int = 300) -> bool:
        """
        使用 curl 下载，监控文件增长智能超时

        Args:
            url: 下载URL
            dest: 目标文件路径
            timeout: 总超时时间（秒），默认2小时
            stall_timeout: 文件停滞超时（秒），默认5分钟无增长则终止

        Returns:
            bool: 是否下载成功
        """
        # 使用临时文件下载，完成后重命名
        temp_dest = Path(str(dest) + self.TEMP_SUFFIX)

        # 不设置curl的max-time，只设置连接超时
        cmd = [
            "curl", "-L",  # 跟随重定向
            "-C", "-",  # 断点续传
            "-o", str(temp_dest),
            "--connect-timeout", "60",  # 仅连接超时60秒
            "--retry", "0",  # 由我们的监控控制重试
            "-f",  # 失败时返回错误码
            url
        ]

        try:
            # 启动下载进程
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

            last_size = 0
            last_progress_time = time.time()
            start_time = time.time()

            while process.poll() is None:
                current_time = time.time()

                # 检查总超时
                if current_time - start_time > timeout:
                    process.terminate()
                    process.wait(timeout=5)
                    logger.error(f"❌ 下载总超时（{timeout}秒），已终止下载")
                    logger.error(f"   URL: {url}")
                    logger.error(f"   文件: {dest}")
                    logger.error(f"   已下载: {last_size / 1024 / 1024:.2f} MB")
                    # 清理临时文件
                    if temp_dest.exists():
                        temp_dest.unlink()
                    return False

                # 检查文件大小
                try:
                    if temp_dest.exists():
                        current_size = temp_dest.stat().st_size
                        if current_size > last_size:
                            last_size = current_size
                            last_progress_time = current_time
                        elif current_time - last_progress_time > stall_timeout:
                            # 文件长时间不增长
                            process.terminate()
                            process.wait(timeout=5)
                            logger.error(f"❌ 下载停滞超时（{stall_timeout}秒无数据增长）")
                            logger.error(f"   URL: {url}")
                            logger.error(f"   文件: {dest}")
                            logger.error(f"   已下载: {last_size / 1024 / 1024:.2f} MB")
                            logger.error(f"   建议: 检查网络连接或使用其他下载源")
                            # 清理临时文件
                            if temp_dest.exists():
                                temp_dest.unlink()
                            return False
                except Exception as e:
                    logger.debug(f"检查文件大小失败: {e}")

                time.sleep(2)  # 每2秒检查一次

            # 进程结束，检查结果
            returncode = process.poll()
            if returncode != 0:
                _, stderr = process.communicate()
                logger.error(f"❌ curl 下载失败: returncode={returncode}")
                if stderr:
                    logger.error(f"   错误信息: {stderr[:500]}")
                # 清理临时文件
                if temp_dest.exists():
                    temp_dest.unlink()
                return False

            # 下载成功，重命名临时文件为目标文件
            try:
                temp_dest.rename(dest)
                logger.info(f"✅ 下载完成: {dest} ({last_size / 1024 / 1024:.2f} MB)")
                return True
            except Exception as e:
                logger.error(f"❌ 重命名临时文件失败: {e}")
                if temp_dest.exists():
                    temp_dest.unlink()
                return False

        except Exception as e:
            logger.error(f"❌ 下载失败: {e}")
            logger.error(f"   URL: {url}")
            logger.error(f"   文件: {dest}")
            # 清理临时文件
            if temp_dest.exists():
                temp_dest.unlink()
            return False

    def download(self, url: str, dest: Path, timeout: int = 3600) -> bool:
        """下载文件（自动选择工具）

        使用临时文件机制：
        1. 先下载到 <filename>.downloading 临时文件
        2. 下载完成后重命名为目标文件
        3. 如果存在临时文件，说明上次下载未完成，会自动清理后重新下载
        """
        logger.info(f"开始下载: {url}")
        logger.info(f"目标路径: {dest}")

        # 检查并清理可能存在的临时文件（上次未完成的下载）
        temp_dest = Path(str(dest) + self.TEMP_SUFFIX)
        if temp_dest.exists():
            logger.warning(f"检测到未完成的下载临时文件，将清理后重新下载: {temp_dest}")
            try:
                temp_dest.unlink()
            except Exception as e:
                logger.error(f"清理临时文件失败: {e}")

        # 确保目标目录存在
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            logger.info(f"缓存目录已创建: {dest.parent}")
        except PermissionError as e:
            logger.error(f"无法创建缓存目录 {dest.parent}: {e}")
            return False
        except Exception as e:
            logger.error(f"创建缓存目录失败: {e}")
            return False

        start_time = time.time()

        # 优先使用 wget，其次 curl
        success = False
        if shutil.which("wget"):
            logger.info(f"使用 wget 下载...")
            success = self.download_with_wget(url, dest, timeout)
        elif shutil.which("curl"):
            logger.info(f"使用 curl 下载...")
            success = self.download_with_curl(url, dest, timeout)
        else:
            logger.error("未找到 wget 或 curl，无法下载")
            return False

        elapsed = time.time() - start_time

        if success:
            # 验证文件是否真的存在且有内容
            if not dest.exists():
                logger.error(f"下载命令返回成功，但文件不存在: {dest}")
                return False

            file_size = dest.stat().st_size
            if file_size == 0:
                logger.error(f"下载的文件大小为 0: {dest}")
                dest.unlink()
                return False

            size_mb = file_size / (1024 * 1024)
            speed_mbps = size_mb / elapsed if elapsed > 0 else 0
            logger.info(f"下载完成: {size_mb:.2f} MB, 耗时 {elapsed:.1f}s, 速度 {speed_mbps:.2f} MB/s")
        else:
            logger.error(f"下载失败: {url}")
            # 清理可能残留的临时文件
            if temp_dest.exists():
                temp_dest.unlink()
            if dest.exists():
                dest.unlink()

        return success


class PackageManager:
    """
    安装包管理器

    负责管理所有安装包的下载、缓存、校验和分发。

    分发策略:
    - download_url: 在登录服务器下载 → 分发到GPU节点
    - local_file: 从本机上传到登录服务器 → 分发到GPU节点
    - 智能跳过: 登录服务器同时是GPU节点时跳过本机传输
    """

    # 临时文件后缀
    TEMP_SUFFIX = ".downloading"

    def __init__(self,
                 cache_dir: str = "/tmp/gpu-deploy/cache",
                 ssh_manager=None,
                 config=None,
                 logger: Optional[logging.Logger] = None):
        """
        初始化包管理器

        Args:
            cache_dir: 登录服务器上的缓存目录
            ssh_manager: SSH管理器，用于分发文件到节点
            config: 集群配置，用于获取节点认证信息
            logger: 日志器
        """
        self.cache_dir = Path(cache_dir)
        self.ssh_manager = ssh_manager
        self.config = config
        self.logger = logger or logging.getLogger(__name__)
        self.downloader = PackageDownloader(cache_dir)

        # 状态跟踪
        self._prepared_on_jumphost: Dict[str, bool] = {}  # 包是否已在登录服务器准备就绪
        self._distributed: Dict[str, Set[str]] = {}  # 包已分发到的节点集合

    def _get_node_auth(self, host: str) -> tuple:
        """获取节点认证信息"""
        username = None
        password = None

        # 从节点配置获取
        if self.config:
            for node in getattr(self.config, 'nodes', []):
                if node.ip == host or node.hostname == host:
                    if hasattr(node, 'username') and node.username:
                        username = node.username
                    if hasattr(node, 'password') and node.password:
                        password = node.password
                    break

            # 从 jumphost.node_auth 获取默认认证
            if (username is None or password is None) and hasattr(self.config, 'jumphost') and self.config.jumphost:
                if hasattr(self.config.jumphost, 'node_auth') and self.config.jumphost.node_auth:
                    if username is None:
                        username = self.config.jumphost.node_auth.username
                    if password is None:
                        password = self.config.jumphost.node_auth.password

        # 默认用户名
        if username is None:
            username = "ubuntu"

        return username, password

    def _get_jumphost_info(self) -> tuple:
        """
        获取登录服务器信息

        Returns:
            tuple: (jumphost_ip, jumphost_username, jumphost_password)
        """
        jumphost_ip = None
        jumphost_username = "ubuntu"
        jumphost_password = None

        if self.config and hasattr(self.config, 'jumphost') and self.config.jumphost:
            jumphost_ip = self.config.jumphost.host
            jumphost_username = self.config.jumphost.username or "ubuntu"
            jumphost_password = self.config.jumphost.password

        return jumphost_ip, jumphost_username, jumphost_password

    def _is_jumphost_also_gpu_node(self, jumphost_ip: str, gpu_hosts: List[str]) -> bool:
        """
        检查登录服务器是否同时也是GPU节点

        Args:
            jumphost_ip: 登录服务器IP
            gpu_hosts: GPU节点IP列表

        Returns:
            bool: 登录服务器是否是GPU节点
        """
        if not jumphost_ip:
            return False
        return jumphost_ip in gpu_hosts

    def _check_file_on_jumphost(self, filepath: str, skip_temp: bool = True) -> bool:
        """
        检查登录服务器上文件是否存在

        Args:
            filepath: 登录服务器上的文件路径
            skip_temp: 是否跳过临时文件（只有正式文件才算存在）

        Returns:
            bool: 文件是否存在
        """
        if not self.ssh_manager or not self.ssh_manager.jump_client:
            # 没有跳转服务器，程序在登录服务器上运行
            if skip_temp:
                # 只有正式文件存在才算存在，临时文件不算
                return Path(filepath).exists() and not Path(str(filepath) + self.TEMP_SUFFIX).exists()
            return Path(filepath).exists()

        # 检查正式文件
        check_cmd = f"test -f {filepath} && echo 'exists' || echo 'not_found'"
        stdin, stdout, stderr = self.ssh_manager.jump_client.exec_command(check_cmd)
        result = stdout.read().decode().strip()

        if result != "exists":
            return False

        # 如果需要跳过临时文件，检查是否存在临时文件
        if skip_temp:
            temp_path = filepath + self.TEMP_SUFFIX
            check_temp_cmd = f"test -f {temp_path} && echo 'has_temp' || echo 'no_temp'"
            stdin, stdout, stderr = self.ssh_manager.jump_client.exec_command(check_temp_cmd)
            temp_result = stdout.read().decode().strip()
            # 如果存在临时文件，说明上次下载可能中断，不算完成
            if temp_result == "has_temp":
                self.logger.warning(f"[登录服务器] 检测到未完成的下载临时文件: {temp_path}")
                return False

        return True

    def _download_on_jumphost(self, package: PackageConfig) -> tuple:
        """
        在登录服务器上下载安装包（download_url模式）

        Args:
            package: 安装包配置

        Returns:
            tuple: (是否成功, 登录服务器上的文件路径)
        """
        cache_key = f"download:{package.name}"
        jumphost_path = package.jumphost_tmp_path

        # 检查是否已下载
        if self._prepared_on_jumphost.get(cache_key):
            if self._check_file_on_jumphost(jumphost_path):
                self.logger.info(f"[登录服务器] 文件已存在: {jumphost_path}")
                return True, jumphost_path

        # 检查登录服务器是否已有文件
        if self._check_file_on_jumphost(jumphost_path):
            self.logger.info(f"[登录服务器] 文件已存在，跳过下载: {jumphost_path}")
            self._prepared_on_jumphost[cache_key] = True
            return True, jumphost_path

        if not package.download_url:
            self.logger.error(f"未配置 download_url，无法下载: {package.name}")
            return False, None

        # 在登录服务器上执行下载
        self.logger.info(f"[登录服务器] 开始下载: {package.name} v{package.version}")
        self.logger.info(f"[登录服务器] 下载地址: {package.download_url}")
        self.logger.info(f"[登录服务器] 目标路径: {jumphost_path}")

        if not self.ssh_manager or not self.ssh_manager.jump_client:
            # 没有跳转服务器，程序在登录服务器上运行，直接本地下载
            self.logger.info("[登录服务器] 程序在登录服务器上运行，直接本地下载")
            success = self.downloader.download(
                package.download_url,
                Path(jumphost_path)
            )
            if success:
                self._prepared_on_jumphost[cache_key] = True
                return True, jumphost_path
            return False, None

        # 通过SSH在登录服务器上执行下载命令
        # 先检查登录服务器上的下载工具
        check_wget = "which wget >/dev/null 2>&1 && echo 'wget' || echo 'no_wget'"
        check_curl = "which curl >/dev/null 2>&1 && echo 'curl' || echo 'no_curl'"

        stdin, stdout, stderr = self.ssh_manager.jump_client.exec_command(check_wget)
        has_wget = stdout.read().decode().strip() == "wget"

        stdin, stdout, stderr = self.ssh_manager.jump_client.exec_command(check_curl)
        has_curl = stdout.read().decode().strip() == "curl"

        if not has_wget and not has_curl:
            self.logger.error("[登录服务器] 未找到 wget 或 curl，无法下载")
            return False, None

        # 创建下载监控脚本（在登录服务器上执行）
        # 使用临时文件机制：先下载到 .downloading 文件，完成后重命名
        stall_timeout = 300  # 5分钟无增长则超时
        temp_path = f"{jumphost_path}.downloading"
        monitor_script = f'''
set -e

DEST_FILE="{jumphost_path}"
TEMP_FILE="{temp_path}"
URL="{package.download_url}"
STALL_TIMEOUT={stall_timeout}

# 检查并清理可能存在的临时文件（上次未完成的下载）
if [ -f "$TEMP_FILE" ]; then
    echo "WARN: 检测到未完成的下载临时文件，清理后重新下载"
    rm -f "$TEMP_FILE"
fi

# 如果目标文件已存在，跳过下载
if [ -f "$DEST_FILE" ] && [ -s "$DEST_FILE" ]; then
    echo "SUCCESS: 文件已存在，跳过下载"
    exit 0
fi

# 启动下载到临时文件（不设置超时，由监控脚本控制）
# wget: --timeout=0 表示不超时，或设置很大的值
# curl: 不设置 --max-time，让下载自然进行
if [ "{has_wget}" = "True" ] || [ "{has_wget}" = "wget" ]; then
    # 不设置timeout，让监控脚本控制超时
    wget -c -O "$TEMP_FILE" --timeout=0 --tries=0 "$URL" 2>/dev/null &
else
    curl -L -C - -o "$TEMP_FILE" --connect-timeout 60 --retry 0 -f "$URL" 2>/dev/null &
fi
DOWNLOAD_PID=$!

# 监控文件增长
LAST_SIZE=0
LAST_PROGRESS=$(date +%s)
START_TIME=$(date +%s)

while kill -0 $DOWNLOAD_PID 2>/dev/null; do
    if [ -f "$TEMP_FILE" ]; then
        CURRENT_SIZE=$(stat -c%s "$TEMP_FILE" 2>/dev/null || echo 0)
        CURRENT_TIME=$(date +%s)

        if [ "$CURRENT_SIZE" -gt "$LAST_SIZE" ]; then
            LAST_SIZE=$CURRENT_SIZE
            LAST_PROGRESS=$CURRENT_TIME
            # 每100MB打印进度
            if [ $((CURRENT_SIZE / 104857600)) -ne $((LAST_SIZE / 104857600)) ]; then
                echo "PROGRESS: $((CURRENT_SIZE / 1048576)) MB"
            fi
        else
            # 检查停滞超时
            STALLED=$((CURRENT_TIME - LAST_PROGRESS))
            if [ "$STALLED" -gt "$STALL_TIMEOUT" ]; then
                echo "ERROR: 下载停滞超时 ($STALL_TIMEOUT 秒无数据增长)"
                echo "ERROR: 已下载 $((LAST_SIZE / 1048576)) MB"
                echo "ERROR: 建议: 检查网络连接或使用其他下载源"
                kill $DOWNLOAD_PID 2>/dev/null || true
                rm -f "$TEMP_FILE"
                exit 1
            fi
        fi
    fi
    sleep 2
done

# 检查下载结果
wait $DOWNLOAD_PID
EXIT_CODE=$?

if [ $EXIT_CODE -ne 0 ]; then
    echo "ERROR: 下载进程退出码: $EXIT_CODE"
    rm -f "$TEMP_FILE"
    exit 1
fi

if [ ! -f "$TEMP_FILE" ] || [ ! -s "$TEMP_FILE" ]; then
    echo "ERROR: 下载后临时文件不存在或为空"
    rm -f "$TEMP_FILE"
    exit 1
fi

# 下载成功，重命名临时文件为目标文件
mv "$TEMP_FILE" "$DEST_FILE"
if [ $? -ne 0 ]; then
    echo "ERROR: 重命名临时文件失败"
    rm -f "$TEMP_FILE"
    exit 1
fi

FINAL_SIZE=$(stat -c%s "$DEST_FILE")
echo "SUCCESS: 下载完成 $((FINAL_SIZE / 1048576)) MB"
exit 0
'''

        self.logger.info(f"[登录服务器] 执行下载（智能监控模式，停滞超时: {stall_timeout}秒）...")
        self.logger.info(f"[登录服务器] 下载地址: {package.download_url}")

        stdin, stdout, stderr = self.ssh_manager.jump_client.exec_command(monitor_script, timeout=7200)

        # 实时读取输出
        output_lines = []
        while True:
            line = stdout.readline()
            if not line and stdout.channel.recv_exit_status() != -1:
                break
            if line:
                line = line.strip()
                output_lines.append(line)
                if line.startswith("PROGRESS:"):
                    self.logger.info(f"[登录服务器] 📥 {line}")
                elif line.startswith("ERROR:"):
                    self.logger.error(f"[登录服务器] ❌ {line}")
                elif line.startswith("SUCCESS:"):
                    self.logger.info(f"[登录服务器] ✅ {line}")

        exit_code = stdout.channel.recv_exit_status()

        if exit_code != 0:
            err_output = stderr.read().decode()
            self.logger.error(f"[登录服务器] 下载失败: exit_code={exit_code}")
            # 打印所有错误输出
            for line in output_lines:
                if "ERROR" in line or "error" in line.lower():
                    self.logger.error(f"[登录服务器] {line}")
            if err_output:
                self.logger.error(f"[登录服务器] stderr: {err_output[:1000]}")
            return False, None

        # 验证文件
        if not self._check_file_on_jumphost(jumphost_path):
            self.logger.error(f"[登录服务器] 下载后文件不存在: {jumphost_path}")
            return False, None

        self.logger.info(f"[登录服务器] 下载成功: {jumphost_path}")
        self._prepared_on_jumphost[cache_key] = True
        return True, jumphost_path

    def _upload_to_jumphost(self, package: PackageConfig) -> tuple:
        """
        从本机上传安装包到登录服务器（local_file模式）

        Args:
            package: 安装包配置

        Returns:
            tuple: (是否成功, 登录服务器上的文件路径)
        """
        cache_key = f"upload:{package.name}"
        jumphost_path = package.jumphost_tmp_path

        if not package.local_file:
            self.logger.error(f"未配置 local_file，无法上传: {package.name}")
            return False, None

        local_path = Path(package.local_file)
        if not local_path.exists():
            self.logger.error(f"本机文件不存在: {package.local_file}")
            return False, None

        # 检查是否已上传
        if self._prepared_on_jumphost.get(cache_key):
            if self._check_file_on_jumphost(jumphost_path):
                self.logger.info(f"[登录服务器] 文件已存在: {jumphost_path}")
                return True, jumphost_path

        # 检查登录服务器是否已有文件
        if self._check_file_on_jumphost(jumphost_path):
            self.logger.info(f"[登录服务器] 文件已存在，跳过上传: {jumphost_path}")
            self._prepared_on_jumphost[cache_key] = True
            return True, jumphost_path

        self.logger.info(f"[本机] 上传文件到登录服务器: {package.local_file}")
        self.logger.info(f"[本机] 本地路径: {package.local_file}")
        self.logger.info(f"[本机] 登录服务器路径: {jumphost_path}")

        # 如果没有跳转服务器，说明程序在登录服务器上运行
        if not self.ssh_manager or not self.ssh_manager.jump_client:
            self.logger.info("[本机] 程序在登录服务器上运行，文件已在正确位置")
            # 检查 local_file 是否就是目标路径
            if local_path.resolve() == Path(jumphost_path).resolve():
                self._prepared_on_jumphost[cache_key] = True
                return True, jumphost_path
            # 否则需要复制
            try:
                import shutil as sh
                sh.copy2(str(local_path), jumphost_path)
                self.logger.info(f"[本机] 文件已复制到: {jumphost_path}")
                self._prepared_on_jumphost[cache_key] = True
                return True, jumphost_path
            except Exception as e:
                self.logger.error(f"[本机] 文件复制失败: {e}")
                return False, None

        # 上传到登录服务器
        try:
            sftp = self.ssh_manager.jump_client.open_sftp()
            sftp.put(str(local_path), jumphost_path)
            sftp.close()
            self.logger.info(f"[登录服务器] 上传成功: {jumphost_path}")
            self._prepared_on_jumphost[cache_key] = True
            return True, jumphost_path
        except Exception as e:
            self.logger.error(f"[登录服务器] 上传失败: {e}")
            return False, None

    def _distribute_from_jumphost(self, package: PackageConfig, target_host: str, dest_path: str = None) -> tuple:
        """
        从登录服务器分发文件到目标GPU节点

        Args:
            package: 安装包配置
            target_host: 目标GPU节点IP
            dest_path: 目标路径

        Returns:
            tuple: (是否成功, 目标路径)
        """
        dest_path = dest_path or f"/tmp/{package.filename}"
        jumphost_path = package.jumphost_tmp_path

        # 获取目标节点认证信息
        username, password = self._get_node_auth(target_host)

        # 检查目标节点是否已有文件
        check_cmd = f"test -f {dest_path} && echo 'exists' || echo 'not_found'"
        result = self.ssh_manager.execute_on_host(
            target_host, check_cmd,
            username=username,
            password=password
        )
        if "exists" in result.stdout:
            self.logger.info(f"[{target_host}] 文件已存在: {dest_path}")
            return True, dest_path

        # 从登录服务器传输到目标节点
        self.logger.info(f"[登录服务器] -> [{target_host}] 传输文件: {jumphost_path} -> {dest_path}")

        if not self.ssh_manager or not self.ssh_manager.jump_client:
            # 没有跳转服务器，程序在登录服务器上运行
            # 检查目标是否是本机
            import socket
            local_ips = []
            try:
                hostname = socket.gethostname()
                local_ips.append(socket.gethostbyname(hostname))
                for ip in socket.gethostbyname_ex(hostname)[2]:
                    if ip not in local_ips:
                        local_ips.append(ip)
            except:
                pass

            if target_host in local_ips or target_host == "127.0.0.1" or target_host == "localhost":
                self.logger.info(f"[{target_host}] 目标是本机，文件已在正确位置")
                return True, dest_path

            # 直接SSH传输
            conn = self.ssh_manager.get_connection(
                host=target_host,
                username=username,
                password=password
            )
            if conn:
                success = conn.put_file(jumphost_path, dest_path)
                if success:
                    self.logger.info(f"[{target_host}] 传输成功: {dest_path}")
                    return True, dest_path
            return False, None

        # 通过登录服务器SCP传输到目标节点
        # 注意：免密配置完成后，直接使用 scp 即可，不需要 sshpass
        try:
            # 注意：不设置传输超时，让传输自然完成
            # ConnectTimeout 只控制连接建立超时，不影响传输过程
            # 免密配置完成后，使用普通 scp 即可
            scp_cmd = f"scp -o StrictHostKeyChecking=no -o ConnectTimeout=30 -o ServerAliveInterval=30 -o ServerAliveCountMax=3 {jumphost_path} {username}@{target_host}:{dest_path}"

            self.logger.info(f"[登录服务器] 开始SCP传输: {jumphost_path} -> {target_host}:{dest_path}")
            self.logger.debug(f"[登录服务器] SCP命令: {scp_cmd}")

            # exec_command 的 timeout=None 表示不设置超时，让传输自然完成
            stdin, stdout, stderr = self.ssh_manager.jump_client.exec_command(scp_cmd, timeout=None)
            exit_code = stdout.channel.recv_exit_status()

            if exit_code == 0:
                # 验证传输
                verify_cmd = f"test -f {dest_path} && echo 'exists' || echo 'not_found'"
                verify_result = self.ssh_manager.execute_on_host(
                    target_host, verify_cmd,
                    username=username,
                    password=password
                )
                if "exists" in verify_result.stdout:
                    self.logger.info(f"[{target_host}] 传输成功: {dest_path}")
                    return True, dest_path
                else:
                    self.logger.error(f"[{target_host}] 传输后文件不存在")
                    return False, None
            else:
                err_output = stderr.read().decode()
                self.logger.error(f"[{target_host}] SCP失败: exit_code={exit_code}")
                if err_output:
                    self.logger.error(f"[{target_host}] 错误: {err_output[:500]}")
                return False, None

        except Exception as e:
            self.logger.error(f"[{target_host}] 传输异常: {e}")
            return False, None

    def check_local_file(self, package: PackageConfig, host: str = None) -> tuple:
        """
        检查节点上是否已有安装包文件

        Args:
            package: 安装包配置
            host: 目标主机（None表示本地/登录服务器）

        Returns:
            tuple: (是否存在, 文件路径)
        """
        # 优先检查配置的 local_file
        if package.local_file:
            if host and self.ssh_manager:
                # 检查远程节点
                username, password = self._get_node_auth(host)
                check_cmd = f"test -f {package.local_file} && echo 'exists' || echo 'not_found'"
                result = self.ssh_manager.execute_on_host(
                    host, check_cmd,
                    username=username,
                    password=password
                )
                if hasattr(result, 'stdout') and "exists" in result.stdout:
                    return True, package.local_file
            else:
                # 检查本地
                if Path(package.local_file).exists():
                    return True, package.local_file

        # 检查默认位置
        default_path = f"/tmp/{package.filename}"
        if host and self.ssh_manager:
            username, password = self._get_node_auth(host)
            check_cmd = f"test -f {default_path} && echo 'exists' || echo 'not_found'"
            self.logger.debug(f"[{host}] 检查文件: {check_cmd}")
            result = self.ssh_manager.execute_on_host(
                host, check_cmd,
                username=username,
                password=password
            )
            self.logger.debug(f"[{host}] 检查结果: stdout={result.stdout!r}, success={result.success}")
            if hasattr(result, 'stdout') and "exists" in result.stdout:
                return True, default_path
        else:
            if Path(default_path).exists():
                return True, default_path

        return False, None

    def prepare_on_jumphost(self, package: PackageConfig) -> tuple:
        """
        在登录服务器上准备安装包

        根据配置选择:
        - download_url: 在登录服务器下载
        - local_file: 从本机上传

        Args:
            package: 安装包配置

        Returns:
            tuple: (是否成功, 登录服务器上的文件路径)
        """
        # 优先使用 local_file（本机文件上传）
        if package.local_file:
            self.logger.info(f"[准备] 使用 local_file 模式: {package.local_file}")
            return self._upload_to_jumphost(package)

        # 其次使用 download_url（登录服务器下载）
        if package.download_url:
            self.logger.info(f"[准备] 使用 download_url 模式: {package.download_url}")
            return self._download_on_jumphost(package)

        # 都没有配置，检查登录服务器默认位置
        jumphost_path = package.jumphost_tmp_path
        if self._check_file_on_jumphost(jumphost_path):
            self.logger.info(f"[登录服务器] 文件已存在于默认位置: {jumphost_path}")
            return True, jumphost_path

        self.logger.error(f"无法准备安装包: 未配置 download_url 或 local_file，且登录服务器默认位置无文件")
        return False, None

    def distribute_to_host(self, package: PackageConfig, host: str, dest_path: str = None,
                           jumphost_ip: str = None) -> tuple:
        """
        将安装包分发到目标GPU节点

        Args:
            package: 安装包配置
            host: 目标GPU节点IP
            dest_path: 目标路径
            jumphost_ip: 登录服务器IP（用于判断是否跳过）

        Returns:
            tuple: (是否成功, 目标路径)
        """
        dest_path = dest_path or f"/tmp/{package.filename}"

        # 如果目标节点就是登录服务器，检查文件是否已存在
        if jumphost_ip and host == jumphost_ip:
            self.logger.info(f"[{host}] 目标节点是登录服务器，检查文件...")
            if self._check_file_on_jumphost(dest_path):
                self.logger.info(f"[{host}] 文件已存在: {dest_path}")
                return True, dest_path
            # 文件在登录服务器的 /tmp，直接返回
            jumphost_path = package.jumphost_tmp_path
            if self._check_file_on_jumphost(jumphost_path):
                self.logger.info(f"[{host}] 登录服务器文件已准备: {jumphost_path}")
                return True, jumphost_path

        # 从登录服务器分发到目标节点
        return self._distribute_from_jumphost(package, host, dest_path)

    def distribute_to_hosts(self,
                            package: PackageConfig,
                            hosts: List[str],
                            dest_path: str = None,
                            parallel: bool = True,
                            progress_callback: Optional[Callable] = None) -> Dict[str, tuple]:
        """
        批量分发安装包到多个GPU节点

        Args:
            package: 安装包配置
            hosts: 目标GPU节点列表
            dest_path: 目标路径
            parallel: 是否并行分发
            progress_callback: 进度回调函数

        Returns:
            Dict[str, tuple]: {host: (success, path)}
        """
        results = {}
        dest_path = dest_path or f"/tmp/{package.filename}"

        # 获取登录服务器信息
        jumphost_ip, _, _ = self._get_jumphost_info()

        self.logger.info(f"开始分发安装包到 {len(hosts)} 个节点: {package.filename}")

        # 1. 在登录服务器准备文件
        success, jumphost_path = self.prepare_on_jumphost(package)
        if not success:
            self.logger.error("登录服务器准备文件失败")
            for host in hosts:
                results[host] = (False, None)
            return results

        # 2. 分发到各GPU节点
        if parallel and len(hosts) > 1:
            # 并行分发
            from concurrent.futures import ThreadPoolExecutor, as_completed

            with ThreadPoolExecutor(max_workers=min(4, len(hosts))) as executor:
                futures = {
                    executor.submit(self.distribute_to_host, package, host, dest_path, jumphost_ip): host
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
                success, path = self.distribute_to_host(package, host, dest_path, jumphost_ip)
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
        2. 在登录服务器准备文件（download_url下载 或 local_file上传）
        3. 从登录服务器分发到GPU节点
        4. 登录服务器同时是GPU节点时跳过本机传输

        Args:
            package: 安装包配置
            hosts: 目标GPU节点列表
            dest_path: 目标路径
            parallel: 是否并行分发

        Returns:
            Dict[str, str]: {host: 文件路径}，失败的节点值为 None
        """
        results = {}
        hosts_need_distribute = []

        # 获取登录服务器信息
        jumphost_ip, _, _ = self._get_jumphost_info()

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

        # 2. 在登录服务器准备文件
        success, jumphost_path = self.prepare_on_jumphost(package)
        if not success:
            for host in hosts_need_distribute:
                results[host] = None
            return results

        # 3. 分发到需要的节点
        distribute_results = self.distribute_to_hosts(
            package, hosts_need_distribute, dest_path, parallel
        )
        for host, (success, path) in distribute_results.items():
            results[host] = path if success else None

        return results

    def clear_cache(self, package: PackageConfig = None):
        """清理缓存"""
        if package:
            # 清理登录服务器缓存
            jumphost_path = package.jumphost_tmp_path
            if self.ssh_manager and self.ssh_manager.jump_client:
                self.ssh_manager.jump_client.exec_command(f"rm -f {jumphost_path}")
                self.logger.info(f"[登录服务器] 已清理: {jumphost_path}")
            else:
                if Path(jumphost_path).exists():
                    Path(jumphost_path).unlink()
                    self.logger.info(f"[本机] 已清理: {jumphost_path}")

            self._prepared_on_jumphost.pop(package.name, None)
        else:
            # 清理所有缓存
            if self.ssh_manager and self.ssh_manager.jump_client:
                self.ssh_manager.jump_client.exec_command("rm -rf /tmp/gpu-deploy/cache")
                self.logger.info("[登录服务器] 已清理所有缓存")
            else:
                if self.cache_dir.exists():
                    shutil.rmtree(self.cache_dir)
                    self.logger.info(f"[本机] 已清理所有缓存: {self.cache_dir}")

            self._prepared_on_jumphost.clear()
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
