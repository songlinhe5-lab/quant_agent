"""宏观经济日历 Mixin"""

import asyncio
import json
import random
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from backend.core.redis_client import redis_client
from backend.core.retry_utils import with_global_retry


class CalendarMixin:
    """宏观经济日历 (百度股市通 / 新浪财经 / 金十数据 三重容灾)"""

    @with_global_retry
    async def get_economic_calendar(
        self, days_ahead: int = 7, days_back: int = 0, skip_cache: bool = False
    ) -> Dict[str, Any]:  # noqa: E501
        """
        通过 百度股市通 / 新浪财经 / 金十数据 (Jin10) 三重接口聚合获取宏观经济日历。
        构建三级容灾架构，彻底解决单一接口被封控导致的无数据问题。
        💡 支持 days_back 参数获取过去已公布的数据
        """
        cache_key = f"akshare_jin10_calendar_{days_ahead}_{days_back}"
        if not skip_cache:
            cached = await redis_client.get(cache_key)
            if cached:
                return json.loads(cached)

            if self._cache_mode:
                return {
                    "status": "no_data",
                    "message": "cache 模式: 宏观日历缓存未命中，等待北京 VPS 采集器写入",
                    "data": [],
                }

        # 国内数据源使用北京时间 (东八区)
        tz_cn = timezone(timedelta(hours=8))
        today = datetime.now(tz_cn)

        dates_to_fetch = []
        # 💡 先添加过去的日期 (从 days_back 天前到今天前一天)
        for i in range(days_back, 0, -1):
            dt = today - timedelta(days=i)
            dates_to_fetch.append((dt.strftime("%Y-%m-%d"), dt.strftime("%Y%m%d")))
        # 再添加今天和未来日期
        for i in range(days_ahead + 1):
            dt = today + timedelta(days=i)
            dates_to_fetch.append((dt.strftime("%Y-%m-%d"), dt.strftime("%Y%m%d")))

        async def _fetch_date(date_str: str, date_compact: str):
            # 1. 尝试 AKShare 百度股市通 (正规，带中文)
            try:
                import akshare as ak

                if hasattr(ak, "news_economic_baidu"):
                    df = await asyncio.to_thread(ak.news_economic_baidu, date=date_compact)  # noqa: E501
                    if df is not None and not df.empty:
                        return df.to_dict("records")
            except Exception:
                pass

            # 2. 尝试裸请求 Sina 新浪财经 (老牌接口，极度稳定无反爬)
            try:
                import httpx

                url = f"https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.get_eco_calendar?date={date_str}"
                async with httpx.AsyncClient(verify=False, timeout=10.0) as client:
                    resp = await client.get(url)
                    if resp.status_code == 200:
                        data = resp.json()
                        if isinstance(data, list) and data:
                            return data
            except Exception:
                pass

            # 3. 尝试裸请求 Jin10 (加满伪装)
            try:
                import httpx

                url = f"https://rili-api.jin10.com/get_list?date={date_str}"
                headers = {
                    "User-Agent": "Mozilla/5.0",
                    "Referer": "https://rili.jin10.com/",
                }
                async with httpx.AsyncClient(verify=False, timeout=10.0) as client:
                    resp = await client.get(url, headers=headers)
                    if resp.status_code == 200:
                        data = resp.json().get("data", [])
                        if isinstance(data, list) and data:
                            return data
            except Exception:
                pass

            return []

        events = []
        try:
            results = await asyncio.gather(
                *[_fetch_date(d_str, d_compact) for d_str, d_compact in dates_to_fetch],
                return_exceptions=True,
            )  # noqa: E501
            for date_idx, res in enumerate(results):
                if isinstance(res, BaseException) or not isinstance(res, list):
                    continue

                target_date_str = dates_to_fetch[date_idx][0]

                for item in res:
                    if not isinstance(item, dict):
                        continue  # noqa: E701

                    # 万能提取器：兼容百度、新浪、金十三种不同的字段规范
                    country = str(item.get("地区", item.get("country", item.get("国家", ""))))  # noqa: E501
                    event_name = str(
                        item.get(
                            "事件",
                            item.get("event", item.get("指标名称", item.get("name", ""))),
                        )
                    ).strip()  # noqa: E501
                    if not event_name:
                        continue  # noqa: E701

                    # 星级/重要性
                    star = str(item.get("重要性", item.get("importance", item.get("star", ""))))  # noqa: E501
                    impact = (
                        "high" if "高" in star or "3" in star else ("medium" if "中" in star or "2" in star else "low")
                    )  # noqa: E501

                    # 时间处理 (如果未提供具体时间，默认 08:30)
                    pub_time = str(
                        item.get(
                            "公布时间",
                            item.get("时间", item.get("time", item.get("pub_time", ""))),
                        )
                    )  # noqa: E501
                    if not pub_time or pub_time.lower() == "nan" or ":" not in pub_time:
                        full_time = f"{target_date_str} 08:30:00"
                    else:
                        full_time = f"{target_date_str} {pub_time}" if len(pub_time) <= 8 else pub_time  # noqa: E501

                    events.append(
                        {
                            "time": full_time,
                            "country": country,
                            "event": event_name,
                            "impact": impact,
                            "previous": str(
                                item.get(
                                    "前值",
                                    item.get("previous_value", item.get("previous", "")),
                                )
                            ),  # noqa: E501
                            "estimate": str(
                                item.get(
                                    "预测值",
                                    item.get("predicted_value", item.get("consensus", "")),
                                )
                            ),  # noqa: E501
                            "actual": str(
                                item.get(
                                    "公布值",
                                    item.get("actual_value", item.get("actual", "")),
                                )
                            ),  # noqa: E501
                        }
                    )

            # 按时间正序排列
            events.sort(key=lambda x: x["time"])

            result = {
                "status": "success",
                "data": events,
                "source": "akshare_universal",
            }  # noqa: E501
            # 缓存半天 + 随机抖动防雪崩
            ttl = 43200 + random.randint(100, 600)
            await redis_client.set(cache_key, json.dumps(result), ex=ttl)
            return result
        except Exception as e:
            return {"status": "error", "message": f"Jin10 宏观日历请求异常: {str(e)}"}
