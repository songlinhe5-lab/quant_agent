#!/bin/bash
# 一键部署验证脚本到 VPS（含 F0-4 容器内 Futu OpenD 等价验证）

set -e

VPS_HOST="root@38.60.126.42"
REMOTE_DIR="/opt/quant-agent/scripts"
LOCAL_DIR="/Users/stephenhe/Development/workspace/quant_agent/scripts"
VERIFY_MASTER="verify_on_master.py"        # 数据源缓存/健康验证
VERIFY_OPEND="probes/verify_futu_opend.py"  # F0-4 容器内 OpenD 接口级等价探针（BE-ARCH-07o 归口 scripts/probes/）

echo "🚀 开始部署验证脚本到 VPS..."
echo "目标：$VPS_HOST:$REMOTE_DIR"

# 方式 1: SCP 传输（两个脚本）
echo ""
echo "📦 方式 1: SCP 传输"
echo "-------------------"
if scp -o "StrictHostKeyChecking=no" \
      "$LOCAL_DIR/$VERIFY_MASTER" "$LOCAL_DIR/$VERIFY_OPEND" "$VPS_HOST:$REMOTE_DIR/"; then
    echo "✅ SCP 传输成功"
else
    echo "❌ SCP 传输失败，尝试方式 2..."
    echo ""
    echo "📦 方式 2: rsync 同步"
    echo "---------------------"
    if rsync -avz "$LOCAL_DIR/$VERIFY_MASTER" "$LOCAL_DIR/$VERIFY_OPEND" "$VPS_HOST:$REMOTE_DIR/"; then
        echo "✅ rsync 同步成功"
    else
        echo "❌ rsync 同步失败"
        exit 1
    fi
fi

# 验证文件
echo ""
echo "🔍 验证文件..."
ssh -o "StrictHostKeyChecking=no" "$VPS_HOST" \
  "ls -lh $REMOTE_DIR/$VERIFY_MASTER $REMOTE_DIR/$VERIFY_OPEND"

# 测试执行（现有数据源缓存/健康验证）
echo ""
echo "🧪 测试执行（verify_on_master）..."
ssh -o "StrictHostKeyChecking=no" "$VPS_HOST" \
  "docker exec quant_app python3 $REMOTE_DIR/$VERIFY_MASTER --help || echo '脚本就绪'"

# F0-4: 容器内 OpenD 等价验证
echo ""
echo "🧪 F0-4 容器内 OpenD 等价验证（verify_futu_opend）..."
echo "    前置检查: ① docker-gw-forward@11111 是否 enable；② 容器内 futu-api 是否安装"
ssh -o "StrictHostKeyChecking=no" "$VPS_HOST" bash -s <<REMOTE
set +e
echo "  ├─ systemd socat 转发状态:"
systemctl is-active docker-gw-forward@11111.service 2>/dev/null || echo "      (未启用/未知)"
echo "  ├─ 容器内 futu-api 版本:"
docker exec quant_app python3 -c "import futu; print('     futu-api', futu.__version__ if hasattr(futu,'__version__') else 'ok')" 2>/dev/null || echo "      (容器内未安装 futu-api)"
echo "  ├─ 执行 OpenD 等价探针:"
docker exec quant_app python3 "$REMOTE_DIR/$VERIFY_OPEND" 2>&1
echo "  └─ exit_code=\$?"
REMOTE

echo ""
echo "✅ 部署完成！"
echo ""
echo "💡 后续手动复跑 F0-4："
echo "   ssh $VPS_HOST 'docker exec quant_app python3 $REMOTE_DIR/$VERIFY_OPEND'"
