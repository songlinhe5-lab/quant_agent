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

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.routers.datasource import _parse_window_seconds
from backend.services.datasource import datasource_registry


@pytest.fixture(autouse=True)
def clean_registry():
    """每个测试前重置全局注册表"""
    datasource_registry.clear()
    yield
    datasource_registry.clear()


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
        analyzer = datasource_registry.get_analyzer("yfinance")
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
        assert not datasource_registry.has("new_source")
        resp = client.get("/api/v1/datasource/new_source/rate-limit-analysis")
        assert resp.status_code == 200
        assert datasource_registry.has("new_source")


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
        throttler = datasource_registry.get_throttler("yfinance")
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
        datasource_registry.get_throttler("yfinance")
        datasource_registry.get_throttler("futu")
        datasource_registry.get_throttler("finnhub")

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
        throttler = datasource_registry.get_throttler("yfinance")
        throttler.on_rate_limit()

        resp = client.get("/api/v1/datasource/rate-limit-overview")
        assert resp.status_code == 200
        data = resp.json()
        yf = next(s for s in data["sources"] if s["source"] == "yfinance")
        assert yf["is_throttled"] is True
        assert yf["consecutive_rate_limits"] == 1


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
