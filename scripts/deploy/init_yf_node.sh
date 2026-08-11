#!/usr/bin/env bash
# ==========================================
# 📊 YFinance 数据子服务节点初始化脚本
# ==========================================
# 用法:
#   chmod +x scripts/deploy/init_yf_node.sh
#   NODE_ID=us-yf-a ./scripts/deploy/init_yf_node.sh
#   NODE_ID=us-yf-b ./scripts/deploy/init_yf_node.sh
#
# 角色：US-YF-A / US-YF-B (YFinance 专用子服务节点)
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
    log_error "NODE_ID 未设置! 用法: NODE_ID=us-yf-s2 $0"
    exit 1
fi

# 兼容旧别名 us-yf-a/us-yf-b -> 映射到现有 s2/s3 节点
case "$NODE_ID" in
    us-yf-a) NODE_ID="us-yf-s2" ;;
    us-yf-b) NODE_ID="us-yf-s3" ;;
esac

# 解析对应 compose 文件 (仓库内实际为 docker-compose.node-s2/s3/s4.yml)
NODE_SEQ="${NODE_ID#us-yf-s}"
COMPOSE_FILE="docker-compose.node-s${NODE_SEQ}.yml"
if [ ! -f "$DEPLOY_DIR/$COMPOSE_FILE" ]; then
    log_error "未找到 compose 文件: $COMPOSE_FILE (NODE_ID=$NODE_ID)"
    exit 1
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
# Step 1.5: 宿主服务对容器可达性预检 (关键!)
# ==========================================
# 容器内 127.0.0.1 指向【容器自身】而非宿主。容器经 host.docker.internal
# (= docker0 网关) 访问宿主 Redis / Futu OpenD 时，若宿主服务仅 bind 127.0.0.1
# 会直接 Connection refused，表现为「心跳写入失败 → 主服务判节点离线 → 熔断」。
# 此处提前暴露问题，避免部署后花数小时排查。
log_info "Step 1.5: 检查宿主服务对容器的可达性..."

DOCKER_GW=$(ip -4 addr show docker0 2>/dev/null | grep -oP '(?<=inet )[\d.]+' | head -1 || true)
DOCKER_GW="${DOCKER_GW:-172.17.0.1}"
log_info "  docker0 网关: ${DOCKER_GW}"

# 探测宿主端口经网关是否可达
probe_gw_port() {
    timeout 3 bash -c "echo > /dev/tcp/${DOCKER_GW}/$1" 2>/dev/null
}
# 探测宿主端口在 loopback 上是否存在（区分「服务没跑」和「服务只 bind loopback」）
probe_lo_port() {
    timeout 3 bash -c "echo > /dev/tcp/127.0.0.1/$1" 2>/dev/null
}

GW_CHECK_FAILED=0

# --- Redis (可直接改 bind，不需要 socat) ---
if probe_gw_port 6379; then
    log_info "  ✅ Redis 经网关 ${DOCKER_GW}:6379 可达"
elif probe_lo_port 6379; then
    GW_CHECK_FAILED=1
    log_error "  ❌ Redis 仅监听 127.0.0.1，容器无法访问!"
    echo "     修复: 编辑 /etc/redis/redis.conf，将 bind 行改为"
    echo "           bind 127.0.0.1 ${TS_IP} ${DOCKER_GW}"
    echo "           然后 sudo systemctl restart redis-server"
else
    log_warn "  ⚠️ Redis 未在本机运行 (跨节点部署请在 .env 设 REDIS_HOST 为主节点 Tailscale IP)"
fi

# --- Futu OpenD (严禁改 OpenD.xml，只能 socat 转发) ---
if probe_gw_port 11111; then
    log_info "  ✅ Futu OpenD 经网关 ${DOCKER_GW}:11111 可达"
