"""板块资金流向服务

三市场板块资金流聚合:
- A股: 行业/概念板块主力净流入排名 (AKShare 东方财富)
- 港股: 南向资金行业分布 (AKShare 东方财富)
- 美股: 核心行业 ETF 主力净流 (Futu API)
"""

from backend.services.fund_flow.service import FundFlowService, fund_flow_service

__all__ = ["FundFlowService", "fund_flow_service"]
