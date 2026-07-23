"""MarginService - 融资融券余额聚合服务

聚合 A 股、港股、美股三个市场的融资融券余额数据。
支持并发请求、缓存、降级处理。
"""

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List

from backend.core.logger import logger
from backend.services.margin.a_share import get_a_share_margin
from backend.services.margin.hk_share import get_hk_share_margin
from backend.services.margin.us_share import get_us_share_margin


class MarginService:
    """融资融券余额聚合服务"""

    async def get_all_margin_data(self) -> Dict[str, Any]:
        """
        获取所有市场的融资融券余额数据

        返回格式:
        {
            "status": "success" | "partial" | "error",
            "data": [
                {
                    "market": "A_SHARE",
                    "market_name": "A 股",
                    "financing_balance": 15234.56,
                    "securities_balance": 234.56,
                    ...
                },
                ...
            ],
            "updated_at": "2026-07-22T10:00:00Z"
        }
        """
        # 并发获取三个市场的数据
        a_share_res, hk_share_res, us_share_res = await asyncio.gather(
            get_a_share_margin(),
            get_hk_share_margin(),
            get_us_share_margin(),
            return_exceptions=True,
        )

        # 组装结果
        markets_data: List[Dict[str, Any]] = []
        success_count = 0
        error_messages: List[str] = []

        # 处理 A 股结果
        if isinstance(a_share_res, dict) and a_share_res.get("status") == "success":
            markets_data.append(a_share_res["data"])
            success_count += 1
        elif isinstance(a_share_res, BaseException):
            error_messages.append(f"A 股: {str(a_share_res)}")
        elif isinstance(a_share_res, dict):
            error_messages.append(f"A 股: {a_share_res.get('message', '未知错误')}")

        # 处理港股结果
        if isinstance(hk_share_res, dict) and hk_share_res.get("status") == "success":
            markets_data.append(hk_share_res["data"])
            success_count += 1
        elif isinstance(hk_share_res, BaseException):
            error_messages.append(f"港股: {str(hk_share_res)}")
        elif isinstance(hk_share_res, dict):
            error_messages.append(f"港股: {hk_share_res.get('message', '未知错误')}")

        # 处理美股结果
        if isinstance(us_share_res, dict) and us_share_res.get("status") == "success":
            markets_data.append(us_share_res["data"])
            success_count += 1
        elif isinstance(us_share_res, BaseException):
            error_messages.append(f"美股: {str(us_share_res)}")
        elif isinstance(us_share_res, dict):
            error_messages.append(f"美股: {us_share_res.get('message', '未知错误')}")

        # 判断整体状态
        if success_count == 3:
            status = "success"
        elif success_count > 0:
            status = "partial"
        else:
            status = "error"

        result = {
            "status": status,
            "data": markets_data,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

        # 如果有错误，添加错误信息
        if error_messages:
            result["errors"] = error_messages
            logger.warning(f"[Margin] 部分市场数据获取失败: {', '.join(error_messages)}")

        return result


# 全局单例
margin_service = MarginService()