elif probe_lo_port 11111; then
    log_warn "  ⚠️ Futu OpenD 仅监听 127.0.0.1，容器无法访问"
    echo "     ⚠️ 严禁修改 OpenD.xml (会触发富途设备二次验证)，须用 socat 转发。"
    if [ "${AUTO_SETUP_GW_FORWARD:-0}" = "1" ]; then
        log_info "     AUTO_SETUP_GW_FORWARD=1 → 自动安装转发服务..."
        sudo apt-get install -y socat >/dev/null 2>&1 || log_warn "     socat 安装失败，请手动安装"
        sudo cp "$DEPLOY_DIR/scripts/deploy/docker-gw-forward@.service" /etc/systemd/system/ 2>/dev/null \
            || log_warn "     unit 文件复制失败 (仓库尚未拉取?)"
        sudo systemctl daemon-reload
        sudo systemctl enable --now docker-gw-forward@11111
        sleep 2
        if probe_gw_port 11111; then
            log_info "     ✅ 转发已生效"
        else
            GW_CHECK_FAILED=1
            log_error "     ❌ 转发仍不可达，请检查 systemctl status docker-gw-forward@11111"
        fi
    else
        GW_CHECK_FAILED=1
        echo "     修复(固化为 systemd，开机自启):"
        echo "       sudo apt-get install -y socat"
        echo "       sudo cp $DEPLOY_DIR/scripts/deploy/docker-gw-forward@.service /etc/systemd/system/"
        echo "       sudo systemctl daemon-reload"
        echo "       sudo systemctl enable --now docker-gw-forward@11111"
        echo "     或重跑本脚本时加 AUTO_SETUP_GW_FORWARD=1 自动完成。"
    fi
else
    log_info "  ℹ️ 本机未运行 Futu OpenD (纯 YF 节点正常，跳过)"
fi

if [ "$GW_CHECK_FAILED" = "1" ]; then
    log_error "宿主可达性预检未通过。继续部署会导致节点心跳失败 / Futu 熔断。"
    read -p "仍要继续? (yes/N) " -r _ans
    [ "$_ans" = "yes" ] || exit 1
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
    if [ -f "$DEPLOY_DIR/scripts/deploy/env.yf-node.example" ]; then
        cp "$DEPLOY_DIR/scripts/deploy/env.yf-node.example" "$DEPLOY_DIR/.env"
        # 自动填充 NODE_ID
        sed -i "s/NODE_ID=us-yf-a/NODE_ID=$NODE_ID/" "$DEPLOY_DIR/.env"
        # 自动填充 Tailscale IP
        if [ "$TS_IP" != "unknown" ]; then
            sed -i "s/TAILSCALE_IP=100.x.x.x/TAILSCALE_IP=$TS_IP/" "$DEPLOY_DIR/.env"
        fi
        log_warn ".env 已从模板创建，请修改以下关键配置:"
        echo ""
        echo "  ⚠️  必须修改的配置:"
        echo "  1. REDIS_HOST=<Master Tailscale IP> (默认 100.102.223.44)"
        echo "  2. REDIS_PASSWORD=<Master Redis 密码>"
        echo "  3. DATA_SOURCE_HMAC_SECRET=<与主节点一致>"
        echo "  4. INTERNAL_API_SECRET=<与主节点一致>"
        echo ""
        echo "  编辑: nano $DEPLOY_DIR/.env"
        echo ""
        read -p "配置完成后按 Enter 继续..."
    else
        log_error "模板文件不存在: scripts/deploy/env.yf-node.example"
        exit 1
    fi
fi

# ==========================================
# Step 4: 构建 Docker 镜像
# ==========================================
log_info "Step 4: 构建 data_subservice 镜像 (可能需要 5-10 分钟)..."
cd "$DEPLOY_DIR"
docker compose -f $COMPOSE_FILE build --no-cache 2>&1 | tail -10

# ==========================================
# Step 5: 启动子服务
# ==========================================
log_info "Step 5: 启动 YFinance 子服务..."
NODE_ID=$NODE_ID docker compose -f $COMPOSE_FILE up -d --remove-orphans

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
    docker compose -f $COMPOSE_FILE logs --tail 30
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
docker compose -f $COMPOSE_FILE ps --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}"

echo ""
echo "=========================================="
echo "  ✅ YFinance 子服务节点初始化完成!"
echo "=========================================="
echo ""
echo "  节点:     $NODE_ID"
echo "  Tailscale IP: $TS_IP"
echo ""
echo "  常用命令:"
echo "  查看日志:   docker compose -f $COMPOSE_FILE logs -f"
echo "  重启服务:   docker compose -f $COMPOSE_FILE restart"
echo "  停止服务:   docker compose -f $COMPOSE_FILE down"
echo "  更新部署:   cd $DEPLOY_DIR && git pull && docker compose -f $COMPOSE_FILE build && NODE_ID=$NODE_ID docker compose -f $COMPOSE_FILE up -d"
echo ""
