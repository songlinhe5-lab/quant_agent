import json
from typing import Any, Dict, List

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel

from backend.core import models

# 引入全局 Redis 客户端 (依赖于目前的架构规范)
from backend.core.redis_client import l1_cached_redis, redis_client
from backend.routers.auth import get_current_user

router = APIRouter(prefix="/settings", tags=["Preferences"])


@router.get("/preferences")
async def get_preferences(current_user: models.User = Depends(get_current_user)):
    """获取当前登录用户的全局偏好设置（含绑定的各类 API Keys）"""
    pref_redis_key = f"quant:user:{current_user.username}:preferences"
    try:
        raw_data = await redis_client.get(pref_redis_key)

        # 默认配置底座 (Fallback Defaults)
        default_prefs = {
            "theme": "dark",
            "defaultLeverage": 1.0,
            "yfinanceFallbackEnabled": True,
            "language": "zh-CN",
        }

        if raw_data:
            saved_prefs = json.loads(raw_data)
            default_prefs.update(saved_prefs)

        return {"status": "success", "data": default_prefs}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"无法获取用户偏好: {str(e)}")


@router.post("/preferences")
async def update_preferences(
    prefs: Dict[str, Any] = Body(...),
    current_user: models.User = Depends(get_current_user),
):  # noqa: E501
    """更新当前登录用户的偏好设置与 API Keys"""
    pref_redis_key = f"quant:user:{current_user.username}:preferences"
    try:
        # 1. 获取现有配置
        raw_data = await redis_client.get(pref_redis_key)
        current_prefs = json.loads(raw_data) if raw_data else {}

        # 2. 局部合并更新
        current_prefs.update(prefs)
        await redis_client.set(pref_redis_key, json.dumps(current_prefs))

        # 3. 🎯 核心联动：如果前端修改了 yfinance 的降级开关，需要同步写入系统全局限流 Key  # noqa: E501
        if "yfinanceFallbackEnabled" in prefs:
            val = "1" if prefs["yfinanceFallbackEnabled"] else "0"
            await l1_cached_redis.set("quant:settings:yfinance_enabled", val)

        return {"status": "success", "message": "偏好设置已更新", "data": current_prefs}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"保存用户偏好失败: {str(e)}")


@router.get("/news-tags")
async def get_news_tags_rules(current_user: models.User = Depends(get_current_user)):
    """获取动态新闻打标规则"""
    cache_key = "quant:settings:news_tags_rules"
    try:
        raw_data = await redis_client.get(cache_key)
        if raw_data:
            return {"status": "success", "data": json.loads(raw_data)}

        default_rules = {
            "FED": r"\b(fed|fomc|powell|yellen|rate(s)?|cut|hike)\b",
            "ECB": r"\b(ecb|lagarde)\b",
            "BOJ": r"\b(boj|ueda|kuroda)\b",
            "INFLATION": r"\b(cpi|pce|inflation|deflation)\b",
            "ECONOMY": r"\b(gdp|payroll|nfp|employment|jobless)\b",
            "CRYPTO": r"\b(crypto|bitcoin|btc|ethereum|eth|sec)\b",
            "COMMODITY": r"\b(oil|wti|brent|opec|energy|gold|xau|silver)\b",
            "GEOPOLITICS": r"\b(war|geopolitical|military|israel|russia|ukraine|sanction|tariff)\b",  # noqa: E501
        }
        return {"status": "success", "data": default_rules}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取新闻打标规则失败: {str(e)}")


@router.post("/news-tags")
async def update_news_tags_rules(
    rules: Dict[str, str] = Body(...),
    current_user: models.User = Depends(get_current_user),
):  # noqa: E501
    """更新动态新闻打标规则"""
    cache_key = "quant:settings:news_tags_rules"
    import re

    try:
        # 风控校验：确保传入的每一个正则表达式都是合法可编译的，防止 Finnhub 后台守护进程因此崩溃  # noqa: E501
        for tag, pattern in rules.items():
            try:
                re.compile(pattern)
            except Exception:
                raise HTTPException(
                    status_code=400,
                    detail=f"标签 '{tag}' 的正则表达式不合法: {pattern}",
                )  # noqa: E501

        await l1_cached_redis.set(cache_key, json.dumps(rules))
        return {"status": "success", "message": "新闻打标规则已更新", "data": rules}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"保存新闻打标规则失败: {str(e)}")


# ==========================================
# --- 核心监控池 (Watchlist) 接口 ---
# ==========================================


class WatchlistBatchRequest(BaseModel):
    tickers: List[str]
    action: str = "add"  # "add" 或 "remove"


@router.get("/watchlist")
async def get_watchlist(current_user: models.User = Depends(get_current_user)):
    """获取当前用户的长期监控池股票列表"""
    user_set_key = f"quant:user:{current_user.username}:monitored_stocks"
    try:
        members = await redis_client.smembers(user_set_key)
        stocks = [m.decode("utf-8") if isinstance(m, bytes) else str(m) for m in members]  # noqa: E501
        return {"status": "success", "data": stocks}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取监控池失败: {str(e)}")


@router.post("/watchlist/batch")
async def batch_update_watchlist(req: WatchlistBatchRequest, current_user: models.User = Depends(get_current_user)):  # noqa: E501
    """一键批量将股票加入或移出系统级监控池，联动后台守护进程"""
    user_set_key = f"quant:user:{current_user.username}:monitored_stocks"
    global_ref_key = "quant:settings:monitored_refcounts"
    from backend.services.futu.utils import format_ticker

    try:
        success_count = 0
        for t in req.tickers:
            fmt_ticker = format_ticker(t)
            if req.action == "add":
                is_new = await redis_client.sadd(user_set_key, fmt_ticker)
                if is_new:
                    # 全局引用计数+1，通知底层 WebSocket 及新闻轮询进程开始工作
                    await redis_client.hincrby(global_ref_key, fmt_ticker, 1)
                    success_count += 1
            elif req.action == "remove":
                is_removed = await redis_client.srem(user_set_key, fmt_ticker)
                if is_removed:
                    # 全局引用计数-1，若归零则底层彻底释放该标的的网络与内存资源
                    new_count = await redis_client.hincrby(global_ref_key, fmt_ticker, -1)  # noqa: E501
                    if new_count <= 0:
                        await redis_client.hdel(global_ref_key, fmt_ticker)
                    success_count += 1

        action_str = "加入" if req.action == "add" else "移出"
        return {
            "status": "success",
            "message": f"成功将 {success_count} 只标的{action_str}核心监控池！",
        }  # noqa: E501
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"批量操作监控池失败: {str(e)}")
