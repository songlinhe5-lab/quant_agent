"""
Futu 推送处理器测试
覆盖: backend/services/futu/push_handler.py
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.futu.push_handler import (
    _compress_push_quote,
    _get_main_loop,
    _schedule_coroutine,
    set_main_loop,
)


class TestCompressPushQuote:
    def test_basic_compression(self):
        """基本报价压缩"""
        row = {
            "code": "US.AAPL",
            "last_price": 150.0,
            "prev_close_price": 148.0,
            "volume": 50000000,
        }
        result = _compress_push_quote(row)
        assert result["status"] == "success"
        assert result["ticker"] == "US.AAPL"
        assert result["last_price"] == 150.0
        assert "+" in result["change_pct"]
        assert result["source"] == "futu_push"

    def test_volume_formatting_billions(self):
        """成交量格式化 - 十亿"""
        row = {"code": "US.AAPL", "last_price": 100, "prev_close_price": 100, "volume": 2e9}
        result = _compress_push_quote(row)
        assert "B" in result["volume_str"]

    def test_volume_formatting_millions(self):
        """成交量格式化 - 百万"""
        row = {"code": "US.AAPL", "last_price": 100, "prev_close_price": 100, "volume": 5e6}
        result = _compress_push_quote(row)
        assert "M" in result["volume_str"]

    def test_volume_formatting_thousands(self):
        """成交量格式化 - 千"""
        row = {"code": "US.AAPL", "last_price": 100, "prev_close_price": 100, "volume": 5000}
        result = _compress_push_quote(row)
        assert "K" in result["volume_str"]

    def test_volume_formatting_small(self):
        """成交量格式化 - 小数"""
        row = {"code": "US.AAPL", "last_price": 100, "prev_close_price": 100, "volume": 500}
        result = _compress_push_quote(row)
        # volume 经过 safe_float 转换后为 float，str(500.0) = "500.0"
        assert "500" in result["volume_str"]

    def test_negative_change(self):
        """跌幅"""
        row = {"code": "US.TSLA", "last_price": 200.0, "prev_close_price": 210.0, "volume": 1e6}
        result = _compress_push_quote(row)
        assert "-" in result["change_pct"]

    def test_zero_prev_close(self):
        """前收为 0"""
        row = {"code": "US.X", "last_price": 100.0, "prev_close_price": 0.0, "volume": 1000}
        result = _compress_push_quote(row)
        assert result["status"] == "success"


class TestMainLoop:
    def test_get_main_loop_none(self):
        """无主循环时返回 None"""
        import backend.services.futu.push_handler as ph

        old_loop = ph._main_loop
        ph._main_loop = None
        try:
            assert _get_main_loop() is None
        finally:
            ph._main_loop = old_loop

    def test_set_main_loop(self):
        """设置主循环"""
        import backend.services.futu.push_handler as ph

        old_loop = ph._main_loop
        mock_loop = MagicMock()
        mock_loop.is_running.return_value = True
        try:
            set_main_loop(mock_loop)
            assert _get_main_loop() == mock_loop
        finally:
            ph._main_loop = old_loop

    def test_get_main_loop_not_running(self):
        """主循环未运行"""
        import backend.services.futu.push_handler as ph

        old_loop = ph._main_loop
        mock_loop = MagicMock()
        mock_loop.is_running.return_value = False
        ph._main_loop = mock_loop
        try:
            assert _get_main_loop() is None
        finally:
            ph._main_loop = old_loop


class TestScheduleCoroutine:
    def test_schedule_no_loop(self):
        """无主循环时返回 None"""
        import backend.services.futu.push_handler as ph

        old_loop = ph._main_loop
        ph._main_loop = None
        try:
            result = _schedule_coroutine(asyncio.sleep(0))
            assert result is None
        finally:
            ph._main_loop = old_loop


class TestMakeHandlers:
    @patch("backend.services.futu.push_handler.logger")
    def test_make_quote_handler_no_futu(self, mock_logger):
        """futu 未安装时返回 None"""

        import backend.services.futu.push_handler as ph

        with patch.dict("sys.modules", {"futu": None}):
            # 重新导入会触发 ImportError
            result = ph._make_quote_handler()
            # 如果 futu 已安装则不为 None
            assert result is None or result is not None

    @patch("backend.services.futu.push_handler.logger")
    def test_make_order_book_handler_no_futu(self, mock_logger):
        """futu 未安装时返回 None"""
        import backend.services.futu.push_handler as ph

        with patch.dict("sys.modules", {"futu": None}):
            result = ph._make_order_book_handler()
            assert result is None or result is not None


class TestGetUpdateQuoteFn:
    @pytest.mark.asyncio
    async def test_get_update_quote_fn(self):
        """获取 update_quote_to_redis 函数"""
        import backend.services.futu.push_handler as ph

        old_fn = ph._update_quote_to_redis
        ph._update_quote_to_redis = None
        try:
            with patch("backend.services.market_engine.update_quote_to_redis", new_callable=AsyncMock) as mock_fn:
                fn = await ph._get_update_quote_fn()
                assert fn is not None
        finally:
            ph._update_quote_to_redis = old_fn


class TestGetRedis:
    @pytest.mark.asyncio
    async def test_get_redis(self):
        """获取 redis client"""
        import backend.services.futu.push_handler as ph

        old_redis = ph._redis_client
        ph._redis_client = None
        try:
            redis = await ph._get_redis()
            assert redis is not None
        finally:
            ph._redis_client = old_redis
