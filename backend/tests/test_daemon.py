"""
守护进程单元测试

覆盖：
- init_trade_db() 数据库初始化
- log_trade() 交易日志记录
- QuoteMonitorHandler 行情监控处理器
- start_daemon() 守护进程启动
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest
from futu import RET_OK

from backend.workers.daemon import (
    QuoteMonitorHandler,
    init_trade_db,
    log_trade,
    start_daemon,
)


class TestInitTradeDb:
    """init_trade_db() 测试"""

    def test_init_trade_db(self):
        """测试数据库初始化（当前为空实现）"""
        # 当前函数体为空，只是确保不抛出异常
        init_trade_db()
        assert True


class TestLogTrade:
    """log_trade() 测试"""

    @patch("backend.workers.daemon.SessionLocal")
    def test_log_trade_success(self, mock_session_local):
        """测试成功记录交易日志"""
        # 创建 mock 数据库会话
        mock_db = MagicMock()
        mock_session_local.return_value.__enter__ = MagicMock(return_value=mock_db)
        mock_session_local.return_value.__exit__ = MagicMock(return_value=False)

        # 调用 log_trade
        log_trade(
            ticker="US.AAPL",
            action="BUY",
            price=150.0,
            qty=1,
            status="success",
            message="Order executed",
        )

        # 验证数据库操作被调用
        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()

    @patch("backend.workers.daemon.SessionLocal")
    def test_log_trade_db_error(self, mock_session_local, capsys):
        """测试数据库错误时打印警告"""
        # 模拟数据库异常
        mock_db = MagicMock()
        mock_db.add.side_effect = Exception("DB error")
        mock_session_local.return_value.__enter__ = MagicMock(return_value=mock_db)
        mock_session_local.return_value.__exit__ = MagicMock(return_value=False)

        # 调用 log_trade（不应抛出异常）
        log_trade(
            ticker="US.AAPL",
            action="BUY",
            price=150.0,
            qty=1,
            status="error",
            message="DB error",
        )

        # 验证错误被打印
        captured = capsys.readouterr()
        assert "记录交易日志失败" in captured.out

    @patch("backend.workers.daemon.SessionLocal")
    def test_log_trade_creates_trade_log(self, mock_session_local):
        """测试创建 TradeLog 对象"""
        from backend.core import models

        mock_db = MagicMock()
        mock_session_local.return_value.__enter__ = MagicMock(return_value=mock_db)
        mock_session_local.return_value.__exit__ = MagicMock(return_value=False)

        log_trade(
            ticker="US.TSLA",
            action="SELL",
            price=200.0,
            qty=10,
            status="success",
            message="Sold",
        )

        # 验证 add 被调用，且参数是 TradeLog 实例
        call_args = mock_db.add.call_args[0][0]
        assert isinstance(call_args, models.TradeLog)
        assert call_args.ticker == "US.TSLA"
        assert call_args.action == "SELL"
        assert call_args.price == 200.0
        assert call_args.qty == 10


class TestQuoteMonitorHandler:
    """QuoteMonitorHandler 测试"""

    @pytest.fixture
    def handler(self):
        """创建 QuoteMonitorHandler 实例"""
        return QuoteMonitorHandler()

    def test_initialization(self, handler):
        """测试初始化"""
        assert handler.has_traded is False

    def test_on_recv_rsp_invalid_data(self, handler):
        """测试无效数据处理"""
        # 模拟非 DataFrame 数据
        rsp_pb = MagicMock()

        # 模拟 super().on_recv_rsp 返回非 OK 状态
        with patch.object(handler.__class__.__bases__[0], "on_recv_rsp") as mock_super:
            mock_super.return_value = (1, "Error data")  # ret_code != RET_OK
            ret_code, data = handler.on_recv_rsp(rsp_pb)

            assert ret_code == RET_OK
            assert data == "Error data"

    def test_on_recv_rsp_non_dataframe(self, handler, capsys):
        """测试非 DataFrame 类型数据"""
        rsp_pb = MagicMock()

        with patch.object(handler.__class__.__bases__[0], "on_recv_rsp") as mock_super:
            mock_super.return_value = (RET_OK, "raw_string_data")
            ret_code, data = handler.on_recv_rsp(rsp_pb)

            assert ret_code == RET_OK
            assert data == "raw_string_data"
            captured = capsys.readouterr()
            assert "非预期的行情数据类型" in captured.out

    @patch("backend.workers.daemon.asyncio.run")
    def test_on_recv_rsp_trade_signal(self, mock_asyncio_run, handler):
        """测试交易信号触发"""
        # 创建模拟的 DataFrame 数据
        test_data = pd.DataFrame({
            "code": ["US.AAPL"],
            "last_price": [100.0],  # 低于 TARGET_BUY_PRICE (9990.0)
        })

        rsp_pb = MagicMock()

        with patch.object(handler.__class__.__bases__[0], "on_recv_rsp") as mock_super:
            mock_super.return_value = (RET_OK, test_data)

            # 模拟 execute_trade 返回成功
            mock_asyncio_run.return_value = {"status": "success", "message": "Order placed"}

            with patch("backend.workers.daemon.notification_service") as mock_notification:
                mock_notification.send_alert = MagicMock()

                ret_code, data = handler.on_recv_rsp(rsp_pb)

                assert ret_code == RET_OK
                assert handler.has_traded is True

                # 验证 execute_trade 被调用
                mock_asyncio_run.assert_called()

    @patch("backend.workers.daemon.asyncio.run")
    def test_on_recv_rsp_no_trade_signal(self, mock_asyncio_run, handler):
        """测试不触发交易信号（价格高于阈值）"""
        # 创建模拟的 DataFrame 数据（价格高于阈值）
        test_data = pd.DataFrame({
            "code": ["US.AAPL"],
            "last_price": [10000.0],  # 高于 TARGET_BUY_PRICE (9990.0)
        })

        rsp_pb = MagicMock()

        with patch.object(handler.__class__.__bases__[0], "on_recv_rsp") as mock_super:
            mock_super.return_value = (RET_OK, test_data)

            ret_code, data = handler.on_recv_rsp(rsp_pb)

            assert ret_code == RET_OK
            assert handler.has_traded is False

            # 验证 execute_trade 未被调用
            mock_asyncio_run.assert_not_called()

    @patch("backend.workers.daemon.asyncio.run")
    def test_on_recv_rsp_trade_failure(self, mock_asyncio_run, handler):
        """测试交易执行失败"""
        test_data = pd.DataFrame({
            "code": ["US.AAPL"],
            "last_price": [100.0],
        })

        rsp_pb = MagicMock()

        with patch.object(handler.__class__.__bases__[0], "on_recv_rsp") as mock_super:
            mock_super.return_value = (RET_OK, test_data)

            # 模拟 execute_trade 返回失败
            mock_asyncio_run.return_value = {"status": "error", "message": "Insufficient funds"}

            with patch("backend.workers.daemon.notification_service"):
                ret_code, data = handler.on_recv_rsp(rsp_pb)

                assert ret_code == RET_OK
                assert handler.has_traded is True

    def test_on_recv_rsp_wrong_ticker(self, handler):
        """测试错误的股票代码不触发交易"""
        test_data = pd.DataFrame({
            "code": ["US.TSLA"],  # 不是 TARGET_TICKER
            "last_price": [100.0],
        })

        rsp_pb = MagicMock()

        with patch.object(handler.__class__.__bases__[0], "on_recv_rsp") as mock_super:
            mock_super.return_value = (RET_OK, test_data)

            with patch("backend.workers.daemon.asyncio.run") as mock_asyncio_run:
                ret_code, data = handler.on_recv_rsp(rsp_pb)

                assert ret_code == RET_OK
                assert handler.has_traded is False
                mock_asyncio_run.assert_not_called()

    @pytest.mark.asyncio
    async def test_execute_trade(self, handler):
        """测试 execute_trade 方法"""
        with patch("backend.workers.daemon.httpx.AsyncClient") as mock_client_class:
            # 创建正确的 async mock
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"status": "success"}
            mock_client.post = AsyncMock(return_value=mock_response)

            # 设置 __aenter__ 和 __aexit__
            mock_client_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_class.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await handler.execute_trade("US.AAPL", "BUY", 1, 150.0)

            assert result["status"] == "success"
            mock_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_trade_error(self, handler):
        """测试 execute_trade 异常处理"""
        with patch("backend.workers.daemon.httpx.AsyncClient") as mock_client_class:
            # 创建正确的 async mock
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=Exception("Network error"))

            # 设置 __aenter__ 和 __aexit__
            mock_client_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_class.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await handler.execute_trade("US.AAPL", "BUY", 1, 150.0)

            assert result["status"] == "error"
            assert "API 异常" in result["message"]


class TestStartDaemon:
    """start_daemon() 测试"""

    @patch("backend.workers.daemon.os.getenv")
    @patch("backend.workers.daemon.print")
    def test_start_daemon(self, mock_print, mock_getenv):
        """测试启动守护进程"""
        # 模拟环境变量
        mock_getenv.side_effect = lambda key, default: {
            "FUTU_HOST": "127.0.0.1",
            "FUTU_PORT": "11111",
        }.get(key, default)

        # start_daemon 当前实现只是打印消息，不会真正连接 Futu API
        # 只是确保不抛出异常
        start_daemon()

        # 验证打印被调用
        mock_print.assert_called()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
