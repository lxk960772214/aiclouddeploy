"""
步骤26: RDMA设备 rail 统一命名

目标: 所有节点上, rail 口(netdev IP = 10.100.<rail>.<节点号>, rail=0..7)的 RDMA 设备
     统一命名为 mlx5_0..7 —— 跨节点同号即同 rail, NCCL_IB_HCA=mlx5_0,1,2,3 这类
     按名选卡才有意义。

命名规则:
    rail N (IP 10.100.N.x)   -> mlx5_N
    非 rail 的多余 RDMA 设备  -> mlx5_extra_<n> (按 netdev 名排序, 不占用 mlx5_0..7)
    bond 设备 (mlx5_bond_*)  -> 不动 (driver 自动命名)

实现:
    1. 发现(Python 侧): 收集每台节点 RDMA设备/netdev/IP/PCI地址(KERNELS), 按 IP 推导
       rail, 打印映射表, 并按机型网卡名表做交叉校验:
         enp 机型: enp156/188/204/220/94/77/26/60 = rail 0-7
         ens 机型: ens8/7/6/5/4/3/2/1            = rail 0-7
       rail 判定以 IP 为准(网卡名表仅校验): 新机型(.9 的 enp33/36/... 命名异类)的
       enp 名不在表内, 但 IP 规律 10.100.<rail>.<node> 依然成立。
    2. 节点脚本 /usr/local/bin/rdma-rail-rename.sh: 自愈式两阶段改名 —— 每次运行按
       当前 IP 重新推导 rail, 重启/换卡/枚举变化后依然收敛; 幂等可重复执行;
       支持 DRY_RUN=1 预览。
    3. 持久化: systemd oneshot (rdma-rail-rename.service, After=network-online),
       开机自动执行上述脚本。

为什么不用 udev 逐设备 rename (SUBSYSTEM=="rdma", KERNELS=="<pci>", ATTR{rename}="mlx5_N"):
    udev 规则本身是持久的, 但开机默认枚举会循环占名(如 rail5 默认叫 mlx5_0 而
    rail0 默认叫 mlx5_5), udev 并行处理各设备事件, 循环换名会随机失败且结果不确定。
    oneshot 脚本等所有设备/IP 就绪后先统一腾位(railtmp_/extratmp_)再落最终名,
    是确定性的。
"""

import re
from typing import List, Optional, Dict, Any, Tuple

from src.steps.base import BaseStep, StepResult, StepStatus

# 步骤元数据 - 用于模块化执行框架
STEP_METADATA = {
    "category": "network",
    "tags": ["rdma", "network", "rename", "rail"],
    "depends_on": [],
    "priority": 260,
}


