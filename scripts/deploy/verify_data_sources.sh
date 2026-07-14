#!/usr/bin/env bash
# ==========================================
# 📊 数据源跨节点验证脚本 (DIST-17/18)
# ==========================================
# 用途:
#   - DIST-17: 验证 US-MASTER 境外源 (Futu/Finnhub/FRED)
#   - DIST-17: 验证 YF 流量落在 A/B 而非 master
#   - DIST-18: 验证 CN-AKSHARE 国内直连
#
# 用法:
#   bash scripts/deploy/verify_data_sources.sh [master|yf|cn|all]
#
# 前置:
#   - 在对应节点上运行，或通过 SSH 远程执行
#   - 环境变量: MASTER_URL / YF_A_URL / YF_B_URL / CN_URL
# ==========================================
set -euo pipefail

# 颜色
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

PASS=0
FAIL=0
WARN=0

pass() { echo -e "${GREEN}✓${NC} $*"; ((PASS++)); }
fail() { echo -e "${RED}✗${NC} $*"; ((FAIL++)); }
warn() { echo -e "${YELLOW}⚠${NC} $*"; ((WARN++)); }
info() { echo -e "${BLUE}→${NC} $*"; }

# 默认 URL
MASTER_URL="${MASTER_URL:-http://localhost:8000}"
YF_A_URL="${YF_A_URL:-http://100.102.223.45:8000}"
YF_B_URL="${YF_B_URL:-http://100.102.223.46:8000}"
CN_URL="${CN_URL:-http://100.124.178.96:8000}"

ROLE="${1:-all}"

echo "=========================================="
echo "  📊 数据源跨节点验证"
echo "  角色: $ROLE"
echo "=========================================="
echo ""

# ==========================================
# 通用: HTTP 请求辅助
# ==========================================
http_get() {
    local url=$1
    local timeout=${2:-10}
    curl -sf --max-time "$timeout" "$url" 2>/dev/null || echo "REQUEST_FAILED"
}

# ==========================================
# DIST-17: US-MASTER 境外源验证
# ==========================================
verify_master() {
    info "验证 US-MASTER 数据源..."
    echo ""

    # 1. 健康检查
    info "[1/5] 主节点健康检查..."
    HEALTH=$(http_get "$MASTER_URL/api/v1/health")
    if echo "$HEALTH" | grep -q '"status"'; then
        pass "主节点 /health 正常"
    else
        fail "主节点 /health 异常: $HEALTH"
        return
    fi

    # 2. Futu 行情 (本地 OpenD)
    info "[2/5] Futu 行情验证 (本地 OpenD)..."
    FUTU_RESULT=$(http_get "$MASTER_URL/api/v1/market/quote?symbol=00700.HK&action=QUOTE")
    if echo "$FUTU_RESULT" | grep -q '"price"'; then
        pass "Futu 行情正常 (00700.HK)"
    else
        fail "Futu 行情异常: $FUTU_RESULT"
    fi

    # 3. Finnhub 新闻
    info "[3/5] Finnhub 新闻验证..."
    NEWS_RESULT=$(http_get "$MASTER_URL/api/v1/market/news?source=finnhub")
    if echo "$NEWS_RESULT" | grep -q '"data"'; then
        pass "Finnhub 新闻正常"
    else
        warn "Finnhub 新闻异常 (可能 API 限制): $NEWS_RESULT"
    fi

    # 4. FRED 宏观数据
    info "[4/5] FRED 宏观数据验证..."
    FRED_RESULT=$(http_get "$MASTER_URL/api/v1/macro/history?indicator=DGS10")
    if echo "$FRED_RESULT" | grep -q '"data"'; then
        pass "FRED 宏观数据正常 (DGS10)"
    else
        warn "FRED 宏观数据异常: $FRED_RESULT"
    fi

    # 5. YF Router 验证 (流量应落在 YF-A/B)
    info "[5/5] YF Router 验证 (流量应路由到 YF-A/B)..."
    YF_HEALTH=$(http_get "$MASTER_URL/api/v1/data-source/nodes")
    if echo "$YF_HEALTH" | grep -q 'us-yf-a'; then
        pass "YF Router 已注册 us-yf-a"
    else
        warn "YF Router 未发现 us-yf-a (可能未部署或未注册)"
    fi
    if echo "$YF_HEALTH" | grep -q 'us-yf-b'; then
        pass "YF Router 已注册 us-yf-b"
    else
        warn "YF Router 未发现 us-yf-b (可能未部署或未注册)"
    fi

    # 验证主节点 COLLECTOR_YFINANCE=false
    if grep -q "COLLECTOR_YFINANCE=false" /opt/quant-agent/.env 2>/dev/null; then
        pass "主节点 COLLECTOR_YFINANCE=false (YF 流量走 Router)"
    else
        warn "主节点 COLLECTOR_YFINANCE 未设置为 false"
    fi
}

