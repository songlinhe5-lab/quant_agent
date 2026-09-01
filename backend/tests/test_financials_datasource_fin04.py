"""
FIN-04: filings 数据源链路（Router 代理 / 薄适配器 / Facade 实体解析）— 单元测试
==============================================================================

主服务禁止直连 SEC（AGENTS §2）：一手申报只能经
``data_source_router.fetch_filings()`` → HTTP+HMAC → data_subservice。
本测试锁三件事：
  1. fetch_filings 的门控顺序：离线 stub → 节点可用性 → 发请求，且限流不计入熔断
  2. FilingsDataSource 把 dict 响应语义化成 Result（限流类必须带 RATE_LIMITED，
     否则会被误当普通失败重试并污染熔断计数）
  3. Facade 的 ticker → CIK 解析：24h 进程缓存、拉不到时的降级路径，禁止猜 CIK
"""

from __future__ import annotations

import os
from datetime import date
from unittest.mock import AsyncMock, patch

import pytest

from backend.services.datasource import ErrorCategory, ErrorInfo, Result, ResultStatus
from backend.services.datasource.adapters import filings as filings_adapter_module
from backend.services.datasource.adapters.filings import FilingsDataSource, ensure_filings_registered
from backend.services.datasource.business import fundamental as fundamental_module
from backend.services.datasource.router import DataSourceNode, DataSourceRouter
from backend.services.datasource.source_registry import datasource_registry
from backend.services.financials.service import FinancialsError

ENTITY = "US:CIK0000320193"


# ─────────────────────────────────────────
#  1. Router 代理：门控与节点状态
# ─────────────────────────────────────────


@pytest.fixture
def router(monkeypatch):
    """独立 DataSourceRouter 实例：不污染全局单例，也不碰 httpx。"""
    with patch.dict(os.environ, {"DATA_SOURCE_ROUTER_ENABLED": "false"}):
        instance = DataSourceRouter()
    instance._enabled = True
    instance._nodes["filings_master"] = DataSourceNode(
        name="filings_master",
        url="http://filings:8000",
        capabilities=["filings", "COMPANY_FACTS", "SUBMISSIONS"],
    )
    instance._update_node_status = AsyncMock()
    monkeypatch.setattr("backend.services.datasource.router.is_offline_mode_enabled", lambda: False)
    return instance


async def test_fetch_filings_rolls_up_params_and_uppercases_action(router):
    router._send_request = AsyncMock(return_value={"status": "success", "data": {"facts": {}}})
    resp = await router.fetch_filings("company_facts", entity_id=ENTITY)

    assert resp["status"] == "success"
    node, source, payload = router._send_request.await_args.args
    assert (node.name, source) == ("filings_master", "filings")
    assert payload == {"source": "filings", "action": "COMPANY_FACTS", "params": {"entity_id": ENTITY}}
    call = router._update_node_status.await_args
    assert call.args == ("filings_master",) and call.kwargs["success"] is True


async def test_offline_mode_never_touches_sec_node(router, monkeypatch):
    """离线开关必须在最前面短路：SEC ≤10 req/s，测试跑一次不该消耗真实配额。"""
    monkeypatch.setattr("backend.services.datasource.router.is_offline_mode_enabled", lambda: True)
    router._send_request = AsyncMock()
    resp = await router.fetch_filings("COMPANY_FACTS", entity_id=ENTITY)

    router._send_request.assert_not_awaited()
    assert resp["offline_stub"] is True and resp["action"] == "COMPANY_FACTS"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda r: r._nodes.pop("filings_master"),  # 未配节点
        lambda r: setattr(r, "_enabled", False),  # 路由整体关闭
        lambda r: (
            setattr(r._nodes["filings_master"], "status", "unhealthy")
            or setattr(r._nodes["filings_master"], "circuit_breaker_until", 9e18)
        ),  # 熔断冷却中
    ],
    ids=["no-node", "router-disabled", "breaker-cooling"],
)
async def test_unusable_node_fails_fast_without_request(router, mutate):
    mutate(router)
    router._send_request = AsyncMock()
    resp = await router.fetch_filings("SUBMISSIONS", entity_id=ENTITY)

    router._send_request.assert_not_awaited()
    assert resp["status"] == "error" and "No healthy Filings remote node" in resp["message"]


