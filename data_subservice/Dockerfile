# ==========================================
# Data Subservice — 分布式数据源子服务镜像
# ==========================================
# 独立 FastAPI 节点，运行在远程 VPS 上作为数据源提供者。
# 通过 ServiceRegistry 注册到主服务，持续发送心跳保活。
#
# 构建 (在项目根目录执行):
#   docker build -f data_subservice/Dockerfile -t quant-data-subservice

# ── 阶段 1：构建依赖 ──
FROM python:3.11-slim AS builder
WORKDIR /app

# 数据源 extra：全量 datasource-all（yfinance+tushare+akshare+futu+finnhub）。
# 所有节点共用同一镜像，能力隔离靠运行时 DS_CAPABILITIES，不再按地域拆分镜像。
ARG DS_EXTRA=datasource-all

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ \
    UV_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ \
    UV_HTTP_TIMEOUT=300

# 安装 uv
RUN pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ uv

# 复制依赖声明
COPY pyproject.toml uv.lock ./

# 安装生产依赖 + 全量数据源 SDK（节点能力由运行时 DS_CAPABILITIES 隔离，未声明的返回 503）
RUN for i in 1 2 3; do \
      uv sync --no-dev --no-install-project --extra ${DS_EXTRA} && break; \
      echo "uv sync failed (attempt $i), retrying..."; \
      sleep 5; \
    done

# ── 阶段 2：运行镜像 ──
FROM python:3.11-slim
WORKDIR /app

ENV TZ=Asia/Shanghai \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH" \
    YF_ROUTER_ENABLED=false \
    DS_CAPABILITIES=yfinance

# 运行时系统库
RUN sed -i 's|http://deb.debian.org|https://mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources || \
    sed -i 's|http://deb.debian.org|https://mirrors.aliyun.com|g' /etc/apt/sources.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# 从 builder 复制 .venv
COPY --from=builder /app/.venv /app/.venv

# 清理 venv 内字节码缓存与构建残留，缩小镜像 (~20-30MB)
RUN find /app/.venv -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true && \
    find /app/.venv -type f -name '*.pyc' -delete 2>/dev/null || true && \
    find /app/.venv -type d -name '*.egg-info' -exec rm -rf {} + 2>/dev/null || true && \
    find /app/.venv -type d -name 'tests' -exec rm -rf {} + 2>/dev/null || true

# 物理解耦：子服务完全自包含，仅复制子服务源码（含 _internal 内联的 backend 基础件），
# 不再 COPY backend/ —— 子服务不依赖 backend 包。
COPY data_subservice/ ./data_subservice/

EXPOSE 8001

CMD ["python", "-m", "uvicorn", "data_subservice.main:app", "--host", "0.0.0.0", "--port", "8001", "--workers", "1"]
