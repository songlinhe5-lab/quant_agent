# Quant Agent Makefile
# 使用 uv 作为高性能包管理器和环境管家

.PHONY: help install format lint test lock clean

help:
	@echo "============== 🤖 Quant Agent Dev Tools =============="
	@echo "可用命令 (Available Commands):"
	@echo "  make install    - 🚀 使用 uv 安装项目依赖并初始化 pre-commit"
	@echo "  make format     - 🎨 使用 Ruff 自动格式化代码"
	@echo "  make lint       - 👀 使用 Ruff 进行代码规范检查"
	@echo "  make test       - 🧪 运行核心工具链的单元测试"
	@echo "  make lock       - 🔒 生成或更新 uv.lock 依赖锁定文件"
	@echo "  make clean      - 🧹 清除虚拟环境、缓存与编译产物"
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

test:
	@echo "🧪 正在运行沙箱测试..."
	uv run python -m unittest discover -s tools -p "*_tool.py" -t .

lock:
	@echo "🔒 正在锁定依赖树并更新 uv.lock..."
	uv lock

clean:
	@echo "🧹 正在清理所有环境与缓存..."
	rm -rf .venv .ruff_cache .pytest_cache uv.lock
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.py[co]" -delete