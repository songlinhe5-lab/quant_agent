"""
G7 交叉验证面板（get_analyst_vs_actual）单元测试。

覆盖 2026-08-30 S1 实战修复的三个缺陷：

1. res_cons.data 经 registry/router 链路后可能是【list 记录数组】（信封已解包），
   旧代码只认 dict 信封 → 拿到 list 时整个解析分支不进入，直接追加
   "分析师共识源不可用"，而数据其实已完整到手。
2. Futu F4-4 共识字段是 average/highest/lowest（不含 "price" 子串），
   通用模糊匹配命中不了 → target_price 恒 None。
3. 合并基本面不含现价 → 需 QUOTE 兜底。
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from backend.services.datasource import Result
from backend.services.datasource.business.facade import DataServiceFacade

# Futu F4-4 真实返回形态（GetResearchAnalystConsensusQuery.unpack 的 dict）
_CONSENSUS_ROW = {
    "highest": 400.0,
    "average": 346.78,
    "lowest": 245.0,
    "rating": "BUY",
    "total": 25.0,
    "update_time": 1788042626.0,
    "update_time_str": "2026-08-29",
    "buy": 60.0,
    "hold": 24.0,
    "sell": 16.0,
}


def _build_facade(cons_data, fund_data=None, quote_data=None) -> DataServiceFacade:
    """构造替身 facade：三个子任务全部打桩，不触网、不依赖 Redis/Futu。"""
    facade = DataServiceFacade()
    facade.get_analyst_consensus = AsyncMock(return_value=Result.make_success(cons_data, source="futu_consensus"))
    facade.get_fundamental_merged = AsyncMock(
        return_value=Result.make_success(
            fund_data if fund_data is not None else {"ticker": "AAPL", "futu": {"financials": []}},
            source="futu",
        )
    )
    facade.get_quote = AsyncMock(
        return_value=Result.make_success(
            quote_data if quote_data is not None else {"last_price": 319.7, "ticker": "US.AAPL"},
            source="futu",
        )
    )
    return facade


@pytest.mark.asyncio
async def test_list_payload_extracts_target_price():
    """回归核心：res_cons.data 为 list（信封已解包）时仍能提取目标价。"""
    facade = _build_facade([_CONSENSUS_ROW])

    res = await facade.get_analyst_vs_actual("AAPL")
    panel = res.data["panel"]

    assert panel["target_price"] == 346.78
    assert panel["notes"] == []


@pytest.mark.asyncio
async def test_dict_envelope_payload_extracts_target_price():
    """dict 信封形态（{"data": [...]}）同样生效，保持向后兼容。"""
    facade = _build_facade({"status": "success", "count": 1, "data": [_CONSENSUS_ROW]})

    panel = (await facade.get_analyst_vs_actual("AAPL")).data["panel"]

    assert panel["target_price"] == 346.78


@pytest.mark.asyncio
async def test_current_price_falls_back_to_quote():
    """合并基本面不含现价 → 由 QUOTE 兜底，并标注来源。"""
    facade = _build_facade(
        [_CONSENSUS_ROW],
        fund_data={"ticker": "AAPL", "futu": {"financials": []}, "fmp": {"profile": {}}},
        quote_data={"last_price": 319.7},
    )

    panel = (await facade.get_analyst_vs_actual("AAPL")).data["panel"]

    assert panel["current_price"] == 319.7
    assert panel["current_price_source"] == "quote"


@pytest.mark.asyncio
async def test_upside_and_verdict_derived():
    """目标价与现价齐备 → 派生上行空间与交叉验证结论。"""
    facade = _build_facade([_CONSENSUS_ROW], quote_data={"last_price": 200.0})

    panel = (await facade.get_analyst_vs_actual("AAPL")).data["panel"]

    assert panel["upside_pct"] == round((346.78 - 200.0) / 200.0 * 100, 2)
    assert panel["verdict"] == "sell_side_bullish"  # 上行 >15% → 卖方过度乐观


@pytest.mark.asyncio
async def test_consensus_unavailable_noted_not_fabricated():
    """共识源失败 → 字段留空 + note，严禁臆造价格（零幻觉红线）。"""
    facade = DataServiceFacade()
    from backend.services.datasource import ErrorInfo

    facade.get_analyst_consensus = AsyncMock(
        return_value=Result.make_error(ErrorInfo.normal("ALL_SOURCES_FAILED", "源不可用"), source="futu")
    )
    facade.get_fundamental_merged = AsyncMock(return_value=Result.make_success({"ticker": "AAPL"}, source="futu"))
    facade.get_quote = AsyncMock(return_value=Result.make_success({"last_price": 319.7}, source="futu"))

    panel = (await facade.get_analyst_vs_actual("AAPL")).data["panel"]

    assert panel["target_price"] is None
    assert panel["upside_pct"] is None
    assert panel["verdict"] is None
    assert "分析师共识源不可用" in panel["notes"]
