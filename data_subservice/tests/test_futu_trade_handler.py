"""
TradeHandler 单元测试
覆盖: place_order / modify_order / query_order / emergency_liquidation / get_account_info
"""

import pandas as pd
import pytest
from futu import (
    RET_ERROR,
    RET_OK,
    ModifyOrderOp,
    OrderType,
    TrdEnv,
    TrdMarket,
    TrdSide,
)

from data_subservice.futu_src.trade_handler import TradeHandler


class _FakeConnMgr:
    """最小化 connection_manager mock。

    - status: CONNECTED / DISCONNECTED 控制 emergency_liquidation / get_account_info 行为
    - trade_ctx: 由测试注入的 MagicMock，其同步方法经 asyncio.to_thread 直接返回
    """

    def __init__(self, status="CONNECTED", trade_ctx=None):
        self.status = status
        self._trade_ctx = trade_ctx or MagicMockStub()

    def get_trade_context(self, market=None, trd_env=None):
        return self._trade_ctx

    async def unlock_trade_if_needed(self, trd_ctx):
        # 测试中默认视为无需解锁 (已解锁)
        return True


class MagicMockStub:
    """占位，避免循环 import 问题。实际由测试通过 monkeypatch 注入 MagicMock。"""

    pass


def _make_conn_mgr(status="CONNECTED"):
    return _FakeConnMgr(status=status)


def _order_df(
    order_id="12345", order_status="SUBMITTED", code="HK.00700", dealt_avg_price=0.0, trd_env=TrdEnv.SIMULATE
):
    return pd.DataFrame(
        [
            {
                "order_id": order_id,
                "order_status": order_status,
                "code": code,
                "dealt_avg_price": dealt_avg_price,
                "trd_env": trd_env,
            }
        ]
    )


def _position_df(code="HK.00700", qty=1000.0, position_side="LONG", trd_env=TrdEnv.SIMULATE):
    return pd.DataFrame([{"code": code, "qty": qty, "position_side": position_side, "trd_env": trd_env}])


def _accinfo_df():
    return pd.DataFrame(
        [
            {
                "total_assets": 1000000.0,
                "cash": 250000.0,
                "power": 250000.0,
                "market_val": 750000.0,
                "currency": "HKD",
            }
        ]
    )


# ── place_order ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_place_order_success():
    trade_ctx = MagicMockStub()
    trade_ctx.place_order = lambda **kw: (RET_OK, _order_df())
    conn = _make_conn_mgr()
    conn._trade_ctx = trade_ctx

    handler = TradeHandler(conn)
    res = await handler.place_order(
        ticker="HK.00700",
        qty=1000,
        price=300.0,
        trd_side=TrdSide.BUY,
        market=TrdMarket.HK,
    )
    assert res["status"] == "success"
    assert res["order_id"] == "12345"
    assert "委托已提交" in res["message"]


@pytest.mark.asyncio
async def test_place_order_market_when_price_zero():
    captured = {}

    def fake_place(**kw):
        captured.update(kw)
        return (RET_OK, _order_df())

    trade_ctx = MagicMockStub()
    trade_ctx.place_order = fake_place
    conn = _make_conn_mgr()
    conn._trade_ctx = trade_ctx

    handler = TradeHandler(conn)
    res = await handler.place_order(
        ticker="HK.00700",
        qty=100,
        price=0.0,
        trd_side=TrdSide.SELL,
        market=TrdMarket.HK,
    )
    # 市价单 price 回退为 1.0，order_type 应为 MARKET
    assert captured["price"] == 1.0
    assert captured["order_type"] == OrderType.MARKET
    assert res["status"] == "success"


@pytest.mark.asyncio
async def test_place_order_failure():
    trade_ctx = MagicMockStub()
    trade_ctx.place_order = lambda **kw: (RET_ERROR, "some error")
    conn = _make_conn_mgr()
    conn._trade_ctx = trade_ctx

    handler = TradeHandler(conn)
    res = await handler.place_order(
        ticker="HK.00700",
        qty=100,
        price=300.0,
        trd_side=TrdSide.BUY,
        market=TrdMarket.HK,
    )
    assert res["status"] == "error"
    assert "下单失败" in res["message"]


