# ==========================================
# Stage 1: 前端 React 构建阶段
# ==========================================
FROM node:20-alpine AS frontend-builder
WORKDIR /build/frontend

# 安装 pnpm
RUN corepack enable && corepack prepare pnpm@latest --activate

# 优先复制 package.json 利用 Docker 层缓存
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

# 复制前端源码并执行构建
COPY frontend/ .
RUN pnpm run build

# ==========================================
# Stage 2: Python 后端运行阶段
# ==========================================
FROM python:3.11-slim
WORKDIR /app

# 设置时区与环境变量
ENV TZ=Asia/Shanghai \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# 安装 uv
RUN pip install --no-cache-dir uv

# 复制项目依赖声明
COPY pyproject.toml uv.lock ./

# 安装 Python 依赖
RUN uv sync --no-dev --no-install-project

# 复制后端及工具链源码
COPY backend/ ./backend/
COPY hermes_agent/ ./hermes_agent/
COPY AGENTS.md ./

# 从第一阶段拷贝编译好的 React 产物
COPY --from=frontend-builder /build/frontend/dist ./frontend/dist

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]