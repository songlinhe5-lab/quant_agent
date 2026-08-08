"""SVC-08 Finnhub 限流感知测试（全远程架构版）。

架构背景（BE-ARCH-01 / SVC-08，2026-08-07 重构后）：
- Finnhub 连接层（REST + WS）已下沉 data_subservice，主服务不再持有 FinnhubService。
- 限流感知由 RateLimitThrottler（rate_limit_registry）承担：子服务侧命中 429/403/402
  时反馈到主服务的 throttler，主服务在退避期内不再向 Finnhub 远程节点发请求。
- 本文件不再测试 FinnhubService 内部限流，改为验证：
  1. rate_limit_registry 的 finnhub throttler 被动探测（on_rate_limit → should_throttle
     → get_status 反馈）。
  2. GET /datasource/finnhub/health 端点（SVC-08 限流感知健康探针）经
     FinnhubDataSource.health() 取数，返回结构含 rate_limit_status，且不直连 FinnhubService。
"""

import pytest

from backend.services.datasource import ErrorCategory, ErrorInfo, rate_limit_registry

# ──────────────────────────────────────────────────────────
#  1. finnhub throttler 被动探测（限流感知核心）
# ──────────────────────────────────────────────────────────


def _rl_error(category: ErrorCategory = ErrorCategory.RATE_LIMIT) -> ErrorInfo:
    if category == ErrorCategory.RATE_LIMIT:
        return ErrorInfo.rate_limited()
    if category == ErrorCategory.IP_BLOCKED:
        return ErrorInfo.ip_blocked()
    return ErrorInfo(category=category, message="error")


@pytest.mark.asyncio
async def test_finnhub_throttler_initial_not_throttled():
    th = rate_limit_registry.get_throttler("finnhub")
    th.reset()
    assert th.should_throttle() is False
    assert th.get_status().is_throttled is False


@pytest.mark.asyncio
async def test_finnhub_throttler_detects_rate_limit():
    th = rate_limit_registry.get_throttler("finnhub")
    th.reset()
    # 模拟子服务上报 429 限流
    th.on_rate_limit(_rl_error(ErrorCategory.RATE_LIMIT))
    assert th.should_throttle() is True
    status = th.get_status()
    assert status.is_throttled is True
    assert status.consecutive_rate_limits >= 1
    assert status.estimated_limit_rpm is not None


@pytest.mark.asyncio
async def test_finnhub_throttler_detects_ip_ban():
    th = rate_limit_registry.get_throttler("finnhub")
    th.reset()
    # 403 = IP 封禁（硬失败，不污染连续限流计数，计入 block_events）
    th.on_rate_limit(_rl_error(ErrorCategory.IP_BLOCKED))
    status = th.get_status()
    assert status.is_throttled is True
    assert status.category == ErrorCategory.IP_BANNED.value
    # IP 封禁不计入 consecutive_limits 指数退避计数，但计入 block_events
    assert status.consecutive_rate_limits >= 1  # == block_events


@pytest.mark.asyncio
async def test_finnhub_throttler_recovers_after_reset():
    """恢复是时间驱动的（throttle_until 过期），单测用 reset() 验证可复位。"""
    th = rate_limit_registry.get_throttler("finnhub")
    th.on_rate_limit(_rl_error(ErrorCategory.RATE_LIMIT))
    assert th.should_throttle() is True
    # 连续成功降低退避间隔（接口契约：递减 consecutive_limits / 降速）
    for _ in range(12):
        th.on_success()
    status = th.get_status()
    assert status.consecutive_rate_limits == 0
    # reset 后彻底解除抑制
    th.reset()
    assert th.should_throttle() is False
    assert th.get_status().is_throttled is False


# ──────────────────────────────────────────────────────────
#  2. GET /api/v1/datasource/finnhub/health 端点（SVC-08）
# ──────────────────────────────────────────────────────────


def test_finnhub_health_endpoint_remote(test_client, monkeypatch):
    """健康探针经 FinnhubDataSource.health() 取数，禁止直连 FinnhubService。"""
    from backend.services.datasource.adapters.finnhub import FinnhubDataSource

    class FakeHealth:
        healthy = True
        connected = True
        mode = "external_rest"
        status = "ok"
        last_error = None

        def to_dict(self):
            return {
                "healthy": self.healthy,
                "connected": self.connected,
                "mode": self.mode,
                "status": self.status,
                "last_error": self.last_error,
            }

    async def fake_health(self):
        return FakeHealth()

    with pytest.MonkeyPatch().context() as m:
        m.setattr(FinnhubDataSource, "health", fake_health)
        from backend.services.datasource.adapters import ensure_all_datasources_registered

        ensure_all_datasources_registered()

        resp = test_client.get("/api/v1/datasource/finnhub/health")

    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["source"] == "finnhub"
    assert body["healthy"] is True
    # SVC-08：Finnhub 解耦后 health 经 FinnhubDataSource 远程取数（不直连 FinnhubService）
    assert body["mode"] == "external_rest"
    assert body["connected"] is True


def test_finnhub_health_endpoint_unregistered(test_client, monkeypatch):
    """Finnhub 未注册时返回 connected=False 但仍带限流状态（不报错，SVC-08 容错）。"""
    from backend.services.datasource import datasource_registry

    with pytest.MonkeyPatch().context() as m:
        m.setattr(datasource_registry, "get", lambda n: None)
        resp = test_client.get("/api/v1/datasource/finnhub/health")

    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["connected"] is False
    assert "rate_limit_status" in body
