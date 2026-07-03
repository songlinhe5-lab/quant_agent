#!/bin/bash
# ==========================================
# Quant Agent 本地开发环境一键启动脚本
# ==========================================
# 用法:
#   ./start.sh          # 开发模式 (Docker 基建 + 本地后端/前端)
#   ./start.sh -d       # Docker 全栈模式 (全部容器化)
#   ./start.sh --infra  # 仅启动基础设施 (Redis + PostgreSQL)
#   ./start.sh --stop   # 停止所有本地服务 (后端/前端/Worker)
# ==========================================

set -e

# 锁定工作目录为脚本所在目录
cd "$(dirname "$0")" || exit 1

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info()  { echo -e "${GREEN}✅ $1${NC}"; }
log_warn()  { echo -e "${YELLOW}⚠️  $1${NC}"; }
log_error() { echo -e "${RED}❌ $1${NC}"; }
log_step()  { echo -e "${BLUE}🚀 $1${NC}"; }

# ==========================================
# 模式: 停止所有服务
# ==========================================
if [ "$1" = "--stop" ]; then
    log_step "正在停止所有本地服务..."
    STOPPED=0

    # 停止后端 uvicorn 进程
    BACKEND_PIDS=$(ps aux | grep "uvicorn backend.main:app" | grep -v grep | awk '{print $2}')
    if [ -n "$BACKEND_PIDS" ]; then
        echo $BACKEND_PIDS | xargs kill -9 2>/dev/null || true
        log_info "已停止后端 API (uvicorn)"
        STOPPED=$((STOPPED + 1))
    fi

    # 停止 Worker 进程
    WORKER_PIDS=$(ps aux | grep "python backend/worker.py" | grep -v grep | awk '{print $2}')
    if [ -n "$WORKER_PIDS" ]; then
        echo $WORKER_PIDS | xargs kill -9 2>/dev/null || true
        log_info "已停止 Worker"
        STOPPED=$((STOPPED + 1))
    fi

    # 停止前端 Vite 进程
    FRONTEND_PIDS=$(ps aux | grep "vite.js" | grep "quant_agent" | grep -v grep | awk '{print $2}')
    if [ -n "$FRONTEND_PIDS" ]; then
        echo $FRONTEND_PIDS | xargs kill -9 2>/dev/null || true
        log_info "已停止前端 (Vite)"
        STOPPED=$((STOPPED + 1))
    fi

    # 停止 Docker 基础设施
    if command -v docker &>/dev/null && docker info &>/dev/null 2>&1; then
        docker compose stop redis postgres 2>/dev/null && log_info "已停止 Docker 基础设施 (Redis + PostgreSQL)" || true
    fi

    # 清理端口占用
    lsof -ti:8000 | xargs kill -9 2>/dev/null || true
    lsof -ti:3000 | xargs kill -9 2>/dev/null || true

    if [ $STOPPED -eq 0 ]; then
        log_warn "未发现运行中的服务"
    else
        log_info "已停止 $STOPPED 个服务"
    fi
    exit 0
fi

# 优雅退出：捕获 Ctrl+C，清理所有子进程
cleanup() {
    echo -e "\n${YELLOW}🛑 正在安全关闭本地服务...${NC}"
    kill $(jobs -p) 2>/dev/null || true
    # 可选：停止 Docker 基建
    if [ "$STOP_INFRA" = "true" ]; then
        echo "🐳 正在停止基础设施容器..."
        docker compose stop redis postgres 2>/dev/null || true
    fi
    exit 0
}
trap cleanup SIGINT SIGTERM

STOP_INFRA="false"

# ==========================================
# Docker 检测
# ==========================================
DOCKER_AVAILABLE=false
if command -v docker &>/dev/null && docker compose version &>/dev/null; then
    DOCKER_AVAILABLE=true
fi

if [ "$DOCKER_AVAILABLE" = true ] && ! docker info &>/dev/null 2>&1; then
    log_warn "Docker 已安装但守护进程未运行"
    DOCKER_AVAILABLE=false
fi

# ==========================================
# 模式: Docker 全栈
# ==========================================
if [ "$1" = "--docker" ] || [ "$1" = "-d" ]; then
    if [ "$DOCKER_AVAILABLE" = false ]; then
        log_error "Docker 全栈模式需要 Docker 支持"
        exit 1
    fi
    log_step "[Docker 模式] 启动全栈服务..."
    docker compose up -d --build
    log_info "全栈服务已在后台运行！"
    echo "   查看日志: docker compose logs -f quant-agent"
    exit 0
fi

# ==========================================
# 模式: 仅基础设施
# ==========================================
if [ "$1" = "--infra" ]; then
    if [ "$DOCKER_AVAILABLE" = false ]; then
        log_error "需要 Docker 来启动基础设施"
        exit 1
    fi
    log_step "启动基础设施 (Redis + PostgreSQL)..."
    docker compose up -d redis postgres
    log_info "基础设施已启动"
    echo "   Redis:      localhost:6379"
    echo "   PostgreSQL: localhost:5432"
    exit 0
