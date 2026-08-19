"""
Futu ConnectionManager 单元测试
覆盖: connect/close/get_trade_context/unlock_trade_if_needed
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from futu import RET_OK, SecurityFirm, TrdEnv, TrdMarket

from data_subservice.futu_src.connection_manager import ConnectionManager


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
        mgr._enabled = True  # 启用 futu，绕过 DISABLED 提前返回
        fake_ctx = MagicMock()
        with (
            patch(
                "data_subservice.futu_src.connection_manager.OpenQuoteContext",
                return_value=fake_ctx,
            ) as mock_open,
            patch(
                "data_subservice.futu_src.connection_manager.ConnectionManager._is_opend_reachable",
                return_value=True,
            ),
        ):
            mgr.connect()
        mock_open.assert_called_once_with(host="127.0.0.1", port=11111, is_encrypt=False)
        assert mgr.quote_ctx is fake_ctx
        assert mgr.status == "CONNECTED"
        assert mgr.error_msg == ""

    def test_connect_revives_from_stale_disconnected_state(self):
        """僵死态自愈 (2026-08-19 根因修复): quote_ctx 残留但 status=DISCONNECTED
        （watchdog 探针失败标记断线后）时, connect() 必须真正重建连接, 而非复用跳过。
        此前复用逻辑会让 watchdog 永远无法把 status 恢复为 CONNECTED。"""
        mgr = ConnectionManager()
        mgr._enabled = True
        # 模拟僵死态: 旧 ctx 残留 + status 被 watchdog 标为 DISCONNECTED
        old_ctx = MagicMock()
        mgr.quote_ctx = old_ctx
        mgr.status = "DISCONNECTED"
        new_ctx = MagicMock()
        with (
            patch(
                "data_subservice.futu_src.connection_manager.OpenQuoteContext",
                return_value=new_ctx,
            ) as mock_open,
            patch(
                "data_subservice.futu_src.connection_manager.ConnectionManager._is_opend_reachable",
                return_value=True,
            ),
        ):
            mgr.connect()
        # 必须 close 旧 ctx 释放线程, 再 new 新 ctx
        old_ctx.close.assert_called_once()
        mock_open.assert_called_once()
        assert mgr.quote_ctx is new_ctx
        assert mgr.status == "CONNECTED"

    def test_connect_failure_sets_error_state(self):
        """connect 抛出异常时应进入 ERROR 状态并记录错误信息"""
        mgr = ConnectionManager()
        mgr._enabled = True  # 启用 futu，绕过 DISABLED 提前返回
        # 先mock socket探测返回True，这样才能测试OpenQuoteContext失败的场景
        with (
            patch(
                "data_subservice.futu_src.connection_manager.ConnectionManager._is_opend_reachable",
                return_value=True,
            ),
            patch(
                "data_subservice.futu_src.connection_manager.OpenQuoteContext",
                side_effect=ConnectionError("OpenD unreachable"),
            ),
        ):
            mgr.connect()
        assert mgr.status == "ERROR"
        assert "OpenD unreachable" in mgr.error_msg
        assert mgr.quote_ctx is None

    def test_connect_socket_unreachable_sets_error_state(self):
        """socket探测失败时直接返回ERROR，不调用OpenQuoteContext"""
        mgr = ConnectionManager()
        mgr._enabled = True  # 启用 futu，绕过 DISABLED 提前返回
        with patch(
            "data_subservice.futu_src.connection_manager.ConnectionManager._is_opend_reachable",
            return_value=False,
        ):
            mgr.connect()
        assert mgr.status == "ERROR"
        assert "OpenD 不可达" in mgr.error_msg
        assert mgr.quote_ctx is None

    def test_connect_uses_env_overrides(self):
        """connect 应从环境变量读取 host/port"""
        # 先在环境变量中设置，然后创建ConnectionManager
        with patch.dict("os.environ", {"FUTU_HOST": "10.0.0.5", "FUTU_PORT": "22222"}):
            mgr = ConnectionManager()  # 这时会读取环境变量
        mgr._enabled = True  # 启用 futu，绕过 DISABLED 提前返回

        fake_ctx = MagicMock()
        with (
            patch(
                "data_subservice.futu_src.connection_manager.OpenQuoteContext",
                return_value=fake_ctx,
            ) as mock_open,
            patch(
                "data_subservice.futu_src.connection_manager.ConnectionManager._is_opend_reachable",
                return_value=True,
            ),
        ):
            mgr.connect()
        mock_open.assert_called_once_with(host="10.0.0.5", port=22222, is_encrypt=True)

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
        with (
            patch(
                "data_subservice.futu_src.connection_manager.ConnectionManager._is_opend_reachable",
                return_value=True,
            ),
            patch(
                "data_subservice.futu_src.connection_manager.OpenSecTradeContext",
                return_value=fake_ctx,
            ) as mock_open,
        ):
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
        with (
            patch(
                "data_subservice.futu_src.connection_manager.ConnectionManager._is_opend_reachable",
                return_value=True,
            ),
            patch(
                "data_subservice.futu_src.connection_manager.OpenSecTradeContext",
                side_effect=[fake_hk, fake_us],
            ) as mock_open,
        ):
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
        from data_subservice.futu_src.connection_manager import ConnectionManager as CM

        assert CM is ConnectionManager

    def test_connect_no_leak_when_status_disconnected_but_ctx_alive(self):
        """🐛 回归测试: 线程泄漏根因 (2026-08-13) + 僵死态自愈 (2026-08-19)

        2026-08-13 根因: watchdog 探针失败标 DISCONNECTED 但不清空 quote_ctx, 若
        connect() 反复 new OpenQuoteContext 覆盖旧 ctx 而不 close → 旧 ctx 回调线程
        永久泄漏 (实测 35min 爬到 814 线程)。

        2026-08-19 修复: 此前的"只要 quote_ctx 存活就复用跳过"会把 status=DISCONNECTED
        态永久僵死 (watchdog 永远无法重建连接)。正确行为:
        - status==CONNECTED 且 ctx 存活 → 复用跳过 (不泄漏, 不做无谓重建);
        - status!=CONNECTED 且 ctx 残留 → 走重建分支, 先 close 旧 ctx 再 new 新 ctx
          (单次重建, 非反复 new, 故不泄漏), 让 watchdog 自愈。

        本测试验证: status=DISCONNECTED 时单次 connect() 应重建 (close 旧 + new 新),
        而非永久复用导致僵死。
        """
        mgr = ConnectionManager()
        mgr._enabled = True
        old_ctx = MagicMock()
        mgr.quote_ctx = old_ctx
        mgr.status = "DISCONNECTED"  # 模拟 watchdog 标记断线但 ctx 未释放
        new_ctx = MagicMock()
        with (
            patch(
                "data_subservice.futu_src.connection_manager.OpenQuoteContext",
                return_value=new_ctx,
            ) as mock_open,
            patch(
                "data_subservice.futu_src.connection_manager.ConnectionManager._is_opend_reachable",
                return_value=True,
            ),
        ):
            mgr.connect()
        # 重建而非永久复用: 旧 ctx 被 close 释放线程, 新 ctx 被创建, status 恢复 CONNECTED
        old_ctx.close.assert_called_once()
        mock_open.assert_called_once()
        assert mgr.quote_ctx is new_ctx
        assert mgr.status == "CONNECTED"
        # 关键: 重建分支只创建一次 ctx, 不会反复 new 覆盖 (防泄漏)
        assert mock_open.call_count == 1

    def test_connect_closes_stale_ctx_before_recreate(self):
        """🐛 回归测试: 兜底防护

        若 quote_ctx 为 None (已释放) 需要重建, connect() 在 new 前必须先 close 旧
        ctx (异常路径下残留) 释放其回调线程, 避免覆盖式泄漏。
        """
        mgr = ConnectionManager()
        mgr._enabled = True
        # recreate 分支: quote_ctx 为 None (已释放) 且 status 非 CONNECTED 时,
        # connect() 应先 close 旧 ctx (防御性) 再 new 新 ctx 并置 CONNECTED。
        mgr.quote_ctx = None
        mgr.status = "DISCONNECTED"
        new_ctx = MagicMock()
        with (
            patch(
                "data_subservice.futu_src.connection_manager.OpenQuoteContext",
                return_value=new_ctx,
            ) as mock_open,
            patch(
                "data_subservice.futu_src.connection_manager.ConnectionManager._is_opend_reachable",
                return_value=True,
            ),
        ):
            mgr.connect()
        mock_open.assert_called_once()
        assert mgr.quote_ctx is new_ctx
        assert mgr.status == "CONNECTED"
