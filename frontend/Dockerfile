# 第一阶段：Node.js 编译构建 (Builder)
FROM node:20-alpine AS builder
WORKDIR /app

# 复制依赖配置并安装
COPY package*.json ./
RUN npm ci

# 复制源码并执行打包
COPY . .
RUN npm run build

# 第二阶段：Nginx 部署 (Production)
FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]