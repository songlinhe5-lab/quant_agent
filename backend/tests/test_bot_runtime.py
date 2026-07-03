"""
Bot Runtime 单元测试
覆盖: backend/services/bot_runtime.py
"""

import asyncio
import json
import os
import sys
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))


async def _mock_bot_loop(self, bot):
    """Mock 的 bot 运行循环 - 只等待停止信号"""
    while not bot._stop_requested:
        await bot._pause_event.wait()
        if bot._stop_requested:
            break
        await asyncio.sleep(0.01)


# ─── BotInstance 单元测试 ──────────────────────────────────────────────────────
class TestBotInstance:
    """BotInstance 数据结构测试"""

    def test_bot_instance_init(self):
        """BotInstance 初始化"""
        from backend.services.bot_runtime import BotInstance

        bot = BotInstance(
            bot_id="bot_001",
            name="TestBot",
            ticker="00700.HK",
            class_name="DualMAATrStopStrategy",
            params={"short_window": 5, "long_window": 20},
        )

        assert bot.bot_id == "bot_001"
        assert bot.name == "TestBot"
        assert bot.ticker == "00700.HK"
        assert bot.class_name == "DualMAATrStopStrategy"
        assert bot.params == {"short_window": 5, "long_window": 20}
        assert bot.status == "running"
        assert bot._stop_requested is False

    def test_bot_instance_to_api_dict(self):
        """转 API 格式"""
        from backend.services.bot_runtime import BotInstance

        bot = BotInstance("bot_001", "TestBot", "00700.HK", "Strategy", {})
        logs = [{"time": "10:30:00", "msg": "Test log", "type": "info"}]

        result = bot.to_api_dict(logs=logs)

        assert result["id"] == "bot_001"
        assert result["name"] == "TestBot"
        assert result["ticker"] == "00700.HK"
        assert result["status"] == "running"
        assert "cpu" in result
        assert "mem" in result
        assert len(result["logs"]) == 1
        assert result["logs"][0]["msg"] == "Test log"

    def test_bot_instance_to_api_dict_no_logs(self):
        """无日志时返回空列表"""
        from backend.services.bot_runtime import BotInstance

        bot = BotInstance("bot_001", "TestBot", "00700.HK", "Strategy", {})
        result = bot.to_api_dict()

        assert result["logs"] == []

    def test_bot_instance_cpu_memory(self):
        """CPU/MEM 获取不抛异常"""
        from backend.services.bot_runtime import BotInstance

        bot = BotInstance("bot_001", "TestBot", "00700.HK", "Strategy", {})
        cpu = bot._get_cpu_percent()
        mem = bot._get_memory_mb()

        assert isinstance(cpu, float)
        assert isinstance(mem, float)
        assert cpu >= 0.0
        assert mem >= 0.0


