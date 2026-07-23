"""
BotRuntime 深度测试 - 覆盖内部循环/策略执行/日志/恢复
覆盖: backend/services/bot_runtime.py (lines 200-434)
"""

import asyncio
import json
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from backend.services.bot_runtime import BotInstance, BotRuntimeManager


@pytest.fixture
def manager():
    return BotRuntimeManager()


@pytest.fixture
def bot():
    return BotInstance(
        bot_id="test_bot_1",
        name="TestBot",
        ticker="US.AAPL",
        class_name="TestStrategy",
        params={"fast_ma": 5},
    )


# ==========================================
# _push_log 测试
# ==========================================
class TestPushLog:
    @pytest.mark.asyncio
    @patch("backend.services.bot_runtime.redis_client")
    async def test_push_log_success(self, mock_redis, manager, bot):
        """日志写入成功"""
        mock_redis.lpush = AsyncMock()
        mock_redis.ltrim = AsyncMock()
        mock_redis.expire = AsyncMock()
        mock_redis.publish = AsyncMock()

        await manager._push_log(bot, "info", "test message")

        mock_redis.lpush.assert_called_once()
        mock_redis.ltrim.assert_called_once()
        mock_redis.publish.assert_called_once()

    @pytest.mark.asyncio
    @patch("backend.services.bot_runtime.redis_client")
    async def test_push_log_redis_error(self, mock_redis, manager, bot):
        """Redis 写入失败不抛异常"""
        mock_redis.lpush = AsyncMock(side_effect=Exception("Redis down"))

        # 不应该抛出异常
        await manager._push_log(bot, "info", "test message")


# ==========================================
# _get_recent_logs 测试
# ==========================================
class TestGetRecentLogs:
    @pytest.mark.asyncio
    @patch("backend.services.bot_runtime.redis_client")
    async def test_get_logs_success(self, mock_redis, manager):
        """获取日志成功"""
        logs = [
            json.dumps({"time": "10:00:00", "msg": "hello", "type": "info"}),
            json.dumps({"time": "10:01:00", "msg": "world", "type": "success"}),
        ]
        mock_redis.lrange = AsyncMock(return_value=logs)

        result = await manager._get_recent_logs("bot_1", limit=20)
        assert len(result) == 2
        assert result[0]["msg"] == "hello"

    @pytest.mark.asyncio
    @patch("backend.services.bot_runtime.redis_client")
    async def test_get_logs_invalid_json(self, mock_redis, manager):
        """无效 JSON 被跳过"""
        logs = ["not_json", json.dumps({"time": "10:00:00", "msg": "ok", "type": "info"})]
        mock_redis.lrange = AsyncMock(return_value=logs)

        result = await manager._get_recent_logs("bot_1")
        assert len(result) == 1

    @pytest.mark.asyncio
    @patch("backend.services.bot_runtime.redis_client")
    async def test_get_logs_redis_error(self, mock_redis, manager):
        """Redis 异常返回空列表"""
        mock_redis.lrange = AsyncMock(side_effect=Exception("timeout"))

        result = await manager._get_recent_logs("bot_1")
        assert result == []


# ==========================================
# _update_bot_stats 测试
# ==========================================
class TestUpdateBotStats:
    @pytest.mark.asyncio
    @patch("backend.services.bot_runtime.redis_client")
    async def test_update_stats(self, mock_redis, manager, bot):
        """资源统计写入"""
        mock_redis.hset = AsyncMock()
        mock_redis.expire = AsyncMock()

        await manager._update_bot_stats(bot)
        mock_redis.hset.assert_called_once()
        mock_redis.expire.assert_called_once()

    @pytest.mark.asyncio
    @patch("backend.services.bot_runtime.redis_client")
    async def test_update_stats_error(self, mock_redis, manager, bot):
        """写入失败不抛异常"""
        mock_redis.hset = AsyncMock(side_effect=Exception("fail"))
        await manager._update_bot_stats(bot)


# ==========================================
# _save_bot_meta 测试
# ==========================================
class TestSaveBotMeta:
    @pytest.mark.asyncio
    @patch("backend.services.bot_runtime.redis_client")
    async def test_save_meta(self, mock_redis, manager, bot):
        """元数据保存"""
        mock_redis.hset = AsyncMock()

        await manager._save_bot_meta(bot)
        assert mock_redis.hset.call_count == 2  # meta key + registry

    @pytest.mark.asyncio
    @patch("backend.services.bot_runtime.redis_client")
    async def test_save_meta_error(self, mock_redis, manager, bot):
        """保存失败不抛异常"""
        mock_redis.hset = AsyncMock(side_effect=Exception("fail"))
        await manager._save_bot_meta(bot)


