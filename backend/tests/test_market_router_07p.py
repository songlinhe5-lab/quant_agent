"""
BE-ARCH-07p 守门测试：对外暴露 broker / kline 实时数据的 HTTP 端点。

验证：
1. /market/broker/{symbol} 与 /market/kline/{symbol} 在缓存命中时正确返回结构与数据。
2. 缓存未命中时返回 cached=false 且 broker/kline 为 None（前端可据此降级）。
3. 不引入任何外部数据源直连（全程 mock subscription_service，守门 07n 不退化）。
"""

from __future__ import annotations

import sys
from unittest.mock import patch

sys.path.insert(0, sys.path[0])

from fastapi import FastAPI  # noqa: E402

from backend.routers.market import router  # noqa: E402

app = FastAPI()
app.include_router(router)

from fastapi.testclient import TestClient  # noqa: E402

_client = TestClient(app, raise_server_exceptions=False)


def _sample_broker(symbol: str) -> dict:
    return {"symbol": symbol.upper(), "bid": 58.1, "ask": 58.2, "updated_at": 1699999999.0}


def _sample_kline(symbol: str) -> dict:
    return {"symbol": symbol.upper(), "close": 58.15, "updated_at": 1699999999.0}


@patch("backend.routers.market.subscription_service")
def test_broker_cache_hit(mock_sub):
    mock_sub.get_broker.return_value = _sample_broker("00700.HK")
    resp = _client.get("/market/broker/00700.HK")
    assert resp.status_code == 200
    data = resp.json()
    assert data["symbol"] == "00700.HK"
    assert data["cached"] is True
    assert data["broker"]["bid"] == 58.1
    assert data["updated_at"] == 1699999999.0
    assert data["source"] == "quant:broker:channel+poly_cache"
    mock_sub.get_broker.assert_called_once_with("00700.HK")


@patch("backend.routers.market.subscription_service")
def test_broker_cache_miss(mock_sub):
    mock_sub.get_broker.return_value = None
    resp = _client.get("/market/broker/AAPL")
    assert resp.status_code == 200
    data = resp.json()
    assert data["cached"] is False
    assert data["broker"] is None
    assert data["updated_at"] is None
    assert data["source"] is None


@patch("backend.routers.market.subscription_service")
def test_kline_cache_hit(mock_sub):
    mock_sub.get_kline.return_value = _sample_kline("AAPL")
    resp = _client.get("/market/kline/AAPL")
    assert resp.status_code == 200
    data = resp.json()
    assert data["symbol"] == "AAPL"
    assert data["cached"] is True
    assert data["kline"]["close"] == 58.15
    assert data["source"] == "quant:kline:channel+poly_cache"
    mock_sub.get_kline.assert_called_once_with("AAPL")


@patch("backend.routers.market.subscription_service")
def test_kline_cache_miss(mock_sub):
    mock_sub.get_kline.return_value = None
    resp = _client.get("/market/kline/00700.HK")
    assert resp.status_code == 200
    data = resp.json()
    assert data["cached"] is False
    assert data["kline"] is None
    assert data["source"] is None