fi

# ==========================================
# 模式: 本地开发 (默认)
# ==========================================
echo "====================================================="
echo "🚀 Quant Agent 本地开发环境"
echo "====================================================="
echo ""

# ------------------------------------------
# [1/4] 基础设施 (Docker)
# ------------------------------------------
if [ "$DOCKER_AVAILABLE" = true ]; then
    log_step "[1/4] 启动基础设施 (Redis + PostgreSQL)..."

    # 检查是否已经在运行
    if docker compose ps redis postgres 2>/dev/null | grep -q "Up"; then
        log_info "基础设施已在运行中，跳过启动"
    else
        docker compose up -d redis postgres
        STOP_INFRA="true"
    fi

    # 等待 PostgreSQL 就绪
    echo -n "   等待 PostgreSQL 就绪"
    for i in {1..20}; do
        if docker compose exec -T postgres pg_isready -U quant_admin &>/dev/null; then
            echo ""
            log_info "PostgreSQL 已就绪"
            break
        fi
        echo -n "."
        sleep 1
    done
    echo ""

    # 等待 Redis 就绪
    echo -n "   等待 Redis 就绪"
    for i in {1..10}; do
        if docker compose exec -T redis redis-cli -a "${REDIS_PASSWORD:-tradingagents123}" ping &>/dev/null; then
            echo ""
            log_info "Redis 已就绪"
            break
        fi
        echo -n "."
        sleep 1
    done
    echo ""
else
    log_warn "未检测到 Docker，请确保本地已运行 Redis (6379) 和 PostgreSQL (5432)"
fi

# ------------------------------------------
# [2/4] Python 虚拟环境
# ------------------------------------------
log_step "[2/4] 激活 Python 虚拟环境..."

if [ -d ".venv" ]; then
    source .venv/bin/activate
    log_info "已激活 .venv (Python $(python --version 2>&1 | cut -d' ' -f2))"
elif [ -d "venv" ]; then
    source venv/bin/activate
    log_info "已激活 venv"
else
    log_error "未找到虚拟环境，请先运行: uv venv && uv sync"
    exit 1
fi

# ------------------------------------------
# [3/4] 后端 API + Worker
# ------------------------------------------
log_step "[3/4] 启动后端服务..."

# 清理可能占用端口的僵尸进程
if command -v lsof &>/dev/null; then
    lsof -ti:8000 | xargs kill -9 2>/dev/null || true
fi

# 启动 Worker (后台)
export SKIP_YF_TEST=1
python backend/worker.py &
WORKER_PID=$!
log_info "Worker 已启动 (PID: $WORKER_PID)"

# 启动 FastAPI 后端 (后台，热重载)
python -m uvicorn backend.main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --reload \
    --reload-dir backend \
    --reload-dir hermes_agent \
    --loop uvloop \
    --http httptools \
    --no-access-log &
BACKEND_PID=$!
log_info "后端 API 已启动 (PID: $BACKEND_PID, http://localhost:8000)"

# 等待后端就绪
echo -n "   等待后端就绪"
for i in {1..30}; do
    if curl -sf http://localhost:8000/api/v1/health &>/dev/null; then
        echo ""
        log_info "后端 API 已就绪"
        break
    fi
    echo -n "."
    sleep 1
done
echo ""

# ------------------------------------------
# [4/4] 前端 Dev Server
# ------------------------------------------
log_step "[4/4] 启动前端开发服务器..."

if [ -d "frontend" ]; then
    # 检查前端依赖
    if [ ! -d "frontend/node_modules" ]; then
        log_warn "前端依赖未安装，正在安装..."
        (cd frontend && pnpm install)
    fi

    # 清理可能占用 3000 端口的进程
    if command -v lsof &>/dev/null; then
        lsof -ti:3000 | xargs kill -9 2>/dev/null || true
    fi

    (cd frontend && pnpm dev) &
    FRONTEND_PID=$!
    log_info "前端已启动 (PID: $FRONTEND_PID, http://localhost:3000)"
else
    log_warn "未找到 frontend 目录，前端跳过启动"
fi

# ==========================================
# 启动完成
# ==========================================
echo ""
echo "====================================================="
echo "🎉 本地开发环境已全面启动！"
echo "====================================================="
echo ""
echo "  📊 服务状态:"
echo "     • Redis:       localhost:6379"
echo "     • PostgreSQL:  localhost:5432"
echo "     • 后端 API:    http://localhost:8000"
echo "     • 前端:        http://localhost:3000"
echo ""
echo "  🔑 默认账号: admin / admin"
echo ""
echo "  按 Ctrl+C 安全停机"
echo "====================================================="
echo ""

# 等待所有后台进程
wait
