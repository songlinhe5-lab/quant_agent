# Quant Agent Makefile
# 使用 uv 作为高性能包管理器和环境管家

.PHONY: help install format lint test test-all test-cluster coverage dev dev-api dev-worker dev-frontend dev-infra clean

help:
	@echo "============== 🤖 Quant Agent Dev Tools =============="
	@echo ""
	@echo "📦 环境管理:"
	@echo "  make install         - 🚀 安装依赖 + 初始化 pre-commit"
	@echo "  make lock            - 🔒 生成/更新 uv.lock"
	@echo "  make clean           - 🧹 清除虚拟环境、缓存与编译产物"
	@echo ""
	@echo "🔍 代码质量:"
	@echo "  make format          - 🎨 Ruff 格式化 + 自动修复"
	@echo "  make lint            - 👀 Ruff 代码规范检查"
	@echo ""
	@echo "🧪 测试:"
	@echo "  make test            - 🧪 运行全部后端单元测试 (pytest)"
	@echo "  make test-cluster    - 🔗 运行集群通信端到端验证 (需本地 Redis)"
	@echo "  make coverage        - 📊 运行测试并生成覆盖率报告 (htmlcov/)"
	@echo ""
	@echo "🚀 本地开发 (需要 Docker 运行基础设施):"
	@echo "  make dev-infra       - 🐳 仅启动基础设施 (Redis + PostgreSQL)"
	@echo "  make dev-api         - 🐍 启动后端 API (热重载, port 8000)"
	@echo "  make dev-worker      - ⚙️  启动 Worker 守护进程"
	@echo "  make dev-frontend    - 🖥️  启动前端开发服务器 (port 5173)"
	@echo "  make dev             - 🚀 一键启动全部 (infra + api + worker + frontend)"
	@echo "===================================================="

install:
	@echo "🚀 创建虚拟环境并同步所有依赖 (包含 dev 组别)..."
	uv sync --all-extras
	@echo "🔗 初始化 git pre-commit 钩子..."
	uv run pre-commit install

format:
	@echo "🎨 正在格式化代码..."
	uv run ruff format
	uv run ruff check --fix

lint:
	@echo "👀 正在执行代码静态检查..."
	uv run ruff check

# ── 测试 ──────────────────────────────────────────────

test:
	@echo "🧪 运行全部后端单元测试..."
	uv run pytest backend/tests/ -v --tb=short

test-cluster:
	@echo "🔗 运行集群通信端到端验证 (需要本地 Redis 运行中)..."
	uv run python scripts/test_cluster_local.py

coverage:
	@echo "📊 运行测试并生成覆盖率报告..."
	uv run pytest backend/tests/ -v --tb=short --cov=backend --cov-report=term-missing --cov-report=html
	@echo "📄 覆盖率报告已生成: htmlcov/index.html"

# ── 本地开发 ──────────────────────────────────────────

dev-infra:
	@echo "🐳 启动基础设施 (Redis + PostgreSQL)..."
	docker compose up -d redis postgres
	@echo "⏳ 等待服务就绪..."
	@sleep 3
	@echo "✅ 基础设施已启动 (Redis:6379, PostgreSQL:5432)"

dev-api:
	@echo "🐍 启动后端 API (热重载模式, port 8000)..."
	SKIP_YF_TEST=1 uv run uvicorn backend.main:app --port 8000 --reload --loop uvloop --http httptools --no-access-log

dev-worker:
	@echo "⚙️  启动 Worker 守护进程..."
	SKIP_YF_TEST=1 uv run python backend/worker.py

dev-frontend:
	@echo "🖥️  启动前端开发服务器 (port 5173)..."
	cd frontend && pnpm dev

dev:
	@echo "🚀 一键启动本地全栈开发环境..."
	@echo ""
	@$(MAKE) dev-infra
	@echo ""
	@echo "🐍 启动后端 API + Worker..."
	SKIP_YF_TEST=1 uv run uvicorn backend.main:app --port 8000 --reload --loop uvloop --http httptools --no-access-log &
	SKIP_YF_TEST=1 uv run python backend/worker.py &
	@echo "🖥️  启动前端..."
	cd frontend && pnpm dev &
	@echo ""
	@echo "✅ 全栈开发环境已启动:"
	@echo "   🌐 前端:     http://localhost:5173"
	@echo "   🔌 后端 API: http://localhost:8000"
	@echo "   📊 Redis:    localhost:6379"
	@echo "   🗄️  PG:      localhost:5432"
	@echo ""
	@echo "按 Ctrl+C 停止所有服务"
	wait

clean:
	@echo "🧹 正在清理所有环境与缓存..."
	rm -rf .venv .ruff_cache .pytest_cache uv.lock
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.py[co]" -delete