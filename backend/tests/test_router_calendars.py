"""
全球市场日历路由测试
覆盖: backend/routers/calendars.py
"""

import json
import os
import sys
from datetime import timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from fastapi.testclient import TestClient

from backend.main import app
from backend.routers.calendars import (
    _build_tile_from_records,
    _extract_closes_from_records,
    _market_session_state,
    _parse_updated_at,
)


@pytest.fixture
def client():
    return TestClient(app)


def _unwrap(resp):
    """剥离可能的响应封装"""
    body = resp.json()
    if isinstance(body, dict) and "data" in body and isinstance(body["data"], dict):
        inner = body["data"]
        if "status" in inner:
            return inner
    return body


# ==========================================
# 工具函数测试
# ==========================================
class TestParseUpdatedAt:
    def test_iso_datetime(self):
        """ISO 日期时间解析"""
        dt = _parse_updated_at("2026-07-16T12:00:00")
        assert dt is not None
        assert dt.year == 2026

    def test_iso_datetime_with_z(self):
        """带 Z 后缀的 ISO 时间"""
        dt = _parse_updated_at("2026-07-16T12:00:00Z")
        assert dt is not None

    def test_date_only(self):
        """仅日期字符串"""
        dt = _parse_updated_at("2026-07-16")
        assert dt is not None
        assert dt.tzinfo == timezone.utc

    def test_empty_string(self):
        """空字符串返回 None"""
        assert _parse_updated_at("") is None

    def test_invalid_string(self):
        """无效字符串返回 None"""
        assert _parse_updated_at("not-a-date") is None


class TestMarketSessionState:
    def test_crypto_24_7(self):
        """加密货币 7x24 交易"""
        is_open, next_change = _market_session_state(None, None, None)
        assert is_open is True
        assert next_change is None

    def test_no_zoneinfo(self):
        """zoneinfo 为 None 时返回 True"""
        with patch("backend.routers.calendars.zoneinfo", None):
            is_open, _ = _market_session_state("America/New_York", (9, 30), (16, 0))
        assert is_open is True

    def test_valid_market(self):
        """有效市场返回元组"""
        is_open, next_change = _market_session_state("America/New_York", (9, 30), (16, 0))
        assert isinstance(is_open, bool)

    def test_invalid_tz(self):
        """无效时区返回 True"""
        is_open, _ = _market_session_state("Invalid/Timezone", (9, 30), (16, 0))
        assert is_open is True


class TestExtractCloses:
    def test_basic_close(self):
        """基本 Close 字段提取"""
        records = [{"Close": 100.0}, {"Close": 101.5}, {"Close": 102.0}]
        closes = _extract_closes_from_records(records)
        assert closes == [100.0, 101.5, 102.0]

    def test_multi_level_column(self):
        """多级列名 ('Close', ticker)"""
        records = [{"('Close', 'AAPL')": 150.0}, {"('Close', 'AAPL')": 151.0}]
        closes = _extract_closes_from_records(records)
        assert closes == [150.0, 151.0]

    def test_non_dict_records(self):
        """非字典记录被跳过"""
        records = [None, "invalid", {"Close": 100.0}]
        closes = _extract_closes_from_records(records)
        assert closes == [100.0]

    def test_empty_records(self):
        """空记录"""
        assert _extract_closes_from_records([]) == []

    def test_invalid_close_value(self):
        """无效 Close 值被跳过"""
        records = [{"Close": "not_a_number"}, {"Close": 100.0}]
        closes = _extract_closes_from_records(records)
        assert closes == [100.0]


class TestBuildTileFromRecords:
    def test_basic_tile(self):
        """基本 tile 构建"""
        records = [
            {"Close": 100.0, "Date": "2026-07-15"},
            {"Close": 102.0, "Date": "2026-07-16"},
        ]
        cfg = {"symbol": "SPX", "name": "S&P 500", "yf": "^GSPC"}
        tile = _build_tile_from_records(records, cfg, "us_markets")
        assert tile is not None
        assert tile["symbol"] == "SPX"
        assert tile["price"] == 102.0
        assert tile["change_abs"] == 2.0
        assert tile["change_pct"] == 2.0
        assert tile["category"] == "us_markets"
        assert tile["source"] == "YFinance"

    def test_empty_records(self):
        """空记录返回 None"""
        cfg = {"symbol": "SPX", "name": "S&P 500", "yf": "^GSPC"}
        assert _build_tile_from_records([], cfg, "us_markets") is None

    def test_no_closes(self):
        """无有效收盘价返回 None"""
        records = [{"Volume": 1000}]
        cfg = {"symbol": "SPX", "name": "S&P 500", "yf": "^GSPC"}
        assert _build_tile_from_records(records, cfg, "us_markets") is None

    def test_single_record(self):
        """单条记录 (prev_close = last_close)"""
        records = [{"Close": 100.0, "Date": "2026-07-16"}]
        cfg = {"symbol": "SPX", "name": "S&P 500", "yf": "^GSPC"}
        tile = _build_tile_from_records(records, cfg, "us_markets")
        assert tile is not None
        assert tile["change_abs"] == 0.0
        assert tile["change_pct"] == 0.0

    def test_sparkline_limit(self):
        """sparkline 最多 60 条"""
        records = [{"Close": float(i), "Date": f"2026-01-{i:02d}"} for i in range(1, 80)]
        cfg = {"symbol": "SPX", "name": "S&P 500", "yf": "^GSPC"}
        tile = _build_tile_from_records(records, cfg, "us_markets")
        assert tile is not None
        assert len(tile["sparkline"]) <= 60


