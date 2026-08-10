#!/usr/bin/env bash
# =====================================================================
# registry-gc.sh - 私有 registry (quant_registry) 垃圾回收
# =====================================================================
# 用途: 回收 registry 卷 (quant_master_registry_data) 中被标记删除的镜像层，
#       防止私有 registry 无限膨胀（曾因 data-subservice 全量镜像堆积至 11GB+）。
#
# 前置条件: registry-config.yml 必须开启 storage.delete.enabled: true（OPS-03），
#           否则 garbage-collect 仅 dry-run、不释放空间。
#
# 用法:
#   ./scripts/registry-gc.sh            # 真正回收（--delete-untagged）
#   ./scripts/registry-gc.sh --dry-run  # 仅预览将被删除的内容，不实际删
#
# 建议: 通过 cron 每天低峰期执行一次（见下方 crontab 示例）。
# =====================================================================
set -euo pipefail

REGISTRY_CONTAINER="${REGISTRY_CONTAINER:-quant_registry}"
REGISTRY_CONFIG="${REGISTRY_CONFIG:-/etc/registry/config.yml}"

DRY_RUN=""
if [[ "${1:-}" == "--dry-run" ]]; then
  DRY_RUN="--dry-run"
  echo "[registry-gc] DRY-RUN 模式：仅预览，不实际删除"
fi

echo "[registry-gc] 开始回收 registry 垃圾 (container=${REGISTRY_CONTAINER}) ..."

# --delete-untagged: 一并清除无 tag 引用的 layer（push 中断/版本切换残留）
docker exec "${REGISTRY_CONTAINER}" \
  bin/registry garbage-collect ${DRY_RUN} --delete-untagged=true "${REGISTRY_CONFIG}"

echo "[registry-gc] 回收完成。"

# 顺带输出回收后卷占用，便于监控
if command -v docker >/dev/null 2>&1; then
  echo "[registry-gc] 当前 registry 卷占用:"
  docker system df --format "{{.Type}}\t{{.Size}}\t{{.Reclaimable}}" | grep -i volume || true
fi
