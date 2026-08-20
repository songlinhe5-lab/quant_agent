"""AKShare 宏观日历（百度股市通 / 新浪财经 / 金十数据 三重容灾）。

物理解耦，零 backend 依赖，相对 import。
解析逻辑完整下沉自 backend.services.akshare.calendar，返回结构与主服务一致。
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import akshare as ak
import httpx

from data_subservice._internal.logger import logger
from data_subservice._internal.retry_utils import with_global_retry


def _fetch_date(date_str: str, date_compact: str) -> List[dict]:
    """三级容灾拉取某日宏观事件，返回原始 records。"""
    # 1. AKShare 百度股市通
    try:
        if hasattr(ak, "news_economic_baidu"):
            df = ak.news_economic_baidu(date=date_compact)
            if df is not None and not df.empty:
                return df.to_dict("records")
    except Exception:
        pass

    # 2. 新浪财经裸请求
    try:
        url = f"https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.get_eco_calendar?date={date_str}"
        with httpx.Client(verify=False, timeout=10.0) as client:
            resp = client.get(url)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list) and data:
                    return data
    except Exception:
        pass

    # 3. 金十数据裸请求
    try:
        url = f"https://rili-api.jin10.com/get_list?date={date_str}"
        headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://rili.jin10.com/"}
        with httpx.Client(verify=False, timeout=10.0) as client:
            resp = client.get(url, headers=headers)
            if resp.status_code == 200:
                data = resp.json().get("data", [])
                if isinstance(data, list) and data:
                    return data
    except Exception:
        pass

    return []


@with_global_retry
def get_economic_calendar(days_ahead: int = 7, days_back: int = 0) -> Dict[str, Any]:
    """宏观经济日历（三重容灾），返回与主服务一致的 {status,data,source} 结构。"""
    tz_cn = timezone(timedelta(hours=8))
    today = datetime.now(tz_cn)
    dates_to_fetch: List[tuple] = []
    for i in range(days_back, 0, -1):
        dt = today - timedelta(days=i)
        dates_to_fetch.append((dt.strftime("%Y-%m-%d"), dt.strftime("%Y%m%d")))
    for i in range(days_ahead + 1):
        dt = today + timedelta(days=i)
        dates_to_fetch.append((dt.strftime("%Y-%m-%d"), dt.strftime("%Y%m%d")))

    events: List[Dict[str, Any]] = []
    try:
        for date_idx, (d_str, d_compact) in enumerate(dates_to_fetch):
            res = _fetch_date(d_str, d_compact)
            if not isinstance(res, list):
                continue
            for item in res:
                if not isinstance(item, dict):
                    continue
                country = str(item.get("地区", item.get("country", item.get("国家", ""))))
                event_name = str(
                    item.get("事件", item.get("event", item.get("指标名称", item.get("name", ""))))
                ).strip()
                if not event_name:
                    continue
                star = str(item.get("重要性", item.get("importance", item.get("star", ""))))
                impact = "high" if "高" in star or "3" in star else ("medium" if "中" in star or "2" in star else "low")
                pub_time = str(item.get("公布时间", item.get("时间", item.get("time", item.get("pub_time", "")))))
                if not pub_time or pub_time.lower() == "nan" or ":" not in pub_time:
                    full_time = f"{d_str} 08:30:00"
                else:
                    full_time = f"{d_str} {pub_time}" if len(pub_time) <= 8 else pub_time
                events.append(
                    {
                        "time": full_time,
                        "country": country,
                        "event": event_name,
                        "impact": impact,
                        "previous": str(item.get("前值", item.get("previous_value", item.get("previous", "")))),
                        "estimate": str(
                            item.get(
                                "预期",
                                item.get(
                                    "预测值",
                                    item.get("predicted_value", item.get("forecast", item.get("consensus", ""))),
                                ),
                            )
                        ),
                        "actual": str(
                            item.get("公布", item.get("公布值", item.get("actual_value", item.get("actual", ""))))
                        ),
                    }
                )
        events.sort(key=lambda x: x["time"])
        return {"status": "success", "data": events, "source": "akshare_universal"}
    except Exception as e:
        logger.error(f"[AKShare] 宏观日历失败: {e}")
        return {"status": "error", "message": f"Jin10 宏观日历请求异常: {str(e)}"}


def get_future_calendar() -> List[dict]:
    """获取期货日历。"""
    try:
        df = ak.futures_rule()
        if df is None or df.empty:
            return []
        return df.head(30).to_dict(orient="records")
    except Exception as e:
        logger.error(f"[AKShare] 期货日历失败: {e}")
        return []
