#!/usr/bin/env bash
# =====================================================================
# 从节点 (slave) 一键初始化脚本
# 角色: 仅作为「数据源节点」运行 data_subservice (Tushare + AKShare + YFinance)
# 与主节点经 Tailscale 内网通信；不对公网暴露 8000。
#
# 幂等保证:
#   - .env 已存在 -> 绝不覆盖用户已填的真实值，只做校验+提示
#   - .env 不存在 -> 从根目录 .env.slave.example 生成模板，提示手动填关键项
#   - 重跑脚本安全，不会清空已有配置
# =====================================================================
set -euo pipefail

# ── 路径 ──
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
TEMPLATE="${PROJECT_ROOT}/.env.slave.example"   # 模板在仓库根目录
ENV_FILE="${PROJECT_ROOT}/.env"                 # compose(slave) 实际读取 .env
cd "${PROJECT_ROOT}"

log()  { echo -e "\033[36m[init_slave]\033[0m $*"; }
warn() { echo -e "\033[33m[init_slave][WARN]\033[0m $*"; }
err()  { echo -e "\033[31m[init_slave][ERR]\033[0m $*" >&2; }

if [ ! -f "${TEMPLATE}" ]; then
  err "模板文件不存在: ${TEMPLATE}"
  exit 1
fi

# ── 1. 生成 .env（仅首次）──
if [ -f "${ENV_FILE}" ]; then
  log ".env 已存在，跳过生成（保留你的真实配置）"
else
  cp "${TEMPLATE}" "${ENV_FILE}"
  log "已从模板生成 .env: ${ENV_FILE}"
fi

# ── 2. 校验关键项是否为空/占位符（只警告，不覆盖）──
# 这些项必须由用户手动填入，脚本绝不自动改写已有值
REQUIRED_KEYS=(
  "TUSHARE_TOKEN"
  "REDIS_HOST"
  "DATA_SOURCE_HMAC_SECRET"
  "PUBLIC_IP"
)
MISSING=()
for key in "${REQUIRED_KEYS[@]}"; do
  # 取该 key 的值（去掉注释行与首尾空白）
  val="$(grep -E "^[[:space:]]*${key}=" "${ENV_FILE}" | tail -1 | cut -d= -f2- | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' || true)"
  # 判定为空 / 占位符 (<...>) / 默认值占位
  if [ -z "${val}" ] || [[ "${val}" == \<* ]]; then
    MISSING+=("${key}")
  fi
done

if [ ${#MISSING[@]} -gt 0 ]; then
  warn "以下关键项尚未填写（tushare 等数据源将处于未验证/不可用状态），请手动编辑 ${ENV_FILE} 后重启:"
  for k in "${MISSING[@]}"; do
    echo "    - ${k}"
  done
  echo ""
  echo "  填写示例:"
  echo "    TUSHARE_TOKEN=你的真实token（从 tushare.pro 个人主页获取）"
  echo "    REDIS_HOST=<主节点 Tailscale IP 或 redis 服务名>"
  echo "    DATA_SOURCE_HMAC_SECRET=<须与主节点一致>"
  echo "    PUBLIC_IP=<本节点 Tailscale/公网 IP>"
  echo ""
  echo "  填完后重启从节点容器:"
  echo "    docker compose -f docker-compose.slave.yml up -d"
fi

# ── 3. 启动（如用户带 --up 参数）──
if [[ "${1:-}" == "--up" ]]; then
  if [ ${#MISSING[@]} -gt 0 ]; then
    warn "关键项未填完，仍尝试启动（数据源可能不可用）。如需中止请 Ctrl-C。"
  fi
  log "启动从节点 (docker-compose.slave.yml)..."
  docker compose -f docker-compose.slave.yml up -d
else
  log "初始化完成。需要启动容器时执行:"
  echo "    docker compose -f docker-compose.slave.yml up -d"
fi
