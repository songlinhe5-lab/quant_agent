#!/usr/bin/env bash
# ==========================================
# 🌊 Slave 从采集节点一键初始化脚本
# ==========================================
# 用法:
#   chmod +x scripts/deploy/init_slave.sh
#   ./scripts/deploy/init_slave.sh
#
# 前置条件:
#   - Ubuntu 22.04+ / Debian 12+
#   - root 或 sudo 权限
#   - Tailscale 已安装并加入 Tailnet
# ==========================================
set -euo pipefail

DEPLOY_DIR="/opt/quant-agent"
REPO_URL="https://github.com/stephenhatch/quant_agent.git"
BRANCH="main"

# 颜色
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

echo ""
echo "=========================================="
echo "  🌊 Quant Agent Slave 节点初始化"
echo "=========================================="
echo ""

# ==========================================
# Step 1: 前置检查
# ==========================================
log_info "Step 1: 检查前置条件..."

# Docker
if ! command -v docker &>/dev/null; then
    log_error "Docker 未安装! 请先安装: curl -fsSL https://get.docker.com | sh"
    exit 1
fi
log_info "  Docker: $(docker --version | head -1)"

# Docker Compose
if ! docker compose version &>/dev/null; then
    log_error "Docker Compose 插件未安装!"
    exit 1
fi
log_info "  Docker Compose: $(docker compose version --short 2>/dev/null || echo 'installed')"

# Tailscale
if ! command -v tailscale &>/dev/null; then
    log_warn "Tailscale 未安装! Slave 需要 Tailscale 连接 Master Redis"
    log_warn "安装: curl -fsSL https://tailscale.com/install.sh | sh && sudo tailscale up"
    read -p "是否继续? (y/N) " -n 1 -r; echo
    [[ $REPLY =~ ^[Yy]$ ]] || exit 1
else
    TS_IP=$(tailscale ip -4 2>/dev/null | head -1 || echo "unknown")
    log_info "  Tailscale IP: ${TS_IP}"
fi

# ==========================================
# Step 2: 克隆/更新代码仓库
# ==========================================
log_info "Step 2: 准备代码仓库..."

if [ -d "$DEPLOY_DIR/.git" ]; then
    log_info "  仓库已存在，拉取最新代码..."
    cd "$DEPLOY_DIR"
    git fetch origin "$BRANCH"
    git reset --hard "origin/$BRANCH"
else
    log_info "  克隆仓库到 ${DEPLOY_DIR}..."
    sudo mkdir -p "$(dirname $DEPLOY_DIR)"
    sudo git clone --branch "$BRANCH" --depth 1 "$REPO_URL" "$DEPLOY_DIR"
    cd "$DEPLOY_DIR"
fi

# 修复权限
sudo chown -R "$USER:$USER" "$DEPLOY_DIR"
chmod -R u+w "$DEPLOY_DIR"

# ==========================================
# Step 3: 配置 .env
# ==========================================
log_info "Step 3: 配置环境变量..."

if [ -f "$DEPLOY_DIR/.env" ]; then
    log_warn ".env 已存在，跳过覆盖 (请手动检查配置)"
else
    if [ -f "$DEPLOY_DIR/scripts/deploy/env.slave.example" ]; then
        cp "$DEPLOY_DIR/scripts/deploy/env.slave.example" "$DEPLOY_DIR/.env"
        log_warn ".env 已从模板创建，请修改以下关键配置:"
        echo ""
        echo "  ⚠️  必须修改的配置:"
        echo "  1. SLAVE_ID=<你的节点ID>"
        echo "  2. NODE_HOST=<你的 Tailscale IP>"
        echo "  3. MASTER_NODES=[{...}] (填入 Master Tailscale IP + Redis 密码)"
        echo "  4. FINNHUB_API_KEY=<你的 key>"
        echo "  5. INTERNAL_API_SECRET=<与主节点一致>"
        echo ""
        echo "  编辑: nano $DEPLOY_DIR/.env"
        echo ""
        read -p "配置完成后按 Enter 继续..."
    else
        log_error "模板文件不存在: scripts/deploy/env.slave.example"
        exit 1
    fi
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
COMPOSE_PROFILES=slave docker compose up -d --remove-orphans

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
    COMPOSE_PROFILES=slave docker compose logs --tail 20
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
COMPOSE_PROFILES=slave docker compose ps --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}"

echo ""
echo "=========================================="
echo "  ✅ Slave 节点初始化完成!"
echo "=========================================="
echo ""
echo "  常用命令:"
echo "  查看日志:   COMPOSE_PROFILES=slave docker compose logs -f"
echo "  重启服务:   COMPOSE_PROFILES=slave docker compose restart"
echo "  停止服务:   COMPOSE_PROFILES=slave docker compose down"
echo "  更新部署:   cd $DEPLOY_DIR && git pull && COMPOSE_PROFILES=slave docker compose build && COMPOSE_PROFILES=slave docker compose up -d"
echo ""
