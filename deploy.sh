#!/usr/bin/env bash
# ==========================================
# 🚀 Quant Agent 多节点一键部署脚本
# ==========================================
# 用法:
#   ./deploy.sh              # 部署当前节点 (根据 .env 中 NODE_ROLE 自动识别)
#   ./deploy.sh beijing      # 强制以北京主节点模式部署
#   ./deploy.sh overseas     # 强制以海外节点模式部署
#   ./deploy.sh --dry-run    # 仅打印将执行的操作，不实际执行

set -euo pipefail

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ==========================================
# 参数解析
# ==========================================
DRY_RUN=false
NODE_ROLE_OVERRIDE=""

for arg in "$@"; do
    case "$arg" in
        --dry-run)
            DRY_RUN=true
            ;;
        beijing|overseas|yfinance)
            NODE_ROLE_OVERRIDE="$arg"
            ;;
        -h|--help)
            echo "用法: ./deploy.sh [beijing|overseas|yfinance] [--dry-run]"
            echo ""
            echo "节点角色:"
            echo "  beijing   北京主节点 (akshare + API网关 + Prometheus/Grafana 监控)"
            echo "  overseas  海外节点 (futu + finnhub)"
            echo "  yfinance  YFinance 独立采集节点 (多 VPS 冗余，可部署多个)"
            echo ""
            echo "选项:"
            echo "  --dry-run  仅打印操作，不实际执行"
            exit 0
            ;;
        *)
            echo -e "${RED}❌ 未知参数: $arg${NC}"
            echo "用法: ./deploy.sh [beijing|overseas] [--dry-run]"
            exit 1
            ;;
    esac
done

# ==========================================
# 节点角色识别
# ==========================================
if [ -n "$NODE_ROLE_OVERRIDE" ]; then
    NODE_ROLE="$NODE_ROLE_OVERRIDE"
elif [ -f .env ]; then
    NODE_ROLE=$(grep -E '^NODE_ROLE=' .env | cut -d= -f2 || echo "")
fi

NODE_ROLE="${NODE_ROLE:-beijing}"  # 默认北京节点

case "$NODE_ROLE" in
    beijing)
        COMPOSE_PROFILES="monitoring"
        COMPOSE_FILE="docker-compose.yml"
        NODE_DESC="🇨🇳 北京主节点 (akshare + API网关 + 监控)"
        ENV_OVERRIDES=("FUTU_ENABLED=false" "FINNHUB_ENABLED=false")
        ;;
    overseas)
        COMPOSE_PROFILES=""
        COMPOSE_FILE="docker-compose.yml"
        NODE_DESC="🌏 海外节点 (futu + finnhub)"
        ENV_OVERRIDES=("FUTU_ENABLED=true" "FINNHUB_ENABLED=true")
        ;;
    yfinance)
        COMPOSE_PROFILES=""
        COMPOSE_FILE="docker-compose.yfinance.yml"
        NODE_DESC="📊 YFinance 独立采集节点 (多 VPS 冗余)"
        ENV_OVERRIDES=("NODE_ROLE=yfinance")
        ;;
    *)
        echo -e "${RED}❌ 未知的节点角色: $NODE_ROLE${NC}"
        echo "支持的角色: beijing, overseas, yfinance"
        exit 1
        ;;
esac

# 构建 compose 命令 (不同节点角色使用不同的 compose 文件)
DC="docker compose -f $COMPOSE_FILE"

# ==========================================
# 部署信息输出
# ==========================================
echo -e "${CYAN}╔══════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║   🚀 Quant Agent 多节点部署系统          ║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════╝${NC}"
echo ""
echo -e "${GREEN}📋 部署配置:${NC}"
echo "  节点角色:    $NODE_DESC"
echo "  Compose 文件:  $COMPOSE_FILE"
echo "  Compose Profile: ${COMPOSE_PROFILES:-default}"
echo "  工作目录:    $(pwd)"
echo "  Dry Run:     $DRY_RUN"
echo ""

if [ "$DRY_RUN" = true ]; then
    echo -e "${YELLOW}⚠️  DRY RUN 模式，以下命令不会实际执行${NC}"
    echo ""
fi

# ==========================================
# 步骤执行函数
# ==========================================
run_step() {
    local step_num="$1"
    local step_desc="$2"
    shift 2
    echo -e "${CYAN}[$step_num] $step_desc${NC}"
    if [ "$DRY_RUN" = true ]; then
        echo "  → (dry-run) $*"
    else
        eval "$@"
    fi
}

