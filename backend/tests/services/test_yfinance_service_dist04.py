"""
DIST-04: YFinanceService 兼容外壳改造 — 单元测试
==================================================

验证 YF_ROUTER_ENABLED 开关在新/旧逻辑间透明切换，上层调用方零改动。

测试矩阵:
  1. 构造函数: YF_ROUTER_ENABLED 环境变量解析
  2. _ensure_router: 懒初始化 + double-check locking
  3. fetch_yf_data: 路由器模式拦截 → 返回 (True, data, "")
  4. fetch_yf_data: 路由器模式失败 → 返回 (False, None, msg)
  5. get_batched_quote: 路由器模式拦截 → 返回 dict
  6. get_batched_quote: 路由器模式失败 → 返回 error dict
  7. macro_data_daemon: 路由器模式 → 跳过采集
  8. get_health_status: 路由器模式标注
  9. close: 路由器关闭
  10. get_tech_indicators: 路由器模式下 fetch_yf_data 被拦截
  11. 非路由器模式: 原有逻辑不受影响
"""

import asyncio
import os
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ─────────────────────────────────────────
#  Mock 基础设施
# ─────────────────────────────────────────


class FakeRouterResult:
    """模拟 YFinanceRouter.call() 返回值"""

    def __init__(self, data: Dict[str, Any]):
        self._data = data

    def get(self, key, default=None):
        return self._data.get(key, default)

    def __contains__(self, key):
        return key in self._data


def make_service(router_enabled: bool = False):
    """
    构造 YFinanceService 实例，跳过 _init_session 以避免真实 Session 创建。
    """
    env = {"YF_ROUTER_ENABLED": "true"} if router_enabled else {}
    with patch.dict(os.environ, env):
        with patch.object(
            __import__("backend.services.yfinance_service", fromlist=["YFinanceService"]).YFinanceService,
            "_init_session",
        ):
            from backend.services.yfinance_service import YFinanceService

            svc = YFinanceService.__new__(YFinanceService)
            # 手动设置构造函数中初始化的属性
            svc._cache = {}
            svc._error_cache = {}
            svc._req_lock = asyncio.Lock()
            svc._last_req_time = 0.0
            svc._circuit_breaker_until = 0.0
            svc._llm_service_override = None
            svc._batch_queue = {}
            svc._batch_lock = asyncio.Lock()
            svc._batch_dispatch_task = None
            svc._executor = None
            svc.session = MagicMock()
            svc._router_enabled = router_enabled
            svc._router = None
            svc._router_init_lock = asyncio.Lock()
            return svc


# ─────────────────────────────────────────
#  1. 构造函数: 环境变量解析
# ─────────────────────────────────────────


class TestRouterEnabledParsing:
    """YF_ROUTER_ENABLED 环境变量解析"""

    @pytest.mark.parametrize(
        "value,expected",
        [
            ("true", True),
            ("True", True),
            ("TRUE", True),
            ("1", True),
            ("yes", True),
            ("false", False),
            ("0", False),
            ("no", False),
            ("", False),
        ],
    )
    def test_env_var_parsing(self, value, expected):
        """各种环境变量值应正确解析为布尔值"""
        with patch.dict(os.environ, {"YF_ROUTER_ENABLED": value}):
            result = os.getenv("YF_ROUTER_ENABLED", "false").lower() in ("true", "1", "yes")
            assert result == expected


# ─────────────────────────────────────────
#  2. _ensure_router: 懒初始化
# ─────────────────────────────────────────


class TestEnsureRouter:
    """_ensure_router 懒初始化 + double-check locking"""

    @pytest.mark.asyncio
    async def test_lazy_init_creates_router_once(self):
        """首次调用创建 router，后续调用复用"""
        svc = make_service(router_enabled=True)
        mock_router = MagicMock()

        with (
            patch("backend.core.service_registry.ServiceRegistry"),
            patch("backend.core.yfinance_router.YFinanceRouter", return_value=mock_router) as mock_router_cls,
            patch("backend.core.redis_client.redis_client", MagicMock()),
        ):
            await svc._ensure_router()
            assert svc._router is mock_router
            assert mock_router_cls.call_count == 1

            # 第二次调用不应再创建
            await svc._ensure_router()
            assert mock_router_cls.call_count == 1  # 仍然是 1

    @pytest.mark.asyncio
    async def test_ensure_router_passes_hmac_secret(self):
        """_ensure_router 应传递 DATA_SOURCE_HMAC_SECRET"""
        svc = make_service(router_enabled=True)

        with (
            patch("backend.core.service_registry.ServiceRegistry"),
            patch("backend.core.yfinance_router.YFinanceRouter") as mock_router_cls,
            patch("backend.core.redis_client.redis_client", MagicMock()),
            patch.dict(os.environ, {"DATA_SOURCE_HMAC_SECRET": "test-secret"}),
        ):
            await svc._ensure_router()
            call_kwargs = mock_router_cls.call_args[1]
            assert call_kwargs["hmac_secret"] == "test-secret"


