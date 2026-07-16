"""
SVC-08: Finnhub 限流感知测试
==============================

验证:
1. FinnhubService 各方法在 429/403 时接入 RateLimitThrottler（记录限流，不计入熔断）
2. 真实请求成功时推进自适应退避恢复（on_success）
3. calendars dividends/ipos 在限流退避期内返回 degraded，不硬重试
4. /api/v1/datasource/finnhub/health 健康端点（被动探测 + 限流状态）
"""

import os
import sys
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

os.environ.setdefault("FINNHUB_API_KEY", "test-finnhub-key")


def _resp(json_data=None, err_code=None):
    """构造 httpx.Response mock：429/403 时 raise_for_status 抛 HTTPStatusError。"""
    r = MagicMock()
    r.json.return_value = json_data or {}
    r.status_code = err_code or 200
    if err_code:
        err = httpx.HTTPStatusError("err", request=MagicMock(), response=MagicMock(status_code=err_code))
        r.raise_for_status = MagicMock(side_effect=err)
    else:
        r.raise_for_status = MagicMock()
    return r


@asynccontextmanager
async def _client_cm(response=None):
    c = AsyncMock()
    c.get = AsyncMock(return_value=response)
    yield c


@pytest.fixture(autouse=True)
def _reset_finnhub_throttler():
    from backend.services.datasource import rate_limit_registry

    rate_limit_registry.get_throttler("finnhub").reset()
    yield
    rate_limit_registry.get_throttler("finnhub").reset()


# ─────────────────────────────────────────
#  FinnhubService 限流感知
# ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_earnings_429_records_rate_limit():
    """SVC-08: 财报日历 429 应触发 throttler 退避（不计入熔断器失败计数）。"""
    from backend.services.datasource import rate_limit_registry
    from backend.services.finnhub_service import FinnhubService

    svc = FinnhubService()
    with (
        patch("backend.services.finnhub_service.redis_client") as m,
        patch(
            "backend.services.finnhub_service.httpx.AsyncClient",
            return_value=_client_cm(response=_resp(err_code=429)),
        ),
    ):
        m.get = AsyncMock(return_value=None)
        result = await svc.get_earnings_calendar()

    assert result["status"] == "error"
    assert "HTTP 429" in result["message"]
    st = rate_limit_registry.get_throttler("finnhub").get_status()
    assert st.consecutive_rate_limits >= 1
    assert st.is_throttled is True


@pytest.mark.asyncio
async def test_market_news_429_records_rate_limit():
    """SVC-08: 新闻 429 应记录限流。"""
    from backend.services.datasource import rate_limit_registry
    from backend.services.finnhub_service import FinnhubService

    svc = FinnhubService()
    with patch(
        "backend.services.finnhub_service.httpx.AsyncClient",
        return_value=_client_cm(response=_resp(err_code=429)),
    ):
        result = await svc.get_market_news()

    assert "429" in result["message"]
    st = rate_limit_registry.get_throttler("finnhub").get_status()
    assert st.consecutive_rate_limits >= 1


@pytest.mark.asyncio
async def test_earnings_success_records_success():
    """SVC-08: 真实请求成功应推进退避恢复（consecutive_rate_limits 保持 0）。"""
    from backend.services.datasource import rate_limit_registry
    from backend.services.finnhub_service import FinnhubService

    svc = FinnhubService()
    data = {"earningsCalendar": [{"symbol": "AAPL", "date": "2026-06-30"}, {"symbol": ""}]}
    with (
        patch("backend.services.finnhub_service.redis_client") as m,
        patch(
            "backend.services.finnhub_service.httpx.AsyncClient",
            return_value=_client_cm(response=_resp(data)),
        ),
    ):
        m.get, m.setex = AsyncMock(return_value=None), AsyncMock()
        result = await svc.get_earnings_calendar()

    assert result["status"] == "success"
    assert len(result["data"]) == 1
    st = rate_limit_registry.get_throttler("finnhub").get_status()
    assert st.consecutive_rate_limits == 0


