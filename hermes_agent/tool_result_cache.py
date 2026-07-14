"""
BE-12 · Hermes Agent Tool 调用结果统一缓存

Redis Hash 键：tool:cache:{tool_name}:{args_hash}
字段：result / cached_at / status
TTL：环境变量可配置（全局默认 + 按工具覆盖）
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from typing import Any, Dict, Optional, Set

logger = logging.getLogger(__name__)

# 默认不缓存的工具（写操作 / 副作用 / 会话态）
_DEFAULT_NO_CACHE: Set[str] = {
    "delete_global_knowledge",
}

# 按工具默认 TTL（秒）——对齐下游数据新鲜度
_DEFAULT_TOOL_TTLS: Dict[str, int] = {
    "get_broker_market_data": 60,
    "calculate_technical_indicators": 120,
    "get_fundamental_data": 600,
    "get_macro_news": 900,
    "get_company_news": 900,
    "get_macro_sentiment_history": 1800,
    "get_fred_macro_data": 3600,
    "get_macro_calendar": 1800,
    "screen_stocks": 300,
    "web_search": 3600,
    "fetch_webpage": 3600,
    "search_global_knowledge": 600,
    "analyze_financial_report": 1800,
}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return max(0, int(raw))
    except ValueError:
        return default


def tool_cache_enabled() -> bool:
    return os.getenv("TOOL_CACHE_ENABLED", "true").lower() in ("1", "true", "yes")


def default_ttl_seconds() -> int:
    return _env_int("TOOL_CACHE_DEFAULT_TTL", 300)


def ttl_for_tool(tool_name: str) -> int:
    """解析 TTL：TOOL_CACHE_TTL_{NAME} > 内置表 > TOOL_CACHE_DEFAULT_TTL。"""
    env_key = f"TOOL_CACHE_TTL_{tool_name.upper()}"
    if os.getenv(env_key) is not None:
        return _env_int(env_key, default_ttl_seconds())
    return _DEFAULT_TOOL_TTLS.get(tool_name, default_ttl_seconds())


def no_cache_tools() -> Set[str]:
    extra = os.getenv("TOOL_CACHE_NO_CACHE", "")
    names = set(_DEFAULT_NO_CACHE)
    for part in extra.split(","):
        part = part.strip()
        if part:
            names.add(part)
    return names


def stable_args_hash(tool_name: str, kwargs: Dict[str, Any]) -> str:
    payload = {"tool": tool_name, "args": kwargs or {}}
    raw = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def cache_key(tool_name: str, kwargs: Dict[str, Any]) -> str:
    return f"tool:cache:{tool_name}:{stable_args_hash(tool_name, kwargs)}"


def should_cache_result(result: Any) -> bool:
    """错误 / 限流 / 空结果不落缓存。"""
    if result is None:
        return False
    if isinstance(result, dict):
        status = str(result.get("status", "")).lower()
        if status in ("error", "rate_limited", "failed"):
            return False
        if result.get("error") and not result.get("data"):
            return False
    return True


class ToolResultCache:
    """Redis Hash 统一 Tool 结果缓存。"""

    def __init__(self, redis_client: Any = None) -> None:
        self._redis = redis_client
        self._hits = 0
        self._misses = 0

    def _client(self) -> Any:
        if self._redis is not None:
            return self._redis
        from backend.core.redis_client import redis_client

        return redis_client

    async def get(self, tool_name: str, kwargs: Dict[str, Any]) -> Optional[Any]:
        if not tool_cache_enabled() or tool_name in no_cache_tools():
            return None
        key = cache_key(tool_name, kwargs)
        try:
            client = self._client()
            data = await client.hgetall(key)
            if not data:
                self._misses += 1
                return None
            # decode_responses=True → str keys; 兼容 bytes
            def _v(k: str) -> Optional[str]:
                if k in data:
                    val = data[k]
                    return val.decode() if isinstance(val, bytes) else val
                bk = k.encode()
                if bk in data:
                    val = data[bk]
                    return val.decode() if isinstance(val, bytes) else val
                return None

            raw = _v("result")
            if not raw:
                self._misses += 1
                return None
            self._hits += 1
            result = json.loads(raw)
            if isinstance(result, dict):
                result = {**result, "_cache_hit": True, "_cache_key": key}
            logger.debug("tool_cache_hit name=%s key=%s", tool_name, key)
            return result
        except Exception as e:
            logger.warning("tool_cache_get_failed name=%s err=%s", tool_name, e)
            return None

    async def set(self, tool_name: str, kwargs: Dict[str, Any], result: Any) -> bool:
        if not tool_cache_enabled() or tool_name in no_cache_tools():
            return False
        if not should_cache_result(result):
            return False
        ttl = ttl_for_tool(tool_name)
        if ttl <= 0:
            return False
        key = cache_key(tool_name, kwargs)
        try:
            # 去掉瞬时标记再存
            payload = result
            if isinstance(result, dict):
                payload = {
                    k: v for k, v in result.items() if not str(k).startswith("_cache")
                }
            client = self._client()
            mapping = {
                "result": json.dumps(payload, ensure_ascii=False, default=str),
                "cached_at": str(int(time.time())),
                "status": str(
                    payload.get("status", "success") if isinstance(payload, dict) else "ok"
                ),
                "tool": tool_name,
            }
            pipe = client.pipeline()
            pipe.hset(key, mapping=mapping)
            pipe.expire(key, ttl)
            await pipe.execute()
            logger.debug("tool_cache_set name=%s ttl=%s key=%s", tool_name, ttl, key)
            return True
        except Exception as e:
            logger.warning("tool_cache_set_failed name=%s err=%s", tool_name, e)
            return False

    def stats(self) -> Dict[str, int]:
        return {"hits": self._hits, "misses": self._misses}


# 进程级默认实例（Registry 可注入 mock）
default_tool_result_cache = ToolResultCache()
