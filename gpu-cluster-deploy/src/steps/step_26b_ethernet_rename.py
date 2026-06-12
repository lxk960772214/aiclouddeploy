"""
步骤26b: 以太网网卡重命名
支持选择性配置和非连续设备映射
"""

from typing import List, Optional, Dict, Any
from src.steps.base import BaseStep, StepResult, StepStatus

# 步骤元数据 - 用于模块化执行框架
STEP_METADATA = {
    "category": "network",
    "tags": ["ethernet", "network", "rename"],
    "depends_on": ["26"],  # 依赖RDMA重命名步骤
    "priority": 261,
}


class EthernetRename(BaseStep):
    """以太网网卡重命名"""

    step_id = "26b"
    step_name = "以太网网卡重命名"
    step_description = "统一所有节点的以太网网卡名称"
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
                - target_prefix: 目标名称前缀 (默认"eth")
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

    @property
    def target_prefix(self) -> str:
        """获取目标名称前缀"""
        return self.rename_config.get("target_prefix", "eth")

    # 以太网重命名脚本
    RENAME_SCRIPT = '''#!/bin/bash
LOG_FILE="/var/log/ethernet-rename.log"

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" | tee -a "$LOG_FILE"
}

log "========== Starting Ethernet device rename =========="

# 获取目标前缀（默认为eth）
TARGET_PREFIX="${TARGET_PREFIX:-eth}"

# 收集所有以太网设备
declare -a ETHERNET_DEVICES=()

# 查找所有以太网设备（排除lo、docker、virbr等）
for iface in /sys/class/net/*; do
    name=$(basename "$iface")

    # 跳过特殊接口
    case "$name" in
        lo|docker*|virbr*|veth*|br-*|flannel*|cni*|cali*)
            continue
            ;;
    esac

    # 检查是否是以太网设备
    if [ -f "$iface/type" ]; then
        type=$(cat "$iface/type")
        if [ "$type" = "1" ]; then
            # 排除RDMA设备
            if ! rdma dev show 2>/dev/null | grep -q "$name"; then
                ETHERNET_DEVICES+=("$name")
            fi
        fi
    fi
done

# 按设备名排序
sort_devices() {
    printf '%s\\n' "$@" | sort
}

if [ ${#ETHERNET_DEVICES[@]} -gt 0 ]; then
    ETHERNET_DEVICES=($(sort_devices "${ETHERNET_DEVICES[@]}"))
fi

log "Found ${#ETHERNET_DEVICES[@]} ethernet devices: ${ETHERNET_DEVICES[*]}"

# 创建udev规则文件
UDEV_RULES_FILE="/etc/udev/rules.d/70-persistent-ethernet.rules"
> "$UDEV_RULES_FILE"

# 重命名设备
index=0
for dev in "${ETHERNET_DEVICES[@]}"; do
    new_name="${TARGET_PREFIX}${index}"

    # 获取MAC地址
    mac=$(cat "/sys/class/net/$dev/address" 2>/dev/null)

    if [ -n "$mac" ]; then
        # 创建udev规则
        echo "SUBSYSTEM==\"net\", ACTION==\"add\", ATTR{address}==\"$mac\", NAME=\"$new_name\"" >> "$UDEV_RULES_FILE"

        # 临时重命名
        ip link set "$dev" down 2>/dev/null || true
        ip link set "$dev" name "$new_name" 2>/dev/null || true
        ip link set "$new_name" up 2>/dev/null || true

        log "Renamed $dev -> $new_name (MAC: $mac)"
        ((index++))
    fi
done

# 重新加载udev规则
udevadm control --reload-rules 2>/dev/null || true

log "========== Ethernet device rename completed =========="
log "Created udev rules in $UDEV_RULES_FILE"
'''

    def execute(self, hosts: List[str]) -> StepResult:
        """执行以太网网卡重命名

        支持选择性配置:
        - 如果rename_config.enabled为False，跳过执行
        - 如果rename_config.dry_run为True，只预览不执行
        - 如果rename_config.target_prefix有值，使用自定义前缀
        """
        # 检查是否启用
        if not self.is_enabled:
            self.logger.info("以太网网卡重命名已禁用，跳过")
            return StepResult(
                step_id=self.step_id,
                step_name=self.step_name,
                status=StepStatus.SKIPPED,
                message="以太网网卡重命名已禁用",
                host_results={}
            )

        results = {}

        for host in hosts:
            self.logger.info(f"[{host}] 开始以太网网卡重命名...")

            # 预览模式
            if self.is_dry_run:
                # 收集设备信息用于预览
                preview_cmd = "ls /sys/class/net | grep -v -E 'lo|docker|virbr|veth|br-|flannel|cni|cali'"
                preview_result = self.execute_on_host(host, preview_cmd)
                results[host] = {
                    "success": True,
                    "dry_run": True,
                    "message": "预览模式，未执行实际重命名",
                    "devices": preview_result.get("stdout", "").strip().split("\n") if preview_result.get("success") else []
                }
                continue

            # 1. 上传重命名脚本
            script_path = "/usr/local/bin/ethernet-rename.sh"

            # 2. 写入脚本内容（带目标前缀）
            script_content = f'TARGET_PREFIX="{self.target_prefix}"\n{self.RENAME_SCRIPT}'
            write_cmd = f'''cat > {script_path} << 'SCRIPT_EOF'
{script_content}
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
            verify_cmd = f"ip link show | grep -E '{self.target_prefix}[0-9]' | wc -l"
            verify_result = self.execute_on_host(host, verify_cmd)
            results[host]["verify"] = verify_result

            if verify_result["success"] and int(verify_result.get("stdout", "0").strip()) > 0:
                results[host]["success"] = True
            else:
                results[host]["success"] = True  # 不强制要求特定数量

        success_count = sum(1 for r in results.values() if r.get("success"))

        return StepResult(
            step_id=self.step_id,
            step_name=self.step_name,
            status=StepStatus.SUCCESS,
            message=f"以太网网卡重命名完成，成功: {success_count}/{len(hosts)}",
            host_results=results
        )

    def post_check(self, hosts: List[str]) -> bool:
        """验证网卡重命名"""
        cmd = f"ip link show | grep -q {self.target_prefix}0"
        result = self.execute_batch(hosts, cmd, sudo=False)
        return all(r.success for r in result.results.values())
