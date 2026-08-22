"""
P1 组合期权交易骨架单测
验证 trade_handler 的 place_combo_order / comboorder_tradinginfo_query：
  - 骨架可用（SIMULATE 沙箱推演）
  - 沙箱约束（AGENTS.md §6：默认 SIMULATE，REAL 需 REAL_TRADE_EXECUTE + force_real）
  - 组合腿解析 / 网关未连接 / SDK 失败降级
全程 mock conn_mgr 与 trd_ctx，不触碰真实 OpenD 交易网关。
"""

import pandas as pd
import pytest
from futu import RET_OK, TrdEnv

from data_subservice.futu_src.trade_handler import TradeHandler


class _FakeTradeCtx:
    """模拟 OpenSecTradeContext（只暴露骨架所需方法）"""

    def __init__(self, place_result=None, query_result=None):
        self.place_result = place_result or (RET_OK, pd.DataFrame([{"order_id": 10086}]))
        self.query_result = query_result or (RET_OK, pd.DataFrame([{"combo_id": 7}]))
        self.calls = []

    def place_combo_order(self, *args, **kwargs):
        self.calls.append(("place", kwargs))
        return self.place_result

    def comboorder_tradinginfo_query(self, *args, **kwargs):
        self.calls.append(("query", kwargs))
        return self.query_result


class _FakeConnMgr:
    def __init__(self, trade_ctx=None):
        self.trade_ctx = trade_ctx
        self.unlock_calls = 0

    def get_trade_context(self, market=None, trd_env=None):
        return self.trade_ctx

    async def unlock_trade_if_needed(self, ctx):
        self.unlock_calls += 1


LEGS = [
    {"code": "US.AAPL260824C205000", "trd_side": "BUY", "qty_ratio": 1},
    {"code": "US.AAPL260824P210000", "trd_side": "BUY", "qty_ratio": 1},
]


@pytest.mark.asyncio
async def test_place_combo_order_simulate_success():
    ctx = _FakeTradeCtx()
    handler = TradeHandler(_FakeConnMgr(trade_ctx=ctx))
    res = await handler.place_combo_order(LEGS, 100.0, 1, "US", force_real=False)
    assert res["status"] == "success"
    assert res["environment"] == "SIMULATE"  # 默认沙箱
    assert res["order_id"] == "10086"
    assert "SIMULATE" in res["message"]
    assert ctx.calls[0][0] == "place"
    # trd_env 必须是 SIMULATE
    assert ctx.calls[0][1]["trd_env"] == TrdEnv.SIMULATE


@pytest.mark.asyncio
async def test_place_combo_order_real_blocked_without_flag(monkeypatch):
    """无 REAL_TRADE_EXECUTE 标志时，即使 force_real=True 也回落 SIMULATE"""
    monkeypatch.delenv("REAL_TRADE_EXECUTE", raising=False)
    ctx = _FakeTradeCtx()
    handler = TradeHandler(_FakeConnMgr(trade_ctx=ctx))
    res = await handler.place_combo_order(LEGS, 100.0, 1, "US", force_real=True)
    assert res["status"] == "success"
    assert res["environment"] == "SIMULATE"  # 红线：标志缺失则回落沙箱
    assert ctx.calls[0][1]["trd_env"] == TrdEnv.SIMULATE


@pytest.mark.asyncio
async def test_place_combo_order_real_allowed_with_flag(monkeypatch):
    """REAL_TRADE_EXECUTE=1 + force_real=True 才允许 REAL"""
    monkeypatch.setenv("REAL_TRADE_EXECUTE", "1")
    ctx = _FakeTradeCtx()
    handler = TradeHandler(_FakeConnMgr(trade_ctx=ctx))
    res = await handler.place_combo_order(LEGS, 100.0, 1, "US", force_real=True)
    assert res["status"] == "success"
    assert res["environment"] == "REAL"
    assert ctx.calls[0][1]["trd_env"] == TrdEnv.REAL


@pytest.mark.asyncio
async def test_place_combo_order_invalid_legs():
    handler = TradeHandler(_FakeConnMgr(trade_ctx=_FakeTradeCtx()))
    res = await handler.place_combo_order([{"code": ""}], 100.0, 1, "US")
    assert res["status"] == "error"
    assert "非法组合腿" in res["message"]


@pytest.mark.asyncio
async def test_place_combo_order_empty_legs():
    handler = TradeHandler(_FakeConnMgr(trade_ctx=_FakeTradeCtx()))
    res = await handler.place_combo_order([], 100.0, 1, "US")
    assert res["status"] == "error"
    assert "combo_legs" in res["message"]


@pytest.mark.asyncio
async def test_place_combo_order_gateway_unavailable():
    handler = TradeHandler(_FakeConnMgr(trade_ctx=None))  # 网关未连接
    res = await handler.place_combo_order(LEGS, 100.0, 1, "US")
    assert res["status"] == "error"
    assert "交易网关" in res["message"]


@pytest.mark.asyncio
async def test_place_combo_order_sdk_fail():
    ctx = _FakeTradeCtx(place_result=(-1, "no permission"))
    handler = TradeHandler(_FakeConnMgr(trade_ctx=ctx))
    res = await handler.place_combo_order(LEGS, 100.0, 1, "US")
    assert res["status"] == "error"


@pytest.mark.asyncio
async def test_combo_tradinginfo_query_simulate_success():
    ctx = _FakeTradeCtx()
    handler = TradeHandler(_FakeConnMgr(trade_ctx=ctx))
    res = await handler.comboorder_tradinginfo_query(LEGS, 100.0, 1, "US")
    assert res["status"] == "success"
    assert res["environment"] == "SIMULATE"
    assert ctx.calls[0][0] == "query"
    assert ctx.calls[0][1]["trd_env"] == TrdEnv.SIMULATE


@pytest.mark.asyncio
async def test_combo_tradinginfo_query_sdk_fail():
    ctx = _FakeTradeCtx(query_result=(-1, "fail"))
    handler = TradeHandler(_FakeConnMgr(trade_ctx=ctx))
    res = await handler.comboorder_tradinginfo_query(LEGS, 100.0, 1, "US")
    assert res["status"] == "error"
