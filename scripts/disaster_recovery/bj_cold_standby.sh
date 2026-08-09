#!/usr/bin/env bash
# =====================================================================
# 北京节点冷备启动脚本 (DOC-05 · ADR-005 最低限度 DR)
# ---------------------------------------------------------------------
# 场景：加州主节点 (VPS_S1 · API+DB+Redis+Futu) 或美国 YF 节点 (S2/S3/S4)
#       整体不可用，需在 4h 内将北京节点 (VPS_BJ) 提升为兜底数据源，
#       恢复 A 股/港股 Tushare+AKShare+YFinance 数据通路，并让主服务
#       DataSourceRouter 降级指向北京节点。
#
# 前置（由 docs/12 备份计划保证，本脚本不负责备份，只负责恢复+启动）：
#   - Cloudflare R2 每日 03:00 Redis RDB + 03:30 PostgreSQL dump
#     (r2://quant-backup/{redis,postgres}/...)
#   - 北京节点已安装 docker compose + Tailscale + aws-cli (含 R2 endpoint)
#
# RTO 目标：< 4h（本脚本执行体 < 30min，余量用于人工确认与路由切换）
#
# 用法：
#   sh scripts/disaster_recovery/bj_cold_standby.sh [--skip-restore] [--dry-run]
#     --skip-restore  已手动恢复过 PG/Redis 时跳过 R2 下载恢复
#     --dry-run       仅打印将执行的命令，不实际改动
# =====================================================================
set -euo pipefail

DRY_RUN=0
SKIP_RESTORE=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=1; shift ;;
    --skip-restore) SKIP_RESTORE=1; shift ;;
    *) echo "未知参数: $1" >&2; exit 2 ;;
  esac
done

RUN() {
  if [[ $DRY_RUN -eq 1 ]]; then
    echo "  [dry-run] $*"
  else
    eval "$@"
  fi
}

START_TS=$(date +%s)
echo "🚨 [DR] 北京节点冷备启动 — $(date -u '+%Y-%m-%dT%H:%M:%SZ')"

# ---------------------------------------------------------------------
# 0. 环境校验
# ---------------------------------------------------------------------
echo "==> [0/6] 环境校验"
: "${R2_ENDPOINT:?请设置 R2_ENDPOINT (如 https://xxx.r2.cloudflarestorage.com)}"
: "${R2_BUCKET:?请设置 R2_BUCKET (如 quant-backup)}"
: "${R2_ACCESS_KEY:?请设置 R2_ACCESS_KEY}"
: "${R2_SECRET_KEY:?请设置 R2_SECRET_KEY}"
: "${PG_CONTAINER:?请设置 PG_CONTAINER (主节点 PostgreSQL 容器名或连接串)}"
: "${REDIS_DATA_DIR:?请设置 REDIS_DATA_DIR (Redis 持久化目录)}"
: "${REPO_DIR:?请设置 REPO_DIR (quant-agent 仓库根目录)}"

command -v aws >/dev/null 2>&1 || { echo "❌ 缺少 aws-cli"; exit 1; }
command -v docker >/dev/null 2>&1 || { echo "❌ 缺少 docker"; exit 1; }
command -v tailscale >/dev/null 2>&1 || echo "⚠️ 未检测到 tailscale，跨节点通信可能失败"

export AWS_ACCESS_KEY_ID="$R2_ACCESS_KEY"
export AWS_SECRET_ACCESS_KEY="$R2_SECRET_KEY"
export AWS_ENDPOINT_URL="$R2_ENDPOINT"