async def test_action_level_breaker_only_blocks_that_action(router):
    """COMPANY_FACTS 被单独熔断时，SUBMISSIONS 仍须放行（BE-ARCH-08i）。"""
    node = router._nodes["filings_master"]
    node.action_breaker_until = {"COMPANY_FACTS": 9e18}
    router._send_request = AsyncMock(return_value={"status": "success", "data": {}})

    blocked = await router.fetch_filings("COMPANY_FACTS", entity_id=ENTITY)
    assert blocked["status"] == "error" and router._send_request.await_count == 0

    allowed = await router.fetch_filings("SUBMISSIONS", entity_id=ENTITY)
    assert allowed["status"] == "success"


async def test_error_category_is_forwarded_to_node_status(router):
    router._send_request = AsyncMock(
        return_value={"status": "error", "message": "SEC 429", "error_category": "rate_limit"}
    )
    resp = await router.fetch_filings("COMPANY_FACTS", entity_id=ENTITY)

    assert resp["status"] == "error"
    kwargs = router._update_node_status.await_args.kwargs
    assert kwargs["success"] is False and kwargs["error_category"] is ErrorCategory.RATE_LIMIT


async def test_unknown_error_category_falls_back_to_normal(router):
    router._send_request = AsyncMock(return_value={"status": "error", "message": "怪东西", "error_category": "weird"})
    await router.fetch_filings("COMPANY_FACTS", entity_id=ENTITY)
    assert router._update_node_status.await_args.kwargs["error_category"] is ErrorCategory.NORMAL


async def test_transport_exception_records_failure(router):
    router._send_request = AsyncMock(side_effect=RuntimeError("HMAC 401"))
    resp = await router.fetch_filings("COMPANY_FACTS", entity_id=ENTITY)

    assert resp["status"] == "error" and "COMPANY_FACTS" in resp["message"]
    assert "HMAC 401" in router._update_node_status.await_args.kwargs["error"]


async def test_record_breaker_flag_is_consumed_not_sent(router):
    """_record_breaker 是主服务内部开关，绝不能混进 params 发给子服务。"""
    router._send_request = AsyncMock(return_value={"status": "success", "data": {}})
    await router.fetch_filings("COMPANY_FACTS", entity_id=ENTITY, _record_breaker=False)

    payload = router._send_request.await_args.args[2]
    assert "_record_breaker" not in payload["params"]
    assert router._update_node_status.await_args.kwargs["record_breaker"] is False


# ─────────────────────────────────────────
#  2. 薄适配器：dict → Result 语义化
# ─────────────────────────────────────────


@pytest.fixture
def adapter(monkeypatch):
    from backend.services.datasource.router import data_source_router

    mock = AsyncMock()
    monkeypatch.setattr(data_source_router, "fetch_filings", mock)
    return FilingsDataSource(), mock


async def test_unsupported_action_never_reaches_router(adapter):
    source, mock = adapter
    result = await source.fetch("QUOTE", {})

    assert result.status is ResultStatus.ERROR
    assert (result.error.code, result.error.retryable) == ("UNSUPPORTED_ACTION", False)
    mock.assert_not_awaited()


async def test_success_result_marks_self_recorded(adapter):
    """router 已记过 throttler，registry 不能再记一次（双记会扭曲限流统计）。"""
    source, mock = adapter
    mock.return_value = {"status": "success", "data": {"cik": "320193"}}
    result = await source.fetch("SUBMISSIONS", {"entity_id": ENTITY})

    assert result.status is ResultStatus.SUCCESS and result.data == {"cik": "320193"}
    assert result.source == "filings" and result.self_recorded is True
    assert mock.await_args.args == ("submissions",)  # 传给 router 的是小写 action


