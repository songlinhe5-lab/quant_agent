import os
import time
import json
from typing import Dict, Any, Tuple

from backend.core.redis_client import redis_client

class BaseTool:
    """
    所有 Tool 的基类，提供统一的全局共享缓存能力。
    支持 L1 (进程内存字典) 与 L2 (全局 Redis 持久化) 双级缓存。
    """
    _shared_cache: Dict[str, Tuple[float, Any]] = {}
    _max_cache_size: int = 256

    @staticmethod
    def normalize_ticker(ticker: str) -> str:
        """将大模型输出的自然语言股票代码转换为后端严格要求的 Region.Code 格式 (如 0772.HK -> HK.0772)"""
        if not ticker:
            return ""
        ticker = ticker.upper().strip()
        
        # 特殊处理加密货币与外汇 (防误伤)
        if ":" in ticker or "=" in ticker or "-" in ticker:
            if ticker.startswith("US."):
                return ticker
            return f"US.{ticker}"

        import re
        match = re.search(r'\d+', ticker)
        
        if "HK" in ticker:
            code = match.group() if match else ticker.replace(".HK", "").replace("HK.", "")
            return f"HK.{code.zfill(5)}" if code.isdigit() else f"HK.{code}"
        elif "SH" in ticker:
            code = match.group() if match else ticker.replace(".SH", "").replace("SH.", "")
            return f"SH.{code.zfill(6)}" if code.isdigit() else f"SH.{code}"
        elif "SZ" in ticker:
            code = match.group() if match else ticker.replace(".SZ", "").replace("SZ.", "")
            return f"SZ.{code.zfill(6)}" if code.isdigit() else f"SZ.{code}"
        elif "US" in ticker:
            code = ticker.replace(".US", "").replace("US.", "")
            return f"US.{code}"
            
        if match and match.group() == ticker:
            # 纯数字推断：A 股 6 位，港股 5 位
            if len(ticker) == 6:
                return f"SH.{ticker}" if ticker.startswith("60") or ticker.startswith("68") else f"SZ.{ticker}"
            return f"HK.{ticker.zfill(5)}"
            
        return f"US.{ticker}"

    async def get_cached_data(self, key: str, ttl: int) -> Any:
        """
        异步获取缓存数据（双级缓存机制）
        """
        current_time = time.time()
        
        # 1. 尝试从 L1 内存中极速获取
        if key in self._shared_cache:
            cache_time, data = self._shared_cache[key]
            if current_time - cache_time < ttl:
                return data
            else:
                del self._shared_cache[key] # L1 过期清理

        # 2. 尝试从 L2 Redis 全局缓存获取跨进程留存的数据
        try:
            cached_str = await redis_client.get(key)
            if cached_str:
                data = json.loads(cached_str)
                # 提取成功后回写到 L1 内存，提升下次读取速度
                self._shared_cache[key] = (current_time, data)
                return data
        except Exception as e:
            print(f"⚠️ [Cache] Redis L2 缓存读取失败: {e}")
            
        return None

    async def set_cached_data(self, key: str, data: Any, persist: bool = False, ttl: int = 604800) -> None:
        """异步写入缓存数据 (ttl 默认 7 天)"""
        current_time = time.time()
        # 1. 写入 L1 内存
        self._shared_cache[key] = (current_time, data)
        if len(self._shared_cache) > self._max_cache_size:
            oldest_key = min(self._shared_cache.keys(), key=lambda k: self._shared_cache[k][0])
            del self._shared_cache[oldest_key]
            
        # 2. 按需写入 L2 Redis 进行持久化
        if persist:
            try:
                await redis_client.setex(key, ttl, json.dumps(data, ensure_ascii=False))
            except Exception as e:
                print(f"⚠️ [Cache] Redis L2 缓存持久化失败: {e}")