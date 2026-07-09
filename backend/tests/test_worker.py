"""worker.py 入口单元测试

覆盖: main 启动所有守护任务 + CancelledError 优雅退出。
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


class TestWorkerMain:
    """main: 启动所有守护任务 + 优雅退出"""

    @pytest.mark.asyncio
    async def test_main_starts_all_daemon_tasks_and_cleans_up_on_cancel(self):
        from backend.worker import main

        with (
            patch("backend.worker.redis_batch_writer") as m_bw,
            patch("backend.worker.redis_client") as m_rc,
            patch("backend.worker.engine") as m_engine,
            patch("backend.worker.start_collector_daemons", new=AsyncMock(return_value=[])),
            patch("backend.worker.notification_service") as m_nt,
            patch("asyncio.gather") as mock_gather,
        ):
            m_bw.start = MagicMock()
            m_bw.stop = AsyncMock()
            m_rc.aclose = AsyncMock()
            m_engine.dispose = MagicMock()
            m_nt.send_alert = AsyncMock()

            # 让 gather 抛出 CancelledError，模拟超时取消
            mock_gather.side_effect = asyncio.CancelledError()

            await main()

            # 验证核心资源启动与清理
            m_bw.start.assert_called_once()
            m_bw.stop.assert_awaited_once()
            m_rc.aclose.assert_awaited_once()
            m_engine.dispose.assert_called_once()