@pytest.mark.parametrize(
    "resp,expected_status,expected_code,expected_category",
    [
        (
            {"message": "HTTP 429 Too Many Requests"},
            ResultStatus.RATE_LIMITED,
            "RATE_LIMITED",
            ErrorCategory.RATE_LIMIT,
        ),
        ({"message": "SEC 限流，退避中"}, ResultStatus.RATE_LIMITED, "RATE_LIMITED", ErrorCategory.RATE_LIMIT),
        (
            {"message": "IP 封禁", "error_category": "ip_blocked"},
            ResultStatus.RATE_LIMITED,
            "IP_BLOCKED",
            ErrorCategory.IP_BLOCKED,
        ),
        (
            {"message": "配额耗尽", "error_category": "quota_exhausted"},
            ResultStatus.RATE_LIMITED,
            "QUOTA_EXHAUSTED",
            ErrorCategory.QUOTA_EXHAUSTED,
        ),
        (
            {"message": "502 网关", "error_category": "normal"},
            ResultStatus.ERROR,
            "FILINGS_FETCH_FAILED",
            ErrorCategory.NORMAL,
        ),
    ],
)
async def test_failure_semantics(adapter, resp, expected_status, expected_code, expected_category):
    source, mock = adapter
    mock.return_value = {"status": "error", **resp}
    result = await source.fetch("COMPANY_FACTS", {"entity_id": ENTITY})

    assert (result.status, result.error.code, result.error.category) == (
        expected_status,
        expected_code,
        expected_category,
    )
    assert result.error.retryable is True
    # 限流类自己记过数 → registry 跳过；普通错误交回 registry 计入熔断
    assert result.self_recorded is (expected_status is ResultStatus.RATE_LIMITED)


async def test_garbage_response_degrades_to_error_without_crashing(adapter):
    source, mock = adapter
    mock.return_value = ["不是字典"]
    result = await source.fetch("SYMBOLS", {})
    assert result.status is ResultStatus.ERROR and result.error.code == "FILINGS_FETCH_FAILED"


async def test_router_exception_is_contained(adapter):
    source, mock = adapter
    mock.side_effect = RuntimeError("节点炸了")
    result = await source.fetch("COMPANY_FACTS", {"entity_id": ENTITY})
    assert (result.status, result.error.code, result.error.retryable) == (
        ResultStatus.ERROR,
        "FILINGS_ROUTER_ERROR",
        True,
    )


def test_capabilities_declare_every_filings_action():
    declared = {c.upper() for c in FilingsDataSource().capabilities}
    assert {"SYMBOLS", "SUBMISSIONS", "COMPANY_FACTS", "FRAMES", "HKEX_FILINGS", "CNINFO_FILINGS"} <= declared


# ─────────────────────────────────────────
#  3. 健康度与注册
# ─────────────────────────────────────────


def _node(status="healthy", error_count=0):
    return DataSourceNode(
        name="filings_master",
        url="http://filings:8000",
        status=status,
        error_count=error_count,
        capabilities=["filings"],
    )


async def test_health_reports_missing_node_as_unhealthy(monkeypatch):
    source = FilingsDataSource()
    monkeypatch.setattr(FilingsDataSource, "_get_filings_node", lambda self: None)
    info = await source.health()
    assert info.healthy is False and info.connected is False
    assert "filings_master" in info.last_error and info.stats["capabilities"] == source.capabilities
    assert source.is_available() is False


async def test_health_follows_node_status(monkeypatch):
    source = FilingsDataSource()
    monkeypatch.setattr(FilingsDataSource, "_get_filings_node", lambda self: _node(error_count=2))
    info = await source.health()
    assert info.healthy is True and info.stats["node_url"] == "http://filings:8000"
    assert info.last_error == "error_count=2"  # 健康但有错误累积 → 必须可见

    monkeypatch.setattr(FilingsDataSource, "_get_filings_node", lambda self: _node(status="unhealthy"))
    assert (await source.health()).healthy is False


def test_ensure_filings_registered_is_idempotent():
    was_registered = datasource_registry.has("filings")
    try:
        assert ensure_filings_registered() == "filings-default"
        assert ensure_filings_registered() == "filings-default"  # 第二次走幂等分支
        assert datasource_registry.get("filings", "SYMBOLS") is not None
    finally:
        if not was_registered:
            datasource_registry.unregister("filings")


# ─────────────────────────────────────────
#  4. Facade：实体解析与对照表缓存
# ─────────────────────────────────────────


class FakeRegistry:
    def __init__(self, results):
        self.results = results if isinstance(results, list) else [results]
        self.calls: list[tuple[str, str, dict]] = []

    async def fetch(self, source_name, action, params):
        self.calls.append((source_name, action, params))
        item = self.results[min(len(self.calls) - 1, len(self.results) - 1)]
        if isinstance(item, Exception):
            raise item
        return item


