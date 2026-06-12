#!/usr/bin/env bash

export PDSH_SSH_ARGS="-o StrictHostKeyChecking=accept-new"

# 控制是否包含本机执行 (true: 包含本机, false: 不包含本机)
# 默认为 true，可以通过脚本第一个参数传入 false 来关闭
INCLUDE_LOCAL=${1:-true}

CURRENT_PATH=$(dirname $(readlink -f "${BASH_SOURCE[0]}"))

NODE=""
while read IP HOSTNAME;
do
    # 如果不包含本机，且当前行是本机，则跳过
    if [[ "${INCLUDE_LOCAL}" != "true" && "${HOSTNAME}" == "$(hostname)" ]]; then
        continue
    fi
    NODE="${NODE},ssh:${IP}"
done < <(cat ${CURRENT_PATH:=.}/hosts | grep -E -v '^(#|$)')

W_LIST=${NODE:1}
PDSH_FANOUT=1



command=$(cat << 'EOF'

hostname

EOF
)

echo "即将对以下节点执行操作:"
cat ${CURRENT_PATH}/hosts | grep -E -v '^(#|$)'
#echo $W_LIST
echo "pdsh 并行数量: ${PDSH_FANOUT}"
echo "------------------"
read -p "是否确认上述节点批量执行命令? (y/N): " confirm
confirm=${confirm:-n}
if [[ $confirm != "y" ]]; then
    echo "操作已取消。"
    exit 0
fi

echo "当前节点是 `hostname`"
    read -p "是否确认在此节点执行命令(y/N): " confirm
confirm=${confirm:-n}
if [[ $confirm != "y" ]]; then
    echo "操作已取消。"
    exit 0
fi

echo "即将执行的命令内容如下:"
echo "------------------"
echo "$command"
echo "------------------"


echo "是否确认开始运行批命令"
read -p " (y/N): " confirm  
confirm=${confirm:-n}
if [[ $confirm = "y" ]]; then
    pdsh -f "$PDSH_FANOUT" -w "$W_LIST" "$command"
else
    echo "操作已取消。"
fi

