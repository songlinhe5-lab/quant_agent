"""
FIN-04: 财报看板 API（routers/financials.py）— 单元测试
======================================================

只验路由该管的事（AGENTS §4：路由只做校验与转发）：
  1. 入参校验：非法枚举 / 越界分页 / 非法 source 必须在进 Service 前被挡住
  2. 转发：Facade 收到的实体与口径参数
  3. 信封：成功 `{status,message,data,timestamp}`；错误另带 `error_code` 且状态码按 docs/28 §六 映射
  4. 注册：`backend.main` 里 8 条 `/api/v1/financials/...` 路径都在

只挂本路由到最小 FastAPI，禁打真实外网/PG。
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routers import financials as financials_router
from backend.services.financials import jobs
from backend.services.financials.service import FinancialsError

app = FastAPI()
app.include_router(financials_router.router, prefix="/api/v1")

ENTITY = "US:CIK0000320193"


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def _clean_jobs():
    jobs.reset_jobs()
    yield
    jobs.reset_jobs()


class FacadeStub:
    """记录调用参数，返回预置值或抛异常。"""

    def __init__(self, result=None, error: Exception | None = None):
        self.result = result if result is not None else {"ok": True}
        self.error = error
        self.calls: list[tuple[str, dict]] = []

    def _call(self, name: str, **kwargs):
        self.calls.append((name, kwargs))
        if self.error:
            raise self.error
        return self.result

    async def get_statements(self, entity, **kwargs):
        return self._call("get_statements", entity=entity, **kwargs)

    async def get_facts(self, entity, **kwargs):
        return self._call("get_facts", entity=entity, **kwargs)

    async def get_filings(self, entity, **kwargs):
        return self._call("get_filings", entity=entity, **kwargs)

    async def get_restatements(self, entity, **kwargs):
        return self._call("get_restatements", entity=entity, **kwargs)

    async def get_analytics(self, entity, **kwargs):
        return self._call("get_analytics", entity=entity, **kwargs)

    async def get_peers(self, entity, **kwargs):
        return self._call("get_peers", entity=entity, **kwargs)

    async def get_text_diff(self, entity, **kwargs):
        return self._call("get_text_diff", entity=entity, **kwargs)

    async def validate_extractions(self, items):
        return self._call("validate_extractions", items=items)

    async def backfill(self, entity, **kwargs):
        return self._call("backfill", entity=entity, **kwargs)

    async def get_coverage(self, entity, **kwargs):
        return self._call("get_coverage", entity=entity, **kwargs)

    def backfill_batch(self, entities, **kwargs):
        return self._call("backfill_batch", entities=entities, **kwargs)

    @property
    def kwargs(self) -> dict:
        return self.calls[-1][1]


@pytest.fixture
def stub(monkeypatch):
    facade = FacadeStub()
    monkeypatch.setattr(financials_router, "facade", facade)
    return facade


# ─────────────────────────────────────────
#  1. 读端点转发与信封
# ─────────────────────────────────────────


def test_statements_forwards_defaults(client, stub):
    resp = client.get(f"/api/v1/financials/statements/{ENTITY}")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"status", "message", "data", "timestamp"}
    assert body["status"] == "success" and body["data"] == {"ok": True}
    assert stub.calls == [
        ("get_statements", {"entity": ENTITY, "statement": "income", "basis": "latest", "as_of": None, "limit": 500})
    ]


def test_statements_forwards_explicit_pit_params(client, stub):
    resp = client.get(
        f"/api/v1/financials/statements/{ENTITY}",
        params={"statement": "balance", "basis": "as_reported", "as_of": "2025-06-30", "limit": 50},
    )
    assert resp.status_code == 200
    assert stub.kwargs["as_of"] == "2025-06-30"  # 路由不翻译日期，交给 Service（保持薄）
    assert stub.kwargs["basis"] == "as_reported" and stub.kwargs["statement"] == "balance"


def test_facts_filings_restatements_delegate(client, stub):
    assert client.get(f"/api/v1/financials/facts/{ENTITY}", params={"concept": "revenue"}).status_code == 200
    assert stub.kwargs["concept"] == "revenue" and stub.kwargs["as_of"] is None

    assert client.get(f"/api/v1/financials/filings/{ENTITY}", params={"limit": 20}).status_code == 200
    assert stub.calls[-1] == ("get_filings", {"entity": ENTITY, "limit": 20})

    assert client.get(f"/api/v1/financials/restatements/{ENTITY}").status_code == 200
    assert stub.calls[-1] == ("get_restatements", {"entity": ENTITY, "limit": 200})


# ─────────────────────────────────────────
#  2. 入参校验：非法值不得进 Service
# ─────────────────────────────────────────


@pytest.mark.parametrize(
    "path,params",
    [
        (f"/api/v1/financials/statements/{ENTITY}", {"basis": "truth"}),  # 枚举白名单
        (f"/api/v1/financials/statements/{ENTITY}", {"limit": 0}),  # 分页下界
        (f"/api/v1/financials/statements/{ENTITY}", {"limit": 5001}),  # 分页上界
        (f"/api/v1/financials/filings/{ENTITY}", {"limit": 501}),
        (f"/api/v1/financials/restatements/{ENTITY}", {"limit": 1001}),
    ],
)
def test_invalid_query_params_rejected_before_facade(client, stub, path, params):
    assert client.get(path, params=params).status_code == 422
    assert stub.calls == []


def test_backfill_rejects_unknown_source(client, stub):
    assert client.post("/api/v1/financials/backfill", json={"entity": "AAPL", "source": "hkex"}).status_code == 422
    assert client.post("/api/v1/financials/backfill", json={"entity": "  "}).status_code == 422
    assert stub.calls == []


# ─────────────────────────────────────────
#  3. 错误码 → HTTP 状态（docs/28 §六）
# ─────────────────────────────────────────


@pytest.mark.parametrize(
    "code,message,status",
    [
        ("fin_entity_not_found", "无法解析实体: NVDA", 404),
        ("fin_no_xbrl_coverage", "该主体无 XBRL 覆盖", 404),
        ("fin_bad_request", "statement 必须是 income / balance / cash", 400),
        ("fin_source_degraded", "SEC 限流，退避中", 429),
        ("fin_backfill_failed", "归一失败", 502),
    ],
)
def test_financials_error_maps_to_status_and_envelope(client, monkeypatch, code, message, status):
    monkeypatch.setattr(
        financials_router,
        "facade",
        FacadeStub(error=FinancialsError(code, message, status_code=status)),
    )
    resp = client.get(f"/api/v1/financials/statements/{ENTITY}")
    assert resp.status_code == status
    body = resp.json()
    assert body["status"] == "error" and body["error_code"] == code
    assert body["message"] == message and body["data"] is None
    assert "timestamp" in body


def test_unexpected_error_is_not_silently_swallowed(client, monkeypatch):
    """路由只吞 FinancialsError，其余交给框架（不许把 500 伪装成 200 空数据）。"""
    monkeypatch.setattr(financials_router, "facade", FacadeStub(error=RuntimeError("DB 连接池炸了")))
    assert client.get(f"/api/v1/financials/facts/{ENTITY}").status_code == 500


# ─────────────────────────────────────────
#  4. 回填：异步登记 + 任务查询
# ─────────────────────────────────────────


def test_backfill_returns_job_id_without_waiting(client, stub):
    stub.result = {"job_id": "job-1", "entity_id": ENTITY, "status": "pending"}
    resp = client.post("/api/v1/financials/backfill", json={"entity": "  aapl  "})
    assert resp.status_code == 200
    body = resp.json()
    assert body["message"] == "backfill scheduled"
    assert body["data"] == {"job_id": "job-1", "entity_id": ENTITY, "status": "pending"}
    assert stub.calls == [("backfill", {"entity": "aapl", "source": "sec"})]  # 首尾空白在校验层就剔掉


def test_backfill_error_keeps_envelope(client, monkeypatch):
    monkeypatch.setattr(
        financials_router,
        "facade",
        FacadeStub(error=FinancialsError("fin_source_degraded", "限流", status_code=429)),
    )
    resp = client.post("/api/v1/financials/backfill", json={"entity": "AAPL"})
    assert (resp.status_code, resp.json()["error_code"]) == (429, "fin_source_degraded")


def test_job_lookup_reads_registry(client):
    job_id = jobs.create_job(entity_id=ENTITY, source="sec")
    resp = client.get(f"/api/v1/financials/jobs/{job_id}")
    assert resp.status_code == 200
    assert resp.json()["data"]["job_id"] == job_id and resp.json()["data"]["status"] == "pending"


def test_unknown_job_is_404_with_job_code(client):
    """任务不存在 ≠ 实体不存在：错误码必须能区分，否则前端排障只能猜。"""
    resp = client.get("/api/v1/financials/jobs/nope")
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "fin_job_not_found"


# ─────────────────────────────────────────
#  5. 端点转发（analytics FIN-05 / peers FIN-06 均已交付，不再回 501）
# ─────────────────────────────────────────


def test_analytics_forwards_as_of_and_market_cap(client, stub):
    """FIN-05：分析端点转发 PIT 日期与行情侧市值（引擎禁止自估）。"""
    resp = client.get(f"/api/v1/financials/analytics/{ENTITY}", params={"as_of": "2026-06-30", "market_cap": 3000.0})
    assert resp.status_code == 200
    assert resp.json()["data"] == {"ok": True}
    name, kwargs = stub.calls[0]
    assert name == "get_analytics"
    assert kwargs["as_of"] == "2026-06-30" and kwargs["market_cap"] == 3000.0


def test_peers_forwards_concept_and_peer_set(client, stub):
    """FIN-06：同业端点转发截面科目与手工固定清单。"""
    resp = client.get(
        f"/api/v1/financials/peers/{ENTITY}", params={"concept": "total_assets", "peer_set": "aapl, msft"}
    )
    assert resp.status_code == 200
    name, kwargs = stub.calls[0]
    assert name == "get_peers"
    assert kwargs["concept"] == "total_assets" and kwargs["peer_set"] == "aapl, msft"


def test_text_diff_forwards_accession_pair(client, stub):
    """FIN-08：文本层端点转发指定年报对（缺省自动取最近两份 10-K）。"""
    resp = client.get(
        f"/api/v1/financials/text/diff/{ENTITY}", params={"accession_a": "accn-2024", "accession_b": "accn-2025"}
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"
    name, kwargs = stub.calls[0]
    assert name == "get_text_diff"
    assert kwargs["entity"] == ENTITY
    assert kwargs["accession_a"] == "accn-2024" and kwargs["accession_b"] == "accn-2025"


def test_text_extractions_forwards_dumped_items(client, stub):
    """FIN-08：定点抽取批量校验转发（model_dump 后逐项透传）。"""
    payload = {
        "items": [
            {"concept": "revenue", "value": 1200.0, "source_page": 12, "source_text": "营业额 1,200 百万"},
            {"concept": "debt", "value": 5.0},  # 缺溯源 → 由域层拒，路由不拦
        ]
    }
    resp = client.post("/api/v1/financials/text/extractions", json=payload)
    assert resp.status_code == 200
    name, kwargs = stub.calls[0]
    assert name == "validate_extractions"
    assert len(kwargs["items"]) == 2
    assert kwargs["items"][0] == {
        "concept": "revenue",
        "value": 1200.0,
        "unit": None,
        "source_page": 12,
        "source_text": "营业额 1,200 百万",
        "doc_url": None,
    }


# ─────────────────────────────────────────
#  6. 注册完整性
# ─────────────────────────────────────────


def test_coverage_forwards_years(client, stub):
    """FIN-09：覆盖率盘点转发。"""
    resp = client.get(f"/api/v1/financials/coverage/{ENTITY}?years=5")
    assert resp.status_code == 200
    name, kwargs = stub.calls[0]
    assert name == "get_coverage"
    assert kwargs["entity"] == ENTITY and kwargs["years"] == 5


def test_backfill_batch_forwards_entities(client, stub):
    """FIN-09：批量回填转发（同步挂后台，立即返 job_id 清单）。"""
    resp = client.post(
        "/api/v1/financials/backfill-batch",
        json={"entities": ["aapl", "msft"], "source": "sec"},
    )
    assert resp.status_code == 200
    name, kwargs = stub.calls[0]
    assert name == "backfill_batch"
    assert kwargs["entities"] == ["aapl", "msft"] and kwargs["source"] == "sec"


def test_all_endpoints_registered_on_main_app():
    from backend.main import app as main_app

    paths = {r.path for r in main_app.routes}
    assert {
        "/api/v1/financials/statements/{entity}",
        "/api/v1/financials/facts/{entity}",
        "/api/v1/financials/filings/{entity}",
        "/api/v1/financials/restatements/{entity}",
        "/api/v1/financials/analytics/{entity}",
        "/api/v1/financials/peers/{entity}",
        "/api/v1/financials/text/diff/{entity}",
        "/api/v1/financials/text/extractions",
        "/api/v1/financials/backfill",
        "/api/v1/financials/jobs/{job_id}",
        "/api/v1/financials/coverage/{entity}",
        "/api/v1/financials/backfill-batch",
        "/api/v1/financials/filings/{entity}/{accession}/ingest",
    } <= paths
