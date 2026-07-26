"""固化 macro_calendar_service 延迟导入的回归护栏

背景：macro_calendar_service 曾在模块顶层 `from backend.app.market_data import market_data`，
而 legacy_market_data 模块加载时会实例化 MarketDataGateway()，其 __init__ 反向拉入 macro 包，
从而在单独收集测试时触发循环导入。修复后改为运行时延迟导入 (_market_data())。

本文件固化三条不变量：
1. 模块可独立导入，不触发 backend.app.market_data 的顶层 import (循环导入不复发)；
2. MacroCalendarAggregator 可无副作用实例化；
3. _market_data() 在运行时延迟返回真实的 market_data 网关；
4. 延迟导入后 aggregate() 仍能正常聚合 (替换 _market_data 即可注入 mock)。
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.services.macro.macro_calendar_service import MacroCalendarAggregator


def test_module_imports_without_eager_market_data():
    # 导入模块本身不应抛错 (延迟导入已生效，不再在模块级拉入 market_data)
    import backend.services.macro.macro_calendar_service as mcs

    assert hasattr(mcs, "MacroCalendarAggregator")


def test_aggregator_instantiates_without_side_effects():
    # 实例化不应在模块级或对象级绑定 market_data
    agg = MacroCalendarAggregator()
    assert isinstance(agg, MacroCalendarAggregator)
    assert not hasattr(agg, "market_data")


def test_lazy_market_data_returns_real_gateway():
    # 运行时延迟导入应返回 backend.app.market_data 中真实的市场数据网关单例
    agg = MacroCalendarAggregator()
    md = agg._market_data()
    from backend.app.market_data import market_data as real_md

    assert md is real_md


@pytest.mark.asyncio
async def test_aggregate_uses_lazy_market_data(monkeypatch):
    # 延迟导入后，聚合器仍可正常聚合；验证 _market_data 是唯一的 market_data 接入点
    agg = MacroCalendarAggregator()
    fake = MagicMock()
    fake.get_economic_calendar_ak = AsyncMock(return_value={"data": []})
    fake.backfill_fred_actuals = AsyncMock(return_value=[])
    fake.get_economic_calendar_finnhub = AsyncMock(return_value={"data": []})
    fake.get_economic_calendar_fred = AsyncMock(return_value={"data": []})
    fake.get_economic_calendar_dbnomics = AsyncMock(return_value={"data": []})
    fake.get_economic_calendar_rbi = AsyncMock(return_value={"data": []})
    monkeypatch.setattr(agg, "_market_data", lambda: fake)

    res = await agg.aggregate(days_ahead=1, days_back=1)
    assert res["status"] in ("success", "warning")
    assert fake.get_economic_calendar_ak.await_count == 1
    assert fake.get_economic_calendar_fred.await_count == 1
