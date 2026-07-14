#!/usr/bin/env bash
# ==========================================
# 📊 YFinance 数据子服务节点初始化脚本
# ==========================================
# 用法:
#   chmod +x scripts/deploy/init_yf_node.sh
#   NODE_ID=us-yf-a ./scripts/deploy/init_yf_node.sh
#   NODE_ID=us-yf-b ./scripts/deploy/init_yf_node.sh
#
# 角色: US-YF-A / US-YF-B (YFinance 专用数据节点)
# 架构: 仅运行 data_subservice，无 Redis/PG/API
#
# 前置条件:
#   - Ubuntu 22.04+ / Debian 12+
#   - root 或 sudo 权限
#   - Tailscale 已安装并加入 Tailnet (tag:quant-yf)
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

# 节点 ID 校验
NODE_ID="${NODE_ID:-}"
if [ -z "$NODE_ID" ]; then
    log_error "NODE_ID 未设置! 用法: NODE_ID=us-yf-a $0"
    exit 1
fi

if [[ "$NODE_ID" != "us-yf-a" && "$NODE_ID" != "us-yf-b" ]]; then
    log_warn "NODE_ID=$NODE_ID (预期: us-yf-a 或 us-yf-b)"
fi

echo ""
echo "=========================================="
echo "  📊 YFinance 子服务节点初始化"
echo "  节点: $NODE_ID"
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
    log_error "Tailscale 未安装! YF 节点必须通过 Tailscale 连接 Master Redis"
    echo "  安装: curl -fsSL https://tailscale.com/install.sh | sh"
    echo "  入网: sudo tailscale up --ssh --advertise-tags=tag:quant-yf"
    exit 1
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
# Step 3: 配置 .env.yf
# ==========================================
log_info "Step 3: 配置环境变量..."

if [ -f "$DEPLOY_DIR/.env.yf" ]; then
    log_warn ".env.yf 已存在，跳过覆盖 (请手动检查配置)"
else
    if [ -f "$DEPLOY_DIR/scripts/deploy/env.yf.example" ]; then
        cp "$DEPLOY_DIR/scripts/deploy/env.yf.example" "$DEPLOY_DIR/.env.yf"
        # 自动填充 NODE_ID
        sed -i "s/NODE_ID=us-yf-a/NODE_ID=$NODE_ID/" "$DEPLOY_DIR/.env.yf"
        # 自动填充 Tailscale IP
        if [ "$TS_IP" != "unknown" ]; then
            sed -i "s/TAILSCALE_IP=100.x.x.x/TAILSCALE_IP=$TS_IP/" "$DEPLOY_DIR/.env.yf"
        fi
        log_warn ".env.yf 已从模板创建，请修改以下关键配置:"
        echo ""
        echo "  ⚠️  必须修改的配置:"
        echo "  1. REDIS_HOST=<Master Tailscale IP> (默认 100.102.223.44)"
        echo "  2. REDIS_PASSWORD=<Master Redis 密码>"
        echo "  3. DATA_SOURCE_HMAC_SECRET=<与主节点一致>"
        echo "  4. INTERNAL_API_SECRET=<与主节点一致>"
        echo ""
        echo "  编辑: nano $DEPLOY_DIR/.env.yf"
        echo ""
        read -p "配置完成后按 Enter 继续..."
    else
        log_error "模板文件不存在: scripts/deploy/env.yf.example"
        exit 1
    fi
fi

# ==========================================
# Step 4: 构建 Docker 镜像
# ==========================================
log_info "Step 4: 构建 data_subservice 镜像 (可能需要 5-10 分钟)..."
cd "$DEPLOY_DIR"
docker compose -f docker-compose.yf-node.yml build --no-cache 2>&1 | tail -10

# ==========================================
# Step 5: 启动子服务
# ==========================================
log_info "Step 5: 启动 YFinance 子服务..."
NODE_ID=$NODE_ID docker compose -f docker-compose.yf-node.yml up -d --remove-orphans

# 等待启动
log_info "  等待服务启动 (15s)..."
sleep 15

# ==========================================
# Step 6: 验证
# ==========================================
log_info "Step 6: 验证服务状态..."

# 健康检查
HEALTH=$(curl -sf --max-time 10 http://localhost:8000/health 2>/dev/null || echo "FAILED")
if echo "$HEALTH" | grep -q '"status":"healthy"'; then
    log_info "  ✅ /health 正常"
    echo "  响应: $HEALTH"
else
    log_error "  ❌ /health 异常: $HEALTH"
    docker compose -f docker-compose.yf-node.yml logs --tail 30
    exit 1
fi

# 检查节点 ID
if echo "$HEALTH" | grep -q "\"node_id\":\"$NODE_ID\""; then
    log_info "  ✅ 节点 ID 正确: $NODE_ID"
else
    log_warn "  ⚠️ 节点 ID 不匹配 (预期: $NODE_ID)"
fi

# 检查 yfinance daemon
if echo "$HEALTH" | grep -q '"yfinance_daemon_running":true'; then
    log_info "  ✅ YFinance daemon 运行中"
else
    log_warn "  ⚠️ YFinance daemon 未运行"
fi

# 容器状态
echo ""
log_info "容器状态:"
docker compose -f docker-compose.yf-node.yml ps --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}"

echo ""
echo "=========================================="
echo "  ✅ YFinance 子服务节点初始化完成!"
echo "=========================================="
echo ""
echo "  节点:     $NODE_ID"
echo "  Tailscale IP: $TS_IP"
echo ""
echo "  常用命令:"
echo "  查看日志:   docker compose -f docker-compose.yf-node.yml logs -f"
echo "  重启服务:   docker compose -f docker-compose.yf-node.yml restart"
echo "  停止服务:   docker compose -f docker-compose.yf-node.yml down"
echo "  更新部署:   cd $DEPLOY_DIR && git pull && docker compose -f docker-compose.yf-node.yml build && NODE_ID=$NODE_ID docker compose -f docker-compose.yf-node.yml up -d"
echo ""