class RDMARename(BaseStep):
    """RDMA设备 rail 统一命名: rail N (IP 10.100.N.x) -> mlx5_N"""

    step_id = "26"
    step_name = "RDMA设备rail统一命名"
    step_description = "统一所有节点的RDMA设备命名(rail N -> mlx5_N)"
    requires_sudo = True
    supports_batch = False

    RAIL_PREFIX = "10.100"  # rail 子网: <PREFIX>.<rail>.<节点号>

    # 机型网卡名 -> rail 校验表(仅交叉校验, rail 判定以 IP 为准)
    NETDEV_RAIL_TABLE = {
        # enp 机型
        "enp156": 0, "enp188": 1, "enp204": 2, "enp220": 3,
        "enp94": 4, "enp77": 5, "enp26": 6, "enp60": 7,
        # ens 机型
        "ens8": 0, "ens7": 1, "ens6": 2, "ens5": 3,
        "ens4": 4, "ens3": 5, "ens2": 6, "ens1": 7,
    }

    # 发现命令: 每行输出 dev|netdev|ipv4列表|PCI地址
    DISCOVERY_CMD = r'''
rdma link show 2>/dev/null | awk '{
    dev=$2; sub(/\/.*/,"",dev);
    if (dev in seen) next; seen[dev]=1;          # 双口卡去重, 只取 port 1
    nd=""; for(i=1;i<NF;i++) if($i=="netdev") nd=$(i+1);
    print dev "\t" nd
  }' | while IFS=$'\t' read -r dev nd; do
    pci=$(readlink -f /sys/class/infiniband/$dev 2>/dev/null | awk -F/ '{print $(NF-2)}')
    ip=""
    if [ -n "$nd" ]; then
      ip=$(ip -4 -o addr show dev "$nd" 2>/dev/null | awk '{print $4}' | cut -d/ -f1 | paste -sd,)
    fi
    echo "$dev|$nd|$ip|$pci"
done
'''

    # 节点侧改名脚本(自愈式: 每次运行按当前 IP 重新推导 rail)
    RENAME_SCRIPT = r'''#!/bin/bash
# rdma-rail-rename.sh — RDMA 设备 rail 统一命名 (由 gpu-cluster-deploy step 26 安装)
# 规则: netdev IP == 10.100.<rail>.<节点> (rail=0..7) 的 RDMA 设备 -> mlx5_<rail>
#       其余非 bond RDMA 设备 -> mlx5_extra_<n>; bond 设备(mlx5_bond_*)不动
# 自愈: 每次运行按当前 IP 重新推导 rail; 幂等, 重启/换卡/枚举变化后依然收敛
# 预览: DRY_RUN=1 bash rdma-rail-rename.sh 只打印计划不执行
LOG=/var/log/rdma-rail-rename.log
RAIL_PREFIX="10.100"
WAIT_SECONDS=60
DRY_RUN="${DRY_RUN:-0}"

log(){ echo "$(date '+%F %T') $*" >>"$LOG"; }

get_devices(){  # 输出: dev<TAB>netdev<TAB>ip(逗号分隔)
  rdma link show 2>/dev/null | awk '{
      dev=$2; sub(/\/.*/,"",dev);
      if (dev in seen) next; seen[dev]=1;
      nd=""; for(i=1;i<NF;i++) if($i=="netdev") nd=$(i+1);
      print dev "\t" nd
    }' | while IFS=$'\t' read -r dev nd; do
      ip=""
      if [ -n "$nd" ]; then
        ip=$(ip -4 -o addr show dev "$nd" 2>/dev/null | awk '{print $4}' | cut -d/ -f1 | paste -sd,)
      fi
      printf '%s\t%s\t%s\n' "$dev" "$nd" "$ip"
    done
}

rail_of(){  # 从逗号分隔 IP 列表提取 rail(0-7), 无匹配返回 1
  local a
  for a in ${1//,/ }; do
    if [[ "$a" =~ ^${RAIL_PREFIX}\.([0-7])\.[0-9]+$ ]]; then
      echo "${BASH_REMATCH[1]}"
      return 0
    fi
  done
  return 1
}

wait_stable(){  # 开机时 rail IP 可能晚于设备出现: 凑满 8 个或连续 3 次计数不变即止
  local i cur prev=-1 same=0
  for i in $(seq 1 $(( WAIT_SECONDS / 2 ))); do
    cur=$(get_devices | awk -F'\t' -v p="$RAIL_PREFIX" \
      '{n=split($3,A,","); for(i=1;i<=n;i++) if(A[i] ~ ("^"p"\\.[0-7]\\.[0-9]+$")) {c++; break}} END{print c+0}')
    [ "$cur" -ge 8 ] && return 0
    if [ "$cur" -gt 0 ] && [ "$cur" -eq "$prev" ]; then
      same=$((same+1)); [ "$same" -ge 3 ] && return 0
    else
      same=0
    fi
    prev=$cur
    sleep 2
  done
}

main(){
  wait_stable

  declare -A RAIL_DEV
  local extra_raw="" rail dev nd ip i e
  while IFS=$'\t' read -r dev nd ip; do
    case "$dev" in *bond*) continue ;; esac
    if rail=$(rail_of "$ip"); then
      RAIL_DEV[$rail]="$dev"
    else
      extra_raw+="$dev|$nd
"
    fi
  done < <(get_devices)

  # extra 按 netdev 名排序得到稳定编号
  local extras=()
  if [ -n "$extra_raw" ]; then
    while IFS= read -r line; do extras+=("$line"); done < <(printf '%s' "$extra_raw" | sort -t'|' -k2)
  fi

  if [ "$DRY_RUN" = "1" ]; then
    for rail in 0 1 2 3 4 5 6 7; do
      if [ -n "${RAIL_DEV[$rail]}" ]; then
        echo "PLAN rail=$rail: ${RAIL_DEV[$rail]} -> mlx5_$rail"
      else
        echo "PLAN rail=$rail: (无设备)"
      fi
    done
    i=0
    for e in "${extras[@]}"; do
      echo "PLAN extra=$i: ${e%%|*} -> mlx5_extra_$i"
      i=$((i+1))
    done
    return 0
  fi

  # ---- 阶段0: 全部腾位 (rail -> railtmp_N, extra -> extratmp_N, bond 不动) ----
  for rail in 0 1 2 3 4 5 6 7; do
    dev="${RAIL_DEV[$rail]}"
    [ -n "$dev" ] || continue
    rdma dev set "$dev" name "railtmp_$rail" 2>>"$LOG" || log "FAIL 腾位 rail=$rail dev=$dev"
  done
  i=0
  for e in "${extras[@]}"; do
    dev="${e%%|*}"
    rdma dev set "$dev" name "extratmp_$i" 2>>"$LOG" || log "FAIL 腾位 extra=$i dev=$dev"
    i=$((i+1))
  done

  # ---- 阶段1/2: 落最终名 ----
  for rail in 0 1 2 3 4 5 6 7; do
    [ -n "${RAIL_DEV[$rail]}" ] || continue
    rdma dev set "railtmp_$rail" name "mlx5_$rail" 2>>"$LOG" \
      || log "FAIL rail=$rail -> mlx5_$rail"
  done
  i=0
  for e in "${extras[@]}"; do
    rdma dev set "extratmp_$i" name "mlx5_extra_$i" 2>>"$LOG" \
      || log "FAIL extra=$i -> mlx5_extra_$i"
    i=$((i+1))
  done

  # ---- 校验: mlx5_N 的 netdev IP 必须是 <PREFIX>.N.x ----
  local fail=0
  for rail in 0 1 2 3 4 5 6 7; do
    nd=$(rdma link show 2>/dev/null | awk -v l="^mlx5_$rail/" \
      '$2 ~ l {for(i=1;i<NF;i++) if($i=="netdev") {print $(i+1); exit}}')
    ip=$(ip -4 -o addr show dev "$nd" 2>/dev/null | awk '{print $4}' | cut -d/ -f1 | paste -sd,)
    if [ -z "${RAIL_DEV[$rail]}" ]; then
      echo "RAIL_MISSING rail=$rail"
    elif [ "$(rail_of "$ip")" = "$rail" ]; then
      echo "RAIL_OK rail=$rail netdev=$nd ip=$ip"
    else
      echo "RAIL_FAIL rail=$rail netdev=$nd ip=$ip"
      fail=$((fail+1))
    fi
  done
  log "rename 完成, fail=$fail"
  exit $fail
}

main "$@"
'''

    SYSTEMD_UNIT = """[Unit]
Description=RDMA rail-consistent device naming (mlx5_0-7 = rail 0-7)
Documentation=file:///usr/local/bin/rdma-rail-rename.sh
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/local/bin/rdma-rail-rename.sh
RemainAfterExit=yes
TimeoutStartSec=180

[Install]
WantedBy=multi-user.target
"""

    SCRIPT_PATH = "/usr/local/bin/rdma-rail-rename.sh"
    UNIT_PATH = "/etc/systemd/system/rdma-rail-rename.service"

    def __init__(self, config=None, ssh_manager=None, batch_executor=None, logger=None,
                 rename_config: Optional[Dict[str, Any]] = None, versions=None):
        """初始化步骤

        Args:
            rename_config: 重命名配置，支持:
                - enabled: 是否启用 (默认True)
                - dry_run: 预览模式，只发现并打印映射计划 (默认False)
            versions: 版本配置
        """
        super().__init__(config, ssh_manager, batch_executor, logger, versions)
        self.rename_config = rename_config or {}

    @property
    def is_enabled(self) -> bool:
        return self.rename_config.get("enabled", True)

    @property
    def is_dry_run(self) -> bool:
        return self.rename_config.get("dry_run", False)

    # ------------------------------------------------------------------ 发现

    def _discover(self, host: str) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
        """在节点上收集 RDMA 设备信息并按 IP 推导 rail

        Returns:
            (设备列表, 错误信息)；成功时错误为 None
        """
        result = self.execute_on_host(host, self.DISCOVERY_CMD, timeout=60)
        if not result.get("success"):
            return None, f"设备发现命令失败: {(result.get('error') or (result.get('stdout') or '')[:200])}"

        devices = []
        for line in (result.get("stdout") or "").splitlines():
            line = line.strip()
            if not line or "|" not in line:
                continue
            parts = (line.split("|") + ["", "", "", ""])[:4]
            dev, netdev, ip, pci = (p.strip() for p in parts)
            d = {"dev": dev, "netdev": netdev, "ip": ip, "pci": pci,
                 "kind": "extra", "rail": None, "target": None}
            if "bond" in dev:
                d["kind"] = "bond"
                d["target"] = dev  # 不动
            else:
                for a in ip.split(","):
                    m = re.match(r"^10\.100\.([0-7])\.\d+$", a)
                    if m:
                        d["rail"] = int(m.group(1))
                        d["kind"] = "rail"
                        d["target"] = f"mlx5_{d['rail']}"
                        break
                if d["kind"] == "extra":
                    # 无 rail IP 的设备改到保留名, 由节点脚本统一编号
                    d["target"] = "mlx5_extra_*"
            devices.append(d)

        # extra 按 netdev 排序编号(与节点脚本一致)
        extra_idx = 0
        for d in sorted((x for x in devices if x["kind"] == "extra"),
                         key=lambda x: x["netdev"]):
            d["target"] = f"mlx5_extra_{extra_idx}"
            extra_idx += 1
        return devices, None

    def _cross_check(self, devices: List[Dict[str, Any]]) -> List[str]:
        """网卡名表交叉校验: 名表推导的 rail 应与 IP 推导一致"""
        warnings = []
        for d in devices:
            if d["kind"] != "rail":
                continue
            m = re.match(r"^(enp|ens)(\d+)", d["netdev"] or "")
            if not m:
                continue
            key = m.group(1) + m.group(2)
            if key in self.NETDEV_RAIL_TABLE and self.NETDEV_RAIL_TABLE[key] != d["rail"]:
                warnings.append(
                    f"{d['dev']} netdev={d['netdev']} ip={d['ip']}: "
                    f"名表 rail={self.NETDEV_RAIL_TABLE[key]} 与 IP rail={d['rail']} 不一致")
        return warnings

    # ------------------------------------------------------------------ 执行

    def execute(self, hosts: List[str]) -> StepResult:
        if not self.is_enabled:
            self.logger.info("RDMA rail 统一命名已禁用，跳过")
            return StepResult(
                step_id=self.step_id,
                step_name=self.step_name,
                status=StepStatus.SKIPPED,
                message="RDMA rail 统一命名已禁用",
                host_results={}
            )

        results: Dict[str, Any] = {}
        for host in hosts:
            self._rename_on_host(host, results)

        success_count = sum(1 for r in results.values() if r.get("success"))
        all_ok = bool(hosts) and success_count == len(hosts)
        return StepResult(
            step_id=self.step_id,
            step_name=self.step_name,
            status=StepStatus.SUCCESS if all_ok else StepStatus.FAILED,
            message=f"RDMA rail统一命名完成，成功: {success_count}/{len(hosts)}",
            host_results=results
        )

    def _rename_on_host(self, host: str, results: Dict[str, Any]) -> bool:
        self.logger.info(f"[{host}] RDMA rail 统一命名...")

        devices, err = self._discover(host)
        if err:
            results[host] = {"success": False, "error": err}
            return False

        rails = [d for d in devices if d["kind"] == "rail"]
        if not rails:
            # 没有 rail 口(IP 10.100.0-7.x)说明该节点没规划 rail 网络, 跳过而非失败
            msg = f"未发现任何 rail 口(IP {self.RAIL_PREFIX}.0-7.x)，跳过命名"
            self.logger.warning(f"[{host}] {msg}")
            results[host] = {"success": True, "skipped": msg, "devices": devices}
            return True

        # 打印映射表(dev/netdev/ip/PCI(KERNELS)/目标名)
        self.logger.info(f"[{host}] 设备映射计划 ({len(devices)} 个设备):")
        for d in devices:
            if d["kind"] == "rail":
                mark = f"rail{d['rail']} -> {d['target']}"
            elif d["kind"] == "bond":
                mark = "bond, 不动"
            else:
                mark = f"多余口 -> {d['target']}"
            self.logger.info(
                f"[{host}]   {d['dev']:<16} {d['netdev']:<18} {d['ip']:<16} "
                f"{d['pci']:<14} {mark}")

        for w in self._cross_check(devices):
            self.logger.warning(f"[{host}] 校验警告: {w}")

        if self.is_dry_run:
            results[host] = {"success": True, "dry_run": True, "devices": devices}
            return True

        # 1. 写入节点脚本
        write_cmd = (
            f"cat > {self.SCRIPT_PATH} << 'SCRIPT_EOF'\n"
            f"{self.RENAME_SCRIPT.strip()}\n"
            f"SCRIPT_EOF\n"
            f"chmod 755 {self.SCRIPT_PATH}"
        )
        w = self.execute_on_host(host, write_cmd, sudo=True, timeout=60)
        if not w.get("success"):
            results[host] = {"success": False, "error": "写入改名脚本失败"}
            return False

        # 2. 执行改名(自愈式, 立即生效)
        run = self.execute_on_host(host, f"bash {self.SCRIPT_PATH}", sudo=True, timeout=300)
        out = (run.get("stdout") or "") + (run.get("stderr") or "")
        rail_fail = [l for l in out.splitlines() if l.startswith("RAIL_FAIL")]
        rail_missing = [l for l in out.splitlines() if l.startswith("RAIL_MISSING")]
        for l in out.splitlines():
            if l.startswith(("RAIL_OK", "RAIL_MISSING")):
                self.logger.info(f"[{host}] {l}")
        ok = bool(run.get("success")) and not rail_fail
        if not ok:
            detail = "; ".join(rail_fail) or (run.get("error") or out[-300:])
            results[host] = {"success": False, "error": f"改名/校验失败: {detail}"}
            return False
        for l in rail_missing:
            self.logger.warning(f"[{host}] {l} (该节点缺此 rail 口)")

        # 3. 安装 systemd 开机持久化
        unit_cmd = (
            f"cat > {self.UNIT_PATH} << 'UNIT_EOF'\n"
            f"{self.SYSTEMD_UNIT.strip()}\n"
            f"UNIT_EOF\n"
            f"systemctl daemon-reload && systemctl enable {self.UNIT_PATH.split('/')[-1]}"
        )
        e = self.execute_on_host(host, unit_cmd, sudo=True, timeout=60)
        if not e.get("success"):
            results[host] = {"success": False,
                             "error": f"改名成功但持久化安装失败: {e.get('error')}"}
            return False
        self.logger.info(f"[{host}] 完成: rail 设备已命名为 mlx5_0..7, "
                         f"开机持久化已启用(rdma-rail-rename.service)")

        results[host] = {"success": True, "rails": len(rails), "missing": len(rail_missing)}
        return True

    # ------------------------------------------------------------------ 幂等/校验

    def _verify_host(self, host: str) -> Tuple[bool, str]:
        """校验 mlx5_0..7 与 rail 0..7 一一对应, 且开机持久化已安装(只读, 不改名)"""
        devices, err = self._discover(host)
        if err:
            return False, err
        if not any(d["kind"] == "rail" for d in devices):
            return True, "无rail口, 视为已配置"
        # 持久化必须与命名同时满足: 手工改过名但没装 unit 的节点不能算"已配置",
        # 否则被幂等检查跳过后, 重启即丢名
        p = self.execute_on_host(
            host,
            f"test -x {self.SCRIPT_PATH} && systemctl is-enabled rdma-rail-rename.service >/dev/null 2>&1",
            timeout=30)
        if not p.get("success"):
            return False, "命名可能正确但缺开机持久化(脚本或systemd unit未安装)"
        by_name = {d["dev"]: d for d in devices}
        problems = []
        for rail in range(8):
            d = by_name.get(f"mlx5_{rail}")
            if d is None:
                problems.append(f"mlx5_{rail}不存在")
            elif d["rail"] != rail:
                problems.append(f"mlx5_{rail}是rail{d['rail']}(netdev={d['netdev']},ip={d['ip']})")
        if problems:
            return False, "rail命名不一致: " + "; ".join(problems)
        return True, "mlx5_0..7 与 rail 0..7 一一对应"

    def is_configured(self, host: str) -> tuple:
        return self._verify_host(host)

    def post_check(self, hosts: List[str]) -> bool:
        ok = True
        for host in hosts:
            good, detail = self._verify_host(host)
            self.logger.info(f"[{host}] {detail}")
            ok = ok and good
        return ok
