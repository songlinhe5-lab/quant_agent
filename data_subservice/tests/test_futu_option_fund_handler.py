"""
Futu OptionFundHandler 单元测试
覆盖: get_option_chain/get_fund_flow/get_fundamental
"""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest
from futu import RET_OK

from data_subservice.futu_src.cache_manager import CacheManager
from data_subservice.futu_src.option_fund_handler import OptionFundHandler


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
    async def test_get_option_chain_disconnected_returns_error_no_mock(self):
        """option_chain 禁止 mock 兜底：未 CONNECTED 时一律返回 error（零幻觉契约，dev 环境亦不例外）"""
        handler, conn_mgr, _ = _make_handler(connected=False)
        conn_mgr.status = "DISCONNECTED"
        conn_mgr.quote_ctx = None
        with patch.dict("os.environ", {"QUANT_ENV": "development"}):
            result = await handler.get_option_chain("HK.00700")
        assert result["status"] == "error"
        assert "未连接" in result["message"] or "数据源已死" in result["message"]

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
    async def test_get_option_chain_enriches_iv_from_snapshot(self):
        """get_option_chain 应通过 get_market_snapshot 补充 IV/Greeks（否则全 null）"""
        handler, conn_mgr, _ = _make_handler()
        chain_df = pd.DataFrame(
            {"code": ["OPT1", "OPT2"], "option_type": ["CALL", "PUT"], "strike_price": [350.0, 360.0]}
        )
        # 快照 DataFrame 含 option_implied_volatility / option_delta 等（chain_data 没有的列）
        snap_df = pd.DataFrame(
            {
                "code": ["OPT1", "OPT2"],
                "option_implied_volatility": [0.35, 0.42],
                "option_delta": [0.6, -0.4],
                "bid_price": [3.5, 4.2],
                "ask_price": [3.6, 4.3],
            }
        )

        async def fake_to_thread(fn, *args, **kwargs):
            if fn == conn_mgr.quote_ctx.get_option_chain:
                return (RET_OK, chain_df)
            if fn == conn_mgr.quote_ctx.get_market_snapshot:
                return (RET_OK, snap_df)
            return (RET_OK, pd.DataFrame())

        with patch("asyncio.to_thread", new=fake_to_thread):
            result = await handler.get_option_chain("HK.00700", expiration_date="2026-01-01")
        assert result["status"] == "success"
        # options 里应包含补充的 IV 字段（不再是 null）
        assert result["count"] == 2
        calls = result.get("calls", [])
        assert len(calls) == 1
        assert calls[0]["implied_volatility"] is not None
        assert calls[0]["implied_volatility"] == pytest.approx(35.0)  # 0.35 → 35%
        assert calls[0]["delta"] == pytest.approx(0.6)
        assert calls[0]["bid"] == pytest.approx(3.5)

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
    async def test_get_fund_flow_circuit_breaker_dev_returns_mock(self):
        """dev 环境熔断期内应返回 mock 数据"""
        handler, _, cache_mgr = _make_handler()
        cache_mgr.ff_circuit_breaker_until = time.time() + 100  # 仍在熔断期
        with patch.dict("os.environ", {"QUANT_ENV": "development"}):
            result = await handler.get_fund_flow("HK.00700")
        assert result["source"] == "mock"

    @pytest.mark.asyncio
    async def test_get_fund_flow_circuit_breaker_prod_returns_error(self):
        """生产环境熔断期内返回错误而非假数据 (零幻觉契约)"""
        handler, _, cache_mgr = _make_handler()
        cache_mgr.ff_circuit_breaker_until = time.time() + 100  # 仍在熔断期
        with patch.dict("os.environ", {"QUANT_ENV": "production"}):
            result = await handler.get_fund_flow("HK.00700")
        assert result["status"] == "error"
        assert "熔断冷却" in result["message"]

    @pytest.mark.asyncio
    async def test_get_fund_flow_frequency_limit_dev_triggers_circuit_breaker(self):
        """dev 环境频率限制错误应触发熔断并返回 mock"""
        handler, conn_mgr, cache_mgr = _make_handler()
        cache_mgr.ff_lock = None  # 确保走创建锁分支

        # 加速 sleep 防止真实等待
        with (
            patch("asyncio.sleep", new=AsyncMock(return_value=None)),
            patch(
                "asyncio.to_thread",
                new=AsyncMock(return_value=(-1, "频率太高，请稍后再试")),
            ),
            patch.dict("os.environ", {"QUANT_ENV": "development"}),
        ):
            result = await handler.get_fund_flow("HK.00700")
        assert result["source"] == "mock"
        # 熔断时间应被设置为 ~60s 后
        assert cache_mgr.ff_circuit_breaker_until > time.time()

    @pytest.mark.asyncio
    async def test_get_fund_flow_frequency_limit_prod_returns_error(self):
        """生产环境频率限制错误应触发熔断并返回错误而非假数据 (零幻觉契约)"""
        handler, conn_mgr, cache_mgr = _make_handler()
        cache_mgr.ff_lock = None

        with (
            patch("asyncio.sleep", new=AsyncMock(return_value=None)),
            patch(
                "asyncio.to_thread",
                new=AsyncMock(return_value=(-1, "频率太高，请稍后再试")),
            ),
            patch.dict("os.environ", {"QUANT_ENV": "production"}),
        ):
            result = await handler.get_fund_flow("HK.00700")
        assert result["status"] == "error"
        assert "熔断" in result["message"]
        # 熔断时间仍应被设置 (保护底层接口)
        assert cache_mgr.ff_circuit_breaker_until > time.time()
        cached = cache_mgr.get_fund_flow_cache("futu_fund_flow_HK.00700")
        assert cached is not None
        assert cached[1]["status"] == "error"

    @pytest.mark.asyncio
    async def test_get_fund_flow_fetch_failure_returns_error(self):
        """非限流错误应返回错误并缓存"""
        handler, _, cache_mgr = _make_handler()
        cache_mgr.ff_lock = None

        with (
            patch("asyncio.sleep", new=AsyncMock(return_value=None)),
            patch(
                "asyncio.to_thread",
                new=AsyncMock(return_value=(-1, "permission denied")),
            ),
        ):
            result = await handler.get_fund_flow("US.AAPL")  # 非 HK 不走 broker 分支
        assert result["status"] == "error"
        cached = cache_mgr.get_fund_flow_cache("futu_fund_flow_US.AAPL")
        assert cached is not None

    # ── F5: 十大买卖经纪商 (get_top_brokers) ──────────────────────────────

    @pytest.mark.asyncio
    async def test_get_top_brokers_hk_success(self):
        """HK 十大经纪商应返回买盘/卖盘两组并拍平 MultiIndex"""
        handler, conn_mgr, cache_mgr = _make_handler()
        # futu 历史类接口常返回 MultiIndex columns，需拍平（DIST-SEC-02 教训）
        df = pd.DataFrame(
            {
                ("broker_name", "HK.00700"): ["BrokerA", "BrokerB", "BrokerC"],
                ("buy_sell_type", "HK.00700"): ["BUY", "SELL", "BUY"],
                ("avg_price", "HK.00700"): [350.2, 349.8, 351.0],
                ("net_vol", "HK.00700"): [12000, -8000, 5000],
                ("total_vol", "HK.00700"): [15000, 9000, 6000],
                ("total_turnover", "HK.00700"): [5.2e6, 3.1e6, 2.1e6],
                ("is_real_time", "HK.00700"): [1, 1, 1],
            }
        )

        async def fake_to_thread(fn, *args, **kwargs):
            return (RET_OK, df)

        with patch("asyncio.to_thread", new=fake_to_thread):
            result = await handler.get_top_brokers("HK.00700")
        assert result["status"] == "success"
        # 拍平后 buy/sell 拆分正确
        assert len(result["buy_brokers"]) == 2
        assert len(result["sell_brokers"]) == 1
        assert result["buy_brokers"][0]["broker_name"] == "BrokerA"
        assert result["is_real_time"] is True
        # 缓存写入
        cached = cache_mgr.get_top_brokers_cache("futu_top_brokers_HK.00700_0")
        assert cached is not None

    @pytest.mark.asyncio
    async def test_get_top_brokers_us_fallback(self):
        """US 标的应走十大经纪商兜底（不拦截 unsupported）"""
        handler, conn_mgr, cache_mgr = _make_handler()
        df = pd.DataFrame(
            {
                ("broker_name", "US.AAPL"): ["BrokerX", "BrokerY"],
                ("buy_sell_type", "US.AAPL"): ["BUY", "SELL"],
                ("avg_price", "US.AAPL"): [180.5, 179.9],
                ("net_vol", "US.AAPL"): [3000, -2000],
                ("total_vol", "US.AAPL"): [3500, 2200],
                ("total_turnover", "US.AAPL"): [6.3e5, 4.0e5],
                ("is_real_time", "US.AAPL"): [1, 1],
            }
        )

        async def fake_to_thread(fn, *args, **kwargs):
            return (RET_OK, df)

        with patch("asyncio.to_thread", new=fake_to_thread):
            result = await handler.get_top_brokers("US.AAPL")
        assert result["status"] == "success"
        assert len(result["buy_brokers"]) == 1
        assert result["sell_brokers"][0]["broker_name"] == "BrokerY"

    @pytest.mark.asyncio
    async def test_get_top_brokers_empty_returns_error(self):
        """空 DataFrame 应返回错误（非空数据才成功）"""
        handler, conn_mgr, _ = _make_handler()

        async def fake_to_thread(fn, *args, **kwargs):
            return (RET_OK, pd.DataFrame())

        with patch("asyncio.to_thread", new=fake_to_thread):
            result = await handler.get_top_brokers("HK.00700")
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_get_top_brokers_disconnected_returns_error(self):
        """未连接应返回错误（不让前端误显示为空数据）"""
        handler, conn_mgr, _ = _make_handler(connected=False)
        conn_mgr.status = "DISCONNECTED"
        conn_mgr.quote_ctx = None
        result = await handler.get_top_brokers("HK.00700")
        assert result["status"] == "error"
        assert "未连接" in result["message"] or "重连中" in result["message"]

    # ── F6: 个股资金流向时间序列 (get_capital_flow) ──────────────────────

    @pytest.mark.asyncio
    async def test_get_capital_flow_intraday_success(self):
        """INTRADAY 资金流向应返回时间序列并拍平 MultiIndex"""
        handler, conn_mgr, cache_mgr = _make_handler()
        df = pd.DataFrame(
            {
                ("data_time_str", "HK.00700"): ["2026-08-21 09:30:00", "2026-08-21 09:31:00"],
                ("capital_in_flow", "HK.00700"): [1.2e6, 0.8e6],
                ("capital_out_flow", "HK.00700"): [0.9e6, 1.1e6],
            }
        )

        async def fake_to_thread(fn, *args, **kwargs):
            return (RET_OK, df)

        with patch("asyncio.to_thread", new=fake_to_thread):
            result = await handler.get_capital_flow("HK.00700")
        assert result["status"] == "success"
        assert result["period_type"] == "INTRADAY"
        assert result["count"] == 2
        assert result["flow"][0]["in_flow"] == pytest.approx(1.2e6)
        assert result["flow"][1]["out_flow"] == pytest.approx(1.1e6)
        cached = cache_mgr.get_capital_flow_cache("futu_capital_flow_HK.00700_INTRADAY")
        assert cached is not None

    @pytest.mark.asyncio
    async def test_get_capital_flow_empty_returns_error(self):
        """空 DataFrame 应返回错误"""
        handler, conn_mgr, _ = _make_handler()

        async def fake_to_thread(fn, *args, **kwargs):
            return (RET_OK, pd.DataFrame())

        with patch("asyncio.to_thread", new=fake_to_thread):
            result = await handler.get_capital_flow("HK.00700")
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_get_fund_flow_hk_success_with_broker_queue(self):
        """HK 标的成功获取应包含 broker_queue 与 order_book_level_1"""
        handler, conn_mgr, cache_mgr = _make_handler()
        cache_mgr.ff_lock = None

        capital_df = pd.DataFrame(
            {"capital_in_super": [100], "capital_in_big": [200], "capital_out_super": [50], "capital_out_big": [30]}
        )
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

        with patch("asyncio.sleep", new=AsyncMock(return_value=None)), patch("asyncio.to_thread", new=fake_to_thread):
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

        capital_df = pd.DataFrame(
            {"capital_in_super": [100], "capital_in_big": [200], "capital_out_super": [50], "capital_out_big": [30]}
        )

        with (
            patch("asyncio.sleep", new=AsyncMock(return_value=None)),
            patch("asyncio.to_thread", new=AsyncMock(return_value=(RET_OK, capital_df))),
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
