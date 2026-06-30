# ==========================================
# 多阶段构建 Python 后端（瘦身版）
# 前端已由 Cloudflare Pages 独立托管，不再打包进 Docker 镜像
# ==========================================

# ── 阶段 1：构建依赖 ──
FROM python:3.11-slim AS builder
WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ \
    UV_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/

# 安装 uv（使用国内镜像加速）
RUN pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ uv

# 复制依赖声明
COPY pyproject.toml uv.lock ./

# 安装生产依赖（不含 local-embedding 和 dev）
RUN uv sync --no-dev --no-install-project

# ── 阶段 2：运行镜像（只复制生产依赖）──
FROM python:3.11-slim
WORKDIR /app

ENV TZ=Asia/Shanghai \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"

# 只安装运行时必要系统库（不含编译工具）
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        libgomp1 \
        libstdc++6 \
    && rm -rf /var/lib/apt/lists/*

# 从 builder 阶段复制完整的 .venv
COPY --from=builder /app/.venv /app/.venv

# 复制后端及工具链源码
COPY backend/ ./backend/
COPY hermes_agent/ ./hermes_agent/
COPY AGENTS.md ./

EXPOSE 8000

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