def _symbols_result():
    return Result.make_success(
        {
            "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
            "1": {"cik_str": 1018724, "ticker": "AMZN"},
        },
        source="filings",
    )


def _symbols_unavailable():
    return Result.make_error(ErrorInfo.normal("FILINGS_FETCH_FAILED", "SEC 对照表不可用"), source="filings")


@pytest.fixture
def registry(monkeypatch):
    """隔离进程缓存 + 桩掉注册表（连 ensure_registered 一起挡住，避免污染全局）。"""
    fundamental_module.reset_symbols_cache()
    monkeypatch.setattr(filings_adapter_module, "ensure_filings_registered", lambda service=None: "filings-default")

    def use(fake: FakeRegistry):
        monkeypatch.setattr(datasource_registry, "fetch", fake.fetch)
        return fake

    yield use
    fundamental_module.reset_symbols_cache()


async def test_resolve_entity_accepts_dash_form_without_querying_symbols(registry):
    fake = registry(FakeRegistry(AssertionError("已带市场前缀不该再拉对照表")))
    assert await fundamental_module.resolve_entity("US-CIK0000320193") == ENTITY
    assert await fundamental_module.resolve_entity("hk-700") == "HK:00700"
    assert await fundamental_module.resolve_entity("600519") == "CN:600519"
    assert fake.calls == []


async def test_resolve_ticker_uses_edgar_mapping_and_caches(registry):
    fake = registry(FakeRegistry(_symbols_result()))
    assert await fundamental_module.resolve_entity("aapl") == ENTITY
    assert await fundamental_module.resolve_entity("AAPL") == ENTITY

    assert fake.calls == [("filings", "SYMBOLS", {})]  # 第二次命中进程缓存，不回源
    assert await fundamental_module.load_symbol_to_cik() == {"AAPL": "0000320193", "AMZN": "0001018724"}


async def test_force_reload_bypasses_cache(registry):
    fake = registry(FakeRegistry([_symbols_result(), _symbols_result()]))
    await fundamental_module.load_symbol_to_cik()
    await fundamental_module.load_symbol_to_cik(force_reload=True)
    assert len(fake.calls) == 2


async def test_symbols_payload_skips_malformed_rows(registry):
    registry(
        FakeRegistry(
            Result.make_success(
                {
                    "0": {"cik_str": 320193, "ticker": "AAPL"},
                    "1": {"title": "没有 ticker"},
                    "2": {"ticker": "BRK", "cik_str": None},
                    "3": "脏行",
                },
                source="filings",
            )
        )
    )
    assert await fundamental_module.load_symbol_to_cik() == {"AAPL": "0000320193"}


async def test_unknown_ticker_is_explicit_404_not_a_guess(registry):
    registry(FakeRegistry(_symbols_result()))
    with pytest.raises(FinancialsError) as exc:
        await fundamental_module.resolve_entity("NVDA")
    assert (exc.value.code, exc.value.status_code) == ("fin_entity_not_found", 404)


@pytest.mark.parametrize("broken", [_symbols_unavailable(), RuntimeError("注册表炸了")])
async def test_symbols_outage_degrades_to_502_without_cache(registry, broken):
    registry(FakeRegistry(broken))
    with pytest.raises(FinancialsError) as exc:
        await fundamental_module.resolve_entity("AAPL")
    assert (exc.value.code, exc.value.status_code) == ("fin_source_degraded", 502)
    assert "US:CIK" in exc.value.message  # 给出可用的替代写法，不让用户卡死


async def test_stale_cache_wins_over_hard_failure(registry):
    """已经拉到的表比「新鲜度」重要：回源失败时用旧缓存，别让整条读路径挂掉。"""
    fake = registry(FakeRegistry(_symbols_result()))
    await fundamental_module.load_symbol_to_cik()

    fake.results = [RuntimeError("节点不可用")]
    fake.calls.clear()
    assert (await fundamental_module.load_symbol_to_cik(force_reload=True))["AAPL"] == "0000320193"
    assert fake.calls == [("filings", "SYMBOLS", {})]  # 确实回源过，不是撞缓存偷跑


