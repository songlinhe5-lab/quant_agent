# 第一阶段：Node.js 构建 (Builder)
FROM node:20-alpine AS builder
WORKDIR /app

# 安装 pnpm
RUN corepack enable && corepack prepare pnpm@9 --activate

# 复制依赖配置并安装
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

# 复制源码并执行打包（加大 Node.js 堆内存限制，避免 OOM）
COPY . .
RUN NODE_OPTIONS="--max-old-space-size=4096" pnpm run build

# 第二阶段：Nginx 部署
FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
