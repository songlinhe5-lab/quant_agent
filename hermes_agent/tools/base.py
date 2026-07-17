import asyncio
import json
import os
import time
from typing import Any, Dict, Tuple

from backend.core.redis_client import redis_client


def get_backend_api_url() -> str:
    """
    统一构建后端 API 基础 URL。
    读取 BACKEND_API_URL + API_URL_VERSION 环境变量，拼接为完整路径。
    升级 API 版本时只需修改 API_URL_VERSION 环境变量即可。
    """
    base = os.getenv("BACKEND_API_URL", "http://127.0.0.1:8000").rstrip("/")
    version = os.getenv("API_URL_VERSION", "v1")
    return f"{base}/api/{version}"


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

        match = re.search(r"\d+", ticker)

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

    # ─────────────────────────────────────────
    # RL-14: 限流感知智能重试
    # ─────────────────────────────────────────
    _RATE_LIMIT_STATUS_CODES = {429, 503}
    _RATE_LIMIT_BODY_KEYS = {"rate_limited", "rate_limit", "throttled"}
    _MAX_RETRIES = 3
    _DEFAULT_RETRY_DELAY = 5.0
    _MAX_RETRY_DELAY = 60.0

    async def rate_limit_aware_request(
        self,
        client,
        method: str,
        url: str,
        *,
        max_retries: int = _MAX_RETRIES,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        RL-14: 限流感知智能重试请求。

        检测后端返回的限流信号 (HTTP 429/503 或响应体中含 rate_limited 状态)，
        解析 retry_after_seconds 后智能等待再重试，而非立即报错或死循环。

        Args:
            client: SecureAsyncClient 实例
            method: HTTP 方法 ("GET" / "POST")
            url: 请求 URL
            max_retries: 最大重试次数 (默认 3)
            **kwargs: 传递给 client.request 的额外参数

        Returns:
            成功时返回响应 JSON；重试耗尽时返回结构化限流错误。
        """
        last_error = None
        for attempt in range(max_retries + 1):
            try:
                resp = await client.request(method, url, **kwargs)

                # 成功响应
                if resp.status_code == 200:
                    return resp.json()

                # 检测限流信号
                if self._is_rate_limit_response(resp):
                    retry_after = self._extract_retry_after(resp)
                    last_error = resp

                    if attempt < max_retries:
                        capped_delay = min(retry_after, self._MAX_RETRY_DELAY)
                        print(
                            f"⏳ [RL-14] 触发限流退避: {method} {url} "
                            f"| HTTP {resp.status_code} | "
                            f"retry_after={capped_delay:.1f}s | "
                            f"attempt={attempt + 1}/{max_retries + 1}"
                        )
                        await asyncio.sleep(capped_delay)
                        continue
                    else:
                        # 重试耗尽，返回结构化限流错误
                        return {
                            "status": "rate_limited",
                            "message": (
                                f"数据源限流，已重试 {max_retries} 次仍未恢复。建议稍后 ({retry_after:.0f}s) 再试。"
                            ),
                            "retry_after_seconds": retry_after,
                            "attempts": max_retries + 1,
                        }

                # 非限流类 HTTP 错误，直接返回
                err_msg = resp.text
                try:
                    err_msg = resp.json().get("detail", resp.text)
                except Exception:
                    pass
                return {
                    "status": "error",
                    "message": f"后端网关报错 (HTTP {resp.status_code}): {err_msg}",
                }

            except Exception as e:
                last_error = e
                if attempt < max_retries:
                    delay = self._DEFAULT_RETRY_DELAY * (2**attempt)
                    capped_delay = min(delay, self._MAX_RETRY_DELAY)
                    print(
                        f"⏳ [RL-14] 请求异常退避: {method} {url} "
                        f"| error={str(e)[:80]} | "
                        f"delay={capped_delay:.1f}s | "
                        f"attempt={attempt + 1}/{max_retries + 1}"
                    )
                    await asyncio.sleep(capped_delay)
                    continue
                return {
                    "status": "error",
                    "message": f"请求后端接口失败 (重试 {max_retries} 次): {str(last_error)}",
                }

        # 兜底 (理论上不会到这里)
        return {"status": "error", "message": "请求异常: 重试逻辑耗尽"}

    def _is_rate_limit_response(self, resp) -> bool:
        """检测响应是否为限流信号"""
        # 1. HTTP 状态码检测
        if resp.status_code in self._RATE_LIMIT_STATUS_CODES:
            return True
        # 2. 响应体关键词检测 (后端可能返回 200 但 status="rate_limited")
        try:
            body = resp.json()
            status_val = str(body.get("status", "")).lower()
            if any(key in status_val for key in self._RATE_LIMIT_BODY_KEYS):
                return True
        except Exception:
            pass
        return False

    def _extract_retry_after(self, resp) -> float:
        """从响应中提取重试等待秒数"""
        # 1. 优先从 Retry-After 响应头提取
        retry_header = resp.headers.get("Retry-After")
        if retry_header:
            try:
                return float(retry_header)
            except (ValueError, TypeError):
                pass

        # 2. 从 X-RateLimit-Reset 响应头推算
        reset_header = resp.headers.get("X-RateLimit-Reset")
        if reset_header:
            try:
                reset_ts = float(reset_header)
                remaining = reset_ts - time.time()
                if remaining > 0:
                    return remaining
            except (ValueError, TypeError):
                pass

        # 3. 从响应体 JSON 提取
        try:
            body = resp.json()
            for key in ("retry_after_seconds", "retry_after", "retry_in"):
                val = body.get(key)
                if val is not None:
                    return float(val)
        except Exception:
            pass

        # 4. 默认退避延迟
        return self._DEFAULT_RETRY_DELAY

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
                del self._shared_cache[key]  # L1 过期清理

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
