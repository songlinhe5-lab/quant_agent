"""
数据源路由服务测试
覆盖: backend/services/data_source_router.py
"""

import asyncio
import json
import os
import sys
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from backend.services.datasource import ErrorCategory
from backend.services.datasource.router import DataSourceNode, DataSourceRouter


# ==========================================
# DataSourceNode 测试
# ==========================================
class TestDataSourceNode:
    def test_node_creation(self):
        """节点创建"""
        node = DataSourceNode(name="test", url="http://localhost:8000")
        assert node.name == "test"
        assert node.url == "http://localhost:8000"
        assert node.enabled is True
        assert node.weight == 10
        assert node.status == "healthy"
        assert node.error_count == 0
        assert node.is_throttled is False

    def test_node_with_capabilities(self):
        """带能力的节点"""
        node = DataSourceNode(name="yf", url="http://yf:8000", capabilities=["yfinance", "quote", "history"])
        assert "yfinance" in node.capabilities
        assert len(node.capabilities) == 3


# ==========================================
# DataSourceRouter 测试
# ==========================================
class TestDataSourceRouter:
    @pytest.fixture
    def router(self):
        with patch.dict(os.environ, {"DATA_SOURCE_ROUTER_ENABLED": "false"}):
            return DataSourceRouter()

    def test_init_disabled(self, router):
        """默认禁用"""
        assert router._enabled is False

    def test_init_nodes(self, router):
        """初始化节点"""
        assert "yf_primary" in router._nodes

    def test_sign_request_matches_subservice_contract(self):
        """签名必须与子服务 verify_hmac 的标准 HMAC-SHA256 一致"""
        import hashlib
        import hmac

        with patch.dict(os.environ, {"DATA_SOURCE_HMAC_SECRET": "test-secret", "DATA_SOURCE_ROUTER_ENABLED": "false"}):
            r = DataSourceRouter()

        body = '{"source": "yfinance", "action": "QUOTE", "params": {}}'
        expected = hmac.new(b"test-secret", f"12345:{body}".encode("utf-8"), hashlib.sha256).hexdigest()
        assert r._sign_request(body, "12345") == expected

    def test_sign_request_with_secret(self):
        """有密钥时生成签名"""
        with patch.dict(os.environ, {"DATA_SOURCE_HMAC_SECRET": "test-secret", "DATA_SOURCE_ROUTER_ENABLED": "false"}):
            r = DataSourceRouter()
        sig = r._sign_request('{"key": "value"}', "12345")
        assert len(sig) == 64  # SHA256 hex

    def test_get_healthy_nodes(self, router):
        """获取健康节点"""
        with patch("backend.services.datasource.router.rate_limit_registry") as mock_rl:
            mock_throttler = MagicMock()
            mock_status = MagicMock()
            mock_status.is_throttled = False
            mock_status.consecutive_rate_limits = 0
            mock_status.estimated_limit_rpm = None
            mock_throttler.get_status.return_value = mock_status
            mock_rl.get_throttler.return_value = mock_throttler
            nodes = router._get_healthy_nodes("yfinance")
        assert len(nodes) >= 1

    def test_get_healthy_nodes_no_capability(self, router):
        """无匹配能力时返回空"""
        with patch("backend.services.datasource.router.rate_limit_registry") as mock_rl:
            mock_throttler = MagicMock()
            mock_status = MagicMock()
            mock_status.is_throttled = False
            mock_status.consecutive_rate_limits = 0
            mock_status.estimated_limit_rpm = None
            mock_throttler.get_status.return_value = mock_status
            mock_rl.get_throttler.return_value = mock_throttler
            nodes = router._get_healthy_nodes("nonexistent_capability")
        assert len(nodes) == 0

    @pytest.mark.asyncio
    async def test_update_node_status_success(self, router):
        """成功更新节点状态"""
        node = router._nodes["yf_primary"]
        node.error_count = 2
        await router._update_node_status("yf_primary", success=True)
        assert node.error_count == 0
        assert node.status == "healthy"

    @pytest.mark.asyncio
    async def test_update_node_status_normal_error(self, router):
        """普通错误计入熔断"""
        node = router._nodes["yf_primary"]
        node.error_count = 0
        for _ in range(3):
            await router._update_node_status("yf_primary", success=False, error="timeout")
        assert node.status == "unhealthy"
        assert node.circuit_breaker_until > time.time()

    @pytest.mark.asyncio
    async def test_update_node_status_rate_limit_no_circuit_break(self, router):
        """限流错误不触发熔断"""
        node = router._nodes["yf_primary"]
        node.error_count = 0
        for _ in range(5):
            await router._update_node_status(
                "yf_primary", success=False, error="429", error_category=ErrorCategory.RATE_LIMIT
            )
        assert node.error_count == 0  # 限流不计入
        assert node.status == "healthy"

    @pytest.mark.asyncio
    async def test_update_node_status_nonexistent(self, router):
        """更新不存在的节点"""
        await router._update_node_status("nonexist", success=True)  # 不报错

    @pytest.mark.asyncio
    async def test_select_node(self, router):
        """选择最优节点"""
        with patch("backend.services.datasource.router.rate_limit_registry") as mock_rl:
            mock_throttler = MagicMock()
            mock_status = MagicMock()
            mock_status.is_throttled = False
            mock_status.consecutive_rate_limits = 0
            mock_status.estimated_limit_rpm = None
            mock_throttler.get_status.return_value = mock_status
            mock_rl.get_throttler.return_value = mock_throttler
            node = await router._select_node("yfinance")
        assert node is not None
        assert node.name == "yf_primary"

    @pytest.mark.asyncio
    async def test_select_node_no_healthy(self, router):
        """无健康节点"""
        router._nodes["yf_primary"].status = "unhealthy"
        router._nodes["yf_primary"].circuit_breaker_until = time.time() + 999
        with patch("backend.services.datasource.router.rate_limit_registry") as mock_rl:
            mock_throttler = MagicMock()
            mock_status = MagicMock()
            mock_status.is_throttled = False
            mock_status.consecutive_rate_limits = 0
            mock_status.estimated_limit_rpm = None
            mock_throttler.get_status.return_value = mock_status
            mock_rl.get_throttler.return_value = mock_throttler
            node = await router._select_node("yfinance")
        assert node is None

    @pytest.mark.asyncio
    async def test_fetch_yfinance_disabled(self, router):
        """路由禁用时直接返回失败（后端已移除本地 yfinance 兜底）"""
        result = await router.fetch_yfinance("AAPL", "quote")
        assert result.get("success") is False
        assert "DataSourceRouter" in result.get("message", "")

    @pytest.mark.asyncio
    async def test_fetch_yfinance_no_healthy_node(self, router):
        """无健康子服务节点时返回失败（不再降级本地）"""
        router._enabled = True
        router._nodes = {}  # 清空节点 → 无健康节点
        router._update_node_status = AsyncMock()
        result = await router.fetch_yfinance("AAPL", "quote")
        assert result.get("success") is False
        assert "No healthy YFinance subservice node" in result.get("message", "")

    @pytest.mark.asyncio
    async def test_fetch_yfinance_unknown_type(self, router):
        """未知 fetch_type 经子服务路由（节点不可用时返回失败）"""
        router._enabled = True
        router._nodes = {}
        router._update_node_status = AsyncMock()
        result = await router.fetch_yfinance("AAPL", "unknown_type")
        assert result.get("success") is False

    @pytest.mark.asyncio
    async def test_fetch_yfinance_remote_success(self, router):
        """经子服务成功路径"""
        router._enabled = True
        mock_node = MagicMock()
        mock_node.name = "yf_primary"
        router._get_healthy_nodes = MagicMock(return_value=[mock_node])
        router._send_request = AsyncMock(return_value={"success": True, "data": {"price": 165.0}})
        router._update_node_status = AsyncMock()
        result = await router.fetch_yfinance("AAPL", "quote")
        assert result.get("success") is True
        assert result["data"]["price"] == 165.0

    @pytest.mark.asyncio
    async def test_save_akshare_stale(self, router):
        """保存 STALE 缓存"""
        with patch("backend.services.datasource.router.redis_client", create=True) as mock_redis:
            mock_redis.set = AsyncMock()
            with patch.dict("sys.modules", {"backend.core.redis_client": MagicMock(redis_client=mock_redis)}):
                await router._save_akshare_stale("southbound", {}, {"status": "success"})

    @pytest.mark.asyncio
    async def test_get_akshare_stale_hit(self, router):
        """STALE 缓存命中"""
        cached = json.dumps({"status": "success", "data": [1, 2, 3]})
        with patch("backend.services.datasource.router.redis_client", create=True) as mock_redis:
            mock_redis.get = AsyncMock(return_value=cached)
            with patch.dict("sys.modules", {"backend.core.redis_client": MagicMock(redis_client=mock_redis)}):
                result = await router._get_akshare_stale("southbound", {})
        assert result is not None
        assert result["degraded"] is True
        assert result["stale_source"] is True

    @pytest.mark.asyncio
    async def test_get_akshare_stale_miss(self, router):
        """STALE 缓存未命中"""
        with patch("backend.services.datasource.router.redis_client", create=True) as mock_redis:
            mock_redis.get = AsyncMock(return_value=None)
            with patch.dict("sys.modules", {"backend.core.redis_client": MagicMock(redis_client=mock_redis)}):
                result = await router._get_akshare_stale("southbound", {})
        assert result is None

    @pytest.mark.asyncio
    async def test_get_health_status(self, router):
        """健康状态"""
        with patch("backend.services.datasource.router.rate_limit_registry") as mock_rl:
            mock_throttler = MagicMock()
            mock_status = MagicMock()
            mock_status.is_throttled = False
            mock_status.consecutive_rate_limits = 0
            mock_status.total_rate_limits_1h = 0
            mock_status.estimated_limit_rpm = None
            mock_status.backoff_strategy = "exponential"
            mock_throttler.get_status.return_value = mock_status
            mock_rl.get_throttler.return_value = mock_throttler
            status = await router.get_health_status()
        assert status["router_enabled"] is False
        assert "yf_primary" in status["nodes"]

    @pytest.mark.asyncio
    async def test_close(self, router):
        """关闭 HTTP 客户端"""
        router._http_client = MagicMock()
        router._http_client.aclose = AsyncMock()
        await router.close()
        router._http_client.aclose.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_no_client(self, router):
        """无客户端时关闭不报错"""
        router._http_client = None
        await router.close()  # 不报错

    def test_build_error_info_rate_limit(self, router):
        """构建限流 ErrorInfo"""

        info = router._build_error_info_from_http(
            status_code=429,
            category=ErrorCategory.RATE_LIMIT,
            retry_after=60.0,
            response_headers={"X-RateLimit-Remaining": "0"},
            message="Too Many Requests",
        )
        assert info.category == ErrorCategory.RATE_LIMIT

    def test_build_error_info_quota_exhausted(self, router):
        """构建配额耗尽 ErrorInfo"""
        info = router._build_error_info_from_http(
            status_code=402,
            category=ErrorCategory.QUOTA_EXHAUSTED,
            retry_after=None,
            response_headers=None,
            message="Payment Required",
        )
        assert info.category == ErrorCategory.QUOTA_EXHAUSTED

    def test_build_error_info_ip_blocked(self, router):
        """构建 IP 封锁 ErrorInfo"""
        info = router._build_error_info_from_http(
            status_code=403,
            category=ErrorCategory.IP_BLOCKED,
            retry_after=None,
            response_headers=None,
            message="Forbidden",
        )
        assert info.category == ErrorCategory.IP_BLOCKED

    def test_build_error_info_normal_5xx(self, router):
        """构建普通 5xx ErrorInfo (可重试)"""
        info = router._build_error_info_from_http(
            status_code=500,
            category=ErrorCategory.NORMAL,
            retry_after=None,
            response_headers=None,
            message="Internal Server Error",
        )
        assert info.category == ErrorCategory.NORMAL
        assert info.retryable is True

    def test_build_error_info_normal_4xx(self, router):
        """构建普通 4xx ErrorInfo (不可重试)"""
        info = router._build_error_info_from_http(
            status_code=404,
            category=ErrorCategory.NORMAL,
            retry_after=None,
            response_headers=None,
            message="Not Found",
        )
        assert info.retryable is False


