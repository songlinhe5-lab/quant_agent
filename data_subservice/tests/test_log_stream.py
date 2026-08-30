"""FE-DEBUG-01 子服务日志流测试：进程内环形缓冲 + /logs/recent 端点（HMAC）。"""

import hashlib
import hmac
import time

import pytest
from fastapi.testclient import TestClient

from data_subservice._internal import log_buffer
from data_subservice.main import HMAC_SECRET, app


@pytest.fixture(autouse=True)
def _fresh_buffer(monkeypatch):
    buf = log_buffer.RingBuffer(capacity=50)
    monkeypatch.setattr(log_buffer, "ring_buffer", buf)
    return buf


def _hmac_headers() -> dict:
    ts = str(int(time.time()))
    message = f"{ts}:".encode("utf-8")
    signature = hmac.new(HMAC_SECRET.encode(), message, hashlib.sha256).hexdigest()
    return {"X-Timestamp": ts, "X-Signature": signature}


class TestRingBuffer:
    def test_append_recent_last_id(self, _fresh_buffer):
        buf = _fresh_buffer
        buf.append("INFO", "worker", "hello")
        buf.append("ERROR", "worker", "boom")
        assert buf.last_id == 2
        assert [e["message"] for e in buf.recent(after_id=0)] == ["hello", "boom"]
        delta = buf.recent(after_id=1)
        assert [e["message"] for e in delta] == ["boom"]

    def test_capacity(self):
        buf = log_buffer.RingBuffer(capacity=5)
        for i in range(8):
            buf.append("INFO", "w", f"m{i}")
        assert len(buf.recent(after_id=0)) == 5


class TestLogsRecentEndpoint:
    def test_recent_requires_hmac(self):
        with TestClient(app) as c:
            res = c.get("/logs/recent")
        assert res.status_code == 403

    def test_recent_with_hmac(self, _fresh_buffer):
        _fresh_buffer.append("INFO", "yfinance_worker", "fetch ok")
        with TestClient(app) as c:
            res = c.get("/logs/recent", params={"after": 0}, headers=_hmac_headers())
        assert res.status_code == 200
        body = res.json()
        assert body["code"] == 0
        data = body["data"]
        assert data["last_id"] == 1
        assert data["entries"][0]["message"] == "fetch ok"

    def test_recent_incremental(self, _fresh_buffer):
        _fresh_buffer.append("INFO", "w", "one")
        with TestClient(app) as c:
            first = c.get("/logs/recent", params={"after": 0}, headers=_hmac_headers()).json()["data"]
            _fresh_buffer.append("WARN", "w", "two")
            second = c.get("/logs/recent", params={"after": first["last_id"]}, headers=_hmac_headers()).json()["data"]
        assert [e["message"] for e in second["entries"]] == ["two"]

    def test_hmac_signature_validation(self, _fresh_buffer):
        bad_headers = {"X-Timestamp": str(int(time.time())), "X-Signature": "0" * 64}
        with TestClient(app) as c:
            res = c.get("/logs/recent", headers=bad_headers)
        assert res.status_code == 403