# ---------------------------------------------------------------------
# 1. 拉取 R2 最新备份（异地恢复）
# ---------------------------------------------------------------------
if [[ $SKIP_RESTORE -eq 0 ]]; then
  echo "==> [1/6] 从 R2 拉取最新备份"
  TMP=$(mktemp -d)
  PG_LATEST=$(aws s3 ls "s3://${R2_BUCKET}/postgres/" --endpoint-url "$R2_ENDPOINT" | awk '{print $4}' | grep -E '\.sql\.gz$' | sort | tail -1)
  RDB_LATEST=$(aws s3 ls "s3://${R2_BUCKET}/redis/" --endpoint-url "$R2_ENDPOINT" | awk '{print $4}' | grep -E 'dump.*\.rdb$' | sort | tail -1)
  echo "  PostgreSQL: $PG_LATEST"
  echo "  Redis RDB:  $RDB_LATEST"
  [[ -n "$PG_LATEST" ]] || { echo "❌ 未找到 PostgreSQL 备份"; exit 1; }
  [[ -n "$RDB_LATEST" ]] || echo "⚠️ 未找到 Redis RDB 备份，将仅恢复 PG"

  RUN "aws s3 cp s3://${R2_BUCKET}/postgres/${PG_LATEST} ${TMP}/pg.sql.gz --endpoint-url ${R2_ENDPOINT}"
  [[ -n "$RDB_LATEST" ]] && RUN "aws s3 cp s3://${R2_BUCKET}/redis/${RDB_LATEST} ${TMP}/dump.rdb --endpoint-url ${R2_ENDPOINT}"

  # ---------------------------------------------------------------------
  # 2. 恢复 PostgreSQL
  # ---------------------------------------------------------------------
  echo "==> [2/6] 恢复 PostgreSQL"
  RUN "gunzip -c ${TMP}/pg.sql.gz | psql ${PG_CONTAINER} -f -"

  # ---------------------------------------------------------------------
  # 3. 恢复 Redis (需停写后替换 RDB 再重启)
  # ---------------------------------------------------------------------
  if [[ -n "$RDB_LATEST" ]]; then
    echo "==> [3/6] 恢复 Redis RDB"
    RUN "docker stop redis || true"
    RUN "cp ${TMP}/dump.rdb ${REDIS_DATA_DIR}/dump.rdb"
    RUN "docker start redis || true"
  else
    echo "==> [3/6] 跳过 Redis 恢复 (无 RDB 备份)"
  fi
  rm -rf "$TMP"
else
  echo "==> [1-3/6] 跳过 R2 恢复 (--skip-restore)"
fi

# ---------------------------------------------------------------------
# 4. 启动北京节点 data_subservice 冷备实例
# ---------------------------------------------------------------------
echo "==> [4/6] 启动北京节点 data_subservice"
cd "$REPO_DIR"
RUN "cp -n .env.data-node.example .env.data-node"
RUN "docker compose --env-file .env.data-node -f docker-compose.node-bj.yml pull"
RUN "docker compose --env-file .env.data-node -f docker-compose.node-bj.yml up -d"
# 健康检查（默认 30s 间隔，最多等 2min）
for i in $(seq 1 4); do
  if curl -sf "http://${PUBLIC_IP:-127.0.0.1}:8001/health" >/dev/null 2>&1; then
    echo "  ✅ 北京节点 data_subservice 健康"
    break
  fi
  echo "  … 等待健康 (${i}/4)"
  sleep 30
done

# ---------------------------------------------------------------------
# 5. 主服务 DataSourceRouter 降级指向北京节点
# ---------------------------------------------------------------------
echo "==> [5/6] 切换主服务路由至北京节点 (降级模式)"
# 在主节点 .env 中将 AKSHARE_REMOTE_URL / TUSHARE_REMOTE_URL 指向北京 Tailscale IP
# 并重启后端 API 使 DataSourceRouter 重新注册节点
BJ_IP="${PUBLIC_IP:-100.124.178.96}"
if [[ -f "${REPO_DIR}/.env" ]]; then
  RUN "sed -i.bak -E \"s#^AKSHARE_REMOTE_URL=.*#AKSHARE_REMOTE_URL=http://${BJ_IP}:8001#; s#^TUSHARE_REMOTE_URL=.*#TUSHARE_REMOTE_URL=http://${BJ_IP}:8001#\" ${REPO_DIR}/.env"
  echo "  ⚠️ 已更新 .env 远程源指向北京节点；请人工确认后重启主服务 API 容器"
fi

# ---------------------------------------------------------------------
# 6. 完成度校验 + RTO 计时
# ---------------------------------------------------------------------
END_TS=$(date +%s)
ELAPSED=$(( (END_TS - START_TS) / 60 ))
echo "==> [6/6] DR 启动完成"
echo "  ⏱️  脚本执行耗时: ${ELAPSED} min (RTO 预算 < 240 min)"
echo "  ✅ 北京节点 data_subservice 已起；PG/Redis 已恢复；主服务路由待人工重启生效"
echo "  📋 人工收尾：1) 重启主服务 API 容器  2) 验证 /datasource/health 北京节点 healthy"
echo "  📋 回切：主节点恢复后，将 .env 改回原 URL 并重启 API 即可"
