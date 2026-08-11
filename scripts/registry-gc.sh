#!/usr/bin/env bash
# =====================================================================
# registry-gc.sh - 私有中转 registry 深度垃圾回收 (cron 用)
# =====================================================================
# 用途: 回收 registry 卷 (quant_master_registry_data) 中的无引用镜像层，
#       防止私有 registry 无限膨胀（曾因 tag 覆盖残留堆积至 11GB+）。
#
# 与 CI 的分工 (勿混淆):
#   - CI (.github/workflows/backend.yml): push 后立即跑 *不带* --delete-untagged
#     的保守 GC，只清 dangling 层，避免误删从节点尚未 pull 的新 tag。
#   - 本脚本 (cron 04:30): 带 --delete-untagged 的深度 GC，回收 tag 被覆盖后
#     残留的旧 manifest —— CI 那轮清不掉、也正是卷膨胀的真正来源。
#
# 前置条件: registry-config.yml 必须开启 storage.delete.enabled: true（OPS-03），
#           否则 garbage-collect 仅 dry-run、不释放空间。
#
# 用法:
#   ./scripts/registry-gc.sh            # 真正回收（--delete-untagged）
#   ./scripts/registry-gc.sh --dry-run  # 仅预览将被删除的内容，不实际删
#
# 容器名: 自动发现 (compose ps -q registry → registry:2 ancestor 兜底)，
#         如需指定可传 REGISTRY_CONTAINER=<name> 覆盖。
#
# cron 安装 (主节点，每日 04:30 低峰期，此时从节点已完成 pull):
#   30 4 * * * /opt/quant-agent/scripts/registry-gc.sh >> /var/log/registry-gc.log 2>&1
# =====================================================================
set -euo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-/opt/quant-agent/docker-compose.master.yml}"
ENV_FILE="${ENV_FILE:-/opt/quant-agent/.env}"
REGISTRY_CONFIG="${REGISTRY_CONFIG:-/etc/registry/config.yml}"

DRY_RUN=""
if [[ "${1:-}" == "--dry-run" ]]; then
  DRY_RUN="--dry-run"
  echo "[registry-gc] DRY-RUN 模式：仅预览，不实际删除"
fi

# ── 容器名动态发现 ──────────────────────────────────────────────
# 历史坑 (本脚本失效 ~11GB 堆积的根因): 此处曾硬编码 REGISTRY_CONTAINER=quant_registry，
# 而新版 compose 已删除 container_name，实际容器名为 <项目名>-registry-1
# (如 quant-agent-master-registry-1)，docker exec 恒报 "No such container" → GC 从未真正执行。
# 现按 compose ps -q → registry:2 ancestor 兜底 两级发现，禁止再写死容器名。
REGISTRY_CID="${REGISTRY_CONTAINER:-}"

if [[ -z "${REGISTRY_CID}" ]] && [[ -f "${COMPOSE_FILE}" ]]; then
  if [[ -f "${ENV_FILE}" ]]; then
    REGISTRY_CID=$(docker compose -f "${COMPOSE_FILE}" --env-file "${ENV_FILE}" ps -q registry 2>/dev/null || true)
  else
    REGISTRY_CID=$(docker compose -f "${COMPOSE_FILE}" ps -q registry 2>/dev/null || true)
  fi
fi

# 兜底: compose 文件缺失/项目名不一致时，按镜像 ancestor 找运行中的 registry
if [[ -z "${REGISTRY_CID}" ]]; then
  REGISTRY_CID=$(docker ps --filter "ancestor=registry:2" --format '{{.Names}}' | head -1 || true)
fi

if [[ -z "${REGISTRY_CID}" ]]; then
  echo "[registry-gc] ❌ 未找到运行中的 registry 容器，跳过 GC。"
  echo "[registry-gc]    排查: docker compose -f ${COMPOSE_FILE} ps registry"
  echo "[registry-gc]    拉起: docker compose -f ${COMPOSE_FILE} --env-file ${ENV_FILE} up -d registry"
  exit 1
fi

# 判活: 容器存在但已退出时 docker exec 同样会失败，此处提前拦截给出明确原因
if [[ "$(docker inspect -f '{{.State.Running}}' "${REGISTRY_CID}" 2>/dev/null)" != "true" ]]; then
  echo "[registry-gc] ❌ registry 容器 (${REGISTRY_CID}) 未处于运行状态，跳过 GC。"
  exit 1
fi

echo "[registry-gc] 开始回收 registry 垃圾 (container=${REGISTRY_CID}) ..."

# --delete-untagged: 一并清除无 tag 引用的 manifest/layer。
# ⚠️ 语义边界 (与 CI 内的保守 GC 分工):
#   CI 在 push 完成后立即跑 *不带* --delete-untagged 的 GC —— 因为此刻从节点 (bj/s2-s4)
#   可能尚未 pull 新推的 cn/us/us-aux tag，误删 untagged manifest 会让从节点 pull
#   报 manifest not found。故 CI 只清 dangling 层。
#   而 tag 被覆盖后 (每次部署 :us 重新指向新 digest) 产生的旧 manifest 恰恰是 untagged，
#   CI 那轮永远回收不掉 —— 这才是卷膨胀的真正来源，必须由本脚本在低峰期 (cron 04:30，
#   从节点早已完成 pull) 深度回收。
docker exec "${REGISTRY_CID}" \
  bin/registry garbage-collect ${DRY_RUN} --delete-untagged=true "${REGISTRY_CONFIG}"

echo "[registry-gc] 回收完成。"

# 回收后输出 registry 存储实际占用，便于 cron 日志追踪膨胀趋势。
# 直接 du 容器内 /var/lib/registry (= registry_data 卷)，比 docker system df
# 笼统列出全部卷更精确 —— 后者混入 PG/Redis，看不出 GC 到底释放了多少。
REG_SIZE=$(docker exec "${REGISTRY_CID}" du -sh /var/lib/registry 2>/dev/null | awk '{print $1}' || true)
if [[ -n "${REG_SIZE}" ]]; then
  echo "[registry-gc] 当前 registry 存储占用: ${REG_SIZE} (/var/lib/registry)"
fi
echo "[registry-gc] 宿主磁盘: $(df -h / | awk 'NR==2 {print "已用 "$5" | 剩余 "$4}')"
