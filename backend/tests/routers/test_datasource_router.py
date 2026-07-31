"""
RL-06: 推测频率查询 API 端点单测
==================================

验证:
- GET /api/v1/datasource/{name}/rate-limit-analysis 正常返回
- GET /api/v1/datasource/{name}/rate-limit-analysis?window=7d 窗口参数
- GET /api/v1/datasource/{name}/rate-limit-analysis?window=invalid 错误处理
- GET /api/v1/datasource/{name}/rate-limit-status 正常返回
- GET /api/v1/datasource/rate-limit-overview 总览
- _parse_window_seconds 参数解析
"""

import time
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.routers.datasource import _parse_window_seconds
from backend.services.datasource import rate_limit_registry
from backend.services.datasource.analyzer import RateLimitAnalyzer


@pytest.fixture(autouse=True)
def clean_registry():
    """每个测试前重置全局注册表"""
    rate_limit_registry.clear()
    yield
    rate_limit_registry.clear()


@pytest.fixture
def client():
    """创建测试客户端（仅挂载目标路由）"""
    from fastapi import FastAPI

    from backend.routers.datasource import router as datasource_router

    app = FastAPI()
    app.include_router(datasource_router, prefix="/api/v1")
    return TestClient(app)


# ─────────────────────────────────────────
#  _parse_window_seconds 参数解析
# ─────────────────────────────────────────


class TestParseWindow:
    def test_none_returns_none(self):
        assert _parse_window_seconds(None) is None

    def test_24h(self):
        assert _parse_window_seconds("24h") == 86400

    def test_7d(self):
        assert _parse_window_seconds("7d") == 604800

    def test_1h(self):
        assert _parse_window_seconds("1h") == 3600

    def test_case_insensitive(self):
        assert _parse_window_seconds("24H") == 86400
        assert _parse_window_seconds("7D") == 604800

    def test_invalid_format_raises(self):
        with pytest.raises(HTTPException) as exc_info:
            _parse_window_seconds("invalid")
        assert exc_info.value.status_code == 400

    def test_invalid_unit_raises(self):
        with pytest.raises(HTTPException) as exc_info:
            _parse_window_seconds("24m")
        assert exc_info.value.status_code == 400

    def test_empty_string_returns_none(self):
        assert _parse_window_seconds("") is None


# ─────────────────────────────────────────
#  GET /rate-limit-analysis
# ─────────────────────────────────────────


class TestRateLimitAnalysisEndpoint:
    def test_empty_analysis(self, client):
        """空数据源返回默认分析结果"""
        resp = client.get("/api/v1/datasource/yfinance/rate-limit-analysis")
        assert resp.status_code == 200
        data = resp.json()
        assert data["source"] == "yfinance"
        assert data["estimated_limit_rpm"] is None
        assert data["confidence"] == 0.0
        assert data["history"] == []

    def test_analysis_with_data(self, client):
        """有数据时返回分析结果"""
        # 先记录一些请求
        analyzer = rate_limit_registry.get_analyzer("yfinance")
        for i in range(50):
            analyzer.record_success()
        for i in range(5):
            analyzer.record_rate_limit()

        resp = client.get("/api/v1/datasource/yfinance/rate-limit-analysis")
        assert resp.status_code == 200
        data = resp.json()
        assert data["source"] == "yfinance"
        assert data["total_rate_limits_window"] == 5
        assert data["confidence"] > 0

    def test_analysis_with_window_param(self, client):
        """window=7d 参数正确传递"""
        resp = client.get("/api/v1/datasource/yfinance/rate-limit-analysis?window=7d")
        assert resp.status_code == 200
        data = resp.json()
        assert data["source"] == "yfinance"

    def test_analysis_with_invalid_window(self, client):
        """无效 window 参数返回 400"""
        resp = client.get("/api/v1/datasource/yfinance/rate-limit-analysis?window=invalid")
        assert resp.status_code == 400

    def test_analysis_auto_creates_source(self, client):
        """查询不存在的数据源时自动创建"""
        assert not rate_limit_registry.has("new_source")
        resp = client.get("/api/v1/datasource/new_source/rate-limit-analysis")
        assert resp.status_code == 200
        assert rate_limit_registry.has("new_source")


