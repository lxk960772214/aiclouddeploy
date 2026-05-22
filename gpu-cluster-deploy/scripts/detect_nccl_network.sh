#!/bin/bash
# NCCL网络环境自动检测脚本
# 在当前机器上检测IB/RoCE设备和以太网接口，输出推荐的NCCL环境变量
#
# 用法:
#   bash detect_nccl_network.sh [目标IP]
#   bash detect_nccl_network.sh          # 自动检测
#   bash detect_nccl_network.sh 10.0.0.1 # 指定对端IP用于路由检测
#
# 输出:
#   - 检测详情到stderr
#   - NCCL环境变量到stdout（可直接eval）

set -euo pipefail

TARGET_IP="${1:-}"

# ============ IB/RoCE 检测 ============

# 从ibstatus输出解析
parse_ibstatus() {
    local ib_output="$1"

    local device="" port="" rate="" phys_state="" link_layer=""
    local -a results=()

    while IFS= read -r line; do
        line=$(echo "$line" | sed 's/^[[:space:]]*//')

        if [[ "$line" =~ ^Infiniband\ device\ \'([^\']+)\'\ port\ ([0-9]+) ]]; then
            if [[ -n "$device" ]]; then
                results+=("${device}|${port}|${rate}|${phys_state}|${link_layer}")
            fi
            device="${BASH_REMATCH[1]}"
            port="${BASH_REMATCH[2]}"
            rate="" phys_state="" link_layer=""
        elif [[ "$line" =~ ^[Rr]ate: ]]; then
            rate=$(echo "$line" | sed 's/^[Rr]ate:[[:space:]]*//' | grep -oP '^\d+' || echo "0")
        elif [[ "$line" =~ ^[Pp]hys(ical)?[[:space:]]*state: ]]; then
            phys_state=$(echo "$line" | sed -E 's/^[Pp]hys(ical)?[[:space:]]*state:[[:space:]]*//')
        elif [[ "$line" =~ ^[Ll]ink[[:space:]]*_?[Ll]ayer: ]]; then
            link_layer=$(echo "$line" | sed -E 's/^[Ll]ink[[:space:]]*_?[Ll]ayer:[[:space:]]*//' | tr '[:upper:]' '[:lower:]' | xargs)
        fi
    done <<< "$ib_output"

    if [[ -n "$device" ]]; then
        results+=("${device}|${port}|${rate}|${phys_state}|${link_layer}")
    fi

    for entry in "${results[@]}"; do
        echo "$entry"
    done
}

# 从ibstat输出解析
parse_ibstat() {
    local ib_output="$1"

    local device="" port="" rate="" phys_state="" link_layer="" state=""
    local -a results=()

    while IFS= read -r line; do
        if [[ "$line" =~ ^CA\ \'([^\']+)\' ]]; then
            if [[ -n "$device" && -n "$port" ]]; then
                results+=("${device}|${port}|${rate}|${phys_state} ${state}|${link_layer}")
            fi
            device="${BASH_REMATCH[1]}"
            port="" rate="" phys_state="" link_layer="" state=""
        elif [[ "$line" =~ Port\ ([0-9]+): ]]; then
            if [[ -n "$device" && -n "$port" ]]; then
                results+=("${device}|${port}|${rate}|${phys_state} ${state}|${link_layer}")
            fi
            port="${BASH_REMATCH[1]}"
            rate="" phys_state="" link_layer="" state=""
        elif [[ -z "$port" ]]; then
            continue
        else
            local trimmed=$(echo "$line" | sed 's/^[[:space:]]*//')
            if [[ "$trimmed" =~ ^[Rr]ate: ]]; then
                rate=$(echo "$trimmed" | sed 's/^[Rr]ate:[[:space:]]*//' | grep -oP '^\d+' || echo "0")
            elif [[ "$trimmed" =~ ^[Pp]hysical[[:space:]]*state: ]]; then
                phys_state=$(echo "$trimmed" | sed -E 's/^[Pp]hysical[[:space:]]*state:[[:space:]]*//')
            elif [[ "$trimmed" =~ ^[Ss]tate: ]]; then
                state=$(echo "$trimmed" | sed 's/^[Ss]tate:[[:space:]]*//')
            elif [[ "$trimmed" =~ ^[Ll]ink[[:space:]]*_?[Ll]ayer: ]]; then
                link_layer=$(echo "$trimmed" | sed -E 's/^[Ll]ink[[:space:]]*_?[Ll]ayer:[[:space:]]*//' | tr '[:upper:]' '[:lower:]' | xargs)
            fi
        fi
    done <<< "$ib_output"

    if [[ -n "$device" && -n "$port" ]]; then
        results+=("${device}|${port}|${rate}|${phys_state} ${state}|${link_layer}")
    fi

    for entry in "${results[@]}"; do
        echo "$entry"
    done
}

detect_ib_devices() {
    if command -v ibstatus &>/dev/null; then
        local ib_output
        ib_output=$(ibstatus 2>/dev/null) || true
        if [[ -n "$ib_output" ]]; then
            parse_ibstatus "$ib_output"
            return 0
        fi
    fi

    if command -v ibstat &>/dev/null; then
        local ib_output
        ib_output=$(ibstat 2>/dev/null) || true
        if [[ -n "$ib_output" ]]; then
            parse_ibstat "$ib_output"
            return 0
        fi
    fi

    return 1
}

get_active_ib_hcas() {
    local -a all_devices=()
    while IFS= read -r line; do
        [[ -z "$line" ]] && continue
        all_devices+=("$line")
    done < <(detect_ib_devices)

    if [[ ${#all_devices[@]} -eq 0 ]]; then
        return 1
    fi

    # 过滤: 1) Active/LinkUp状态  2) 只保留InfiniBand链路层设备(RoCE/Ethernet走SOCKET_IFNAME)
    local -a active=()
    for entry in "${all_devices[@]}"; do
        IFS='|' read -r d p r ps ll nd <<< "$entry"
        local ps_lower=$(echo "$ps" | tr '[:upper:]' '[:lower:]')
        # 跳过非InfiniBand链路层的设备
        if [[ "$ll" != "infiniband" ]]; then
            echo "  [跳过] $d: 链路层=$ll (非InfiniBand, 不纳入HCA)" >&2
            continue
        fi
        if [[ "$ps_lower" == *"linkup"* || "$ps_lower" == *"active"* ]]; then
            active+=("$entry")
        fi
    done

    if [[ ${#active[@]} -eq 0 ]]; then
        # 放宽：IB设备即使状态不理想也用
        for entry in "${all_devices[@]}"; do
            IFS='|' read -r d p r ps ll nd <<< "$entry"
            if [[ "$ll" == "infiniband" ]]; then
                active+=("$entry")
            fi
        done
    fi

    # 找出最高速率，只保留该速率的设备（排除异速率卡）
    local max_rate=0
    for entry in "${active[@]}"; do
        IFS='|' read -r d p r ps ll nd <<< "$entry"
        if [[ ${r:-0} -gt $max_rate ]]; then
            max_rate=$r
        fi
    done

    local -a filtered=()
    for entry in "${active[@]}"; do
        IFS='|' read -r d p r ps ll nd <<< "$entry"
        if [[ $r -eq $max_rate ]]; then
            filtered+=("$entry")
        else
            echo "  [跳过] $d: 速率=${r}Gb/s < 最高速率=${max_rate}Gb/s" >&2
        fi
    done

    # 按设备名排序
    local -a sorted=()
    while IFS= read -r e; do
        [[ -n "$e" ]] && sorted+=("$e")
    done < <(for e in "${filtered[@]}"; do
        IFS='|' read -r d p r ps ll nd <<< "$e"
        echo "${d}|$e"
    done | sort -t'|' -k1 | cut -d'|' -f2-)

    for e in "${sorted[@]}"; do
        echo "$e"
    done
}

# ============ 以太网接口检测 ============

detect_ethernet_iface() {
    local target="$1"

    if [[ -n "$target" ]]; then
        local iface
        iface=$(ip -o addr show 2>/dev/null | grep "${target}/" | awk '{print $2}' | head -1) || true
        if [[ -n "$iface" ]]; then
            echo "$iface"
            return 0
        fi
    fi

    if [[ -n "$target" ]]; then
        local iface
        iface=$(ip route get "$target" 2>/dev/null | head -1 | awk '{print $5}') || true
        if [[ -n "$iface" && "$iface" != "lo" ]]; then
            echo "$iface"
            return 0
        fi
    fi

    local iface
    iface=$(ip -o link show 2>/dev/null | grep -v -E 'lo:|docker|br-|virbr|veth|flannel|cni' | grep 'state UP' | awk -F': ' '{print $2}' | head -1) || true
    if [[ -n "$iface" ]]; then
        echo "$iface"
        return 0
    fi

    return 1
}

# ============ 主逻辑 ============

main() {
    local -a nccl_env=()

    # --- IB检测 ---
    local -a ib_hcas=()
    while IFS= read -r line; do
        [[ -z "$line" ]] && continue
        ib_hcas+=("$line")
    done < <(get_active_ib_hcas)

    local has_infiniband=false has_roce=false

    # 检查是否有RoCE/Ethernet链路层的IB设备（用于判断类型提示）
    local -a all_ib=()
    while IFS= read -r line; do
        [[ -z "$line" ]] && continue
        all_ib+=("$line")
    done < <(detect_ib_devices)
    for entry in "${all_ib[@]}"; do
        IFS='|' read -r d p r ps ll nd <<< "$entry"
        if [[ "$ll" == "infiniband" ]]; then
            has_infiniband=true
        elif [[ "$ll" == "ethernet" ]]; then
            has_roce=true
        fi
    done

    if [[ ${#ib_hcas[@]} -gt 0 ]]; then
        echo "===== 检测到InfiniBand设备 =====" >&2
        for entry in "${ib_hcas[@]}"; do
            IFS='|' read -r d p r ps ll nd <<< "$entry"
            echo "  设备: $d, 端口: $p, 速率: ${r}Gb/s, 状态: $ps" >&2
        done

        nccl_env+=("NCCL_IB_DISABLE=0")

        # HCA列表
        local hca_parts=()
        for entry in "${ib_hcas[@]}"; do
            IFS='|' read -r d p r ps ll nd <<< "$entry"
            hca_parts+=("${d}:${p}")
        done
        nccl_env+=("NCCL_IB_HCA=$(IFS=,; echo "${hca_parts[*]}")")

        # 根据IB类型设置参数
        if $has_infiniband; then
            nccl_env+=("NCCL_IB_GID_INDEX=0")
            nccl_env+=("NCCL_IB_TC=0")
            echo "  类型: InfiniBand (GID_INDEX=0, TC=0)" >&2
        else
            nccl_env+=("NCCL_IB_GID_INDEX=3")
            nccl_env+=("NCCL_IB_TC=106")
            echo "  类型: RoCE (GID_INDEX=3, TC=106)" >&2
        fi

        nccl_env+=("NCCL_IB_RETRY_CNT=7")
        nccl_env+=("NCCL_IB_TIMEOUT=23")
        nccl_env+=("NCCL_IB_QPS_PER_CONNECTION=4")
        nccl_env+=("NCCL_NET_GDR_LEVEL=3")
        nccl_env+=("NCCL_MAX_NCHANNELS=16")
        nccl_env+=("NCCL_MIN_NCHANNELS=16")
    else
        echo "===== 未检测到InfiniBand设备，将使用以太网 =====" >&2
        nccl_env+=("NCCL_IB_DISABLE=1")
    fi

    # --- 以太网接口检测 ---
    local eth_iface=""
    eth_iface=$(detect_ethernet_iface "$TARGET_IP") || true

    if [[ -n "$eth_iface" ]]; then
        nccl_env+=("NCCL_SOCKET_IFNAME=$eth_iface")
        echo "===== 以太网接口: $eth_iface =====" >&2
    else
        echo "===== 警告: 无法检测以太网接口 =====" >&2
    fi

    # --- 通用参数 ---
    nccl_env+=("NCCL_DEBUG=WARN")
    nccl_env+=("NCCL_CHECKS_DISABLE=1")

    # --- 输出 ---
    echo "" >&2
    echo "===== 推荐的NCCL环境变量 =====" >&2
    for e in "${nccl_env[@]}"; do
        echo "  export $e" >&2
    done
    echo "" >&2

    # stdout: 可eval的export命令
    for e in "${nccl_env[@]}"; do
        echo "export $e"
    done
}

main