# ==========================================
# _fetch_latest_quote 测试
# ==========================================
class TestFetchLatestQuote:
    @pytest.mark.asyncio
    @patch("backend.services.futu_service.futu_service")
    async def test_fetch_quote_success(self, mock_futu, manager):
        """行情获取成功"""
        mock_futu.get_quote = AsyncMock(return_value={"status": "success", "data": {"last_price": 150.0}})
        result = await manager._fetch_latest_quote("US.AAPL")
        assert result["status"] == "success"

    @pytest.mark.asyncio
    @patch("backend.services.futu_service.futu_service")
    async def test_fetch_quote_error(self, mock_futu, manager):
        """行情获取异常返回 None"""
        mock_futu.get_quote = AsyncMock(side_effect=Exception("timeout"))
        result = await manager._fetch_latest_quote("US.AAPL")
        assert result is None


# ==========================================
# _execute_strategy 测试
# ==========================================
class TestExecuteStrategy:
    @pytest.mark.asyncio
    async def test_no_strategy_file(self, manager, bot):
        """策略文件不存在"""
        result = await manager._execute_strategy(bot, {"status": "success"})
        assert result is None

    @pytest.mark.asyncio
    async def test_strategy_with_on_tick(self, manager, bot, tmp_path):
        """策略有 on_tick 方法"""
        strategy_code = """
class TestStrategy:
    def on_tick(self, quote, params):
        return "BUY signal"
"""
        strategy_file = tmp_path / "teststrategy.py"
        strategy_file.write_text(strategy_code)

        with patch("backend.services.bot_runtime._STRATEGIES_DIR", str(tmp_path)):
            result = await manager._execute_strategy(bot, {"status": "success", "data": {"last_price": 150}})
            assert result is not None
            assert "BUY signal" in result

    @pytest.mark.asyncio
    async def test_strategy_without_on_tick(self, manager, bot, tmp_path):
        """策略无 on_tick 方法"""
        strategy_code = """
class TestStrategy:
    def calculate(self):
        pass
"""
        strategy_file = tmp_path / "teststrategy.py"
        strategy_file.write_text(strategy_code)

        with patch("backend.services.bot_runtime._STRATEGIES_DIR", str(tmp_path)):
            result = await manager._execute_strategy(bot, {"status": "success"})
            assert result is None

    @pytest.mark.asyncio
    async def test_strategy_load_error(self, manager, bot, tmp_path):
        """策略加载异常"""
        strategy_file = tmp_path / "teststrategy.py"
        strategy_file.write_text("raise RuntimeError('broken')")

        with patch("backend.services.bot_runtime._STRATEGIES_DIR", str(tmp_path)):
            result = await manager._execute_strategy(bot, None)
            assert result is None


# ==========================================
# _run_bot_loop 测试
# ==========================================
class TestRunBotLoop:
    @pytest.mark.asyncio
    @patch("backend.services.bot_runtime.redis_client")
    async def test_loop_stop_immediately(self, mock_redis, manager, bot):
        """立即停止"""
        mock_redis.lpush = AsyncMock()
        mock_redis.ltrim = AsyncMock()
        mock_redis.expire = AsyncMock()
        mock_redis.publish = AsyncMock()
        mock_redis.hset = AsyncMock()

        bot._stop_requested = True
        await manager._run_bot_loop(bot)
        assert bot.status == "stopped"

    @pytest.mark.asyncio
    @patch("backend.services.bot_runtime.redis_client")
    async def test_loop_one_iteration(self, mock_redis, manager, bot):
        """运行一轮后停止"""
        mock_redis.lpush = AsyncMock()
        mock_redis.ltrim = AsyncMock()
        mock_redis.expire = AsyncMock()
        mock_redis.publish = AsyncMock()
        mock_redis.hset = AsyncMock()

        manager._fetch_latest_quote = AsyncMock(return_value={"status": "success", "data": {"last_price": 150.0}})
        manager._execute_strategy = AsyncMock(return_value=None)
        manager._update_bot_stats = AsyncMock()
        manager._save_bot_meta = AsyncMock()
        manager._broadcast_bots_update = AsyncMock()

        # 运行一轮后设置停止
        original_sleep = asyncio.sleep

        async def mock_sleep(seconds):
            bot._stop_requested = True

        with patch("asyncio.sleep", side_effect=mock_sleep):
            await manager._run_bot_loop(bot)

        assert bot.status == "stopped"

    @pytest.mark.asyncio
    @patch("backend.services.bot_runtime.redis_client")
    async def test_loop_cancelled(self, mock_redis, manager, bot):
        """CancelledError 处理"""
        mock_redis.lpush = AsyncMock()
        mock_redis.ltrim = AsyncMock()
        mock_redis.expire = AsyncMock()
        mock_redis.publish = AsyncMock()
        mock_redis.hset = AsyncMock()

        manager._save_bot_meta = AsyncMock()
        manager._broadcast_bots_update = AsyncMock()

        # 让 pause_event.wait() 抛出 CancelledError
        bot._pause_event = MagicMock()
        bot._pause_event.wait = AsyncMock(side_effect=asyncio.CancelledError())

        with pytest.raises(asyncio.CancelledError):
            await manager._run_bot_loop(bot)


