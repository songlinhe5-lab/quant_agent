import asyncio
import unittest
from typing import Any, Dict, List, Optional

from hermes_agent.tool_registry import register_tool

from .base import BaseTool, get_backend_api_url
from .secure_client import SecureAsyncClient


@register_tool
class TechnicalIndicatorsTool(BaseTool):
    """
    负责拉取历史 K 线并进行矩阵级的技术指标计算。
    贯彻“Token 极简原则”，仅返回最新截面的特征数据。
    """

    name = "calculate_technical_indicators"
    description = "计算指定股票的核心技术指标 (如 MA 均线, RSI, MACD, ATR)，并自带基于均线与动能的 0-100 trend_score(多空趋势评分)。大模型严禁自行口算指标，必须调用此工具获取精确数值。"
    parameters = {
        "type": "object",
        "properties": {
            "ticker": {"type": "string", "description": "股票标准代码，例如 AAPL, 0700.HK"},
            "ma_periods": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "可选：需要计算的 MA 均线周期列表，默认计算 [10, 20]",
            },
            "rsi_period": {"type": "integer", "description": "可选：需要计算的 RSI 周期，默认为 14"},
            "include_macd": {"type": "boolean", "description": "可选：是否计算 MACD (12, 26, 9) 指标，默认为 true"},
            "include_kdj": {"type": "boolean", "description": "可选：是否计算 KDJ (9, 3, 3) 随机指标，默认为 true"},
            "atr_period": {"type": "integer", "description": "可选：需要计算的 ATR 真实波幅周期，默认为 14"},
            "stop_loss_multiplier": {
                "type": "number",
                "description": "可选：ATR 动态止损乘数，默认 2.0 (例如 MA_10 - 2 * ATR)",
            },
            "take_profit_multiplier": {
                "type": "number",
                "description": "可选：ATR 动态止盈乘数，默认 3.0 (例如 MA_10 + 3 * ATR)",
            },
            "lookback_days": {
                "type": "integer",
                "description": "可选：返回过去多少天的指标趋势，默认 1 (仅返回最新的一天)，需要趋势分析时可设为 5 或 7。",
            },
            "bbands_period": {
                "type": "integer",
                "description": "可选：需要计算的布林带(Bollinger Bands)周期，默认为 20。设为 0 可关闭计算。",
            },
            "bbands_std_dev": {"type": "number", "description": "可选：布林带的标准差倍数，默认为 2.0"},
        },
        "required": ["ticker"],
    }

    def __init__(self):
        super().__init__()

    async def run(
        self,
        ticker: str = "",
        ma_periods: Optional[List[int]] = None,
        rsi_period: int = 14,
        include_macd: bool = True,
        include_kdj: bool = True,
        atr_period: int = 14,
        stop_loss_multiplier: float = 2.0,
        take_profit_multiplier: float = 3.0,
        lookback_days: int = 1,
        bbands_period: int = 20,
        bbands_std_dev: float = 2.0,
    ) -> Dict[str, Any]:
        if not ticker:
            return {"status": "error", "message": "调用失败：缺少必要的股票代码(ticker)参数。"}

        backend_url = get_backend_api_url()
        # 强制格式化 ticker
        ticker = self.normalize_ticker(ticker)
        url = f"{backend_url}/market/tech-indicators"
        # RL-14: 限流感知智能重试
        async with SecureAsyncClient(timeout=20.0) as client:
            return await self.rate_limit_aware_request(
                client,
                "GET",
                url,
                params={"ticker": ticker, "lookback_days": lookback_days},
                timeout=20.0,
            )


class TestTechnicalIndicatorsTool(unittest.TestCase):
    def test_missing_ticker(self):
        tool = TechnicalIndicatorsTool()
        self.assertEqual(asyncio.run(tool.run(""))["status"], "error")


if __name__ == "__main__":
    # 本地验证与测试指标计算逻辑
    import json

    tool = TechnicalIndicatorsTool()
    print("⏳ 正在通过 yfinance 拉取 AAPL 数据并进行指标计算...")
    res = asyncio.run(tool.run(ticker="AAPL", ma_periods=[10, 20], rsi_period=14, include_macd=True, lookback_days=5))
    print("\n✅ 指标计算测试结果:")
    print(json.dumps(res, indent=2, ensure_ascii=False))
