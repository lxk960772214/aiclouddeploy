"""
步骤43: Sysbench CPU性能测试

测试CPU性能，使用不同线程数进行测试
"""

import os
from typing import List
from src.steps.base import BaseStep, StepResult, StepStatus


class SysbenchCPUTest(BaseStep):
    """Sysbench CPU性能测试"""

    step_id = "43"
    step_name = "Sysbench CPU测试"
    step_description = "测试CPU性能，使用不同线程数进行测试"
    requires_sudo = False
    supports_batch = True
    timeout = 300

    def _get_result_dir(self) -> str:
        """获取测试结果目录"""
        if hasattr(self, 'versions') and self.versions and hasattr(self.versions, 'test_packages'):
            return self.versions.test_packages.result_dir
        return "/opt/gpu-test/result"

    def is_configured(self, host: str) -> tuple:
        """检查sysbench是否安装"""
        check_cmd = "which sysbench && echo 'installed' || echo 'not_installed'"
        result = self.execute_on_host(host, check_cmd)
        stdout = result.get("stdout", "").strip()
        if stdout == "installed" or "/usr/bin/sysbench" in stdout:
            return True, "sysbench已安装"
        return False, "sysbench未安装"

    def _get_cpu_cores(self, host: str) -> int:
        """获取CPU核心数"""
        cores_cmd = "nproc"
        result = self.execute_on_host(host, cores_cmd)
        if result.get("success"):
            return int(result.get("stdout", "1").strip())
        return 1

    def execute(self, hosts: List[str]) -> StepResult:
        """执行Sysbench CPU测试"""
        results = {}
        result_dir = self._get_result_dir()

        for host in hosts:
            self.logger.info(f"[{host}] 开始Sysbench CPU测试...")

            # 1. 检查sysbench是否安装
            check_cmd = "which sysbench && echo 'installed' || echo 'not_installed'"
            check_result = self.execute_on_host(host, check_cmd)

            if check_result.get("stdout", "").strip() == "not_installed":
                self.logger.info(f"[{host}] 安装sysbench...")
                install_cmd = "apt update -qq && apt install -y sysbench"
                install_result = self.execute_on_host(host, install_cmd, sudo=True)
                if not install_result.get("success"):
                    results[host] = {"success": False, "error": "sysbench安装失败"}
                    continue

            # 2. 获取CPU核心数
            cpu_cores = self._get_cpu_cores(host)
            self.logger.info(f"[{host}] CPU核心数: {cpu_cores}")

            # 3. 创建结果目录
            self.execute_on_host(host, f"mkdir -p {result_dir}")

            # 4. 运行测试（线程数: 1, 2, 4, 8, 16, ... 直到CPU核心数）
            hostname_cmd = "hostname"
            hostname_result = self.execute_on_host(host, hostname_cmd)
            hostname = hostname_result.get("stdout", host).strip()

            test_results = []
            thread = 1
            while thread <= cpu_cores:
                self.logger.info(f"[{host}] 测试线程数: {thread}")

                # 运行sysbench CPU测试
                test_cmd = f"sysbench --threads={thread} --time=30 --report-interval=2 cpu run 2>/dev/null | grep -E 'events per second:|min:|avg:|max:|95th percentile:' | tr '\\n' ','"
                test_result = self.execute_on_host(host, test_cmd, timeout=60)

                if test_result.get("success"):
                    perf_data = test_result.get("stdout", "").strip()
                    # 去掉最后的逗号
                    if perf_data.endswith(','):
                        perf_data = perf_data[:-1]
                    test_results.append({"threads": thread, "perf": perf_data})
                    self.logger.info(f"[{host}] 线程数 {thread}: {perf_data}")
                else:
                    test_results.append({"threads": thread, "perf": "N/A"})

                thread *= 2

            # 5. 保存结果
            result_lines = []
            for r in test_results:
                line = f"线程数: {r['threads']} | {r['perf']}"
                result_lines.append(line)

            result_file = f"{result_dir}/sysbench_{hostname}.log"
            write_cmd = f"cat > {result_file} << 'EOF'\n" + "\n".join(result_lines) + "\nEOF"
            self.execute_on_host(host, write_cmd)

            results[host] = {"success": True, "cpu_cores": cpu_cores, "results": test_results}

        success_count = sum(1 for r in results.values() if r.get("success"))

        return StepResult(
            step_id=self.step_id,
            step_name=self.step_name,
            status=StepStatus.SUCCESS if success_count == len(hosts) else StepStatus.FAILED,
            message=f"Sysbench CPU测试完成，成功: {success_count}/{len(hosts)}",
            host_results=results
        )

    def post_check(self, hosts: List[str]) -> bool:
        """验证测试结果"""
        result_dir = self._get_result_dir()
        for host in hosts:
            check_cmd = f"test -f {result_dir}/sysbench_*.log"
            result = self.execute_on_host(host, check_cmd)
            if not result.get("success"):
                return False
        return True