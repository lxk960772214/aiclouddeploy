#!/bin/bash
# NCCL多节点测试命令生成脚本
# 根据网卡检测结果生成mpirun命令，不执行，只打印
#
# 用法:
#   bash generate_nccl_test_cmd.sh [选项]
#
# 选项:
#   --hosts "ip1 ip2 ..."     参与测试的节点IP列表 (必填)
#   --gpus-per-node N         每节点使用的GPU数 (默认: 自动检测)
#   --test-items "item1 item2" 测试项 (默认: "all_reduce_perf all_gather_perf alltoall_perf")
#   --toolkit-dir DIR         工具目录 (默认: /ssd/nfs/gpu-test/toolkit)
#   --nccl-test-size SIZE     最大测试数据量 (默认: 8G)
#   --label LABEL             测试标签 (默认: custom)
#   --run                     生成命令后直接执行 (默认: 只打印)
#
# 示例:
#   # 只生成命令不执行
#   bash generate_nccl_test_cmd.sh --hosts "10.0.0.1 10.0.0.2"
#
#   # 指定GPU数和测试项
#   bash generate_nccl_test_cmd.sh --hosts "10.0.0.1 10.0.0.2" --gpus-per-node 1 --test-items "all_reduce_perf"
#
#   # 生成后直接执行
#   bash generate_nccl_test_cmd.sh --hosts "10.0.0.1 10.0.0.2" --run

set -euo pipefail

# ============ 默认参数 ============
HOSTS=""
GPUS_PER_NODE=""
TEST_ITEMS="all_reduce_perf all_gather_perf alltoall_perf"
TOOLKIT_DIR="/ssd/nfs/gpu-test/toolkit"
NCCL_TEST_SIZE=""
LABEL="custom"
RUN=false
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# ============ 参数解析 ============
while [[ $# -gt 0 ]]; do
    case "$1" in
        --hosts)         HOSTS="$2"; shift 2 ;;
        --gpus-per-node) GPUS_PER_NODE="$2"; shift 2 ;;
        --test-items)    TEST_ITEMS="$2"; shift 2 ;;
        --toolkit-dir)   TOOLKIT_DIR="$2"; shift 2 ;;
        --nccl-test-size) NCCL_TEST_SIZE="$2"; shift 2 ;;
        --label)         LABEL="$2"; shift 2 ;;
        --run)           RUN=true; shift ;;
        -h|--help)
            head -30 "$0" | grep '^#' | sed 's/^# \?//'
            exit 0 ;;
        *) echo "未知参数: $1"; exit 1 ;;
    esac
done

if [[ -z "$HOSTS" ]]; then
    echo "错误: 必须指定 --hosts" >&2
    echo "用法: bash $0 --hosts \"10.0.0.1 10.0.0.2\"" >&2
    exit 1
fi

# ============ 辅助函数 ============

get_gpu_count() {
    nvidia-smi --query-gpu=count --format=csv,noheader 2>/dev/null | head -1 | tr -d ' ' || echo "0"
}

get_compute_cap() {
    nvidia-smi --query-gpu=compute_cap --format=csv,noheader 2>/dev/null | head -1 | tr -d ' .' || echo ""
}

# ============ 自动检测 ============

# GPU数量
if [[ -z "$GPUS_PER_NODE" ]]; then
    GPUS_PER_NODE=$(get_gpu_count)
    if [[ "$GPUS_PER_NODE" == "0" || -z "$GPUS_PER_NODE" ]]; then
        echo "警告: 无法检测GPU数量，默认使用1" >&2
        GPUS_PER_NODE=1
    fi
fi

# 计算能力 → 自动调整测试数据量
if [[ -z "$NCCL_TEST_SIZE" ]]; then
    CAP=$(get_compute_cap)
    if [[ "$CAP" == "120" || "$CAP" == "89" ]]; then
        NCCL_TEST_SIZE="2G"
    else
        NCCL_TEST_SIZE="8G"
    fi
fi

# 检测网络配置 (调用同目录下的detect脚本)
NCCL_ENV_FILE=$(mktemp)
if [[ -f "$SCRIPT_DIR/detect_nccl_network.sh" ]]; then
    # 用第一个对端IP做路由检测
    read -ra HOST_ARRAY <<< "$HOSTS"
    OTHER_IP=""
    for h in "${HOST_ARRAY[@]:1}"; do
        OTHER_IP="$h"; break
    done
    bash "$SCRIPT_DIR/detect_nccl_network.sh" "$OTHER_IP" > "$NCCL_ENV_FILE" 2>/dev/null || true
