"""
步骤25: 安装NCCL通信库
"""

import os
from pathlib import Path
from typing import List
from src.steps.base import BaseStep, StepResult, StepStatus


class NCCLInstall(BaseStep):
    """安装NCCL通信库"""

    step_id = "25"
    step_name = "安装NCCL通信库"
    step_description = "安装NCCL通信库（可选）"
    requires_sudo = True
    supports_batch = False
    can_skip = True
    timeout = 1800  # 30分钟

    def is_configured(self, host: str) -> tuple:
        """
        检查NCCL是否已安装

        Args:
            host: 主机地址

        Returns:
            tuple[bool, str]: (是否已配置, 检查详情)
        """
        nccl_config = self.versions.nccl if hasattr(self, 'versions') and self.versions else None

        if not nccl_config or not nccl_config.enabled:
            # NCCL未启用时，返回False让用户知道实际状态，而不是显示"已配置"
            return False, "NCCL未启用"

        install_path = getattr(nccl_config, 'install_path', '/home/ubuntu/nccl')

        # 检查NCCL库文件
        result = self.execute_on_host(host, f"test -d {install_path}/lib && ls {install_path}/lib/ 2>/dev/null | head -3", timeout=30)

        if result.get("success") and result.get("stdout", "").strip():
            return True, f"NCCL已安装: {install_path}"

        return False, "NCCL未安装"

    def execute(self, hosts: List[str]) -> StepResult:
        """执行NCCL安装"""
        results = {}

        nccl_config = self.versions.nccl

        if not nccl_config.enabled:
            self.logger.info("NCCL未启用，跳过安装")
            return StepResult(
                step_id=self.step_id,
                step_name=self.step_name,
                status=StepStatus.SKIPPED,
                message="NCCL未启用，跳过安装"
            )

        install_path = getattr(nccl_config, 'install_path', '/home/ubuntu/nccl')
        install_method = getattr(nccl_config, 'install_method', 'source')
        local_file = getattr(nccl_config, 'local_file', None)
        compile_jobs = getattr(nccl_config, 'compile_jobs', None)  # None表示使用nproc

        for host in hosts:
            self.logger.info(f"[{host}] 开始安装NCCL...")
            self.logger.info(f"[{host}] 安装方式: {install_method}, 安装路径: {install_path}")

            # 1. 获取GPU计算能力
            cap_cmd = "nvidia-smi --query-gpu=compute_cap --format=csv,noheader | head -1"
            cap_result = self.execute_on_host(host, cap_cmd)

            if not cap_result["success"]:
                results[host] = {"success": False, "error": "获取GPU计算能力失败"}
                continue

            compute_cap = cap_result["stdout"].strip().replace(".", "")
            self.logger.info(f"[{host}] GPU计算能力: {compute_cap}")

            # 2. 根据安装方式获取源码
            if install_method == "local_file" and local_file:
                # 使用本地文件
                if not os.path.exists(local_file):
                    results[host] = {"success": False, "error": f"本地文件不存在: {local_file}"}
                    continue

                filename = Path(local_file).name
                remote_path = f"/tmp/{filename}"
                self.logger.info(f"[{host}] 使用本地文件: {local_file}")

                # 上传文件到远程节点
                self.logger.info(f"[{host}] 上传文件到: {remote_path}")
                upload_results = self.put_file([host], local_file, remote_path)
                self.logger.info(f"[{host}] 上传结果: {upload_results}")

                if not upload_results.get(host):
                    results[host] = {"success": False, "error": f"上传文件失败: {local_file}"}
                    self.logger.error(f"[{host}] 上传文件失败")
                    continue

                # 验证远程文件大小是否匹配
                local_size = os.path.getsize(local_file)
                check_size_cmd = f"stat -c%s {remote_path} 2>/dev/null || echo 0"
                size_result = self.execute_on_host(host, check_size_cmd)
                remote_size = int(size_result.get("stdout", "0").strip())

                if remote_size != local_size:
                    results[host] = {"success": False, "error": f"文件大小不匹配: 本地{local_size}B, 远程{remote_size}B"}
                    self.logger.error(f"[{host}] 文件大小不匹配: 本地{local_size}B, 远程{remote_size}B")
                    continue

                self.logger.info(f"[{host}] 文件上传成功，大小: {local_size}B")

                # 根据文件扩展名选择解压方式
                if filename.endswith('.zip'):
                    # ZIP格式解压
                    extract_cmd = f"rm -rf /tmp/nccl-src && mkdir -p /tmp/nccl-src && unzip -o {remote_path} -d /tmp/nccl-src && ls -la /tmp/nccl-src/"
                    extract_result = self.execute_on_host(host, extract_cmd, sudo=True)

                    if not extract_result["success"]:
                        results[host] = {"success": False, "error": "解压NCCL源码(zip)失败"}
                        continue

                    # 查找解压后的目录（zip可能有顶层目录）
                    find_cmd = "ls -d /tmp/nccl-src/*/ 2>/dev/null | head -1 || ls -d /tmp/nccl-src/ 2>/dev/null | head -1"
                    find_result = self.execute_on_host(host, find_cmd)
                    found_dir = find_result.get("stdout", "").strip()
                    # 如果有子目录，使用子目录；否则使用nccl-src
                    if found_dir and found_dir.endswith('/'):
                        nccl_src_dir = found_dir.rstrip('/')
                    else:
                        nccl_src_dir = "/tmp/nccl-src"

                elif filename.endswith('.tar.gz') or filename.endswith('.tgz'):
                    # tar.gz格式
                    extract_cmd = f"rm -rf /tmp/nccl-src && mkdir -p /tmp/nccl-src && tar -xzf {remote_path} -C /tmp/nccl-src --strip-components=1 && ls -la /tmp/nccl-src/"
                    extract_result = self.execute_on_host(host, extract_cmd, sudo=True)

                    if not extract_result["success"]:
                        # 尝试不带strip-components
                        extract_cmd2 = f"rm -rf /tmp/nccl-tmp && mkdir -p /tmp/nccl-tmp && tar -xzf {remote_path} -C /tmp/nccl-tmp && ls -la /tmp/nccl-tmp/"
                        extract_result2 = self.execute_on_host(host, extract_cmd2, sudo=True)
                        if extract_result2.get("success"):
                            # 查找解压后的目录
                            find_cmd = "ls -d /tmp/nccl-tmp/*/ 2>/dev/null | head -1"
                            find_result = self.execute_on_host(host, find_cmd)
                            nccl_src_dir = find_result.get("stdout", "").strip().rstrip('/') or "/tmp/nccl-tmp"
                        else:
                            results[host] = {"success": False, "error": "解压NCCL源码(tar.gz)失败"}
                            continue
                    else:
                        nccl_src_dir = "/tmp/nccl-src"

                elif filename.endswith('.tar'):
                    # tar格式
                    extract_cmd = f"rm -rf /tmp/nccl-src && mkdir -p /tmp/nccl-src && tar -xf {remote_path} -C /tmp/nccl-src --strip-components=1 && ls -la /tmp/nccl-src/"
                    extract_result = self.execute_on_host(host, extract_cmd, sudo=True)

                    if not extract_result["success"]:
                        # 尝试不带strip-components
                        extract_cmd2 = f"rm -rf /tmp/nccl-tmp && mkdir -p /tmp/nccl-tmp && tar -xf {remote_path} -C /tmp/nccl-tmp && ls -la /tmp/nccl-tmp/"
                        extract_result2 = self.execute_on_host(host, extract_cmd2, sudo=True)
                        if extract_result2.get("success"):
                            find_cmd = "ls -d /tmp/nccl-tmp/*/ 2>/dev/null | head -1"
                            find_result = self.execute_on_host(host, find_cmd)
                            nccl_src_dir = find_result.get("stdout", "").strip().rstrip('/') or "/tmp/nccl-tmp"
                        else:
                            results[host] = {"success": False, "error": "解压NCCL源码(tar)失败"}
                            continue
                    else:
                        nccl_src_dir = "/tmp/nccl-src"

                else:
                    results[host] = {"success": False, "error": f"不支持的文件格式: {filename}（支持 .zip, .tar.gz, .tar）"}
                    continue

                self.logger.info(f"[{host}] NCCL源码目录: {nccl_src_dir}")

            elif install_method == "source":
                # 从GitHub克隆源码
                clone_cmd = f"rm -rf /tmp/nccl && cd /tmp && git clone https://github.com/NVIDIA/nccl.git"
                clone_result = self.execute_on_host(host, clone_cmd, sudo=True)

                if not clone_result["success"]:
                    results[host] = {"success": False, "error": "克隆NCCL源码失败"}
                    continue

                nccl_src_dir = "/tmp/nccl"

            else:
                results[host] = {"success": False, "error": f"不支持的安装方式: {install_method}"}
                continue

            # 3. 编译NCCL
            # 确定编译并行度：如果compile_jobs设置了固定值则使用，否则使用nproc自动检测
            jobs_arg = f"-j{compile_jobs}" if compile_jobs else "-j$(nproc)"
            compile_cmd = f'''
cd {nccl_src_dir}
mkdir -p {install_path}
make {jobs_arg} src.build BUILDDIR={install_path} CUDA_HOME=/usr/local/cuda NVCC_GENCODE="-gencode=arch=compute_{compute_cap},code=sm_{compute_cap}"
'''
            compile_result = self.execute_on_host(host, compile_cmd, sudo=True, timeout=1200)
            results[host] = {"compile": compile_result}

            if not compile_result["success"]:
                results[host]["success"] = False
                results[host]["error"] = "NCCL编译失败"
                continue

            # 4. 配置环境变量（避免重复添加）
            env_cmd = f'''
grep -q "{install_path}/lib" /etc/profile 2>/dev/null || echo "export LD_LIBRARY_PATH=\\$LD_LIBRARY_PATH:{install_path}/lib" >> /etc/profile
grep -q "{install_path}/bin" /etc/profile 2>/dev/null || echo "export PATH=\\$PATH:{install_path}/bin" >> /etc/profile
'''
            self.execute_on_host(host, env_cmd, sudo=True)

            # 5. 验证
            verify_cmd = f"test -d {install_path}/lib && ls {install_path}/lib/"
            verify_result = self.execute_on_host(host, verify_cmd)
            results[host]["verify"] = verify_result

            if verify_result["success"]:
                results[host]["success"] = True
            else:
                results[host]["success"] = False
                results[host]["error"] = "NCCL库验证失败"

        success_count = sum(1 for r in results.values() if r.get("success"))

        return StepResult(
            step_id=self.step_id,
            step_name=self.step_name,
            status=StepStatus.SUCCESS if success_count == len(hosts) else StepStatus.FAILED,
            message=f"NCCL安装完成，成功: {success_count}/{len(hosts)}",
            details={"install_path": install_path},
            host_results=results
        )

    def post_check(self, hosts: List[str]) -> bool:
        """验证NCCL安装"""
        # 可选步骤，跳过验证
        return True