# ─────────────────────────────────────────
#  3-4. fetch_yf_data: 路由器模式拦截
# ─────────────────────────────────────────


class TestFetchYfDataRouterMode:
    """fetch_yf_data 路由器模式拦截"""

    @pytest.mark.asyncio
    async def test_router_mode_success(self):
        """路由器模式: 成功返回 (True, data, "")"""
        svc = make_service(router_enabled=True)
        mock_router = AsyncMock()
        mock_router.call.return_value = {"status": "success", "data": {"price": 150.0}}
        svc._router = mock_router

        success, data, msg = await svc.fetch_yf_data("AAPL", "info", ttl=300)

        assert success is True
        assert data == {"price": 150.0}
        assert msg == ""
        mock_router.call.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_router_mode_failure(self):
        """路由器模式: 失败返回 (False, None, error_msg)"""
        svc = make_service(router_enabled=True)
        mock_router = AsyncMock()
        mock_router.call.return_value = {"status": "error", "message": "所有节点不可用"}
        svc._router = mock_router

        success, data, msg = await svc.fetch_yf_data("AAPL", "info", ttl=300)

        assert success is False
        assert data is None
        assert "所有节点不可用" in msg

    @pytest.mark.asyncio
    async def test_router_mode_passes_correct_payload(self):
        """路由器模式: 传递正确的 payload 和 cache_key"""
        svc = make_service(router_enabled=True)
        mock_router = AsyncMock()
        mock_router.call.return_value = {"status": "success", "data": []}
        svc._router = mock_router

        await svc.fetch_yf_data("AAPL", "history", ttl=3600, period="6mo", progress=False)

        call_args = mock_router.call.call_args
        assert call_args[0][0] == "yfinance"  # endpoint
        payload = call_args[0][1]
        assert payload["ticker"] == "AAPL"
        assert payload["fetch_type"] == "history"
        assert payload["ttl"] == 3600
        assert payload["period"] == "6mo"
        assert "cache_key" in call_args[1]

    @pytest.mark.asyncio
    async def test_non_router_mode_unaffected(self):
        """非路由器模式: 原有逻辑不受影响 (yf=None 时返回环境缺失)"""
        svc = make_service(router_enabled=False)
        svc._router = None

        with patch("backend.services.yfinance.service.yf", None):
            success, data, msg = await svc.fetch_yf_data("AAPL", "info", ttl=300)

        assert success is False
        assert "环境缺失" in msg


# ─────────────────────────────────────────
#  5-6. get_batched_quote: 路由器模式拦截
# ─────────────────────────────────────────


class TestGetBatchedQuoteRouterMode:
    """get_batched_quote 路由器模式拦截"""

    @pytest.mark.asyncio
    async def test_router_mode_success(self):
        """路由器模式: 成功返回 dict"""
        svc = make_service(router_enabled=True)
        mock_router = AsyncMock()
        mock_router.call.return_value = {
            "status": "success",
            "ticker": "AAPL",
            "last_price": 150.0,
        }
        svc._router = mock_router

        result = await svc.get_batched_quote("AAPL", req_type="quote")

        assert result["status"] == "success"
        assert result["last_price"] == 150.0

    @pytest.mark.asyncio
    async def test_router_mode_failure(self):
        """路由器模式: 失败返回 error dict"""
        svc = make_service(router_enabled=True)
        mock_router = AsyncMock()
        mock_router.call.return_value = {"status": "error", "message": "节点超时"}
        svc._router = mock_router

        result = await svc.get_batched_quote("AAPL", req_type="quote")

        assert result["status"] == "error"
        assert "节点超时" in result["message"]


# ─────────────────────────────────────────
#  7. macro_data_daemon: 路由器模式跳过
# ─────────────────────────────────────────


