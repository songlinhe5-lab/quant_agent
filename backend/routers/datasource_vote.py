"""
==========================================
Datasource Vote Router - 数据源贡献投票与需求看板 (COMM-02)
==========================================

提供数据源接入优先级投票 API：
  - GET  /datasource-vote/board   需求看板（已接入 / 开发中 / 社区投票中 + 票数 + 今日已投）
  - POST /datasource-vote/vote    投票（防刷票：每用户每源每日限一票）

设计文档: docs/TODO.md COMM-02 · 投票计数经 Redis 持久化，跨 worker 一致。
"""

from datetime import date, datetime, timedelta
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.core import models
from backend.core.redis_client import redis_client
from backend.routers.auth import get_current_user
from backend.services.datasource import datasource_registry

router = APIRouter(prefix="/datasource-vote", tags=["DataSource Vote"])

# ── COMM-02 分类目录 ─────────────────────────────────────────────
# 已接入（connected）= datasource_registry 动态注册源 + 已功能性接入但独立于 registry 的源。
# FRED 虽是独立 macro 服务（未注册进 DataSourceRegistry），但已通过 market 路由智能路由
# 与 agent 工具 get_fred_macro_data 真实对外提供数据，故标记为已接入。
_CONNECTED_SOURCES: List[Dict[str, str]] = [
    {
        "name": "fred",
        "label": "FRED 宏观经济",
        "desc": "圣路易斯联储宏观时间序列（已接入 market 路由 + get_fred_macro_data）",
    },
]
_DEVELOPING_SOURCES: List[Dict[str, str]] = [
    {"name": "dbnomics", "label": "DBnomics", "desc": "全球央行/机构宏观数据集"},
    {"name": "rbi", "label": "RBI / World Bank", "desc": "新兴市场 CPI 等年度序列"},
    {"name": "polygon", "label": "Polygon.io", "desc": "美股实时/历史行情"},
]
_VOTING_SOURCES: List[Dict[str, str]] = [
    {"name": "binance", "label": "Binance", "desc": "加密货币现货/合约行情"},
    {"name": "coinbase", "label": "Coinbase", "desc": "加密货币现货行情"},
    {"name": "cryptocompare", "label": "CryptoCompare", "desc": "加密市场聚合数据"},
    {"name": "tiingo", "label": "Tiingo", "desc": "美股基本面 + 价格"},
    {"name": "alpha_vantage", "label": "Alpha Vantage", "desc": "美股 + 外汇 + 加密货币"},
    {"name": "twelvedata", "label": "Twelve Data", "desc": "多资产实时行情"},
]


def _all_votable() -> set:
    connected = set(datasource_registry.list_names()) | {d["name"] for d in _CONNECTED_SOURCES}
    catalog = {d["name"] for d in _DEVELOPING_SOURCES + _VOTING_SOURCES}
    return connected | catalog


class VoteRequest(BaseModel):
    source: str


@router.get("/board")
async def get_vote_board(current_user: models.User = Depends(get_current_user)) -> Dict[str, Any]:
    """
    COMM-02 需求看板：返回三类数据源及投票数 + 当前用户今日已投列表。
    """
    today = date.today().isoformat()
    connected = datasource_registry.list_names()
    names = list(connected) + [d["name"] for d in _CONNECTED_SOURCES + _DEVELOPING_SOURCES + _VOTING_SOURCES]

    count_map: Dict[str, int] = {}
    try:
        async with redis_client.pipeline() as pipe:
            for n in names:
                pipe.get(f"ds_vote:count:{n}")
            counts = await pipe.execute()
        count_map = {n: int(c or 0) for n, c in zip(names, counts)}
    except Exception:
        count_map = {n: 0 for n in names}

    # registry 动态源 + 已功能性接入但独立于 registry 的源（如 FRED macro 服务）
    connected_entries = [{"name": n, "votes": count_map.get(n, 0)} for n in connected]
    connected_entries += [{**d, "votes": count_map.get(d["name"], 0)} for d in _CONNECTED_SOURCES]

    my_votes = set()
    try:
        for n in names:
            if await redis_client.get(f"ds_vote:ud:{current_user.username}:{today}:{n}"):
                my_votes.add(n)
    except Exception:
        pass

    return {
        "connected": connected_entries,
        "developing": [{**d, "votes": count_map.get(d["name"], 0)} for d in _DEVELOPING_SOURCES],
        "voting": [{**d, "votes": count_map.get(d["name"], 0)} for d in _VOTING_SOURCES],
        "my_votes_today": sorted(my_votes),
    }


@router.post("/vote")
async def cast_vote(req: VoteRequest, current_user: models.User = Depends(get_current_user)) -> Dict[str, Any]:
    """
    COMM-02 投票（防刷票：每用户每源每日限一票）。
    计数经 Redis 自增，用户当日投票以带 TTL(至当日结束) 的 key 去重。
    """
    name = (req.source or "").strip().lower()
    if name not in _all_votable():
        raise HTTPException(status_code=404, detail=f"未知或不可投票的数据源: {name}")

    today = date.today().isoformat()
    ud_key = f"ds_vote:ud:{current_user.username}:{today}:{name}"
    try:
        if await redis_client.get(ud_key):
            raise HTTPException(status_code=409, detail="今天已为该数据源投过票（每日每源限一票）")
        await redis_client.incr(f"ds_vote:count:{name}")
        # TTL 到当日 24:00（本地时区）
        ttl = int(
            (datetime.combine(date.today() + timedelta(days=1), datetime.min.time()) - datetime.now()).total_seconds()
        )
        await redis_client.set(ud_key, "1", ex=max(ttl, 1))
        votes = int(await redis_client.get(f"ds_vote:count:{name}") or 0)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"投票写入失败: {e}")

    return {"ok": True, "source": name, "votes": votes}
