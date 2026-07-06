"""
Futu 主服务模块单元测试

覆盖：
- FutuService 单例模式
- 各 Handler 的集成调用
- 连接管理
- 异常路径
"""

from unittest.mock import AsyncMock, patch

import pytest

from backend.services.futu.service import FutuService, futu_service


class TestFutuServiceSingleton:
    """FutuService 单例模式"""

    def test_singleton_pattern(self):
        """确保 FutuService 是单例"""
        service1 = FutuService()
        service2 = FutuService()
        assert service1 is service2

    def test_global_instance(self):
        """全局实例 futu_service 是 FutuService 的单例"""
        assert isinstance(futu_service, FutuService)
        assert futu_service is FutuService()

    def test_init_only_once(self):
        """_init() 只执行一次"""
        service = FutuService()
        # 第一次创建时 _init() 被调用
        assert hasattr(service, "conn_mgr")
        assert hasattr(service, "quote_handler")
        assert hasattr(service, "trade_handler")


class TestFutuServiceInit:
    """FutuService 初始化"""

    def test_has_all_handlers(self):
        """初始化后包含所有 Handler"""
        service = FutuService()
        assert hasattr(service, "conn_mgr")
        assert hasattr(service, "cache_mgr")
        assert hasattr(service, "quote_handler")
        assert hasattr(service, "option_fund_handler")
        assert hasattr(service, "screener_handler")
        assert hasattr(service, "trade_handler")

    def test_compat_attrs(self):
        """兼容旧接口的属性"""
        service = FutuService()
        assert hasattr(service, "quote_ctx")
        assert hasattr(service, "trade_ctxs")
        assert hasattr(service, "status")
        assert hasattr(service, "error_msg")


class TestFutuServiceConnect:
    """connect() 连接管理"""

    def test_connect_calls_conn_mgr(self):
        """connect() 调用 ConnectionManager.connect()"""
        service = FutuService()
        with patch.object(service.conn_mgr, "connect") as mock_connect:
            service.connect()
            mock_connect.assert_called_once()

    def test_connect_syncs_status(self):
        """connect() 同步状态到旧接口"""
        service = FutuService()
        with patch.object(service.conn_mgr, "connect"):
            service.conn_mgr.status = "CONNECTED"
            service.conn_mgr.error_msg = ""
            service.connect()
            assert service.status == "CONNECTED"
            assert service.error_msg == ""


class TestFutuServiceClose:
    """close() 关闭连接"""

    def test_close_calls_conn_mgr(self):
        """close() 调用 ConnectionManager.close()"""
        service = FutuService()
        with patch.object(service.conn_mgr, "close") as mock_close:
            service.close()
            mock_close.assert_called_once()

    def test_close_resets_state(self):
        """close() 重置状态"""
        service = FutuService()
        service.quote_ctx = "mock"
        service.trade_ctxs["HK"] = "mock"
        service.status = "CONNECTED"
        service.cache_mgr.touch_topic("HK.00700", "QUOTE")

        service.close()

        assert service.quote_ctx is None
        assert len(service.trade_ctxs) == 0
        assert service.status == "DISCONNECTED"
        assert len(service.cache_mgr.subscribed_topics) == 0