# ==========================================
# DIST-17: YF 子服务节点验证
# ==========================================
verify_yf_nodes() {
    info "验证 YF 子服务节点..."
    echo ""

    for node_url in "$YF_A_URL" "$YF_B_URL"; do
        node_name=$(echo "$node_url" | grep -q "45" && echo "YF-A" || echo "YF-B")
        info "检查 $node_name ($node_url)..."

        # 健康检查
        HEALTH=$(http_get "$node_url/health")
        if echo "$HEALTH" | grep -q '"status":"healthy"'; then
            pass "$node_name /health 正常"
        else
            fail "$node_name /health 异常: $HEALTH"
            continue
        fi

        # 节点 ID
        NODE_ID=$(echo "$HEALTH" | grep -o '"node_id":"[^"]*"' | cut -d'"' -f4)
        info "  节点 ID: $NODE_ID"

        # YFinance daemon
        if echo "$HEALTH" | grep -q '"yfinance_daemon_running":true'; then
            pass "$node_name YFinance daemon 运行中"
        else
            fail "$node_name YFinance daemon 未运行"
        fi

        # 数据接口测试
        QUOTE=$(http_get "$node_url/api/v1/data-source/proxy/yfinance?action=quote&symbol=AAPL")
        if echo "$QUOTE" | grep -q '"price"'; then
            pass "$node_name YF quote 正常 (AAPL)"
        else
            fail "$node_name YF quote 异常"
        fi

        echo ""
    done
}

# ==========================================
# DIST-18: CN-AKSHARE 验证
# ==========================================
verify_cn() {
    info "验证 CN-AKSHARE 数据源..."
    echo ""

    # 1. 健康检查
    info "[1/3] CN 节点健康检查..."
    HEALTH=$(http_get "$CN_URL/api/v1/health")
    if echo "$HEALTH" | grep -q '"status"'; then
        pass "CN 节点 /health 正常"
    else
        fail "CN 节点 /health 异常: $HEALTH"
        return
    fi

    # 2. AKShare 数据验证 (国内源直连)
    info "[2/3] AKShare 国内数据源验证..."
    AK_RESULT=$(http_get "$CN_URL/api/v1/market/quote?symbol=sh000001&action=QUOTE")
    if echo "$AK_RESULT" | grep -q '"price"'; then
        pass "AKShare 数据正常 (上证指数)"
    else
        fail "AKShare 数据异常: $AK_RESULT"
    fi

    # 3. 验证禁止 YF
    info "[3/3] 验证 CN 节点禁止 YFinance..."
    if grep -q "COLLECTOR_YFINANCE=false" /opt/quant-agent/.env 2>/dev/null; then
        pass "CN 节点 COLLECTOR_YFINANCE=false (禁止 YF)"
    else
        warn "CN 节点 COLLECTOR_YFINANCE 未设置为 false"
    fi

    # 验证 Redis 连接 (通过 Tailscale 到 Master)
    REDIS_CHECK=$(http_get "$CN_URL/api/v1/health")
    if echo "$REDIS_CHECK" | grep -q '"redis"'; then
        pass "CN → Master Redis 连接正常"
    else
        warn "CN → Master Redis 连接异常"
    fi
}

# ==========================================
# 执行验证
# ==========================================
case "$ROLE" in
    master)
        verify_master
        ;;
    yf)
        verify_yf_nodes
        ;;
    cn)
        verify_cn
        ;;
    all)
        verify_master
        echo ""
        verify_yf_nodes
        echo ""
        verify_cn
        ;;
    *)
        echo "用法: $0 [master|yf|cn|all]"
        exit 1
        ;;
esac

# ==========================================
# 结果汇总
# ==========================================
echo ""
echo "=========================================="
echo "  验证结果汇总"
echo "=========================================="
echo -e "  ${GREEN}通过: $PASS${NC}"
echo -e "  ${RED}失败: $FAIL${NC}"
echo -e "  ${YELLOW}警告: $WARN${NC}"
echo ""

if [ $FAIL -gt 0 ]; then
    echo -e "${RED}验证失败! 请检查上述问题。${NC}"
    exit 1
elif [ $WARN -gt 0 ]; then
    echo -e "${YELLOW}验证通过 (有警告)。${NC}"
    exit 0
else
    echo -e "${GREEN}验证全部通过!${NC}"
    exit 0
fi
