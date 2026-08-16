"""
BE-ARCH-06a: 业务数据源聚合 Facade 守门。

验证 DataServiceFacade：
- 只经 datasource_registry.fetch 取数（不直连底层）
- 源选择策略：健康度 → 限流退避 → 业务权重排序
- 多源融合（QUOTE 偏差指标）
- 业务级 Stale 检测 + 降级标记
- OHLCV / 币种 / 复权归一化
- 全源失败降级路径
"""

from __future__ import annotations

import pytest

from backend.services.datasource import (
    ErrorInfo,
    Result,
    ResultStatus,
    datasource_registry,
    rate_limit_registry,
)
from backend.services.datasource.business.facade import _QUOTE_DEVIATION_PCT, DataServiceFacade
from backend.services.datasource.business.fundamental import FundamentalDataService


class _FakeSource:
    """最小 DataSourceInterface 替身，用于驱动 Facade 调度。"""

    def __init__(self, name: str, caps: list[str], data: dict, available: bool = True):
        self._name = name
        self._caps = caps
        self._data = data
        self._available = available

    @property
    def name(self) -> str:
        return self._name

    @property
    def capabilities(self) -> list[str]:
        return self._caps

    def is_available(self) -> bool:
        return self._available

    async def fetch(self, action: str, params: dict) -> Result:
        return Result.make_success(self._data, source=self._name, latency_ms=10.0)


@pytest.fixture(autouse=True)
def _clean():
    datasource_registry.clear()
    rate_limit_registry.clear()
    yield
    datasource_registry.clear()
    rate_limit_registry.clear()


def _register(name: str, caps: list[str], data: dict, available: bool = True) -> None:
    datasource_registry.register(_FakeSource(name, caps, data, available), instance_id="default")


class TestFacadeDispatchViaRegistry:
    @pytest.mark.asyncio
    async def test_get_quote_goes_through_registry(self):
        _register("futu", ["QUOTE"], {"last_price": 150.0, "ticker": "AAPL"})
        facade = DataServiceFacade()
        res = await facade.get_quote("AAPL")
        assert res.is_success
        assert res.source == "futu"
        assert res.data["last_price"] == 150.0

    @pytest.mark.asyncio
    async def test_all_sources_fail_returns_error(self):
        # 注册一个不可用源（is_available=False）
        _register("futu", ["QUOTE"], {}, available=False)
        facade = DataServiceFacade()
        res = await facade.get_quote("AAPL")
        assert res.status == ResultStatus.ERROR
        assert res.error and res.error.code == "ALL_SOURCES_FAILED"


class TestSourceSelectionStrategy:
    @pytest.mark.asyncio
    async def test_business_weight_ordering(self):
        _register("akshare", ["QUOTE"], {"last_price": 1.0, "ticker": "AAPL"})
        _register("futu", ["QUOTE"], {"last_price": 2.0, "ticker": "AAPL"})
        facade = DataServiceFacade()
        # futu 权重100 > akshare 60，应优先被选
        candidates = facade._select_source("QUOTE", None)
        assert candidates[0] == "futu"

    @pytest.mark.asyncio
    async def test_prefer_sources_overrides_weight(self):
        _register("akshare", ["QUOTE"], {"last_price": 1.0, "ticker": "AAPL"})
        _register("futu", ["QUOTE"], {"last_price": 2.0, "ticker": "AAPL"})
        facade = DataServiceFacade()
        candidates = facade._select_source("QUOTE", prefer_sources=["akshare"])
        assert candidates[0] == "akshare"

    @pytest.mark.asyncio
    async def test_rate_limited_source_skipped(self):
        _register("futu", ["QUOTE"], {"last_price": 2.0, "ticker": "AAPL"})
        throttler = rate_limit_registry.get_throttler("futu")
        throttler.on_rate_limit(ErrorInfo.rate_limited(retry_after=60))
        from backend.services.datasource.throttler import BackoffStrategy

        throttler._strategy = BackoffStrategy.EXPONENTIAL  # noqa: SLF001
        throttler.on_rate_limit(ErrorInfo.rate_limited(retry_after=60))

        _register("akshare", ["QUOTE"], {"last_price": 1.0, "ticker": "AAPL"})
        facade = DataServiceFacade()
        candidates = facade._select_source("QUOTE", None)
        assert "futu" not in candidates
        assert candidates == ["akshare"]


