"""
ALERT-02: 告警规则 CRUD API — 单元测试
========================================

验证:
  1. 创建规则 (POST /rules)
  2. 查询规则列表 (GET /rules) + 过滤
  3. 查询单条规则 (GET /rules/{id})
  4. 更新规则 (PUT /rules/{id})
  5. 删除规则 (DELETE /rules/{id})
  6. 启停规则 (POST /rules/{id}/toggle)
  7. 告警事件查询 (GET /events)
  8. 事件确认 (POST /events/{id}/ack)
  9. 引擎状态 (GET /engine/status)
  10. 404 处理
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routers.alert import (
    _events_store,
    _rules_store,
    router,
)
from backend.core.alert_models import (
    AlertChannel,
    AlertEvent,
    AlertRule,
    AlertRuleType,
    AlertSeverity,
)


# ─────────────────────────────────────────
#  Fixtures
# ─────────────────────────────────────────


@pytest.fixture
def app():
    test_app = FastAPI()
    test_app.include_router(router)
    return test_app


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture(autouse=True)
def clean_stores():
    """每个测试前清空内存存储"""
    _rules_store.clear()
    _events_store.clear()
    yield
    _rules_store.clear()
    _events_store.clear()


def _make_create_body(
    name="Test Alert",
    ticker="AAPL",
    rule_type="price_above",
    threshold=200.0,
    cooldown_seconds=300,
):
    return {
        "name": name,
        "ticker": ticker,
        "rule_type": rule_type,
        "threshold": threshold,
        "cooldown_seconds": cooldown_seconds,
    }


# ─────────────────────────────────────────
#  测试: 创建规则
# ─────────────────────────────────────────


class TestCreateRule:
    """ALERT-02: POST /rules"""

    def test_create_rule_success(self, client):
        body = _make_create_body()
        resp = client.post("/api/v1/alert/rules", json=body)
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Test Alert"
        assert data["ticker"] == "AAPL"
        assert data["rule_type"] == "price_above"
        assert data["threshold"] == 200.0
        assert data["enabled"] is True
        assert data["trigger_count"] == 0
        assert "rule_id" in data

    def test_create_rule_with_all_fields(self, client):
        body = {
            "name": "Full Alert",
            "ticker": "MSFT",
            "rule_type": "price_below",
            "threshold": 100.0,
            "severity": "critical",
            "channels": ["in_app", "feishu"],
            "cooldown_seconds": 600,
            "metadata": {"avg_volume": 1000},
        }
        resp = client.post("/api/v1/alert/rules", json=body)
        assert resp.status_code == 201
        data = resp.json()
        assert data["severity"] == "critical"
        assert data["channels"] == ["in_app", "feishu"]
        assert data["cooldown_seconds"] == 600

    def test_create_rule_invalid_type(self, client):
        body = _make_create_body()
        body["rule_type"] = "invalid_type"
        resp = client.post("/api/v1/alert/rules", json=body)
        assert resp.status_code == 422

    def test_create_rule_missing_required(self, client):
        resp = client.post("/api/v1/alert/rules", json={"name": "test"})
        assert resp.status_code == 422

    def test_create_rule_cooldown_too_small(self, client):
        body = _make_create_body()
        body["cooldown_seconds"] = 10  # < 60 minimum
        resp = client.post("/api/v1/alert/rules", json=body)
        assert resp.status_code == 422


# ─────────────────────────────────────────
#  测试: 查询规则列表
# ─────────────────────────────────────────


class TestListRules:
    """ALERT-02: GET /rules"""

    def test_list_rules_empty(self, client):
        resp = client.get("/api/v1/alert/rules")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_rules_multiple(self, client):
        for i in range(3):
            client.post("/api/v1/alert/rules", json=_make_create_body(name=f"Rule {i}"))
        resp = client.get("/api/v1/alert/rules")
        assert resp.status_code == 200
        assert len(resp.json()) == 3

    def test_list_rules_filter_by_ticker(self, client):
        client.post("/api/v1/alert/rules", json=_make_create_body(ticker="AAPL"))
        client.post("/api/v1/alert/rules", json=_make_create_body(ticker="MSFT"))
        resp = client.get("/api/v1/alert/rules?ticker=AAPL")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["ticker"] == "AAPL"

    def test_list_rules_filter_by_enabled(self, client):
        resp1 = client.post("/api/v1/alert/rules", json=_make_create_body())
        rule_id = resp1.json()["rule_id"]
        # 停用该规则
        client.post(f"/api/v1/alert/rules/{rule_id}/toggle")

        resp = client.get("/api/v1/alert/rules?enabled=false")
        assert resp.status_code == 200
        assert len(resp.json()) == 1
        assert resp.json()[0]["enabled"] is False


# ─────────────────────────────────────────
#  测试: 查询单条规则
# ─────────────────────────────────────────


class TestGetRule:
    """ALERT-02: GET /rules/{id}"""

    def test_get_rule_success(self, client):
        resp = client.post("/api/v1/alert/rules", json=_make_create_body())
        rule_id = resp.json()["rule_id"]

        resp = client.get(f"/api/v1/alert/rules/{rule_id}")
        assert resp.status_code == 200
        assert resp.json()["rule_id"] == rule_id

    def test_get_rule_not_found(self, client):
        resp = client.get("/api/v1/alert/rules/nonexistent-id")
        assert resp.status_code == 404


# ─────────────────────────────────────────
#  测试: 更新规则
# ─────────────────────────────────────────


class TestUpdateRule:
    """ALERT-02: PUT /rules/{id}"""

    def test_update_rule_name(self, client):
        resp = client.post("/api/v1/alert/rules", json=_make_create_body())
        rule_id = resp.json()["rule_id"]

        resp = client.put(f"/api/v1/alert/rules/{rule_id}", json={"name": "Updated Name"})
        assert resp.status_code == 200
        assert resp.json()["name"] == "Updated Name"

    def test_update_rule_threshold(self, client):
        resp = client.post("/api/v1/alert/rules", json=_make_create_body(threshold=200.0))
        rule_id = resp.json()["rule_id"]

        resp = client.put(f"/api/v1/alert/rules/{rule_id}", json={"threshold": 250.0})
        assert resp.status_code == 200
        assert resp.json()["threshold"] == 250.0

    def test_update_rule_partial(self, client):
        resp = client.post(
            "/api/v1/alert/rules",
            json=_make_create_body(name="Original", threshold=100.0),
        )
        rule_id = resp.json()["rule_id"]

        # 只更新 name，threshold 不变
        resp = client.put(f"/api/v1/alert/rules/{rule_id}", json={"name": "New Name"})
        assert resp.status_code == 200
        assert resp.json()["name"] == "New Name"
        assert resp.json()["threshold"] == 100.0

    def test_update_rule_not_found(self, client):
        resp = client.put("/api/v1/alert/rules/nonexistent-id", json={"name": "test"})
        assert resp.status_code == 404


# ─────────────────────────────────────────
#  测试: 删除规则
# ─────────────────────────────────────────


class TestDeleteRule:
    """ALERT-02: DELETE /rules/{id}"""

    def test_delete_rule_success(self, client):
        resp = client.post("/api/v1/alert/rules", json=_make_create_body())
        rule_id = resp.json()["rule_id"]

        resp = client.delete(f"/api/v1/alert/rules/{rule_id}")
        assert resp.status_code == 204

        # 确认已删除
        resp = client.get(f"/api/v1/alert/rules/{rule_id}")
        assert resp.status_code == 404

    def test_delete_rule_not_found(self, client):
        resp = client.delete("/api/v1/alert/rules/nonexistent-id")
        assert resp.status_code == 404


# ─────────────────────────────────────────
#  测试: 启停规则
# ─────────────────────────────────────────


class TestToggleRule:
    """ALERT-02: POST /rules/{id}/toggle"""

    def test_toggle_rule_disable(self, client):
        resp = client.post("/api/v1/alert/rules", json=_make_create_body())
        rule_id = resp.json()["rule_id"]
        assert resp.json()["enabled"] is True

        resp = client.post(f"/api/v1/alert/rules/{rule_id}/toggle")
        assert resp.status_code == 200
        assert resp.json()["enabled"] is False

    def test_toggle_rule_re_enable(self, client):
        resp = client.post("/api/v1/alert/rules", json=_make_create_body())
        rule_id = resp.json()["rule_id"]

        # 停用
        client.post(f"/api/v1/alert/rules/{rule_id}/toggle")
        # 重新启用
        resp = client.post(f"/api/v1/alert/rules/{rule_id}/toggle")
        assert resp.status_code == 200
        assert resp.json()["enabled"] is True

    def test_toggle_rule_not_found(self, client):
        resp = client.post("/api/v1/alert/rules/nonexistent-id/toggle")
        assert resp.status_code == 404


# ─────────────────────────────────────────
#  测试: 告警事件
# ─────────────────────────────────────────


class TestEvents:
    """ALERT-02: GET /events + POST /events/{id}/ack"""

    def test_list_events_empty(self, client):
        resp = client.get("/api/v1/alert/events")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_events_with_data(self, client):
        import time

        event = AlertEvent(
            event_id="evt-1",
            rule_id="rule-1",
            ticker="AAPL",
            rule_type=AlertRuleType.PRICE_ABOVE,
            severity=AlertSeverity.WARNING,
            message="Test alert",
            trigger_value=205.0,
            threshold=200.0,
            channels=[AlertChannel.IN_APP],
            triggered_at=time.time(),
        )
        _events_store.append(event)

        resp = client.get("/api/v1/alert/events")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["event_id"] == "evt-1"
        assert data[0]["acknowledged"] is False

    def test_list_events_filter_by_ticker(self, client):
        import time

        for ticker in ["AAPL", "MSFT", "AAPL"]:
            _events_store.append(
                AlertEvent(
                    event_id=f"evt-{ticker}",
                    rule_id="rule-1",
                    ticker=ticker,
                    rule_type=AlertRuleType.PRICE_ABOVE,
                    severity=AlertSeverity.WARNING,
                    message="Test",
                    trigger_value=100.0,
                    threshold=100.0,
                    channels=[AlertChannel.IN_APP],
                    triggered_at=time.time(),
                )
            )

        resp = client.get("/api/v1/alert/events?ticker=AAPL")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_list_events_filter_by_severity(self, client):
        import time

        _events_store.append(
            AlertEvent(
                event_id="evt-critical",
                rule_id="rule-1",
                ticker="AAPL",
                rule_type=AlertRuleType.PRICE_ABOVE,
                severity=AlertSeverity.CRITICAL,
                message="Critical",
                trigger_value=100.0,
                threshold=100.0,
                channels=[AlertChannel.IN_APP],
                triggered_at=time.time(),
            )
        )
        _events_store.append(
            AlertEvent(
                event_id="evt-warning",
                rule_id="rule-2",
                ticker="AAPL",
                rule_type=AlertRuleType.PRICE_ABOVE,
                severity=AlertSeverity.WARNING,
                message="Warning",
                trigger_value=100.0,
                threshold=100.0,
                channels=[AlertChannel.IN_APP],
                triggered_at=time.time(),
            )
        )

        resp = client.get("/api/v1/alert/events?severity=critical")
        assert resp.status_code == 200
        assert len(resp.json()) == 1
        assert resp.json()[0]["severity"] == "critical"

    def test_list_events_limit(self, client):
        import time

        for i in range(10):
            _events_store.append(
                AlertEvent(
                    event_id=f"evt-{i}",
                    rule_id="rule-1",
                    ticker="AAPL",
                    rule_type=AlertRuleType.PRICE_ABOVE,
                    severity=AlertSeverity.WARNING,
                    message=f"Event {i}",
                    trigger_value=100.0,
                    threshold=100.0,
                    channels=[AlertChannel.IN_APP],
                    triggered_at=time.time() + i,
                )
            )

        resp = client.get("/api/v1/alert/events?limit=5")
        assert resp.status_code == 200
        assert len(resp.json()) == 5

    def test_ack_event_success(self, client):
        import time

        _events_store.append(
            AlertEvent(
                event_id="evt-ack",
                rule_id="rule-1",
                ticker="AAPL",
                rule_type=AlertRuleType.PRICE_ABOVE,
                severity=AlertSeverity.WARNING,
                message="Test",
                trigger_value=100.0,
                threshold=100.0,
                channels=[AlertChannel.IN_APP],
                triggered_at=time.time(),
            )
        )

        resp = client.post("/api/v1/alert/events/evt-ack/ack")
        assert resp.status_code == 200
        assert resp.json()["acknowledged"] is True

    def test_ack_event_not_found(self, client):
        resp = client.post("/api/v1/alert/events/nonexistent/ack")
        assert resp.status_code == 404


# ─────────────────────────────────────────
#  测试: 引擎状态
# ─────────────────────────────────────────


class TestEngineStatus:
    """ALERT-02: GET /engine/status"""

    def test_engine_status_empty(self, client):
        resp = client.get("/api/v1/alert/engine/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["running"] is True
        assert data["active_rules"] == 0
        assert data["tracked_tickers"] == 0

    def test_engine_status_with_rules(self, client):
        client.post("/api/v1/alert/rules", json=_make_create_body(ticker="AAPL"))
        client.post("/api/v1/alert/rules", json=_make_create_body(ticker="MSFT"))

        resp = client.get("/api/v1/alert/engine/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["active_rules"] == 2
        assert data["tracked_tickers"] == 2

    def test_engine_status_disabled_not_counted(self, client):
        resp = client.post("/api/v1/alert/rules", json=_make_create_body(ticker="AAPL"))
        rule_id = resp.json()["rule_id"]
        client.post(f"/api/v1/alert/rules/{rule_id}/toggle")  # disable

        resp = client.get("/api/v1/alert/engine/status")
        data = resp.json()
        assert data["active_rules"] == 0  # disabled rules not counted
        assert data["tracked_tickers"] == 0
