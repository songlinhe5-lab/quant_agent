"""AI-02 解盘副驾 /ai/stream 单元测试

验证 NDJSON 流式协议：首包 ping、delta 逐段真文本、done 结构化结果、error 不中断。
monkeypatch 解说服务以隔离真实 LLM/工具调用，专注验证流协议本身。
"""

import json

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.routers import ai_narrator
from backend.services.ai_narrator.models import NarrativeResult


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def fake_narrate(monkeypatch):
    result = NarrativeResult(
        symbol="AAPL",
        direction="up",
        change_pct=2.8,
        threshold=2.0,
        summary="AAPL 盘中异动拉升 2.8%，头肩底形态历史胜率 68%，主力净流入 1.2 亿。",
        source="mock",
        confidence=0.82,
        pattern_winrate=0.68,
    )

    async def _fake(*args, **kwargs):
        return result

    monkeypatch.setattr(ai_narrator._service, "narrate", _fake)
    return result


def test_ai_stream_protocol(client, fake_narrate):
    resp = client.post(
        "/api/v1/ai/stream",
        json={
            "symbol": "AAPL",
            "change_pct": 2.8,
            "direction": "up",
            "include_pattern_winrate": True,
            "pattern_winrate": 0.68,
            "pattern_name": "头肩底",
        },
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/x-ndjson")

    events = [json.loads(line) for line in resp.text.split("\n") if line.strip()]
    assert events[0]["event"] == "ping"

    deltas = [e for e in events if e["event"] == "delta"]
    assert deltas, "应当包含 delta 事件"
    joined = "".join(d["data"]["text"] for d in deltas)
    assert "AAPL" in joined  # 真实内容切片，不编造

    done = [e for e in events if e["event"] == "done"][-1]
    assert done["data"]["summary"] == fake_narrate.summary
    assert done["data"]["pattern_winrate"] == 0.68
    assert done["data"]["source"] == "mock"


def test_ai_stream_error_event_not_interrupt(client, monkeypatch):
    async def _boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(ai_narrator._service, "narrate", _boom)

    resp = client.post("/api/v1/ai/stream", json={"symbol": "TSLA", "change_pct": 3.1})
    assert resp.status_code == 200
    events = [json.loads(line) for line in resp.text.split("\n") if line.strip()]
    assert events[0]["event"] == "ping"
    assert any(e["event"] == "error" for e in events)  # 下游异常透传为 error 事件
    # error 事件不抛 500、不中断流（流正常结束）
