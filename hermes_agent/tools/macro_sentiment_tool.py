from typing import Any, Dict

from hermes_agent.tool_registry import register_tool

from .base import BaseTool, get_backend_api_url
from .secure_client import SecureAsyncClient


@register_tool
class MacroSentimentTool(BaseTool):
    """
    宏观情绪风向标历史序列工具。
    获取 P/C Ratio (期权多空比)、VIX (恐慌指数) 和高收益债利差 (Credit Spread) 的近期历史数据。
    """

    name = "get_macro_sentiment_history"
    description = (
        "获取近期市场情绪的真实历史序列，包含 P/C Ratio (期权多空比)、VIX (恐慌指数) 和高收益债利差 (Credit Spread)。"
        "当用户要求'分析当前情绪'、'查看恐慌指数'、'P/C Ratio 走势'时，调用此工具提取近期序列，结合阈值给出专业研判。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "days": {
                "type": "integer",
                "description": "获取最近 N 天的情绪数据，默认为 30 天。",
                "default": 30,
            },
        },
    }

    async def run(self, days: int = 30) -> Dict[str, Any]:
        backend_url = get_backend_api_url()
        url = f"{backend_url}/macro/sentiment-history"

        # API 使用 limit (数据点数量)，按每天约 1 个数据点估算
        limit = min(days, 2000)

        async with SecureAsyncClient(timeout=30.0) as client:
            resp = await client.get(url, params={"limit": limit})
            if resp.status_code != 200:
                err_msg = resp.text
                try:
                    err_msg = resp.json().get("detail", resp.text)
                except Exception:
                    pass
                return {"status": "error", "message": f"获取情绪历史失败 (HTTP {resp.status_code}): {err_msg}"}

            data = resp.json()
            # 后端统一响应格式: {"code": 0, "msg": "ok", "data": {"status": "success", "data": [...]}}
            if data.get("code") != 0 and data.get("status") != "success":
                return {"status": "error", "message": f"情绪数据异常: {data}"}

            # 提取内层实际数据
            inner = data.get("data", {})
            records = inner.get("data", []) if isinstance(inner, dict) else inner
            if not records:
                return {"status": "success", "message": "暂无情绪历史数据，SentimentRecord 表可能为空。"}

            # ── 数据完整性红线 (PROD-零幻觉) ──
            # 若所有记录的核心字段(VIX/P-C/Spread)均为 None，说明源数据缺失
            # (如 yfinance 节点瘫痪)，禁止把 30 条 None 当有效序列输出误导 LLM 研判。
            def _has_value(r):
                return any(r.get(k) is not None for k in ("vix", "pc_ratio", "credit_spread"))

            valid_records = [r for r in records if _has_value(r)]
            if not valid_records:
                return {
                    "status": "success",
                    "data_available": False,
                    "message": (
                        "情绪数据源当前不可用：VIX/P-C 历史记录均为空 (源数据缺失，"
                        "通常因 yfinance 节点断供)。无法进行情绪研判，请勿基于空序列编造结论。"
                    ),
                    "records": records,
                }

            # 提取关键阈值供 LLM 研判（取最近一条有值的记录）
            latest = valid_records[-1]
            vix_latest = latest.get("vix")
            pc_latest = latest.get("pc_ratio")
            cs_latest = latest.get("credit_spread")

            summary_lines = [
                f"📊 情绪风向标历史 (最近 {len(valid_records)} 个有效数据点，共 {len(records)} 条记录)：",
                f"- 最新 VIX: {vix_latest} (<15 乐观, >25 恐慌)" if vix_latest else "- VIX: N/A",
                f"- 最新 P/C Ratio: {pc_latest} (<0.7 看涨, >1.0 看跌)" if pc_latest else "- P/C Ratio: N/A",
                f"- 最新 Credit Spread: {cs_latest}% (<4.5% 安全, >4.5% 高危)" if cs_latest else "- Credit Spread: N/A",
                "",
                "近期有效序列 (最近 10 条)：",
            ]

            for r in valid_records[-10:]:
                time_str = r.get("time", "")
                vix = r.get("vix", "N/A")
                pc = r.get("pc_ratio", "N/A")
                cs = r.get("credit_spread", "N/A")
                summary_lines.append(f"  [{time_str}] VIX={vix} | P/C={pc} | Spread={cs}%")

            return {
                "status": "success",
                "data_available": True,
                "data": {"summary": "\n".join(summary_lines), "records": valid_records},
            }
