"""
Futu Service 主服务单元测试
覆盖: 单例模式/connect/close/方法委托
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from futu import ModifyOrderOp, TrdMarket, TrdSide

from backend.services.futu.service import FutuService


class TestFutuService:
    """FutuService 主服务测试套件"""

    def test_singleton_returns_same_instance(self):
        """FutuService 应为单例"""
        svc1 = FutuService()
        svc2 = FutuService()
        assert svc1 is svc2

    def test_init_creates_handlers(self):
        """初始化应创建所有子 handler"""
        svc = FutuService()
        assert svc.conn_mgr is not None
        assert svc.cache_mgr is not None
        assert svc.quote_handler is not None
        assert svc.option_fund_handler is not None
        assert svc.trade_handler is not None
        assert svc.screener_handler is not None

    def test_is_futu_unsupported_delegates_to_utils(self):
        """is_futu_unsupported 应直接委托给 utils 函数"""
        svc = FutuService()
        assert svc.is_futu_unsupported("GC=F") is True
        assert svc.is_futu_unsupported("HK.00700") is False

    def test_format_ticker_delegates_to_utils(self):
        """format_ticker 应直接委托给 utils 函数"""
        svc = FutuService()
        assert svc.format_ticker("0700") == "US.0700"
        assert svc.format_ticker("HK.0700") == "HK.00700"
        assert svc.format_ticker("HSI") == "HK.800000"

    def test_connect_delegates_to_conn_mgr_and_syncs_state(self):
        """connect 应调用 conn_mgr.connect 并同步状态"""
        svc = FutuService()
        with patch.object(svc.conn_mgr, "connect") as mock_connect:
            svc.conn_mgr.status = "CONNECTED"
            svc.conn_mgr.quote_ctx = MagicMock()
            svc.conn_mgr.error_msg = ""
            svc.connect()
        mock_connect.assert_called_once()
        assert svc.status == "CONNECTED"
        assert svc.quote_ctx is svc.conn_mgr.quote_ctx

    def test_close_delegates_to_conn_mgr_and_clears_state(self):
        """close 应调用 conn_mgr.close 并清空状态"""
        svc = FutuService()
        svc.cache_mgr.subscribed_topics.add(("HK.00700", "QUOTE"))
        with patch.object(svc.conn_mgr, "close") as mock_close:
            svc.close()
        mock_close.assert_called_once()
        assert svc.quote_ctx is None
        assert svc.status == "DISCONNECTED"
        assert len(svc.cache_mgr.subscribed_topics) == 0

    @pytest.mark.asyncio
    async def test_get_quote_delegates_to_quote_handler(self):
        """get_quote 应委托给 quote_handler.get_quote"""
        svc = FutuService()
        with patch.object(
            svc.quote_handler, "get_quote", new=AsyncMock(return_value={"status": "success"})
        ) as mock_method:
            result = await svc.get_quote("HK.00700")
        mock_method.assert_awaited_once()
        args, _ = mock_method.call_args
        # 第一个参数是 ticker，第二和第三参数是 format_ticker/is_futu_unsupported
        assert args[0] == "HK.00700"
        assert callable(args[1])
        assert callable(args[2])
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_unsubscribe_quote_delegates(self):
        """unsubscribe_quote 应委托给 quote_handler"""
        svc = FutuService()
        with patch.object(
            svc.quote_handler, "unsubscribe_quote", new=AsyncMock(return_value={"status": "success"})
        ) as mock_method:
            await svc.unsubscribe_quote("HK.00700")
        args, _ = mock_method.call_args
        assert args[0] == "HK.00700"

    @pytest.mark.asyncio
    async def test_get_history_delegates(self):
        """get_history 应委托给 quote_handler"""
        svc = FutuService()
        with patch.object(
            svc.quote_handler, "get_history", new=AsyncMock(return_value={"status": "success"})
        ) as mock_method:
            await svc.get_history("HK.00700", "K_DAY", 30)
        mock_method.assert_awaited_once_with("HK.00700", "K_DAY", 30)

    @pytest.mark.asyncio
    async def test_get_order_book_delegates(self):
        """get_order_book 应委托给 quote_handler"""
        svc = FutuService()
        with patch.object(
            svc.quote_handler, "get_order_book", new=AsyncMock(return_value={"status": "success"})
        ) as mock_method:
            await svc.get_order_book("HK.00700")
        args, _ = mock_method.call_args
        assert args[0] == "HK.00700"

    @pytest.mark.asyncio
    async def test_get_option_chain_delegates(self):
        """get_option_chain 应委托给 option_fund_handler"""
        svc = FutuService()
        with patch.object(
            svc.option_fund_handler, "get_option_chain", new=AsyncMock(return_value={"status": "success"})
        ) as mock_method:
            await svc.get_option_chain("HK.00700", "2026-01-01")
        args, _ = mock_method.call_args
        assert args[0] == "HK.00700"
        assert args[1] == "2026-01-01"

    @pytest.mark.asyncio
    async def test_get_fund_flow_delegates(self):
        """get_fund_flow 应委托给 option_fund_handler"""
        svc = FutuService()
        with patch.object(
            svc.option_fund_handler, "get_fund_flow", new=AsyncMock(return_value={"status": "success"})
        ) as mock_method:
            await svc.get_fund_flow("HK.00700")
        args, _ = mock_method.call_args
        assert args[0] == "HK.00700"

    @pytest.mark.asyncio
    async def test_get_fundamental_delegates(self):
        """get_fundamental 应委托给 option_fund_handler"""
        svc = FutuService()
        with patch.object(
            svc.option_fund_handler, "get_fundamental", new=AsyncMock(return_value={"status": "success"})
        ) as mock_method:
            await svc.get_fundamental("HK.00700")
        args, _ = mock_method.call_args
        assert args[0] == "HK.00700"

    @pytest.mark.asyncio
    async def test_get_market_snapshots_delegates(self):
        """get_market_snapshots 应委托给 screener_handler"""
        svc = FutuService()
        with patch.object(
            svc.screener_handler, "get_market_snapshots", new=AsyncMock(return_value={"status": "success"})
        ) as mock_method:
            await svc.get_market_snapshots(["HK.00700", "US.AAPL"])
        mock_method.assert_awaited_once_with(["HK.00700", "US.AAPL"])

    @pytest.mark.asyncio
    async def test_screen_stocks_delegates_with_defaults(self):
        """screen_stocks 应使用默认参数委托给 screener_handler"""
        svc = FutuService()
        with patch.object(
            svc.screener_handler, "screen_stocks", new=AsyncMock(return_value={"status": "success"})
        ) as mock_method:
            await svc.screen_stocks()
        mock_method.assert_awaited_once_with("HK", [])

    @pytest.mark.asyncio
    async def test_place_order_delegates_with_format_ticker(self):
        """place_order 应委托给 trade_handler 并传入 format_ticker"""
        svc = FutuService()
        with patch.object(
            svc.trade_handler, "place_order", new=AsyncMock(return_value={"status": "success"})
        ) as mock_method:
            await svc.place_order("HK.00700", 100, 350.0, TrdSide.BUY, TrdMarket.HK)
        mock_method.assert_awaited_once()
        args, _ = mock_method.call_args
        assert args[0] == "HK.00700"
        assert args[1] == 100
        assert args[2] == 350.0
        assert args[3] == TrdSide.BUY
        assert args[4] == TrdMarket.HK
        assert callable(args[5])  # format_ticker

    @pytest.mark.asyncio
    async def test_modify_order_delegates(self):
        """modify_order 应委托给 trade_handler"""
        svc = FutuService()
        with patch.object(
            svc.trade_handler, "modify_order", new=AsyncMock(return_value={"status": "success"})
        ) as mock_method:
            await svc.modify_order("OID123", ModifyOrderOp.CANCEL, TrdMarket.HK)
        mock_method.assert_awaited_once_with("OID123", ModifyOrderOp.CANCEL, TrdMarket.HK)

    @pytest.mark.asyncio
    async def test_query_order_delegates(self):
        """query_order 应委托给 trade_handler"""
        svc = FutuService()
        with patch.object(
            svc.trade_handler, "query_order", new=AsyncMock(return_value={"status": "success"})
        ) as mock_method:
            await svc.query_order("OID123", TrdMarket.HK)
        mock_method.assert_awaited_once_with("OID123", TrdMarket.HK)

    @pytest.mark.asyncio
    async def test_get_account_info_delegates_with_default_market(self):
        """get_account_info 默认 market=HK 委托给 trade_handler"""
        svc = FutuService()
        with patch.object(
            svc.trade_handler, "get_account_info", new=AsyncMock(return_value={"status": "success"})
        ) as mock_method:
            await svc.get_account_info()
        mock_method.assert_awaited_once_with("HK")


def test_global_singleton_exported():
    """模块级 futu_service 实例应可被导入且为单例"""
    from backend.services.futu.service import FutuService as FC, futu_service

    assert isinstance(futu_service, FC)
    assert futu_service is FC()  # 应与 FutuService() 是同一实例
