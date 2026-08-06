"""
OmsExecutionAdapter 真实下单管道 + LiveContext.history 单测
覆盖：模拟盘跳过券商、实盘桥接 Futu、交易市场对映射、撤单、K 线接入 KlineCacheEngine
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
from futu import TrdMarket, TrdSide

from backend.engine.contracts import OrderIntent
from backend.engine.drivers.live import LiveContext
from backend.engine.gateway import OmsExecutionAdapter


def _intent(
    symbol="US.AAPL",
    side="BUY",
    qty=100,
    order_type="MARKET",
    limit_price=None,
):
    return OrderIntent(
        symbol=symbol,
        side=side,
        qty=qty,
        order_type=order_type,
        limit_price=limit_price,
    )


def test_submit_simulated_skips_futu():
    """模拟盘：OMS 落库，但不真正发往券商 (DataSourceRouter.fetch_futu 不被调用)。"""
    oms = AsyncMock()
    futu = AsyncMock()
    db = MagicMock()
    adapter = OmsExecutionAdapter(oms_service=oms, futu_service=futu, db=db, is_simulated=True)

    with patch("backend.services.datasource.router.DataSourceRouter.fetch_futu") as mock_fetch:
        order_id = adapter.submit(_intent(), "client-1")

        assert order_id.startswith("oms-")
        oms.create_order.assert_awaited_once()
        _, kwargs = oms.create_order.call_args
        assert kwargs["symbol"] == "US.AAPL"
        assert kwargs["side"] == "BUY"
        assert kwargs["is_simulated"] is True
        assert kwargs["db"] is db
        mock_fetch.assert_not_awaited()
    # 状态回写
    assert adapter._orders[order_id].status.value == "SUBMITTED"


def test_submit_live_calls_futu():
    """实盘：OMS 落库 + 经 DataSourceRouter.fetch_futu 实盘下单，marketplace 映射正确。"""
    oms = AsyncMock()
    futu = AsyncMock()
    db = MagicMock()
    adapter = OmsExecutionAdapter(oms_service=oms, futu_service=futu, db=db, is_simulated=False)
    intent = _intent(symbol="US.TSLA", side="SELL", order_type="LIMIT", limit_price=250.5)

    with patch("backend.services.datasource.router.DataSourceRouter.fetch_futu") as mock_fetch:
        adapter.submit(intent, "client-2")

        mock_fetch.assert_awaited_once()
        _, kwargs = mock_fetch.call_args
        assert kwargs["ticker"] == "US.TSLA"
        # futu-api 的 TrdSide 为字符串枚举，直接比较值
        assert kwargs["trd_side"] == TrdSide.SELL
        assert kwargs["market"] == TrdMarket.US
        assert kwargs["price"] == 250.5
        assert kwargs["qty"] == 100


def test_submit_hk_market_mapping():
    """港股代码应路由到 TrdMarket.HK (经 DataSourceRouter.fetch_futu)。"""
    futu = AsyncMock()
    adapter = OmsExecutionAdapter(
        oms_service=AsyncMock(),
        futu_service=futu,
        db=MagicMock(),
        is_simulated=False,
    )
    with patch("backend.services.datasource.router.DataSourceRouter.fetch_futu") as mock_fetch:
        adapter.submit(_intent(symbol="HK.00700", side="BUY"), "client-3")
        _, kwargs = mock_fetch.call_args
        assert kwargs["market"] == TrdMarket.HK


def test_infer_trd_market():
    """交易市场对映射（含默认分支）。"""
    assert OmsExecutionAdapter._infer_trd_market("HK.00700") == TrdMarket.HK
    assert OmsExecutionAdapter._infer_trd_market("SH.600519") == TrdMarket.CN
    assert OmsExecutionAdapter._infer_trd_market("SZ.000001") == TrdMarket.CN
    assert OmsExecutionAdapter._infer_trd_market("US.AAPL") == TrdMarket.US
    assert OmsExecutionAdapter._infer_trd_market("BTC-USD") == TrdMarket.US


def test_cancel():
    """撤单：存在返回 True，不存在返回 False。"""
    adapter = OmsExecutionAdapter(oms_service=AsyncMock(), futu_service=AsyncMock(), db=MagicMock(), is_simulated=True)
    order_id = adapter.submit(_intent(), "client-x")
    assert adapter.cancel(order_id) is True
    assert adapter._orders[order_id].status.value == "CANCELLED"
    assert adapter.cancel("nonexistent") is False


def test_live_context_history_success(monkeypatch):
    """history 接入 KlineCacheEngine，返回真实 K 线。"""
    fake_engine = MagicMock()

    async def _fake_get_kline(symbol, period, days, **kw):
        return pd.DataFrame({"close": [1.0, 2.0, 3.0]})

    fake_engine.get_kline = _fake_get_kline
    monkeypatch.setattr(
        "backend.services.datalake.kline_cache.get_kline_cache_engine",
        lambda: fake_engine,
    )

    ctx = LiveContext(
        mode="paper",
        run_id="r1",
        clock=MagicMock(),
        gateway=MagicMock(),
        symbol="US.AAPL",
    )
    df = ctx.history("US.AAPL", 10, "K_DAY")

    assert not df.empty
    assert list(df["close"]) == [1.0, 2.0, 3.0]


def test_live_context_history_failure_returns_empty(monkeypatch):
    """K线引擎异常时回退空 DataFrame，不抛异常。"""
    fake_engine = MagicMock()

    async def _boom(*args, **kwargs):
        raise RuntimeError("redis down")

    fake_engine.get_kline = _boom
    monkeypatch.setattr(
        "backend.services.datalake.kline_cache.get_kline_cache_engine",
        lambda: fake_engine,
    )

    ctx = LiveContext(
        mode="paper",
        run_id="r2",
        clock=MagicMock(),
        gateway=MagicMock(),
        symbol="US.AAPL",
    )
    df = ctx.history("US.AAPL", 10)
    assert df.empty
