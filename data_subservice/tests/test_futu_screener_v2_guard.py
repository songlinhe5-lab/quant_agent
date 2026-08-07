"""ScreenerHandler V2 不支持守卫测试 (TODO 守卫完整性)

futu-api 不支持 V2 条件选股接口 (StockScreenRequest) 时, screen_stocks 必须返回
明确错误, 绝不能静默返回空结果或伪造数据。screener_handler.py:56 的 `pass` 是
ImportError 守卫, 此处验证守卫下游的错误处理闭环。
"""

from unittest.mock import MagicMock, patch

import pytest

from data_subservice.futu_src.screener_handler import ScreenerHandler


def _make_handler():
    conn_mgr = MagicMock()
    conn_mgr.status = "CONNECTED"
    conn_mgr.quote_ctx = MagicMock()
    return ScreenerHandler(conn_mgr), conn_mgr


@pytest.mark.asyncio
async def test_screen_stocks_v2_unsupported_returns_error():
    """V2 选股接口不可用时返回明确错误, 不静默不造假"""
    handler, _ = _make_handler()
    with patch("data_subservice.futu_src.screener_handler._FUTU_V2_SUPPORT", False):
        result = await handler.screen_stocks("HK", [{"field": "MARKET_CAP", "type": "simple", "min": 1e10}])
    assert result["status"] == "error"
    assert "V2" in result["message"] or "选股" in result["message"]