# ── modify_order ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_modify_order_cancel_success():
    trade_ctx = MagicMockStub()
    trade_ctx.modify_order = lambda *a, **kw: (RET_OK, None)
    conn = _make_conn_mgr()
    conn._trade_ctx = trade_ctx

    handler = TradeHandler(conn)
    res = await handler.modify_order(order_id="999", op=ModifyOrderOp.CANCEL, market=TrdMarket.HK)
    assert res["status"] == "success"
    assert "999" in res["message"]


@pytest.mark.asyncio
async def test_modify_order_failure():
    trade_ctx = MagicMockStub()
    trade_ctx.modify_order = lambda *a, **kw: (RET_ERROR, "fail")
    conn = _make_conn_mgr()
    conn._trade_ctx = trade_ctx

    handler = TradeHandler(conn)
    res = await handler.modify_order(order_id="999", op=ModifyOrderOp.CANCEL, market=TrdMarket.HK)
    assert res["status"] == "error"


# ── query_order ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_query_order_filled_notifies():
    trade_ctx = MagicMockStub()
    trade_ctx.order_list_query = lambda **kw: (
        RET_OK,
        _order_df(order_status="FILLED", dealt_avg_price=305.5),
    )
    conn = _make_conn_mgr()
    conn._trade_ctx = trade_ctx

    handler = TradeHandler(conn)
    res = await handler.query_order(order_id="12345", market=TrdMarket.HK)
    assert res["status"] == "success"
    assert res["order_status"] == "FILLED"
    assert res["dealt_avg_price"] == 305.5


@pytest.mark.asyncio
async def test_query_order_not_found():
    trade_ctx = MagicMockStub()
    trade_ctx.order_list_query = lambda **kw: (RET_ERROR, "not found")
    conn = _make_conn_mgr()
    conn._trade_ctx = trade_ctx

    handler = TradeHandler(conn)
    res = await handler.query_order(order_id="x", market=TrdMarket.HK)
    assert res["status"] == "error"
    assert "未找到" in res["message"]


@pytest.mark.asyncio
async def test_query_order_empty_df():
    trade_ctx = MagicMockStub()
    trade_ctx.order_list_query = lambda **kw: (RET_OK, pd.DataFrame())
    conn = _make_conn_mgr()
    conn._trade_ctx = trade_ctx

    handler = TradeHandler(conn)
    res = await handler.query_order(order_id="x", market=TrdMarket.HK)
    assert res["status"] == "error"


# ── emergency_liquidation (Kill Switch) ───────────────────────────────


@pytest.mark.asyncio
async def test_emergency_liquidation_disconnected():
    conn = _make_conn_mgr(status="DISCONNECTED")
    handler = TradeHandler(conn)
    res = await handler.emergency_liquidation(market="HK")
    assert res["status"] == "error"
    assert res["ok"] is False
    assert res["reason"] == "futu_opend_not_connected"


@pytest.mark.asyncio
async def test_emergency_liquidation_success():
    class _Ctx:
        def order_list_query(self, **kw):
            return (RET_OK, _order_df(order_id="o1"))

        def modify_order(self, *a, **kw):
            return (RET_OK, None)

        def position_list_query(self, **kw):
            return (RET_OK, _position_df(code="HK.00700", qty=500.0, position_side="LONG"))

        def place_order(self, **kw):
            return (RET_OK, _order_df())

    conn = _make_conn_mgr()
    conn._trade_ctx = _Ctx()
    handler = TradeHandler(conn)

    res = await handler.emergency_liquidation(market="HK")
    assert res["status"] == "success"
    assert res["ok"] is True
    assert res["cancelled"] == 1
    assert res["closed"] == 1


@pytest.mark.asyncio
async def test_emergency_liquidation_market_map():
    calls = []

    class _Ctx:
        def order_list_query(self, **kw):
            calls.append(("order", kw))
            return (RET_OK, pd.DataFrame())

        def modify_order(self, *a, **kw):
            return (RET_OK, None)

        def position_list_query(self, **kw):
            calls.append(("pos", kw))
            return (RET_OK, pd.DataFrame())

        def place_order(self, **kw):
            return (RET_OK, _order_df())

    for market, expected in [
        ("US", TrdMarket.US),
        ("CN", TrdMarket.CN),
        ("HK_CCASS", TrdMarket.HKCC),
        ("BAD", TrdMarket.HK),
    ]:
        conn = _make_conn_mgr()
        conn._trade_ctx = _Ctx()
        handler = TradeHandler(conn)
        res = await handler.emergency_liquidation(market=market)
        assert res["status"] == "success"
        # 撤单查询使用模拟盘环境
        assert calls[0][1].get("trd_env") == TrdEnv.SIMULATE
        calls.clear()


