import os
from typing import Dict, Any
from .base import BaseTool
from .secure_client import SecureAsyncClient
from hermes_agent.tool_registry import register_tool

@register_tool
class OptimizeStrategyTool(BaseTool):
    """
    大模型专用的高频策略网格搜索寻优器。
    """
    name = "optimize_strategy_parameters"
    description = "通过网格搜索(Grid Search)批量遍历量化策略的参数组合，利用 Numba C++ 级底层引擎瞬间测算所有可能性，自动找出夏普比率、胜率或总收益最高的最佳参数。"
    parameters = {
        "type": "object",
        "properties": {
            "source_code": {
                "type": "string",
                "description": "完整的 Python 策略类源码"
            },
            "class_name": {
                "type": "string",
                "description": "源码中的策略类名，例如 MACrossStrategy"
            },
            "param_grid": {
                "type": "object",
                "description": "你要测试的参数网络，Key 为参数名，Value 为候选值的数组。例如: {\"fast_ma\": [5, 10, 15], \"slow_ma\": [20, 30]}"
            },
            "target_metric": {
                "type": "string",
                "enum": ["sharpe_ratio", "win_rate", "total_return"],
                "description": "优化的核心目标。可选：sharpe_ratio(夏普比率), win_rate(胜率), total_return(总收益)"
            }
        },
        "required": ["source_code", "class_name", "param_grid"]
    }

    async def run(self, source_code: str, class_name: str, param_grid: dict, target_metric: str = "sharpe_ratio") -> Dict[str, Any]:
        backend_url = os.getenv("BACKEND_API_URL", "http://127.0.0.1:8000")
        
        payload = {
            "source_code": source_code,
            "class_name": class_name,
            "param_grid": param_grid,
            "target_metric": target_metric
        }
        try:
            async with SecureAsyncClient(timeout=30.0) as client:
                resp = await client.post(f"{backend_url}/api/strategy/optimize-sandbox", json=payload)
                return resp.json()
        except Exception as e:
            return {"status": "error", "message": f"优化引擎请求异常: {str(e)}"}