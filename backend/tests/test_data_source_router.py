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


# ==========================================
# BE-ARCH-08i: action 级熔断隔离 + 节点级兜底
# ==========================================
class TestActionLevelCircuitBreaker:
    """验收：单节点 pin 源某 action 连续失败只熔断该 action，不影响同节点其它 action；
    仅当多个不同 action 同时熔断（进程级故障）才整节点熔断兜底。"""

    def _setup_fred_node(self, router) -> None:
        node = DataSourceNode(name="fred_master", url="http://fred", status="healthy")
        router._nodes["fred_master"] = node

    def test_single_action_failure_breaks_only_that_action(self, router_enabled):
        self._setup_fred_node(router_enabled)
        # MACRO_SERIES 连续失败 3 次 → 仅熔断 MACRO_SERIES
        for _ in range(3):
            asyncio.run(
                router_enabled._update_node_status("fred_master", success=False, error="boom", action="MACRO_SERIES")
            )
        node = router_enabled._nodes["fred_master"]
        # 节点本身保持 healthy，其它 action 不受影响
        assert node.status == "healthy"
        # MACRO_SERIES 已熔断（冷却截止在未来）
        assert router_enabled._action_usable(node, "MACRO_SERIES") is False
        # 其它 action 仍可用
        assert router_enabled._action_usable(node, "ECONOMIC_CALENDAR") is True

    def test_multiple_actions_failure_triggers_node_breaker(self, router_enabled):
        self._setup_fred_node(router_enabled)
        # 两个不同 action 各自连续失败 → 触发节点级兜底熔断
        for _ in range(3):
            asyncio.run(
                router_enabled._update_node_status("fred_master", success=False, error="boom", action="MACRO_SERIES")
            )
        for _ in range(3):
            asyncio.run(
                router_enabled._update_node_status(
                    "fred_master", success=False, error="boom", action="ECONOMIC_CALENDAR"
                )
            )
        node = router_enabled._nodes["fred_master"]
        assert node.status == "unhealthy"
        assert node.circuit_breaker_until > time.time()

    def test_action_success_resets_action_error(self, router_enabled):
        self._setup_fred_node(router_enabled)
        # 2 次失败（未达阈值）后 1 次成功 → 重置该 action 计数
        asyncio.run(router_enabled._update_node_status("fred_master", success=False, error="e1", action="MACRO_SERIES"))
        asyncio.run(router_enabled._update_node_status("fred_master", success=False, error="e2", action="MACRO_SERIES"))
        asyncio.run(router_enabled._update_node_status("fred_master", success=True, action="MACRO_SERIES"))
        node = router_enabled._nodes["fred_master"]
        assert "MACRO_SERIES" not in node.action_errors
        assert router_enabled._action_usable(node, "MACRO_SERIES") is True

    def test_rate_limit_error_does_not_count_action(self, router_enabled):
        self._setup_fred_node(router_enabled)
        for _ in range(5):
            asyncio.run(
                router_enabled._update_node_status(
                    "fred_master",
                    success=False,
                    error="429",
                    error_category=ErrorCategory.RATE_LIMIT,
                    action="MACRO_SERIES",
                )
            )
        node = router_enabled._nodes["fred_master"]
        # 限流类错误不计入 action 熔断计数
        assert node.action_errors.get("MACRO_SERIES", 0) == 0
        assert node.status == "healthy"
        assert router_enabled._action_usable(node, "MACRO_SERIES") is True

    def test_legacy_no_action_call_degrades_to_node_level(self, router_enabled):
        self._setup_fred_node(router_enabled)
        # 旧调用点（不传 action）保持原节点级熔断行为
        for _ in range(3):
            asyncio.run(router_enabled._update_node_status("fred_master", success=False, error="err"))
        node = router_enabled._nodes["fred_master"]
        assert node.status == "unhealthy"


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

    def test_get_health_status_exposes_action_breakers(self, router_enabled):
        """BE-ARCH-08i: health 接口暴露 action 级熔断状态"""
        node = DataSourceNode(name="fred_master", url="http://fred", status="healthy")
        router_enabled._nodes["fred_master"] = node
        # MACRO_SERIES 熔断（冷却未到期），ECONOMIC_CALENDAR 正常
        node.action_breaker_until["MACRO_SERIES"] = time.time() + 60
        node.action_errors["MACRO_SERIES"] = 3
        node.action_errors["ECONOMIC_CALENDAR"] = 1

        status = asyncio.run(router_enabled.get_health_status())
        fred = status["nodes"]["fred_master"]

        # 冷却未到期的 action 出现在 action_breakers，且剩余冷却 > 0
        assert "MACRO_SERIES" in fred["action_breakers"]
        assert fred["action_breakers"]["MACRO_SERIES"] > 0
        # 未熔断的 action 不出现
        assert "ECONOMIC_CALENDAR" not in fred["action_breakers"]
        # action_error_counts 完整暴露各 action 的失败计数
        assert fred["action_error_counts"]["MACRO_SERIES"] == 3
        assert fred["action_error_counts"]["ECONOMIC_CALENDAR"] == 1

    def test_get_health_status_action_breaker_expired_not_exposed(self, router_enabled):
        """冷却已过期的 action 不再出现在 action_breakers"""
        node = DataSourceNode(name="fred_master", url="http://fred", status="healthy")
        router_enabled._nodes["fred_master"] = node
        node.action_breaker_until["MACRO_SERIES"] = time.time() - 1  # 已过期

        status = asyncio.run(router_enabled.get_health_status())
        fred = status["nodes"]["fred_master"]
        assert "MACRO_SERIES" not in fred["action_breakers"]


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
        router._nodes["akshare_remote"] = node  # fetch_akshare 走 _nodes.get("akshare_remote")
        monkeypatch.setattr(
            router,
            "_send_request",
            AsyncMock(return_value={"status": "error", "message": "boom"}),
        )
        stale_payload = {"status": "success", "data": {"a": 1}, "degraded": True, "stale_source": True}
        monkeypatch.setattr(router, "_get_akshare_stale", AsyncMock(return_value=stale_payload))

        result = await router.fetch_akshare("stock_zh_a_spot_em")
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

        result = await router.fetch_akshare("stock_zh_a_spot_em")
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