class TestFutuServiceQuoteMethods:
    """行情相关方法"""

    @pytest.mark.asyncio
    async def test_get_quote(self):
        """get_quote() 本地连接时调用 QuoteHandler.get_quote()"""
        from backend.services.futu.utils import format_ticker, is_futu_unsupported

        service = FutuService()
        service.status = "CONNECTED"
        with patch.object(service.quote_handler, "get_quote", new_callable=AsyncMock) as mock:
            mock.return_value = {"data": "quote"}
            result = await service.get_quote("HK.00700")
            mock.assert_called_once_with(
                ticker="HK.00700", format_ticker_func=format_ticker, is_unsupported_func=is_futu_unsupported
            )
            assert result == {"data": "quote"}

    @pytest.mark.asyncio
    async def test_get_quote_cluster_fallback(self):
        """get_quote() 本地未连接时通过 ClusterManager 路由"""
        service = FutuService()
        service.status = "DISCONNECTED"
        with patch.object(service, "_cluster_call", new_callable=AsyncMock) as mock:
            mock.return_value = {"status": "success", "data": "cluster_quote"}
            result = await service.get_quote("HK.00700")
            mock.assert_called_once_with("fetch_quote", {"ticker": "HK.00700"})
            assert result == {"status": "success", "data": "cluster_quote"}

    @pytest.mark.asyncio
    async def test_unsubscribe_quote(self):
        """unsubscribe_quote() 本地连接时调用 QuoteHandler.unsubscribe_quote()"""
        from backend.services.futu.utils import format_ticker

        service = FutuService()
        service.status = "CONNECTED"
        with patch.object(service.quote_handler, "unsubscribe_quote", new_callable=AsyncMock) as mock:
            mock.return_value = {"data": "unsubscribed"}
            result = await service.unsubscribe_quote("HK.00700")
            mock.assert_called_once_with("HK.00700", format_ticker)
            assert result == {"data": "unsubscribed"}

    @pytest.mark.asyncio
    async def test_get_history(self):
        """get_history() 本地连接时调用 QuoteHandler.get_history()"""
        service = FutuService()
        service.status = "CONNECTED"
        with patch.object(service.quote_handler, "get_history", new_callable=AsyncMock) as mock:
            mock.return_value = {"data": "history"}
            result = await service.get_history("HK.00700", "K_DAY", 100)
            mock.assert_called_once_with(ticker="HK.00700", ktype="K_DAY", num=100)
            assert result == {"data": "history"}

    @pytest.mark.asyncio
    async def test_get_order_book(self):
        """get_order_book() 本地连接时调用 QuoteHandler.get_order_book()"""
        from backend.services.futu.utils import format_ticker, is_futu_unsupported

        service = FutuService()
        service.status = "CONNECTED"
        with patch.object(service.quote_handler, "get_order_book", new_callable=AsyncMock) as mock:
            mock.return_value = {"data": "order_book"}
            result = await service.get_order_book("HK.00700")
            mock.assert_called_once_with(
                ticker="HK.00700", format_ticker_func=format_ticker, is_unsupported_func=is_futu_unsupported
            )
            assert result == {"data": "order_book"}


class TestFutuServiceOptionFundMethods:
    """期权和资金相关方法"""

    @pytest.mark.asyncio
    async def test_get_option_chain(self):
        """get_option_chain() 本地连接时调用 OptionFundHandler.get_option_chain()"""
        from backend.services.futu.utils import format_ticker, is_futu_unsupported

        service = FutuService()
        service.status = "CONNECTED"
        with patch.object(service.option_fund_handler, "get_option_chain", new_callable=AsyncMock) as mock:
            mock.return_value = {"data": "option_chain"}
            result = await service.get_option_chain("HK.00700", "2024-12-31")
            mock.assert_called_once_with(
                ticker="HK.00700",
                expiration_date="2024-12-31",
                format_ticker_func=format_ticker,
                is_unsupported_func=is_futu_unsupported,
            )
            assert result == {"data": "option_chain"}

    @pytest.mark.asyncio
    async def test_get_fund_flow(self):
        """get_fund_flow() 本地连接时调用 OptionFundHandler.get_fund_flow()"""
        from backend.services.futu.utils import format_ticker, is_futu_unsupported

        service = FutuService()
        service.status = "CONNECTED"
        with patch.object(service.option_fund_handler, "get_fund_flow", new_callable=AsyncMock) as mock:
            mock.return_value = {"data": "fund_flow"}
            result = await service.get_fund_flow("HK.00700")
            mock.assert_called_once_with(
                ticker="HK.00700", format_ticker_func=format_ticker, is_unsupported_func=is_futu_unsupported
            )
            assert result == {"data": "fund_flow"}

    @pytest.mark.asyncio
    async def test_get_fundamental(self):
        """get_fundamental() 本地连接时调用 OptionFundHandler.get_fundamental()"""
        from backend.services.futu.utils import format_ticker, is_futu_unsupported

        service = FutuService()
        service.status = "CONNECTED"
        with patch.object(service.option_fund_handler, "get_fundamental", new_callable=AsyncMock) as mock:
            mock.return_value = {"data": "fundamental"}
            result = await service.get_fundamental("HK.00700")
            mock.assert_called_once_with(
                ticker="HK.00700", format_ticker_func=format_ticker, is_unsupported_func=is_futu_unsupported
            )
            assert result == {"data": "fundamental"}


