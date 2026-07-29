"""
BE-03 FutuAdapter 单元测试

覆盖：
- 代码/周期归一化
- 真实 _connect (注入 ctx 时可用；无 ctx 且 OpenD 不可用时降级返回 False，绝不伪造)
- quote / history / fund_flow / option_chain 真实解析 (注入 fake ctx)
- 零幻觉：未连接时 fetch 返回 degraded / _fetch_option_chain 返回 error，绝不返回 mock 数据
- subscribe / unsubscribe 真实调用 futu 订阅 + 推送回调路由
- 限流退避

原则：全程注入 fake ctx，绝不触发真实 OpenD 连接。
"""

from unittest.mock import MagicMock

import pandas as pd
import pytest
from futu import RET_OK

from backend.adapters.futu.futu_adapter import FutuAdapter


# ─── 构造 fake ctx 辅助 ──────────────────────────────────────────
def _make_fake_ctx(is_connected: bool = True) -> MagicMock:
    ctx = MagicMock()
    ctx.is_connected = is_connected
    ctx.subscribe.return_value = (RET_OK, None)
    ctx.unsubscribe.return_value = (RET_OK, None)
    ctx.set_handler.return_value = None
    ctx.close.return_value = None
    return ctx


def _adapter(ctx: MagicMock) -> FutuAdapter:
    a = FutuAdapter(ctx=ctx)
    return a


def _connected_adapter(ctx: MagicMock) -> FutuAdapter:
    """构造已连接（注入 ctx 且 is_connected=True）的适配器。"""
    a = FutuAdapter(ctx=ctx)
    a._connect()
    return a


# ─── 归一化 ──────────────────────────────────────────────────────
def test_normalize_code_reverses_suffix():
    a = FutuAdapter(ctx=_make_fake_ctx())
    assert a._normalize_code("00700.HK") == "HK.00700"
    assert a._normalize_code("HK.00700") == "HK.00700"
    assert a._normalize_code("AAPL.US") == "US.AAPL"
    assert a._normalize_code("US.AAPL") == "US.AAPL"
    assert a._normalize_code("600000.SH") == "SH.600000"


def test_map_interval_to_ktype():
    a = FutuAdapter(ctx=_make_fake_ctx())
    assert a._map_interval("1d") == "K_DAY"
    assert a._map_interval("5m") == "K_5M"
    assert a._map_interval("60m") == "K_60M"
    assert a._map_interval("week") == "K_WEEK"
    assert a._map_interval("unknown") == "K_DAY"  # 默认日线


# ─── 连接 ───────────────────────────────────────────────────────
def test_connect_with_injected_ctx():
    a = _adapter(_make_fake_ctx(is_connected=True))
    assert a._connect() is True
    assert a._connected is True


def test_connect_without_ctx_and_no_opend_returns_false(monkeypatch):
    # 无 ctx：尝试创建真实 OpenQuoteContext；OpenD 不可用时连接失败，返回 False（绝不伪造）
    dying = MagicMock(side_effect=ConnectionError("OpenD not running"))
    monkeypatch.setattr("backend.adapters.futu.futu_adapter.OpenQuoteContext", dying)
    a = FutuAdapter(host="127.0.0.1", port=9)  # 不会真正连，monkeypatch 拦截
    assert a._connect() is False
    assert a._connected is False


def test_health_check_unhealthy_when_not_connected():
    a = _adapter(_make_fake_ctx(is_connected=False))
    # _connect 会因 is_connected=False 而失败
    result = a.health_check()
    assert result["healthy"] is False


# ─── quote ───────────────────────────────────────────────────────
def test_fetch_quote_success_parses_real_df():
    ctx = _make_fake_ctx()
    df = pd.DataFrame(
        [
            {
                "code": "HK.00700",
                "last_price": 512.5,
                "open_price": 505.0,
                "high_price": 520.0,
                "low_price": 500.0,
                "prev_close_price": 500.0,
                "volume": 12345678,
                "turnover": 6.3e9,
            }
        ]
    )
    ctx.get_stock_quote.return_value = (RET_OK, df)
    a = _connected_adapter(ctx)

    res = a.fetch("quote", {"ticker": "00700.HK"})
    assert res.status == "success"
    q = res.data
    assert q["ticker"] == "HK.00700"
    assert q["price"] == pytest.approx(512.5)
    assert q["prev_close"] == pytest.approx(500.0)
    assert q["change"] == pytest.approx(12.5)
    assert q["change_pct"] == pytest.approx(2.5)
    # 查询前会自动订阅 QUOTE
    ctx.subscribe.assert_called()


