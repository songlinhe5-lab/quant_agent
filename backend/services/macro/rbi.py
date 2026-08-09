import json
import random
from typing import Any, Dict

from backend.core.redis_client import redis_client
from backend.services.datasource.router import data_source_router


class RBIService:
    """印度 CPI 无 Key 兜底源 (专治印度等新兴市场 CPI 盲点)

    💡 RBI/MOSPI 原始 CPI 序列需反爬抓取、稳定性差。此处改用 World Bank 开放 API
    (FP.CPI.TOTL.ZG 印度 CPI 通胀率 YoY, 完全免 Key) 作为可靠的印度 CPI 兜底补充。
    当 TradingEconomics 因缺 Key 被跳过时，本源仍能补上印度 CPI 实际值。

    BE-ARCH-07f: 主服务不再持有 WorldBank REST 直连，统一经 DataSourceRouter
    远程代理至 data_subservice (source=rbi)，本类仅保留解析与 Redis 缓存逻辑。
    """

    async def get_economic_calendar(
        self, days_ahead: int = 7, days_back: int = 0, skip_cache: bool = False
    ) -> Dict[str, Any]:  # noqa: E501
        """获取印度 CPI 通胀率 (YoY) 最新值，作为无 Key 新兴市场兜底事件。"""
        cache_key = "quant:macro:rbi_cpi"
        if not skip_cache:
            try:
                cached = await redis_client.get(cache_key)
                if cached:
                    return {
                        "status": "success",
                        "data": json.loads(cached),
                        "source": "redis_cache",
                    }
            except Exception:
                pass

        try:
            remote = await data_source_router.fetch_rbi(
                "india_cpi_series",
                date_range="2010:2035",
                per_page=100,
            )
            if not isinstance(remote, dict) or remote.get("status") != "success":
                message = "RBI 子服务不可用"
                if isinstance(remote, dict):
                    message = remote.get("message") or remote.get("error") or message
                return {
                    "status": "skipped",
                    "message": f"RBI/WorldBank 印度 CPI 拉取失败: {message}",
                    "data": [],
                }

            payload = remote.get("data")
            rows = payload[1] if isinstance(payload, list) and len(payload) > 1 else []
            series = [(int(x["date"]), float(x["value"])) for x in rows if x.get("value") is not None]
            series.sort(key=lambda t: t[0])
            if not series:
                return {
                    "status": "skipped",
                    "message": "World Bank 暂无印度 CPI 数据",
                    "data": [],
                }

            latest = series[-1]
            prev_val = series[-2][1] if len(series) > 1 else None
            events = [
                {
                    "time": f"{latest[0]}-12-31 00:00:00",
                    "country": "India",
                    "event": "India CPI (YoY)",
                    "impact": "high",
                    "previous": str(prev_val) if prev_val is not None else "",
                    "estimate": "",
                    "actual": str(latest[1]),
                    "tz": "UTC",
                }
            ]

            try:
                ttl = 86400 * 7 + random.randint(100, 600)
                await redis_client.set(cache_key, json.dumps(events), ex=ttl)
            except Exception:
                pass
            return {"status": "success", "data": events, "source": "rbi_worldbank"}
        except Exception as e:
            return {
                "status": "skipped",
                "message": f"RBI/WorldBank 印度 CPI 拉取失败: {e}",
                "data": [],
            }


# 全局单例
rbi_service = RBIService()