# ==========================================
# 端点测试
# ==========================================
class TestCalendarsSnapshot:
    @patch("backend.routers.calendars.redis_client")
    def test_snapshot_cached(self, mock_redis, client):
        """快照缓存命中"""
        cached_data = json.dumps({"status": "success", "data": {"categories": []}})
        mock_redis.get = AsyncMock(return_value=cached_data)
        resp = client.get("/api/v1/calendars/snapshot")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "success"

    @patch("backend.routers.calendars._fetch_calendar_snapshot")
    @patch("backend.routers.calendars.redis_client")
    def test_snapshot_cache_miss(self, mock_redis, mock_fetch, client):
        """快照缓存未命中"""
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.set = AsyncMock()
        mock_fetch.return_value = {
            "categories": [],
            "timezone": "Asia/Hong_Kong",
            "server_time": "2026-07-23T00:00:00Z",
            "data_sources_health": {},
        }
        resp = client.get("/api/v1/calendars/snapshot")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "success"


class TestCalendarsHours:
    def test_hours_endpoint(self, client):
        """交易时段矩阵"""
        resp = client.get("/api/v1/calendars/hours")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "success"
        data = body["data"]
        assert "timezones" in data
        assert "markets" in data
        assert len(data["timezones"]) >= 4
        assert len(data["markets"]) >= 4


class TestCalendarsDividends:
    def test_dividends_no_api_key(self, client):
        """无 API Key 时返回 unavailable"""
        with patch.dict(os.environ, {"FINNHUB_API_KEY": ""}):
            resp = client.get("/api/v1/calendars/dividends")
        assert resp.status_code == 200
        body = _unwrap(resp)
        assert body.get("status") in ("unavailable", "error", "degraded")

    @patch("backend.routers.calendars.redis_client")
    def test_dividends_cached(self, mock_redis, client):
        """分红日历缓存命中"""
        cached = json.dumps({"status": "success", "data": [{"symbol": "AAPL"}]})
        mock_redis.get = AsyncMock(return_value=cached)
        with patch.dict(os.environ, {"FINNHUB_API_KEY": "test-key"}):
            resp = client.get("/api/v1/calendars/dividends")
        assert resp.status_code == 200
        body = _unwrap(resp)
        assert body.get("status") == "success"

    @patch("backend.routers.calendars.rate_limit_registry")
    @patch("backend.routers.calendars.redis_client")
    def test_dividends_throttled(self, mock_redis, mock_rl, client):
        """限流退避时返回 degraded"""
        mock_redis.get = AsyncMock(return_value=None)
        mock_throttler = MagicMock()
        mock_throttler.should_throttle.return_value = True
        mock_rl.get_throttler.return_value = mock_throttler
        with patch.dict(os.environ, {"FINNHUB_API_KEY": "test-key"}):
            resp = client.get("/api/v1/calendars/dividends")
        assert resp.status_code == 200
        body = _unwrap(resp)
        assert body.get("status") in ("degraded", "error")


class TestCalendarsIpos:
    def test_ipos_no_api_key(self, client):
        """无 API Key 时返回 unavailable"""
        with patch.dict(os.environ, {"FINNHUB_API_KEY": ""}):
            resp = client.get("/api/v1/calendars/ipos")
        assert resp.status_code == 200
        body = _unwrap(resp)
        assert body.get("status") in ("unavailable", "error", "degraded")

    @patch("backend.routers.calendars.redis_client")
    def test_ipos_cached(self, mock_redis, client):
        """IPO 日历缓存命中"""
        cached = json.dumps({"status": "success", "data": [{"symbol": "NEWTICKER"}]})
        mock_redis.get = AsyncMock(return_value=cached)
        with patch.dict(os.environ, {"FINNHUB_API_KEY": "test-key"}):
            resp = client.get("/api/v1/calendars/ipos")
        assert resp.status_code == 200
        body = _unwrap(resp)
        assert body.get("status") == "success"

    @patch("backend.routers.calendars.rate_limit_registry")
    @patch("backend.routers.calendars.redis_client")
    def test_ipos_throttled(self, mock_redis, mock_rl, client):
        """限流退避时返回 degraded"""
        mock_redis.get = AsyncMock(return_value=None)
        mock_throttler = MagicMock()
        mock_throttler.should_throttle.return_value = True
        mock_rl.get_throttler.return_value = mock_throttler
        with patch.dict(os.environ, {"FINNHUB_API_KEY": "test-key"}):
            resp = client.get("/api/v1/calendars/ipos")
        assert resp.status_code == 200
        body = _unwrap(resp)
        assert body.get("status") in ("degraded", "error")


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