# ─────────────────────────────────────
#  5. Facade 与 Service / 会话的接线
# ─────────────────────────────────────


class FakeSession:
    """一个会话 = 一次 `__aenter__`，用来数 Facade 到底开了几个会话。"""

    def __init__(self, opened: list):
        self.opened = opened

    async def __aenter__(self):
        self.opened.append(True)
        return self

    async def __aexit__(self, *_exc):
        return False


class StubFinancials:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    async def get_statements(self, session, **kwargs):
        self.calls.append(("get_statements", kwargs))
        return {"statement": "income", "rows": []}

    async def get_facts(self, session, **kwargs):
        self.calls.append(("get_facts", kwargs))
        return {"items": []}

    async def get_filings(self, session, **kwargs):
        self.calls.append(("get_filings", kwargs))
        return {"items": []}

    async def get_restatements(self, session, **kwargs):
        self.calls.append(("get_restatements", kwargs))
        return {"items": []}

    async def backfill(self, session, **kwargs):
        self.calls.append(("backfill", kwargs))
        return {"facts_written": 6, "job_id": "job-sync"}

    def schedule_backfill(self, session_factory, **kwargs):
        self.calls.append(("schedule_backfill", {"factory": session_factory, **kwargs}))
        return "job-1"


@pytest.fixture
def facade():
    opened: list = []
    financials = StubFinancials()
    service = fundamental_module.FundamentalDataService(
        facade=object(), financials=financials, session_factory=lambda: FakeSession(opened)
    )
    return service, financials, opened


async def test_read_paths_open_exactly_one_session_and_pass_parsed_params(facade):
    service, financials, opened = facade
    view = await service.get_statements("US-CIK0000320193", statement="balance", as_of="2025-06-30", limit=50)

    assert view["statement"] == "income" and opened == [True]  # 一个请求一个会话
    name, kwargs = financials.calls[0]
    assert name == "get_statements" and kwargs["entity_id"] == ENTITY
    assert kwargs["as_of"] == date(2025, 6, 30)  # 日期在 Facade 就解析成 date，Service 不再猜格式
    assert kwargs["statement"] == "balance" and kwargs["limit"] == 50


async def test_each_read_facade_delegates(facade):
    service, financials, opened = facade
    await service.get_facts("US-CIK0000320193", concept="revenue", as_of="2025-06-30")
    await service.get_filings("US:CIK0000320193", limit=20)
    await service.get_restatements("US:CIK0000320193")

    assert [c[0] for c in financials.calls] == ["get_facts", "get_filings", "get_restatements"]
    assert opened == [True, True, True]
    assert financials.calls[0][1]["concept"] == "revenue" and financials.calls[0][1]["as_of"] == date(2025, 6, 30)


async def test_service_error_propagates_after_session_close(facade):
    service, financials, opened = facade

    async def boom(_session, **_kwargs):
        raise FinancialsError("fin_no_xbrl_coverage", "无 XBRL", status_code=404)

    financials.get_filings = boom
    with pytest.raises(FinancialsError) as exc:
        await service.get_filings("US:CIK0000320193")
    assert exc.value.code == "fin_no_xbrl_coverage" and opened == [True]


async def test_backfill_background_hands_session_factory_to_job(facade):
    """后台路径不得替任务开会话：请求返回即关闭，会把回填拦腰折断。"""
    service, financials, opened = facade
    result = await service.backfill("US-CIK0000320193")

    assert result == {"job_id": "job-1", "entity_id": ENTITY, "status": "pending"}
    assert opened == []
    name, kwargs = financials.calls[0]
    assert name == "schedule_backfill" and kwargs["source"] == "sec"
    async with kwargs["factory"]():  # 会话工厂交给后台，由它自己 `async with`
        assert opened == [True]


async def test_backfill_synchronous_path_uses_request_session(facade):
    service, financials, opened = facade
    result = await service.backfill("US-CIK0000320193", background=False)

    assert result["facts_written"] == 6 and opened == [True]
    assert financials.calls[0][1]["entity_id"] == ENTITY


async def test_legacy_fundamental_facade_still_validates_ticker(facade):
    service, _financials, _opened = facade
    with pytest.raises(ValueError, match="不能为空"):
        await service.get_fundamental("   ")
