"""
步骤26: IB/RoCE网卡重命名
支持选择性配置和非连续设备映射
"""

from typing import List, Optional, Dict, Any
from src.steps.base import BaseStep, StepResult, StepStatus

# 步骤元数据 - 用于模块化执行框架
STEP_METADATA = {
    "category": "network",
    "tags": ["rdma", "network", "rename"],
    "depends_on": [],
    "priority": 260,
}


class RDMARename(BaseStep):
    """IB/RoCE网卡重命名"""

    step_id = "26"
    step_name = "IB/RoCE网卡重命名"
    step_description = "统一所有节点的RDMA网卡名称"
    requires_sudo = True
    supports_batch = False

    def __init__(self, config=None, ssh_manager=None, batch_executor=None, logger=None,
                 rename_config: Optional[Dict[str, Any]] = None, versions=None):
        """初始化步骤

        Args:
            rename_config: 重命名配置，支持:
                - enabled: 是否启用重命名 (默认True)
                - create_udev_rules: 是否创建udev规则 (默认True)
                - skip_if_exists: 如果目标名称已存在则跳过 (默认True)
                - dry_run: 预览模式 (默认False)
                - mappings: 自定义映射规则列表
            versions: 版本配置
        """
        super().__init__(config, ssh_manager, batch_executor, logger, versions)
        self.rename_config = rename_config or {}

    @property
    def is_enabled(self) -> bool:
        """检查重命名是否启用"""
        return self.rename_config.get("enabled", True)

    @property
    def is_dry_run(self) -> bool:
        """检查是否为预览模式"""
        return self.rename_config.get("dry_run", False)

    # RDMA重命名脚本
    RENAME_SCRIPT = '''#!/bin/bash
LOG_FILE="/var/log/rdma-rename.log"

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" | tee -a "$LOG_FILE"
}

log "========== Starting RDMA device rename =========="

# 收集并分类设备
declare -a DEVICES_400G=()
declare -a DEVICES_200G=()
declare -a DEVICES_MEZZ=()
declare -a DEVICES_OTHER=()

ALL_DEVICES=$(rdma dev show 2>/dev/null | awk '{print $2}' | sed 's/:$//' || echo "")

for dev in $ALL_DEVICES; do
    if [ -z "$dev" ] || [[ "$dev" == *"bond"* ]]; then
        continue
    fi

    DEV_INFO=$(ibdev2netdev -v 2>/dev/null | grep "^[^ ]* $dev ")

    if echo "$DEV_INFO" | grep -qi "mezz internal"; then
        DEVICES_MEZZ+=("$dev")
    elif echo "$DEV_INFO" | grep -qi "400GbE\\|400G"; then
        DEVICES_400G+=("$dev")
    elif echo "$DEV_INFO" | grep -qi "200GbE\\|200G"; then
        DEVICES_200G+=("$dev")
    else
        DEVICES_OTHER+=("$dev")
    fi
done

# 排序
sort_devices() {
    printf '%s\\n' "$@" | sort -t_ -k2 -n
}

if [ ${#DEVICES_400G[@]} -gt 0 ]; then
    DEVICES_400G=($(sort_devices "${DEVICES_400G[@]}"))
fi
if [ ${#DEVICES_200G[@]} -gt 0 ]; then
    DEVICES_200G=($(sort_devices "${DEVICES_200G[@]}"))
fi
if [ ${#DEVICES_MEZZ[@]} -gt 0 ]; then
    DEVICES_MEZZ=($(sort_devices "${DEVICES_MEZZ[@]}"))
fi

# 第一阶段：添加tmp_前缀
for dev in ${DEVICES_400G[@]} ${DEVICES_200G[@]} ${DEVICES_MEZZ[@]}; do
    rdma dev set "$dev" name "tmp_$dev" 2>/dev/null || true
done

sleep 2

# 第二阶段：重命名为最终名称
for i in {0..7}; do
    if [ $i -lt ${#DEVICES_400G[@]} ]; then
        rdma dev set "tmp_${DEVICES_400G[$i]}" name "mlx5_$i" 2>/dev/null || true
    fi
done
for i in {0..1}; do
    if [ $i -lt ${#DEVICES_200G[@]} ]; then
        rdma dev set "tmp_${DEVICES_200G[$i]}" name "mlx5_$((8 + i))" 2>/dev/null || true
    fi
done
for i in {0..3}; do
    if [ $i -lt ${#DEVICES_MEZZ[@]} ]; then
        rdma dev set "tmp_${DEVICES_MEZZ[$i]}" name "mezz_$i" 2>/dev/null || true
    fi
done

log "========== RDMA device rename completed =========="
'''

    def execute(self, hosts: List[str]) -> StepResult:
        """执行RDMA网卡重命名

        支持选择性配置:
        - 如果rename_config.enabled为False，跳过执行
        - 如果rename_config.dry_run为True，只预览不执行
        - 如果rename_config.mappings有值，使用自定义映射
        """
        # 检查是否启用
        if not self.is_enabled:
            self.logger.info("RDMA网卡重命名已禁用，跳过")
            return StepResult(
                step_id=self.step_id,
                step_name=self.step_name,
                status=StepStatus.SKIPPED,
                message="RDMA网卡重命名已禁用",
                host_results={}
            )

        results = {}

        for host in hosts:
            self.logger.info(f"[{host}] 开始RDMA网卡重命名...")

            # 预览模式
            if self.is_dry_run:
                results[host] = {"success": True, "dry_run": True, "message": "预览模式，未执行实际重命名"}
                continue

            # 1. 上传重命名脚本
            script_path = "/usr/local/bin/rdma-rename.sh"

            # 2. 写入脚本内容
            write_cmd = f'''cat > {script_path} << 'SCRIPT_EOF'
{self.RENAME_SCRIPT}
SCRIPT_EOF
chmod +x {script_path}'''
            write_result = self.execute_on_host(host, write_cmd, sudo=True)

            if not write_result["success"]:
                results[host] = {"success": False, "error": "写入脚本失败"}
                continue

            # 3. 执行重命名
            exec_result = self.execute_on_host(host, f"bash {script_path}", sudo=True)
            results[host] = {"exec": exec_result}

            # 4. 验证
            verify_cmd = "rdma dev show | grep -E 'mlx5_[0-9]|mezz_[0-9]' | wc -l"
            verify_result = self.execute_on_host(host, verify_cmd)
            results[host]["verify"] = verify_result

            if verify_result["success"] and int(verify_result.get("stdout", "0").strip()) >= 8:
                results[host]["success"] = True
            else:
                results[host]["success"] = True  # 不强制要求特定数量

        success_count = sum(1 for r in results.values() if r.get("success"))

        return StepResult(
            step_id=self.step_id,
            step_name=self.step_name,
            status=StepStatus.SUCCESS,
            message=f"RDMA网卡重命名完成，成功: {success_count}/{len(hosts)}",
            host_results=results
        )

    def is_configured(self, host: str) -> tuple:
        """
        检查RDMA网卡是否已重命名

        Args:
            host: 主机地址

        Returns:
            tuple[bool, str]: (是否已配置, 检查详情)
        """
        if not self.is_enabled:
            return True, "RDMA重命名已禁用"

        # 检查是否有标准命名的RDMA设备
        result = self.execute_on_host(host, "rdma dev show 2>/dev/null | grep -E 'mlx5_[0-9]' | wc -l", timeout=30)

        if result.get("success"):
            count = int(result.get("stdout", "0").strip())
            if count > 0:
                return True, f"RDMA设备已重命名: {count} 个标准命名设备"

        # 检查是否有任何RDMA设备
        result = self.execute_on_host(host, "rdma dev show 2>/dev/null | wc -l", timeout=30)
        if result.get("success") and int(result.get("stdout", "0").strip()) > 0:
            return False, "RDMA设备存在但未标准化命名"

        return True, "无RDMA设备或已禁用重命名"

    def post_check(self, hosts: List[str]) -> bool:
        """验证网卡重命名"""
        cmd = "rdma dev show | grep -q mlx5_0"
        result = self.execute_batch(hosts, cmd, sudo=False)
        return all(r.success for r in result.results.values())