def test_fetch_quote_degraded_without_connection():
    # 无 ctx 且未连接 → fetch 返回 degraded，绝不返回编造数据
    a = FutuAdapter(ctx=None)
    a._connected = False
    res = a.fetch("quote", {"ticker": "HK.00700"})
    assert res.status == "degraded"


def test_fetch_quote_missing_ticker():
    # 必须在已连接状态下校验，missing ticker 属请求参数错误(error)而非数据源降级(degraded)
    a = _connected_adapter(_make_fake_ctx())
    res = a.fetch("quote", {})
    assert res.status == "error"


# ─── history ────────────────────────────────────────────────────
def test_fetch_history_success_and_interval_mapping():
    ctx = _make_fake_ctx()
    df = pd.DataFrame(
        [
            {
                "code": "HK.00700",
                "time_key": "2026-07-27 00:00:00",
                "open": 500.0,
                "high": 520.0,
                "low": 499.0,
                "close": 512.5,
                "volume": 1000,
                "turnover": 5.0e8,
            },
            {
                "code": "HK.00700",
                "time_key": "2026-07-28 00:00:00",
                "open": 512.5,
                "high": 530.0,
                "low": 510.0,
                "close": 525.0,
                "volume": 1100,
                "turnover": 5.5e8,
            },
        ]
    )
    ctx.get_cur_kline.return_value = (RET_OK, df)
    a = _connected_adapter(ctx)

    res = a.fetch("history", {"ticker": "HK.00700", "interval": "5m", "num": 50})
    assert res.status == "success"
    klines = res.data
    assert len(klines) == 2
    assert klines[0]["close"] == pytest.approx(512.5)
    # interval "5m" 应映射为 K_5M
    call = ctx.get_cur_kline.call_args
    assert call.args[0] == "HK.00700"
    assert call.args[1] == 50
    assert call.kwargs["ktype"] == "K_5M"


def test_fetch_history_degraded_without_connection():
    a = FutuAdapter(ctx=None)
    a._connected = False
    res = a.fetch("history", {"ticker": "HK.00700"})
    assert res.status == "degraded"


# ─── fund_flow ───────────────────────────────────────────────────
def test_fetch_fund_flow_success_aggregates_main_in_flow():
    ctx = _make_fake_ctx()
    df = pd.DataFrame(
        [
            {
                "last_valid_time": "2026-07-27 10:00",
                "in_flow": 1.0,
                "super_in_flow": 0.2,
                "big_in_flow": 0.3,
                "mid_in_flow": 0.2,
                "sml_in_flow": 0.3,
                "main_in_flow": 0.5,
            },
            {
                "last_valid_time": "2026-07-27 10:01",
                "in_flow": 2.0,
                "super_in_flow": 0.4,
                "big_in_flow": 0.6,
                "mid_in_flow": 0.4,
                "sml_in_flow": 0.6,
                "main_in_flow": 1.0,
            },
        ]
    )
    ctx.get_capital_flow.return_value = (RET_OK, df)
    a = _connected_adapter(ctx)

    res = a.fetch("fund_flow", {"ticker": "HK.00700"})
    assert res.status == "success"
    f = res.data
    assert f["ticker"] == "HK.00700"
    assert f["main_in_flow"] == pytest.approx(1.5)  # 0.5 + 1.0
    assert f["in_flow"] == pytest.approx(3.0)
    assert f["super_in"] == pytest.approx(0.4)  # 末行
    assert f["big_in"] == pytest.approx(0.6)


def test_fetch_fund_flow_degraded_without_connection():
    a = FutuAdapter(ctx=None)
    a._connected = False
    res = a.fetch("fund_flow", {"ticker": "HK.00700"})
    assert res.status == "degraded"


