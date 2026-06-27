#!/bin/bash

# Quant Agent 一键启动脚本
# 提供本地开发环境混合启动与纯 Docker 生产环境启动的支持

function cleanup() {
    echo -e "\n🛑 [System] 收到退出信号，正在安全关闭本地业务进程与 Docker 基建..."
    kill $(jobs -p) 2>/dev/null
    if [ "$DOCKER_AVAILABLE" = true ]; then
        echo "🐳 正在停止 Redis, Postgres 等中间件容器..."
        $DOCKER_CMD stop redis postgres prometheus grafana
    fi
    exit 0
}

# 捕获 Ctrl+C 中断信号，确保退出时清理由该脚本启动的后台任务
trap cleanup SIGINT SIGTERM

# 💡 确保工作目录强制锁定为脚本所在目录，避免在其他路径下执行导致相对路径失效或污染
cd "$(dirname "$0")" || exit 1

echo "====================================================="
echo "🚀 欢迎使用 Hermes Quant Agent 一键启动脚本"
echo "====================================================="

DOCKER_AVAILABLE=false
if command -v docker-compose &> /dev/null; then
    DOCKER_CMD="docker-compose"
    DOCKER_AVAILABLE=true
elif command -v docker &> /dev/null && docker compose version &> /dev/null; then
    DOCKER_CMD="docker compose"
    DOCKER_AVAILABLE=true
fi

# 检查 Docker 守护进程是否正常运行（仅在生产模式或需要中间件时检查）
if [ "$DOCKER_AVAILABLE" = true ] && ! docker info &> /dev/null; then
    echo "⚠️ 警告: Docker 已安装但守护进程未运行。"
    DOCKER_AVAILABLE=false
fi

if [ "$1" == "--docker" ] || [ "$1" == "-d" ]; then
    if [ "$DOCKER_AVAILABLE" = false ]; then
        echo "❌ 错误: 生产模式需要 Docker 支持，请先启动 Docker Desktop 或 Docker 服务。"
        exit 1
    fi
    echo "🐳 [生产模式] 正在通过 Docker 启动全栈服务..."
    $DOCKER_CMD up -d --build
    echo "✅ 全栈服务已在后台运行！可以使用 '$DOCKER_CMD logs -f quant-agent' 查看日志。"
    exit 0
fi

echo "🛠️ [开发模式] 准备启动本地调试环境..."

echo " 正在激活 Python 虚拟环境..."

if [ -d "venv" ]; then
    source venv/bin/activate
elif [ -d ".venv" ]; then
    source .venv/bin/activate
else
    echo "⚠️ 警告: 未找到 venv 或 .venv 虚拟环境，将尝试使用全局 Python 环境。"
fi

# 检查依赖是否完整
if ! python -c "import meilisearch_python_async" &> /dev/null; then
    echo "📦 正在补充安装新引入的核心依赖 (meilisearch-python-async)..."
    pip install meilisearch-python-async
fi

# 检查 RAG 服务核心依赖
if ! python -c "import chromadb" &> /dev/null; then
    echo "📦 正在补充安装 RAG 向量检索依赖 (chromadb, sentence-transformers)..."
    pip install chromadb sentence-transformers
fi

# 创建必需的日志与数据存储目录
mkdir -p logs
mkdir -p data/chroma_db

echo "🚀 正在按混合启动模式 (Docker 基建 + 本地业务) 启动开发环境..."

if [ "$DOCKER_AVAILABLE" = true ]; then
    echo "🐳 [1/3] 启动底层数据基建 (Redis + Postgres + 监控)..."
    $DOCKER_CMD up -d redis postgres prometheus grafana
    echo "⏳ 等待数据基建 (Postgres & Redis) 就绪 (最长约等待 15 秒)..."
    
    # 💡 增加智能轮询，使用 Python 真实检查 PostgreSQL 是否完全就绪 (绕过 Docker 端口欺骗)
    for i in {1..15}; do
        if python -c "from dotenv import load_dotenv; load_dotenv(); import os; from sqlalchemy import create_engine; user = os.getenv('DB_USER', 'quant_admin'); pw = os.getenv('DB_PASSWORD', 'quant_pg_secret_2026'); db = os.getenv('DB_NAME', 'quant_agent_db'); engine = create_engine(f'postgresql://{user}:{pw}@127.0.0.1:5432/{db}'); engine.connect().close()" &>/dev/null; then
            echo "✅ PostgreSQL 数据库已完全就绪！"
            break
        fi
        echo "⏳ 数据库仍在启动初始化中 ($i/15)..."
        sleep 2
    done

    # 💡 同样增加智能轮询，使用 Python 真实检查 Redis 是否完全就绪
    for i in {1..15}; do
        if python -c "from dotenv import load_dotenv; load_dotenv(); import os, redis; pw = os.getenv('REDIS_PASSWORD', 'quant_redis_secret_2026'); r = redis.Redis(host='127.0.0.1', port=6379, password=pw); r.ping()" &>/dev/null; then
            echo "✅ Redis 缓存服务已完全就绪！"
            break
        fi
        echo "⏳ Redis 仍在启动初始化中 ($i/15)..."
        sleep 1
    done
else
    echo "⚠️ 警告: 未检测到 Docker，跳过基建启动，请确保本地已运行 Redis 和 Postgres。"
fi

echo "🧹 清理可能遗留的占用 8000 端口的僵尸进程..."
# 检查 8000 端口是否被占用，如果有则安全杀掉
if command -v lsof &> /dev/null; then
    lsof -ti:8000 | xargs kill -9 2>/dev/null || true
fi

echo "🐍 [2/4] 启动独立数据生产与守护进程 (Worker)..."
export SKIP_YF_TEST=1
python backend/worker.py &

echo "🐍 [3/4] 启动 FastAPI 后端网关 (热重载模式)..."
# 💡 本地开发依然保留 --reload，但显式启用高性能的 uvloop 与 httptools 引擎
python -m uvicorn backend.main:app --port 8000 --reload --loop uvloop --http httptools --no-access-log &

echo "🖥️  [4/4] 启动 React 前端..."
# 💡 增加目录容错，并使用子 Shell () 运行，防止意外改变主进程的当前目录
if [ -d "frontend" ]; then
    (cd frontend && npm run dev) &
else
    echo "⚠️ 警告: 未找到 frontend 目录，前端跳过启动。"
fi

echo "✅ 开发环境已全面启动！按 Ctrl+C 即可安全停机并释放端口。"
wait