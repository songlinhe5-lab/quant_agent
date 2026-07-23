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

from backend.services.data_source_router import DataSourceNode, DataSourceRouter
from backend.services.datasource import ErrorCategory


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

    def test_sign_request_no_secret(self, router):
        """无密钥时签名为空"""
        sig = router._sign_request({"key": "value"}, "12345")
        assert sig == ""

    def test_sign_request_with_secret(self):
        """有密钥时生成签名"""
        with patch.dict(os.environ, {"DATA_SOURCE_HMAC_SECRET": "test-secret", "DATA_SOURCE_ROUTER_ENABLED": "false"}):
            r = DataSourceRouter()
        sig = r._sign_request({"key": "value"}, "12345")
        assert len(sig) == 64  # SHA256 hex

    def test_get_healthy_nodes(self, router):
        """获取健康节点"""
        with patch("backend.services.data_source_router.rate_limit_registry") as mock_rl:
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
        with patch("backend.services.data_source_router.rate_limit_registry") as mock_rl:
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
        with patch("backend.services.data_source_router.rate_limit_registry") as mock_rl:
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
        with patch("backend.services.data_source_router.rate_limit_registry") as mock_rl:
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
        """路由禁用时走本地"""
        with patch("backend.services.data_source_router.yf_service", create=True) as mock_yf:
            mock_yf.get_batched_quote = AsyncMock(return_value={"status": "success", "data": {}})
            with patch.dict("sys.modules", {"backend.services.yfinance_service": MagicMock(yf_service=mock_yf)}):
                result = await router.fetch_yfinance("AAPL", "quote")
        assert result.get("status") == "success"

    @pytest.mark.asyncio
    async def test_fetch_yfinance_local(self, router):
        """本地 yfinance 降级"""
        with patch("backend.services.data_source_router.yf_service", create=True) as mock_yf:
            mock_yf.get_batched_quote = AsyncMock(return_value={"status": "success"})
            with patch.dict("sys.modules", {"backend.services.yfinance_service": MagicMock(yf_service=mock_yf)}):
                result = await router.fetch_yfinance_local("AAPL", "quote")
        assert result.get("status") == "success"

    @pytest.mark.asyncio
    async def test_fetch_yfinance_local_unknown_type(self, router):
        """未知 fetch_type"""
        with patch("backend.services.data_source_router.yf_service", create=True) as mock_yf:
            with patch.dict("sys.modules", {"backend.services.yfinance_service": MagicMock(yf_service=mock_yf)}):
                result = await router.fetch_yfinance_local("AAPL", "unknown_type")
        assert result.get("success") is False

    @pytest.mark.asyncio
    async def test_fetch_yfinance_local_exception(self, router):
        """本地 yfinance 异常"""
        with patch("backend.services.data_source_router.yf_service", create=True) as mock_yf:
            mock_yf.get_batched_quote = AsyncMock(side_effect=Exception("连接失败"))
            with patch.dict("sys.modules", {"backend.services.yfinance_service": MagicMock(yf_service=mock_yf)}):
                result = await router.fetch_yfinance_local("AAPL", "quote")
        assert result.get("success") is False

    @pytest.mark.asyncio
    async def test_call_local_akshare_southbound(self, router):
        """本地 AKShare 南向资金"""
        mock_ak = MagicMock()
        mock_ak.get_southbound_flow = AsyncMock(return_value={"status": "success"})
        result = await router._call_local_akshare("southbound", mock_ak)
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_call_local_akshare_northbound(self, router):
        """本地 AKShare 北向资金"""
        mock_ak = MagicMock()
        mock_ak.get_northbound_flow = AsyncMock(return_value={"status": "success"})
        result = await router._call_local_akshare("northbound", mock_ak)
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_call_local_akshare_unknown(self, router):
        """未知 action"""
        mock_ak = MagicMock()
        result = await router._call_local_akshare("unknown_action", mock_ak)
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_call_local_akshare_exception(self, router):
        """AKShare 异常"""
        mock_ak = MagicMock()
        mock_ak.get_southbound_flow = AsyncMock(side_effect=Exception("网络错误"))
        result = await router._call_local_akshare("southbound", mock_ak)
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_save_akshare_stale(self, router):
        """保存 STALE 缓存"""
        with patch("backend.services.data_source_router.redis_client", create=True) as mock_redis:
            mock_redis.set = AsyncMock()
            with patch.dict("sys.modules", {"backend.core.redis_client": MagicMock(redis_client=mock_redis)}):
                await router._save_akshare_stale("southbound", {}, {"status": "success"})

    @pytest.mark.asyncio
    async def test_get_akshare_stale_hit(self, router):
        """STALE 缓存命中"""
        cached = json.dumps({"status": "success", "data": [1, 2, 3]})
        with patch("backend.services.data_source_router.redis_client", create=True) as mock_redis:
            mock_redis.get = AsyncMock(return_value=cached)
            with patch.dict("sys.modules", {"backend.core.redis_client": MagicMock(redis_client=mock_redis)}):
                result = await router._get_akshare_stale("southbound", {})
        assert result is not None
        assert result["degraded"] is True
        assert result["stale_source"] is True

    @pytest.mark.asyncio
    async def test_get_akshare_stale_miss(self, router):
        """STALE 缓存未命中"""
        with patch("backend.services.data_source_router.redis_client", create=True) as mock_redis:
            mock_redis.get = AsyncMock(return_value=None)
            with patch.dict("sys.modules", {"backend.core.redis_client": MagicMock(redis_client=mock_redis)}):
                result = await router._get_akshare_stale("southbound", {})
        assert result is None

    @pytest.mark.asyncio
    async def test_get_health_status(self, router):
        """健康状态"""
        with patch("backend.services.data_source_router.rate_limit_registry") as mock_rl:
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


