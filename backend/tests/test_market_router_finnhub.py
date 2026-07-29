"""
market 路由器 Finnhub 真实数据源桥接单测
覆盖：/news、/events/{ticker}、/insider-transactions
  - 真实源可用 → 返回 finnhub 映射后的数据
  - 真实源不可用 → 回退本地模拟数据（前端联调用）

注意：全局响应中间件会把端点返回值包成 {code, msg, data, ts}，
故断言时统一取 resp.json()["data"]。
"""

import pytest
from fastapi.testclient import TestClient

import backend.main  # 预热模块，规避 legacy_market_data 循环导入

app = backend.main.app


class FakeResult:
    """仿 datasource Result：is_success 为属性（与真实 Result 一致）。"""

    def __init__(self, data, success: bool = True):
        self.data = data
        self._success = success

    @property
    def is_success(self) -> bool:
        return self._success


class FakeRegistry:
    def __init__(self, by_action: dict | None = None):
        self.by_action = by_action or {}
        self.calls = []

    async def fetch(self, source, action, params):
        self.calls.append((source, action, params))
        data = self.by_action.get(action)
        return FakeResult(data, success=data is not None)


@pytest.fixture
def finnhub(monkeypatch):
    """将 Finnhub 数据源替换为可控的 FakeRegistry。"""
    reg = FakeRegistry()
    monkeypatch.setattr("backend.services.datasource.source_registry.datasource_registry", reg)
    monkeypatch.setattr(
        "backend.services.datasource.adapters.finnhub.ensure_finnhub_registered",
        lambda: None,
    )
    return reg


def _data(resp):
    return resp.json()["data"]


def test_news_real_source(finnhub):
    """Finnhub 可用 → source=finnhub，且新闻被映射为 {time, headline, summary}。"""
    finnhub.by_action["company_news"] = [
        {
            "datetime": 1700000000,
            "headline": "Apple beats estimates",
            "summary": "Strong quarter",
            "url": "http://x",
            "category": "company",
        }
    ]
    client = TestClient(app)
    resp = client.get("/api/v1/market/news?ticker=AAPL&limit=5")
    assert resp.status_code == 200
    body = _data(resp)
    assert body["status"] == "success"
    assert body["source"] == "finnhub"
    assert body["data"][0]["headline"] == "Apple beats estimates"
    assert body["data"][0]["time"].startswith("2023")
    assert "summary" in body["data"][0]


def test_news_fallback_mock(finnhub):
    """Finnhub 不可用 → 回退模拟数据，source=mock_news_fallback。"""
    client = TestClient(app)
    resp = client.get("/api/v1/market/news?ticker=AAPL&limit=5")
    assert resp.status_code == 200
    body = _data(resp)
    assert body["status"] == "success"
    assert body["source"] == "mock_news_fallback"


def test_events_real_source(finnhub):
    """财报 + 新闻均来自 Finnhub。"""
    finnhub.by_action["earnings"] = [{"date": "2024-01-15", "quarter": 4, "epsEstimated": 2.1, "eps": 2.3}]
    finnhub.by_action["company_news"] = [{"datetime": 1700000000, "headline": "Guidance raised", "summary": "Up"}]
    client = TestClient(app)
    resp = client.get("/api/v1/market/events/AAPL?days_back=30&days_ahead=30")
    assert resp.status_code == 200
    body = _data(resp)
    assert body["status"] == "success"
    types = {e["type"] for e in body["data"]}
    assert "earnings" in types
    assert "news" in types
    earnings = next(e for e in body["data"] if e["type"] == "earnings")
    assert "Q4" in earnings["label"]


def test_events_fallback_mock(finnhub):
    """Finnhub 不可用 → 回退模拟财报/新闻事件（含合法的 Q 季度标签）。"""
    client = TestClient(app)
    resp = client.get("/api/v1/market/events/AAPL")
    assert resp.status_code == 200
    body = _data(resp)
    assert body["status"] == "success"
    earnings = [e for e in body["data"] if e["type"] == "earnings"]
    assert earnings
    assert earnings[0]["label"].startswith("Q")


def test_insider_real_source(finnhub):
    """Finnhub insider_trading 可用 → 返回映射后的内幕交易。"""
    finnhub.by_action["insider_trading"] = [
        {
            "date": "2024-01-10",
            "name": "Tim Cook",
            "action": "Sale",
            "change": -50000,
            "transaction_price": 185.0,
        }
    ]
    client = TestClient(app)
    resp = client.get("/api/v1/market/insider-transactions?ticker=AAPL&limit=5")
    assert resp.status_code == 200
    body = _data(resp)
    assert body["status"] == "success"
    assert body["source"] == "finnhub"
    row = body["data"][0]
    assert row["name"] == "Tim Cook"
    assert row["transaction_type"] == "Sale"
    assert row["shares"] == -50000
    assert row["price"] == 185.0
    assert row["value"] == -50000 * 185.0


def test_insider_fallback_mock(finnhub):
    """Finnhub 不可用 → 回退模拟内幕交易数据。"""
    client = TestClient(app)
    resp = client.get("/api/v1/market/insider-transactions?ticker=AAPL&limit=5")
    assert resp.status_code == 200
    body = _data(resp)
    assert body["status"] == "success"
    assert body["source"] == "mock_insider_data"
    assert body["data"]
