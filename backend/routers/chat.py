"""
Chat & Session 管理路由
从 main.py 迁出的 AI 对话 + 历史会话 CRUD 端点 (ARCH-01)
"""

import asyncio
import json
import os
from typing import Any, Optional

from fastapi import APIRouter, Cookie, Depends, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from pydantic import BaseModel

from backend.core import models
from backend.core.database import SessionLocal
from backend.core.redis_client import redis_client

router = APIRouter(tags=["Chat"])

# ==========================================
# --- JWT 轻量鉴权 (仅提取 username，不查库) ---
# ==========================================
SECRET_KEY = os.getenv("SECRET_KEY", "your-super-secret-key-keep-it-safe")
ALGORITHM = "HS256"
_bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_username(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
    refresh_token: Optional[str] = Cookie(None),
) -> str:
    """从 Header (Bearer) 或 Cookie (SSR) 中提取并验证 JWT Token，返回 username"""
    token = credentials.credentials if credentials else refresh_token
    if token == "null":
        token = refresh_token
    if not token:
        raise HTTPException(status_code=401, detail="请求未携带合法 Token，拒绝访问")
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: Optional[str] = payload.get("sub")
        if not username:
            raise HTTPException(status_code=401, detail="Token 载荷非法 (缺失 sub)")
        return username
    except JWTError:
        raise HTTPException(status_code=401, detail="Token 无效或已过期")


# ==========================================
# --- 聊天灵感建议 (静态 + 动态组合) ---
# ==========================================
STATIC_SUGGESTIONS = [
    {"title": "今日宏观风向", "prompt": "提取今天全球核心经济体的宏观大事件，并给出你的风险判断。"},
    {"title": "回测绩效归因", "prompt": "我的策略夏普比率 1.5，但最大回撤 25%，请分析可能的原因及改进建议。"},
    {
        "title": "量化代码 Debug",
        "prompt": "我有一个报错：RuntimeWarning: divide by zero encountered in scalar divide，在 Numpy 计算夏普比率时，如何安全处理？",
    },
    {"title": "交易心理建设", "prompt": "连续亏损导致心态失衡，作为量化交易员，该如何科学地执行熔断并调整心态？"},
    {"title": "期权策略套利", "prompt": "当前 VIX 较低，推荐一个适合中性震荡行情的期权卖方策略（如 Iron Condor）。"},
    {
        "title": "个股深度研判",
        "prompt": "请对我关注的标的进行深度研判，综合基本面(PE/PB/ROE)、技术面(MACD/RSI/MA)和估值分析，给出明确的多空概率和建仓建议。",
    },
]

DYN_ASSETS = [
    "AAPL(苹果)",
    "TSLA(特斯拉)",
    "NVDA(英伟达)",
    "MSFT(微软)",
    "0700.HK(腾讯)",
    "09988.HK(阿里)",
    "BTC(比特币)",
    "ETH(以太坊)",
    "SPY(标普500)",
    "QQQ(纳指ETF)",
    "GLD(黄金ETF)",
    "USO(原油ETF)",
    "TLT(长牛美债)",
]
DYN_INDICATORS = [
    "双均线(MA)",
    "指数移动平均(EMA)",
    "MACD",
    "RSI",
    "布林带(BOLL)",
    "真实波幅(ATR)",
    "KDJ",
    "VWAP",
    "动量因子(Momentum)",
    "夏普比率(Sharpe)",
]
DYN_THEMES = [
    "基本面",
    "技术面",
    "资金面",
    "情绪面",
    "宏观政策",
    "期权隐含波动率(IV)",
    "量化统计套利",
    "跨市场对冲",
]
DYN_ACTIONS = [
    "写一个实盘策略框架",
    "分析最新的走势",
    "诊断可能存在的黑天鹅风险",
    "给出投资组合建议",
    "编写量化特征提取代码",
    "分析支撑位和压力位",
    "评估目前的估值水平",
    "深度研判",
    "对标同业 top 3",
    "检测财务异常信号",
    "评估12月目标价空间",
    "分析建仓时机",
]


