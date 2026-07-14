#!/usr/bin/env bash
# ==========================================
# Quant Agent - Tailscale 节点安装/入网脚本
# ==========================================
# 用法:
#   1. 在目标 VPS 上执行:
#      curl -fsSL https://tailscale.com/install.sh | sh
#   2. 运行此脚本加入 Tailnet:
#      bash scripts/deploy/setup_tailscale.sh <role>
#
# 角色:
#   master  → US-MASTER (tag:quant-master)
#   yf      → US-YF-A/B (tag:quant-yf)
#   cn      → CN-AKSHARE (tag:quant-cn)
#
# 前置条件:
#   - Tailscale 已安装 (curl -fsSL https://tailscale.com/install.sh | sh)
#   - root 权限
# ==========================================

set -euo pipefail

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }

# 参数校验
if [ $# -lt 1 ]; then
    echo "用法: $0 <role>"
    echo "角色: master | yf | cn"
    exit 1
fi

ROLE="$1"
TAG=""
HOSTNAME=""

case "$ROLE" in
    master)
        TAG="tag:quant-master"
        HOSTNAME="us-master"
        ;;
    yf)
        TAG="tag:quant-yf"
        HOSTNAME="us-yf-$(hostname | cut -d'-' -f2)"
        ;;
    cn)
        TAG="tag:quant-cn"
        HOSTNAME="cn-akshare"
        ;;
    *)
        log_error "未知角色: $ROLE (可选: master, yf, cn)"
        exit 1
        ;;
esac

# 检查 Tailscale 是否已安装
if ! command -v tailscale &> /dev/null; then
    log_error "Tailscale 未安装，请先执行:"
    echo "  curl -fsSL https://tailscale.com/install.sh | sh"
    exit 1
fi

# 检查是否已加入 Tailnet
if tailscale status --json 2>/dev/null | grep -q '"Self":{'; then
    log_warn "节点已加入 Tailnet，跳过入网步骤"
    tailscale status
else
    log_info "正在加入 Tailnet (角色: $ROLE, 标签: $TAG)..."
    sudo tailscale up \
        --hostname="$HOSTNAME" \
        --advertise-tags="$TAG" \
        --ssh \
        --accept-routes=false \
        --accept-dns=true
    
    log_info "Tailscale 入网成功!"
fi

# 显示 Tailscale 状态
log_info "Tailscale 状态:"
tailscale status

# 获取 Tailscale IP
TS_IP=$(tailscale ip -4)
log_info "Tailscale 内网 IP: $TS_IP"

# 防火墙加固: 禁止数据端口对公网暴露
log_info "加固防火墙规则..."

# 检测公网网卡 (通常是 eth0 或 ens3)
PUBLIC_IFACE=$(ip route get 1.1.1.1 2>/dev/null | awk '{print $5; exit}' || echo "eth0")

# Redis (6379) - 仅允许 Tailscale 接口
if command -v ufw &> /dev/null; then
    # Ubuntu/Debian UFW
    sudo ufw default deny incoming
    sudo ufw allow out
    sudo ufw allow 22/tcp comment 'SSH'
    sudo ufw allow 8000/tcp comment 'API (公网)'
    sudo ufw enable
    log_info "UFW 防火墙已启用 (仅开放 22, 8000)"
elif command -v firewall-cmd &> /dev/null; then
    # CentOS/RHEL firewalld
    sudo firewall-cmd --permanent --add-port=22/tcp
    sudo firewall-cmd --permanent --add-port=8000/tcp
    sudo firewall-cmd --reload
    log_info "Firewalld 已配置 (仅开放 22, 8000)"
else
    log_warn "未检测到防火墙工具，请手动配置 iptables:"
    echo "  # 仅允许 Tailscale 接口访问 Redis"
    echo "  iptables -A INPUT -i tailscale0 -p tcp --dport 6379 -j ACCEPT"
    echo "  iptables -A INPUT -p tcp --dport 6379 -j DROP"
fi

# 验证端口暴露
log_info "验证端口绑定..."
echo ""
echo "=== 监听端口检查 ==="
ss -tlnp | grep -E ':(22|6379|5432|8000)\s' || true
echo ""

# 检查 Redis 是否绑定到 Tailscale IP (而非 0.0.0.0)
if ss -tlnp | grep -q ':6379.*0\.0\.0\.0'; then
    log_warn "Redis 绑定到 0.0.0.0 (公网可访问)!"
    log_warn "请修改 docker-compose 中的 ports 配置:"
    echo "  ports:"
    echo "    - \"\${TAILSCALE_IP:-127.0.0.1}:6379:6379\""
else
    log_info "Redis 端口绑定安全 ✓"
fi

# SSH 配置: 优先使用 Tailscale SSH
log_info "配置 Tailscale SSH..."
if [ -f /etc/ssh/sshd_config ]; then
    # 备份原始配置
    sudo cp /etc/ssh/sshd_config /etc/ssh/sshd_config.bak.$(date +%s)
    
    # 禁用密码认证 (强制密钥)
    if ! grep -q "^PasswordAuthentication no" /etc/ssh/sshd_config; then
        echo "PasswordAuthentication no" | sudo tee -a /etc/ssh/sshd_config > /dev/null
    fi
    
    # 重启 SSH
    sudo systemctl restart sshd 2>/dev/null || sudo service ssh restart 2>/dev/null || true
    log_info "SSH 配置已加固 (禁用密码认证)"
fi

# 输出摘要
echo ""
echo "=========================================="
echo "  Tailscale 节点配置完成"
echo "=========================================="
echo "  角色:     $ROLE"
echo "  标签:     $TAG"
echo "  Hostname: $HOSTNAME"
echo "  Tailscale IP: $TS_IP"
echo "  公网 IP:  $(curl -s ifconfig.me 2>/dev/null || echo 'N/A')"
echo ""
echo "  后续步骤:"
echo "  1. 在 Tailscale Admin Console 确认节点标签"
echo "  2. 更新 .env 中的 TAILSCALE_IP=$TS_IP"
echo "  3. 运行验证脚本: bash scripts/deploy/verify_tailscale.sh"
echo "=========================================="
