"""
部署步骤模块
"""

from .base import BaseStep, StepResult, StepStatus

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
from .step_11_ssh_key import SSHKeySetup
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


# 所有步骤类
ALL_STEPS = [
    # Group A
    InstallDependencies,
    KernelCheck,
    KernelInstall,
    GlibcCheck,
    OpenSSHCheck,
    # Group B
    SudoNopasswd,
    DiskMount,
    MSRSettings,
    RcLocalSetup,
    HostnameHosts,
    # Group C
    CreateUser,
    SSHKeySetup,
    CPUPerformance,
    FileLimits,
    # Group D
    DisableAutoUpdate,
    LockKernel,
    TimezoneSetup,
    DisableIPv6,
    VmcoreHibernate,
    # Group E
    MellanoxDriver,
    DisableNouveau,
    NVIDIADriver,
    FabricManager,
    # Group F
    CUDAToolkit,
    NCCLInstall,
    RDMARename,
    GPUPersistence,
    NVIDIAModules,
    # Group G
    DisableACS,
    TimeSync,
    NFSConfig,
]

# 步骤ID到类的映射
STEP_MAP = {step.step_id: step for step in ALL_STEPS}

__all__ = [
    'BaseStep', 'StepResult', 'StepStatus',
    'ALL_STEPS', 'STEP_MAP',
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
]
