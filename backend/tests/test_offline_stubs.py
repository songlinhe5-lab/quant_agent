"""
SVC-06: 三方服务 Mock/Stub 离线化 单元测试。

验证：
1. LLM 离线 stub：QUANT_ENV=testing 下 LLMService.generate / generate_pydantic
   返回确定性内容（不触网），且 generate_pydantic 构造的 JSON 能通过 pydantic 校验。
2. LLM 离线 stub 与 SVC-05 token 计量联动：generate 后 TokenUsageStore 记录到 token。
3. 离线开关判定：testing/dev/offline → 启用；production + OFFLINE_MODE=0 → 关闭。
4. DataSourceRouter 离线短路：fetch_* 直接返回确定性 stub，不触网、不依赖 enabled/节点健康。
5. live_network 标记：默认跳过需真实网络的集成测试（离线友好）。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import BaseModel

from backend.services.ai_narrator.llm_service import LLMService
from backend.services.ai_narrator.llm_stub import (
    LLMStubProvider,
    is_offline_llm_enabled,
)
from backend.services.datasource.offline_stub import (
    build_offline_response,
    is_offline_mode_enabled,
)


# ── 离线开关判定 ────────────────────────────────────────
def test_llm_offline_enabled_under_testing(monkeypatch):
    monkeypatch.setenv("QUANT_ENV", "testing")
    assert is_offline_llm_enabled() is True


def test_llm_offline_disabled_in_production(monkeypatch):
    monkeypatch.setenv("QUANT_ENV", "production")
    monkeypatch.setenv("LLM_STUB", "0")
    assert is_offline_llm_enabled() is False


def test_offline_mode_enabled_under_offline_env(monkeypatch):
    monkeypatch.setenv("QUANT_ENV", "offline")
    assert is_offline_mode_enabled() is True


def test_offline_mode_disabled_in_dev_not_auto(monkeypatch):
    # dev 不自动启用 router stub（避免破坏既有 router 集成测试）
    monkeypatch.setenv("QUANT_ENV", "dev")
    monkeypatch.setenv("OFFLINE_MODE", "0")
    assert is_offline_mode_enabled() is False


def test_offline_mode_disabled_in_prod(monkeypatch):
    monkeypatch.setenv("QUANT_ENV", "production")
    monkeypatch.setenv("OFFLINE_MODE", "0")
    assert is_offline_mode_enabled() is False


def test_offline_mode_explicit_flag(monkeypatch):
    monkeypatch.setenv("QUANT_ENV", "production")
    monkeypatch.setenv("OFFLINE_MODE", "1")
    assert is_offline_mode_enabled() is True


# ── LLM 离线 stub 行为 ──────────────────────────────────
@pytest.fixture
def offline_llm(monkeypatch):
    monkeypatch.setenv("QUANT_ENV", "testing")
    svc = LLMService()
    yield svc


async def test_llm_generate_offline_returns_deterministic_text(offline_llm):
    out = await offline_llm.generate("测试 prompt", tier=None)
    assert isinstance(out, str)
    assert "离线stub" in out
    assert "测试 prompt"[:10] in out


class _SampleModel(BaseModel):
    symbol: str = "STUB"
    score: float = 0.5
    note: str = "default"


async def test_llm_generate_pydantic_offline_returns_valid_instance(offline_llm):
    result = await offline_llm.generate_pydantic("分析 AAPL", response_model=_SampleModel, tier=None)
    assert isinstance(result, _SampleModel)
    assert result.symbol == "STUB"
    assert result.score == 0.5


async def test_llm_offline_records_token_usage(offline_llm, monkeypatch):
    """SVC-06 + SVC-05 联动：离线 stub 走真实 _record_token_usage，token 被计量。"""
    import backend.services.ai_narrator.token_usage_store as tus

    fake_redis = MagicMock()
    fake_redis.hgetall = AsyncMock(side_effect=RuntimeError("no redis"))
    pipe = MagicMock()
    pipe.hincrby = MagicMock()
    pipe.expire = MagicMock()
    pipe.execute = AsyncMock(side_effect=RuntimeError("no redis"))
    fake_redis.pipeline = MagicMock(return_value=pipe)
    monkeypatch.setattr(tus, "redis_client", fake_redis)

    from backend.services.ai_narrator.token_usage_store import token_usage_store

    token_usage_store.reset()
    await offline_llm.generate("计量测试 prompt", tier=None)

    today = await token_usage_store.get_today()
    assert today["total_tokens"] > 0, "离线 stub 应触发 SVC-05 token 计量"
    assert today["calls"] == 1


def test_llm_stub_provider_modes():
    provider = LLMStubProvider(default_prompt_tokens=10, default_completion_tokens=5)
    t = provider.make_text_response("hi")
    assert t.usage.total_tokens == 15
    assert t.choices[0].message.content == "hi"

    class M(BaseModel):
        x: int = 1

    j = provider.make_json_response(M)
    assert "x" in j.choices[0].message.content


# ── DataSourceRouter 离线短路 ───────────────────────────
async def test_router_offline_shortcircuit_all_sources(monkeypatch):
    """OFFLINE_MODE=1 时，所有 fetch_* 直接返回 stub，不触网、不依赖 enabled/节点。"""
    monkeypatch.setenv("OFFLINE_MODE", "1")

    from backend.services.datasource.router import DataSourceRouter

    router = DataSourceRouter()  # 默认 enabled=False（环境变量未设），验证 stub 仍生效
    router._nodes = {}  # 无健康节点，验证不依赖节点

    cases = [
        ("yfinance", await router.fetch_yfinance("AAPL", "quote")),
        ("akshare", await router.fetch_akshare("stock_zh_a_spot")),
        ("tushare", await router.fetch_tushare("daily")),
        ("futu", await router.fetch_futu("quote", symbol="HK.00700")),
        ("fmp", await router.fetch_fmp("quote")),
        ("finnhub", await router.fetch_finnhub("quote", symbol="AAPL")),
        ("fred", await router.fetch_fred("series", series_id="DGS10")),
        ("dbnomics", await router.fetch_dbnomics("series")),
        ("rbi", await router.fetch_rbi("repo_rate")),
        ("search", await router.fetch_search("tavily", query="test")),
    ]
    for source, resp in cases:
        assert resp.get("offline_stub") is True, f"{source} 应返回离线 stub"
        assert resp.get("success") is True or resp.get("status") == "ok", f"{source} stub 应成功"


def test_build_offline_response_unknown_source():
    resp = build_offline_response("unknown_src", "act")
    assert resp["offline_stub"] is True
    assert resp["data"] == []


# ── live_network 标记 ───────────────────────────────────
@pytest.mark.live_network
def test_live_network_example_is_skipped_by_default():
    """示例：需真实网络的集成测试，默认应被 skip（离线友好）。"""
    pytest.skip("live network required")