# ==========================================
# 1. 前置检查
# ==========================================
run_step "1/7" "🔍 前置环境检查" '
    # 检查 Docker
    if ! command -v docker &> /dev/null; then
        echo -e "${RED}❌ Docker 未安装${NC}"
        exit 1
    fi
    DOCKER_VERSION=$(docker --version)
    echo "  ✅ Docker: $DOCKER_VERSION"

    # 检查 Docker Compose
    if ! docker compose version &> /dev/null; then
        echo -e "${RED}❌ Docker Compose V2 未安装${NC}"
        exit 1
    fi
    COMPOSE_VERSION=$(docker compose version --short)
    echo "  ✅ Docker Compose: $COMPOSE_VERSION"

    # 检查 .env 文件
    if [ ! -f .env ]; then
        echo -e "${YELLOW}⚠️  .env 文件不存在，从模板创建...${NC}"
        if [ -f .env.example ]; then
            cp .env.example .env
            echo "  ✅ 已从 .env.example 创建 .env"
            echo -e "  ${YELLOW}⚠️  请编辑 .env 填入真实的 API Key 和密钥后重新运行${NC}"
            exit 0
        else
            echo -e "${RED}❌ .env.example 模板不存在${NC}"
            exit 1
        fi
    fi
    echo "  ✅ .env 文件存在"
'

# ==========================================
# 2. 拉取最新代码
# ==========================================
run_step "2/7" "📥 拉取最新代码" '
    if [ -d .git ]; then
        git fetch origin main 2>/dev/null || echo "  ⚠️  fetch 失败，使用本地代码"
        LOCAL=$(git rev-parse HEAD 2>/dev/null)
        REMOTE=$(git rev-parse origin/main 2>/dev/null || echo "$LOCAL")
        if [ "$LOCAL" != "$REMOTE" ]; then
            echo "  本地: $(git rev-parse --short HEAD)"
            echo "  远程: $(git rev-parse --short origin/main 2>/dev/null || echo "N/A")"
            git reset --hard origin/main
            echo "  ✅ 代码已更新"
        else
            echo "  ✅ 已是最新"
        fi
    else
        echo "  ⚠️  非 Git 仓库，跳过代码更新"
    fi
'

# ==========================================
# 3. 记录当前镜像 (回滚用)
# ==========================================
run_step "3/7" "📸 记录当前镜像 ID (回滚用)" '
    PREV_IMAGE=$(docker compose -f $COMPOSE_FILE ps -q quant-agent 2>/dev/null | head -1 | \
        xargs -I{} docker inspect --format="{{.Id}}" {} 2>/dev/null || echo "none")
    echo "  当前镜像: ${PREV_IMAGE:0:20}..."
'

# ==========================================
# 4. 停掉旧容器
# ==========================================
run_step "4/7" "🛑 停掉旧容器释放内存" "
    COMPOSE_PROFILES=$COMPOSE_PROFILES docker compose -f $COMPOSE_FILE down || true
'

# ==========================================
# 5. 构建新镜像
# ==========================================
run_step "5/7" "🔨 构建 Docker 镜像 (VPS 内存有限，已先停容器释放空间)" '
    docker compose -f $COMPOSE_FILE build --no-cache
'

# ==========================================
# 6. 启动服务
# ==========================================
run_step "6/7" "🚀 启动服务 (Profile: ${COMPOSE_PROFILES:-default})" "
    COMPOSE_PROFILES=$COMPOSE_PROFILES docker compose -f $COMPOSE_FILE up -d --remove-orphans
'

# ==========================================
# 7. 健康检查 + 清理
# ==========================================
run_step "7/7" "⏳ 等待服务启动并验证健康状态" '
    echo "  等待 30 秒..."
    sleep 30

    HEALTH=$(curl -sf --max-time 10 http://localhost:8000/api/v1/health 2>/dev/null || echo "UNHEALTHY")
    if [ "$HEALTH" = "UNHEALTHY" ]; then
        echo -e "  ${RED}❌ 健康检查失败！${NC}"
        echo "  查看日志: docker compose logs quant-agent --tail 50"
        exit 1
    fi
    echo "  ✅ 健康检查通过"

    # 清理
    echo "  🧹 清理旧镜像和缓存..."
    docker image prune -f >/dev/null 2>&1 || true
    docker builder prune -af --filter "until=168h" >/dev/null 2>&1 || true
    docker volume prune -f >/dev/null 2>&1 || true
'

# ==========================================
# 部署结果
# ==========================================
echo ""
echo -e "${GREEN}╔══════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║   ✅ 部署成功！                          ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════╝${NC}"
echo ""
echo -e "${GREEN}📋 部署摘要:${NC}"
echo "  节点角色:  $NODE_DESC"
echo ""

if [ "$DRY_RUN" = false ]; then
    echo -e "${CYAN}🐳 容器状态:${NC}"
    COMPOSE_PROFILES=$COMPOSE_PROFILES docker compose -f $COMPOSE_FILE ps --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null || \
        docker compose -f $COMPOSE_FILE ps
    echo ""
    echo -e "${CYAN}💾 磁盘使用:${NC}"
    df -h / | tail -1
    echo ""
    echo -e "${CYAN}🔧 常用运维命令:${NC}"
    echo "  查看日志:        docker compose -f $COMPOSE_FILE logs -f"
    echo "  重启服务:        docker compose -f $COMPOSE_FILE restart"
    echo "  查看内存:        docker stats --no-stream"
    echo "  进入容器调试:    docker exec -it quant_app bash"
fi
