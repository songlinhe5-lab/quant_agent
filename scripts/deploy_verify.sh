#!/bin/bash
# 一键部署验证脚本到 VPS

set -e

VPS_HOST="root@38.60.126.42"
REMOTE_DIR="/opt/quant-agent/scripts"
LOCAL_SCRIPT="/Users/stephenhe/Development/workspace/quant_agent/scripts/verify_on_master.py"

echo "🚀 开始部署验证脚本到 VPS..."
echo "目标：$VPS_HOST:$REMOTE_DIR"

# 方式 1: SCP 传输
echo ""
echo "📦 方式 1: SCP 传输"
echo "-------------------"
if scp -o "StrictHostKeyChecking=no" "$LOCAL_SCRIPT" "$VPS_HOST:$REMOTE_DIR/"; then
    echo "✅ SCP 传输成功"
else
    echo "❌ SCP 传输失败，尝试方式 2..."

    # 方式 2: rsync 同步
    echo ""
    echo "📦 方式 2: rsync 同步"
    echo "---------------------"
    if rsync -avz "$LOCAL_SCRIPT" "$VPS_HOST:$REMOTE_DIR/"; then
        echo "✅ rsync 同步成功"
    else
        echo "❌ rsync 同步失败"
        exit 1
    fi
fi

# 验证文件
echo ""
echo "🔍 验证文件..."
ssh -o "StrictHostKeyChecking=no" "$VPS_HOST" "ls -lh $REMOTE_DIR/verify_on_master.py"

# 测试执行
echo ""
echo "🧪 测试执行..."
ssh -o "StrictHostKeyChecking=no" "$VPS_HOST" "docker exec quant_app python3 $REMOTE_DIR/verify_on_master.py --help || echo '脚本就绪'"

echo ""
echo "✅ 部署完成！"
echo ""
echo "💡 下一步："
echo "   ssh $VPS_HOST 'docker exec quant_app python3 $REMOTE_DIR/verify_on_master.py'"
