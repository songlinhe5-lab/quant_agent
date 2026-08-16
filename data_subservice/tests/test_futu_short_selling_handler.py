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
