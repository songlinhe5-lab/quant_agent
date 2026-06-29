"""Futu ScreenerHandler 单元测试
覆盖: get_market_snapshots / screen_stocks (9 种 filter + 错误分支) / get_stock_basicinfo
"""
import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest
from futu import RET_OK, StockScreenRequest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from backend.services.futu.screener_handler import ScreenerHandler


def _make_handler(status="CONNECTED"):
    """构造 ScreenerHandler + mock conn_mgr"""
    conn_mgr = MagicMock()
    conn_mgr.status = status
    conn_mgr.quote_ctx = MagicMock() if status == "CONNECTED" else None
    return ScreenerHandler(conn_mgr), conn_mgr


def _screen_ok(items, is_last=True):
    """构造 get_stock_screen 成功返回 (RET_OK, (is_last, items))"""
    return (RET_OK, (is_last, items))


def _item(code="00700", name="Tencent", price=350.0, chg=0.05, roe=0.20):
    """构造一条选股结果 (code/name/price/price_change_pct/roe)"""
    return {"results": [
        {"property": {"name": 1101}, "value_type": 1, "sval": code},
        {"property": {"name": 1102}, "value_type": 1, "sval": name},
        {"property": {"name": 2201}, "value_type": 4, "dval": price},
        {"property": {"name": 3102}, "value_type": 4, "dval": chg},
        {"property": {"name": 4110}, "value_type": 4, "dval": roe},
    ]}


class TestGetMarketSnapshots:
    """get_market_snapshots: 未连接/空数据/成功"""

    @pytest.mark.asyncio
    async def test_not_connected_returns_error(self):
        handler, _ = _make_handler("DISCONNECTED")
        r = await handler.get_market_snapshots(["HK.00700"])
        assert r["status"] == "error" and "未连接" in r["message"]

    @pytest.mark.asyncio
    async def test_empty_df_returns_error(self):
        handler, _ = _make_handler()
        with patch("asyncio.to_thread", new=AsyncMock(return_value=(RET_OK, pd.DataFrame()))), \
             patch("asyncio.sleep", new=AsyncMock()):
            r = await handler.get_market_snapshots(["HK.00700"])
        assert r["status"] == "error" and "失败" in r["message"]

    @pytest.mark.asyncio
    async def test_success_returns_records(self):
        handler, _ = _make_handler()
        df = pd.DataFrame({"code": ["HK.00700"], "price": [350.0]})
        with patch("asyncio.to_thread", new=AsyncMock(return_value=(RET_OK, df))), \
             patch("asyncio.sleep", new=AsyncMock()):
            r = await handler.get_market_snapshots(["HK.00700"])
        assert r["status"] == "success"
        assert r["data"][0]["code"] == "HK.00700"