# ===== DataSourceRouter 增强测试 =====


@pytest.fixture
def router_disabled():
    with patch.dict(os.environ, {"DATA_SOURCE_ROUTER_ENABLED": "false"}):
        yield DataSourceRouter()


@pytest.fixture
def router_enabled():
    with patch.dict(
        os.environ,
        {
            "DATA_SOURCE_ROUTER_ENABLED": "true",
            "YF_PRIMARY_NODE_URL": "http://localhost:8000",
            "YF_BACKUP_NODE_URL": "http://10.0.0.2:8000",
            "AKSHARE_REMOTE_URL": "http://10.0.0.3:8000",
            "DATA_SOURCE_HMAC_SECRET": "test_secret_123",
        },
    ):
        yield DataSourceRouter()


class TestDataSourceNodeEnhanced:
    def test_node_initialization(self):
        node = DataSourceNode(name="test", url="http://localhost:8000")
        assert node.name == "test"
        assert node.url == "http://localhost:8000"
        assert node.enabled is True
        assert node.weight == 10
        assert node.status == "healthy"
        assert node.error_count == 0

    def test_node_with_capabilities(self):
        node = DataSourceNode(
            name="test",
            url="http://localhost:8000",
            capabilities=["yfinance", "quote"],
            weight=5,
        )
        assert "yfinance" in node.capabilities
        assert node.weight == 5


