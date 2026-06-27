# ==========================================
# Stage 1: 前端 React 构建阶段
# ==========================================
FROM node:20-alpine AS frontend-builder
WORKDIR /build/frontend

# 优先复制 package.json 利用 Docker 层缓存
COPY frontend/package*.json ./
RUN npm install

# 复制前端源码并执行构建
COPY frontend/ .
RUN npm run build

# ==========================================
# Stage 2: Python 后端运行阶段
# ==========================================
FROM python:3.11-slim
WORKDIR /app

# 设置时区与环境变量，防止 Python 缓冲标准输出
ENV TZ=Asia/Shanghai \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# 安装 Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制后端及工具链源码
COPY backend/ ./backend/
COPY hermes_agent/ ./hermes_agent/
COPY AGENTS.md ./

# 从第一阶段拷贝编译好的 React 产物到指定的挂载目录
# 注意: 如果你使用 Create React App，请将 /build/frontend/dist 改为 /build/frontend/build
COPY --from=frontend-builder /build/frontend/dist ./frontend/dist

# 暴露 FastAPI 端口
EXPOSE 8000

# 启动服务 (支持通过 docker-compose 覆盖命令来修改 worker 数量)
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]