class TestScreenStocks:
    """screen_stocks: V2检测/连接检测/9种filter/错误分支/结果格式化"""

    @pytest.mark.asyncio
    async def test_v2_not_supported_returns_error(self):
        handler, _ = _make_handler()
        with patch("backend.services.futu.screener_handler._FUTU_V2_SUPPORT", False):
            r = await handler.screen_stocks("HK", [])
        assert r["status"] == "error" and "V2" in r["message"]

    @pytest.mark.asyncio
    async def test_not_connected_returns_error(self):
        handler, _ = _make_handler("DISCONNECTED")
        r = await handler.screen_stocks("HK", [])
        assert r["status"] == "error" and "未连接" in r["message"]

    @pytest.mark.asyncio
    async def test_unknown_type_returns_error(self):
        handler, _ = _make_handler()
        filters = [{"field": "FOO", "type": "unknown_type", "min": 1}]
        r = await handler.screen_stocks("HK", filters)
        assert r["status"] == "error" and "不支持" in r["message"]

    @pytest.mark.asyncio
    async def test_inner_exception_returns_error(self):
        handler, _ = _make_handler()
        with patch("backend.services.futu.screener_handler.StockScreenRequest") as MockReq:
            MockReq.return_value.add_simple_property.side_effect = RuntimeError("boom")
            r = await handler.screen_stocks("HK", [{"field": "PRICE", "type": "simple", "min": 1}])
        assert r["status"] == "error" and "异常" in r["message"]

    @pytest.mark.parametrize("flt", [
        {"field": "PRICE", "type": "simple", "min": 1, "max": 1000},
        {"field": "ROE", "type": "financial", "min": 0.15},
        {"field": "PRICE_CHANGE_PCT", "type": "accumulate", "min": 0.05, "days": 5},
        {"field": "HIST_PERCENTILE_PE", "type": "featured", "max": 0.3},
        {"field": "RSI_BOTTOM_DIVERGE", "type": "indicator_pattern", "period": "K_DAY"},
        {"field": "MA", "type": "indicator_positional", "second_indicator": "EMA", "position": "CROSS_UP", "period": "K_DAY"},  # noqa: E501
        {"field": "SHAPE_TYPE", "type": "kline_shape", "period": "K_DAY"},
        {"field": "BROKER_NUM", "type": "broker", "days": 5},
        {"field": "STOCK_IV", "type": "option", "min": 0.5, "period": "K_DAY"},
    ])
    @pytest.mark.asyncio
    async def test_filter_types_dispatched_successfully(self, flt):
        handler, conn_mgr = _make_handler()
        conn_mgr.quote_ctx.get_stock_screen.return_value = _screen_ok([])
        # kline_shape/option 真实方法对 period 字符串做 int() 转换报错,需 mock
        mocks = []
        if flt.get("type") == "kline_shape":
            mocks = [
                patch.object(StockScreenRequest, "add_kline_shape", return_value=None),
                patch.object(StockScreenRequest, "add_retrieve_kline_shape", return_value=None),
            ]
        elif flt.get("type") == "option":
            mocks = [
                patch.object(StockScreenRequest, "add_option", return_value=None),
                patch.object(StockScreenRequest, "add_retrieve_option", return_value=None),
            ]
        for m in mocks:
            m.start()
        try:
            with patch("asyncio.sleep", new=AsyncMock()):
                r = await handler.screen_stocks("HK", [flt])
        finally:
            for m in mocks:
                m.stop()
        assert r["status"] == "success"

    @pytest.mark.asyncio
    async def test_smart_type_correction_fixes_wrong_type(self):
        handler, conn_mgr = _make_handler()
        conn_mgr.quote_ctx.get_stock_screen.return_value = _screen_ok([])
        with patch("asyncio.sleep", new=AsyncMock()):
            # PRICE 是 SimpleProperty 但声明为 financial，应被自动纠正
            r = await handler.screen_stocks("HK", [{"field": "PRICE", "type": "financial", "min": 1}])  # noqa: E501
        assert r["status"] == "success"

    @pytest.mark.asyncio
    async def test_plate_filter_translates_name_and_succeeds(self):
        handler, conn_mgr = _make_handler()
        conn_mgr.quote_ctx.get_plate_list.return_value = (
            RET_OK, pd.DataFrame({"plate_name": ["半导体"], "code": ["HK.BK0001"]})
        )
        conn_mgr.quote_ctx.get_stock_screen.return_value = _screen_ok([])
        with patch("asyncio.sleep", new=AsyncMock()):
            r = await handler.screen_stocks("HK", [{"type": "plate", "value": ["半导体"]}])
        assert r["status"] == "success"

    @pytest.mark.asyncio
    async def test_exclude_plate_filters_out_matching_stocks(self):
        handler, conn_mgr = _make_handler()
        conn_mgr.quote_ctx.get_stock_screen.return_value = _screen_ok([
            _item(code="00700"), _item(code="00001")
        ])
        conn_mgr.quote_ctx.get_plate_stock.return_value = (
            RET_OK, pd.DataFrame({"code": ["HK.00001"]})
        )
        with patch("asyncio.sleep", new=AsyncMock()):
            r = await handler.screen_stocks("HK", [{"type": "exclude_plate", "value": ["BK0001"]}])  # noqa: E501
        assert r["status"] == "success"
        assert len(r["data"]) == 1
        assert r["data"][0]["symbol"] == "HK.00700"

    @pytest.mark.asyncio
    async def test_get_stock_screen_error_returns_error(self):
        handler, conn_mgr = _make_handler()
        conn_mgr.quote_ctx.get_stock_screen.return_value = (-1, "err msg")
        with patch("asyncio.sleep", new=AsyncMock()):
            r = await handler.screen_stocks("HK", [])
        assert r["status"] == "error" and "选股失败" in r["message"]

    @pytest.mark.asyncio
    async def test_empty_result_returns_empty_success(self):
        handler, conn_mgr = _make_handler()
        conn_mgr.quote_ctx.get_stock_screen.return_value = _screen_ok([])
        with patch("asyncio.sleep", new=AsyncMock()):
            r = await handler.screen_stocks("HK", [])
        assert r["status"] == "success" and r["data"] == []

    @pytest.mark.asyncio
    async def test_three_tuple_response_handled_correctly(self):
        handler, conn_mgr = _make_handler()
        # 3-element tuple: (is_last, all_count, items)
        conn_mgr.quote_ctx.get_stock_screen.return_value = (RET_OK, (True, 0, []))
        with patch("asyncio.sleep", new=AsyncMock()):
            r = await handler.screen_stocks("HK", [])
        assert r["status"] == "success"

    @pytest.mark.asyncio
    async def test_success_deduplicates_and_formats_pct_fields(self):
        handler, conn_mgr = _make_handler()
        conn_mgr.quote_ctx.get_stock_screen.return_value = _screen_ok([
            _item(code="00700", price=350.0, chg=0.05, roe=0.20),
            _item(code="00700", price=350.0, chg=0.05, roe=0.20),
        ])
        with patch("asyncio.sleep", new=AsyncMock()):
            r = await handler.screen_stocks("HK", [])
        assert r["status"] == "success"
        assert len(r["data"]) == 1
        item = r["data"][0]
        assert item["symbol"] == "HK.00700"
        assert item["name"] == "Tencent"
        assert item["price"] == 350.0
        assert item["chg"] == 0.05
        assert item["roe"] == 0.20
        assert item.get("roe_fmt") == "20.00%"


class TestGetStockBasicinfo:
    """get_stock_basicinfo: 未连接/API错误/成功"""

    @pytest.mark.asyncio
    async def test_not_connected_returns_error(self):
        handler, _ = _make_handler("DISCONNECTED")
        r = await handler.get_stock_basicinfo("HK", "STOCK")
        assert r["status"] == "error" and "未连接" in r["message"]

    @pytest.mark.asyncio
    async def test_api_error_returns_error(self):
        handler, _ = _make_handler()
        with patch("asyncio.to_thread", new=AsyncMock(return_value=(-1, "err"))):
            r = await handler.get_stock_basicinfo("HK", "STOCK")
        assert r["status"] == "error" and "失败" in r["message"]

    @pytest.mark.asyncio
    async def test_success_returns_records(self):
        handler, _ = _make_handler()
        df = pd.DataFrame({"code": ["HK.00700"], "name": ["Tencent"]})
        with patch("asyncio.to_thread", new=AsyncMock(return_value=(RET_OK, df))):
            r = await handler.get_stock_basicinfo("HK", "STOCK")
        assert r["status"] == "success"
        assert r["data"][0]["code"] == "HK.00700"
