"""worker.py 入口单元测试

覆盖: worker_heartbeat_daemon 心跳/分片计算/动态切换,
main 启动所有守护任务 + CancelledError 优雅退出。
"""

import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# 环境变量必须在 import worker 之前设置
os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("EMBEDDING_API_KEY", "test-key")
os.environ.setdefault("EMBEDDING_BASE_URL", "https://api.test.com")
os.environ.setdefault("EMBEDDING_MODEL", "BAAI/bge-large-zh-v1.5")
os.environ.setdefault("INTERNAL_API_SECRET", "test-secret-key")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-for-testing")
os.environ.setdefault("FINNHUB_API_KEY", "test-finnhub-key")
os.environ.setdefault("LLM_API_KEY", "test-llm-key")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))


def _cancelling_sleep(after_n=0):
    """生成 sleep, 第 after_n 次后抛 CancelledError 中断 while True。"""
    counter = {"n": 0}

    async def _fake(_seconds):
        counter["n"] += 1
        if counter["n"] > after_n:
            raise asyncio.CancelledError()

    return _fake


class TestWorkerHeartbeatDaemon:
    """worker_heartbeat_daemon: 心跳注册/分片计算/动态容灾"""

    @pytest.mark.asyncio
    async def test_heartbeat_registers_and_cancels_after_one_iteration(self):
        from backend.worker import WORKER_UUID, worker_heartbeat_daemon

        with (
            patch("backend.worker.redis_client") as m_r,
            patch("backend.worker.asyncio.sleep", new=_cancelling_sleep(1)),
        ):
            m_r.set = AsyncMock(return_value=True)
            m_r.scan = AsyncMock(return_value=(0, []))
            with pytest.raises(asyncio.CancelledError):
                await worker_heartbeat_daemon()
        # 验证心跳 key 被注册
        m_r.set.assert_awaited()
        set_args = m_r.set.await_args
        assert f"quant:worker:heartbeat:{WORKER_UUID}" == set_args.args[0]
        assert set_args.kwargs.get("ex") == 15

    @pytest.mark.asyncio
    async def test_heartbeat_computes_rank_and_updates_env_when_changed(self):
        from backend.worker import WORKER_UUID, worker_heartbeat_daemon

        # 构造两个 worker,other_uuid 用 "!!!" 开头(ASCII 33)确保字典序小于
        # 任何 uuid4(以十六进制数字开头,ASCII 48-57),使自身排第二(rank=1)
        other_key = b"quant:worker:heartbeat:!!!-before-my-uuid"
        my_key = f"quant:worker:heartbeat:{WORKER_UUID}".encode()
        with (
            patch("backend.worker.redis_client") as m_r,
            patch("backend.worker.asyncio.sleep", new=_cancelling_sleep(1)),
            patch.dict(os.environ, {"WORKER_ID": "0", "WORKER_TOTAL": "1"}, clear=False),
        ):
            m_r.set = AsyncMock(return_value=True)
            m_r.scan = AsyncMock(return_value=(0, [other_key, my_key]))
            with pytest.raises(asyncio.CancelledError):
                await worker_heartbeat_daemon()
            # 断言必须在 patch.dict 的 with 块内,否则退出时会被恢复
            assert os.environ["WORKER_ID"] == "1"
            assert os.environ["WORKER_TOTAL"] == "2"

    @pytest.mark.asyncio
    async def test_heartbeat_skips_env_update_when_rank_unchanged(self):
        from backend.worker import WORKER_UUID, worker_heartbeat_daemon

        my_key = f"quant:worker:heartbeat:{WORKER_UUID}".encode()
        with (
            patch("backend.worker.redis_client") as m_r,
            patch("backend.worker.asyncio.sleep", new=_cancelling_sleep(1)),
            patch.dict(os.environ, {"WORKER_ID": "0", "WORKER_TOTAL": "1"}, clear=False),
        ):
            m_r.set = AsyncMock(return_value=True)
            m_r.scan = AsyncMock(return_value=(0, [my_key]))
            with pytest.raises(asyncio.CancelledError):
                await worker_heartbeat_daemon()
            # 单节点 rank=0/total=1 与初始一致,不更新
            assert os.environ["WORKER_ID"] == "0"
            assert os.environ["WORKER_TOTAL"] == "1"

    @pytest.mark.asyncio
    async def test_heartbeat_handles_str_keys_not_bytes(self):
        from backend.worker import WORKER_UUID, worker_heartbeat_daemon

        my_key = f"quant:worker:heartbeat:{WORKER_UUID}"  # str 而非 bytes
        with (
            patch("backend.worker.redis_client") as m_r,
            patch("backend.worker.asyncio.sleep", new=_cancelling_sleep(1)),
            patch.dict(os.environ, {"WORKER_ID": "", "WORKER_TOTAL": ""}, clear=False),
        ):
            m_r.set = AsyncMock(return_value=True)
            m_r.scan = AsyncMock(return_value=(0, [my_key]))
            with pytest.raises(asyncio.CancelledError):
                await worker_heartbeat_daemon()
            assert os.environ["WORKER_ID"] == "0"
            assert os.environ["WORKER_TOTAL"] == "1"

    @pytest.mark.asyncio
    async def test_heartbeat_swallows_exception_and_continues_loop(self):
        from backend.worker import worker_heartbeat_daemon

        with (
            patch("backend.worker.redis_client") as m_r,
            patch("backend.worker.asyncio.sleep", new=_cancelling_sleep(1)),
        ):
            m_r.set = AsyncMock(side_effect=RuntimeError("redis down"))
            # 第一次迭代异常被吞，第二次 sleep 抛 CancelledError
            with pytest.raises(asyncio.CancelledError):
                await worker_heartbeat_daemon()

    @pytest.mark.asyncio
    async def test_heartbeat_scan_pagination_traverses_multiple_pages(self):
        from backend.worker import WORKER_UUID, worker_heartbeat_daemon

        my_key = f"quant:worker:heartbeat:{WORKER_UUID}".encode()
        call_count = {"n": 0}

        async def fake_scan(cursor, match, count):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return (123, [my_key])  # 还有下一页
            return (0, [b"quant:worker:heartbeat:zzz"])  # 终止

        # _cancelling_sleep(0): 第 1 次 sleep 即抛 CancelledError,只跑 1 次迭代
        with (
            patch("backend.worker.redis_client") as m_r,
            patch("backend.worker.asyncio.sleep", new=_cancelling_sleep(0)),
            patch.dict(os.environ, {"WORKER_ID": "", "WORKER_TOTAL": ""}, clear=False),
        ):
            m_r.set = AsyncMock(return_value=True)
            m_r.scan = AsyncMock(side_effect=fake_scan)
            with pytest.raises(asyncio.CancelledError):
                await worker_heartbeat_daemon()
            # 两页都被遍历
            assert call_count["n"] == 2
            # WORKER_UUID 字典序小于 zzz → rank=0
            assert os.environ["WORKER_ID"] == "0"


