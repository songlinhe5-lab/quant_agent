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

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ \
    UV_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ \
    UV_HTTP_TIMEOUT=300

# 安装 uv
RUN pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ uv

# 复制依赖声明
COPY pyproject.toml uv.lock ./

# 安装生产依赖 + 数据源 SDK（子服务节点需要直连 API）
# datasource extras 包含 tushare/akshare/futu-api
RUN for i in 1 2 3; do \
      uv sync --no-dev --no-install-project --extra datasource && break; \
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
    COLLECTOR_YFINANCE=true

# 运行时系统库
RUN sed -i 's|http://deb.debian.org|https://mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources || \
    sed -i 's|http://deb.debian.org|https://mirrors.aliyun.com|g' /etc/apt/sources.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# 从 builder 复制 .venv
COPY --from=builder /app/.venv /app/.venv

# 物理解耦：子服务完全自包含，仅复制子服务源码（含 _internal 内联的 backend 基础件），
# 不再 COPY backend/ —— 子服务不依赖 backend 包。
COPY data_subservice/ ./data_subservice/

EXPOSE 8001

CMD ["uvicorn", "data_subservice.main:app", "--host", "0.0.0.0", "--port", "8001", "--workers", "1"]