# ── get_account_info ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_account_info_disconnected_non_dev(monkeypatch):
    monkeypatch.delenv("QUANT_ENV", raising=False)
    conn = _make_conn_mgr(status="DISCONNECTED")
    handler = TradeHandler(conn)
    res = await handler.get_account_info(market="HK")
    assert res["status"] == "error"
    assert "未连接" in res["message"]


@pytest.mark.asyncio
async def test_get_account_info_disconnected_dev_uses_mock(monkeypatch):
    monkeypatch.setenv("QUANT_ENV", "development")
    conn = _make_conn_mgr(status="DISCONNECTED")
    handler = TradeHandler(conn)
    res = await handler.get_account_info(market="HK")
    assert res["status"] == "success"
    assert res["total_assets"] == 1000000.0
    assert res["positions"]


@pytest.mark.asyncio
async def test_get_account_info_real_env_from_variable(monkeypatch):
    monkeypatch.setenv("FUTU_TRD_ENV", "REAL")
    monkeypatch.delenv("QUANT_ENV", raising=False)
    conn = _make_conn_mgr()
    conn._trade_ctx = MagicMockStub()

    # REAL 环境下未配置解锁密码 → unlock 返回 False → locked=True (DIST-23 隔离)
    async def _unlock_false(trd_ctx):
        return False

    conn.unlock_trade_if_needed = _unlock_false
    handler = TradeHandler(conn)

    res = await handler.get_account_info(market="US")
    assert res["status"] == "error"
    assert res["locked"] is True


@pytest.mark.asyncio
async def test_get_account_info_success_simulation(monkeypatch):
    monkeypatch.delenv("QUANT_ENV", raising=False)
    monkeypatch.delenv("FUTU_TRD_ENV", raising=False)

    class _Ctx:
        def accinfo_query(self, **kw):
            return (RET_OK, _accinfo_df())

        def position_list_query(self, **kw):
            return (RET_OK, _position_df())

    conn = _make_conn_mgr()
    conn._trade_ctx = _Ctx()
    handler = TradeHandler(conn)

    res = await handler.get_account_info(market="HK")
    assert res["status"] == "success"
    assert res["environment"] == "SIMULATE"
    assert res["total_assets"] == 1000000.0
    assert res["currency"] == "HKD"
    assert len(res["positions"]) == 1
    assert res["positions"][0]["code"] == "HK.00700"


@pytest.mark.asyncio
async def test_get_account_info_accinfo_error(monkeypatch):
    monkeypatch.delenv("QUANT_ENV", raising=False)
    monkeypatch.delenv("FUTU_TRD_ENV", raising=False)

    class _Ctx:
        def accinfo_query(self, **kw):
            return (RET_ERROR, "fail")

        def position_list_query(self, **kw):
            return (RET_OK, _position_df())

    conn = _make_conn_mgr()
    conn._trade_ctx = _Ctx()
    handler = TradeHandler(conn)

    res = await handler.get_account_info(market="HK")
    assert res["status"] == "error"
    assert "获取失败" in res["message"]


@pytest.mark.asyncio
async def test_get_account_info_empty_df(monkeypatch):
    monkeypatch.delenv("QUANT_ENV", raising=False)
    monkeypatch.delenv("FUTU_TRD_ENV", raising=False)

    class _Ctx:
        def accinfo_query(self, **kw):
            return (RET_OK, pd.DataFrame())

        def position_list_query(self, **kw):
            return (RET_OK, pd.DataFrame())

    conn = _make_conn_mgr()
    conn._trade_ctx = _Ctx()
    handler = TradeHandler(conn)

    res = await handler.get_account_info(market="HK")
    assert res["status"] == "error"
    assert "账户数据为空" in res["message"]
