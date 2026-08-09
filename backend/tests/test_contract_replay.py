"""
SVC-01: 三方数据源契约测试 (录制回放)
====================================

录制点: DataSourceRouter._send_request 发出的 httpx 调用 (到 data_subservice
``/api/v1/data``)。cassette 预置在 ``backend/tests/cassettes/``。

工作流:
- 默认 CI/本地: record_mode='none', 离线回放预置 cassette。
- 三方字段变更需更新契约: 启动 ContractMockSubservice + QUANT_RECORD=1 跑本文件,
  生成/刷新 cassettes (见 conftest 的 contract_replay 标记或手动运行)。

契约断言: 各 fetch_* 回放响应的 data 字段必须包含三方约定的关键键。
任一方 (Yahoo/Finnhub/FMP/Futu/FRED) 改字段 -> 此处断言变红。
"""

import asyncio
import os
import sys

import pytest

os.environ.setdefault("QUANT_ENV", "testing")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from contract_helpers import (  # noqa: E402
    ContractMockSubservice,
    cassette_path,
    get_vcr,
)

from backend.services.datasource.router import DataSourceRouter  # noqa: E402

RECORDING = os.getenv("QUANT_RECORD") == "1"


def _point_router_to(router: DataSourceRouter, url: str, *node_names: str):
    for n in node_names:
        if n in router._nodes:
            router._nodes[n].url = url
            router._nodes[n].status = "healthy"
            router._nodes[n].circuit_breaker_until = 0.0


@pytest.fixture
def mock_sub():
    svc = ContractMockSubservice()
    if RECORDING:
        svc.start()
        yield svc
        svc.stop()
    else:
        yield svc


# ---------------------------------------------------------------------------
# Finnhub 契约
# ---------------------------------------------------------------------------
class TestFinnhubContract:
    def test_quote_contract(self, mock_sub):
        vcr = get_vcr()
        with vcr.use_cassette(cassette_path("finnhub_quote")):
            router = DataSourceRouter()
            router._enabled = True
            _point_router_to(router, mock_sub.base_url, "finnhub_master")
            result = asyncio.run(router.fetch_finnhub("quote", symbol="AAPL"))

        assert result.get("status") == "success", result
        data = result["data"]
        # Finnhub /quote 契约字段 (FinnhubDataSource.fetch 解析)
        for key in ("c", "pc", "o", "h", "l", "t"):
            assert key in data, f"Finnhub quote 缺少契约字段 {key}: {data}"
        assert data["c"] == 189.71


# ---------------------------------------------------------------------------
# FMP 契约
# ---------------------------------------------------------------------------
class TestFmpContract:
    def test_quote_contract(self, mock_sub):
        vcr = get_vcr()
        with vcr.use_cassette(cassette_path("fmp_quote")):
            router = DataSourceRouter()
            router._enabled = True
            _point_router_to(router, mock_sub.base_url, "fmp_master")
            result = asyncio.run(router.fetch_fmp("quote", symbol="AAPL"))

        assert result.get("status") == "success", result
        data = result["data"]
        for key in (
            "symbol",
            "price",
            "change",
            "changePercentage" if "changePercentage" in data else "changesPercentage",
        ):
            assert key in data, f"FMP quote 缺少契约字段 {key}: {data}"
        assert data["price"] == 189.71


# ---------------------------------------------------------------------------
# Futu 契约 (透传子服务信封)
# ---------------------------------------------------------------------------
class TestFutuContract:
    def test_quote_contract(self, mock_sub):
        vcr = get_vcr()
        with vcr.use_cassette(cassette_path("futu_quote")):
            router = DataSourceRouter()
            router._enabled = True
            _point_router_to(router, mock_sub.base_url, "futu_master")
            result = asyncio.run(router.fetch_futu("quote", ticker="AAPL"))

        assert result.get("status") == "success", result
        data = result["data"]
        for key in ("stock_code", "curt_price", "open_price", "high_price", "low_price"):
            assert key in data, f"Futu quote 缺少契约字段 {key}: {data}"
        assert data["curt_price"] == 189.71


# ---------------------------------------------------------------------------
# Yahoo (yfinance) 契约
# ---------------------------------------------------------------------------
class TestYfinanceContract:
    def test_quote_contract(self, mock_sub):
        vcr = get_vcr()
        with vcr.use_cassette(cassette_path("yfinance_quote")):
            router = DataSourceRouter()
            router._enabled = True
            _point_router_to(router, mock_sub.base_url, "yf_primary")
            result = asyncio.run(router.fetch_yfinance("AAPL", "quote"))

        assert result.get("status") == "success", result
        data = result["data"]
        for key in ("ticker", "price", "open", "day_high", "day_low", "previous_close"):
            assert key in data, f"Yahoo quote 缺少契约字段 {key}: {data}"
        assert data["price"] == 189.71


# ---------------------------------------------------------------------------
# FRED 契约
# ---------------------------------------------------------------------------
class TestFredContract:
    def test_macro_series_contract(self, mock_sub):
        vcr = get_vcr()
        with vcr.use_cassette(cassette_path("fred_macro_series")):
            router = DataSourceRouter()
            router._enabled = True
            _point_router_to(router, mock_sub.base_url, "fred_master")
            result = asyncio.run(router.fetch_fred("macro_series", series_id="DGS10"))

        assert result.get("status") == "success", result
        data = result["data"]
        assert "observations" in data, f"FRED macro_series 缺少契约字段 observations: {data}"
        assert isinstance(data["observations"], list) and len(data["observations"]) > 0
        assert "date" in data["observations"][0] and "value" in data["observations"][0]
