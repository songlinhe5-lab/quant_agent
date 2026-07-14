#!/usr/bin/env bash
# ==========================================
# Quant Agent - Tailscale 跨节点连通性验证
# ==========================================
# 用途: 验证 Tailnet 内节点间通信是否正常
#       检查数据端口是否对公网暴露
#
# 用法: bash scripts/deploy/verify_tailscale.sh
#
# 预期结果:
#   ✓ Tailscale 服务运行中
#   ✓ 所有节点在线
#   ✓ CN-AKSHARE → US-MASTER:6379 可达
#   ✓ US-MASTER → US-YF-*:8000 可达
#   ✗ Redis/Postgres 不对公网暴露
# ==========================================

set -euo pipefail

# 颜色
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

PASS=0
FAIL=0
WARN=0

pass() { echo -e "${GREEN}✓${NC} $*"; ((PASS++)); }
fail() { echo -e "${RED}✗${NC} $*"; ((FAIL++)); }
warn() { echo -e "${YELLOW}⚠${NC} $*"; ((WARN++)); }
info() { echo -e "${BLUE}→${NC} $*"; }

echo "=========================================="
echo "  Tailscale 跨节点连通性验证"
echo "=========================================="
echo ""

# ==========================================
# 1. 本地 Tailscale 状态
# ==========================================
info "检查 Tailscale 服务状态..."

if ! command -v tailscale &> /dev/null; then
    fail "Tailscale 未安装"
    exit 1
fi

if ! tailscale status --json &> /dev/null; then
    fail "Tailscale 未运行或未加入 Tailnet"
    exit 1
fi
pass "Tailscale 服务运行中"

# 获取本机信息
LOCAL_IP=$(tailscale ip -4 2>/dev/null || echo "unknown")
info "本机 Tailscale IP: $LOCAL_IP"

# ==========================================
# 2. 节点在线检查
# ==========================================
echo ""
info "检查 Tailnet 节点在线状态..."

TAILNET_STATUS=$(tailscale status --json 2>/dev/null)

# 解析节点 (需要 jq)
if command -v jq &> /dev/null; then
    ONLINE_NODES=$(echo "$TAILNET_STATUS" | jq -r '.Peer | to_entries[] | select(.value.Online == true) | .value.HostName' | wc -l)
    TOTAL_NODES=$(echo "$TAILNET_STATUS" | jq -r '.Peer | length')
    
    info "在线节点: $ONLINE_NODES / $TOTAL_NODES"
    
    # 检查关键节点
    for node in us-master cn-akshare; do
        if echo "$TAILNET_STATUS" | jq -e ".Peer | to_entries[] | select(.value.HostName == \"$node\" and .value.Online == true)" &> /dev/null; then
            pass "节点 $node 在线"
        else
            warn "节点 $node 离线或不存在"
        fi
    done
else
    warn "jq 未安装，跳过节点在线状态解析"
    info "请手动检查: tailscale status"
fi

# ==========================================
# 3. 跨节点连通性测试
# ==========================================
echo ""
info "测试跨节点连通性..."

# 从环境变量或默认值获取节点 IP
US_MASTER_IP="${US_MASTER_IP:-100.102.223.44}"
CN_AKSHARE_IP="${CN_AKSHARE_IP:-100.124.178.96}"

# 测试 ping (Tailscale 内网)
if ping -c 1 -W 3 "$US_MASTER_IP" &> /dev/null; then
    pass "US-MASTER ($US_MASTER_IP) 可达"
else
    warn "US-MASTER ($US_MASTER_IP) 不可达 (可能不在同一 Tailnet)"
fi

if ping -c 1 -W 3 "$CN_AKSHARE_IP" &> /dev/null; then
    pass "CN-AKSHARE ($CN_AKSHARE_IP) 可达"
else
    warn "CN-AKSHARE ($CN_AKSHARE_IP) 不可达 (可能不在同一 Tailnet)"
fi

# ==========================================
# 4. 端口连通性测试
# ==========================================
echo ""
info "测试关键端口连通性..."

