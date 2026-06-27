import json
from typing import Type, Literal, Optional
from pydantic import BaseModel, Field

from backend.core.redis_client import redis_client
from backend.services.futu.utils import format_ticker
from hermes_agent.tool_registry import register_tool

class StockTrackingInput(BaseModel):
    ticker: str = Field(default="", description="股票代码，例如 US.AAPL, HK.00700。如果 action 是 list，可以传空字符串。")
    action: Literal["add", "remove", "list"] = Field(..., description="操作类型：add (加入长期监控), remove (取消监控), list (列出所有正在监控的股票)")
    upper_threshold: Optional[float] = Field(default=None, description="可选：向上突破的价格报警阈值")
    lower_threshold: Optional[float] = Field(default=None, description="可选：向下突破（跌破）的价格报警阈值")
    pct_change_threshold: Optional[float] = Field(default=None, description="可选：当日涨跌幅的异动报警阈值（纯数字，如 5 表示涨幅大于 5% 或跌幅小于 -5% 均触发报警）")
    user_id: str = Field(default="admin", description="当前操作的用户ID（系统根据会话上下文自动注入）")

@register_tool
class StockTrackingTool:
    """
    用于将特定股票加入或移出系统级长期监控池的 Agent Tool。
    加入监控池后，系统后台守护进程会自动追踪该标的实时行情、盘口异动以及个股专属新闻，并主动推送警报。
    """
    name = "manage_monitored_stocks"
    description = "管理系统的长期追踪股票池。当用户要求'长期关注/监控/追踪/盯盘某只股票'时调用此工具。"
    args_schema: Type[BaseModel] = StockTrackingInput

    @property
    def parameters(self):
        return self.args_schema.model_json_schema()

    async def run(self, ticker: str, action: str, upper_threshold: Optional[float] = None, lower_threshold: Optional[float] = None, pct_change_threshold: Optional[float] = None, user_id: str = "admin") -> str:
        try:
            # 1. 用户的个人监控池
            user_set_key = f"quant:user:{user_id}:monitored_stocks"
            # 2. 全局底层数据抓取池 (引用计数)
            global_ref_key = "quant:settings:monitored_refcounts"
            
            if action == "list":
                members = await redis_client.smembers(user_set_key)
                if not members:
                    return "当前系统没有正在长期监控的股票，也没有设置价格报警。"
                    
                stocks = [m.decode('utf-8') if isinstance(m, bytes) else str(m) for m in members]
                
                # 组装展示个人的报警规则
                alerts_info = []
                for t in stocks:
                    rules = await redis_client.hget(f"quant:alerts:by_ticker:{t}", user_id)
                    if rules:
                        alerts_info.append(f"{t}: {rules}")
                        
                return f"您的自选监控池：{', '.join(stocks)}\n您的活跃价格报警：{', '.join(alerts_info) if alerts_info else '无'}"
                
            if not ticker:
                return "操作 add 或 remove 必须提供具体的股票代码 (ticker)。"
                
            fmt_ticker = format_ticker(ticker)
            alert_key = f"quant:alerts:by_ticker:{fmt_ticker}"
            
            if action == "add":
                # 往个人池加入标的
                is_new_for_user = await redis_client.sadd(user_set_key, fmt_ticker)
                
                # 如果是该用户新加的，增加全局引用计数（告诉底层 C++ 网关有 1 个人需要这个数据）
                if is_new_for_user:
                    await redis_client.hincrby(global_ref_key, fmt_ticker, 1)
                    
                msg = f"✅ 成功将 {fmt_ticker} 加入长期监控池！系统现已在后台开启实时数据监听。"
                
                if upper_threshold is not None or lower_threshold is not None or pct_change_threshold is not None:
                    rules = {}
                    if upper_threshold: rules["upper"] = upper_threshold
                    if lower_threshold: rules["lower"] = lower_threshold
                    if pct_change_threshold: rules["pct_change"] = pct_change_threshold
                    # 将报警规则写入【以标的为索引的 Hash】，键为 user_id
                    await redis_client.hset(alert_key, user_id, json.dumps(rules))
                    msg += f"\n🔔 已为您挂载报警：上限 {upper_threshold or '未设'}, 下限 {lower_threshold or '未设'}, 振幅阈值 ±{pct_change_threshold or '未设'}%。触发后将自动通知并解除。"
                return msg
                
            elif action == "remove":
                res = await redis_client.srem(user_set_key, fmt_ticker)
                await redis_client.hdel(alert_key, user_id)
                
                if res:
                    # 减少全局引用计数，若降到 0 则底层网关会自动退订该标的，释放内存
                    new_count = await redis_client.hincrby(global_ref_key, fmt_ticker, -1)
                    if new_count <= 0:
                        await redis_client.hdel(global_ref_key, fmt_ticker)
                    return f"✅ 成功将 {fmt_ticker} 从监控池中移除，并清除了相关的报警规则。"
                return f"⚠️ {fmt_ticker} 本不在监控池中。"
                
            return f"⚠️ 未知的操作类型: {action}。支持的操作仅限: add, remove, list。"
        except Exception as e:
            return f"执行监控池管理异常: {str(e)}"