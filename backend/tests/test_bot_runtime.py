"""
Bot 运行时引擎测试
覆盖: backend/services/bot_runtime.py
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


# ==========================================
# BotInstance 测试
# ==========================================
class TestBotInstance:
    def test_creation(self):
        """创建 Bot 实例"""
        bot = BotInstance("bot_1", "TestBot", "US.AAPL", "MACrossStrategy", {"fast": 5, "slow": 20})
        assert bot.bot_id == "bot_1"
        assert bot.name == "TestBot"
        assert bot.ticker == "US.AAPL"
        assert bot.class_name == "MACrossStrategy"
        assert bot.params == {"fast": 5, "slow": 20}
        assert bot.status == "running"

    def test_to_api_dict(self):
        """API 字典格式"""
        bot = BotInstance("bot_1", "TestBot", "US.AAPL", "MACrossStrategy", {})
        d = bot.to_api_dict(logs=[{"msg": "hello"}])
        assert d["id"] == "bot_1"
        assert d["name"] == "TestBot"
        assert d["ticker"] == "US.AAPL"
        assert d["status"] == "running"
        assert "cpu" in d
        assert "mem" in d
        assert d["logs"] == [{"msg": "hello"}]

    def test_to_api_dict_no_logs(self):
        """无日志时默认空列表"""
        bot = BotInstance("bot_1", "TestBot", "US.AAPL", "Strat", {})
        d = bot.to_api_dict()
        assert d["logs"] == []

    def test_get_cpu_percent(self):
        """CPU 使用率获取"""
        bot = BotInstance("bot_1", "TestBot", "US.AAPL", "Strat", {})
        cpu = bot._get_cpu_percent()
        assert isinstance(cpu, float)
        assert cpu >= 0.0

    def test_get_memory_mb(self):
        """内存占用获取"""
        bot = BotInstance("bot_1", "TestBot", "US.AAPL", "Strat", {})
        mem = bot._get_memory_mb()
        assert isinstance(mem, float)
        assert mem > 0.0

    def test_get_cpu_percent_exception(self):
        """CPU 获取异常时返回 0"""
        bot = BotInstance("bot_1", "TestBot", "US.AAPL", "Strat", {})
        bot._process = MagicMock()
        bot._process.cpu_percent.side_effect = Exception("psutil error")
        assert bot._get_cpu_percent() == 0.0

    def test_get_memory_mb_exception(self):
        """内存获取异常时返回 0"""
        bot = BotInstance("bot_1", "TestBot", "US.AAPL", "Strat", {})
        bot._process = MagicMock()
        bot._process.memory_info.side_effect = Exception("psutil error")
        assert bot._get_memory_mb() == 0.0


# ==========================================
# BotRuntimeManager 测试
# ==========================================
class TestBotRuntimeManager:
    @pytest.fixture
    def manager(self):
        return BotRuntimeManager()

    @pytest.mark.asyncio
    @patch("backend.services.bot_runtime.redis_client")
    async def test_start_bot(self, mock_redis, manager):
        """启动 Bot"""
        mock_redis.hset = AsyncMock()
        mock_redis.publish = AsyncMock()
        mock_redis.lpush = AsyncMock()
        mock_redis.ltrim = AsyncMock()
        mock_redis.expire = AsyncMock()
        mock_redis.lrange = AsyncMock(return_value=[])

        with patch.object(manager, "_run_bot_loop", new_callable=AsyncMock):
            bot = await manager.start_bot("bot_1", "TestBot", "US.AAPL", "MACrossStrategy", {"fast": 5})
            assert bot.bot_id == "bot_1"
            assert bot.status == "running"
            assert "bot_1" in manager._bots

    @pytest.mark.asyncio
    @patch("backend.services.bot_runtime.redis_client")
    async def test_start_bot_duplicate(self, mock_redis, manager):
        """重复启动同一 Bot 报错"""
        mock_redis.hset = AsyncMock()
        mock_redis.publish = AsyncMock()
        mock_redis.lpush = AsyncMock()
        mock_redis.ltrim = AsyncMock()
        mock_redis.expire = AsyncMock()
        mock_redis.lrange = AsyncMock(return_value=[])

        with patch.object(manager, "_run_bot_loop", new_callable=AsyncMock):
            await manager.start_bot("bot_1", "TestBot", "US.AAPL", "Strat", {})
            with pytest.raises(ValueError, match="已在运行中"):
                await manager.start_bot("bot_1", "TestBot2", "US.TSLA", "Strat2", {})

    @pytest.mark.asyncio
    @patch("backend.services.bot_runtime.redis_client")
    async def test_pause_bot(self, mock_redis, manager):
        """暂停 Bot"""
        mock_redis.hset = AsyncMock()
        mock_redis.publish = AsyncMock()
        mock_redis.lpush = AsyncMock()
        mock_redis.ltrim = AsyncMock()
        mock_redis.expire = AsyncMock()
        mock_redis.lrange = AsyncMock(return_value=[])

        bot = BotInstance("bot_1", "TestBot", "US.AAPL", "Strat", {})
        manager._bots["bot_1"] = bot
        result = await manager.pause_bot("bot_1")
        assert result is True
        assert bot.status == "paused"

    @pytest.mark.asyncio
    async def test_pause_nonexistent(self, manager):
        """暂停不存在的 Bot"""
        result = await manager.pause_bot("nonexist")
        assert result is False

    @pytest.mark.asyncio
    async def test_pause_not_running(self, manager):
        """暂停非运行中的 Bot"""
        bot = BotInstance("bot_1", "TestBot", "US.AAPL", "Strat", {})
        bot.status = "stopped"
        manager._bots["bot_1"] = bot
        result = await manager.pause_bot("bot_1")
        assert result is False

    @pytest.mark.asyncio
    @patch("backend.services.bot_runtime.redis_client")
    async def test_resume_bot(self, mock_redis, manager):
        """恢复 Bot"""
        mock_redis.hset = AsyncMock()
        mock_redis.publish = AsyncMock()
        mock_redis.lpush = AsyncMock()
        mock_redis.ltrim = AsyncMock()
        mock_redis.expire = AsyncMock()
        mock_redis.lrange = AsyncMock(return_value=[])

        bot = BotInstance("bot_1", "TestBot", "US.AAPL", "Strat", {})
        bot.status = "paused"
        bot._pause_event.clear()
        manager._bots["bot_1"] = bot
        result = await manager.resume_bot("bot_1")
        assert result is True
        assert bot.status == "running"

    @pytest.mark.asyncio
    async def test_resume_not_paused(self, manager):
        """恢复非暂停的 Bot"""
        bot = BotInstance("bot_1", "TestBot", "US.AAPL", "Strat", {})
        bot.status = "running"
        manager._bots["bot_1"] = bot
        result = await manager.resume_bot("bot_1")
        assert result is False

    @pytest.mark.asyncio
    @patch("backend.services.bot_runtime.redis_client")
    async def test_stop_bot(self, mock_redis, manager):
        """终止 Bot"""
        mock_redis.hset = AsyncMock()
        mock_redis.publish = AsyncMock()
        mock_redis.lpush = AsyncMock()
        mock_redis.ltrim = AsyncMock()
        mock_redis.expire = AsyncMock()
        mock_redis.lrange = AsyncMock(return_value=[])

        bot = BotInstance("bot_1", "TestBot", "US.AAPL", "Strat", {})
        manager._bots["bot_1"] = bot
        result = await manager.stop_bot("bot_1")
        assert result is True
        assert bot.status == "stopped"

    @pytest.mark.asyncio
    async def test_stop_nonexistent(self, manager):
        """终止不存在的 Bot"""
        result = await manager.stop_bot("nonexist")
        assert result is False

    @pytest.mark.asyncio
    @patch("backend.services.bot_runtime.redis_client")
    async def test_stop_all_bots(self, mock_redis, manager):
        """Kill Switch 终止所有"""
        mock_redis.hset = AsyncMock()
        mock_redis.publish = AsyncMock()
        mock_redis.lpush = AsyncMock()
        mock_redis.ltrim = AsyncMock()
        mock_redis.expire = AsyncMock()
        mock_redis.lrange = AsyncMock(return_value=[])

        for i in range(3):
            bot = BotInstance(f"bot_{i}", f"Bot{i}", "US.AAPL", "Strat", {})
            manager._bots[f"bot_{i}"] = bot
        count = await manager.stop_all_bots()
        assert count == 3

    @pytest.mark.asyncio
    @patch("backend.services.bot_runtime.redis_client")
    async def test_get_all_bots(self, mock_redis, manager):
        """获取所有 Bot"""
        mock_redis.lrange = AsyncMock(return_value=[])
        bot = BotInstance("bot_1", "TestBot", "US.AAPL", "Strat", {})
        manager._bots["bot_1"] = bot
        result = await manager.get_all_bots()
        assert len(result) == 1
        assert result[0]["id"] == "bot_1"

    def test_get_bot(self, manager):
        """获取单个 Bot"""
        bot = BotInstance("bot_1", "TestBot", "US.AAPL", "Strat", {})
        manager._bots["bot_1"] = bot
        assert manager.get_bot("bot_1") is bot
        assert manager.get_bot("nonexist") is None

    @pytest.mark.asyncio
    @patch("backend.services.bot_runtime.redis_client")
    async def test_push_log(self, mock_redis, manager):
        """日志写入 Redis"""
        mock_redis.lpush = AsyncMock()
        mock_redis.ltrim = AsyncMock()
        mock_redis.expire = AsyncMock()
        mock_redis.publish = AsyncMock()
        bot = BotInstance("bot_1", "TestBot", "US.AAPL", "Strat", {})
        await manager._push_log(bot, "info", "测试日志")
        mock_redis.lpush.assert_called_once()
        mock_redis.publish.assert_called_once()

    @pytest.mark.asyncio
    @patch("backend.services.bot_runtime.redis_client")
    async def test_get_recent_logs(self, mock_redis, manager):
        """读取最近日志"""
        mock_redis.lrange = AsyncMock(return_value=[json.dumps({"time": "12:00:00", "msg": "hello", "type": "info"})])
        logs = await manager._get_recent_logs("bot_1", limit=5)
        assert len(logs) == 1
        assert logs[0]["msg"] == "hello"

    @pytest.mark.asyncio
    @patch("backend.services.bot_runtime.redis_client")
    async def test_get_recent_logs_invalid_json(self, mock_redis, manager):
        """日志 JSON 解析失败时跳过"""
        mock_redis.lrange = AsyncMock(return_value=["invalid_json", json.dumps({"msg": "ok"})])
        logs = await manager._get_recent_logs("bot_1")
        assert len(logs) == 1

    @pytest.mark.asyncio
    @patch("backend.services.bot_runtime.redis_client")
    async def test_update_bot_stats(self, mock_redis, manager):
        """资源统计写入 Redis"""
        mock_redis.hset = AsyncMock()
        mock_redis.expire = AsyncMock()
        bot = BotInstance("bot_1", "TestBot", "US.AAPL", "Strat", {})
        await manager._update_bot_stats(bot)
        mock_redis.hset.assert_called_once()

    @pytest.mark.asyncio
    @patch("backend.services.bot_runtime.redis_client")
    async def test_save_bot_meta(self, mock_redis, manager):
        """元数据写入 Redis"""
        mock_redis.hset = AsyncMock()
        bot = BotInstance("bot_1", "TestBot", "US.AAPL", "Strat", {"fast": 5})
        await manager._save_bot_meta(bot)
        assert mock_redis.hset.call_count == 2  # meta + registry

    @pytest.mark.asyncio
    @patch("backend.services.bot_runtime.redis_client")
    async def test_restore_bots_from_redis_empty(self, mock_redis, manager):
        """Redis 无数据时恢复 0 个"""
        mock_redis.hgetall = AsyncMock(return_value={})
        count = await manager.restore_bots_from_redis()
        assert count == 0

    @pytest.mark.asyncio
    @patch("backend.services.bot_runtime.redis_client")
    async def test_restore_bots_from_redis_with_data(self, mock_redis, manager):
        """从 Redis 恢复 Bot"""
        mock_redis.hgetall = AsyncMock(
            return_value={
                "bot_1": json.dumps(
                    {
                        "name": "TestBot",
                        "ticker": "US.AAPL",
                        "class_name": "MACross",
                        "params": "{}",
                        "status": "running",
                    }
                )
            }
        )
        with patch.object(manager, "start_bot", new_callable=AsyncMock) as mock_start:
            mock_start.return_value = BotInstance("bot_1", "TestBot", "US.AAPL", "MACross", {})
            with patch("os.path.exists", return_value=True):
                count = await manager.restore_bots_from_redis()
        assert count == 1

    @pytest.mark.asyncio
    @patch("backend.services.bot_runtime.redis_client")
    async def test_restore_bots_file_not_exists(self, mock_redis, manager):
        """策略文件不存在时跳过"""
        mock_redis.hgetall = AsyncMock(
            return_value={
                "bot_1": json.dumps(
                    {
                        "name": "TestBot",
                        "ticker": "US.AAPL",
                        "class_name": "NoFile",
                        "params": "{}",
                        "status": "running",
                    }
                )
            }
        )
        with patch("os.path.exists", return_value=False):
            count = await manager.restore_bots_from_redis()
        assert count == 0

    @pytest.mark.asyncio
    @patch("backend.services.bot_runtime.redis_client")
    async def test_shutdown(self, mock_redis, manager):
        """优雅关停"""
        mock_redis.hset = AsyncMock()
        mock_redis.publish = AsyncMock()
        mock_redis.lpush = AsyncMock()
        mock_redis.ltrim = AsyncMock()
        mock_redis.expire = AsyncMock()
        mock_redis.lrange = AsyncMock(return_value=[])
        bot = BotInstance("bot_1", "TestBot", "US.AAPL", "Strat", {})
        manager._bots["bot_1"] = bot
        await manager.shutdown()
        assert bot.status == "stopped"

    @pytest.mark.asyncio
    @patch("backend.services.bot_runtime.redis_client")
    async def test_fetch_latest_quote_success(self, mock_redis, manager):
        """获取行情成功"""
        with patch("backend.services.bot_runtime.futu_service", create=True) as mock_futu:
            mock_futu.get_quote = AsyncMock(return_value={"status": "success", "last_price": 150.0})
            with patch.dict("sys.modules", {"backend.services.futu_service": MagicMock(futu_service=mock_futu)}):
                result = await manager._fetch_latest_quote("US.AAPL")
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_fetch_latest_quote_failure(self, manager):
        """获取行情失败返回 None"""
        with patch("backend.services.bot_runtime.futu_service", create=True) as mock_futu:
            mock_futu.get_quote = AsyncMock(side_effect=Exception("连接失败"))
            with patch.dict("sys.modules", {"backend.services.futu_service": MagicMock(futu_service=mock_futu)}):
                result = await manager._fetch_latest_quote("US.AAPL")
        assert result is None

    @pytest.mark.asyncio
    async def test_execute_strategy_no_file(self, manager):
        """策略文件不存在返回 None"""
        bot = BotInstance("bot_1", "TestBot", "US.AAPL", "NoExistStrategy", {})
        with patch("os.path.exists", return_value=False):
            result = await manager._execute_strategy(bot, {"last_price": 150.0})
        assert result is None


# ===== Bot Runtime 增强测试 =====


async def _mock_bot_loop(self, bot):
    """Mock 的 bot 运行循环 - 只等待停止信号"""
    while not bot._stop_requested:
        await bot._pause_event.wait()
        if bot._stop_requested:
            break
        await asyncio.sleep(0.01)


# ─── BotInstance 单元测试 ──────────────────────────────────────────────────────
class TestBotInstanceEnhanced:
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
class TestBotRuntimeManagerEnhanced:
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
