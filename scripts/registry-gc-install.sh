#!/usr/bin/env bash
# registry-gc-install.sh - registry 保守 GC + 深度 GC cron 自愈安装
# =====================================================================
# 由 CI 每次部署主节点时调用 (curl 落盘后执行)，目的是:
#   1. push 后立即跑 *不带* --delete-untagged 的保守 GC (仅清 dangling 层)，
#      避免误删从节点 (bj/s2-s4) 尚未 pull 的新推 cn/us/us-aux tag 引用的 blob。
#   2. 幂等下发 scripts/registry-gc.sh 并安装 04:30 深度 GC cron。
#      深度回收带 --delete-untagged=true，专门清 tag 被覆盖后残留的旧 manifest
#      —— 那才是 registry 卷膨胀到 11GB 的真凶，CI 这轮清不掉 (从节点还没 pull 完)。
#
# 设计边界 (勿混淆):
#   - 本脚本 = CI push 后 (保守 GC + 装 cron)
#   - scripts/registry-gc.sh = cron 04:30 跑的深度 GC (见该脚本头部注释)
#
# 退出码: 0 (GC/cron 失败均非致命，仅告警，不影响部署)。
# =====================================================================
set -uo pipefail

REGISTRY_CONFIG="${REGISTRY_CONFIG:-/etc/registry/config.yml}"

# 容器名动态发现 (与 scripts/registry-gc.sh 同源逻辑，禁止写死)
REGISTRY_CID="${REGISTRY_CONTAINER:-}"
if [[ -z "${REGISTRY_CID}" ]]; then
  REGISTRY_CID=$(docker ps --filter "ancestor=registry:2" --format '{{.Names}}' | head -1 || true)
fi

if [[ -z "${REGISTRY_CID}" ]]; then
  echo "⚠️ 未找到运行中的 registry 容器，跳过 CI GC 与 cron 安装 (下次部署重试)"
  exit 0
fi

# ── 1. 保守 GC (仅清 dangling) ──────────────────────────────────
echo "🧹 push 完成，执行 registry 垃圾回收 (GC, 仅清 dangling)..."

# 前置断言: delete.enabled 若被改回 false，GC 会静默退化为只读扫描、一点空间都不释放
# (11GB 堆积期间正是无人察觉)。此处显式校验，配置回退时当场告警而非默默失效。
if docker exec "${REGISTRY_CID}" grep -qE '^\s*enabled:\s*true' "${REGISTRY_CONFIG}" 2>/dev/null; then
  echo "✅ registry delete.enabled 已开启，GC 可真正释放空间"
else
  echo "⚠️ registry-config.yml 未开启 storage.delete.enabled，GC 将不释放任何空间！请检查配置。"
fi

docker exec "${REGISTRY_CID}" bin/registry garbage-collect "${REGISTRY_CONFIG}" \
  || echo "⚠️ registry GC 失败（非致命，下次部署或 cron 重试），registry 仍可正常服务"
echo "✅ registry GC 完成"

# ── 2. 深度 GC cron 自愈安装 ────────────────────────────────────
# 历史坑: registry-gc.sh 曾硬编码容器名 quant_registry，docker exec 恒失败，
# GC 从未生效且无人发现。现由 CI 每次部署幂等下发脚本 + 装 cron，避免重装机器后
# 深度 GC 再度沦为"纸面上的 GC"。
REPO_REF="${GC_SCRIPT_REF:-${1:-}}"
if [[ -n "${REPO_REF}" ]]; then
  curl -sSL -o scripts/registry-gc.sh \
    "https://raw.githubusercontent.com/${REPO_REF}/scripts/registry-gc.sh" 2>/dev/null \
    && chmod +x scripts/registry-gc.sh \
    && echo "✅ registry-gc.sh 已同步至主节点" \
    || echo "⚠️ registry-gc.sh 拉取失败，跳过 cron 安装 (不影响本次部署)"
else
  echo "⚠️ 未传入仓库引用 (GC_SCRIPT_REF)，跳过 registry-gc.sh 同步 (不影响本次部署)"
fi

if [ -x scripts/registry-gc.sh ]; then
  GC_CRON="30 4 * * * /opt/quant-agent/scripts/registry-gc.sh >> /var/log/registry-gc.log 2>&1"
  # 幂等: 先滤掉旧的 registry-gc 行再追加，避免每次部署重复堆积 crontab 条目
  ( crontab -l 2>/dev/null | grep -v 'registry-gc.sh' || true; echo "${GC_CRON}" ) | crontab - \
    && echo "✅ 深度 GC cron 已安装 (每日 04:30, 日志 /var/log/registry-gc.log)" \
    || echo "⚠️ cron 安装失败 (非致命)，可手动执行 scripts/registry-gc.sh"
fi

exit 0
