"""网络模块"""

# 模块将包含以下组件:
# - DeviceDiscovery: 设备发现工具类
# - IbdevParser: ibdev2netdev解析器
# - DeviceConsistencyChecker: 设备一致性检查器
# - GPUTopologyChecker: GPU拓扑检查器
# - FixSuggestionGenerator: 修复建议生成器
# - ConnectivityChecker: 网络连通性检查器
# - IPResolver: IP地址解析器
# - RDMADetector: RDMA设备类型检测器
# - IBWriteBWTester: ib_write_bw性能测试器
# - ThreePhaseTester: 三轮测试策略
# - DeploymentVerifier: 部署验证检查器
# - RoCEPingTester: RoCE网络Ping连通性测试器

from .connectivity_checker import (
    ConnectivityChecker,
    CheckType,
    CheckResult,
    HostConnectivityResult,
    generate_connectivity_report
)

from .ip_resolver import IPResolver
from .rdma_detector import RDMADetector, RDMADeviceType, RDMADeviceInfo
from .ibandwidth_tester import IBWriteBWTester, BandwidthTestResult, BandwidthTestConfig
from .three_phase_tester import (
    ThreePhaseTester,
    ThreePhaseReport,
    TestPhase,
    DeviceStatus
)
from .deployment_verifier import (
    DeploymentVerifier,
    DeploymentVerificationReport,
    CheckStatus,
    CheckCategory
)
from .roce_ping_tester import (
    RoCEPingTester,
    PingResult,
    PingTestReport
)

__all__ = [
    'ConnectivityChecker',
    'CheckType',
    'CheckResult',
    'HostConnectivityResult',
    'generate_connectivity_report',
    'IPResolver',
    'RDMADetector',
    'RDMADeviceType',
    'RDMADeviceInfo',
    'IBWriteBWTester',
    'BandwidthTestResult',
    'BandwidthTestConfig',
    'ThreePhaseTester',
    'ThreePhaseReport',
    'TestPhase',
    'DeviceStatus',
    'DeploymentVerifier',
    'DeploymentVerificationReport',
    'CheckStatus',
    'CheckCategory',
    'RoCEPingTester',
    'PingResult',
    'PingTestReport',
]