# ─── BotRuntimeManager 单元测试 ────────────────────────────────────────────────
class TestBotRuntimeManager:
    """BotRuntimeManager 核心逻辑测试"""

    @patch("backend.services.bot_runtime.redis_client")
    @patch("backend.services.bot_runtime.BotRuntimeManager._run_bot_loop", _mock_bot_loop)
    def test_start_bot(self, mock_redis):
        """启动 Bot"""
        from backend.services.bot_runtime import BotRuntimeManager

        mock_redis.hset = AsyncMock()
        mock_redis.lpush = AsyncMock()
        mock_redis.ltrim = AsyncMock()
        mock_redis.expire = AsyncMock()
        mock_redis.publish = AsyncMock()
        mock_redis.lrange = AsyncMock(return_value=[])

        manager = BotRuntimeManager()

        bot = asyncio.run(
            manager.start_bot(
                bot_id="bot_001",
                name="TestBot",
                ticker="00700.HK",
                class_name="DualMAATrStopStrategy",
                params={"short_window": 5},
            )
        )

        assert bot.bot_id == "bot_001"
        assert bot.name == "TestBot"
        assert bot.status == "running"
        assert "bot_001" in manager._bots
        mock_redis.hset.assert_called()

    @patch("backend.services.bot_runtime.redis_client")
    @patch("backend.services.bot_runtime.BotRuntimeManager._run_bot_loop", _mock_bot_loop)
    def test_start_bot_already_running(self, mock_redis):
        """重复启动已运行 Bot 抛异常"""
        from backend.services.bot_runtime import BotRuntimeManager

        mock_redis.hset = AsyncMock()
        mock_redis.lpush = AsyncMock()
        mock_redis.ltrim = AsyncMock()
        mock_redis.expire = AsyncMock()
        mock_redis.publish = AsyncMock()
        mock_redis.lrange = AsyncMock(return_value=[])

        manager = BotRuntimeManager()

        asyncio.run(
            manager.start_bot(
                bot_id="bot_001",
                name="TestBot",
                ticker="00700.HK",
                class_name="Strategy",
            )
        )

        try:
            asyncio.run(
                manager.start_bot(
                    bot_id="bot_001",
                    name="TestBot",
                    ticker="00700.HK",
                    class_name="Strategy",
                )
            )
            assert False, "Should raise ValueError"
        except ValueError as e:
            assert "已在运行中" in str(e)

    @patch("backend.services.bot_runtime.redis_client")
    @patch("backend.services.bot_runtime.BotRuntimeManager._run_bot_loop", _mock_bot_loop)
    def test_pause_bot(self, mock_redis):
        """暂停 Bot"""
        from backend.services.bot_runtime import BotRuntimeManager

        mock_redis.hset = AsyncMock()
        mock_redis.lpush = AsyncMock()
        mock_redis.ltrim = AsyncMock()
        mock_redis.expire = AsyncMock()
        mock_redis.publish = AsyncMock()
        mock_redis.lrange = AsyncMock(return_value=[])

        manager = BotRuntimeManager()

        bot = asyncio.run(
            manager.start_bot(
                bot_id="bot_001",
                name="TestBot",
                ticker="00700.HK",
                class_name="Strategy",
            )
        )

        result = asyncio.run(manager.pause_bot("bot_001"))
        assert result is True
        assert bot.status == "paused"
        assert bot._pause_event.is_set() is False

    @patch("backend.services.bot_runtime.redis_client")
    def test_pause_bot_not_found(self, mock_redis):
        """暂停不存在的 Bot 返回 False"""
        from backend.services.bot_runtime import BotRuntimeManager

        manager = BotRuntimeManager()

        result = asyncio.run(manager.pause_bot("nonexistent"))
        assert result is False

    @patch("backend.services.bot_runtime.redis_client")
    @patch("backend.services.bot_runtime.BotRuntimeManager._run_bot_loop", _mock_bot_loop)
    def test_resume_bot(self, mock_redis):
        """恢复暂停的 Bot"""
        from backend.services.bot_runtime import BotRuntimeManager

        mock_redis.hset = AsyncMock()
        mock_redis.lpush = AsyncMock()
        mock_redis.ltrim = AsyncMock()
        mock_redis.expire = AsyncMock()
        mock_redis.publish = AsyncMock()
        mock_redis.lrange = AsyncMock(return_value=[])

        manager = BotRuntimeManager()

        bot = asyncio.run(
            manager.start_bot(
                bot_id="bot_001",
                name="TestBot",
                ticker="00700.HK",
                class_name="Strategy",
            )
        )

        asyncio.run(manager.pause_bot("bot_001"))
        result = asyncio.run(manager.resume_bot("bot_001"))

        assert result is True
        assert bot.status == "running"
        assert bot._pause_event.is_set() is True

    @patch("backend.services.bot_runtime.redis_client")
    @patch("backend.services.bot_runtime.BotRuntimeManager._run_bot_loop", _mock_bot_loop)
    def test_resume_bot_not_paused(self, mock_redis):
        """恢复非 paused 状态 Bot 返回 False"""
        from backend.services.bot_runtime import BotRuntimeManager

        mock_redis.hset = AsyncMock()
        mock_redis.lpush = AsyncMock()
        mock_redis.ltrim = AsyncMock()
        mock_redis.expire = AsyncMock()
        mock_redis.publish = AsyncMock()
        mock_redis.lrange = AsyncMock(return_value=[])

        manager = BotRuntimeManager()

        asyncio.run(
            manager.start_bot(
                bot_id="bot_001",
                name="TestBot",
                ticker="00700.HK",
                class_name="Strategy",
            )
        )

        result = asyncio.run(manager.resume_bot("bot_001"))
        assert result is False

    @patch("backend.services.bot_runtime.redis_client")
    @patch("backend.services.bot_runtime.BotRuntimeManager._run_bot_loop", _mock_bot_loop)
    def test_stop_bot(self, mock_redis):
        """终止 Bot"""
        from backend.services.bot_runtime import BotRuntimeManager

        mock_redis.hset = AsyncMock()
        mock_redis.lpush = AsyncMock()
        mock_redis.ltrim = AsyncMock()
        mock_redis.expire = AsyncMock()
        mock_redis.publish = AsyncMock()
        mock_redis.lrange = AsyncMock(return_value=[])

        manager = BotRuntimeManager()

        bot = asyncio.run(
            manager.start_bot(
                bot_id="bot_001",
                name="TestBot",
                ticker="00700.HK",
                class_name="Strategy",
            )
        )

        result = asyncio.run(manager.stop_bot("bot_001"))
        assert result is True
        assert bot.status == "stopped"
        assert bot._stop_requested is True

    @patch("backend.services.bot_runtime.redis_client")
    def test_stop_bot_not_found(self, mock_redis):
        """终止不存在的 Bot 返回 False"""
        from backend.services.bot_runtime import BotRuntimeManager

        manager = BotRuntimeManager()

        result = asyncio.run(manager.stop_bot("nonexistent"))
        assert result is False

    @patch("backend.services.bot_runtime.redis_client")
    @patch("backend.services.bot_runtime.BotRuntimeManager._run_bot_loop", _mock_bot_loop)
    def test_stop_all_bots(self, mock_redis):
        """Kill Switch: 终止所有运行中 Bot"""
        from backend.services.bot_runtime import BotRuntimeManager

        mock_redis.hset = AsyncMock()
        mock_redis.lpush = AsyncMock()
        mock_redis.ltrim = AsyncMock()
        mock_redis.expire = AsyncMock()
        mock_redis.publish = AsyncMock()
        mock_redis.lrange = AsyncMock(return_value=[])

        manager = BotRuntimeManager()

        asyncio.run(manager.start_bot(bot_id="bot_001", name="Bot1", ticker="00700.HK", class_name="Strategy"))
        asyncio.run(manager.start_bot(bot_id="bot_002", name="Bot2", ticker="09988.HK", class_name="Strategy"))

        result = asyncio.run(manager.stop_all_bots())
        assert result == 2

    @patch("backend.services.bot_runtime.redis_client")
    @patch("backend.services.bot_runtime.BotRuntimeManager._run_bot_loop", _mock_bot_loop)
    def test_get_all_bots(self, mock_redis):
        """获取所有 Bot 状态"""
        from backend.services.bot_runtime import BotRuntimeManager

        mock_redis.hset = AsyncMock()
        mock_redis.lpush = AsyncMock()
        mock_redis.ltrim = AsyncMock()
        mock_redis.expire = AsyncMock()
        mock_redis.publish = AsyncMock()
        mock_redis.lrange = AsyncMock(return_value=[])

        manager = BotRuntimeManager()

        asyncio.run(manager.start_bot(bot_id="bot_001", name="Bot1", ticker="00700.HK", class_name="Strategy"))
        asyncio.run(manager.start_bot(bot_id="bot_002", name="Bot2", ticker="09988.HK", class_name="Strategy"))

        result = asyncio.run(manager.get_all_bots())
        assert len(result) == 2

    @patch("backend.services.bot_runtime.redis_client")
    @patch("backend.services.bot_runtime.BotRuntimeManager._run_bot_loop", _mock_bot_loop)
    def test_get_bot(self, mock_redis):
        """获取单个 Bot 实例"""
        from backend.services.bot_runtime import BotRuntimeManager

        mock_redis.hset = AsyncMock()
        mock_redis.lpush = AsyncMock()
        mock_redis.ltrim = AsyncMock()
        mock_redis.expire = AsyncMock()
        mock_redis.publish = AsyncMock()
        mock_redis.lrange = AsyncMock(return_value=[])

        manager = BotRuntimeManager()

        asyncio.run(manager.start_bot(bot_id="bot_001", name="Bot1", ticker="00700.HK", class_name="Strategy"))

        bot = manager.get_bot("bot_001")
        assert bot is not None
        assert bot.bot_id == "bot_001"

        none_bot = manager.get_bot("nonexistent")
        assert none_bot is None

    @patch("backend.services.bot_runtime.redis_client")
    def test_push_log(self, mock_redis):
        """日志写入 Redis"""
        from backend.services.bot_runtime import BotInstance, BotRuntimeManager

        mock_redis.lpush = AsyncMock()
        mock_redis.ltrim = AsyncMock()
        mock_redis.expire = AsyncMock()
        mock_redis.publish = AsyncMock()

        manager = BotRuntimeManager()
        bot = BotInstance("bot_001", "TestBot", "00700.HK", "Strategy", {})

        asyncio.run(manager._push_log(bot, "info", "Test message"))

        mock_redis.lpush.assert_called_once()
        mock_redis.publish.assert_called_once()

    @patch("backend.services.bot_runtime.redis_client")
    def test_get_recent_logs(self, mock_redis):
        """读取最近日志"""
        from backend.services.bot_runtime import BotRuntimeManager

        log_entries = [
            json.dumps({"time": "10:30:00", "msg": "Log 1", "type": "info"}),
            json.dumps({"time": "10:31:00", "msg": "Log 2", "type": "warn"}),
        ]
        mock_redis.lrange = AsyncMock(return_value=log_entries)

        manager = BotRuntimeManager()

        result = asyncio.run(manager._get_recent_logs("bot_001", limit=10))

        assert len(result) == 2
        assert result[0]["msg"] == "Log 1"
        assert result[1]["type"] == "warn"

    @patch("backend.services.bot_runtime.redis_client")
    def test_get_recent_logs_empty(self, mock_redis):
        """无日志时返回空列表"""
        from backend.services.bot_runtime import BotRuntimeManager

        mock_redis.lrange = AsyncMock(return_value=[])

        manager = BotRuntimeManager()

        result = asyncio.run(manager._get_recent_logs("bot_001"))
        assert result == []

    @patch("backend.services.bot_runtime.redis_client")
    def test_restore_bots_from_redis_empty(self, mock_redis):
        """Redis 无注册表时恢复 0"""
        from backend.services.bot_runtime import BotRuntimeManager

        mock_redis.hgetall = AsyncMock(return_value={})

        manager = BotRuntimeManager()

        result = asyncio.run(manager.restore_bots_from_redis())
        assert result == 0

    @patch("backend.services.bot_runtime.redis_client")
    @patch("backend.services.bot_runtime.BotRuntimeManager._run_bot_loop", _mock_bot_loop)
    def test_shutdown(self, mock_redis):
        """优雅关停"""
        from backend.services.bot_runtime import BotRuntimeManager

        mock_redis.hset = AsyncMock()
        mock_redis.lpush = AsyncMock()
        mock_redis.ltrim = AsyncMock()
        mock_redis.expire = AsyncMock()
        mock_redis.publish = AsyncMock()
        mock_redis.lrange = AsyncMock(return_value=[])

        manager = BotRuntimeManager()

        asyncio.run(manager.start_bot(bot_id="bot_001", name="Bot1", ticker="00700.HK", class_name="Strategy"))

        asyncio.run(manager.shutdown())

        assert len(manager._bots) == 1
        assert manager._bots["bot_001"].status == "stopped"