# ─────────────────────────────────────────
#  GET /rate-limit-status
# ─────────────────────────────────────────


class TestRateLimitStatusEndpoint:
    def test_status_default(self, client):
        """默认状态（无限流）"""
        resp = client.get("/api/v1/datasource/yfinance/rate-limit-status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["source"] == "yfinance"
        assert data["is_throttled"] is False
        assert data["consecutive_rate_limits"] == 0
        assert data["backoff_strategy"] == "adaptive"

    def test_status_after_rate_limit(self, client):
        """限流后状态"""
        throttler = rate_limit_registry.get_throttler("yfinance")
        throttler.on_rate_limit()

        resp = client.get("/api/v1/datasource/yfinance/rate-limit-status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_throttled"] is True
        assert data["consecutive_rate_limits"] == 1

    def test_status_unknown_source(self, client):
        """查询未注册数据源返回默认状态"""
        resp = client.get("/api/v1/datasource/unknown/rate-limit-status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_throttled"] is False


# ─────────────────────────────────────────
#  GET /rate-limit-overview
# ─────────────────────────────────────────


class TestRateLimitOverviewEndpoint:
    def test_overview_empty(self, client):
        """无数据源时返回空列表"""
        resp = client.get("/api/v1/datasource/rate-limit-overview")
        assert resp.status_code == 200
        data = resp.json()
        assert data["sources"] == []
        assert data["total"] == 0

    def test_overview_with_sources(self, client):
        """有多个数据源时返回总览"""
        # 触发几个数据源的创建
        rate_limit_registry.get_throttler("yfinance")
        rate_limit_registry.get_throttler("futu")
        rate_limit_registry.get_throttler("finnhub")

        resp = client.get("/api/v1/datasource/rate-limit-overview")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3
        sources = data["sources"]
        source_names = {s["source"] for s in sources}
        assert "yfinance" in source_names
        assert "futu" in source_names
        assert "finnhub" in source_names

    def test_overview_includes_throttle_status(self, client):
        """总览包含退避状态"""
        throttler = rate_limit_registry.get_throttler("yfinance")
        throttler.on_rate_limit()

        resp = client.get("/api/v1/datasource/rate-limit-overview")
        assert resp.status_code == 200
        data = resp.json()
        yf = next(s for s in data["sources"] if s["source"] == "yfinance")
        assert yf["is_throttled"] is True
        assert yf["consecutive_rate_limits"] == 1


# ─────────────────────────────────────────
#  _build_health_card status 语义：stale/idle 解耦
# ─────────────────────────────────────────
class _FakeThrottlerStatus:
    def __init__(self, is_throttled=False, category=None):
        self.is_throttled = is_throttled
        self.consecutive_rate_limits = 0
        self.backoff_strategy = "adaptive"
        self.category = category


class _FakeThrottler:
    def get_status(self):
        return _FakeThrottlerStatus()


class _FakeAnalyzer:
    def __init__(self, metrics):
        self._metrics = metrics

    def get_health_metrics(self):
        return self._metrics


class _FakeHealth:
    def __init__(self, connected):
        self.connected = connected
        self.healthy = connected
        self.status = "ok" if connected else "error"
        self.last_error = None


class _FakeSourceHealthOnly:
    def __init__(self, connected):
        self.capabilities = []

    def health(self):
        return _FakeHealth(connected)


class TestHealthCardStatusLogic:
    """stale(失联) 改由 connected 主信号驱动；超时未调用归为 idle(空闲)。"""

    def _patch(self, client, monkeypatch, connected, last_success_ts, has_success=True):
        src = _FakeSourceHealthOnly(connected)
        reg = MagicMock()
        reg.has.return_value = True
        reg.get.return_value = src
        reg.list_names.return_value = ["yfinance"]
        monkeypatch.setattr("backend.routers.datasource.datasource_registry", reg)

        analyzer = _FakeAnalyzer(
            {
                "last_success_ts": last_success_ts,
                "today_requests": 10,
                "today_success": 10 if has_success else 0,
                "today_errors": 0 if has_success else 5,
                "today_rate_limits": 0,
                "last_latency_ms": 120.0,
                "success_rate": 1.0 if has_success else 0.0,
                "latency_avg_ms": 120.0,
                "latency_p95_ms": 200.0,
                "latency_min_ms": 100.0,
                "latency_max_ms": 300.0,
                "latency_samples": 10,
                "last_request_ts": last_success_ts or 0,
            }
        )
        rl_reg = MagicMock()
        rl_reg.get_throttler.return_value = _FakeThrottler()
        rl_reg.get_analyzer.return_value = analyzer
        monkeypatch.setattr("backend.routers.datasource.rate_limit_registry", rl_reg)
        return rl_reg

    def test_connected_but_idle_is_idle_not_stale(self, client, monkeypatch):
        """配好且可达但 5 分钟无成功调用 → idle，不再误判 stale(失联)。"""
        old = time.time() - 1000  # 远超 _STALE_SECONDS(300)
        self._patch(client, monkeypatch, connected=True, last_success_ts=old)
        resp = client.get("/api/v1/datasource/rate-limit-overview")
        assert resp.status_code == 200
        card = next(s for s in resp.json()["sources"] if s["source"] == "yfinance")
        assert card["connected"] is True
        assert card["status"] == "idle"

    def test_disconnected_is_stale(self, client, monkeypatch):
        """健康探针确认不可达(connected=false) → stale(失联)，即使最近有成功调用。"""
        recent = time.time() - 5
        self._patch(client, monkeypatch, connected=False, last_success_ts=recent)
        resp = client.get("/api/v1/datasource/rate-limit-overview")
        assert resp.status_code == 200
        card = next(s for s in resp.json()["sources"] if s["source"] == "yfinance")
        assert card["connected"] is False
        assert card["status"] == "stale"

    def test_throttled_rate_limit_label(self, client, monkeypatch):
        """真·限流(RATE_LIMIT) → 标签 throttled，rl_category=rate_limit。"""
        rl_reg = self._patch(client, monkeypatch, connected=True, last_success_ts=time.time())
        rl_reg.get_throttler.return_value.get_status.return_value = _FakeThrottlerStatus(
            is_throttled=True, category="rate_limit"
        )
        card = next(
            s
            for s in client.get("/api/v1/datasource/rate-limit-overview").json()["sources"]
            if s["source"] == "yfinance"
        )
        assert card["status"] == "throttled"
        assert card["rl_category"] == "rate_limit"

    def test_ip_blocked_label_not_throttled(self, client, monkeypatch):
        """403/IP封禁 → 标签 blocked（不再误标为限流 throttled）。"""
        rl_reg = self._patch(client, monkeypatch, connected=True, last_success_ts=time.time())
        rl_reg.get_throttler.return_value.get_status.return_value = _FakeThrottlerStatus(
            is_throttled=True, category="ip_blocked"
        )
        card = next(
            s
            for s in client.get("/api/v1/datasource/rate-limit-overview").json()["sources"]
            if s["source"] == "yfinance"
        )
        assert card["status"] == "blocked"
        assert card["rl_category"] == "ip_blocked"

    def test_quota_exhausted_label(self, client, monkeypatch):
        """402/配额耗尽 → 标签 quota_exhausted。"""
        rl_reg = self._patch(client, monkeypatch, connected=True, last_success_ts=time.time())
        rl_reg.get_throttler.return_value.get_status.return_value = _FakeThrottlerStatus(
            is_throttled=True, category="quota_exhausted"
        )
        card = next(
            s
            for s in client.get("/api/v1/datasource/rate-limit-overview").json()["sources"]
            if s["source"] == "yfinance"
        )
        assert card["status"] == "quota_exhausted"
        assert card["rl_category"] == "quota_exhausted"


class TestThrottlerCategoryBackoff:
    """按 category 区分退避：真·限流指数自愈；403/IP封禁、402/配额走固定窗口不污染连续计数。"""

    def _t(self):
        from backend.services.datasource import ErrorInfo
        from backend.services.datasource.throttler import RateLimitThrottler

        return RateLimitThrottler("finnhub"), ErrorInfo

    def test_rate_limit_compounds_consecutive(self):
        t, EI = self._t()
        t.on_rate_limit(EI.rate_limited(message="429"))
        t.on_rate_limit(EI.rate_limited(message="429"))
        st = t.get_status()
        assert st.category == "rate_limit"
        assert st.is_throttled is True
        assert t._consecutive_limits == 2
        assert st.consecutive_rate_limits == 2

    def test_ip_blocked_not_compounding(self):
        t, EI = self._t()
        t.on_rate_limit(EI.ip_blocked(message="403"))
        t.on_rate_limit(EI.ip_blocked(message="403"))
        st = t.get_status()
        assert st.category == "ip_blocked"
        assert st.is_throttled is True
        # 封禁不污染 RATE_LIMIT 连续计数，仅累计 block_events
        assert t._consecutive_limits == 0
        assert t._block_events == 2
        assert st.consecutive_rate_limits == 2

    def test_quota_exhausted_labeled(self):
        t, EI = self._t()
        t.on_rate_limit(EI.quota_exhausted(message="402"))
        st = t.get_status()
        assert st.category == "quota_exhausted"
        assert st.is_throttled is True


# ─────────────────────────────────────────
#  WS /ws/health 鉴权一致性
# ─────────────────────────────────────────
from starlette.websockets import WebSocketDisconnect


class TestHealthWsAuth:
    """WS 鉴权必须与 access token 签名密钥(SECRET_KEY) 一致，否则全部 4401。"""

    def test_ws_rejects_invalid_token(self, client):
        with pytest.raises(WebSocketDisconnect) as exc:
            with client.websocket_connect("/api/v1/datasource/ws/health?token=invalid.token.here"):
                pass
        assert exc.value.code == 4401

    def test_ws_accepts_valid_access_token(self, client):
        from backend.routers.auth import create_access_token

        token = create_access_token({"sub": "test-user"})
        with client.websocket_connect(f"/api/v1/datasource/ws/health?token={token}") as ws:
            data = ws.receive_json()
            assert data["type"] == "overview"
            assert "sources" in data


# ─────────────────────────────────────────
#  POST /{name}/test-link 主动链接探测
# ─────────────────────────────────────────


class _FakeInfo:
    connected = True
    healthy = True
    status = "ok"
    last_error = None


class _FakeSourceUp:
    capabilities = ["quote"]

    def health(self):
        return _FakeInfo()

    async def fetch(self, action, params):
        return {"price": 123.0}


class _FakeSourceDown:
    capabilities = []

    def health(self):
        info = _FakeInfo()
        info.connected = False
        info.healthy = False
        info.status = "error"
        return info

    async def fetch(self, action, params):
        raise RuntimeError("boom")


class _FakeSourceCaptureParams:
    """捕获 probe 传入的 params，用于断言 skip_cache 透传。"""

    def __init__(self, capabilities):
        self.capabilities = capabilities
        self.last_action = None
        self.last_params = None

    def health(self):
        return _FakeInfo()

    async def fetch(self, action, params):
        self.last_action = action
        self.last_params = dict(params)
        return {"ok": True}


class TestLinkTestSkipCache:
    def test_quote_probe_passes_skip_cache(self, client, monkeypatch):
        """quote 探针必须透传 skip_cache=True 与 ttl，否则会命中缓存误报 0ms 或抛 TypeError 静默失败。"""
        src = _FakeSourceCaptureParams(capabilities=["quote"])
        reg = MagicMock()
        reg.get.return_value = src
        monkeypatch.setattr("backend.routers.datasource.datasource_registry", reg)

        resp = client.post("/api/v1/datasource/yfinance/test-link")
        assert resp.status_code == 200
        assert src.last_action == "quote"
        assert src.last_params.get("skip_cache") is True
        assert src.last_params.get("ticker") == "AAPL"
        # ttl 是 fetch_yf_data 的必填位置参数，缺失会导致探针抛 TypeError 被静默吞掉
        assert src.last_params.get("ttl") == 60

    def test_web_scrape_probe_passes_skip_cache(self, client, monkeypatch):
        """WEB_SCRAPE 探针同样透传 skip_cache=True。"""
        src = _FakeSourceCaptureParams(capabilities=["WEB_SCRAPE"])
        reg = MagicMock()
        reg.get.return_value = src
        monkeypatch.setattr("backend.routers.datasource.datasource_registry", reg)

        resp = client.post("/api/v1/datasource/jina/test-link")
        assert resp.status_code == 200
        assert src.last_action == "WEB_SCRAPE"
        assert src.last_params.get("skip_cache") is True

    def test_web_search_probe_no_cache_layer(self, client, monkeypatch):
        """WEB_SEARCH 适配器本就无缓存层，skip_cache 非必需，但透传无害。"""
        src = _FakeSourceCaptureParams(capabilities=["WEB_SEARCH"])
        reg = MagicMock()
        reg.get.return_value = src
        monkeypatch.setattr("backend.routers.datasource.datasource_registry", reg)

        resp = client.post("/api/v1/datasource/tavily/test-link")
        assert resp.status_code == 200
        assert src.last_action == "WEB_SEARCH"
        assert src.last_params.get("query") == "quant agent test"

    def test_macro_probe_runs_economic_calendar(self, client, monkeypatch):
        """宏观源(fred/dbnomics/rbi) 此前无探针分支 → 永远 0 延迟；现应发 economic_calendar 探针。"""
        src = _FakeSourceCaptureParams(capabilities=["macro_series", "economic_calendar"])
        reg = MagicMock()
        reg.get.return_value = src
        monkeypatch.setattr("backend.routers.datasource.datasource_registry", reg)

        resp = client.post("/api/v1/datasource/fred/test-link")
        assert resp.status_code == 200
        assert src.last_action == "economic_calendar"
        assert src.last_params.get("skip_cache") is True
        assert src.last_params.get("days_ahead") == 1

    def test_futu_probe_uses_declared_uppercase_quote(self, client, monkeypatch):
        """futu 声明大写 QUOTE，此前因探针查小写 'quote' 被漏掉 → 永远 health()≈0；现应发 QUOTE 探针。"""
        src = _FakeSourceCaptureParams(capabilities=["QUOTE", "HISTORY", "FUND_FLOW"])
        reg = MagicMock()
        reg.get.return_value = src
        monkeypatch.setattr("backend.routers.datasource.datasource_registry", reg)

        resp = client.post("/api/v1/datasource/futu/test-link")
        assert resp.status_code == 200
        # 必须用适配器声明的大小写(QUOTE)，否则 futu.fetch 大小写敏感会拒 UNSUPPORTED_ACTION
        assert src.last_action == "QUOTE"
        assert src.last_params.get("ticker") == "AAPL"
        assert src.last_params.get("skip_cache") is True
        assert src.last_params.get("ttl") == 60

    def test_akshare_probe_uses_declared_uppercase_economic_calendar(self, client, monkeypatch):
        """akshare 声明大写 ECONOMIC_CALENDAR，此前因探针查小写被漏掉 → 永远 health()≈0；现应发探针。"""
        src = _FakeSourceCaptureParams(capabilities=["FUND_FLOW", "ECONOMIC_CALENDAR"])
        reg = MagicMock()
        reg.get.return_value = src
        monkeypatch.setattr("backend.routers.datasource.datasource_registry", reg)

        resp = client.post("/api/v1/datasource/akshare/test-link")
        assert resp.status_code == 200
        assert src.last_action == "ECONOMIC_CALENDAR"
        assert src.last_params.get("skip_cache") is True
        assert src.last_params.get("days_ahead") == 1


class TestLinkTestEndpoint:
    def test_link_test_active_probe_ok(self, client, monkeypatch):
        """支持 quote 的源：主动探测成功，probed=True 且延迟被测量回写。"""
        reg = MagicMock()
        reg.get.return_value = _FakeSourceUp()
        monkeypatch.setattr("backend.routers.datasource.datasource_registry", reg)

        resp = client.post("/api/v1/datasource/yfinance/test-link")
        assert resp.status_code == 200
        d = resp.json()
        assert d["source"] == "yfinance"
        assert d["connected"] is True
        assert d["healthy"] is True
        assert d["probed"] is True
        assert d["validated"] is True
        assert isinstance(d["latency_ms"], (int, float))
        assert d["error"] is None

    def test_link_test_unknown_source_404(self, client, monkeypatch):
        reg = MagicMock()
        reg.get.return_value = None
        monkeypatch.setattr("backend.routers.datasource.datasource_registry", reg)

        resp = client.post("/api/v1/datasource/ghost/test-link")
        assert resp.status_code == 404

    def test_link_test_passive_fallback(self, client, monkeypatch):
        """不支持 quote 的源：回退被动健康，probed=False。"""
        reg = MagicMock()
        reg.get.return_value = _FakeSourceDown()
        monkeypatch.setattr("backend.routers.datasource.datasource_registry", reg)

        resp = client.post("/api/v1/datasource/futu/test-link")
        assert resp.status_code == 200
        d = resp.json()
        assert d["connected"] is False
        assert d["probed"] is False
        assert d["validated"] is True


# ─────────────────────────────────────────
#  RateLimitAnalyzer 延迟统计（调用延迟数据验证）
# ─────────────────────────────────────────


class TestAnalyzerLatencyStats:
    def test_latency_stats_empty(self):
        a = RateLimitAnalyzer("latency_empty")
        m = a.get_health_metrics()
        assert m["latency_avg_ms"] is None
        assert m["latency_p95_ms"] is None
        assert m["latency_samples"] == 0

    def test_latency_stats_computed(self):
        a = RateLimitAnalyzer("latency_calc")
        for v in [10, 20, 30, 40, 50]:
            a.record_request(latency_ms=v)
        m = a.get_health_metrics()
        assert m["latency_samples"] == 5
        assert m["latency_avg_ms"] == 30.0
        assert m["latency_min_ms"] == 10
        assert m["latency_max_ms"] == 50
        # p95: sorted[4] = 50
        assert m["latency_p95_ms"] == 50.0
        # 仅统计有效延迟，0/None 不计入样本
        a.record_request(latency_ms=0)
        assert a.get_health_metrics()["latency_samples"] == 5


# ─────────────────────────────────────────
#  路由优先级：overview 必须在 {name} 之前
# ─────────────────────────────────────────


class TestRoutePriority:
    def test_overview_not_matched_as_name(self, client):
        """rate-limit-overview 不应被 {name} 路由捕获"""
        resp = client.get("/api/v1/datasource/rate-limit-overview")
        assert resp.status_code == 200
        data = resp.json()
        # 应该是总览接口，不是名为 "rate-limit-overview" 的数据源
        assert "sources" in data
        assert "total" in data
