"""yfinance worker 限流 error_category 标注测试（BE-ARCH-08d 补漏）。

验证 handle_yfinance 作为 yfinance 结果唯一出口，对含 error 的响应统一补上
error_category=rate_limit，使主服务 router 能正确区分限流（退避）与普通失败（熔断），
避免被限流节点被误判为普通故障触发熔断器。
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

# 允许以脚本方式运行（子服务独立 pytest 入口）
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from data_subservice.yfinance_worker import _annotate_error_category, handle_yfinance  # noqa: E402


class TestAnnotateErrorCategory:
    def test_rate_limit_error_gets_category(self):
        out = _annotate_error_category(
            {"symbol": "AAPL", "error": "Too Many Requests. Rate limited. Try after a while.", "source": "yfinance"}
        )
        assert out["error_category"] == "rate_limit"
        assert out["error"] == "Too Many Requests. Rate limited. Try after a while."

    def test_normal_error_not_annotated(self):
        out = _annotate_error_category({"symbol": "AAPL", "error": "no history data", "source": "yfinance"})
        assert "error_category" not in out

    def test_existing_category_respected(self):
        out = _annotate_error_category({"error": "x", "error_category": "ip_blocked"})
        assert out["error_category"] == "ip_blocked"

    def test_success_result_untouched(self):
        out = _annotate_error_category({"symbol": "AAPL", "price": 302.25})
        assert "error_category" not in out
        assert out["price"] == 302.25

    def test_non_dict_passthrough(self):
        assert _annotate_error_category("not a dict") == "not a dict"


class TestHandleYfinance:
    @pytest.mark.asyncio
    async def test_quote_rate_limit_annotated(self):
        with patch("data_subservice.yfinance_worker.yfinance_service") as svc:
            svc.get_quote = AsyncMock(
                return_value={"symbol": "AAPL", "error": "Too Many Requests. Rate limited.", "source": "yfinance"}
            )
            out = await handle_yfinance("QUOTE", {"symbol": "AAPL"})
        assert out["error_category"] == "rate_limit"

    @pytest.mark.asyncio
    async def test_quote_success_untouched(self):
        with patch("data_subservice.yfinance_worker.yfinance_service") as svc:
            svc.get_quote = AsyncMock(return_value={"symbol": "AAPL", "price": 302.25, "source": "yfinance"})
            out = await handle_yfinance("QUOTE", {"symbol": "AAPL"})
        assert out["price"] == 302.25
        assert "error_category" not in out

    @pytest.mark.asyncio
    async def test_worker_exception_rate_limit_annotated(self):
        with patch("data_subservice.yfinance_worker.yfinance_service") as svc:
            svc.get_history = AsyncMock(side_effect=RuntimeError("Too Many Requests. Rate limited."))
            out = await handle_yfinance("HISTORY", {"symbol": "AAPL"})
        assert out["error_category"] == "rate_limit"