fi

# ============ 生成hostfile ============

HOSTFILE_CONTENT=""
for host in $HOSTS; do
    HOSTFILE_CONTENT+="${host} slots=${GPUS_PER_NODE}"$'\n'
done

HOSTFILE_PATH="${TOOLKIT_DIR}/hostfile_${LABEL}"

# ============ 生成mpirun命令 ============

OPENMPI_BIN="${TOOLKIT_DIR}/openmpi/bin/mpirun"
NCCL_TESTS_BIN_BASE="${TOOLKIT_DIR}/nccl-tests-mpi/build"
LD_LIBRARY_PATH_STR="${TOOLKIT_DIR}/openmpi/lib:${TOOLKIT_DIR}/nccl/lib:/usr/local/cuda/lib64"

TOTAL_PROCESSES=$((${#HOST_ARRAY[@]} * GPUS_PER_NODE))

# 读取NCCL环境变量
NCCL_X_ARGS=()
if [[ -f "$NCCL_ENV_FILE" ]]; then
    while IFS= read -r line; do
        [[ -z "$line" ]] && continue
        # export KEY=VALUE → -x KEY=VALUE
        key_val=$(echo "$line" | sed 's/^export //')
        NCCL_X_ARGS+=("-x" "$key_val")
    done < "$NCCL_ENV_FILE"
fi

# MCA参数
SOCKET_IFNAME=$(grep NCCL_SOCKET_IFNAME "$NCCL_ENV_FILE" 2>/dev/null | sed 's/.*=//' || true)
MCA_ARGS=("-mca" "coll_hcoll_enable" "0" "-mca" "pml" "ob1")
if [[ -n "$SOCKET_IFNAME" && "$SOCKET_IFNAME" != "^" ]]; then
    MCA_ARGS+=("-mca" "btl_tcp_if_include" "$SOCKET_IFNAME")
fi
MCA_ARGS+=("-mca" "btl" "^openib")

# ============ 输出 ============

echo "=========================================="
echo "NCCL多节点测试命令"
echo "=========================================="
echo ""
echo "节点:       ${HOST_ARRAY[*]}"
echo "每节点GPU:  ${GPUS_PER_NODE}"
echo "总进程数:   ${TOTAL_PROCESSES}"
echo "测试数据量: ${NCCL_TEST_SIZE}"
echo "工具目录:   ${TOOLKIT_DIR}"
echo ""
echo "--- hostfile (${HOSTFILE_PATH}) ---"
echo -n "$HOSTFILE_CONTENT"
echo ""
echo "--- NCCL环境变量 ---"
if [[ -f "$NCCL_ENV_FILE" ]]; then
    cat "$NCCL_ENV_FILE"
else
    echo "(未检测到，请手动设置)"
fi
echo ""

# 为每个测试项生成命令
for test_item in $TEST_ITEMS; do
    echo "--- ${test_item} 命令 ---"

    CMD_PARTS=(
        "$OPENMPI_BIN"
        "-np" "$TOTAL_PROCESSES"
        "--hostfile" "$HOSTFILE_PATH"
        "--allow-run-as-root"
        "-bind-to" "numa"
        "-map-by" "slot"
        "-x" "LD_LIBRARY_PATH=${LD_LIBRARY_PATH_STR}"
        "-x" "PATH=\$PATH"
    )
    CMD_PARTS+=("${NCCL_X_ARGS[@]}")
    CMD_PARTS+=("${MCA_ARGS[@]}")
    CMD_PARTS+=("${NCCL_TESTS_BIN_BASE}/${test_item}")
    CMD_PARTS+=("-b" "1M" "-e" "$NCCL_TEST_SIZE" "-f" "2" "-g" "$GPUS_PER_NODE")

    echo ""
    echo "# 写入hostfile"
    echo "cat > ${HOSTFILE_PATH} << 'EOF'"
    echo -n "$HOSTFILE_CONTENT"
    echo "EOF"
    echo ""
    echo "# 加载NCCL环境变量"
    echo "source ${NCCL_ENV_FILE} 2>/dev/null || true"
    echo ""
    echo "# 执行测试"
    echo "${CMD_PARTS[*]}"
    echo ""
done

# 清理临时文件
rm -f "$NCCL_ENV_FILE"

echo "=========================================="
echo "提示: 去掉命令前的 # 即可执行，或使用 --run 参数直接运行"
echo "=========================================="
