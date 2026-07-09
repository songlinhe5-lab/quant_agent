import os
import json
import asyncio
import re
from typing import Type, List
from pydantic import BaseModel, Field

from backend.services.screener_service import screener_service
from backend.services.futu import futu_service
from backend.routers.strategy import _fetch_backtest_data
from backend.backtest import run_batch_sandbox_backtest
from hermes_agent.tool_registry import register_tool

class ScreenerToolInput(BaseModel):
    query: str = Field(..., description="自然语言选股条件，例如：'美股市值大于100亿，PE小于20，MACD金叉'")
    limit: int = Field(default=10, description="返回的标的数量上限，默认 10只")

@register_tool
class ScreenerTool:
    name = "screen_stocks"
    description = "全市场智能条件选股器。向它发送自然语言条件，它将从全市场为你选出符合技术面、财务面特征的优质股票备选池。"
    args_schema: Type[BaseModel] = ScreenerToolInput

    @property
    def parameters(self):
        return self.args_schema.model_json_schema()

    async def run(self, query: str, limit: int = 10) -> str:
        try:
            dsl = await screener_service.translate_nlp_to_dsl(query)
            markets, futu_filters, post_filters = screener_service.parse_dsl_to_futu_filters(dsl)
            
            tasks = [futu_service.screen_stocks(market=m, filters=futu_filters) for m in markets]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            final_data = []
            for res in results:
                if isinstance(res, dict) and res.get("status") == "success":
                    final_data.extend(res.get("data", []))
                    
            if post_filters.get("exclude_st"):
                final_data = [r for r in final_data if "ST" not in r.get("name", "").upper() and "退" not in r.get("name", "")]
                
            tech_patterns = post_filters.get("technical_patterns", [])
            if final_data and tech_patterns:
                final_data = await screener_service.apply_technical_pattern_filtering(final_data, tech_patterns)
                
            if not final_data:
                return f"根据条件 '{query}' 未能筛选出任何股票。"
                
            top_stocks = final_data[:limit]
            stock_list = [f"{r['symbol']} ({r['name']})" for r in top_stocks]
            tickers_only = [r['symbol'] for r in top_stocks]
            
            return f"✅ 选股成功！符合条件的备选股票池如下：\n" + "\n".join(stock_list) + f"\n\n请提取以下代码数组进入下一步的批量回测：{json.dumps(tickers_only)}"
        except Exception as e:
            return f"选股工具执行失败: {str(e)}"

class BatchBacktestInput(BaseModel):
    tickers: List[str] = Field(..., description="要回测的股票代码列表数组，例如 ['US.AAPL', 'US.MSFT']")
    strategy_name: str = Field(..., description="保存在你工作区的策略草稿名称（不带.py后缀），例如 'divergenceresonancestrategy'")
    period: str = Field(default="max", description="回测时间跨度，支持 1mo, 3mo, 6mo, 1y, 2y, 5y, 10y, 20y, max。默认使用 max 获取所有可用历史以保证回测深度。")
    
@register_tool
class BatchBacktestTool:
    name = "batch_backtest_strategy"
    description = "对股票备选池执行批量量化回测。提供策略名称和股票池代码列表，返回组合的总收益率、夏普比率等核心指标，用于出具最终的投研研报。"
    args_schema: Type[BaseModel] = BatchBacktestInput

    @property
    def parameters(self):
        return self.args_schema.model_json_schema()

    async def run(self, tickers: List[str], strategy_name: str, period: str = "max") -> str:
        try:
            strategies_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "strategies", "drafts"))
            file_path = os.path.join(strategies_dir, f"{strategy_name.lower()}.py")
            if not os.path.exists(file_path):
                return f"找不到名为 '{strategy_name}' 的策略草稿。请确保策略名正确。"
                
            with open(file_path, "r", encoding="utf-8") as f:
                source_code = f.read()
                
            match = re.search(r'class\s+([A-Za-z0-9_]+)\s*\(BaseStrategy', source_code)
            if not match:
                return "策略源码未找到合法的基类继承定义。"
            class_name = match.group(1)
            
            async def fetch_one(t):
                success, df, _ = await _fetch_backtest_data(t, period, "auto", "1d")
                return t, df if success else None

            fetch_tasks = [fetch_one(t) for t in tickers]
            results = await asyncio.gather(*fetch_tasks)
            dfs = {t: df for t, df in results if df is not None and not df.empty}
            
            if not dfs:
                return "所有选定标的均无法获取历史数据，批量回测终止。"
                
            report = await asyncio.to_thread(
                run_batch_sandbox_backtest, source_code, class_name, {}, dfs, 100000.0
            )
            
            metrics = report["metrics"]
            valid_tickers = report["valid_tickers"]
            
            return f"✅ 批量横截面回测完成！\n成功参测有效标的数: {len(valid_tickers)}/{len(tickers)}\n" \
                   f"策略组合总收益率: {metrics['total_return']}\n" \
                   f"组合夏普比率: {metrics['sharpe_ratio']}\n" \
                   f"组合最大回撤: {metrics['max_drawdown']}\n" \
                   f"组合总体胜率: {metrics['win_rate']}\n" \
                   f"总交易撮合次数: {metrics['total_trades']}\n\n" \
                   f"请作为顶级分析师，结合这些数据向用户输出最终的投资交易建议与评级。"
        except Exception as e:
            return f"批量回测引擎执行失败: {str(e)}"