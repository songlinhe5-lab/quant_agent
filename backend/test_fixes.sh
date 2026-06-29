#!/bin/bash
# 快速验证测试修复的脚本

echo "=========================================="
echo "验证 test_market.py 修复"
echo "=========================================="
cd "$(dirname "$0")"
python -m pytest tests/test_market.py::TestCircuitBreaker -xvs 2>&1 | tail -20

echo ""
echo "=========================================="
echo "验证 test_router_preferences_extra.py 修复"
echo "=========================================="
python -m pytest tests/test_router_preferences_extra.py::TestUpdatePreferencesRoute::test_update_preferences_merges_and_syncs_yfinance_flag -xvs 2>&1 | tail -20

echo ""
echo "=========================================="
echo "验证 test_router_trade.py 修复"
echo "=========================================="
python -m pytest tests/test_router_trade.py::TestPlaceOrderRiskControl::test_buy_blocked_when_order_value_exceeds_leverage_limit -xvs 2>&1 | tail -20

echo ""
echo "=========================================="
echo "验证 test_main_exception_handlers.py 修复"
echo "=========================================="
python -m pytest tests/test_main_exception_handlers.py::TestQuantExceptionHandler::test_quant_exception_returns_custom_format -xvs 2>&1 | tail -20