"""
Tests for backend/services/data_source_router.py

Coverage targets:
- DataSourceNode dataclass
- DataSourceRouter initialization
- HMAC signature generation
- HTTP client lazy loading
- Node selection and health filtering
- Circuit breaker mechanism
- YFinance fetch (local + remote)
- AKShare fetch (local + remote)
- Health status endpoint
"""

import asyncio
import os
import time
from unittest.mock import patch

import pytest

from backend.services.data_source_router import DataSourceNode, DataSourceRouter


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


class TestDataSourceNode:
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
        assert "yf_backup" in router_enabled._nodes
        assert "akshare_remote" in router_enabled._nodes

    def test_nodes_capabilities(self, router_enabled):
        yf_primary = router_enabled._nodes["yf_primary"]
        assert "yfinance" in yf_primary.capabilities

        akshare = router_enabled._nodes["akshare_remote"]
        assert "akshare" in akshare.capabilities


class TestHmacSignature:
    def test_sign_request_with_secret(self, router_enabled):
        payload = {"ticker": "AAPL", "fetch_type": "quote"}
        timestamp = "1234567890"
        signature = router_enabled._sign_request(payload, timestamp)
        assert isinstance(signature, str)
        assert len(signature) == 64

    def test_sign_request_without_secret(self, router_disabled):
        payload = {"ticker": "AAPL"}
        signature = router_disabled._sign_request(payload, "1234567890")
        assert signature == ""

    def test_sign_request_consistent(self, router_enabled):
        payload = {"key": "value", "num": 123}
        timestamp = "1234567890"
        sig1 = router_enabled._sign_request(payload, timestamp)
        sig2 = router_enabled._sign_request(payload, timestamp)
        assert sig1 == sig2

    def test_sign_request_with_timestamp(self, router_enabled):
        payload = {"ticker": "AAPL"}
        sig1 = router_enabled._sign_request(payload, "1234567890")
        sig2 = router_enabled._sign_request(payload, "0987654321")
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
        router_enabled._nodes["yf_backup"].weight = 5
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
    @patch("backend.services.yfinance_service.YFinanceService.get_batched_quote")
    def test_fetch_yfinance_disabled_router(self, mock_method, router_disabled):
        mock_method.return_value = {"success": True, "data": {}}
        result = asyncio.run(router_disabled.fetch_yfinance("AAPL", "quote"))
        assert result["success"] is True
        mock_method.assert_called_once()

    @patch("backend.services.data_source_router.DataSourceRouter._send_request")
    def test_fetch_yfinance_remote_success(self, mock_send, router_enabled):
        mock_send.return_value = {"success": True, "data": {"price": 165.0}}
        result = asyncio.run(router_enabled.fetch_yfinance("AAPL", "history", period="1d"))
        assert result["success"] is True
        assert result["data"]["price"] == 165.0

    @patch("backend.services.data_source_router.DataSourceRouter._send_request")
    def test_fetch_yfinance_rate_limit_switch(self, mock_send, router_enabled):
        mock_send.side_effect = [
            {"success": False, "message": "429 Rate Limit"},
            {"success": True, "data": {"price": 165.0}},
        ]
        result = asyncio.run(router_enabled.fetch_yfinance("AAPL", "history", period="1d"))
        assert result["success"] is True
        assert mock_send.call_count == 2

    @patch("backend.services.data_source_router.DataSourceRouter._send_request")
    @patch("backend.services.yfinance_service.YFinanceService.fetch_yf_data")
    def test_fetch_yfinance_fallback_local(self, mock_method, mock_send, router_enabled):
        mock_send.side_effect = Exception("Network error")
        mock_method.return_value = (True, {"price": 165.0}, "")
        result = asyncio.run(router_enabled.fetch_yfinance("AAPL", "history", period="1d"))
        assert result["success"] is True


class TestFetchAKShare:
    @patch("backend.services.akshare_service.AKShareService.get_southbound_flow")
    def test_fetch_akshare_disabled_router(self, mock_method, router_disabled):
        mock_method.return_value = {"status": "success", "data": {}}
        result = asyncio.run(router_disabled.fetch_akshare("southbound"))
        assert result["status"] == "success"

    @patch("backend.services.data_source_router.DataSourceRouter._send_request")
    def test_fetch_akshare_remote_success(self, mock_send, router_enabled):
        mock_send.return_value = {"status": "success", "data": {"flow": 100}}
        result = asyncio.run(router_enabled.fetch_akshare("southbound"))
        assert result["status"] == "success"

    @patch("backend.services.data_source_router.DataSourceRouter._send_request")
    @patch("backend.services.akshare_service.AKShareService.get_southbound_flow")
    def test_fetch_akshare_fallback_local(self, mock_method, mock_send, router_enabled):
        mock_send.side_effect = Exception("Connection refused")
        mock_method.return_value = {"status": "success", "data": {}}
        result = asyncio.run(router_enabled.fetch_akshare("southbound"))
        assert result["status"] == "success"


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