class TestWorkerMain:
    """main: 启动所有守护任务 + 优雅退出"""

    @pytest.mark.asyncio
    async def test_main_starts_all_daemon_tasks_and_cleans_up_on_cancel(self):
        from backend.worker import main

        # 用一个会在 0.1s 后取消自身的 sentinel task 模拟 gather 被取消
        async def _cancel_afterdelay():
            await asyncio.sleep(0.05)
            raise asyncio.CancelledError()

        with (
            patch("backend.worker.redis_batch_writer") as m_bw,
            patch("backend.worker.redis_client") as m_rc,
            patch("backend.worker.engine") as m_engine,
            patch("backend.worker.QuotePublisher") as m_pub_cls,
            patch("backend.worker.finnhub_service") as m_fh,
            patch("backend.worker.screener_service") as m_sc,
            patch("backend.worker.sentiment_tracker") as m_st,
            patch("backend.worker.ticker_service") as m_ts,
            patch("backend.worker.yf_service") as m_yf,
            patch("backend.worker.notification_service") as m_nt,
            patch("backend.worker.worker_heartbeat_daemon", new=_cancel_afterdelay),
        ):
            m_pub = MagicMock()
            m_pub.run_daemon = AsyncMock()
            m_pub_cls.return_value = m_pub
            m_fh.run_global_daemon = AsyncMock()
            m_sc.screener_subscription_daemon = AsyncMock()
            m_sc.daily_market_summary_daemon = AsyncMock()
            m_sc.clean_obsolete_knowledge_base_daemon = AsyncMock()
            m_st.track_daemon = AsyncMock()
            m_ts.sync_tickers_daemon = AsyncMock()
            m_yf.macro_data_daemon = AsyncMock()
            m_nt.send_alert = AsyncMock()
            m_bw.start = MagicMock()
            m_bw.stop = AsyncMock()
            m_rc.aclose = AsyncMock()
            m_engine.dispose = MagicMock()

            await main()
            # 让 fire-and-forget 的 send_alert task 有机会被调度
            await asyncio.sleep(0)

        # 验证所有 daemon 被启动
        m_bw.start.assert_called_once()
        m_pub.run_daemon.assert_awaited_once()
        m_fh.run_global_daemon.assert_awaited_once()
        m_sc.screener_subscription_daemon.assert_awaited_once()
        m_sc.daily_market_summary_daemon.assert_awaited_once()
        m_sc.clean_obsolete_knowledge_base_daemon.assert_awaited_once()
        m_st.track_daemon.assert_awaited_once()
        m_ts.sync_tickers_daemon.assert_awaited_once()
        m_yf.macro_data_daemon.assert_awaited_once()
        # 验证清理
        m_bw.stop.assert_awaited_once()
        m_rc.aclose.assert_awaited_once()
        m_engine.dispose.assert_called_once()
