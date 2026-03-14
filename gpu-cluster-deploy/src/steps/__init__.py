"""
部署步骤模块

步骤分类说明:
- SYSTEM: 系统配置 (内核、依赖、系统设置)
- STORAGE: 存储配置 (磁盘挂载、NFS)
- NETWORK: 网络配置 (RDMA、网络驱动)
- GPU: GPU配置 (驱动、CUDA、GPU工具)
- SECURITY: 安全配置 (用户、SSH密钥)
"""

from .base import BaseStep, StepResult, StepStatus

# Step categories for module framework
from enum import Enum


class StepCategory(Enum):
    """Step categories for modular execution."""
    SYSTEM = "system"
    STORAGE = "storage"
    NETWORK = "network"
    GPU = "gpu"
    SECURITY = "security"
    MONITORING = "monitoring"
    CUSTOM = "custom"


# Step metadata including category and tags
STEP_METADATA = {
    # Group A: System checks
    "step_1": {"category": StepCategory.SYSTEM, "tags": ["dependencies", "prerequisites"]},
    "step_2": {"category": StepCategory.SYSTEM, "tags": ["kernel", "os"]},
    "step_3": {"category": StepCategory.SYSTEM, "tags": ["glibc", "libraries"]},
    "step_4": {"category": StepCategory.SYSTEM, "tags": ["ssh", "network"]},
    # Group B: Base configuration
    "step_5": {"category": StepCategory.SECURITY, "tags": ["sudo", "permissions"]},
    "step_6": {"category": StepCategory.STORAGE, "tags": ["disk", "mount", "format"]},
    "step_7": {"category": StepCategory.SYSTEM, "tags": ["msr", "cpu"]},
    "step_8": {"category": StepCategory.SYSTEM, "tags": ["startup", "rc-local"]},
    "step_9": {"category": StepCategory.SYSTEM, "tags": ["hostname", "hosts", "network"]},
    # Group C: User and SSH
    "step_10": {"category": StepCategory.SECURITY, "tags": ["user", "account"]},
    "step_0d": {"category": StepCategory.SECURITY, "tags": ["ssh", "keys", "auth"]},
    "step_12": {"category": StepCategory.SYSTEM, "tags": ["cpu", "performance"]},
    "step_13": {"category": StepCategory.SYSTEM, "tags": ["limits", "ulimit"]},
    # Group D: System optimization
    "step_15": {"category": StepCategory.SYSTEM, "tags": ["update", "package"]},
    "step_16": {"category": StepCategory.SYSTEM, "tags": ["kernel", "lock"]},
    "step_17": {"category": StepCategory.SYSTEM, "tags": ["timezone", "time"]},
    "step_18": {"category": StepCategory.NETWORK, "tags": ["ipv6", "network"]},
    "step_19": {"category": StepCategory.SYSTEM, "tags": ["vmcore", "crash"]},
    # Group E: Network drivers
    "step_20": {"category": StepCategory.NETWORK, "tags": ["rdma", "mlnx", "ofed"]},
    "step_21": {"category": StepCategory.GPU, "tags": ["nvidia", "nouveau", "driver"]},
    "step_22": {"category": StepCategory.GPU, "tags": ["nvidia", "driver", "gpu"]},
    "step_23": {"category": StepCategory.GPU, "tags": ["fabric", "nvlink", "gpu"]},
    # Group F: GPU environment
    "step_24": {"category": StepCategory.GPU, "tags": ["cuda", "toolkit", "gpu"]},
    "step_25": {"category": StepCategory.GPU, "tags": ["nccl", "gpu", "communication"]},
    "step_26": {"category": StepCategory.NETWORK, "tags": ["rdma", "rename", "network"]},
    "step_27": {"category": StepCategory.GPU, "tags": ["persistence", "gpu", "daemon"]},
    "step_28": {"category": StepCategory.GPU, "tags": ["nvidia", "modules", "kernel"]},
    # Group G: Advanced config
    "step_29": {"category": StepCategory.SYSTEM, "tags": ["acs", "pci", "iommu"]},
    "step_30": {"category": StepCategory.SYSTEM, "tags": ["time", "sync", "ntp"]},
    "step_34": {"category": StepCategory.STORAGE, "tags": ["nfs", "mount", "storage"]},
    # Device check (step_0)
    "step_0": {"category": StepCategory.SYSTEM, "tags": ["device", "check", "validation"]},
    # Network connectivity check (step_0b)
    "step_0b": {"category": StepCategory.NETWORK, "tags": ["network", "connectivity", "check"]},
    # RDMA network test (step_0c)
    "step_0c": {"category": StepCategory.NETWORK, "tags": ["rdma", "bandwidth", "test"]},
}


def get_step_category(step_id: str) -> StepCategory:
    """Get the category for a step by its ID."""
    meta = STEP_METADATA.get(step_id, {})
    return meta.get("category", StepCategory.CUSTOM)


def get_step_tags(step_id: str) -> list:
    """Get the tags for a step by its ID."""
    meta = STEP_METADATA.get(step_id, {})
    return meta.get("tags", [])


# Group A: 系统检查类
from .step_1_dependencies import InstallDependencies
from .step_2_kernel_check import KernelCheck, KernelInstall
from .step_3_glibc_check import GlibcCheck
from .step_4_openssh_check import OpenSSHCheck

