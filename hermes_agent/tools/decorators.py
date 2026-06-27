import inspect
import functools
import asyncio
from typing import Callable
from backend.services.notification_service import notification_service

class ToolCorrectionError(Exception):
    """当子模型或下游 API 返回校验失败时抛出，以此触发装饰器的外层自我纠错重试"""
    pass

def with_agent_self_correction(max_retries: int = 2, query_param: str = "query"):
    """
    Agent Tool 全局自我纠错装饰器 (Self-Correction)。
    拦截 ToolCorrectionError，将报错拼接到指定的入参（如 query）后，强制触发 LLM 修正自己的输出。
    """
    def decorator(func: Callable):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            # 获取并绑定原始参数，处理默认值
            sig = inspect.signature(func)
            bound_args = sig.bind(*args, **kwargs)
            bound_args.apply_defaults()
            
            original_query = bound_args.arguments.get(query_param, "")
            last_error = ""
            
            for attempt in range(max_retries):
                if attempt > 0 and last_error:
                    # 动态注入报错信息，利用大模型极强的上下文反思能力进行自我修正
                    enhanced_query = str(original_query) + f"\n\n[系统提示：你上一次的操作未通过校验，报错如下：{last_error}。请严格参考规则修正你的输出。]"
                    bound_args.arguments[query_param] = enhanced_query
                    
                try:
                    return await func(*bound_args.args, **bound_args.kwargs)
                except ToolCorrectionError as e:
                    last_error = str(e)
                    print(f"⚠️ [{func.__name__}] 触发大模型自我纠错，准备第 {attempt + 1} 次重试...\n报错: {last_error}")
                    
                    # 💡 将自我反思的过程通过 WebSocket (系统通知渠道) 实时推送给前端
                    alert_msg = f"🧠 [AI 自我反思] 发现参数偏离设定，正在自动纠错重试 (第 {attempt + 1} 次)...\n拦截原因: {last_error}"
                    asyncio.create_task(notification_service.send_alert(alert_msg))
                    
                    if attempt == max_retries - 1:
                        return {"status": "error", "message": f"多次纠错尝试均失败，请更换指令重试。最后一次报错: {last_error}"}
                except Exception as e:
                    return {"status": "error", "message": f"工具执行发生未知异常: {str(e)}"}
        return wrapper
    return decorator