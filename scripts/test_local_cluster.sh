#!/usr/bin/env bash
# ==========================================
# 本地主从集群验证脚本
# ==========================================
# 用法:
#   chmod +x scripts/test_local_cluster.sh
#   ./scripts/test_local_cluster.sh
#
# 前置条件:
#   - Docker Desktop 运行中
#   - .env 文件存在 (从 .env.example 复制)
#   - 端口 6379, 5432, 8000, 8001 未被占用
# ==========================================

set -e

COMPOSE_FILE="docker-compose.local.yml"
SLAVE_URL="http://localhost:8001"
MASTER_URL="http://localhost:8000"
PASS=0
FAIL=0

# 颜色
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_pass() { echo -e "${GREEN}[PASS]${NC} $1"; ((PASS++)); }
log_fail() { echo -e "${RED}[FAIL]${NC} $1"; ((FAIL++)); }
log_info() { echo -e "${YELLOW}[INFO]${NC} $1"; }

cleanup() {
    log_info "清理容器..."
    docker compose -f "$COMPOSE_FILE" down -v --remove-orphans 2>/dev/null || true
}

# 注册退出清理
trap cleanup EXIT

echo ""
echo "=========================================="
echo "  本地主从集群验证"
echo "=========================================="
echo ""

# ==========================================
# Step 1: 构建并启动
# ==========================================
log_info "Step 1: 构建并启动 master + slave..."
docker compose -f "$COMPOSE_FILE" build --no-cache 2>&1 | tail -5
docker compose -f "$COMPOSE_FILE" up -d 2>&1

# 等待服务就绪
log_info "等待服务启动 (30s)..."
sleep 30

# ==========================================
# Step 2: 验证 slave /health
# ==========================================
log_info "Step 2: 验证 slave /health 端点..."
HEALTH_RESP=$(curl -sf "$SLAVE_URL/health" 2>/dev/null || echo "FAILED")

if echo "$HEALTH_RESP" | grep -q '"role":"slave"'; then
    log_pass "slave /health 返回 role=slave"
else
    log_fail "slave /health 响应异常: $HEALTH_RESP"
fi

if echo "$HEALTH_RESP" | grep -q '"yfinance"'; then
    log_pass "slave 声明 yfinance 采集器"
else
    log_fail "slave 未声明 yfinance 采集器"
fi

if echo "$HEALTH_RESP" | grep -q '"local-master":"connected"'; then
    log_pass "slave 成功连接 master Redis"
else
    log_fail "slave 未连接 master Redis: $HEALTH_RESP"
fi

# ==========================================
# Step 3: 验证 master /api/v1/health
# ==========================================
log_info "Step 3: 验证 master 健康检查..."
MASTER_HEALTH=$(curl -sf "$MASTER_URL/api/v1/health" 2>/dev/null || echo "FAILED")

if echo "$MASTER_HEALTH" | grep -q '"status":"ok"\|"code":0'; then
    log_pass "master /api/v1/health 正常"
else
    log_fail "master 健康检查异常: $MASTER_HEALTH"
fi

# ==========================================
# Step 4: 验证 master 发现 slave (ClusterManager)
# ==========================================
log_info "Step 4: 验证 ClusterManager 发现 slave..."
# 等待心跳注册 (slave 每 5s 写一次)
sleep 10

CLUSTER_RESP=$(curl -sf "$MASTER_URL/api/v1/cluster" 2>/dev/null || echo "FAILED")

if echo "$CLUSTER_RESP" | grep -q 'local-slave-1\|slave-collector'; then
    log_pass "master ClusterManager 发现 slave 节点"
else
    log_fail "master 未发现 slave: $CLUSTER_RESP"
fi

if echo "$CLUSTER_RESP" | grep -q '"yfinance"'; then
    log_pass "slave 采集器能力正确注册 (yfinance)"
else
    log_fail "slave 采集器能力未注册: $CLUSTER_RESP"
fi

# ==========================================
# Step 5: 验证 Redis 心跳写入
# ==========================================
log_info "Step 5: 验证 Redis 心跳数据..."
NODE_KEY=$(docker compose -f "$COMPOSE_FILE" exec -T redis redis-cli -a quant_local_dev --no-auth-warning GET "quant:node:local-slave-1" 2>/dev/null || echo "FAILED")

if echo "$NODE_KEY" | grep -q '"role":"slave"'; then
    log_pass "Redis 中存在 slave 心跳数据 (quant:node:local-slave-1)"
else
    log_fail "Redis 中未找到 slave 心跳: $NODE_KEY"
fi

# ==========================================
# Step 6: 验证采集回调链路
# ==========================================
log_info "Step 6: 验证 master -> slave 采集回调..."
COLLECT_RESP=$(curl -sf -X POST "$SLAVE_URL/collect/fetch_quote" \
    -H "Content-Type: application/json" \
    -d '{"ticker":"AAPL","params":{},"callback_redis":{"host":"redis","port":6379,"password":"quant_local_dev"}}' \
    2>/dev/null || echo "FAILED")

if echo "$COLLECT_RESP" | grep -q '"code":0'; then
    log_pass "slave /collect/fetch_quote 采集成功"
else
    log_fail "slave 采集失败: $COLLECT_RESP"
fi

# 验证 callback_redis 写入
sleep 2
CACHE_KEY=$(docker compose -f "$COMPOSE_FILE" exec -T redis redis-cli -a quant_local_dev --no-auth-warning GET "quant:cache:fetch_quote:AAPL" 2>/dev/null || echo "FAILED")

if echo "$CACHE_KEY" | grep -q '"source_node"'; then
    log_pass "采集结果已写入 master Redis (quant:cache:fetch_quote:AAPL)"
else
    log_fail "Redis 中未找到采集缓存: $CACHE_KEY"
fi

# ==========================================
# 结果汇总
# ==========================================
echo ""
echo "=========================================="
echo "  验证结果: ${GREEN}${PASS} passed${NC}, ${RED}${FAIL} failed${NC}"
echo "=========================================="
echo ""

if [ $FAIL -gt 0 ]; then
    echo "查看日志: docker compose -f $COMPOSE_FILE logs"
    exit 1
fi

echo "全部验证通过!"