class TestDataSourceRouterInit:
    def test_router_disabled_by_default(self, router_disabled):
        assert router_disabled._enabled is False

    def test_router_enabled_with_env(self, router_enabled):
        assert router_enabled._enabled is True

    def test_nodes_initialization(self, router_enabled):
        assert "yf_primary" in router_enabled._nodes
        assert "yf_backup_1" in router_enabled._nodes
        assert "akshare_remote" in router_enabled._nodes

    def test_nodes_capabilities(self, router_enabled):
        yf_primary = router_enabled._nodes["yf_primary"]
        assert "yfinance" in yf_primary.capabilities

        akshare = router_enabled._nodes["akshare_remote"]
        assert "akshare" in akshare.capabilities


class TestHmacSignature:
    def test_sign_request_with_secret(self, router_enabled):
        body = '{"source": "yfinance", "action": "QUOTE", "params": {"ticker": "AAPL"}}'
        timestamp = "1234567890"
        signature = router_enabled._sign_request(body, timestamp)
        assert isinstance(signature, str)
        assert len(signature) == 64

    def test_sign_request_matches_subservice_contract(self, router_enabled):
        """签名须与 data_subservice/main.py::verify_hmac 完全一致"""
        import hashlib
        import hmac

        body = '{"ticker": "AAPL"}'
        timestamp = "1234567890"
        expected = hmac.new(
            router_enabled._hmac_secret.encode("utf-8"),
            f"{timestamp}:{body}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        assert router_enabled._sign_request(body, timestamp) == expected

    def test_sign_request_consistent(self, router_enabled):
        body = '{"key": "value", "num": 123}'
        timestamp = "1234567890"
        sig1 = router_enabled._sign_request(body, timestamp)
        sig2 = router_enabled._sign_request(body, timestamp)
        assert sig1 == sig2

    def test_sign_request_with_timestamp(self, router_enabled):
        body = '{"ticker": "AAPL"}'
        sig1 = router_enabled._sign_request(body, "1234567890")
        sig2 = router_enabled._sign_request(body, "0987654321")
        assert sig1 != sig2


class TestHttpClientLazyLoading:
    def test_http_client_none_initially(self, router_enabled):
        assert router_enabled._http_client is None

    def test_http_client_created_on_first_use(self, router_enabled):
        router_enabled._ensure_http_client()
        assert router_enabled._http_client is not None


class TestNodeHealthFiltering:
    def test_get_healthy_nodes(self, router_enabled):
        nodes = router_enabled._get_healthy_nodes("yfinance")
        assert len(nodes) >= 1

    def test_get_healthy_nodes_with_circuit_breaker(self, router_enabled):
        router_enabled._nodes["yf_primary"].circuit_breaker_until = time.time() + 3600
        nodes = router_enabled._get_healthy_nodes("yfinance")
        assert router_enabled._nodes["yf_primary"] not in nodes

    def test_get_healthy_nodes_unhealthy_status(self, router_enabled):
        router_enabled._nodes["yf_primary"].status = "unhealthy"
        nodes = router_enabled._get_healthy_nodes("yfinance")
        assert router_enabled._nodes["yf_primary"] not in nodes

    def test_select_node_priority(self, router_enabled):
        router_enabled._nodes["yf_primary"].weight = 10
        router_enabled._nodes["yf_backup_1"].weight = 5
        node = asyncio.run(router_enabled._select_node("yfinance"))
        assert node.name == "yf_primary"


class TestCircuitBreaker:
    def test_update_node_status_success(self, router_enabled):
        asyncio.run(router_enabled._update_node_status("yf_primary", success=True))
        node = router_enabled._nodes["yf_primary"]
        assert node.error_count == 0
        assert node.status == "healthy"

    def test_update_node_status_failure(self, router_enabled):
        asyncio.run(router_enabled._update_node_status("yf_primary", success=False, error="test"))
        node = router_enabled._nodes["yf_primary"]
        assert node.error_count == 1
        assert node.status == "healthy"

    def test_circuit_breaker_triggered(self, router_enabled):
        asyncio.run(router_enabled._update_node_status("yf_primary", success=False, error="err1"))
        asyncio.run(router_enabled._update_node_status("yf_primary", success=False, error="err2"))
        asyncio.run(router_enabled._update_node_status("yf_primary", success=False, error="err3"))
        node = router_enabled._nodes["yf_primary"]
        assert node.error_count >= 3
        assert node.status == "unhealthy"
        assert node.circuit_breaker_until > time.time()


class TestFetchYFinance:
    def test_fetch_yfinance_disabled_router(self, router_disabled):
        """路由禁用时直接返回失败（不再本地兜底）"""
        result = asyncio.run(router_disabled.fetch_yfinance("AAPL", "quote"))
        assert result["success"] is False
        assert "未启用" in result["message"] or "disabled" in result["message"]

    @patch("backend.services.datasource.router.DataSourceRouter._send_request")
    def test_fetch_yfinance_remote_success(self, mock_send, router_enabled):
        mock_send.return_value = {"success": True, "data": {"price": 165.0}}
        result = asyncio.run(router_enabled.fetch_yfinance("AAPL", "history", period="1d"))
        assert result["success"] is True
        assert result["data"]["price"] == 165.0

    @patch("backend.services.datasource.router.DataSourceRouter._send_request")
    def test_fetch_yfinance_rate_limit_switch(self, mock_send, router_enabled):
        mock_send.side_effect = [
            {"success": False, "message": "429 Rate Limit"},
            {"success": True, "data": {"price": 165.0}},
        ]
        result = asyncio.run(router_enabled.fetch_yfinance("AAPL", "history", period="1d"))
        assert result["success"] is True
        assert mock_send.call_count == 2

    def test_fetch_yfinance_fallback_local_removed(self, router_enabled):
        """本地兜底已移除：无健康节点时返回失败"""
        router_enabled._nodes = {}
        router_enabled._update_node_status = AsyncMock()
        result = asyncio.run(router_enabled.fetch_yfinance("AAPL", "history", period="1d"))
        assert result["success"] is False
        assert "No healthy YFinance subservice node" in result["message"]


class TestFetchAKShare:
    def test_fetch_akshare_disabled_router(self, router_disabled):
        """Router 未启用时直接返回 error（不再本地兜底）"""
        result = asyncio.run(router_disabled.fetch_akshare("southbound"))
        assert result["status"] == "error"
        assert "未启用" in result["message"] or "disabled" in result["message"]

    @patch("backend.services.datasource.router.DataSourceRouter._send_request")
    @patch("backend.services.datasource.router.DataSourceRouter._save_akshare_stale")
    @patch("backend.services.datasource.router.DataSourceRouter._save_akshare_cache")
    def test_fetch_akshare_remote_success(self, mock_cache, mock_stale, mock_send, router_enabled):
        mock_send.return_value = {"status": "success", "data": {"flow": 100}}
        result = asyncio.run(router_enabled.fetch_akshare("southbound"))
        assert result["status"] == "success"
        mock_stale.assert_awaited_once()
        mock_cache.assert_awaited_once()

    @patch("backend.services.datasource.router.DataSourceRouter._get_akshare_stale")
    @patch("backend.services.datasource.router.DataSourceRouter._send_request")
    def test_fetch_akshare_remote_fail_no_stale(self, mock_send, mock_stale, router_enabled):
        """远程失败且无 STALE 缓存时返回裸 error（不再本地兜底）"""
        mock_send.side_effect = Exception("Connection refused")
        mock_stale.return_value = None
        result = asyncio.run(router_enabled.fetch_akshare("southbound"))
        assert result["status"] == "error"


class TestHealthStatus:
    def test_get_health_status(self, router_enabled):
        status = asyncio.run(router_enabled.get_health_status())
        assert status["router_enabled"] is True
        assert "yf_primary" in status["nodes"]
        assert "akshare_remote" in status["nodes"]


class TestClose:
    def test_close_http_client(self, router_enabled):
        router_enabled._ensure_http_client()
        assert router_enabled._http_client is not None
        asyncio.run(router_enabled.close())


# ==========================================
# BE-ARCH-08b: 跨进程 params 键名归一回归
# ==========================================
class TestOutboundParamNormalization:
    """验收：业务侧统一用 ticker/tickers，子服务 worker 读 symbol/symbols，
    归一后子服务必须能取到非 None 的 symbol（否则线上取不到数）。"""

    def test_ticker_maps_to_symbol_dual_key(self):
        out = DataSourceRouter._normalize_outbound_params({"ticker": "AAPL", "period": "1mo"})
        # 双键兼容：原键保留 + 映射副本
        assert out.get("symbol") == "AAPL"
        assert out.get("ticker") == "AAPL"
        assert out.get("period") == "1mo"

    def test_tickers_maps_to_symbols_dual_key(self):
        out = DataSourceRouter._normalize_outbound_params({"tickers": ["AAPL", "MSFT"]})
        assert out.get("symbols") == ["AAPL", "MSFT"]
        assert out.get("tickers") == ["AAPL", "MSFT"]

    def test_existing_symbol_not_overwritten(self):
        out = DataSourceRouter._normalize_outbound_params({"symbol": "000001", "ktype": "d"})
        assert out.get("symbol") == "000001"

    def test_worker_reads_symbol_after_normalization(self):
        """复刻 yfinance_worker 读取路径：归一后 params.get('symbol') 非 None。"""
        raw = {"ticker": "AAPL"}  # 业务侧调用 fetch_yfinance 时传入
        normalized = DataSourceRouter._normalize_outbound_params(raw)
        symbol = normalized.get("symbol")  # yfinance_worker.py:13
        assert symbol is not None and symbol == "AAPL"


# ==========================================
# BE-ARCH-08d: 子服务错误体归一回归 (限流/配额感知)
# ==========================================
class TestNormalizeResponseErrorBody:
    """验收：子服务 (FMP/Finnhub) 返回 {"status":"error",...} (无 error 键) 必须被
    识别为失败并透传 error_category, 否则 429/配额耗尽被吞成成功, RateLimitThrottler
    退避与熔断分流在这两源上完全失效。"""

    def test_status_error_without_error_key_is_failure(self):
        raw = {"code": 0, "data": {"status": "error", "message": "FMP 429 rate limited"}}
        r = DataSourceRouter._normalize_response(raw)
        assert r["status"] == "error"
        assert r["success"] is False
        assert "429" in r["message"]

    def test_status_error_propagates_error_category(self):
        raw = {
            "code": 0,
            "data": {
                "status": "error",
                "message": "FMP quota exhausted",
                "error_category": "quota",
            },
        }
        r = DataSourceRouter._normalize_response(raw)
        assert r["status"] == "error"
        assert r.get("error_category") == "quota"

    def test_legacy_error_key_still_failure(self):
        raw = {"code": 0, "data": {"error": "unknown fmp action: FOO"}}
        r = DataSourceRouter._normalize_response(raw)
        assert r["status"] == "error"
        assert "FOO" in r["message"]

    def test_success_body_unaffected(self):
        raw = {"code": 0, "data": {"status": "success", "symbol": "AAPL", "price": 123.4}}
        r = DataSourceRouter._normalize_response(raw)
        assert r["status"] == "success"
        assert r["success"] is True
        assert r["data"]["price"] == 123.4

    def test_nonzero_code_is_failure(self):
        raw = {"code": 500, "message": "boom"}
        r = DataSourceRouter._normalize_response(raw)
        assert r["status"] == "error"


# ==========================================
# BE-ARCH-08e: 单节点 pin 源熔断后半开探测 (避免永久失效)
# ==========================================
class TestPinNodeHalfOpenProbe:
    """验收：pin 源熔断 (status=unhealthy + circuit_breaker_until 未来) 后, 冷却到期应
    允许一次探测 (HALF_OPEN); 冷却未到期仍拦截; healthy 始终放行。"""

    def _make_node(self, status: str, cooldown_until: float) -> DataSourceNode:
        return DataSourceNode(
            name="akshare_remote",
            url="http://x",
            status=status,
            circuit_breaker_until=cooldown_until,
        )

    def test_healthy_always_usable(self):
        n = self._make_node("healthy", 0.0)
        assert DataSourceRouter._pin_node_usable(n) is True

    def test_unhealthy_cooldown_active_blocked(self):
        n = self._make_node("unhealthy", time.time() + 100)
        assert DataSourceRouter._pin_node_usable(n) is False

    def test_unhealthy_cooldown_expired_allows_probe(self):
        n = self._make_node("unhealthy", time.time() - 1)
        assert DataSourceRouter._pin_node_usable(n) is True


# ==========================================
# BE-ARCH-08f: AKShare 远程失败 STALE 降级 (DIST-19 写入只写不读)
# ==========================================
class TestFetchAkshareStaleDegrade:
    """验收：AKShare 远程节点失败时, 应先返回 STALE 缓存 (degraded=true) 而非裸错;
    无 STALE 缓存时才返回裸错。"""

    @pytest.mark.asyncio
    async def test_remote_fail_falls_back_to_stale(self, monkeypatch):
        router = DataSourceRouter()
        router._enabled = True
        node = DataSourceNode(name="akshare_remote", url="http://akshare", status="healthy")
        monkeypatch.setattr(router, "_select_node", lambda s: node)
        monkeypatch.setattr(
            router,
            "_send_request",
            AsyncMock(return_value={"status": "error", "message": "boom"}),
        )
        stale_payload = {"status": "success", "data": {"a": 1}, "degraded": True, "stale_source": True}
        monkeypatch.setattr(router, "_get_akshare_stale", AsyncMock(return_value=stale_payload))

        payload = {"action": "stock_zh_a_spot_em", "params": {}, "kwargs": {}}
        result = await router.fetch_akshare(payload)
        assert result["status"] == "success"
        assert result.get("degraded") is True
        assert result.get("stale_source") is True

    @pytest.mark.asyncio
    async def test_remote_fail_no_stale_returns_error(self, monkeypatch):
        router = DataSourceRouter()
        router._enabled = True
        node = DataSourceNode(name="akshare_remote", url="http://akshare", status="healthy")
        monkeypatch.setattr(router, "_select_node", lambda s: node)
        monkeypatch.setattr(
            router,
            "_send_request",
            AsyncMock(return_value={"status": "error", "message": "boom"}),
        )
        monkeypatch.setattr(router, "_get_akshare_stale", AsyncMock(return_value=None))

        payload = {"action": "stock_zh_a_spot_em", "params": {}, "kwargs": {}}
        result = await router.fetch_akshare(payload)
        assert result["status"] == "error"


# ==========================================
# BE-ARCH-08g: FMP FUNDAMENTAL/INFO 路由打通 (Facade 选到 fmp 不再必失败)
# ==========================================
class TestFmpFundamentalInfoRouting:
    """验收：Facade 的 get_fundamental/get_fundamental_info 以 FUNDAMENTAL/INFO 抵达
    router.fetch_fmp 后, 经 _FMP_ACTION_MAP 映射为子服务 worker 可识别的
    FUNDAMENTAL/INFO action (此前缺失 → worker 返回"未知 fmp action")。"""

    @pytest.mark.asyncio
    async def test_fmp_action_map_fundamental_info(self, monkeypatch):
        router = DataSourceRouter()
        router._enabled = True
        node = DataSourceNode(name="fmp_master", url="http://fmp", status="healthy")
        router._nodes["fmp_master"] = node
        captured = {}
        # 屏蔽 success 分支的 redis 存档 (避免 asyncio.run 嵌套 + 真实 redis)
        monkeypatch.setattr(router, "_save_fmp_profile", AsyncMock())
        monkeypatch.setattr(router, "_save_fmp_cache", AsyncMock())

        async def fake_send(n, source, payload):
            captured["action"] = payload["action"]
            return {"status": "success", "data": {"ok": True}}

        monkeypatch.setattr(router, "_send_request", fake_send)

        await router.fetch_fmp("fundamental", symbol="AAPL")
        assert captured["action"] == "FUNDAMENTAL"
        await router.fetch_fmp("info", symbol="AAPL")
        assert captured["action"] == "INFO"
        # 既有 action 仍映射正确
        await router.fetch_fmp("profile", symbol="AAPL")
        assert captured["action"] == "PROFILE"
