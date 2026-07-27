"""BRD-01: 早报刊物 API 路由单元测试 (routers/briefing.py, 覆盖 43% → 全绿)

仅挂载 briefing 路由到最小 FastAPI 实例，避免加载整个 backend.main。
"""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routers import briefing
from backend.services.morning_briefing.models import BriefingResult

app = FastAPI()
app.include_router(briefing.router)


@pytest.fixture
def client():
    return TestClient(app)


def _briefing(bid: str) -> BriefingResult:
    return BriefingResult(
        id=bid,
        date="2026-07-24",
        market="全球",
        markdown="# 早报\n内容",
        source_tools=["get_macro_news"],
    )


def test_generate_success(client):
    with patch(
        "backend.routers.briefing.generate_morning_briefing",
        new_callable=AsyncMock,
        return_value=_briefing("b1"),
    ) as mock_gen:
        resp = client.post("/briefing/generate?market=全球")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    assert body["data"]["id"] == "b1"
    mock_gen.assert_awaited_once()


def test_generate_error_raises_500(client):
    with patch(
        "backend.routers.briefing.generate_morning_briefing",
        new_callable=AsyncMock,
        side_effect=RuntimeError("LLM down"),
    ):
        resp = client.post("/briefing/generate")
    assert resp.status_code == 500


def test_latest_empty(client):
    with patch(
        "backend.routers.briefing.get_latest_briefing",
        new_callable=AsyncMock,
        return_value=None,
    ):
        resp = client.get("/briefing/latest?market=港股")
    assert resp.status_code == 200
    assert resp.json()["status"] == "empty"


def test_latest_success(client):
    with patch(
        "backend.routers.briefing.get_latest_briefing",
        new_callable=AsyncMock,
        return_value=_briefing("b2"),
    ):
        resp = client.get("/briefing/latest")
    assert resp.json()["data"]["id"] == "b2"


def test_share_success(client):
    with patch(
        "backend.routers.briefing.get_briefing",
        new_callable=AsyncMock,
        return_value=_briefing("b3"),
    ):
        resp = client.get("/briefing/share/b3")
    assert resp.status_code == 200
    assert resp.json()["data"]["id"] == "b3"


def test_share_not_found_404(client):
    with patch(
        "backend.routers.briefing.get_briefing",
        new_callable=AsyncMock,
        return_value=None,
    ):
        resp = client.get("/briefing/share/missing")
    assert resp.status_code == 404