class TestFutuServiceScreenerMethods:
    """选股相关方法"""

    @pytest.mark.asyncio
    async def test_get_market_snapshots(self):
        """get_market_snapshots() 本地连接时调用 ScreenerHandler.get_market_snapshots()"""
        service = FutuService()
        service.status = "CONNECTED"
        with patch.object(service.screener_handler, "get_market_snapshots", new_callable=AsyncMock) as mock:
            mock.return_value = {"data": "snapshots"}
            result = await service.get_market_snapshots(["HK.00700", "HK.09988"])
            mock.assert_called_once_with(tickers=["HK.00700", "HK.09988"])
            assert result == {"data": "snapshots"}

    @pytest.mark.asyncio
    async def test_screen_stocks(self):
        """screen_stocks() 本地连接时调用 ScreenerHandler.screen_stocks()"""
        service = FutuService()
        service.status = "CONNECTED"
        with patch.object(service.screener_handler, "screen_stocks", new_callable=AsyncMock) as mock:
            mock.return_value = {"data": "screened"}
            result = await service.screen_stocks("HK", [{"field": "pe", "op": "<", "value": 20}])
            mock.assert_called_once_with(market="HK", filters=[{"field": "pe", "op": "<", "value": 20}])
            assert result == {"data": "screened"}

    @pytest.mark.asyncio
    async def test_get_stock_basicinfo(self):
        """get_stock_basicinfo() 本地连接时调用 ScreenerHandler.get_stock_basicinfo()"""
        service = FutuService()
        service.status = "CONNECTED"
        with patch.object(service.screener_handler, "get_stock_basicinfo", new_callable=AsyncMock) as mock:
            mock.return_value = {"data": "basicinfo"}
            result = await service.get_stock_basicinfo("HK", "STOCK")
            mock.assert_called_once_with(market="HK", sec_type="STOCK")
            assert result == {"data": "basicinfo"}


class TestFutuServiceTradeMethods:
    """交易相关方法"""

    @pytest.mark.asyncio
    async def test_place_order(self):
        """place_order() 调用 TradeHandler.place_order()"""
        from futu import TrdMarket, TrdSide

        from backend.services.futu.utils import format_ticker

        service = FutuService()
        with patch.object(service.trade_handler, "place_order", new_callable=AsyncMock) as mock:
            mock.return_value = {"data": "order_placed"}
            result = await service.place_order("HK.00700", 100, 50.0, TrdSide.BUY, TrdMarket.HK)
            mock.assert_called_once_with("HK.00700", 100, 50.0, TrdSide.BUY, TrdMarket.HK, format_ticker)
            assert result == {"data": "order_placed"}

    @pytest.mark.asyncio
    async def test_modify_order(self):
        """modify_order() 调用 TradeHandler.modify_order()"""
        from futu import ModifyOrderOp, TrdMarket

        service = FutuService()
        with patch.object(service.trade_handler, "modify_order", new_callable=AsyncMock) as mock:
            mock.return_value = {"data": "order_modified"}
            result = await service.modify_order("12345", ModifyOrderOp.NORMAL, TrdMarket.HK)
            mock.assert_called_once_with("12345", ModifyOrderOp.NORMAL, TrdMarket.HK)
            assert result == {"data": "order_modified"}

    @pytest.mark.asyncio
    async def test_query_order(self):
        """query_order() 调用 TradeHandler.query_order()"""
        from futu import TrdMarket

        service = FutuService()
        with patch.object(service.trade_handler, "query_order", new_callable=AsyncMock) as mock:
            mock.return_value = {"data": "order_queried"}
            result = await service.query_order("12345", TrdMarket.HK)
            mock.assert_called_once_with("12345", TrdMarket.HK)
            assert result == {"data": "order_queried"}

    @pytest.mark.asyncio
    async def test_get_account_info(self):
        """get_account_info() 本地连接时调用 TradeHandler.get_account_info()"""
        service = FutuService()
        service.status = "CONNECTED"
        with patch.object(service.trade_handler, "get_account_info", new_callable=AsyncMock) as mock:
            mock.return_value = {"data": "account_info"}
            result = await service.get_account_info("HK")
            mock.assert_called_once_with(market="HK")
            assert result == {"data": "account_info"}


class TestFutuServiceUtils:
    """工具方法"""

    def test_is_futu_unsupported(self):
        """is_futu_unsupported() 正确判断"""

        service = FutuService()
        # 测试包装方法正确调用底层函数
        with patch("backend.services.futu.service.is_futu_unsupported", return_value=True) as mock_func:
            result = service.is_futu_unsupported("HK.00700")
            mock_func.assert_called_once_with("HK.00700")
            assert result is True

    def test_format_ticker(self):
        """format_ticker() 正确格式化"""

        service = FutuService()
        # 测试包装方法正确调用底层函数
        with patch("backend.services.futu.service.format_ticker", return_value="HK.00700") as mock_func:
            result = service.format_ticker("00700")
            mock_func.assert_called_once_with("00700")
            assert result == "HK.00700"


