#!/bin/bash
# 在干净终端执行: sh scripts/commit_topology.sh
# 按 commit 规范拆分提交: feat / docs / chore / fix / ci
set -e

cd "$(dirname "$0")/.."

echo "==> [1/5] feat: data_subservice 能力化 + 主节点远程路由"
git add \
  data_subservice/main.py \
  data_subservice/nodeinfo.py \
  data_subservice/routes.py \
  data_subservice/yfinance_worker.py \
  backend/services/datasource/router.py
git commit -m "$(cat <<'EOF'
feat: data_subservice 按节点能力暴露数据源代理 + 主节点远程路由

- 新增 nodeinfo.py，从 DS_CAPABILITIES/DS_NODE_ID/DS_REGION/DS_BASE_URL 构建节点身份
- main.py 按 DS_CAPABILITIES 启动对应代理端点与 worker（仅 yfinance 起常驻 worker）
- routes.py 新增 /api/v1/data-source/proxy/{tushare,akshare}，委托 backend tushare/akshare 单例
- yfinance_worker.py 暴露模块级 worker 单例与 handle/start/stop
- router.py 支持逗号分隔多 URL，注册 yfinance 多活节点与 tushare/akshare 北京单节点
- router.py 新增 fetch_tushare（远程不可用时降级本地适配器）；修复远程节点注册/取键不一致 bug

Co-Authored-By: Claude (CodeBuddy) <noreply@tencent.com>
EOF
)"

echo "==> [2/5] docs: 5 节点 env 模板"
git add \
  .env.example \
  .env.slave.example \
  .env.yf-s2.example \
  .env.yf-s3.example \
  .env.yf-s4.example
git commit -m "$(cat <<'EOF'
docs: 补充 5 节点拓扑 env 模板

- .env.example: DATA_SOURCE_ROUTER_ENABLED/HMAC_SECRET/ALLOWED_IPS；
  TUSHARE/AKSHARE_REMOTE_URL 指向北京单节点 (无容灾)；YF_BACKUP 含 S2/S3/S4
- .env.slave.example 北京节点配置 tushare+akshare+yfinance
- .env.yf-s2/s3/s4.example 美西从节点纯 yfinance (命名对齐 VPS_S2/S3/S4)

Co-Authored-By: Claude (CodeBuddy) <noreply@tencent.com>
EOF
)"

echo "==> [3/5] chore: 收敛 5 节点 compose 并清理冗余"
git add \
  docker-compose.master.yml \
  docker-compose.node-bj.yml \
  docker-compose.node-s2.yml \
  docker-compose.node-s3.yml \
  docker-compose.node-s4.yml
git rm -q \
  docker-compose.yml \
  docker-compose.yf-backup.yml \
  docker-compose.local.yml \
  docker-compose.yf-node.yml \
  docker-compose.yf-node2.yml \
  docker-compose.yf-node-data.yml \
  .env.yf.example \
  .env.yf2.example \
  .env.yf-data.example
git commit -m "$(cat <<'EOF'
chore: 收敛为多节点部署拓扑并清理冗余 compose

- 保留 5 节点: master(VPS_S1) / slave(VPS_BJ: tushare+akshare+yfinance) /
  node-s2(VPS_S2: yfinance) / node-s3(VPS_S3: yfinance) / node-s4(VPS_S4: yfinance)
- 删除 docker-compose.yml(单 VPS 全家桶)、docker-compose.yf-backup.yml、docker-compose.local.yml
- 删除旧 yf 节点命名 (yf-node/yf-node2/yf-node-data + .env.yf/.env.yf2/.env.yf-data)，统一为 s2/s3/s4
- slave/yf 节点统一引用 data_subservice 镜像，按 DS_CAPABILITIES 配置数据源

Co-Authored-By: Claude (CodeBuddy) <noreply@tencent.com>
EOF
)"

echo "==> [4/5] fix: 拓扑修正 — Tushare/AKShare 仅北京单节点 (无 S2 双活)"
git add \
  backend/services/datasource/router.py \
  .env.example \
  .env.yf-s2.example \
  docker-compose.node-s2.yml
git commit -m "$(cat <<'EOF'
fix: Tushare/AKShare 收敛为北京单节点，移除 S2 双活

- router.py: tushare_remote/akshare_remote 注册为单键节点；YF_BACKUP 含 S2/S3/S4
- .env.example: TUSHARE_REMOTE_URL/AKSHARE_REMOTE_URL 改北京单节点
- docker-compose.node-s2.yml / .env.yf-s2.example: S2 为纯 yfinance 节点

Co-Authored-By: Claude (CodeBuddy) <noreply@tencent.com>
EOF
)"

echo "==> [5/5] ci: 5 节点全部纳入自动部署"
git add \
  .github/workflows/backend.yml
git commit -m "$(cat <<'EOF'
ci: 4 个数据源从节点纳入自动部署 + 动态生成 .env

- push develop: 仅构建校验 (build + 推镜像)，不部署
- PR (合入 develop): 构建 + 自动部署到 5 个节点
- 新增 build-data-subservice job 构建 data_subservice 镜像并推送 GHCR
- 新增 deploy-data-nodes matrix job (PR 触发): BJ(slave) / S2(node-s2) / S3(node-s3) / S4(node-s4)
- 部署时由 CI 用 Secrets 动态生成各节点 .env (写入 Tailscale IP / REDIS_HOST / HMAC / TZ 等)，无需 VPS 预置
- 各从节点 compose 改用 ghcr.io/.../quant-agent-data-subservice:latest 镜像
- deploy 经 ssh-preflight 探测后拉取镜像 up -d --remove-orphans

Co-Authored-By: Claude (CodeBuddy) <noreply@tencent.com>
EOF
)"

echo "==> ALL DONE. 当前最近 5 条 commit:"
git --no-pager log --oneline -5
