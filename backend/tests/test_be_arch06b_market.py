"""
BE-ARCH-06b: 行情领域业务适配器守门。

验证 MarketDataService：
- ticker 校验拦截空/注入字符
- ktype 归一映射
- 行情语义方法经 Facade 走通 Registry 链路
"""

from __future__ import annotations

import pytest

from backend.services.datasource import (
    Result,
    datasource_registry,
    rate_limit_registry,
)
from backend.services.datasource.business.market import MarketDataService, market_data_service


class _FakeSource:
    def __init__(self, name, caps, data, available=True):
        self._name = name
        self._caps = caps
        self._data = data
        self._available = available

    @property
    def name(self):
        return self._name

    @property
    def capabilities(self):
        return self._caps

    def is_available(self):
        return self._available

    async def fetch(self, action, params):
        return Result.make_success(self._data, source=self._name, latency_ms=5.0)


@pytest.fixture(autouse=True)
def _clean():
    datasource_registry.clear()
    rate_limit_registry.clear()
    yield
    datasource_registry.clear()
    rate_limit_registry.clear()


def _register(name, caps, data, available=True):
    datasource_registry.register(_FakeSource(name, caps, data, available), instance_id="default")


class TestTickerValidation:
    def test_empty_ticker_rejected(self):
        with pytest.raises(ValueError):
            MarketDataService._validate_ticker("")

    def test_injection_ticker_rejected(self):
        with pytest.raises(ValueError):
            MarketDataService._validate_ticker("AAPL; DROP TABLE")


class TestKtypeNormalize:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("day", "K_DAY"),
            ("D", "K_DAY"),
            ("5min", "K_MIN_5"),
            ("K_WEEK", "K_WEEK"),
            ("week", "K_WEEK"),
        ],
    )
    def test_ktype_mapping(self, raw, expected):
        assert MarketDataService._normalize_ktype(raw) == expected


class TestMarketDispatch:
    @pytest.mark.asyncio
    async def test_get_quote_e2e(self):
        _register("futu", ["QUOTE"], {"last_price": 150.0, "ticker": "AAPL"})
        res = await market_data_service.get_quote("AAPL")
        assert res.is_success
        assert res.data["last_price"] == 150.0

    @pytest.mark.asyncio
    async def test_get_history_ktype_normalized(self):
        captured = {}

        class Cap(_FakeSource):
            async def fetch(self, action, params):
                captured.update(params)
                return Result.make_success({"close": [1, 2]}, source="futu", latency_ms=5.0)

        datasource_registry.register(Cap("futu", ["HISTORY"], {}), instance_id="default")
        res = await market_data_service.get_history("AAPL", ktype="5min", num=10)
        assert res.is_success
        assert captured["ktype"] == "K_MIN_5"
        assert captured["num"] == 10