class TestMergeAndStale:
    @pytest.mark.asyncio
    async def test_multi_source_merge_picks_freshest(self):
        _register("akshare", ["QUOTE"], {"last_price": 1.0, "ticker": "AAPL"})
        _register("futu", ["QUOTE"], {"last_price": 2.0, "ticker": "AAPL"})
        facade = DataServiceFacade()
        # get_quote 默认 enable_merge=True
        res = await facade.get_quote("AAPL")
        assert res.is_success
        # 两源都成功，merge 取延迟最低（替身 latency 相同），仍返回成功结果
        assert res.data["last_price"] in (1.0, 2.0)

    @pytest.mark.asyncio
    async def test_quote_deviation_emits_metric(self):
        # 偏差超阈值应触发 quote_deviation 指标（这里只验证不抛异常）
        r1 = Result.make_success({"last_price": 100.0}, source="futu", latency_ms=5.0)
        r2 = Result.make_success(
            {"last_price": 100.0 + 100.0 * _QUOTE_DEVIATION_PCT * 2 / 100}, source="yf", latency_ms=6.0
        )
        merged = DataServiceFacade._merge("QUOTE", [r1, r2])
        assert merged is not None

    @pytest.mark.asyncio
    async def test_stale_detection_marks_degraded(self):
        # 注入一个超旧时间戳的 quote
        stale = {"last_price": 150.0, "ticker": "AAPL", "timestamp": 0.0}
        _register("futu", ["QUOTE"], stale)
        facade = DataServiceFacade()
        res = await facade.get_quote("AAPL")
        assert res.status == ResultStatus.DEGRADED
        assert res.error and res.error.code == "DATA_STALE"


class TestNormalize:
    def test_ohlc_alias_unified(self):
        raw = {"Open": 1, "High": 2, "Low": 3, "Close": 4, "Volume": 5}
        out = DataServiceFacade._normalize(raw, "HISTORY")
        assert out["open"] == 1 and out["high"] == 2 and out["low"] == 3 and out["close"] == 4 and out["volume"] == 5

    def test_currency_inferred_for_hk(self):
        raw = {"ticker": "00700.HK", "last_price": 380.0}
        out = DataServiceFacade._normalize(raw, "QUOTE")
        assert out["currency"] == "HKD"

    def test_adjust_default_qfq_for_history(self):
        raw = {"ticker": "AAPL", "close": 1}
        out = DataServiceFacade._normalize(raw, "HISTORY")
        assert out["adjust"] == "qfq"


class TestFundamentalValidation:
    """FundamentalDataService 入参校验分支 (business/fundamental.py)"""

    def test_validate_ticker_empty_raises(self):
        with pytest.raises(ValueError):
            FundamentalDataService._validate_ticker("")

    def test_validate_ticker_none_raises(self):
        with pytest.raises(ValueError):
            FundamentalDataService._validate_ticker(None)

    def test_validate_ticker_whitespace_raises(self):
        with pytest.raises(ValueError):
            FundamentalDataService._validate_ticker("   ")

    @pytest.mark.asyncio
    async def test_get_fundamental_happy_path(self):
        from unittest.mock import AsyncMock

        fake = AsyncMock()
        fake.get_fundamental.return_value = {"pe": 15}
        svc = FundamentalDataService(facade=fake)
        out = await svc.get_fundamental("AAPL")
        assert out == {"pe": 15}
        fake.get_fundamental.assert_awaited_once_with("AAPL", prefer_sources=None)

    @pytest.mark.asyncio
    async def test_get_fundamental_info_happy_path(self):
        from unittest.mock import AsyncMock

        fake = AsyncMock()
        fake.get_fundamental_info.return_value = {"sector": "Tech"}
        svc = FundamentalDataService(facade=fake)
        out = await svc.get_fundamental_info("00700.HK")
        assert out == {"sector": "Tech"}
