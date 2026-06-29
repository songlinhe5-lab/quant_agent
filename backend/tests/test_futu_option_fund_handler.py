"""
Futu OptionFundHandler 单元测试
覆盖: get_option_chain/get_fund_flow/get_fundamental
"""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest
from futu import RET_OK

from backend.services.futu.cache_manager import CacheManager
from backend.services.futu.option_fund_handler import OptionFundHandler


def _make_handler(connected=True):
    conn_mgr = MagicMock()
    conn_mgr.status = "CONNECTED" if connected else "DISCONNECTED"
    conn_mgr.quote_ctx = MagicMock() if connected else None
    cache_mgr = CacheManager()
    return OptionFundHandler(conn_mgr, cache_mgr), conn_mgr, cache_mgr


def _fmt(t):
    return t.upper()


def _unsupported(t):
    t = t.upper()
    return "=" in t or "-" in t or "^" in t or t in ["GC=F"]


class TestOptionFundHandler:
    """OptionFundHandler 期权资金处理器测试套件"""

    @pytest.mark.asyncio
    async def test_get_option_chain_unsupported_returns_error(self):
        """不支持资产应返回错误"""
        handler, _, _ = _make_handler()
        result = await handler.get_option_chain("GC=F", is_unsupported_func=_unsupported, format_ticker_func=_fmt)
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_get_option_chain_cache_hit(self):
        """缓存命中（TTL 3600s）应直接返回"""
        handler, _, cache_mgr = _make_handler()
        cache_mgr.set_option_chain_cache(
            "futu_option_chain_HK.00700_2026-01-01",
            time.time(),
            {"status": "success", "cached": True},
        )
        result = await handler.get_option_chain("HK.00700", expiration_date="2026-01-01")
        assert result.get("cached") is True

    @pytest.mark.asyncio
    async def test_get_option_chain_dev_env_uses_mock(self):
        """dev 环境未连接应使用 mock"""
        handler, conn_mgr, _ = _make_handler(connected=False)
        conn_mgr.status = "DISCONNECTED"
        conn_mgr.quote_ctx = None
        with patch.dict("os.environ", {"QUANT_ENV": "development"}):
            result = await handler.get_option_chain("HK.00700")
        assert result["status"] == "success"
        assert result["source"] == "mock"

    @pytest.mark.asyncio
    async def test_get_option_chain_no_ctx_returns_error(self):
        """非 dev 环境未连接应返回错误"""
        handler, conn_mgr, _ = _make_handler(connected=False)
        conn_mgr.status = "DISCONNECTED"
        with patch.dict("os.environ", {"QUANT_ENV": "production"}):
            result = await handler.get_option_chain("HK.00700", expiration_date="2026-01-01")
        assert result["status"] == "error"
        assert "未连接" in result["message"]

    @pytest.mark.asyncio
    async def test_get_option_chain_no_exp_fetches_date_first(self):
        """未传 expiration_date 应先调用 get_option_expiration_date"""
        handler, conn_mgr, _ = _make_handler()
        # 顺序：get_option_expiration_date → get_option_chain
        date_df = pd.DataFrame({"strike_time": ["2026-03-20 16:00:00"]})
        chain_df = pd.DataFrame({"code": ["OPT1"], "option_type": ["CALL"], "strike_price": [350.0]})

        async def fake_to_thread(fn, *args, **kwargs):
            if fn == conn_mgr.quote_ctx.get_option_expiration_date:
                return (RET_OK, date_df)
            return (RET_OK, chain_df)

        with patch("asyncio.to_thread", new=fake_to_thread):
            result = await handler.get_option_chain("HK.00700")
        assert result["status"] == "success"
        assert result["expiration_date"] == "2026-03-20"
        assert result["count"] == 1

    @pytest.mark.asyncio
    async def test_get_option_chain_exp_fetch_failure_returns_error(self):
        """get_option_expiration_date 失败应返回错误"""
        handler, conn_mgr, _ = _make_handler()

        async def fake_to_thread(fn, *args, **kwargs):
            return (-1, "no date data")

        with patch("asyncio.to_thread", new=fake_to_thread):
            result = await handler.get_option_chain("HK.00700")
        assert result["status"] == "error"
        assert "无法获取到期日列表" in result["message"]

    @pytest.mark.asyncio
    async def test_get_option_chain_chain_fetch_failure_returns_error(self):
        """get_option_chain 失败应返回错误（不缓存）"""
        handler, conn_mgr, _ = _make_handler()

        async def fake_to_thread(fn, *args, **kwargs):
            return (-1, "no chain data")

        with patch("asyncio.to_thread", new=fake_to_thread):
            result = await handler.get_option_chain("HK.00700", expiration_date="2026-01-01")
        assert result["status"] == "error"
        assert "期权链获取失败" in result["message"]

    @pytest.mark.asyncio
    async def test_get_option_chain_success_caches_result(self):
        """成功获取应缓存结果"""
        handler, _, cache_mgr = _make_handler()
        chain_df = pd.DataFrame(
            {"code": ["OPT1", "OPT2"], "option_type": ["CALL", "PUT"], "strike_price": [350.0, 360.0]}
        )
        with patch("asyncio.to_thread", new=AsyncMock(return_value=(RET_OK, chain_df))):
            result = await handler.get_option_chain("HK.00700", expiration_date="2026-01-01")
        assert result["status"] == "success"
        cached = cache_mgr.get_option_chain_cache("futu_option_chain_HK.00700_2026-01-01")
        assert cached is not None
        assert cached[1]["count"] == 2

    @pytest.mark.asyncio
    async def test_get_fund_flow_unsupported_returns_error(self):
        """不支持资产应返回错误"""
        handler, _, _ = _make_handler()
        result = await handler.get_fund_flow("GC=F", is_unsupported_func=_unsupported)
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_get_fund_flow_cache_hit(self):
        """缓存命中（TTL 60s）应直接返回"""
        handler, _, cache_mgr = _make_handler()
        cache_mgr.set_fund_flow_cache("futu_fund_flow_HK.00700", time.time(), {"status": "success", "cached": True})
        result = await handler.get_fund_flow("HK.00700")
        assert result.get("cached") is True

    @pytest.mark.asyncio
    async def test_get_fund_flow_dev_env_uses_mock(self):
        """dev 环境应使用 mock"""
        handler, conn_mgr, _ = _make_handler(connected=False)
        conn_mgr.status = "DISCONNECTED"
        conn_mgr.quote_ctx = None
        with patch.dict("os.environ", {"QUANT_ENV": "development"}):
            result = await handler.get_fund_flow("HK.00700")
        assert result["status"] == "success"
        assert result["source"] == "mock"

    @pytest.mark.asyncio
    async def test_get_fund_flow_no_ctx_returns_error(self):
        """非 dev 环境未连接应返回错误"""
        handler, conn_mgr, _ = _make_handler(connected=False)
        conn_mgr.status = "DISCONNECTED"
        with patch.dict("os.environ", {"QUANT_ENV": "production"}):
            result = await handler.get_fund_flow("HK.00700")
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_get_fund_flow_circuit_breaker_returns_mock(self):
        """熔断期内应返回 mock 数据"""
        handler, _, cache_mgr = _make_handler()
        cache_mgr.ff_circuit_breaker_until = time.time() + 100  # 仍在熔断期
        result = await handler.get_fund_flow("HK.00700")
        assert result["source"] == "mock"

    @pytest.mark.asyncio
    async def test_get_fund_flow_frequency_limit_triggers_circuit_breaker(self):
        """频率限制错误应触发熔断并返回 mock"""
        handler, conn_mgr, cache_mgr = _make_handler()
        cache_mgr.ff_lock = None  # 确保走创建锁分支

        # 加速 sleep 防止真实等待
        with patch("asyncio.sleep", new=AsyncMock(return_value=None)), patch(
            "asyncio.to_thread",
            new=AsyncMock(return_value=(-1, "频率太高，请稍后再试")),
        ):
            result = await handler.get_fund_flow("HK.00700")
        assert result["source"] == "mock"
        # 熔断时间应被设置为 ~60s 后
        assert cache_mgr.ff_circuit_breaker_until > time.time()

    @pytest.mark.asyncio
    async def test_get_fund_flow_fetch_failure_returns_error(self):
        """非限流错误应返回错误并缓存"""
        handler, _, cache_mgr = _make_handler()
        cache_mgr.ff_lock = None

        with patch("asyncio.sleep", new=AsyncMock(return_value=None)), patch(
            "asyncio.to_thread",
            new=AsyncMock(return_value=(-1, "permission denied")),
        ):
            result = await handler.get_fund_flow("US.AAPL")  # 非 HK 不走 broker 分支
        assert result["status"] == "error"
        cached = cache_mgr.get_fund_flow_cache("futu_fund_flow_US.AAPL")
        assert cached is not None

    @pytest.mark.asyncio
    async def test_get_fund_flow_hk_success_with_broker_queue(self):
        """HK 标的成功获取应包含 broker_queue 与 order_book_level_1"""
        handler, conn_mgr, cache_mgr = _make_handler()
        cache_mgr.ff_lock = None

        capital_df = pd.DataFrame({"capital_in_super": [100], "capital_in_big": [200], "capital_out_super": [50], "capital_out_big": [30]})
        broker_bid_df = pd.DataFrame({"id": [1, 2], "broker_name": ["A", "B"]})
        broker_ask_df = pd.DataFrame({"id": [3], "broker_name": ["C"]})
        ob_data = {"Bid": [(350.0, 1000)], "Ask": [(350.5, 800)]}

        # 模拟所有 to_thread 调用顺序：
        # 1) get_capital_distribution -> (RET_OK, capital_df)
        # 2) subscribe -> (RET_OK, "")
        # 3) get_broker_queue -> (RET_OK, bid_df, ask_df)
        # 4) get_order_book -> (RET_OK, ob_data)
        results = [
            (RET_OK, capital_df),
            (RET_OK, ""),
            (RET_OK, broker_bid_df, broker_ask_df),
            (RET_OK, ob_data),
        ]

        async def fake_to_thread(fn, *args, **kwargs):
            return results.pop(0)

        with patch("asyncio.sleep", new=AsyncMock(return_value=None)), patch(
            "asyncio.to_thread", new=fake_to_thread
        ):
            result = await handler.get_fund_flow("HK.00700")
        assert result["status"] == "success"
        assert result["broker_queue"] is not None
        assert result["order_book_level_1"] is not None
        assert result["order_book_level_1"]["bid1"]["price"] == 350.0

    @pytest.mark.asyncio
    async def test_get_fund_flow_us_success_without_broker_queue(self):
        """US 标的成功获取应 broker_queue=None"""
        handler, _, cache_mgr = _make_handler()
        cache_mgr.ff_lock = None

        capital_df = pd.DataFrame({"capital_in_super": [100], "capital_in_big": [200], "capital_out_super": [50], "capital_out_big": [30]})

        with patch("asyncio.sleep", new=AsyncMock(return_value=None)), patch(
            "asyncio.to_thread", new=AsyncMock(return_value=(RET_OK, capital_df))
        ):
            result = await handler.get_fund_flow("US.AAPL")
        assert result["status"] == "success"
        assert result["broker_queue"] is None
        assert result["order_book_level_1"] is None
        # main_fund_net_inflow = (100+200) - (50+30) = 220
        assert result["main_fund_net_inflow"] == 220

    @pytest.mark.asyncio
    async def test_get_fundamental_unsupported_returns_error(self):
        """不支持资产应返回错误"""
        handler, _, _ = _make_handler()
        result = await handler.get_fundamental("GC=F", is_unsupported_func=_unsupported)
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_get_fundamental_cache_hit(self):
        """缓存命中应直接返回"""
        handler, _, cache_mgr = _make_handler()
        cache_mgr.set_fundamental_cache("futu_fundamental_HK.00700", time.time(), {"status": "success", "cached": True})
        result = await handler.get_fundamental("HK.00700")
        assert result.get("cached") is True

    @pytest.mark.asyncio
    async def test_get_fundamental_dev_env_uses_mock(self):
        """dev 环境应使用 mock"""
        handler, conn_mgr, _ = _make_handler(connected=False)
        conn_mgr.status = "DISCONNECTED"
        conn_mgr.quote_ctx = None
        with patch.dict("os.environ", {"QUANT_ENV": "development"}):
            result = await handler.get_fundamental("HK.00700")
        assert result["status"] == "success"
        assert result["source"] == "mock"

    @pytest.mark.asyncio
    async def test_get_fundamental_no_ctx_returns_error(self):
        """非 dev 环境未连接应返回错误"""
        handler, conn_mgr, _ = _make_handler(connected=False)
        conn_mgr.status = "DISCONNECTED"
        with patch.dict("os.environ", {"QUANT_ENV": "production"}):
            result = await handler.get_fundamental("HK.00700")
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_get_fundamental_fetch_failure_returns_error(self):
        """获取失败应返回错误并缓存"""
        handler, _, cache_mgr = _make_handler()
        with patch("asyncio.to_thread", new=AsyncMock(return_value=(-1, "snapshot failed"))):
            result = await handler.get_fundamental("HK.00700")
        assert result["status"] == "error"
        cached = cache_mgr.get_fundamental_cache("futu_fundamental_HK.00700")
        assert cached is not None

    @pytest.mark.asyncio
    async def test_get_fundamental_success_filters_zero_fields(self):
        """成功时应过滤掉值为 0 的字段"""
        handler, _, _ = _make_handler()
        snapshot_df = pd.DataFrame(
            {
                "name": ["腾讯控股"],
                "pe_ratio": [15.5],
                "pb_rate": [0.0],  # 应被过滤
                "dividend_yield": [0.0],  # 应被过滤
                "market_val": [50000000000.0],
            }
        )
        with patch("asyncio.to_thread", new=AsyncMock(return_value=(RET_OK, snapshot_df))):
            result = await handler.get_fundamental("HK.00700")
        assert result["status"] == "success"
        data = result["data"]
        assert data["company_name"] == "腾讯控股"
        assert data["trailing_PE"] == 15.5
        assert data["market_cap"] == 50000000000.0
        assert "price_to_book" not in data
        assert "dividend_yield" not in data