# ==========================================
# restore_bots_from_redis 测试
# ==========================================
class TestRestoreBots:
    @pytest.mark.asyncio
    @patch("backend.services.bot_runtime.redis_client")
    async def test_restore_empty(self, mock_redis, manager):
        """无注册表"""
        mock_redis.hgetall = AsyncMock(return_value={})
        count = await manager.restore_bots_from_redis()
        assert count == 0

    @pytest.mark.asyncio
    @patch("backend.services.bot_runtime.redis_client")
    async def test_restore_with_running_bot(self, mock_redis, manager, tmp_path):
        """恢复运行中的 bot"""
        meta = {
            "id": "bot_1",
            "name": "TestBot",
            "ticker": "US.AAPL",
            "class_name": "TestStrategy",
            "params": "{}",
            "status": "running",
        }
        mock_redis.hgetall = AsyncMock(return_value={"bot_1": json.dumps(meta)})

        # 创建策略文件
        strategy_file = tmp_path / "teststrategy.py"
        strategy_file.write_text("class TestStrategy: pass")

        manager.start_bot = AsyncMock()

        with patch("backend.services.bot_runtime._STRATEGIES_DIR", str(tmp_path)):
            count = await manager.restore_bots_from_redis()

        assert count == 1
        manager.start_bot.assert_called_once()

    @pytest.mark.asyncio
    @patch("backend.services.bot_runtime.redis_client")
    async def test_restore_no_strategy_file(self, mock_redis, manager):
        """策略文件不存在跳过"""
        meta = {
            "id": "bot_1",
            "name": "TestBot",
            "ticker": "US.AAPL",
            "class_name": "NonExistStrategy",
            "params": "{}",
            "status": "running",
        }
        mock_redis.hgetall = AsyncMock(return_value={"bot_1": json.dumps(meta)})

        with patch("backend.services.bot_runtime._STRATEGIES_DIR", "/nonexist"):
            count = await manager.restore_bots_from_redis()

        assert count == 0

    @pytest.mark.asyncio
    @patch("backend.services.bot_runtime.redis_client")
    async def test_restore_redis_error(self, mock_redis, manager):
        """Redis 异常"""
        mock_redis.hgetall = AsyncMock(side_effect=Exception("down"))
        count = await manager.restore_bots_from_redis()
        assert count == 0

    @pytest.mark.asyncio
    @patch("backend.services.bot_runtime.redis_client")
    async def test_restore_paused_bot(self, mock_redis, manager, tmp_path):
        """恢复暂停的 bot"""
        meta = {
            "id": "bot_2",
            "name": "PausedBot",
            "ticker": "US.TSLA",
            "class_name": "TestStrategy",
            "params": "{}",
            "status": "paused",
        }
        mock_redis.hgetall = AsyncMock(return_value={"bot_2": json.dumps(meta)})

        strategy_file = tmp_path / "teststrategy.py"
        strategy_file.write_text("class TestStrategy: pass")

        manager.start_bot = AsyncMock()
        manager.pause_bot = AsyncMock()

        with patch("backend.services.bot_runtime._STRATEGIES_DIR", str(tmp_path)):
            count = await manager.restore_bots_from_redis()

        assert count == 1
        manager.pause_bot.assert_called_once_with("bot_2")