@router.get("/chat/suggestions")
async def get_chat_suggestions(limit: int = 10):
    import random

    selected = []
    while len(selected) < limit:
        if random.random() < 0.2:
            item = random.choice(STATIC_SUGGESTIONS)
            if item not in selected:
                selected.append(item)
        else:
            asset = random.choice(DYN_ASSETS)
            indicator = random.choice(DYN_INDICATORS)
            theme = random.choice(DYN_THEMES)
            action = random.choice(DYN_ACTIONS)

            template_idx = random.randint(1, 7)
            if template_idx == 1:
                title = f"{asset} {theme}分析"
                prompt = f"请结合当前的{theme}，帮我{action}：{asset}。"
            elif template_idx == 2:
                title = f"{indicator} {asset}策略"
                prompt = f"我想要针对 {asset} 交易，请结合 {indicator} 指标，帮我{action}。"
            elif template_idx == 3:
                title = f"深挖 {asset} {theme}"
                prompt = f"目前 {asset} 的{theme}表现如何？结合 {indicator} 数据，{action}。"
            elif template_idx == 4:
                title = f"量化因子: {indicator}"
                prompt = f"我想利用 Pandas 计算 {asset} 的 {indicator} 因子，请{action}。"
            elif template_idx == 5:
                title = f"{asset} 风险预警"
                prompt = f"假设我重仓了 {asset}，请从{theme}的角度，结合 {indicator}，帮我{action}。"
            elif template_idx == 6:
                title = f"{asset} 深度研判"
                prompt = f"请对 {asset} 进行深度研判，综合基本面、技术面和估值分析，给出明确的投资建议和止损位。"
            else:
                title = f"{asset} 对标分析"
                prompt = f"请将 {asset} 与行业内 top 3 竞品进行对标分析，从估值、成长性和风险三个维度对比。"

            item = {"title": title, "prompt": prompt}
            if not any(x["title"] == item["title"] for x in selected):
                selected.append(item)

    return {"status": "success", "data": selected}


# ==========================================
# --- AI Chat 流式端点 ---
# ==========================================
class ChatMessage(BaseModel):
    role: str
    content: Optional[Any] = None
    name: Optional[str] = None
    tool_calls: Optional[Any] = None
    tool_call_id: Optional[str] = None


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    session_id: Optional[str] = "default_api_session"


@router.post("/chat")
async def chat_endpoint(request: ChatRequest, username: str = Depends(get_current_username)):
    """接收前端对话并调用 Hermes Agent (流式 NDJSON)"""
    from backend.bootstrap.lifecycle import global_llm_client, global_registry

    if not global_registry:
        raise HTTPException(status_code=503, detail="Tool Registry 未初始化")

    from hermes_agent.agent import HermesAgent

    safe_session_id = f"user_{username}_{request.session_id or 'default_api_session'}"

    current_agent = HermesAgent(
        tool_registry=global_registry,
        system_prompt_path=os.path.abspath("AGENTS.md"),
        session_id=safe_session_id,
        llm_client=global_llm_client,
        redis_client=redis_client,
    )
    await current_agent.initialize()

    user_message = ""
    if request.messages and request.messages[-1].role == "user":
        last_content = request.messages[-1].content
        if last_content is not None and str(last_content).strip():
            user_message = str(last_content).strip()
            if len(user_message) > 20000:
                user_message = user_message[:20000] + "\n\n...[⚠️ 用户输入过长，已被系统安全机制自动截断保护]"

    async def generate_response():
        try:
            async for chunk in current_agent.chat_stream_async(user_message, attachments=None):
                yield json.dumps(chunk, ensure_ascii=False) + "\n"
        except Exception as e:
            import traceback

            traceback.print_exc()
            error_event = {"type": "error", "content": f"\n\n> ⚠️ **Agent 引擎调用失败**: {str(e)}\n"}
            yield json.dumps(error_event, ensure_ascii=False) + "\n"

    return StreamingResponse(generate_response(), media_type="application/x-ndjson")