# ─────────────────────────────────────────
#  Calendars dividends/ipos 限流感知
# ─────────────────────────────────────────


def test_calendars_dividends_429_records_throttler():
    """SVC-08: calendars /dividends 遇 429 返回 error 且记录限流。"""
    from fastapi.testclient import TestClient

    from backend.main import app
    from backend.services.datasource import rate_limit_registry

    with (
        patch("backend.routers.calendars.redis_client") as m,
        patch(
            "backend.routers.calendars.httpx.AsyncClient",
            return_value=_client_cm(response=_resp(err_code=429)),
        ),
    ):
        m.get = AsyncMock(return_value=None)
        r = TestClient(app).get("/api/v1/calendars/dividends")

    body = r.json()["data"]
    assert body["status"] == "error"
    assert "HTTP 429" in body["message"]
    assert rate_limit_registry.get_throttler("finnhub").get_status().consecutive_rate_limits >= 1


def test_calendars_ipos_429_records_throttler():
    """SVC-08: calendars /ipos 遇 429 返回 error 且记录限流。"""
    from fastapi.testclient import TestClient

    from backend.main import app
    from backend.services.datasource import rate_limit_registry

    with (
        patch("backend.routers.calendars.redis_client") as m,
        patch(
            "backend.routers.calendars.httpx.AsyncClient",
            return_value=_client_cm(response=_resp(err_code=403)),
        ),
    ):
        m.get = AsyncMock(return_value=None)
        r = TestClient(app).get("/api/v1/calendars/ipos")

    body = r.json()["data"]
    assert body["status"] == "error"
    assert rate_limit_registry.get_throttler("finnhub").get_status().consecutive_rate_limits >= 1


def test_calendars_dividends_throttled_returns_degraded():
    """SVC-08: 退避期内 calendars /dividends 不硬重试，返回 degraded。"""
    from fastapi.testclient import TestClient

    from backend.main import app
    from backend.services.datasource import rate_limit_registry

    # 1) 先触发一次 429 让 throttler 进入退避期
    with (
        patch("backend.routers.calendars.redis_client") as m,
        patch(
            "backend.routers.calendars.httpx.AsyncClient",
            return_value=_client_cm(response=_resp(err_code=429)),
        ),
    ):
        m.get = AsyncMock(return_value=None)
        TestClient(app).get("/api/v1/calendars/dividends")

    assert rate_limit_registry.get_throttler("finnhub").get_status().is_throttled is True

    # 2) 退避期内再次调用：无缓存命中 → 应返回 degraded，不发起真实请求
    with patch("backend.routers.calendars.redis_client") as m:
        m.get = AsyncMock(return_value=None)
        r = TestClient(app).get("/api/v1/calendars/dividends")

    body = r.json()["data"]
    assert body["status"] == "degraded"
    assert "退避" in body["message"]


# ─────────────────────────────────────────
#  Finnhub 健康端点
# ─────────────────────────────────────────


def test_finnhub_health_endpoint_connected():
    """SVC-08: /datasource/finnhub/health 被动健康探测返回限流状态。"""
    from fastapi.testclient import TestClient

    from backend.main import app

    with patch.dict(os.environ, {"FINNHUB_API_KEY": "x"}, clear=False):
        r = TestClient(app).get("/api/v1/datasource/finnhub/health")

    assert r.status_code == 200
    body = r.json().get("data", r.json())
    assert body["source"] == "finnhub"
    assert body["connected"] is True
    assert "rate_limit_status" in body


def test_finnhub_health_endpoint_no_api_key():
    """SVC-08: 未配置 API Key 时健康端点标记未连接。"""
    from fastapi.testclient import TestClient

    from backend.main import app

    with patch.dict(os.environ, {"FINNHUB_API_KEY": ""}, clear=False):
        r = TestClient(app).get("/api/v1/datasource/finnhub/health")

    assert r.status_code == 200
    body = r.json().get("data", r.json())
    assert body["connected"] is False
    assert body["last_error"] is not None