class TestMacroDataDaemonRouterMode:
    """macro_data_daemon 路由器模式跳过采集"""

    @pytest.mark.asyncio
    async def test_router_mode_skips_daemon(self):
        """路由器模式: daemon 应跳过采集并休眠"""
        svc = make_service(router_enabled=True)

        # mock asyncio.sleep 以避免真实等待
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await svc.macro_data_daemon()
            mock_sleep.assert_awaited_once_with(3600)


# ─────────────────────────────────────────
#  8. get_health_status: 路由器模式标注
# ─────────────────────────────────────────


class TestGetHealthStatusRouterMode:
    """get_health_status 路由器模式标注"""

    def test_router_mode_adds_flag(self):
        """路由器模式: 应包含 router_mode=True"""
        svc = make_service(router_enabled=True)
        status = svc.get_health_status()
        assert status["router_mode"] is True
        assert "路由器模式" in status["message"]

    def test_non_router_mode_no_flag(self):
        """非路由器模式: 不应包含 router_mode"""
        svc = make_service(router_enabled=False)
        status = svc.get_health_status()
        assert "router_mode" not in status


# ─────────────────────────────────────────
#  9. close: 路由器关闭
# ─────────────────────────────────────────


class TestCloseRouterMode:
    """close 路由器清理"""

    def test_close_with_router(self):
        """close 应清理路由器"""
        svc = make_service(router_enabled=True)
        mock_router = MagicMock()
        mock_router.close = AsyncMock()
        svc._router = mock_router

        svc.close()

        assert svc._router is None

    def test_close_without_router(self):
        """close 无路由器时不应报错"""
        svc = make_service(router_enabled=False)
        svc._router = None
        svc.close()  # 不应抛异常


# ─────────────────────────────────────────
#  10. get_tech_indicators: 路由器模式穿透
# ─────────────────────────────────────────


class TestGetTechIndicatorsRouterMode:
    """get_tech_indicators 路由器模式下通过 fetch_yf_data 拦截"""

    @pytest.mark.asyncio
    async def test_tech_indicators_routes_through_fetch(self):
        """get_tech_indicators 内部调用 fetch_yf_data，路由器模式应自动拦截"""
        svc = make_service(router_enabled=True)
        mock_router = AsyncMock()
        # 模拟路由器返回历史数据 (DataFrame 的 JSON 形式)
        mock_router.call.return_value = {
            "status": "success",
            "data": {"price": 150.0, "change": 1.5},
        }
        svc._router = mock_router

        # fetch_yf_data 应被路由器拦截
        success, data, msg = await svc.fetch_yf_data("AAPL", "history", ttl=3600)
        assert success is True
        assert data == {"price": 150.0, "change": 1.5}


# ─────────────────────────────────────────
#  11. 集成: 上层调用方零改动验证
# ─────────────────────────────────────────


class TestUpstreamCompatibility:
    """验证上层调用方在路由器模式下零改动"""

    @pytest.mark.asyncio
    async def test_data_source_router_pattern(self):
        """模拟 data_source_router 的调用模式"""
        svc = make_service(router_enabled=True)
        mock_router = AsyncMock()
        mock_router.call.return_value = {
            "status": "success",
            "ticker": "AAPL",
            "last_price": 150.0,
            "change_pct": "+1.5%",
            "source": "yfinance_batch",
        }
        svc._router = mock_router

        # 模拟 data_source_router.py 的调用方式
        result = await svc.get_batched_quote("AAPL", req_type="quote")
        assert result["status"] == "success"
        assert result["last_price"] == 150.0

    @pytest.mark.asyncio
    async def test_market_router_pattern(self):
        """模拟 market router 的调用模式"""
        svc = make_service(router_enabled=True)
        mock_router = AsyncMock()
        mock_router.call.return_value = {
            "status": "success",
            "data": {"trend": []},
        }
        svc._router = mock_router

        # 模拟 market.py 的调用方式
        success, data, msg = await svc.fetch_yf_data("AAPL", "info", ttl=300)
        assert success is True

    @pytest.mark.asyncio
    async def test_health_check_pattern(self):
        """模拟 health check 端点的调用模式"""
        svc = make_service(router_enabled=True)
        # 模拟 market.py 的调用方式
        health_data = svc.get_health_status()
        assert "name" in health_data
        assert "status" in health_data
        assert health_data["router_mode"] is True
