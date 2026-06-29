# ==========================================
# 直接构建 Python 后端
# 前端已由 Cloudflare Pages 独立托管，不再打包进 Docker 镜像
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

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
