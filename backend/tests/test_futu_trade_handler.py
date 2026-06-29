"""
Futu TradeHandler 单元测试
覆盖: place_order/modify_order/query_order/get_account_info
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest
from futu import ModifyOrderOp, OrderType, TrdEnv, TrdMarket, TrdSide

from backend.services.futu.trade_handler import TradeHandler



def _make_handler():
    conn_mgr = MagicMock()
    conn_mgr.status = "CONNECTED"
    conn_mgr.quote_ctx = MagicMock()
    conn_mgr.get_trade_context = MagicMock(return_value=MagicMock())
    conn_mgr.unlock_trade_if_needed = AsyncMock()
    return TradeHandler(conn_mgr), conn_mgr


class TestTradeHandler:
    """TradeHandler 交易处理器测试套件"""

    @pytest.mark.asyncio
    async def test_place_order_limit_uses_normal_type(self):
        """price>0 时 order_type=NORMAL"""
        handler, conn_mgr = _make_handler()
        trd_ctx = conn_mgr.get_trade_context.return_value
        order_df = pd.DataFrame({"order_id": ["OID123"]})
        with patch("asyncio.to_thread", new=AsyncMock(return_value=(0, order_df))) as mock_thread:
            result = await handler.place_order(
                "HK.00700", qty=100, price=350.0, trd_side=TrdSide.BUY, market=TrdMarket.HK
            )
        args, kwargs = mock_thread.call_args
        assert args[0] == trd_ctx.place_order
        assert kwargs["price"] == 350.0
        assert kwargs["order_type"] == OrderType.NORMAL
        assert result["status"] == "success"
        assert result["order_id"] == "OID123"

    @pytest.mark.asyncio
    async def test_place_order_market_uses_market_type(self):
        """price=0 时 order_type=MARKET 且 price 回退为 1.0"""
        handler, conn_mgr = _make_handler()
        trd_ctx = conn_mgr.get_trade_context.return_value
        order_df = pd.DataFrame({"order_id": ["OID456"]})
        with patch("asyncio.to_thread", new=AsyncMock(return_value=(0, order_df))) as mock_thread:
            result = await handler.place_order(
                "HK.00700", qty=50, price=0.0, trd_side=TrdSide.SELL, market=TrdMarket.HK
            )
        _, kwargs = mock_thread.call_args
        assert kwargs["price"] == 1.0
        assert kwargs["order_type"] == OrderType.MARKET
        assert kwargs["trd_side"] == TrdSide.SELL
        assert result["status"] == "success"
        assert result["order_id"] == "OID456"

    @pytest.mark.asyncio
    async def test_place_order_failure_returns_error(self):
        """place_order 返回非 RET_OK 应返回错误"""
        handler, _ = _make_handler()
        with patch("asyncio.to_thread", new=AsyncMock(return_value=(-1, "insufficient cash"))):
            result = await handler.place_order(
                "HK.00700", qty=100, price=350.0, trd_side=TrdSide.BUY, market=TrdMarket.HK
            )
        assert result["status"] == "error"
        assert "insufficient cash" in result["message"]

    @pytest.mark.asyncio
    async def test_place_order_calls_unlock_trade_if_needed(self):
        """下单前应调用 unlock_trade_if_needed"""
        handler, conn_mgr = _make_handler()
        order_df = pd.DataFrame({"order_id": ["OID789"]})
        with patch("asyncio.to_thread", new=AsyncMock(return_value=(0, order_df))):
            await handler.place_order("HK.00700", 10, 100.0, TrdSide.BUY, TrdMarket.HK)
        conn_mgr.unlock_trade_if_needed.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_place_order_uses_default_format_ticker(self):
        """未传 format_ticker_func 时使用默认 utils.format_ticker"""
        handler, _ = _make_handler()
        order_df = pd.DataFrame({"order_id": ["OID"]})
        with patch("asyncio.to_thread", new=AsyncMock(return_value=(0, order_df))) as mock_thread:
            await handler.place_order("0700", 10, 100.0, TrdSide.BUY, TrdMarket.HK)
        _, kwargs = mock_thread.call_args
        # format_ticker("0700") -> "US.0700" (默认前缀)
        assert kwargs["code"] == "US.0700"

    @pytest.mark.asyncio
    async def test_modify_order_success_returns_cancel_msg(self):
        """改单/撤单成功应返回 success"""
        handler, conn_mgr = _make_handler()
        with patch("asyncio.to_thread", new=AsyncMock(return_value=(0, "ok"))):
            result = await handler.modify_order("OID123", ModifyOrderOp.CANCEL, TrdMarket.HK)
        assert result["status"] == "success"
        assert "OID123" in result["message"]

    @pytest.mark.asyncio
    async def test_modify_order_failure_returns_error(self):
        """改单失败应返回错误"""
        handler, _ = _make_handler()
        with patch("asyncio.to_thread", new=AsyncMock(return_value=(-1, "order not found"))):
            result = await handler.modify_order("OID999", ModifyOrderOp.CANCEL, TrdMarket.HK)
        assert result["status"] == "error"
        assert "撤单失败" in result["message"]

    @pytest.mark.asyncio
    async def test_query_order_success_returns_status(self):
        """查询订单成功应返回 order_status"""
        handler, _ = _make_handler()
        order_df = pd.DataFrame(
            {"order_status": ["FILLED_ALL"], "dealt_avg_price": [350.5], "code": ["HK.00700"]}
        )
        with patch("asyncio.to_thread", new=AsyncMock(return_value=(0, order_df))):
            with patch("asyncio.create_task") as mock_create_task:
                result = await handler.query_order("OID123", TrdMarket.HK)
        assert result["status"] == "success"
        assert result["order_status"] == "FILLED_ALL"
        assert result["dealt_avg_price"] == 350.5
        # FILLED 状态应触发通知
        mock_create_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_query_order_cancelled_triggers_notification(self):
        """CANCELLED 状态应触发通知"""
        handler, _ = _make_handler()
        order_df = pd.DataFrame(
            {"order_status": ["CANCELLED"], "dealt_avg_price": [0.0], "code": ["HK.00700"]}
        )
        with patch("asyncio.to_thread", new=AsyncMock(return_value=(0, order_df))):
            with patch("asyncio.create_task") as mock_create_task:
                result = await handler.query_order("OID", TrdMarket.HK)
        assert result["order_status"] == "CANCELLED"
        mock_create_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_query_order_pending_skips_notification(self):
        """非 FILLED/CANCELLED 状态不应触发通知"""
        handler, _ = _make_handler()
        order_df = pd.DataFrame(
            {"order_status": ["WAITING_SUBMIT"], "dealt_avg_price": [0.0], "code": ["HK.00700"]}
        )
        with patch("asyncio.to_thread", new=AsyncMock(return_value=(0, order_df))):
            with patch("asyncio.create_task") as mock_create_task:
                result = await handler.query_order("OID", TrdMarket.HK)
        assert result["order_status"] == "WAITING_SUBMIT"
        mock_create_task.assert_not_called()

    @pytest.mark.asyncio
    async def test_query_order_not_found_returns_error(self):
        """订单不存在应返回错误"""
        handler, _ = _make_handler()
        with patch("asyncio.to_thread", new=AsyncMock(return_value=(-1, "not found"))):
            result = await handler.query_order("OID_X", TrdMarket.HK)
        assert result["status"] == "error"
        assert "OID_X" in result["message"]

    @pytest.mark.asyncio
    async def test_query_order_empty_df_returns_error(self):
        """空 DataFrame 应返回错误"""
        handler, _ = _make_handler()
        with patch("asyncio.to_thread", new=AsyncMock(return_value=(0, pd.DataFrame()))):
            result = await handler.query_order("OID", TrdMarket.HK)
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_get_account_info_dev_env_uses_mock(self):
        """dev 环境 + 未连接应使用 mock_account_info"""
        handler, conn_mgr = _make_handler()
        conn_mgr.status = "DISCONNECTED"
        with patch.dict("os.environ", {"QUANT_ENV": "development"}):
            result = await handler.get_account_info("HK")
        assert result["status"] == "success"
        assert result["market"] == "HK"
        # mock_account_info 默认 environment 为传入的 env_str
        assert result["environment"] == "SIMULATE"

    @pytest.mark.asyncio
    async def test_get_account_info_success(self):
        """成功获取应返回账户信息和持仓"""
        handler, conn_mgr = _make_handler()
        trd_ctx = conn_mgr.get_trade_context.return_value
        acc_df = pd.DataFrame({"total_assets": [1000000.0], "cash": [250000.0], "power": [250000.0], "market_val": [750000.0], "currency": ["HKD"]})
        pos_df = pd.DataFrame(
            {
                "code": ["HK.00700"],
                "stock_name": ["腾讯"],
                "position_side": ["LONG"],
                "qty": [1000.0],
                "can_sell_qty": [1000.0],
                "cost_price": [300.0],
                "market_val": [400000.0],
                "pl_val": [100000.0],
                "pl_ratio": [33.33],
            }
        )
        # 第一次 to_thread: accinfo_query，第二次: position_list_query
        with patch("asyncio.to_thread", new=AsyncMock(side_effect=[(0, acc_df), (0, pos_df)])):
            result = await handler.get_account_info("HK")
        assert result["status"] == "success"
        assert result["total_assets"] == 1000000.0
        assert result["currency"] == "HKD"
        assert len(result["positions"]) == 1
        assert result["positions"][0]["code"] == "HK.00700"

    @pytest.mark.asyncio
    async def test_get_account_info_accinfo_failure_returns_error(self):
        """accinfo_query 失败应返回错误"""
        handler, _ = _make_handler()
        with patch("asyncio.to_thread", new=AsyncMock(return_value=(-1, "auth failed"))):
            result = await handler.get_account_info("HK")
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_get_account_info_empty_accinfo_returns_error(self):
        """空账户数据应返回错误"""
        handler, _ = _make_handler()
        with patch("asyncio.to_thread", new=AsyncMock(return_value=(0, pd.DataFrame()))):
            result = await handler.get_account_info("HK")
        assert result["status"] == "error"
        assert "账户数据为空" in result["message"]

    @pytest.mark.asyncio
    async def test_get_account_info_exception_returns_error(self):
        """API 抛异常应被吞下并返回错误"""
        handler, conn_mgr = _make_handler()
        trd_ctx = conn_mgr.get_trade_context.return_value

        async def boom(*a, **kw):
            raise RuntimeError("network error")

        with patch("asyncio.to_thread", new=boom):
            result = await handler.get_account_info("HK")
        assert result["status"] == "error"
        assert "network error" in result["message"]

    @pytest.mark.asyncio
    async def test_get_account_info_market_mapping(self):
        """不同 market 参数应映射到正确的 TrdMarket"""
        handler, conn_mgr = _make_handler()
        acc_df = pd.DataFrame({"total_assets": [100.0], "cash": [50.0], "power": [50.0], "market_val": [50.0], "currency": ["USD"]})
        empty_pos = pd.DataFrame()

        with patch("asyncio.to_thread", new=AsyncMock(side_effect=[(0, acc_df), (0, empty_pos)])):
            result = await handler.get_account_info("US")
        assert result["market"] == "US"
        assert result["positions"] == []

    @pytest.mark.asyncio
    async def test_get_account_info_real_env_calls_unlock(self):
        """REAL 环境应调用 unlock_trade_if_needed"""
        handler, conn_mgr = _make_handler()
        with patch.dict("os.environ", {"FUTU_TRD_ENV": "REAL", "QUANT_ENV": "production"}):
            acc_df = pd.DataFrame({"total_assets": [100.0], "cash": [50.0], "power": [50.0], "market_val": [50.0], "currency": ["HKD"]})
            with patch("asyncio.to_thread", new=AsyncMock(side_effect=[(0, acc_df), (0, pd.DataFrame())])):
                result = await handler.get_account_info("HK")
        assert result["status"] == "success"
        assert result["environment"] == "REAL"
        conn_mgr.unlock_trade_if_needed.assert_awaited()
