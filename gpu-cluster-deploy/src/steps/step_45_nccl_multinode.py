"""
步骤45: NCCL多节点通信测试

使用OpenMPI + NCCL进行多节点多卡通信性能测试
支持模式:
- all: 所有节点一起测试（每节点1卡或全卡）
- pairwise: 两两节点配对测试
- each_1gpu: 每个节点只用1张GPU测试（默认）
"""

import os
import time
from typing import List, Optional, Dict
from src.steps.base import BaseStep, StepResult, StepStatus


class NCCLMultiNodeTest(BaseStep):
    """NCCL多节点通信测试"""

    step_id = "45"
    step_name = "NCCL多节点测试"
    step_description = "使用OpenMPI进行多节点NCCL通信性能测试（每节点使用全部GPU，最少1卡）"
    requires_sudo = True
    supports_batch = False
    can_skip = True
    timeout = 3600  # 60分钟（含编译时间）

    TEST_ITEMS = ['all_reduce_perf', 'all_gather_perf', 'alltoall_perf']

    def _get_test_config(self):
        if hasattr(self, 'versions') and self.versions and hasattr(self.versions, 'test_packages'):
            return self.versions.test_packages
        return None

    def _get_build_dir(self) -> str:
        config = self._get_test_config()
        return config.build_dir if config else "/tmp/gpu-test-build"

    def _get_toolkit_dir(self) -> str:
        config = self._get_test_config()
        return config.toolkit_dir if config else "/ssd/nfs/gpu-test/toolkit"

    def _get_result_dir(self) -> str:
        config = self._get_test_config()
        return config.result_dir if config else "/ssd/nfs/gpu-test/result"

    def _get_log_dir(self) -> str:
        config = self._get_test_config()
        return config.log_dir if config else "/ssd/nfs/gpu-test/logs"

    def _get_nccl_test_size(self) -> str:
        config = self._get_test_config()
        if config:
            return config.nccl_test_size
        return "8G"

    def _get_compile_jobs_arg(self) -> str:
        """获取编译并行参数，-jN 或 -j$(nproc)"""
        config = self._get_test_config()
        if config and config.compile_jobs:
            return f"-j{config.compile_jobs}"
        return "-j$(nproc)"

    def _get_compile_strategy(self) -> str:
        config = self._get_test_config()
        return config.compile_strategy if config else "single_node"

    def _get_compile_role(self) -> str:
        config = self._get_test_config()
        return config.compile_role if config else "test_compile"

    def _get_gpu_count(self, host: str) -> int:
        count_cmd = "nvidia-smi --query-gpu=count --format=csv,noheader | head -1"
        result = self.execute_on_host(host, count_cmd)
        if result.get("success"):
            return int(result.get("stdout", "0").strip())
        return 0

    def _get_compute_cap(self, host: str) -> Optional[int]:
        cap_cmd = "nvidia-smi --query-gpu=compute_cap --format=csv,noheader | head -1"
        cap_result = self.execute_on_host(host, cap_cmd)
        if cap_result.get("success"):
            cap_str = cap_result.get("stdout", "").strip().replace(".", "")
            return int(cap_str) if cap_str.isdigit() else None
        return None

    def _get_compile_hosts(self, hosts: List[str]) -> List[str]:
        strategy = self._get_compile_strategy()
        if strategy == "local":
            return hosts
        elif strategy == "single_node":
            return [hosts[0]] if hosts else []
        elif strategy == "role_based":
            compile_role = self._get_compile_role()
            compile_hosts = []
            for host in hosts:
                node = self._get_node_config(host)
                if node and hasattr(node, 'roles') and compile_role in node.roles:
                    compile_hosts.append(host)
            if not compile_hosts and hosts:
                self.logger.warning(f"没有节点具有 '{compile_role}' 角色，使用第一个节点编译")
                compile_hosts = [hosts[0]]
            return compile_hosts
        return [hosts[0]] if hosts else []

    def _get_hostname(self, host: str) -> str:
        result = self.execute_on_host(host, "hostname")
        return result.get("stdout", host).strip()

    def _detect_ib_devices(self, host: str) -> List[Dict]:
        """检测IB/RoCE设备信息，返回设备列表

        每个设备包含: device, port, rate, phys_state, link_layer, netdev
        """
        cmd = "ibstatus 2>/dev/null"
        result = self.execute_on_host(host, cmd)
        if not result.get("success") or not result.get("stdout", "").strip():
            return []

        devices = []
        current = {}
        for line in result.get("stdout", "").splitlines():
            line = line.strip()
            if line.startswith("Infiniband device"):
                if current and current.get("device"):
                    devices.append(current)
                # "Infiniband device 'mlx5_0' port 1:"
                parts = line.replace("'", "").replace(":", "").split()
                current = {"device": parts[2] if len(parts) > 2 else "", "port": parts[4] if len(parts) > 4 else "1"}
            elif "Rate:" in line:
                current["rate"] = line.split(":")[-1].strip()
            elif "Physical state:" in line:
                current["phys_state"] = line.split(":")[-1].strip()
            elif "Link layer:" in line:
                current["link_layer"] = line.split(":")[-1].strip().lower()
        if current and current.get("device"):
            devices.append(current)

        # 补充netdev信息: ib设备 -> 以太网卡名映射
        if devices:
            netdev_cmd = "rdma link 2>/dev/null"
            netdev_result = self.execute_on_host(host, netdev_cmd)
            if netdev_result.get("success") and netdev_result.get("stdout", "").strip():
                # 输出格式: link mlx5_0/1 active mlx5_0
                for line in netdev_result.get("stdout", "").splitlines():
                    parts = line.strip().split()
                    if len(parts) >= 5:
                        dev_port = parts[1]  # mlx5_0/1
                        netdev = parts[4]    # 对应的网卡名
                        dev_name = dev_port.split("/")[0]
                        for d in devices:
                            if d["device"] == dev_name:
                                d["netdev"] = netdev

        return devices

    def _detect_active_ib_hcas(self, host: str) -> List[Dict]:
        """获取活跃的IB设备列表(Active状态)，按速率降序

        返回: [{"device": "mlx5_0", "port": "1", "rate": "100", "link_layer": "infiniband", "netdev": ""}, ...]
        """
        devices = self._detect_ib_devices(host)
        active = [d for d in devices if d.get("phys_state", "").lower() == "linkup" or d.get("phys_state", "").lower().startswith("active")]

        if not active:
            # 放宽条件：state包含Active
            active = [d for d in devices if "active" in d.get("phys_state", "").lower() or "linkup" in d.get("phys_state", "").lower()]

        if not active:
            # 再放宽：只要有设备就用
            active = devices

        # 按速率降序排列
        def sort_key(d):
            try:
                return int(d.get("rate", "0"))
            except ValueError:
                return 0
        active.sort(key=sort_key, reverse=True)
        return active

    def _detect_ethernet_ifaces(self, host: str, target_ip: str = None) -> Optional[str]:
        """检测节点间通信使用的以太网卡名称

        优先级:
        1. cluster.yaml network.compute.interfaces 配置
        2. 根据节点IP反查网卡
        3. 根据节点间连通的子网自动选择（排除lo/docker等）
        """
        # 1. 优先从cluster config获取compute网络接口
        if hasattr(self, 'config') and self.config and hasattr(self.config, 'network'):
            network = self.config.network
            compute_ifaces = network.get_network_interfaces('compute')
            if compute_ifaces:
                # 验证接口在远端存在
                for iface in compute_ifaces:
                    check = self.execute_on_host(host, f"ip link show {iface} 2>/dev/null | grep -q 'state UP' && echo 'up' || echo 'down'")
                    if check.get("stdout", "").strip() == "up":
                        self.logger.info(f"[{host}] 使用配置的compute网络接口: {iface}")
                        return iface

        # 2. 根据节点IP反查网卡
        node = self._get_node_config(host)
        ip_to_match = target_ip or (node.ip if node and hasattr(node, 'ip') else None)
        if ip_to_match:
            # 匹配IP所在网卡的接口
            iface_cmd = f"ip -o addr show | grep '{ip_to_match}/' | awk '{{print $2}}'"
            iface_result = self.execute_on_host(host, iface_cmd)
            if iface_result.get("success") and iface_result.get("stdout", "").strip():
                iface = iface_result.get("stdout", "").strip().split('\n')[0]
                self.logger.info(f"[{host}] 通过IP {ip_to_match} 匹配到网卡: {iface}")
                return iface

        # 3. 自动选择：找到和其他节点在同一子网的UP状态网卡（排除lo/docker/br/virbr）
        other_ips = []
        if hasattr(self, 'config') and self.config:
            for n in getattr(self.config, 'nodes', []):
                if hasattr(n, 'ip') and n.ip and n.ip != (ip_to_match or ""):
                    other_ips.append(n.ip)

        if other_ips:
            # 找到能ping通其他节点的网卡
            for other_ip in other_ips[:1]:  # 只测试一个
                route_cmd = f"ip route get {other_ip} 2>/dev/null | head -1 | awk '{{print $5}}'"
                route_result = self.execute_on_host(host, route_cmd)
                if route_result.get("success") and route_result.get("stdout", "").strip():
                    iface = route_result.get("stdout", "").strip()
                    if iface and iface != "lo":
                        self.logger.info(f"[{host}] 通过路由表匹配到网卡: {iface} (目标: {other_ip})")
                        return iface

        self.logger.warning(f"[{host}] 无法自动检测通信网卡")
        return None

    def _detect_network_config(self, hosts: List[str]) -> Dict[str, str]:
        """自动检测所有节点的网络配置，返回NCCL环境变量

        检测逻辑:
        1. 检查所有节点是否有活跃的IB/RoCE设备
        2. 如果有IB设备，自动配置NCCL_IB参数和HCA列表
        3. 无论是否有IB，都检测以太网fallback接口(NCCL_SOCKET_IFNAME)
        4. 区分IB(InfiniBand)和RoCE，设置不同的推荐参数
        """
        nccl_env = {}

        # 在所有节点检测IB设备
        all_ib_devices = {}
        has_ib = True
        has_infiniband = False
        has_roce = False

        for host in hosts:
            ib_devs = self._detect_active_ib_hcas(host)
            all_ib_devices[host] = ib_devs
            if not ib_devs:
                has_ib = False
            for dev in ib_devs:
                if dev.get("link_layer") == "infiniband":
                    has_infiniband = True
                elif dev.get("link_layer") == "ethernet":
                    has_roce = True

        if has_ib and all(len(v) > 0 for v in all_ib_devices.values()):
            nccl_env["NCCL_IB_DISABLE"] = "0"

            # 构建HCA列表：取所有节点都有的设备交集端口
            # 格式: mlx5_0:1,mlx5_1:1
            hca_parts = []
            if all_ib_devices:
                first_devs = all_ib_devices[hosts[0]]
                for dev in first_devs:
                    dev_name = dev["device"]
                    port = dev.get("port", "1")
                    # 检查所有节点是否都有这个设备
                    if all(any(d["device"] == dev_name for d in host_devs)
                           for host_devs in all_ib_devices.values()):
                        hca_parts.append(f"{dev_name}:{port}")

                # 如果交集为空，用第一个节点的所有设备
                if not hca_parts:
                    for dev in first_devs:
                        hca_parts.append(f"{dev['device']}:{dev.get('port', '1')}")

            if hca_parts:
                nccl_env["NCCL_IB_HCA"] = ",".join(hca_parts)

            # 根据IB类型设置推荐参数
            if has_infiniband:
                # 原生InfiniBand: 使用DC传输，TC=160优化
                nccl_env["NCCL_IB_GID_INDEX"] = "3"
                nccl_env["NCCL_IB_TC"] = "160"
                self.logger.info("检测到InfiniBand网络，使用IB优化参数(GID_INDEX=3, TC=160)")
            else:
                # RoCE: GID_INDEX通常需要0或1，TC取决于交换机配置
                nccl_env["NCCL_IB_GID_INDEX"] = "0"
                nccl_env["NCCL_IB_TC"] = "0"
                self.logger.info("检测到RoCE网络，使用RoCE优化参数(GID_INDEX=0, TC=0)")

            # 通用IB参数
            nccl_env["NCCL_IB_RETRY_CNT"] = "7"
            nccl_env["NCCL_IB_TIMEOUT"] = "23"
            nccl_env["NCCL_IB_QPS_PER_CONNECTION"] = "4"
            nccl_env["NCCL_NET_GDR_LEVEL"] = "2"
        else:
            nccl_env["NCCL_IB_DISABLE"] = "1"
            ib_status = {self._get_hostname(h): len(v) for h, v in all_ib_devices.items()}
            self.logger.info(f"IB设备不完整或不存在，禁用IB: {ib_status}")

        # 检测以太网接口(用于NCCL_SOCKET_IFNAME和MPI btl_tcp_if_include)
        net_ifaces = {}
        for host in hosts:
            iface = self._detect_ethernet_ifaces(host)
            if iface:
                net_ifaces[host] = iface

        # 检查所有节点是否使用了相同的网卡名
        unique_ifaces = set(net_ifaces.values())
        if len(unique_ifaces) == 1:
            nccl_env["NCCL_SOCKET_IFNAME"] = list(unique_ifaces)[0]
        elif len(unique_ifaces) > 1:
            # 多个不同网卡名，用^分隔
            nccl_env["NCCL_SOCKET_IFNAME"] = "^" + ",".join(sorted(unique_ifaces))
            self.logger.info(f"不同节点使用了不同的网卡名: {dict((self._get_hostname(h), i) for h, i in net_ifaces.items())}")
        else:
            self.logger.warning("无法检测到以太网接口，NCCL_SOCKET_IFNAME未设置")

        # 通用参数
        nccl_env["NCCL_DEBUG"] = "WARN"
        nccl_env["NCCL_ALGO"] = "Ring"
        nccl_env["NCCL_MAX_NCHANNELS"] = "16"
        nccl_env["NCCL_MIN_NCHANNELS"] = "16"
        nccl_env["NCCL_CHECKS_DISABLE"] = "1"

        return nccl_env

    def _upload_and_unzip(self, host: str, local_path: str, toolkit_dir: str, zip_name: str) -> bool:
        """上传并解压工具包"""
        self.execute_on_host(host, f"mkdir -p {toolkit_dir}")

        check_cmd = f"test -d {toolkit_dir}/{zip_name.replace('.zip', '').replace('.tar.gz', '').replace('.tar', '')} && echo 'exists' || echo 'not_exists'"
        check_result = self.execute_on_host(host, check_cmd)
        if check_result.get("stdout", "").strip() == "exists":
            self.logger.info(f"[{host}] {zip_name} 已存在，跳过解压")
            return True

        remote_file = f"{toolkit_dir}/{zip_name}"
        check_file_cmd = f"test -f {remote_file} && echo 'exists' || echo 'not_exists'"
        file_result = self.execute_on_host(host, check_file_cmd)

        if "not_exists" in file_result.get("stdout", ""):
            self.logger.info(f"[{host}] 上传 {zip_name}...")
            upload_result = self.put_file([host], local_path, remote_file)
            if not upload_result.get(host):
                self.logger.error(f"[{host}] 上传 {zip_name} 失败")
                return False

        self.logger.info(f"[{host}] 解压 {zip_name}...")
        if zip_name.endswith('.tar.gz') or zip_name.endswith('.tgz'):
            unzip_cmd = f"cd {toolkit_dir} && tar -zxf {remote_file}"
        elif zip_name.endswith('.zip'):
            unzip_cmd = f"cd {toolkit_dir} && unzip -q {remote_file}"
        else:
            unzip_cmd = f"cd {toolkit_dir} && tar -xf {remote_file}"

        unzip_result = self.execute_on_host(host, unzip_cmd, sudo=True)
        if not unzip_result.get("success"):
            self.logger.error(f"[{host}] 解压 {zip_name} 失败")
            return False
        return True

    # ---- 编译相关 ----

    def _build_openmpi(self, host: str) -> bool:
        """编译安装OpenMPI"""
        toolkit_dir = self._get_toolkit_dir()
        log_dir = self._get_log_dir()
        config = self._get_test_config()
        install_dir = f"{toolkit_dir}/openmpi"

        openmpi_pkg = config.openmpi if config else "openmpi-4.1.8.tar.gz"
        packages_dir = config.packages_dir if config else "packages"

        # 检查是否已安装
        check_cmd = f"test -f {install_dir}/bin/mpirun && echo 'exists' || echo 'not_exists'"
        check_result = self.execute_on_host(host, check_cmd)
        if check_result.get("stdout", "").strip() == "exists":
            self.logger.info(f"[{host}] OpenMPI已编译，跳过")
            return True

        # 上传并解压OpenMPI源码
        local_pkg = os.path.join(os.getcwd(), packages_dir, openmpi_pkg)
        if not os.path.exists(local_pkg):
            self.logger.error(f"[{host}] OpenMPI源码包不存在: {local_pkg}")
            return False

        if not self._upload_and_unzip(host, local_pkg, toolkit_dir, openmpi_pkg):
            return False

        # 获取解压后的目录名
        src_dir_name = openmpi_pkg.replace('.tar.gz', '').replace('.tgz', '')
        src_dir = f"{toolkit_dir}/{src_dir_name}"

        # 编译OpenMPI，直接安装到toolkit_dir
        self.logger.info(f"[{host}] 编译OpenMPI (安装路径: {install_dir})...")
        self.execute_on_host(host, f"mkdir -p {install_dir} {log_dir}")

        configure_cmd = f"cd {src_dir} && ./configure --prefix={install_dir} --with-cuda=/usr/local/cuda --without-fs-gpfs --without-gpfs > {log_dir}/build_openmpi_configure.log 2>&1"
        result = self.execute_on_host(host, configure_cmd, sudo=True, timeout=600)
        if not result.get("success"):
            self.logger.error(f"[{host}] OpenMPI configure失败")
            return False

        make_cmd = f"cd {src_dir} && make {self._get_compile_jobs_arg()} > {log_dir}/build_openmpi_make.log 2>&1"
        result = self.execute_on_host(host, make_cmd, sudo=True, timeout=1200)
        if not result.get("success"):
            self.logger.error(f"[{host}] OpenMPI编译失败")
            return False

        install_cmd = f"cd {src_dir} && make install > {log_dir}/build_openmpi_install.log 2>&1"
        result = self.execute_on_host(host, install_cmd, sudo=True, timeout=600)
        if not result.get("success"):
            self.logger.error(f"[{host}] OpenMPI安装失败")
            return False

        self.logger.info(f"[{host}] OpenMPI编译安装完成")
        return True

    def _build_nccl(self, host: str, compute_cap: int) -> bool:
        """编译NCCL（如果尚未编译）"""
        toolkit_dir = self._get_toolkit_dir()
        log_dir = self._get_log_dir()
        nccl_dir = f"{toolkit_dir}/nccl"

        check_cmd = f"test -f {nccl_dir}/lib/libnccl.so && echo 'exists' || echo 'not_exists'"
        result = self.execute_on_host(host, check_cmd)
        if result.get("stdout", "").strip() == "exists":
            self.logger.info(f"[{host}] NCCL已编译，跳过")
            return True

        config = self._get_test_config()
        packages_dir = config.packages_dir if config else "packages"
        nccl_pkg_name = "nccl-master.zip"
        local_pkg = os.path.join(os.getcwd(), packages_dir, nccl_pkg_name)

        if not os.path.exists(local_pkg):
            self.logger.error(f"[{host}] NCCL源码包不存在: {local_pkg}")
            return False

        if not self._upload_and_unzip(host, local_pkg, toolkit_dir, nccl_pkg_name):
            return False

        src_dir = f"{toolkit_dir}/nccl-master"
        self.execute_on_host(host, f"mkdir -p {nccl_dir} {log_dir}")

        # BUILDDIR直接指向toolkit_dir/nccl，编译产物直接到位
        compile_cmd = f"cd {src_dir} && make {self._get_compile_jobs_arg()} src.build BUILDDIR={nccl_dir} CUDA_HOME=/usr/local/cuda NVCC_GENCODE='-gencode=arch=compute_{compute_cap},code=sm_{compute_cap}' > {log_dir}/build_nccl_multinode.log 2>&1"
        result = self.execute_on_host(host, compile_cmd, sudo=True, timeout=1200)
        if not result.get("success"):
            self.logger.error(f"[{host}] NCCL编译失败")
            return False

        self.logger.info(f"[{host}] NCCL编译完成")
        return True

    def _build_nccl_tests_mpi(self, host: str) -> bool:
        """编译带MPI支持的NCCL-tests，使用独立的源码目录 nccl-tests-mpi"""
        toolkit_dir = self._get_toolkit_dir()
        log_dir = self._get_log_dir()
        mpi_src_dir = f"{toolkit_dir}/nccl-tests-mpi"

        # 检查MPI版本是否已编译
        check_cmd = f"test -f {mpi_src_dir}/build/all_reduce_perf && echo 'exists' || echo 'not_exists'"
        result = self.execute_on_host(host, check_cmd)
        if result.get("stdout", "").strip() == "exists":
            self.logger.info(f"[{host}] NCCL-tests(MPI版)已编译，跳过")
            return True

        config = self._get_test_config()
        packages_dir = config.packages_dir if config else "packages"
        nccl_tests_pkg = "nccl-tests-master.zip"
        local_pkg = os.path.join(os.getcwd(), packages_dir, nccl_tests_pkg)

        if not os.path.exists(local_pkg):
            self.logger.error(f"[{host}] NCCL-tests源码包不存在: {local_pkg}")
            return False

        # 上传并解压到独立的 nccl-tests-mpi 目录
        self.execute_on_host(host, f"mkdir -p {toolkit_dir}")

        remote_zip = f"{toolkit_dir}/{nccl_tests_pkg}"
        check_zip = f"test -f {remote_zip} && echo 'exists' || echo 'not_exists'"
        zip_result = self.execute_on_host(host, check_zip)

        if "not_exists" in zip_result.get("stdout", ""):
            self.logger.info(f"[{host}] 上传 {nccl_tests_pkg}...")
            upload_result = self.put_file([host], local_pkg, remote_zip)
            if not upload_result.get(host):
                self.logger.error(f"[{host}] 上传 {nccl_tests_pkg} 失败")
                return False

        # 解压到临时目录后复制为 nccl-tests-mpi
        self.logger.info(f"[{host}] 解压 {nccl_tests_pkg} 到 {mpi_src_dir}...")
        tmp_dir = f"{toolkit_dir}/nccl-tests-mpi-tmp"
        self.execute_on_host(host, f"rm -rf {tmp_dir} {mpi_src_dir}")
        unzip_cmd = f"cd {toolkit_dir} && unzip -q {remote_zip} -d {tmp_dir}"
        unzip_result = self.execute_on_host(host, unzip_cmd, sudo=True)
        if not unzip_result.get("success"):
            self.logger.error(f"[{host}] 解压 {nccl_tests_pkg} 失败")
            return False

        # unzip 会创建 nccl-tests-master 子目录，重命名为 nccl-tests-mpi
        rename_cmd = f"mv {tmp_dir}/nccl-tests-master {mpi_src_dir} && rm -rf {tmp_dir}"
        rename_result = self.execute_on_host(host, rename_cmd, sudo=True)
        if not rename_result.get("success"):
            self.logger.error(f"[{host}] 重命名 nccl-tests-master -> nccl-tests-mpi 失败")
            return False

        self.execute_on_host(host, f"mkdir -p {log_dir}")

        # 使用OpenMPI编译NCCL-tests
        openmpi_dir = f"{toolkit_dir}/openmpi"
        compile_cmd = f"cd {mpi_src_dir} && make {self._get_compile_jobs_arg()} MPI=1 MPI_HOME={openmpi_dir} CUDA_HOME=/usr/local/cuda NCCL_HOME={toolkit_dir}/nccl > {log_dir}/build_nccl_tests_mpi.log 2>&1"
        result = self.execute_on_host(host, compile_cmd, sudo=True, timeout=600)
        if not result.get("success"):
            self.logger.error(f"[{host}] NCCL-tests(MPI版)编译失败")
            return False

        self.logger.info(f"[{host}] NCCL-tests(MPI版)编译完成")
        return True

    def _compile_all(self, hosts: List[str]) -> Dict[str, bool]:
        """在编译节点编译所有需要的工具"""
        compile_hosts = self._get_compile_hosts(hosts)
        self.logger.info(f"编译策略: {self._get_compile_strategy()}, 编译节点: {compile_hosts}")

        compile_results = {}
        for host in compile_hosts:
            self.logger.info(f"[{host}] 开始编译多节点测试所需工具...")

            compute_cap = self._get_compute_cap(host)
            if not compute_cap:
                compile_results[host] = False
                self.logger.error(f"[{host}] 无法获取GPU计算能力")
                continue

            self.logger.info(f"[{host}] 计算能力: {compute_cap}")

            # 1. 编译OpenMPI
            if not self._build_openmpi(host):
                compile_results[host] = False
                continue

            # 2. 编译NCCL
            if not self._build_nccl(host, compute_cap):
                compile_results[host] = False
                continue

            # 3. 编译NCCL-tests (MPI版本)
            if not self._build_nccl_tests_mpi(host):
                compile_results[host] = False
                continue

            compile_results[host] = True

        return compile_results

    def _ensure_tools_on_all_nodes(self, hosts: List[str]) -> bool:
        """确保所有节点都能访问编译好的工具（通过NFS共享）"""
        toolkit_dir = self._get_toolkit_dir()

        for host in hosts:
            check_cmd = f"test -f {toolkit_dir}/nccl-tests-mpi/build/all_reduce_perf && test -f {toolkit_dir}/openmpi/bin/mpirun && echo 'ready' || echo 'not_ready'"
            result = self.execute_on_host(host, check_cmd)
            if result.get("stdout", "").strip() != "ready":
                self.logger.error(f"[{host}] 工具不可用(OpenMPI或NCCL-tests缺失)，无法执行多节点测试")
                return False

        return True

    def _generate_hostfile(self, hosts: List[str], gpus_per_node: int) -> str:
        """生成MPI hostfile内容，使用IP地址确保跨节点可解析"""
        lines = []
        for host in hosts:
            node = self._get_node_config(host)
            addr = node.ip if node and hasattr(node, 'ip') and node.ip else host
            lines.append(f"{addr} slots={gpus_per_node}")
        return "\n".join(lines)

    def _run_mpirun_test(self, run_hosts: List[str], gpus_per_node: int,
                         test_item: str, result_dir: str, label: str) -> Dict:
        """在指定节点上运行mpirun测试"""
        toolkit_dir = self._get_toolkit_dir()
        nccl_test_size = self._get_nccl_test_size()

        # 计算测试数据大小：如果用户未在配置中显式指定（使用默认值8G），则根据GPU算力自动调整
        first_host = run_hosts[0]
        compute_cap = self._get_compute_cap(first_host)
        config = self._get_test_config()
        user_specified = config and config.nccl_test_size != "8G"
        if not user_specified and compute_cap and (compute_cap == 120 or compute_cap == 89):
            nccl_test_size = "2G"

        # 生成hostfile
        hostfile_content = self._generate_hostfile(run_hosts, gpus_per_node)
        hostfile_path = f"{toolkit_dir}/hostfile_{label}"
        self.execute_on_host(first_host, f"cat > {hostfile_path} << 'HOSTFILE_EOF'\n{hostfile_content}\nHOSTFILE_EOF")

        # 检测网络配置
        nccl_env = self._detect_network_config(run_hosts)

        ib_status = '启用' if nccl_env.get('NCCL_IB_DISABLE') == '0' else '禁用'
        ib_type = ''
        if nccl_env.get('NCCL_IB_DISABLE') == '0':
            ib_type = f" (HCA={nccl_env.get('NCCL_IB_HCA', 'auto')}, GID_INDEX={nccl_env.get('NCCL_IB_GID_INDEX', 'auto')}, TC={nccl_env.get('NCCL_IB_TC', 'auto')})"
        self.logger.info(f"[{label}] 网络配置: IB={ib_status}{ib_type}, "
                        f"以太网={nccl_env.get('NCCL_SOCKET_IFNAME', '自动')}")

        total_processes = len(run_hosts) * gpus_per_node
        hostnames = [self._get_hostname(h) for h in run_hosts]
        self.logger.info(f"[{label}] 测试: {test_item}, 节点: {hostnames}, "
                        f"每节点GPU: {gpus_per_node}, 总进程: {total_processes}")

        # 构建mpirun命令
        openmpi_bin = f"{toolkit_dir}/openmpi/bin/mpirun"
        nccl_tests_bin = f"{toolkit_dir}/nccl-tests-mpi/build/{test_item}"

        # LD_LIBRARY_PATH
        ld_path = f"{toolkit_dir}/openmpi/lib:{toolkit_dir}/nccl/lib:/usr/local/cuda/lib64"

        # 构建-x参数
        env_args = []
        for key, val in nccl_env.items():
            env_args.extend(["-x", f"{key}={val}"])

        # MCA参数：根据网络类型配置
        mca_args = ["-mca", "coll_hcoll_enable", "0", "-mca", "pml", "ob1"]
        if nccl_env.get("NCCL_SOCKET_IFNAME"):
            mca_args.extend(["-mca", "btl_tcp_if_include", nccl_env["NCCL_SOCKET_IFNAME"]])
        mca_args.extend(["-mca", "btl", "^openib"])

        cmd_parts = [
            openmpi_bin,
            "-np", str(total_processes),
            "--hostfile", hostfile_path,
            "--allow-run-as-root",
            "-bind-to", "numa",
            "-map-by", "slot",
        ]
        cmd_parts.extend(["-x", f"LD_LIBRARY_PATH={ld_path}"])
        cmd_parts.extend(["-x", "PATH=$PATH"])
        cmd_parts.extend(env_args)
        cmd_parts.extend(mca_args)
        cmd_parts.append(nccl_tests_bin)
        cmd_parts.extend(["-b", "1M", "-e", nccl_test_size, "-f", "2", "-g", str(gpus_per_node)])

        cmd = " ".join(cmd_parts)
        log_file = f"{result_dir}/{test_item}_{label}.log"
        full_cmd = f"{cmd} > {log_file} 2>&1"

        self.logger.info(f"[{label}] 执行: {cmd[:200]}...")

        result = self.execute_on_host(first_host, full_cmd, timeout=1800)

        if result.get("success"):
            # 读取结果摘要
            summary_cmd = f"tail -20 {log_file}"
            summary_result = self.execute_on_host(first_host, summary_cmd)
            summary = summary_result.get("stdout", "")
            self.logger.info(f"[{label}] {test_item} 测试完成")
            return {"success": True, "summary": summary, "log_file": log_file}
        else:
            self.logger.error(f"[{label}] {test_item} 测试失败")
            # 尝试读取错误信息
            error_cmd = f"tail -30 {log_file} 2>/dev/null || echo 'no log'"
            error_result = self.execute_on_host(first_host, error_cmd)
            return {"success": False, "error_log": error_result.get("stdout", "")}

    def execute(self, hosts: List[str]) -> StepResult:
        """执行NCCL多节点测试"""
        if len(hosts) < 2:
            return StepResult(
                step_id=self.step_id,
                step_name=self.step_name,
                status=StepStatus.SKIPPED,
                message="节点数不足2，无法执行多节点测试"
            )

        results = {}
        toolkit_dir = self._get_toolkit_dir()
        result_dir = self._get_result_dir()

        # 1. 编译
        compile_results = self._compile_all(hosts)
        compile_failed = [h for h, ok in compile_results.items() if not ok]
        if compile_failed:
            return StepResult(
                step_id=self.step_id,
                step_name=self.step_name,
                status=StepStatus.FAILED,
                message=f"编译失败: {compile_failed}",
                host_results=compile_results
            )

        # 2. 确保所有节点可访问工具
        if not self._ensure_tools_on_all_nodes(hosts):
            return StepResult(
                step_id=self.step_id,
                step_name=self.step_name,
                status=StepStatus.FAILED,
                message="部分节点无法访问测试工具"
            )

        # 3. 创建结果目录
        for host in hosts:
            self.execute_on_host(host, f"mkdir -p {result_dir}")

        # 4. 获取每节点GPU数，取最小值确保所有节点都能参与
        gpu_counts = {}
        for host in hosts:
            gpu_counts[host] = self._get_gpu_count(host)
            self.logger.info(f"[{host}] GPU数量: {gpu_counts[host]}")

        min_gpu = min(gpu_counts.values()) if gpu_counts else 1
        if min_gpu < 1:
            min_gpu = 1
        self.logger.info(f"各节点GPU最小值: {min_gpu}，将使用每节点{min_gpu}卡进行多节点测试")

        # 5. 执行全节点多GPU测试
        self.logger.info(f"===== 开始全节点多GPU测试 (每节点{min_gpu}卡) =====")

        test_results = {}
        for test_item in self.TEST_ITEMS:
            test_result = self._run_mpirun_test(
                run_hosts=hosts,
                gpus_per_node=min_gpu,
                test_item=test_item,
                result_dir=result_dir,
                label=f"multinode_{min_gpu}gpu"
            )
            test_results[test_item] = test_result

        results[f"multinode_{min_gpu}gpu"] = {
            "success": all(r.get("success") for r in test_results.values()),
            "hosts": [self._get_hostname(h) for h in hosts],
            "gpus_per_node": min_gpu,
            "tests": test_results
        }

        # 6. 执行两两配对测试
        if len(hosts) >= 2:
            self.logger.info(f"===== 开始两两配对测试 (每节点{min_gpu}卡) =====")
            pairwise_results = {}

            for i in range(len(hosts)):
                for j in range(i + 1, len(hosts)):
                    host1_name = self._get_hostname(hosts[i])
                    host2_name = self._get_hostname(hosts[j])
                    pair_key = f"{host1_name}-{host2_name}"

                    # 配对测试取两个节点GPU的较小值
                    pair_gpu = min(gpu_counts.get(hosts[i], 1), gpu_counts.get(hosts[j], 1))
                    self.logger.info(f"配对测试: {pair_key} (每节点{pair_gpu}卡)")
                    pair_test_results = {}
                    for test_item in self.TEST_ITEMS:
                        test_result = self._run_mpirun_test(
                            run_hosts=[hosts[i], hosts[j]],
                            gpus_per_node=pair_gpu,
                            test_item=test_item,
                            result_dir=result_dir,
                            label=f"pair_{host1_name}_{host2_name}_{pair_gpu}gpu"
                        )
                        pair_test_results[test_item] = test_result

                    pairwise_results[pair_key] = {
                        "success": all(r.get("success") for r in pair_test_results.values()),
                        "gpus_per_node": pair_gpu,
                        "tests": pair_test_results
                    }

            results["pairwise"] = pairwise_results

        # 汇总
        all_success = True
        multinode_key = f"multinode_{min_gpu}gpu"
        if not results.get(multinode_key, {}).get("success", False):
            all_success = False
        for pair_key, pair_data in results.get("pairwise", {}).items():
            if not pair_data.get("success", False):
                all_success = False

        return StepResult(
            step_id=self.step_id,
            step_name=self.step_name,
            status=StepStatus.SUCCESS if all_success else StepStatus.FAILED,
            message=f"NCCL多节点测试完成 ({'全部成功' if all_success else '部分失败'})",
            host_results=results
        )

    def is_configured(self, host: str) -> tuple:
        """测试步骤每次都应执行，不跳过"""
        return False, "测试步骤需要执行"

    def post_check(self, hosts: List[str]) -> bool:
        result_dir = self._get_result_dir()
        for host in hosts:
            check_cmd = f"ls {result_dir}/all_reduce_perf_multinode_*gpu.log 2>/dev/null | wc -l | grep -q '[1-9]'"
            result = self.execute_on_host(host, check_cmd)
            if not result.get("success"):
                return False
        return True
