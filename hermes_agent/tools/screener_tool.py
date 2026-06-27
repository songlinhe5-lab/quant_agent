import os
from typing import Dict, Any, Optional
from .base import BaseTool
from .secure_client import SecureAsyncClient
from hermes_agent.tool_registry import register_tool
from .decorators import with_agent_self_correction, ToolCorrectionError

@register_tool
class ScreenerTool(BaseTool):
    """
    全市场选股扫描工具。赋予 Agent 主动发现交易机会的能力。
    """
    name = "screen_stocks"
    description = "全市场智能选股器。请直接将用户的自然语言选股条件原封不动地传给此工具（如：'寻找港股滚动十二个月(TTM)净利润大于100亿...'）。底层引擎已原生接管财报周期及所有硬指标和大师法则，严禁你自行拉取明细数据手动计算！"
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "用户的自然语言选股查询原话"
            }
        },
        "required": ["query"]
    }

    @with_agent_self_correction(max_retries=2, query_param="query")
    async def run(self, query: str = "") -> Dict[str, Any]:
        if not query:
            return {"status": "error", "message": "缺失必要的查询语句"}
            
        base_url = os.getenv("BACKEND_API_URL", "http://127.0.0.1:8000/api").rstrip('/')
        if not base_url.endswith("/api"):
            base_url += "/api"

        async with SecureAsyncClient(timeout=45.0) as client:
            # 1. 前置翻译流程，将 NLP 转化为强类型的后端 JSON 筛选协议
            trans_resp = await client.post(f"{base_url}/screener/translate", json={"query": query})
            if trans_resp.status_code != 200:
                err_msg = trans_resp.text
                try: err_msg = trans_resp.json().get("detail", trans_resp.text)
                except: pass
                return {"status": "error", "message": f"转译选股条件失败: {err_msg}"}
            
            json_dsl = trans_resp.json().get("data")
            
            # 2. 执行选股
            payload = {"dsl": json_dsl, "page": 1, "page_size": 15}
            resp = await client.post(f"{base_url}/screener/run", json=payload)
            
            if resp.status_code != 200:
                err_msg = resp.text
                try: err_msg = resp.json().get("detail", resp.text)
                except: pass
                
                # 💡 抛出自定义异常，交由 @with_agent_self_correction 装饰器拦截并触发大模型重试
                if resp.status_code == 400:
                    raise ToolCorrectionError(err_msg)
                    
                return {"status": "error", "message": f"后端筛选网关报错 (HTTP {resp.status_code}): {err_msg}"}
            
            data = resp.json()
            # 后端已完成分页，这里只需提取真实全量数值补充提示信息
            if data.get("status") == "success":
                total = data.get("total", len(data.get("data", [])))
                data["message"] = f"筛选成功！共找到 {total} 只标的，为节省 Token 已截取前 15 只供您分析。"
            return data