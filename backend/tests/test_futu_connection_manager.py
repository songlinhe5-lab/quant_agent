"""
Futu ConnectionManager 单元测试
覆盖: connect/close/get_trade_context/unlock_trade_if_needed
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from futu import RET_OK, SecurityFirm, TrdEnv, TrdMarket

from backend.services.futu.connection_manager import ConnectionManager


class TestConnectionManager:
    """ConnectionManager 连接管理器测试套件"""

    def test_initial_state_disconnected(self):
        """新实例的初始状态应为 DISCONNECTED 且无任何上下文"""
        mgr = ConnectionManager()
        assert mgr.status == "DISCONNECTED"
        assert mgr.quote_ctx is None
        assert mgr.trade_ctxs == {}
        assert mgr.error_msg == ""

    def test_connect_success_sets_connected(self):
        """connect 成功时应创建 quote_ctx 并切换到 CONNECTED 状态"""
        mgr = ConnectionManager()
        fake_ctx = MagicMock()
        with patch(
            "backend.services.futu.connection_manager.OpenQuoteContext",
            return_value=fake_ctx,
        ) as mock_open:
            mgr.connect()
        mock_open.assert_called_once_with(host="127.0.0.1", port=11111)
        assert mgr.quote_ctx is fake_ctx
        assert mgr.status == "CONNECTED"
        assert mgr.error_msg == ""

    def test_connect_failure_sets_error_state(self):
        """connect 抛出异常时应进入 ERROR 状态并记录错误信息"""
        mgr = ConnectionManager()
        with patch(
            "backend.services.futu.connection_manager.OpenQuoteContext",
            side_effect=ConnectionError("OpenD unreachable"),
        ):
            mgr.connect()
        assert mgr.status == "ERROR"
        assert "OpenD unreachable" in mgr.error_msg
        assert mgr.quote_ctx is None

    def test_connect_uses_env_overrides(self):
        """connect 应从环境变量读取 host/port"""
        mgr = ConnectionManager()
        fake_ctx = MagicMock()
        with (
            patch.dict("os.environ", {"FUTU_HOST": "10.0.0.5", "FUTU_PORT": "22222"}),
            patch(
                "backend.services.futu.connection_manager.OpenQuoteContext",
                return_value=fake_ctx,
            ) as mock_open,
        ):
            mgr.connect()
        mock_open.assert_called_once_with(host="10.0.0.5", port=22222)

    def test_close_releases_all_contexts(self):
        """close 应关闭 quote_ctx 和所有 trade_ctx 并清空字典"""
        mgr = ConnectionManager()
        quote_ctx = MagicMock()
        trade_ctx_1 = MagicMock()
        trade_ctx_2 = MagicMock()
        mgr.quote_ctx = quote_ctx
        mgr.trade_ctxs = {(TrdEnv.SIMULATE, TrdMarket.HK): trade_ctx_1, (TrdEnv.REAL, TrdMarket.US): trade_ctx_2}
        mgr.status = "CONNECTED"

        mgr.close()

        quote_ctx.close.assert_called_once()
        trade_ctx_1.close.assert_called_once()
        trade_ctx_2.close.assert_called_once()
        assert mgr.quote_ctx is None
        assert mgr.trade_ctxs == {}
        assert mgr.status == "DISCONNECTED"

    def test_close_when_already_disconnected_safe(self):
        """close 在已断开状态调用应是安全无操作"""
        mgr = ConnectionManager()
        mgr.close()
        assert mgr.status == "DISCONNECTED"
        assert mgr.quote_ctx is None

    def test_get_trade_context_creates_singleton_per_key(self):
        """相同 (trd_env, market) 组合应复用同一个 trade_ctx"""
        mgr = ConnectionManager()
        fake_ctx = MagicMock()
        with patch(
            "backend.services.futu.connection_manager.OpenSecTradeContext",
            return_value=fake_ctx,
        ) as mock_open:
            ctx1 = mgr.get_trade_context(TrdMarket.HK, TrdEnv.SIMULATE)
            ctx2 = mgr.get_trade_context(TrdMarket.HK, TrdEnv.SIMULATE)
        assert ctx1 is fake_ctx
        assert ctx2 is fake_ctx
        mock_open.assert_called_once()
        args, kwargs = mock_open.call_args
        assert kwargs["filter_trdmarket"] == str(TrdMarket.HK)
        assert kwargs["security_firm"] == SecurityFirm.FUTUSECURITIES
        assert kwargs["host"] == "127.0.0.1"
        assert kwargs["port"] == 11111

    def test_get_trade_context_distinct_keys_create_distinct_contexts(self):
        """不同 (trd_env, market) 组合应创建独立的 trade_ctx"""
        mgr = ConnectionManager()
        fake_hk = MagicMock()
        fake_us = MagicMock()
        with patch(
            "backend.services.futu.connection_manager.OpenSecTradeContext",
            side_effect=[fake_hk, fake_us],
        ) as mock_open:
            ctx_hk = mgr.get_trade_context(TrdMarket.HK, TrdEnv.SIMULATE)
            ctx_us = mgr.get_trade_context(TrdMarket.US, TrdEnv.REAL)
        assert ctx_hk is fake_hk
        assert ctx_us is fake_us
        assert mock_open.call_count == 2
        assert len(mgr.trade_ctxs) == 2

    @pytest.mark.asyncio
    async def test_unlock_trade_if_needed_skips_when_no_pwd(self):
        """无密码环境变量时不应调用 unlock_trade"""
        mgr = ConnectionManager()
        trd_ctx = MagicMock()
        with patch.dict("os.environ", {}, clear=False):
            import os

            os.environ.pop("FUTU_TRD_UNLOCK_PWD", None)
            os.environ.pop("FUTU_TRADE_PWD", None)
            await mgr.unlock_trade_if_needed(trd_ctx)
        trd_ctx.unlock_trade.assert_not_called()

    @pytest.mark.asyncio
    async def test_unlock_trade_if_needed_calls_unlock_with_pwd(self):
        """存在密码时应通过 asyncio.to_thread 调用 unlock_trade"""
        mgr = ConnectionManager()
        trd_ctx = MagicMock()
        trd_ctx.unlock_trade.return_value = (RET_OK, "unlocked")
        with patch.dict("os.environ", {"FUTU_TRD_UNLOCK_PWD": "secret"}):
            with patch("asyncio.to_thread", new=AsyncMock(return_value=(RET_OK, "unlocked"))) as mock_thread:
                await mgr.unlock_trade_if_needed(trd_ctx)
        mock_thread.assert_called_once()
        args, kwargs = mock_thread.call_args
        assert args[0] == trd_ctx.unlock_trade
        assert args[1] == "secret"
        assert kwargs.get("is_unlock") is True

    @pytest.mark.asyncio
    async def test_unlock_trade_if_needed_handles_failure_gracefully(self):
        """unlock 返回非 RET_OK 时应吞下错误不抛出异常"""
        mgr = ConnectionManager()
        trd_ctx = MagicMock()
        with patch.dict("os.environ", {"FUTU_TRADE_PWD": "pwd"}):
            with patch(
                "asyncio.to_thread",
                new=AsyncMock(return_value=(-1, "permission denied")),
            ):
                # 不应抛出异常
                await mgr.unlock_trade_if_needed(trd_ctx)

    @pytest.mark.asyncio
    async def test_unlock_trade_if_needed_prefers_unlock_pwd_over_trade_pwd(self):
        """FUTU_TRD_UNLOCK_PWD 优先于 FUTU_TRADE_PWD"""
        mgr = ConnectionManager()
        trd_ctx = MagicMock()
        with patch.dict(
            "os.environ",
            {"FUTU_TRD_UNLOCK_PWD": "preferred", "FUTU_TRADE_PWD": "fallback"},
        ):
            with patch("asyncio.to_thread", new=AsyncMock(return_value=(RET_OK, "ok"))) as mock_thread:
                await mgr.unlock_trade_if_needed(trd_ctx)
            args, _ = mock_thread.call_args
            assert args[1] == "preferred"

    def test_global_singleton_import(self):
        """模块级 singleton 实例应可被导入"""
        from backend.services.futu.connection_manager import ConnectionManager as CM

        assert CM is ConnectionManager
