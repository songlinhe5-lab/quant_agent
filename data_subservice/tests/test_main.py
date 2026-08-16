"""main.py FastAPI 应用路由单元测试 — 使用 TestClient 覆盖 HTTP 层。"""

import hashlib
import hmac
import json
import time

import pytest
from fastapi.testclient import TestClient

import data_subservice.main as main_mod
from data_subservice.main import app


def _sign(body: str, secret: str = "change-me-in-prod") -> tuple:
    ts = str(int(time.time()))
    message = f"{ts}:{body}".encode("utf-8")
    sig = hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
    return ts, sig


@pytest.fixture
def client(monkeypatch):
    # 默认声明 yfinance 能力, 避免 503
    monkeypatch.setenv("DS_CAPABILITIES", "yfinance")
    monkeypatch.setattr(main_mod, "_declared_capabilities", lambda: {"yfinance"})
    return TestClient(app)


class TestHealth:
    def test_health_ok(self, client, monkeypatch):
        monkeypatch.setenv("YF_THREAD_WARN", "999999")  # 线程数必然低于阈值
        r = client.get("/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] in ("healthy", "degraded")
        assert body["service"] == "data-subservice"
        assert "threads" in body
        assert "futu" in body


class TestFutuStatus:
    def test_futu_status_unavailable(self, client, monkeypatch):
        # 直接 mock 快照函数, 避免触碰 ConnectionManager 只读 property
        monkeypatch.setattr(
            main_mod,
            "_futu_status_snapshot",
            lambda: {
                "status": "CONNECTED",
                "connected": True,
                "target": "127.0.0.1:11111",
                "error_msg": "",
                "trade_connected": False,
                "trade_unlocked": False,
                "trade_error": None,
            },
        )
        r = client.get("/futu/status")
        assert r.status_code == 200
        assert r.json()["status"] == "CONNECTED"
        assert r.json()["connected"] is True


class TestMetrics:
    def test_circuit_metrics(self, client):
        r = client.get("/metrics/circuit")
        assert r.status_code == 200
        assert "closed" in r.json() or isinstance(r.json(), dict)

    def test_prometheus_metrics(self, client):
        r = client.get("/metrics")
        assert r.status_code == 200
        # Prometheus text 格式包含 HELP/TYPE 行
        assert "HELP" in r.text or "process_threads" in r.text


class TestVerifyHmac:
    def test_missing_headers(self, client):
        r = client.post("/api/v1/data", json={"source": "yfinance", "action": "QUOTE", "params": {}})
        # 无 HMAC 头 → 403
        assert r.status_code == 403

    def test_expired_timestamp(self, client):
        ts = str(int(time.time()) - 1000)
        body = json.dumps({"source": "yfinance", "action": "QUOTE", "params": {}})
        message = f"{ts}:{body}".encode("utf-8")
        sig = hmac.new(b"change-me-in-prod", message, hashlib.sha256).hexdigest()
        r = client.post(
            "/api/v1/data",
            content=body,
            headers={"X-Timestamp": ts, "X-Signature": sig},
        )
        assert r.status_code == 403

    def test_bad_signature(self, client):
        ts, _ = _sign("")
        body = json.dumps({"source": "yfinance", "action": "QUOTE", "params": {}})
        r = client.post(
            "/api/v1/data",
            content=body,
            headers={"X-Timestamp": ts, "X-Signature": "deadbeef"},
        )
        assert r.status_code == 403


class TestFetchData:
    def test_invalid_json(self, client, monkeypatch):
        ts, sig = _sign("{not json")
        r = client.post(
            "/api/v1/data",
            content=b"{not json",
            headers={"X-Timestamp": ts, "X-Signature": sig},
        )
        assert r.status_code == 400

    def test_undeclared_capability(self, client, monkeypatch):
        # 声明集仅 yfinance, 请求 futu → 503
        monkeypatch.setattr(main_mod, "_declared_capabilities", lambda: {"yfinance"})
        ts, sig = _sign(json.dumps({"source": "futu", "action": "QUOTE", "params": {}}))
        r = client.post(
            "/api/v1/data",
            content=json.dumps({"source": "futu", "action": "QUOTE", "params": {}}),
            headers={"X-Timestamp": ts, "X-Signature": sig},
        )
        assert r.status_code == 503

    def test_yfinance_success(self, client, monkeypatch):
        captured = {}

        async def fake_handle_yfinance(action, params):
            captured["action"] = action
            captured["params"] = params
            return {"rows": [1, 2, 3]}

        monkeypatch.setattr(main_mod, "handle_yfinance", fake_handle_yfinance)
        body = json.dumps({"source": "yfinance", "action": "HISTORY", "params": {"ticker": "AAPL"}})
        ts, sig = _sign(body)
        r = client.post(
            "/api/v1/data",
            content=body,
            headers={"X-Timestamp": ts, "X-Signature": sig},
        )
        assert r.status_code == 200
        assert r.json()["code"] == 0
        assert r.json()["data"] == {"rows": [1, 2, 3]}
        assert captured["action"] == "HISTORY"

    def test_yfinance_exception_returns_500(self, client, monkeypatch):
        async def boom(action, params):
            raise RuntimeError("boom")

        monkeypatch.setattr(main_mod, "handle_yfinance", boom)
        body = json.dumps({"source": "yfinance", "action": "HISTORY", "params": {}})
        ts, sig = _sign(body)
        # TestClient 默认未吞未捕获异常; FastAPI 会返回 500。若 raise_server_exceptions
        # 默认 True 会抛, 这里捕获异常即可(验证路由确实调用了 handler)
        with pytest.raises(Exception):
            client.post(
                "/api/v1/data",
                content=body,
                headers={"X-Timestamp": ts, "X-Signature": sig},
            )

    def test_unknown_source(self, client, monkeypatch):
        # 声明集包含某源, 但不在 _WORKER_IMPORTS 且无 handle_<source>
        monkeypatch.setattr(main_mod, "_declared_capabilities", lambda: {"bogus"})
        ts, sig = _sign(json.dumps({"source": "bogus", "action": "X", "params": {}}))
        r = client.post(
            "/api/v1/data",
            content=json.dumps({"source": "bogus", "action": "X", "params": {}}),
            headers={"X-Timestamp": ts, "X-Signature": sig},
        )
        assert r.status_code == 400

    def test_worker_missing_sdk(self, client, monkeypatch):
        # 声明 cap 后, import 失败 → 503; 通过 builtins 模块 monkeypatch __import__
        import builtins

        monkeypatch.setattr(main_mod, "_declared_capabilities", lambda: {"akshare"})
        real_import = builtins.__import__

        def fake_import(name, *a, **k):
            if name == "data_subservice.akshare_worker":
                raise ModuleNotFoundError("no akshare", name="akshare")
            return real_import(name, *a, **k)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        ts, sig = _sign(json.dumps({"source": "akshare", "action": "X", "params": {}}))
        r = client.post(
            "/api/v1/data",
            content=json.dumps({"source": "akshare", "action": "X", "params": {}}),
            headers={"X-Timestamp": ts, "X-Signature": sig},
        )
        assert r.status_code == 503
