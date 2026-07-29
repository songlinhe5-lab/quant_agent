"""
cache_manager.clear_cache 单测 + /internal/cache/clear 端点鉴权与行为
覆盖：业务缓存清理、交易态前缀保护、自定义前缀、Redis 异常兜底
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

import backend.main  # 预热模块，避免循环导入
from backend.core import cache_manager
from backend.core.security import generate_internal_signature

app = backend.main.app


class FakeRedis:
    """模拟 Redis：scan(cursor, match, count) / delete(*keys)。"""

    def __init__(self, keys_map: dict):
        self._keys_map = keys_map
        self.deleted: list[str] = []

    async def scan(self, cursor, match, count=200):
        return (0, list(self._keys_map.get(match, [])))

    async def delete(self, *keys):
        self.deleted.extend(keys)
        return len(keys)


def test_clear_cache_default_prefixes(monkeypatch):
    """默认业务前缀全部清理，返回正确计数。"""
    fr = FakeRedis(
        {
            "quant:kline:*": ["quant:kline:AAPL", "quant:kline:TSLA"],
            "quant:cache:*": ["quant:cache:quote:AAPL"],
            "quant:news:*": ["quant:news:AAPL"],
            "quant:macro:*": ["quant:macro:VIX"],
            "quant:insider*": ["quant:insider:TSLA"],
            "yf_macro_cache_*": ["yf_macro_cache_sp500"],
        }
    )
    monkeypatch.setattr(cache_manager, "redis_client", fr)

    cleared = asyncio.run(cache_manager.clear_cache())

    assert cleared == 7
    assert len(fr.deleted) == 7
    # 交易态前缀不参与默认扫描，绝不会被删除
    assert not any(k.startswith("quant:oms:") for k in fr.deleted)


def test_clear_cache_custom_prefixes(monkeypatch):
    """自定义前缀：仅清理指定前缀。"""
    fr = FakeRedis(
        {
            "quant:kline:*": ["quant:kline:AAPL", "quant:kline:TSLA"],
            "quant:news:*": ["quant:news:AAPL"],  # 不应被触碰
        }
    )
    monkeypatch.setattr(cache_manager, "redis_client", fr)

    cleared = asyncio.run(cache_manager.clear_cache(["quant:kline:*"]))

    assert cleared == 2
    assert fr.deleted == ["quant:kline:AAPL", "quant:kline:TSLA"]
    assert "quant:news:AAPL" not in fr.deleted


def test_clear_cache_protected_prefix_skipped(monkeypatch):
    """被显式传入的交易态前缀仍被保护，不删除任何数据。"""
    fr = FakeRedis({"quant:oms:active_orders:*": ["quant:oms:active_orders:US.AAPL"]})
    monkeypatch.setattr(cache_manager, "redis_client", fr)

    cleared = asyncio.run(cache_manager.clear_cache(["quant:oms:active_orders:*"]))

    assert cleared == 0
    assert fr.deleted == []


def test_clear_cache_scan_error_returns_zero(monkeypatch):
    """Redis scan 抛异常时安全兜底，返回 0 不清任何数据。"""
    fr = MagicMock()
    fr.scan = AsyncMock(side_effect=RuntimeError("redis down"))
    monkeypatch.setattr(cache_manager, "redis_client", fr)

    cleared = asyncio.run(cache_manager.clear_cache())
    assert cleared == 0
    fr.delete.assert_not_called()


def _signed_headers(method: str, path: str) -> dict:
    """构造内部请求签名头（X-Internal-Sig: timestamp.signature）。"""
    return {"X-Internal-Sig": generate_internal_signature(method, path)}


def test_internal_cache_clear_ok():
    """带 HMAC 签名：调用 clear_cache 并返回 cleared 计数。"""
    from backend.routers import internal as internal_router

    path = "/api/v1/internal/cache/clear"
    with patch.object(internal_router, "clear_cache", new=AsyncMock(return_value=7)):
        client = TestClient(app)
        resp = client.post(path, headers=_signed_headers("POST", path), json={})
    assert resp.status_code == 200
    # 全局响应中间件将返回值包进 data
    body = resp.json()["data"]
    assert body["status"] == "ok"
    assert body["cleared"] == 7


def test_internal_cache_clear_custom_prefixes():
    """请求体携带 prefixes 时透传给 clear_cache。"""
    from backend.routers import internal as internal_router

    path = "/api/v1/internal/cache/clear"
    fake = AsyncMock(return_value=2)
    with patch.object(internal_router, "clear_cache", new=fake):
        client = TestClient(app)
        resp = client.post(
            path,
            headers=_signed_headers("POST", path),
            json={"prefixes": ["quant:kline:*"]},
        )
    assert resp.status_code == 200
    fake.assert_awaited_once_with(["quant:kline:*"])


def test_internal_cache_clear_missing_signature():
    """无签名：鉴权失败返回 401。"""
    client = TestClient(app)
    resp = client.post("/api/v1/internal/cache/clear", json={})
    assert resp.status_code == 401