# ==========================================
# --- 历史会话管理 CRUD ---
# ==========================================
@router.get("/sessions")
async def get_sessions(
    user_id: Optional[int] = None,
    q: Optional[str] = None,
    username: str = Depends(get_current_username),
):
    """获取历史会话列表 (支持关键字搜索)"""

    def fetch_sessions():
        from sqlalchemy import String, cast

        with SessionLocal() as db:
            query = db.query(models.AgentSession)
            prefix = f"user_{username}_"
            query = query.filter(models.AgentSession.session_id.startswith(prefix))

            if q:
                query = query.filter(
                    (models.AgentSession.title.ilike(f"%{q}%"))
                    | (cast(models.AgentSession.messages, String).ilike(f"%{q}%"))
                )

            records = query.order_by(models.AgentSession.updated_at.desc()).all()

            # 动态概括标题
            needs_commit = False
            for r in records:
                if r.title == "新对话" and r.messages:
                    for m in r.messages:
                        if isinstance(m, dict) and m.get("role") == "user" and m.get("content"):
                            content_str = str(m.get("content")).strip()
                            if content_str:
                                r.title = content_str[:20] + ("..." if len(content_str) > 20 else "")
                                needs_commit = True
                                break

            if needs_commit:
                db.commit()

            res_data = []
            for r in records:
                display_count = 0
                if r.messages:
                    last_role = None
                    for m in r.messages:
                        if not isinstance(m, dict):
                            continue
                        role = m.get("role")
                        if role in ["system", "tool"]:
                            continue
                        if role == "user":
                            display_count += 1
                            last_role = "user"
                        elif role == "assistant":
                            if last_role != "assistant":
                                display_count += 1
                            last_role = "assistant"

                res_data.append(
                    {
                        "session_id": r.session_id[len(prefix) :] if r.session_id.startswith(prefix) else r.session_id,
                        "title": r.title,
                        "created_at": r.created_at.isoformat() if getattr(r, "created_at", None) else "",
                        "updated_at": r.updated_at.isoformat() if getattr(r, "updated_at", None) else "",
                        "message_count": display_count,
                    }
                )
            return res_data

    try:
        sessions = await asyncio.to_thread(fetch_sessions)
        return {"status": "success", "data": sessions}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sessions/{session_id}")
async def get_session_history(session_id: str, username: str = Depends(get_current_username)):
    """获取指定会话的历史详细消息"""
    safe_session_id = f"user_{username}_{session_id}"

    def fetch_history():
        with SessionLocal() as db:
            record = db.query(models.AgentSession).filter(models.AgentSession.session_id == safe_session_id).first()
            if record:
                return record.messages
            return []

    try:
        messages = await asyncio.to_thread(fetch_history)
        return {"status": "success", "data": messages}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/sessions")
async def delete_all_sessions(username: str = Depends(get_current_username)):
    """删除当前用户的所有历史会话 (冷热两层)"""
    prefix = f"user_{username}_"

    def drop_all():
        with SessionLocal() as db:
            records = db.query(models.AgentSession).filter(models.AgentSession.session_id.startswith(prefix)).all()
            if not records:
                return False
            for r in records:
                db.delete(r)
            db.commit()
            return True

    try:
        deleted = await asyncio.to_thread(drop_all)

        # 清除 Redis 热数据
        cursor = 0
        while True:
            cursor, keys = await redis_client.scan(cursor=cursor, match=f"hermes:memory:{prefix}*", count=100)
            if keys:
                await redis_client.delete(*keys)
            if cursor == 0:
                break

        if not deleted:
            return {"status": "success", "message": "当前无历史会话记录"}
        return {"status": "success", "message": "所有历史会话已彻底删除"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str, username: str = Depends(get_current_username)):
    """删除指定的历史会话 (冷热两层)"""
    safe_session_id = f"user_{username}_{session_id}"

    def drop_session():
        with SessionLocal() as db:
            record = db.query(models.AgentSession).filter(models.AgentSession.session_id == safe_session_id).first()
            if not record:
                return False
            db.delete(record)
            db.commit()
            return True

    try:
        deleted = await asyncio.to_thread(drop_session)
        await redis_client.delete(f"hermes:memory:{safe_session_id}")

        if not deleted:
            raise HTTPException(status_code=404, detail="会话记录不存在")
        return {"status": "success", "message": f"会话 {session_id} 已彻底删除"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