class TestFutuServiceRoute:
    """_route() 统一路由逻辑"""

    @pytest.mark.asyncio
    async def test_route_local_connected_uses_local(self):
        """本地连接时直接走 handler，不调用 cluster"""
        service = FutuService()
        service.status = "CONNECTED"
        mock_handler = AsyncMock(return_value={"status": "success", "data": "local"})

        with patch.object(service, "_cluster_call", new_callable=AsyncMock) as mock_cluster:
            result = await service._route("fetch_quote", {"ticker": "HK.00700"}, mock_handler, ticker="HK.00700")

        mock_handler.assert_called_once_with(ticker="HK.00700")
        mock_cluster.assert_not_called()
        assert result == {"status": "success", "data": "local"}

    @pytest.mark.asyncio
    async def test_route_local_handler_exception_falls_to_cluster(self):
        """本地 handler 抛异常后降级到 cluster"""
        service = FutuService()
        service.status = "CONNECTED"
        mock_handler = AsyncMock(side_effect=RuntimeError("OpenD timeout"))

        with patch.object(service, "_cluster_call", new_callable=AsyncMock) as mock_cluster:
            mock_cluster.return_value = {"status": "success", "data": "from_slave"}
            result = await service._route("fetch_quote", {"ticker": "HK.00700"}, mock_handler, ticker="HK.00700")

        mock_handler.assert_called_once()
        mock_cluster.assert_called_once_with("fetch_quote", {"ticker": "HK.00700"})
        assert result == {"status": "success", "data": "from_slave"}

    @pytest.mark.asyncio
    async def test_route_local_disconnected_uses_cluster(self):
        """本地未连接时走 cluster_call"""
        service = FutuService()
        service.status = "DISCONNECTED"
        mock_handler = AsyncMock()

        with patch.object(service, "_cluster_call", new_callable=AsyncMock) as mock_cluster:
            mock_cluster.return_value = {"status": "success", "data": "slave_data"}
            result = await service._route("fetch_history", {"ticker": "US.AAPL"}, mock_handler, ticker="US.AAPL")

        mock_handler.assert_not_called()
        mock_cluster.assert_called_once_with("fetch_history", {"ticker": "US.AAPL"})
        assert result == {"status": "success", "data": "slave_data"}

    @pytest.mark.asyncio
    async def test_route_all_failed_returns_unavailable(self):
        """本地和 cluster 都失败返回 error"""
        service = FutuService()
        service.status = "DISCONNECTED"
        mock_handler = AsyncMock()

        with patch.object(service, "_cluster_call", new_callable=AsyncMock) as mock_cluster:
            mock_cluster.return_value = None
            result = await service._route("fetch_quote", {"ticker": "HK.00700"}, mock_handler, ticker="HK.00700")

        assert result["status"] == "error"
        assert "无可用远程节点" in result["message"]

    @pytest.mark.asyncio
    async def test_route_no_recursive_dispatch(self):
        """防递归重入: _in_cluster_dispatch=True 时不再调用 _cluster_call"""
        service = FutuService()
        service.status = "DISCONNECTED"
        service._in_cluster_dispatch = True  # 模拟已在 cluster dispatch 中
        mock_handler = AsyncMock()

        with patch.object(service, "_cluster_call", new_callable=AsyncMock) as mock_cluster:
            result = await service._route("fetch_quote", {"ticker": "HK.00700"}, mock_handler, ticker="HK.00700")

        mock_handler.assert_not_called()
        mock_cluster.assert_not_called()  # 应该被拦截，不再调用
        assert result["status"] == "error"
        # 清理
        service._in_cluster_dispatch = False


class TestFutuServiceClusterCall:
    """_cluster_call() 集群路由"""

    @pytest.mark.asyncio
    async def test_cluster_call_success(self):
        """cluster_call 正常返回"""
        service = FutuService()
        mock_cm = AsyncMock()
        mock_cm.call_collector = AsyncMock(return_value={"code": 0, "data": {"price": 100}})

        with patch("backend.services.futu.service.cluster_manager", mock_cm, create=True):
            with patch("backend.workers.cluster_manager.cluster_manager", mock_cm, create=True):
                result = await service._cluster_call("fetch_quote", {"ticker": "HK.00700"})

        assert result is not None
        assert result["status"] == "success"
        assert result["price"] == 100

    @pytest.mark.asyncio
    async def test_cluster_call_no_cluster_manager(self):
        """ClusterManager 不可用时返回 None"""
        service = FutuService()

        with patch("backend.workers.cluster_manager.cluster_manager") as mock_cm:
            mock_cm.call_collector = AsyncMock(side_effect=RuntimeError("no cluster"))
            result = await service._cluster_call("fetch_quote", {"ticker": "HK.00700"})

        assert result is None