# 测试 Redis (6379) - 应该仅 Tailscale 可达
test_port() {
    local host=$1
    local port=$2
    local desc=$3
    local should_pass=$4
    
    if timeout 3 bash -c "echo > /dev/tcp/$host/$port" 2>/dev/null; then
        if [ "$should_pass" = "true" ]; then
            pass "$desc ($host:$port) 可达"
        else
            fail "$desc ($host:$port) 不应可达!"
        fi
    else
        if [ "$should_pass" = "true" ]; then
            fail "$desc ($host:$port) 不可达"
        else
            pass "$desc ($host:$port) 已隔离 ✓"
        fi
    fi
}

# 使用 nc 或 curl 测试端口
test_port_nc() {
    local host=$1
    local port=$2
    local desc=$3
    local should_pass=$4
    
    if nc -z -w 3 "$host" "$port" 2>/dev/null; then
        if [ "$should_pass" = "true" ]; then
            pass "$desc ($host:$port) 可达"
        else
            fail "$desc ($host:$port) 不应可达!"
        fi
    else
        if [ "$should_pass" = "true" ]; then
            fail "$desc ($host:$port) 不可达"
        else
            pass "$desc ($host:$port) 已隔离 ✓"
        fi
    fi
}

# 选择测试工具
if command -v nc &> /dev/null; then
    TEST_FUNC=test_port_nc
else
    TEST_FUNC=test_port
fi

# CN-AKSHARE → US-MASTER:6379 (应该可达)
$TEST_FUNC "$US_MASTER_IP" 6379 "CN→Master Redis" "true"

# US-MASTER → US-YF-*:8000 (应该可达)
# 注: YF 节点可能尚未部署，仅警告
US_YF_A_IP="${US_YF_A_IP:-100.102.223.45}"
$TEST_FUNC "$US_YF_A_IP" 8000 "Master→YF-A 数据服务" "true" || warn "US-YF-A 可能尚未部署"

# ==========================================
# 5. 公网暴露检查
# ==========================================
echo ""
info "检查数据端口公网暴露..."

# 获取公网 IP
PUBLIC_IP=$(curl -s ifconfig.me 2>/dev/null || echo "unknown")
info "公网 IP: $PUBLIC_IP"

if [ "$PUBLIC_IP" != "unknown" ]; then
    # 检查 Redis 是否对公网暴露
    $TEST_FUNC "$PUBLIC_IP" 6379 "公网 Redis" "false"
    
    # 检查 Postgres 是否对公网暴露
    $TEST_FUNC "$PUBLIC_IP" 5432 "公网 Postgres" "false"
else
    warn "无法获取公网 IP，跳过公网暴露检查"
fi

# ==========================================
# 6. 本地端口绑定检查
# ==========================================
echo ""
info "检查本地端口绑定..."

# 检查 Redis 绑定
if ss -tlnp 2>/dev/null | grep -q ':6379.*0\.0\.0\.0'; then
    fail "Redis 绑定到 0.0.0.0 (公网可访问)"
elif ss -tlnp 2>/dev/null | grep -q ":6379.*$LOCAL_IP"; then
    pass "Redis 绑定到 Tailscale IP ($LOCAL_IP)"
elif ss -tlnp 2>/dev/null | grep -q ':6379.*127\.0\.0\.1'; then
    warn "Redis 仅绑定到 localhost (跨节点不可达)"
else
    info "Redis 未运行或端口未监听"
fi

# 检查 Postgres 绑定
if ss -tlnp 2>/dev/null | grep -q ':5432.*0\.0\.0\.0'; then
    fail "Postgres 绑定到 0.0.0.0 (公网可访问)"
else
    pass "Postgres 未对公网暴露"
fi

# ==========================================
# 7. SSH 配置检查
# ==========================================
echo ""
info "检查 SSH 配置..."

if [ -f /etc/ssh/sshd_config ]; then
    if grep -q "^PasswordAuthentication no" /etc/ssh/sshd_config; then
        pass "SSH 密码认证已禁用"
    else
        warn "SSH 密码认证未禁用"
    fi
    
    if grep -q "^PermitRootLogin.*no" /etc/ssh/sshd_config; then
        pass "Root SSH 登录已禁用"
    else
        warn "Root SSH 登录未禁用"
    fi
fi

# ==========================================
# 8. 验证结果汇总
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
