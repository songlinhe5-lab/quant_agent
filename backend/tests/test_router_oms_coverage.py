"""补充 oms.py 遗漏分支的覆盖率测试。

conftest 已 autouse 地 bypass 了 /api/v1/oms 的鉴权并 mock 了
backend.core.redis_client.redis_client, 但 oms.py 通过
`from backend.core.redis_client import redis_client` 在导入期绑定,
不受 conftest 对 core 模块的 mock 影响。因此本文件对 oms 真正使用的
redis_client 名称做本地 mock, 避免落到真实 redis 产生并行 flake。

注意: app 有自定义异常处理器, HTTPException 被包成 {"code","msg","data"},
故 500 断言查 resp.json()["msg"] 而非 ["detail"]。
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.core.database import Base, SessionLocal, engine
from backend.core.models import Order
from backend.routers import oms as oms_router

# 🔧 同 test_router_oms.py：幂等建表，确保 Order/AuditLog 表存在（否则路由 log_audit 500）。
Base.metadata.create_all(bind=engine)


def _mem_redis():
    """简单内存 redis mock, set/get/delete/publish 均为 async。"""
    m = MagicMock()
    m.set = AsyncMock(return_value=True)
    m.get = AsyncMock(return_value=None)
    m.delete = AsyncMock(return_value=1)
    m.publish = AsyncMock(return_value=1)
    return m


def _insert_order(order_id: str) -> None:
    with SessionLocal() as s:
        s.query(Order).filter(Order.order_id == order_id).delete()
        s.commit()
        o = Order(
            order_id=order_id,
            symbol="700.HK",
            side="buy",
            order_type="LIMIT",
            qty=100,
            status="SUBMITTED",
            price=10.0,
        )
        s.add(o)
        s.commit()


def _clean_order(order_id: str) -> None:
    with SessionLocal() as s:
        s.query(Order).filter(Order.order_id == order_id).delete()
        s.commit()


@pytest.fixture
def client(test_client):
    return test_client


# ── execute_emergency_liquidation (89-91) ──────────────────────────────────
@pytest.mark.asyncio
async def test_execute_emergency_liquidation_forwards():
    fake_db = MagicMock()
    with patch(
        "backend.app.oms_app.run_emergency_liquidation",
        new=AsyncMock(return_value={"ok": True}),
    ) as m_run:
        await oms_router.execute_emergency_liquidation(fake_db)
        m_run.assert_awaited_once_with(fake_db)


# ── kill_switch 异常分支 (116-117) ─────────────────────────────────────────
def test_kill_switch_raises_500_on_failure(client):
    r = _mem_redis()
    with (
        patch.object(oms_router, "redis_client", r),
        patch(
            "backend.app.oms_app.engage_kill_switch_flags",
            new=AsyncMock(side_effect=RuntimeError("boom")),
        ),
    ):
        resp = client.post("/api/v1/oms/kill_switch", json={"timestamp": 123})
    assert resp.status_code == 500
    assert "kill switch" in resp.json()["msg"].lower()


# ── cancel 异常分支: 删除锁 + 500 (144-146) ────────────────────────────────
def test_cancel_order_dispatch_failure_deletes_lock(client):
    r = _mem_redis()
    with (
        patch.object(oms_router, "redis_client", r),
        patch(
            "backend.services.oms_service.oms_service.update_order_status",
            new=AsyncMock(side_effect=ValueError("db dead")),
        ),
    ):
        resp = client.post(
            "/api/v1/oms/orders/ORD-X/cancel",
            json={"idempotency_key": "key-cancel-fail"},
        )
    assert resp.status_code == 500
    assert "Cancellation dispatch failed" in resp.json()["msg"]
    r.delete.assert_awaited()


# ── modify: order 存在分支 (166-170) ───────────────────────────────────────
def test_modify_order_found_updates_price(client):
    order_id = "ORD-COV-MODIFY-1"
    _insert_order(order_id)
    try:
        r = _mem_redis()
        with (
            patch.object(oms_router, "redis_client", r),
            patch(
                "backend.services.oms_service.oms_service._sync_order_to_redis",
                new=AsyncMock(),
            ),
            patch(
                "backend.services.oms_service.oms_service._publish_orders_update",
                new=AsyncMock(),
            ),
        ):
            resp = client.post(
                f"/api/v1/oms/orders/{order_id}/modify",
                json={"price": 12.5},
            )
        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "success"
        with SessionLocal() as s:
            o = s.query(Order).filter(Order.order_id == order_id).first()
            assert o.price == 12.5
    finally:
        _clean_order(order_id)


# ── modify 异常分支 (176-177) ──────────────────────────────────────────────
def test_modify_order_dispatch_failure(client):
    order_id = "ORD-COV-MODIFY-2"
    _insert_order(order_id)
    try:
        r = _mem_redis()
        with (
            patch.object(oms_router, "redis_client", r),
            patch(
                "backend.services.oms_service.oms_service._sync_order_to_redis",
                new=AsyncMock(side_effect=Exception("redis down")),
            ),
        ):
            resp = client.post(
                f"/api/v1/oms/orders/{order_id}/modify",
                json={"price": 99.0},
            )
        assert resp.status_code == 500
        assert "Modification dispatch failed" in resp.json()["msg"]
    finally:
        _clean_order(order_id)


# ── _get_trading_mode 各分支 (333-337) ─────────────────────────────────────
@pytest.mark.asyncio
async def test_get_trading_mode_returns_redis_value():
    r = _mem_redis()
    r.get = AsyncMock(return_value="PAPER")
    with patch.object(oms_router, "redis_client", r):
        assert await oms_router._get_trading_mode() == "PAPER"


@pytest.mark.asyncio
async def test_get_trading_mode_redis_error_falls_back():
    r = _mem_redis()
    r.get = AsyncMock(side_effect=RuntimeError("redis gone"))
    with patch.object(oms_router, "redis_client", r):
        mode = await oms_router._get_trading_mode()
    assert mode in ("SANDBOX", "LIVE")
