"""
算力节点运行时引擎 (OMS-05~07)

职责:
- OMS-05: 策略运行时引擎 — asyncio.Task 管理策略生命周期 (启动/暂停/恢复/终止)
- OMS-06: Bot 真实资源监控 — psutil 采集 CPU/MEM，替代 Mock 随机数
- OMS-07: Bot 日志持久化 — Redis List + PubSub 广播
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import logging
import os
import time
from datetime import datetime
from typing import Any, Dict, Optional

import psutil

from backend.core.redis_client import redis_client

logger = logging.getLogger("OMS.BotRuntime")

# Redis 键空间
_BOT_META_KEY = "quant:oms:bot:{bot_id}:meta"
_BOT_STATS_KEY = "quant:oms:bot:{bot_id}:stats"
_BOT_LOGS_KEY = "quant:oms:bot:{bot_id}:logs"
_BOTS_REGISTRY_KEY = "quant:oms:bots_registry"

# 策略文件存储目录
_STRATEGIES_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "strategies", "live"))


class BotInstance:
    """单个 Bot 算力节点的运行时实例"""

    def __init__(self, bot_id: str, name: str, ticker: str, class_name: str, params: Dict[str, Any]):
        self.bot_id = bot_id
        self.name = name
        self.ticker = ticker
        self.class_name = class_name
        self.params = params
        self.status: str = "running"  # running / paused / stopped / error
        self.task: Optional[asyncio.Task] = None
        self._pause_event = asyncio.Event()
        self._pause_event.set()  # 初始为非暂停状态
        self._stop_requested = False
        self._started_at = time.time()
        self._process = psutil.Process(os.getpid())  # 当前进程句柄 (psutil)

    def to_api_dict(self, logs: list | None = None) -> Dict[str, Any]:
        """转为前端 API 格式"""
        return {
            "id": self.bot_id,
            "name": self.name,
            "ticker": self.ticker,
            "status": self.status,
            "cpu": self._get_cpu_percent(),
            "mem": self._get_memory_mb(),
            "logs": logs or [],
        }

    def _get_cpu_percent(self) -> float:
        """OMS-06: 从 psutil 获取真实 CPU 使用率"""
        try:
            return round(self._process.cpu_percent(interval=None), 1)
        except Exception:
            return 0.0

    def _get_memory_mb(self) -> float:
        """OMS-06: 从 psutil 获取真实内存占用 (MB)"""
        try:
            return round(self._process.memory_info().rss / (1024 * 1024), 0)
        except Exception:
            return 0.0


class BotRuntimeManager:
    """
    算力节点运行时管理器 (OMS-05)

    管理所有 Bot 的生命周期: 启动 / 暂停 / 恢复 / 终止
    每个 Bot 以 asyncio.Task 形式运行在主进程内
    """

    def __init__(self):
        self._bots: Dict[str, BotInstance] = {}
        self._monitor_task: Optional[asyncio.Task] = None

    # ── 生命周期管理 ─────────────────────────────────────────────────────

    async def start_bot(
        self,
        bot_id: str,
        name: str,
        ticker: str,
        class_name: str,
        params: Dict[str, Any] | None = None,
    ) -> BotInstance:
        """启动一个 Bot 算力节点"""
        if bot_id in self._bots and self._bots[bot_id].status == "running":
            raise ValueError(f"Bot {bot_id} 已在运行中")

        bot = BotInstance(
            bot_id=bot_id,
            name=name,
            ticker=ticker,
            class_name=class_name,
            params=params or {},
        )
        self._bots[bot_id] = bot

        # 创建 asyncio.Task 运行策略
        bot.task = asyncio.create_task(self._run_bot_loop(bot))

        # 注册到 Redis
        await self._save_bot_meta(bot)
        await self._broadcast_bots_update()

        await self._push_log(bot, "info", f"🚀 Bot 启动成功: {name} ({ticker})")
        logger.info(f"[BotRuntime] Bot 已启动: {bot_id} ({name})")
        return bot

    async def pause_bot(self, bot_id: str) -> bool:
        """暂停 Bot (OMS-05: asyncio.Event 清除 → 循环挂起)"""
        bot = self._bots.get(bot_id)
        if not bot or bot.status != "running":
            return False

        bot._pause_event.clear()
        bot.status = "paused"
        await self._save_bot_meta(bot)
        await self._broadcast_bots_update()
        await self._push_log(bot, "warn", f"⏸️ Bot 已暂停: {bot.name}")
        logger.info(f"[BotRuntime] Bot 已暂停: {bot_id}")
        return True

    async def resume_bot(self, bot_id: str) -> bool:
        """恢复 Bot (OMS-05: asyncio.Event 设置 → 循环恢复)"""
        bot = self._bots.get(bot_id)
        if not bot or bot.status != "paused":
            return False

        bot._pause_event.set()
        bot.status = "running"
        await self._save_bot_meta(bot)
        await self._broadcast_bots_update()
        await self._push_log(bot, "success", f"▶️ Bot 已恢复运行: {bot.name}")
        logger.info(f"[BotRuntime] Bot 已恢复: {bot_id}")
        return True

    async def stop_bot(self, bot_id: str) -> bool:
        """终止 Bot (OMS-05: 设置停止标志 + 取消 Task)"""
        bot = self._bots.get(bot_id)
        if not bot:
            return False

        bot._stop_requested = True
        bot._pause_event.set()  # 解除暂停，让循环有机会检查 stop 标志

        if bot.task and not bot.task.done():
            bot.task.cancel()
            try:
                await bot.task
            except (asyncio.CancelledError, Exception):
                pass

        bot.status = "stopped"
        await self._save_bot_meta(bot)
        await self._broadcast_bots_update()
        await self._push_log(bot, "warn", f"🛑 Bot 已终止: {bot.name}")
        logger.info(f"[BotRuntime] Bot 已终止: {bot_id}")
        return True

    async def stop_all_bots(self) -> int:
        """Kill Switch: 终止所有运行中的 Bot"""
        count = 0
        for bot_id, bot in list(self._bots.items()):
            if bot.status in ("running", "paused"):
                await self.stop_bot(bot_id)
                count += 1
        return count

    # ── 查询接口 ──────────────────────────────────────────────────────────

    async def get_all_bots(self) -> list[Dict[str, Any]]:
        """获取所有 Bot 状态 (含真实 CPU/MEM + 最近日志)"""
        result = []
        for bot in self._bots.values():
            logs = await self._get_recent_logs(bot.bot_id, limit=20)
            result.append(bot.to_api_dict(logs=logs))
        return result

    def get_bot(self, bot_id: str) -> Optional[BotInstance]:
        return self._bots.get(bot_id)

    # ── 内部: Bot 运行主循环 ─────────────────────────────────────────────

    async def _run_bot_loop(self, bot: BotInstance) -> None:
        """
        Bot 策略运行主循环 (OMS-05)

        每隔 60 秒执行一次:
        1. 检查暂停/停止标志
        2. 获取最新行情数据
        3. 尝试加载并执行策略逻辑
        4. 记录运行日志
        """
        loop_count = 0
        try:
            while not bot._stop_requested:
                # 暂停检查点
                await bot._pause_event.wait()
                if bot._stop_requested:
                    break

                loop_count += 1
                bot.status = "running"

                try:
                    # 1. 获取最新行情
                    quote = await self._fetch_latest_quote(bot.ticker)
                    if quote and quote.get("status") == "success":
                        price = quote.get("data", {}).get("last_price", 0)
                        await self._push_log(
                            bot, "info",
                            f"[#{loop_count}] {bot.ticker} 最新价: {price:.2f}"
                        )
                    else:
                        await self._push_log(
                            bot, "info",
                            f"[#{loop_count}] 行情获取中... ({bot.ticker})"
                        )

                    # 2. 尝试加载并执行策略
                    strategy_result = await self._execute_strategy(bot, quote)
                    if strategy_result:
                        await self._push_log(bot, "success", strategy_result)

                    # 3. 更新 Redis 资源统计 (OMS-06)
                    await self._update_bot_stats(bot)

                except Exception as e:
                    await self._push_log(bot, "warn", f"⚠️ 运行异常: {str(e)[:100]}")
                    logger.warning(f"[BotRuntime] Bot {bot.bot_id} 循环异常: {e}")

                # 等待下一轮 (60 秒间隔)
                await asyncio.sleep(60)

        except asyncio.CancelledError:
            await self._push_log(bot, "warn", "🛑 进程被外部终止")
            raise
        except Exception as e:
            bot.status = "error"
            await self._push_log(bot, "warn", f"💥 致命错误: {str(e)[:200]}")
            logger.error(f"[BotRuntime] Bot {bot.bot_id} 致命异常: {e}")
        finally:
            if bot.status not in ("error",):
                bot.status = "stopped"
            await self._save_bot_meta(bot)
            await self._broadcast_bots_update()

    async def _fetch_latest_quote(self, ticker: str) -> Optional[Dict[str, Any]]:
        """从 Futu 获取最新行情"""
        try:
            from backend.services.futu_service import futu_service
            return await futu_service.get_quote(ticker)
        except Exception as e:
            logger.debug(f"[BotRuntime] 行情获取失败 ({ticker}): {e}")
            return None

    async def _execute_strategy(self, bot: BotInstance, quote: Optional[Dict]) -> Optional[str]:
        """
        尝试加载并执行策略代码 (OMS-05)

        从磁盘读取部署的策略文件，动态 import 并尝试调用:
        - on_tick(quote, params) → 如果策略定义了该方法
        - 否则仅记录监控状态
        """
        strategy_file = os.path.join(_STRATEGIES_DIR, f"{bot.class_name.lower()}.py")
        if not os.path.exists(strategy_file):
            return None

        try:
            # 动态加载策略模块
            spec = importlib.util.spec_from_file_location(f"live_{bot.bot_id}", strategy_file)
            if not spec or not spec.loader:
                return None
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            # 查找策略类
            strategy_cls = getattr(module, bot.class_name, None)
            if not strategy_cls:
                # 尝试查找模块中第一个非 BaseStrategy 的类
                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    if isinstance(attr, type) and attr_name != "BaseStrategy":
                        strategy_cls = attr
                        break

            if not strategy_cls:
                return None

            # 实例化并尝试调用 on_tick
            instance = strategy_cls()
            if hasattr(instance, "on_tick"):
                result = instance.on_tick(quote, bot.params)
                if result:
                    return f"📊 策略信号: {result}"

            # 无 on_tick 方法，仅记录监控状态
            return None

        except Exception as e:
            logger.debug(f"[BotRuntime] 策略执行异常 ({bot.bot_id}): {e}")
            return None

    # ── 内部: 日志持久化 (OMS-07) ────────────────────────────────────────

    async def _push_log(self, bot: BotInstance, log_type: str, message: str) -> None:
        """OMS-07: 写入 Redis List + PubSub 广播"""
        log_entry = {
            "time": datetime.now().strftime("%H:%M:%S"),
            "msg": message,
            "type": log_type,
        }
        redis_key = _BOT_LOGS_KEY.format(bot_id=bot.bot_id)

        try:
            # 写入 Redis List (左侧推入，保留最近 200 条)
            await redis_client.lpush(redis_key, json.dumps(log_entry))
            await redis_client.ltrim(redis_key, 0, 199)
            await redis_client.expire(redis_key, 86400)  # 24h TTL

            # PubSub 广播给 WebSocket 客户端
            payload = {"bot_id": bot.bot_id, "log": log_entry}
            await redis_client.publish("oms:bot_log:stream", json.dumps(payload))
        except Exception as e:
            logger.debug(f"[BotRuntime] 日志写入失败: {e}")

    async def _get_recent_logs(self, bot_id: str, limit: int = 20) -> list[Dict[str, Any]]:
        """从 Redis 读取最近 N 条日志"""
        redis_key = _BOT_LOGS_KEY.format(bot_id=bot_id)
        try:
            raw_logs = await redis_client.lrange(redis_key, 0, limit - 1)
            logs = []
            for raw in raw_logs:
                try:
                    logs.append(json.loads(raw))
                except (json.JSONDecodeError, TypeError):
                    pass
            return logs
        except Exception:
            return []

    # ── 内部: 资源监控 (OMS-06) ──────────────────────────────────────────

    async def _update_bot_stats(self, bot: BotInstance) -> None:
        """OMS-06: 将真实 CPU/MEM 数据写入 Redis Hash"""
        stats_key = _BOT_STATS_KEY.format(bot_id=bot.bot_id)
        try:
            stats = {
                "cpu": str(bot._get_cpu_percent()),
                "mem": str(bot._get_memory_mb()),
                "status": bot.status,
                "updated_at": datetime.now().isoformat(),
            }
            await redis_client.hset(stats_key, mapping=stats)
            await redis_client.expire(stats_key, 15)  # 15s TTL
        except Exception as e:
            logger.debug(f"[BotRuntime] 资源统计写入失败: {e}")

    # ── 内部: 元数据持久化 ────────────────────────────────────────────────

    async def _save_bot_meta(self, bot: BotInstance) -> None:
        """将 Bot 元数据写入 Redis Hash"""
        meta_key = _BOT_META_KEY.format(bot_id=bot.bot_id)
        try:
            meta = {
                "id": bot.bot_id,
                "name": bot.name,
                "ticker": bot.ticker,
                "class_name": bot.class_name,
                "params": json.dumps(bot.params),
                "status": bot.status,
                "started_at": str(bot._started_at),
            }
            await redis_client.hset(meta_key, mapping=meta)
            # 同时更新全局 Bot 注册表
            await redis_client.hset(_BOTS_REGISTRY_KEY, bot.bot_id, json.dumps(meta))
        except Exception as e:
            logger.debug(f"[BotRuntime] Bot 元数据写入失败: {e}")

    async def _broadcast_bots_update(self) -> None:
        """广播 Bot 列表变更到 PubSub"""
        bots = await self.get_all_bots()
        await redis_client.publish("oms:bots:update", json.dumps(bots))

    # ── 启动/恢复已有 Bot (服务重启后) ────────────────────────────────────

    async def restore_bots_from_redis(self) -> int:
        """从 Redis 注册表恢复之前运行的 Bot"""
        try:
            registry = await redis_client.hgetall(_BOTS_REGISTRY_KEY)
            if not registry:
                return 0

            count = 0
            for bot_id, raw_meta in registry.items():
                try:
                    meta = json.loads(raw_meta)
                    if meta.get("status") in ("running", "paused"):
                        strategy_file = os.path.join(
                            _STRATEGIES_DIR, f"{meta['class_name'].lower()}.py"
                        )
                        if os.path.exists(strategy_file):
                            await self.start_bot(
                                bot_id=bot_id,
                                name=meta.get("name", bot_id),
                                ticker=meta.get("ticker", ""),
                                class_name=meta.get("class_name", ""),
                                params=json.loads(meta.get("params", "{}")),
                            )
                            if meta.get("status") == "paused":
                                await self.pause_bot(bot_id)
                            count += 1
                        else:
                            logger.warning(f"[BotRuntime] 策略文件不存在，跳过恢复: {bot_id}")
                except Exception as e:
                    logger.warning(f"[BotRuntime] 恢复 Bot {bot_id} 失败: {e}")

            if count:
                logger.info(f"[BotRuntime] 已从 Redis 恢复 {count} 个 Bot")
            return count
        except Exception as e:
            logger.warning(f"[BotRuntime] 恢复 Bot 注册表失败: {e}")
            return 0

    # ── 全局关停 ──────────────────────────────────────────────────────────

    async def shutdown(self) -> None:
        """优雅关停所有 Bot"""
        await self.stop_all_bots()
        logger.info("[BotRuntime] 所有 Bot 已关停")


# 导出全局单例
bot_runtime = BotRuntimeManager()
