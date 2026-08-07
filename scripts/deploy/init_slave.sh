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
  echo "    docker compose -f docker-compose.node-bj.yml up -d"
fi

# ── 3. 启动（如用户带 --up 参数）──
if [[ "${1:-}" == "--up" ]]; then
  if [ ${#MISSING[@]} -gt 0 ]; then
    warn "关键项未填完，仍尝试启动（数据源可能不可用）。如需中止请 Ctrl-C。"
  fi
  log "启动从节点 (docker-compose.node-bj.yml)..."
  docker compose -f docker-compose.node-bj.yml up -d
else
  log "初始化完成。需要启动容器时执行:"
  echo "    docker compose -f docker-compose.node-bj.yml up -d"
fi

# 修复权限
sudo chown -R "$USER:$USER" "$DEPLOY_DIR"
chmod -R u+w "$DEPLOY_DIR"

# ==========================================
# Step 3: 校验 .env (不生成，由 CI 部署基于 .env.slave.example 注入)
# ==========================================
log_info "Step 3: 校验环境变量..."

# .env 由 CI (deploy-data-nodes) 基于仓库 .env.slave.example 模板动态生成并回填 Secrets；
# 本地手动部署时请自行: cp .env.slave.example .env 并填入真实 TUSHARE_TOKEN / REDIS_HOST / DATA_SOURCE_HMAC_SECRET
if [ ! -f "$DEPLOY_DIR/.env" ]; then
    log_warn "未检测到 $DEPLOY_DIR/.env"
    log_warn "  CI 部署: 由 GitHub Actions 自动生成 (基于 .env.slave.example)"
    log_warn "  本地部署: 请先执行  cp $DEPLOY_DIR/.env.slave.example $DEPLOY_DIR/.env  并补全以下关键配置:"
    echo ""
    echo "    ⚠️  必须填的真实值:"
    echo "    1. PUBLIC_IP=<本节点 Tailscale IP>"
    echo "    2. DS_BASE_URL=http://<本节点Tailscale IP>:8000"
    echo "    3. REDIS_HOST=<主节点 Tailscale IP>"
    echo "    4. REDIS_PASSWORD=<与主节点一致>"
    echo "    5. DATA_SOURCE_HMAC_SECRET=<与主节点一致>"
    echo "    6. TUSHARE_TOKEN=<你的 Tushare Token> | AKSHARE_API_KEY=<你的 AKShare Key>"
    echo ""
    read -p "已配置 .env 后按 Enter 继续 (或 Ctrl+C 退出)..."
fi

# 校验关键空值 (不修改文件，仅告警)
if [ -f "$DEPLOY_DIR/.env" ]; then
    for key in PUBLIC_IP REDIS_HOST REDIS_PASSWORD DATA_SOURCE_HMAC_SECRET; do
        val=$(grep -E "^${key}=" "$DEPLOY_DIR/.env" 2>/dev/null | cut -d'=' -f2-)
        if [ -z "$val" ]; then
            log_warn "  .env 中 ${key} 为空，服务可能无法正常连接主节点！"
        fi
    done
fi

# ==========================================
# Step 4: 构建 Docker 镜像
# ==========================================
log_info "Step 4: 构建 Docker 镜像 (可能需要 5-10 分钟)..."
cd "$DEPLOY_DIR"
COMPOSE_PROFILES=slave docker compose build --no-cache 2>&1 | tail -5

# ==========================================
# Step 5: 启动 Slave 采集器
# ==========================================
log_info "Step 5: 启动 Slave 采集器..."
COMPOSE_PROFILES=slave docker compose --env-file .env up -d --remove-orphans

# 等待启动
log_info "  等待服务启动 (15s)..."
sleep 15

# ==========================================
# Step 6: 验证
# ==========================================
log_info "Step 6: 验证服务状态..."

# 健康检查
HEALTH=$(curl -sf --max-time 10 http://localhost:8001/health 2>/dev/null || echo "FAILED")
if echo "$HEALTH" | grep -q '"role":"slave"'; then
    log_info "  ✅ /health 正常"
else
    log_error "  ❌ /health 异常: $HEALTH"
    COMPOSE_PROFILES=slave docker compose --env-file .env logs --tail 20
    exit 1
fi

# 检查采集器
if echo "$HEALTH" | grep -q '"yfinance"'; then
    log_info "  ✅ yfinance 采集器已启用"
fi
if echo "$HEALTH" | grep -q '"finnhub"'; then
    log_info "  ✅ finnhub 采集器已启用"
fi
if echo "$HEALTH" | grep -q '"futu"'; then
    log_info "  ✅ futu 采集器已启用"
fi

# 检查 Master Redis 连接
if echo "$HEALTH" | grep -q '"connected"'; then
    log_info "  ✅ Master Redis 连接正常"
else
    log_warn "  ⚠️ Master Redis 连接异常 (检查 Tailscale + MASTER_NODES 配置)"
fi

# 容器状态
echo ""
log_info "容器状态:"
COMPOSE_PROFILES=slave docker compose --env-file .env ps --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}"

echo ""
echo "=========================================="
echo "  ✅ Slave 节点初始化完成!"
echo "=========================================="
echo ""
echo "  常用命令:"
echo "  查看日志:   COMPOSE_PROFILES=slave docker compose --env-file .env logs -f"
echo "  重启服务:   COMPOSE_PROFILES=slave docker compose --env-file .env restart"
echo "  停止服务:   COMPOSE_PROFILES=slave docker compose --env-file .env down"
echo "  更新部署:   cd $DEPLOY_DIR && git pull && COMPOSE_PROFILES=slave docker compose --env-file .env build && COMPOSE_PROFILES=slave docker compose --env-file .env up -d"
echo ""
