"""
财报预期对比工具 - 对比实际财报数据与预设预期值，生成差异分析报告
"""

import os
from typing import Optional, Type

import httpx
from pydantic import BaseModel, Field

from hermes_agent.tool_registry import register_tool


class EarningsCompareInput(BaseModel):
    ticker: str = Field(..., description="股票代码，例如 HK.00772, US.AAPL")
    period: str = Field(..., description="财报周期，例如 2026H1, 2025Q4, 2025FY")
    action: str = Field(
        default="compare",
        description="操作类型: compare=对比分析, set=设置预期值, get=查看已设置的预期值",
    )


class EarningsExpectation(BaseModel):
    """单条预期值定义"""

    metric: str = Field(..., description="指标名称，如 '总收入', 'Non-IFRS净利润'")
    expected_low: Optional[float] = Field(None, description="预期下限（亿元）")
    expected_high: Optional[float] = Field(None, description="预期上限（亿元）")
    expected_value: Optional[float] = Field(None, description="预期值（单一值）")
    unit: str = Field(default="亿", description="单位")
    scenario: str = Field(default="中性", description="情景: 乐观/中性/悲观")
    notes: str = Field(default="", description="关键假设说明")


@register_tool
class EarningsCompareTool:
    """
    财报预期对比工具：存储预期值 → 拉取实际数据 → 生成差异分析报告
    """

    name = "compare_earnings_expectations"
    description = """对比财报实际值与预设预期值，生成差异分析报告。

    使用场景：
    1. action="set" - 设置某只股票的财报预期基准值（在财报发布前使用）
    2. action="compare" - 财报发布后，拉取实际数据并与预期对比
    3. action="get" - 查看已设置的预期值

    示例：
    - 设置阅文2026H1预期: action="set", ticker="HK.00772", period="2026H1"
    - 对比阅文2026H1实际: action="compare", ticker="HK.00772", period="2026H1"
    """
    args_schema: Type[BaseModel] = EarningsCompareInput

    @property
    def parameters(self):
        return self.args_schema.model_json_schema()

    async def run(self, ticker: str, period: str, action: str = "compare") -> str:
        if action == "set":
            return await self._set_expectations(ticker, period)
        elif action == "get":
            return await self._get_expectations(ticker, period)
        else:  # compare
            return await self._compare_earnings(ticker, period)

    async def _set_expectations(self, ticker: str, period: str) -> str:
        """设置预期值 - 返回引导信息让 Agent 提供数据"""
        return f"""📋 请提供 {ticker} {period} 的预期基准值：

请按以下格式提供预期数据（可只提供部分）：

| 指标 | 预期值/区间 | 单位 | 情景 | 关键假设 |
|------|------------|------|------|---------|
| 总收入 | 34-37 | 亿 | 中性 | 低基数+版权复苏 |
| Non-IFRS净利润 | 5.5-7.0 | 亿 | 中性 | 营收杠杆 |
| ... | ... | ... | ... | ... |

提供后我将存储为对比基准。"""

    async def _get_expectations(self, ticker: str, period: str) -> str:
        """查看已设置的预期值"""
        backend_url = os.getenv("BACKEND_URL", "http://localhost:8000")

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{backend_url}/api/v1/earnings/expectations",
                    params={"ticker": ticker, "period": period},
                )
                resp.raise_for_status()
                data = resp.json()

                if data.get("status") == "success" and data.get("data"):
                    expectations = data["data"]
                    output = [f"📋 {ticker} {period} 预期基准值：\n"]
                    output.append("| 指标 | 预期区间 | 情景 | 假设 |")
                    output.append("|------|---------|------|------|")
                    for exp in expectations:
                        low = exp.get("expected_low", "")
                        high = exp.get("expected_high", "")
                        unit = exp.get("unit", "")
                        output.append(
                            f"| {exp['metric']} | {low}-{high} {unit} | {exp.get('scenario', '')} | {exp.get('notes', '')} |"
                        )
                    return "\n".join(output)
                else:
                    return f"未找到 {ticker} {period} 的预期基准值。请先使用 action='set' 设置。"
        except Exception as e:
            return f"获取预期值失败: {str(e)}"

    async def _compare_earnings(self, ticker: str, period: str) -> str:
        """对比实际财报数据与预期值"""
        backend_url = os.getenv("BACKEND_URL", "http://localhost:8000")

        # 1. 获取预期基准值
        expectations = []
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{backend_url}/api/v1/earnings/expectations",
                    params={"ticker": ticker, "period": period},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("status") == "success":
                        expectations = data.get("data", [])
        except Exception as e:
            print(f"⚠️ [EarningsCompare] 获取预期值失败: {e}")

        if not expectations:
            return f"""⚠️ 未找到 {ticker} {period} 的预期基准值。

请先设置预期值：
1. 调用 compare_earnings_expectations(action="set", ticker="{ticker}", period="{period}")
2. 提供各项指标的预期区间和关键假设"""

        # 2. 返回对比模板，引导 Agent 拉取实际数据
        output = [f"📊 {ticker} {period} 财报对比分析\n"]
        output.append("=" * 50)
        output.append("\n📋 预设预期基准：\n")
        output.append("| 指标 | 预期区间 | 实际值 | 预期差 | 验证 |")
        output.append("|------|---------|--------|--------|------|")

        for exp in expectations:
            metric = exp.get("metric", "")
            low = exp.get("expected_low", "")
            high = exp.get("expected_high", "")
            unit = exp.get("unit", "")
            output.append(f"| {metric} | {low}-{high} {unit} | ? | ? | ? |")

        output.append("\n" + "=" * 50)
        output.append("\n💡 下一步操作：")
        output.append(f'1. 调用 get_fundamental_data(ticker="{ticker}") 获取实际财报数据')
        output.append(f'2. 或调用 analyze_financial_report(ticker="{ticker}") 读取本地财报PDF')
        output.append("3. 将实际值填入上表，计算预期差 = (实际值 - 预期中值) / 预期中值 × 100%")
        output.append("4. 判断是否超预期：预期差 > 0% 为超预期，< 0% 为不及预期")

        return "\n".join(output)
