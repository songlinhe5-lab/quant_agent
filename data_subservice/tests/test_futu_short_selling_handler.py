"""Futu ShortSellingHandler 单元测试 (卖空榜 / 每日卖空量)"""

from unittest.mock import MagicMock

import pandas as pd
import pytest

from data_subservice.futu_src.short_selling_handler import ShortSellingHandler


def _make_handler():
    conn_mgr = MagicMock()
    ctx = MagicMock()
    conn_mgr.get_quote_ctx.return_value = ctx
    return ShortSellingHandler(conn_mgr), conn_mgr, ctx


class TestShortSellingHandler:
    # ── get_short_selling_rank ──
    @pytest.mark.asyncio
    async def test_get_short_selling_rank_success(self):
        handler, _, ctx = _make_handler()
        df = pd.DataFrame(
            {
                "code": ["HK.00700", "HK.09988"],
                "name": ["腾讯", "阿里"],
                "short_sell_turnover": [1.2e9, 3.4e8],
                "short_sell_ratio": [0.25, 0.18],
            }
        )
        ctx.get_short_selling_rank.return_value = (0, df)
        result = await handler.get_short_selling_rank("HK.00700", market="HK")
        assert result["status"] == "success"
        assert len(result["data"]) == 2
        assert result["data"][0]["code"] == "HK.00700"

    @pytest.mark.asyncio
    async def test_get_short_selling_rank_failure(self):
        handler, _, ctx = _make_handler()
        ctx.get_short_selling_rank.return_value = (-1, "api error")
        result = await handler.get_short_selling_rank("HK.00700", market="HK")
        assert result["status"] == "error"
        assert "api error" in result["message"]

    @pytest.mark.asyncio
    async def test_get_short_selling_rank_no_ctx(self):
        handler, conn_mgr, _ = _make_handler()
        conn_mgr.get_quote_ctx.return_value = None
        result = await handler.get_short_selling_rank("HK.00700", market="HK")
        assert result["status"] == "error"
        assert "未连接" in result["message"]

    @pytest.mark.asyncio
    async def test_get_short_selling_rank_unsupported(self):
        handler, _, _ = _make_handler()
        result = await handler.get_short_selling_rank("BAD", market="HK", is_unsupported_func=lambda t: True)
        assert result["status"] == "error"
        assert "不支持" in result["message"]

    # ── get_daily_short_volume ──
    @pytest.mark.asyncio
    async def test_get_daily_short_volume_success(self):
        handler, _, ctx = _make_handler()
        df = pd.DataFrame(
            {
                "code": ["HK.00700"],
                "short_volume": [1_000_000],
                "total_volume": [5_000_000],
                "date": ["2026-08-15"],
            }
        )
        ctx.get_daily_short_volume.return_value = (0, df, "")
        result = await handler.get_daily_short_volume("HK.00700")
        assert result["status"] == "success"
        assert result["data"][0]["code"] == "HK.00700"

    @pytest.mark.asyncio
    async def test_get_daily_short_volume_failure(self):
        handler, _, ctx = _make_handler()
        ctx.get_daily_short_volume.return_value = (-1, "fail", "")
        result = await handler.get_daily_short_volume("HK.00700")
        assert result["status"] == "error"
        assert "fail" in result["message"]

    @pytest.mark.asyncio
    async def test_get_daily_short_volume_no_ctx(self):
        handler, conn_mgr, _ = _make_handler()
        conn_mgr.get_quote_ctx.return_value = None
        result = await handler.get_daily_short_volume("HK.00700")
        assert result["status"] == "error"
        assert "未连接" in result["message"]

    @pytest.mark.asyncio
    async def test_get_daily_short_volume_bad_shape(self):
        handler, _, ctx = _make_handler()
        ctx.get_daily_short_volume.return_value = "weird"
        result = await handler.get_daily_short_volume("HK.00700")
        assert result["status"] == "error"
        assert "形态异常" in result["message"]

    async def test_get_short_selling_rank_empty_code(self):
        # BE-ARCH: 卖空榜为市场级接口, ticker 可选。仅当既无 market 又无法从 code
        # 推导市场时才报错（纯市场模式 market=已给时应放行, 见 test_get_short_selling_rank_market_only）
        handler, _, ctx = _make_handler()
        result = await handler.get_short_selling_rank("BAD", format_ticker_func=lambda t: "")
        assert result["status"] == "error"
        assert "未提供标的代码且无法推导卖空榜市场" in result["message"]

    async def test_get_short_selling_rank_market_only(self):
        # F1-1 纯市场模式: ticker 为空但 market=HK 已显式给出 -> 跳过 code 推导,
        # 直接以 market 拉全市场卖空榜
        handler, _, ctx = _make_handler()
        from futu import RET_OK

        ctx.get_short_selling_rank.return_value = (RET_OK, [{"code": "HK.00700", "short_sell_volume": 1.0}])
        result = await handler.get_short_selling_rank(None, market="HK")
        assert result["status"] == "success"
        assert result["count"] == 1
        assert result["market"] == "HK"

    async def test_get_short_selling_rank_market_derive_fail(self):
        handler, _, ctx = _make_handler()
        result = await handler.get_short_selling_rank("WEIRD", format_ticker_func=lambda t: t)
        assert result["status"] == "error"
        assert "无法推导卖空榜市场" in result["message"]

    async def test_get_short_selling_rank_exception(self):
        handler, _, ctx = _make_handler()
        ctx.get_short_selling_rank.side_effect = RuntimeError("boom")
        result = await handler.get_short_selling_rank("HK.00700", market="HK")
        assert result["status"] == "error"
        assert "boom" in result["message"]

    async def test_get_short_selling_rank_non_dataframe_rows(self):
        handler, _, ctx = _make_handler()
        from futu import RET_OK

        ctx.get_short_selling_rank.return_value = (RET_OK, [{"code": "HK.00700"}])
        result = await handler.get_short_selling_rank("HK.00700", market="HK")
        assert result["status"] == "success"
        assert result["count"] == 1

    async def test_get_daily_short_volume_empty_code(self):
        handler, _, ctx = _make_handler()
        result = await handler.get_daily_short_volume("BAD", format_ticker_func=lambda t: "")
        assert result["status"] == "error"
        assert "格式无法识别" in result["message"]

    async def test_get_daily_short_volume_no_data(self):
        handler, _, ctx = _make_handler()
        from futu import RET_OK

        ctx.get_daily_short_volume.return_value = (RET_OK, [])
        result = await handler.get_daily_short_volume("HK.00700")
        assert result["status"] == "no_data"
        assert result["count"] == 0

    async def test_get_daily_short_volume_exception(self):
        handler, _, ctx = _make_handler()
        ctx.get_daily_short_volume.side_effect = RuntimeError("kaboom")
        result = await handler.get_daily_short_volume("HK.00700")
        assert result["status"] == "error"
        assert "kaboom" in result["message"]


def test_market_from_code(monkeypatch):
    from futu import Market

    from data_subservice.futu_src.short_selling_handler import _market_from_code

    # 当前 futu 版本 Market 无 CN 属性(沪深用 SH/SZ); 源码合并返回 CN,
    # 此处为覆盖 line 39 分支临时补齐该枚举属性, 不改动源码。
    monkeypatch.setattr(Market, "CN", "CN", raising=False)

    assert _market_from_code("HK.00700") is Market.HK
    assert _market_from_code("US.AAPL") is Market.US
    assert _market_from_code("SH.600519") is Market.CN
    assert _market_from_code("SZ.000001") is Market.CN
    assert _market_from_code("BADCODE") is None
