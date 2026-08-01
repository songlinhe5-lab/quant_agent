#!/usr/bin/env bash
# 在【新终端】执行： sh /Users/stephenhe/Development/workspace/quant_agent/scripts/commit_tushare.sh
# 当前会话 shell 环境损坏(argv 超限)，请勿在原会话执行。
set -e
REPO=/Users/stephenhe/Development/workspace/quant_agent
GIT=/usr/bin/git

cd "$REPO"

# ---- Commit 1: Tushare 数据源接入 ----
cat > "$REPO/.git/CI_MSG_1.txt" <<'EOF'
feat: 接入 Tushare 数据源作为 A 股主源

实现 TushareService + DataSourceInterface 适配器，覆盖 2000 积分档接口
（股票列表/日周月线/实时/三大报表/每日指标/沪深港通/宏观经济 cn_*）。
- 令牌桶频次保护：通用 200 次/分、财务 80 次/分
- NO_PROXY 防本机失效代理卡死
- A 股行情主路径 Tushare 优先、AkShare 兜底
- 注册至 /health-overview 看板
EOF
$GIT add \
  backend/services/tushare/service.py \
  backend/services/tushare/adapter.py \
  backend/services/tushare/__init__.py \
  backend/app/market_data_app.py \
  backend/routers/datasource.py
$GIT commit -F "$REPO/.git/CI_MSG_1.txt"

# ---- Commit 2: .env.example 配置模板 ----
$GIT add .env.example
$GIT commit -m "docs: 新增 TUSHARE_TOKEN 与 DATASOURCE_TUSHARE_MODE 配置模板"

# ---- Commit 3: 依赖收口 + 清理临时脚本 ----
$GIT add backend/requirements.txt
$GIT rm -q scripts/_probe_tushare_err.py scripts/_install_tushare.sh 2>/dev/null || true
$GIT commit -m "chore: 收口 backend 依赖并清理排查期临时脚本"

echo "=== 三个 commit 已完成 ==="
$GIT log --oneline -3
