"""routers/calendars.py 单元测试 (FE-PROD-05)

覆盖: /calendars/snapshot (缓存/聚合/STALE) · /calendars/hours · /calendars/dividends · /calendars/ipos
以及 macro.py 新增的 /macro/earnings 复用。

注意：全局响应包装器将端点返回值置于 {"code":0,"msg":"ok","data": <端点返回>}，
因此断言时统一取 resp.json()["data"] 再访问端点字段。
"""

import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.main import app


@pytest.fixture
def client():
    return TestClient(app)


# ==========================================
# GET /api/v1/calendars/snapshot
# ==========================================


class TestCalendarsSnapshot:
    def test_snapshot_cache_hit(self, client):
        """缓存命中：直接返回 Redis 缓存的快照结构"""
        cached = {
            "status": "success",
            "data": {"timezone": "Asia/Hong_Kong", "categories": [], "server_time": "x"},
            "updated_at": "2026-07-16T00:00:00Z",
        }
        with patch("backend.routers.calendars.redis_client") as m_redis:
            m_redis.get = AsyncMock(return_value=json.dumps(cached))
            resp = client.get("/api/v1/calendars/snapshot")
        assert resp.status_code == 200
        body = resp.json()["data"]
        assert body["status"] == "success"
        assert "categories" in body["data"]

    def test_snapshot_force_refresh_bypasses_cache_and_aggregates(self, client):
        """force_refresh 跳过缓存，按类目聚合行情；SPX tile 来自 yf Redis 缓存"""

        def fake_get(key: str):
            if key == "calendars_snapshot":
                return None
            if key == "yf_macro_cache_^GSPC":
                return json.dumps(
                    [
                        {"Date": "2026-07-15", "Close": 4900.0},
                        {"Date": "2026-07-16", "Close": 5000.0},
                    ]
                )
            return None

        # on-demand 兜底在生产才触发真实 Yahoo，单测中隔离，避免 52 次网络请求
        with (
            patch("backend.routers.calendars.redis_client") as m_redis,
            patch("backend.routers.calendars._fetch_calendar_tile_ondemand", new=AsyncMock(return_value=None)),
        ):
            m_redis.get = AsyncMock(side_effect=fake_get)
            m_redis.set = AsyncMock(return_value=True)
            resp = client.get("/api/v1/calendars/snapshot?force_refresh=true")
        assert resp.status_code == 200
        data = resp.json()["data"]["data"]
        # 7 大类目全部返回
        assert len(data["categories"]) == 7
        us = next(c for c in data["categories"] if c["category"] == "us_markets")
        spx = next((t for t in us["tiles"] if t["symbol"] == "SPX"), None)
        assert spx is not None
        assert spx["price"] == 5000.0
        assert round(spx["change_abs"], 2) == 100.0
        assert spx["category"] == "us_markets"
        # 写回缓存
        m_redis.set.assert_awaited()

    def test_snapshot_missing_yf_cache_marks_tile_stale(self, client):
        """yf 缓存缺失且 on-demand 兜底也失败：该 tile 标记 is_stale=True 且 source=N/A"""
        with (
            patch("backend.routers.calendars.redis_client") as m_redis,
            patch("backend.routers.calendars._fetch_calendar_tile_ondemand", new=AsyncMock(return_value=None)),
        ):
            m_redis.get = AsyncMock(return_value=None)
            m_redis.set = AsyncMock(return_value=True)
            resp = client.get("/api/v1/calendars/snapshot")
        assert resp.status_code == 200
        data = resp.json()["data"]["data"]
        crypto = next(c for c in data["categories"] if c["category"] == "crypto")
        btc = next(t for t in crypto["tiles"] if t["symbol"] == "BTC")
        assert btc["is_stale"] is True
        assert btc["source"] == "N/A"
        # 类目维度仍存在
        assert crypto["display_name"] == "Crypto"

    def test_snapshot_ondemand_fills_tile_when_cache_missing(self, client):
        """cache miss 时经 DataSourceRegistry on-demand 兜底抓取成功，tile 不再全空"""
        filled = {
            "symbol": "SPX",
            "display_name": "S&P 500",
            "yf_ticker": "^GSPC",
            "price": 5555.0,
            "change_abs": 55.0,
            "change_pct": 1.0,
            "sparkline": [5500.0, 5555.0],
            "updated_at": "2026-07-16",
            "is_stale": False,
            "source": "YFinance",
            "category": "us_markets",
        }
        with (
            patch("backend.routers.calendars.redis_client") as m_redis,
            patch("backend.routers.calendars._fetch_calendar_tile_ondemand", new=AsyncMock(return_value=filled)),
        ):
            m_redis.get = AsyncMock(return_value=None)
            m_redis.set = AsyncMock(return_value=True)
            resp = client.get("/api/v1/calendars/snapshot")
        assert resp.status_code == 200
        data = resp.json()["data"]["data"]
        us = next(c for c in data["categories"] if c["category"] == "us_markets")
        spx = next((t for t in us["tiles"] if t["symbol"] == "SPX"), None)
        assert spx is not None
        assert spx["price"] == 5555.0
        assert spx["source"] == "YFinance"
        assert spx["is_stale"] is False

# ==========================================
# GET /api/v1/calendars/hours
# ==========================================


class TestCalendarsHours:
    def test_hours_returns_timezones_and_markets(self, client):
        resp = client.get("/api/v1/calendars/hours")
        assert resp.status_code == 200
        body = resp.json()["data"]
        assert body["status"] == "success"
        data = body["data"]
        assert len(data["timezones"]) == 5
        assert len(data["markets"]) == 5
        # Crypto 市场 7x24 视为开盘
        crypto = next(m for m in data["markets"] if m["name"] == "Crypto")
        assert crypto["is_open"] is True
        assert crypto["open"] is None


# ==========================================
# GET /api/v1/calendars/dividends · /ipos
# ==========================================


class TestCalendarsSchedules:
    def test_dividends_unavailable_without_finnhub_key(self, client):
        """未配置 FINNHUB_API_KEY：优雅降级返回 unavailable（HTTP 200）"""
        with patch("backend.routers.calendars._finnhub_key", return_value=""):
            resp = client.get("/api/v1/calendars/dividends")
        assert resp.status_code == 200
        body = resp.json()["data"]
        assert body["status"] == "unavailable"
        assert body["data"] == []

    def test_ipos_unavailable_without_finnhub_key(self, client):
        with patch("backend.routers.calendars._finnhub_key", return_value=""):
            resp = client.get("/api/v1/calendars/ipos")
        assert resp.status_code == 200
        body = resp.json()["data"]
        assert body["status"] == "unavailable"
        assert body["data"] == []


# ==========================================
# GET /api/v1/macro/earnings (复用聚合)
# ==========================================


class TestMacroEarnings:
    def test_earnings_reuses_aggregator(self, client):
        with (
            patch("backend.routers.macro._fetch_earnings_calendar_data", new_callable=AsyncMock) as m_earn,
        ):
            m_earn.return_value = {
                "status": "success",
                "data": [{"symbol": "AAPL", "date": "2026-07-30"}],
            }
            resp = client.get("/api/v1/macro/earnings?days_ahead=7")
        assert resp.status_code == 200
        body = resp.json()["data"]
        assert body["status"] == "success"
        assert body["data"][0]["symbol"] == "AAPL"