# Group B: 基础配置类
from .step_5_sudo_nopasswd import SudoNopasswd
from .step_6_disk_mount import DiskMount
from .step_7_msr_settings import MSRSettings
from .step_8_rc_local import RcLocalSetup
from .step_9_hostname_hosts import HostnameHosts

# Group C: 用户与SSH
from .step_10_create_user import CreateUser
from .step_0d_ssh_key import SSHKeySetup
from .step_12_cpu_performance import CPUPerformance
from .step_13_file_limits import FileLimits

# Group D: 系统优化
from .step_15_disable_autoupdate import DisableAutoUpdate
from .step_16_lock_kernel import LockKernel
from .step_17_timezone import TimezoneSetup
from .step_18_disable_ipv6 import DisableIPv6
from .step_19_vmcore_hibernate import VmcoreHibernate

# Group E: 网络驱动
from .step_20_mlnx_ofed import MellanoxDriver
from .step_21_disable_nouveau import DisableNouveau
from .step_22_nvidia_driver import NVIDIADriver
from .step_23_fabricmanager import FabricManager

# Group F: GPU环境
from .step_24_cuda_toolkit import CUDAToolkit
from .step_25_nccl import NCCLInstall
from .step_26_rdma_rename import RDMARename
from .step_27_gpu_persistence import GPUPersistence
from .step_28_nvidia_modules import NVIDIAModules

# Group G: 高级配置
from .step_29_disable_acs import DisableACS
from .step_30_time_sync import TimeSync
from .step_34_nfs_config import NFSConfig

# Device check step
from .step_0_device_check import Step0DeviceCheck

# Network connectivity check step
from .step_0b_network_check import NetworkCheckStep

# RDMA network test step
from .step_0c_network_rdma_test import NetworkRDMATest

# Final verification step
from .step_final_verification import FinalVerification


# 所有步骤类 - 按依赖顺序排列
# 重要：
# 1. SSH免密(step_0d)和hosts(step_9)必须最先配置，后续步骤才能使用pdsh批量执行
# 2. SSH免密使用IP连接，不依赖hosts
# 3. 控制机需要预先安装pdsh
ALL_STEPS = [
    # Phase 0: 设备检查（使用登录用户）
    Step0DeviceCheck,       # step_00: 设备一致性检查
    NetworkCheckStep,       # step_0b: 网络连通性检查
    # Phase 1: 初始化配置（SSH免密优先，为后续pdsh批量执行做准备）
    SSHKeySetup,            # step_0d: 配置SSH免密（使用登录用户）
    HostnameHosts,          # step_09: 配置hosts（使用部署用户免密）
    # --- SSH免密和hosts完成后切换到pdsh模式 ---
    InstallDependencies,    # step_01: 安装依赖（pdsh模式）
    # Phase 2: 系统检查
    KernelCheck,
    KernelInstall,
    GlibcCheck,
    OpenSSHCheck,
    # Phase 3: 系统基础配置
    SudoNopasswd,
    DiskMount,
    MSRSettings,
    RcLocalSetup,
    DisableAutoUpdate,
    LockKernel,
    TimezoneSetup,
    DisableIPv6,
    VmcoreHibernate,
    # Phase 4: 用户和权限配置
    CreateUser,
    CPUPerformance,
    FileLimits,
    # Phase 5: GPU和网络驱动
    MellanoxDriver,
    DisableNouveau,
    NVIDIADriver,
    FabricManager,
    CUDAToolkit,
    NCCLInstall,
    RDMARename,
    GPUPersistence,
    NVIDIAModules,
    # Phase 6: 高级配置
    DisableACS,
    TimeSync,
    NFSConfig,
    # Phase 7: 最终验证
    FinalVerification,
]

# 步骤ID到类的映射
STEP_MAP = {step.step_id: step for step in ALL_STEPS}

__all__ = [
    'BaseStep', 'StepResult', 'StepStatus',
    'StepCategory', 'STEP_METADATA', 'get_step_category', 'get_step_tags',
    'ALL_STEPS', 'STEP_MAP',
    # Device check
    'Step0DeviceCheck',
    # Network check
    'NetworkCheckStep',
    # RDMA network test
    'NetworkRDMATest',
    # Group A
    'InstallDependencies', 'KernelCheck', 'KernelInstall', 'GlibcCheck', 'OpenSSHCheck',
    # Group B
    'SudoNopasswd', 'DiskMount', 'MSRSettings', 'RcLocalSetup', 'HostnameHosts',
    # Group C
    'CreateUser', 'SSHKeySetup', 'CPUPerformance', 'FileLimits',
    # Group D
    'DisableAutoUpdate', 'LockKernel', 'TimezoneSetup', 'DisableIPv6', 'VmcoreHibernate',
    # Group E
    'MellanoxDriver', 'DisableNouveau', 'NVIDIADriver', 'FabricManager',
    # Group F
    'CUDAToolkit', 'NCCLInstall', 'RDMARename', 'GPUPersistence', 'NVIDIAModules',
    # Group G
    'DisableACS', 'TimeSync', 'NFSConfig',
    # Final verification
    'FinalVerification',
]