# ==========================================
# RL-14: 部署重置 (熔断清零) + 半开自愈探针 (熔断节点自动恢复)
# ==========================================
class TestRL14DeployResetAndSelfHeal:
    """验收 (复盘 2026-08 实战故障: 改 FUTU_REMOTE_URL 重启后老进程熔断态
    (error_count=41, status=unhealthy) 驻留内存不自愈, 导致 QUOTE 持续
    "所有候选源失败", 必须 force-recreate 才恢复)。

    修复后:
    1. 进程启动即 reset_circuit_breakers(), 新进程从干净状态开始 (部署重置)。
    2. 后台半开探针 _probe_loop 持续探活熔断节点, 恢复则复位为 healthy。
    """

    def test_deploy_reset_clears_circuit_breakers(self):
        """部署重置: 构造一个已熔断污染的节点, 调用 reset 后应全部清零。"""
        router = DataSourceRouter()
        node = router._nodes["yf_primary"]
        # 模拟上一次运行累积的熔断残留
        node.status = "unhealthy"
        node.error_count = 41
        node.circuit_breaker_until = time.time() + 999
        node.probe_consecutive_failures = 7

        router.reset_circuit_breakers()

        assert node.status == "healthy"
        assert node.error_count == 0
        assert node.circuit_breaker_until == 0.0
        assert node.probe_consecutive_failures == 0

    def test_deploy_reset_clears_all_nodes(self):
        """部署重置必须覆盖所有节点, 而非单个。"""
        router = DataSourceRouter()
        for n in router._nodes.values():
            n.status = "unhealthy"
            n.error_count = 99
            n.circuit_breaker_until = time.time() + 999
        router.reset_circuit_breakers()
        for n in router._nodes.values():
            assert n.status == "healthy"
            assert n.error_count == 0
            assert n.circuit_breaker_until == 0.0

    @pytest.mark.asyncio
    async def test_probe_recovers_unhealthy_node(self, monkeypatch):
        """自愈探针: 节点 unhealthy 且 /health 探活成功 -> 复位 healthy。"""
        router = DataSourceRouter()
        node = router._nodes["yf_primary"]
        node.status = "unhealthy"
        node.error_count = 30
        node.circuit_breaker_until = time.time() + 100

        # mock 探活成功
        async def fake_probe(n):
            return True

        monkeypatch.setattr(router, "_probe_node", fake_probe)

        await router._probe_once()

        assert node.status == "healthy"
        assert node.error_count == 0
        assert node.circuit_breaker_until == 0.0

    @pytest.mark.asyncio
    async def test_probe_skips_healthy_node(self, monkeypatch):
        """自愈探针: 全 healthy 时不应发起任何探活请求。"""
        router = DataSourceRouter()
        for n in router._nodes.values():
            n.status = "healthy"
            n.circuit_breaker_until = 0.0

        called = {"probe": 0}

        async def fake_probe(n):
            called["probe"] += 1
            return True

        monkeypatch.setattr(router, "_probe_node", fake_probe)

        await router._probe_once()
        assert called["probe"] == 0, "healthy 节点不应被探针打扰"

    @pytest.mark.asyncio
    async def test_probe_keeps_unhealthy_on_failure(self, monkeypatch):
        """自愈探针: 探活持续失败 -> 维持 unhealthy, 但冷却不续期 (由真实请求失败续期)。"""
        router = DataSourceRouter()
        node = router._nodes["yf_primary"]
        node.status = "unhealthy"
        node.error_count = 30
        cb_until_before = time.time() - 1  # 已到期
        node.circuit_breaker_until = cb_until_before

        async def fake_probe(n):
            return False

        monkeypatch.setattr(router, "_probe_node", fake_probe)

        await router._probe_once()

        assert node.status == "unhealthy"
        # 冷却不续期: 仍 <= 之前的值, 让冷却自然到期后可被 _pin_node_usable 放行重试
        assert node.circuit_breaker_until <= cb_until_before

    def test_start_probing_disabled_skipped(self):
        """路由禁用时 start_probing 应静默跳过 (不创建后台任务, 不抛错)。"""
        router = DataSourceRouter()
        assert router._enabled is False
        router._probe_task = None
        router._shutdown_event = asyncio.Event()
        router.start_probing()  # 禁用态 -> 直接 return
        assert router._probe_task is None

    @pytest.mark.asyncio
    async def test_start_probing_runs_under_running_loop(self):
        """路由启用 + running loop 下, start_probing 应真实拉起后台探针任务。"""
        with patch.dict(
            os.environ,
            {
                "DATA_SOURCE_ROUTER_ENABLED": "true",
                "DATA_SOURCE_HMAC_SECRET": "test-verify-secret",
            },
        ):
            router = DataSourceRouter()
        router.start_probing()
        assert router._probe_task is not None
        assert not router._probe_task.done()
        await router.stop_probing()
        assert router._probe_task is None