# ─── option_chain (零幻觉) ────────────────────────────────────────
def test_fetch_option_chain_real():
    ctx = _make_fake_ctx()
    date_df = pd.DataFrame([{"strike_time": "2026-12-20 00:00:00"}])
    chain_df = pd.DataFrame(
        [
            {
                "strike_price": 500.0,
                "option_type": "CALL",
                "implied_volatility": 0.25,
                "option_code": "HK.00700C500",
                "last_price": 12.0,
                "volume": 100,
                "open_interest": 2000,
            },
            {
                "strike_price": 520.0,
                "option_type": "PUT",
                "implied_volatility": 0.30,
                "option_code": "HK.00700P520",
                "last_price": 8.0,
                "volume": 50,
                "open_interest": 1500,
            },
        ]
    )
    ctx.get_option_expiration_date.return_value = (RET_OK, date_df)
    ctx.get_option_chain.return_value = (RET_OK, chain_df)
    a = _connected_adapter(ctx)

    res = a.fetch("option_chain", {"underlying_ticker": "HK.00700"})
    assert res.status == "success"
    opts = res.data["options"]
    assert len(opts) == 2
    assert opts[0]["option_type"] == "call"
    assert opts[1]["strike_price"] == pytest.approx(520.0)


def test_fetch_option_chain_not_connected_returns_error_no_mock():
    # 未连接真实数据源 → 返回 error（明确告警），绝不 mock 兜底
    ctx = _make_fake_ctx(is_connected=False)
    a = _adapter(ctx)
    a._connected = True  # 绕过外部 is_available，直接验证内部零幻觉分支
    result = a._fetch_option_chain({"underlying_ticker": "HK.00700"})
    assert result["success"] is False
    assert "数据源已死" in result["message"]


# ─── subscribe / unsubscribe ─────────────────────────────────────
def test_subscribe_success_and_push_routing():
    ctx = _make_fake_ctx()
    a = _adapter(ctx)

    received = []
    sub_id = a.subscribe(
        "subscribe_quote",
        {"tickers": ["HK.00700", "US.AAPL"], "sub_type": "QUOTE"},
        callback=received.append,
    )
    assert sub_id.startswith("sub_")
    ctx.subscribe.assert_called_once()
    # 回调应已注册；模拟一次推送分发，回调应被调用
    import pandas as pd

    push_df = pd.DataFrame([{"code": "HK.00700", "last_price": 512.0}])
    a._router.dispatch("QUOTE", push_df)
    assert len(received) == 1
    assert received[0]["ticker"] == "HK.00700"
    assert received[0]["sub_type"] == "QUOTE"


def test_subscribe_requires_connection(monkeypatch):
    a = FutuAdapter(ctx=None)
    a._connected = False
    # 强制 _connect 失败（零幻觉：未连接时订阅必须抛 RuntimeError，不伪造订阅）
    monkeypatch.setattr(a, "_connect", lambda: False)
    with pytest.raises(RuntimeError):
        a.subscribe("subscribe_quote", {"tickers": ["HK.00700"]}, callback=lambda m: None)


def test_subscribe_rejects_bad_action():
    a = _adapter(_make_fake_ctx())
    with pytest.raises(ValueError):
        a.subscribe("subscribe_ticks", {"tickers": ["HK.00700"]}, callback=lambda m: None)


def test_unsubscribe_calls_futu_and_returns_true():
    ctx = _make_fake_ctx()
    a = _adapter(ctx)
    sub_id = a.subscribe(
        "subscribe_quote",
        {"tickers": ["HK.00700"], "sub_type": "QUOTE"},
        callback=lambda m: None,
    )
    assert a.unsubscribe(sub_id) is True
    ctx.unsubscribe.assert_called_once()
    # 再次取消应返回 False（已不存在）
    assert a.unsubscribe(sub_id) is False


# ─── 限流退避 ────────────────────────────────────────────────────
def test_rate_limit_triggers_backoff(monkeypatch):
    a = _adapter(_make_fake_ctx())
    monkeypatch.setattr(FutuAdapter, "RATE_LIMIT_REQUESTS_PER_MINUTE", 1)
    a._record_request()
    assert a._is_rate_limited is True
    assert a.is_available is False


def test_fetch_rate_limited_then_degraded():
    ctx = _make_fake_ctx()
    import pandas as pd

    ctx.get_stock_quote.return_value = (
        RET_OK,
        pd.DataFrame(
            [
                {
                    "code": "HK.00700",
                    "last_price": 1.0,
                    "open_price": 1.0,
                    "high_price": 1.0,
                    "low_price": 1.0,
                    "prev_close_price": 1.0,
                    "volume": 1,
                    "turnover": 1.0,
                }
            ]
        ),
    )
    a = _adapter(ctx)
    # 连续请求触发限流（默认每分钟 60 次）
    for _ in range(61):
        a.fetch("quote", {"ticker": "HK.00700"})
    res = a.fetch("quote", {"ticker": "HK.00700"})
    assert res.status in ("rate_limited", "degraded")
