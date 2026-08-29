"""
SVC-07: 降级与混沌测试 (Degradation & Chaos)

验证三层降级/容错基础设施在「真实故障注入」下的行为，**真实驱动状态机**
（不 mock 被测逻辑本身，只在最底层注入故障）：

A. 熔断器 CircuitBreaker (BE-04)：连续失败 → OPEN → 超时 → HALF_OPEN → 成功 → CLOSED；
   限流错误不计入熔断计数。
B. LLM Ollama 降级 (AI-02)：主供应商连续失败达阈值 → 自动降级 Ollama；主供应商恢复 → 切回。
C. DataSourceRouter 节点熔断 + failover：主节点连续失败 → unhealthy + 熔断冷却，
   自动切换到备节点；限流类错误只 failover 不熔断；全节点失联 → 返回失败且
   **无本地兜底**（架构红线：移除一切本地 SDK 降级通道）。
D. 端到端降级编排：Futu 节点全失联 → 返回错误且无本地兜底。
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from backend.core.circuit_breaker import (
    CircuitBreakerOpenError,
    CircuitState,
    get_circuit_breaker,
)
from backend.services.ai_narrator.llm_service import LLMRouter, ModelTier
from backend.services.datasource import ErrorCategory
from backend.services.datasource.router import DataSourceNode, DataSourceRouter


# ─────────────────────────────────────────────────────────────
# A. 熔断器 CircuitBreaker 混沌
# ─────────────────────────────────────────────────────────────
async def test_circuit_breaker_open_after_max_failures():
    """连续失败达到 max_failures → OPEN，后续调用抛 CircuitBreakerOpenError。"""
    cb = get_circuit_breaker(max_failures=2, recovery_timeout=100)

    async def boom():
        raise RuntimeError("boom")

    for _ in range(2):
        with pytest.raises(RuntimeError):
            await cb.call("chaos_svc", boom)

    assert cb.get_state("chaos_svc") == CircuitState.OPEN

    with pytest.raises(CircuitBreakerOpenError):
        await cb.call("chaos_svc", boom)
    cb.reset("chaos_svc")


async def test_circuit_breaker_half_open_then_closed():
    """OPEN 超时 → HALF_OPEN → 成功 → CLOSED。"""
    cb = get_circuit_breaker(max_failures=1, recovery_timeout=0.05)

    async def boom():
        raise RuntimeError("boom")

    async def ok():
        return "ok"

    with pytest.raises(RuntimeError):
        await cb.call("chaos_svc2", boom)
    assert cb.get_state("chaos_svc2") == CircuitState.OPEN

    await asyncio.sleep(0.1)  # 超过 recovery_timeout → 转 HALF_OPEN
    assert cb.get_state("chaos_svc2") == CircuitState.HALF_OPEN

    result = await cb.call("chaos_svc2", ok)
    assert result == "ok"
    assert cb.get_state("chaos_svc2") == CircuitState.CLOSED
    cb.reset("chaos_svc2")


async def test_circuit_breaker_rate_limit_skips_failure():
    """限流错误 (is_rate_limit=True) 不计入失败计数，不触发熔断。"""
    cb = get_circuit_breaker(max_failures=2, recovery_timeout=100)

    for _ in range(5):
        cb.record_failure("chaos_rl", is_rate_limit=True)

    assert cb.get_state("chaos_rl") == CircuitState.CLOSED
    cb.reset("chaos_rl")


async def test_circuit_breaker_prometheus_state_transition():
    """熔断状态变化应反映到 Prometheus 指标（state=2 表示 OPEN）。"""
    cb = get_circuit_breaker(max_failures=1, recovery_timeout=100)
    from backend.core.metrics import CIRCUIT_BREAKER_STATE

    async def boom():
        raise RuntimeError("x")

    with pytest.raises(RuntimeError):
        await cb.call("chaos_metrics", boom)

    # OPEN=2, CLOSED=0, HALF_OPEN=1
    assert CIRCUIT_BREAKER_STATE.labels(service="chaos_metrics")._value.get() == 2
    cb.reset("chaos_metrics")


# ─────────────────────────────────────────────────────────────
# B. LLM Ollama 降级混沌
# ─────────────────────────────────────────────────────────────
@pytest.fixture
def llm_router():
    return LLMRouter(
        api_key="sk-test",
        fallback_enabled=True,
        fallback_threshold=2,
        ollama_base_url="http://localhost:11434/v1",
    )


def _fake_openai_client(raise_times: int):
    """构造一个假的 AsyncOpenAI client：前 raise_times 次 create 抛错，之后成功。"""
    state = {"calls": 0, "raised": raise_times}
    client = MagicMock()

    async def create(*args, **kwargs):
        state["calls"] += 1
        if state["calls"] <= state["raised"]:
            raise RuntimeError("primary down")
        return MagicMock(
            choices=[MagicMock(message=MagicMock(content='{"x": 1}'))],
            usage=MagicMock(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        )

    client.chat.completions.create = create
    return client


async def test_llm_fallback_to_ollama_on_repeated_failure(llm_router, monkeypatch):
    """主供应商连续失败达阈值 → 降级 Ollama（get_client 返回 Ollama client），且 is_fallback_active=True。

    前置：Ollama 可达（mock 探测），否则按 3402622 加固逻辑不会降级到死路。
    """
    primary = _fake_openai_client(raise_times=3)
    ollama = MagicMock()

    monkeypatch.setattr(llm_router, "_get_primary_client", lambda: primary)
    monkeypatch.setattr(llm_router, "_get_ollama_client", lambda: ollama)
    monkeypatch.setattr(llm_router, "_probe_ollama_sync", lambda: True)

    assert llm_router.is_fallback_active is False

    # 前两次失败触发降级（threshold=2）
    for _ in range(2):
        llm_router.record_failure(ModelTier.STANDARD)
    assert llm_router.is_fallback_active is True

    # 降级后 get_client 返回 Ollama client
    assert llm_router.get_client(ModelTier.STANDARD) is ollama

    # 主供应商恢复 → 切回
    llm_router.record_success(ModelTier.STANDARD)
    assert llm_router.is_fallback_active is False
    assert llm_router.get_client(ModelTier.STANDARD) is primary


async def test_llm_fallback_skipped_when_ollama_unreachable(llm_router, monkeypatch):
    """加固逻辑（3402622）：主供应商连续失败但 Ollama 不可达 → 不降级，维持主链路，防降级到死路死锁。"""
    primary = _fake_openai_client(raise_times=3)
    monkeypatch.setattr(llm_router, "_get_primary_client", lambda: primary)
    # 模拟 Ollama 不可达环境（CI / 无本地 Ollama）
    monkeypatch.setattr(llm_router, "_probe_ollama_sync", lambda: False)

    assert llm_router.is_fallback_active is False
    for _ in range(2):
        llm_router.record_failure(ModelTier.STANDARD)
    # 不降级，继续保持主链路
    assert llm_router.is_fallback_active is False
    assert llm_router.get_client(ModelTier.STANDARD) is primary


async def test_llm_fallback_threshold_not_reached(llm_router):
    """失败次数未达阈值 → 不降级。"""
    llm_router.record_failure(ModelTier.STANDARD)
    assert llm_router.is_fallback_active is False


async def test_llm_fallback_disabled(llm_router, monkeypatch):
    """fallback 关闭时，即使连续失败也不降级。"""
    llm_router.fallback_enabled = False
    for _ in range(5):
        llm_router.record_failure(ModelTier.STANDARD)
    assert llm_router.is_fallback_active is False


# ─────────────────────────────────────────────────────────────
# C. DataSourceRouter 节点熔断 + failover 混沌
# ─────────────────────────────────────────────────────────────
def _make_router_with_nodes():
    router = DataSourceRouter()
    router._enabled = True
    router._nodes = {
        "yf_a": DataSourceNode(
            name="yf_a",
            url="http://a:8001",
            enabled=True,
            capabilities=["yfinance"],
            weight=10,
            status="healthy",
        ),
        "yf_b": DataSourceNode(
            name="yf_b",
            url="http://b:8001",
            enabled=True,
            capabilities=["yfinance"],
            weight=5,
            status="healthy",
        ),
    }
    return router


async def test_router_failover_on_node_failure(monkeypatch):
    """主节点 yf_a 连续失败 → unhealthy + 熔断冷却；_select_node 自动选 yf_b。"""
    router = _make_router_with_nodes()

    # 注入 _send_request：yf_a 返回普通错误（NORMAL），yf_b 成功
    async def fake_send(node, source, payload):
        if node.name == "yf_a":
            return {"status": "error", "error_category": ErrorCategory.NORMAL.value, "message": "node a down"}
        return {"status": "success", "data": {"ok": True}}

    monkeypatch.setattr(router, "_send_request", fake_send)

    # yf_a 连续失败 3 次（router 内部 _update_node_status 触发 unhealthy + 熔断）
    for _ in range(3):
        await router._update_node_status("yf_a", success=False, error="down", error_category=ErrorCategory.NORMAL)

    a = router._nodes["yf_a"]
    assert a.status == "unhealthy"
    assert a.circuit_breaker_until > 0.0

    # 现在 _select_node 应跳过 yf_a，选中 yf_b
    selected = await router._select_node("yfinance")
    assert selected is not None
    assert selected.name == "yf_b"


async def test_router_rate_limit_does_not_trip_breaker(monkeypatch):
    """限流类错误只 failover 不计数熔断：yf_a 限流后仍 healthy。"""
    router = _make_router_with_nodes()

    for _ in range(10):
        await router._update_node_status(
            "yf_a", success=False, error="ratelimit", error_category=ErrorCategory.RATE_LIMIT
        )

    a = router._nodes["yf_a"]
    assert a.status == "healthy"
    assert a.circuit_breaker_until == 0.0
    assert a.error_count == 0


async def test_router_no_local_fallback_on_total_outage(monkeypatch):
    """全节点失联 → fetch_yfinance 返回失败消息，且无本地兜底（架构红线）。"""
    router = _make_router_with_nodes()

    async def fake_send(node, source, payload):
        return {"status": "error", "error_category": ErrorCategory.NORMAL.value, "message": f"{node.name} dead"}

    monkeypatch.setattr(router, "_send_request", fake_send)

    # 让两节点都 unhealthy
    for name in ("yf_a", "yf_b"):
        for _ in range(3):
            await router._update_node_status(name, success=False, error="dead", error_category=ErrorCategory.NORMAL)

    result = await router.fetch_yfinance("AAPL", "quote")
    assert result["success"] is False
    assert "local yfinance disabled" in result["message"]
    # 红线：不静默降级本地，结果不含任何真实行情字段
    assert "open" not in result and "close" not in result


# ─────────────────────────────────────────────────────────────
# D. 端到端降级编排：Futu 全失联
# ─────────────────────────────────────────────────────────────
async def test_futu_total_outage_no_local_fallback(monkeypatch):
    """Futu 远程节点全失联 → fetch_futu 返回错误且禁用本地兜底。"""
    router = DataSourceRouter()
    router._enabled = True
    router._nodes = {
        "futu_master": DataSourceNode(
            name="futu_master",
            url="http://futu:8001",
            enabled=True,
            capabilities=["futu"],
            weight=10,
            status="healthy",
        ),
    }

    async def fake_send(node, source, payload):
        return {"status": "error", "error_category": ErrorCategory.NORMAL.value, "message": "futu node dead"}

    monkeypatch.setattr(router, "_send_request", fake_send)

    for _ in range(3):
        await router._update_node_status(
            "futu_master", success=False, error="dead", error_category=ErrorCategory.NORMAL
        )

    result = await router.fetch_futu("quote", symbol="HK.00700")
    assert result["status"] == "error"
    # 3 次无 action 失败累计 = 整节点熔断（进程级故障）。消息须明确点出「节点级」，
    # 不再伪装成含糊的 "local SDK disabled"，以便与单 action 冷却区分开。
    assert "节点熔断中" in result["message"]


# ─────────────────────────────────────────────────────────────
# E. 熔断 + 降级联动：主服务熔断时 LLM 降级与数据源熔断并行不互相拖累
# ─────────────────────────────────────────────────────────────
async def test_parallel_circuit_breaker_isolation():
    """两个独立服务的熔断器互不干扰（状态隔离）。"""
    cb = get_circuit_breaker(max_failures=1, recovery_timeout=100)

    async def boom():
        raise RuntimeError("x")

    async def ok():
        return "ok"

    with pytest.raises(RuntimeError):
        await cb.call("svc_alpha", boom)
    assert cb.get_state("svc_alpha") == CircuitState.OPEN

    # svc_beta 仍应正常
    assert await cb.call("svc_beta", ok) == "ok"
    assert cb.get_state("svc_beta") == CircuitState.CLOSED

    cb.reset("svc_alpha")
    cb.reset("svc_beta")
