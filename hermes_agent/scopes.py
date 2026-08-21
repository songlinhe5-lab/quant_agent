"""
AGENT-03 · 工具集场景分类

对标 hermes `toolsets.py` + codex `tools/` 分组思想。
提供场景标签定义与自动分类脚本入口。
"""

from __future__ import annotations

from enum import Enum
from typing import Dict, List


class ToolScope(str, Enum):
    """
    工具场景分类闭集。

    每个工具可属于多个场景（通过 register_tool(scopes=[...]) 声明）。
    """

    # ─── 市场数据类 ──────────────────────────────────────────────
    QUOTE = "quote"  # 盘口实时价、涨跌、成交量
    INDICATORS = "indicators"  # 技术指标 MA/MACD/RSI 等
    FUND_FLOW = "fund_flow"  # 主力资金净流入、席位分析

    # ─── 基本面财务类 ────────────────────────────────────────────
    FUNDAMENTAL = "fundamental"  # PE/PB/ROE、财报三大表

    # ─── 宏观舆情类 ──────────────────────────────────────────────
    MACRO = "macro"  # 美债、VIX、非农、FOMC 日历
    NEWS = "news"  # 新闻聚合、个股公告

    # ─── 交易执行类 ──────────────────────────────────────────────
    TRADE = "trade"  # OMS：买入/卖出/撤单/账户查询

    # ─── 检索知识库类 ────────────────────────────────────────────
    SEARCH = "search"  # 网络搜索、研报下载、本地知识库 RAG

    # ─── 回测与策略研发类 ──────────────────────────────────────
    BACKTEST = "backtest"  # 历史回测引擎（暂未实装）
    STRATEGY = "strategy"  # 策略实验室（暂未实装）

    # ─── 系统工具类 ──────────────────────────────────────────────
    SYSTEM = "system"  # 环境检查、版本查询、健康探测


# ─── 默认场景集合 ──────────────────────────────────────────────────
DEFAULT_TOOL_SET: List[ToolScope] = [
    ToolScope.QUOTE,
    ToolScope.INDICATORS,
    ToolScope.FUND_FLOW,
    ToolScope.FUNDAMENTAL,
    ToolScope.MACRO,
    ToolScope.NEWS,
    ToolScope.TRADE,
    ToolScope.SEARCH,
]


def resolve_scope(name: str) -> ToolScope:
    """
    从名称解析 ToolScope 枚举值。

    Args:
        name: 场景名称字符串，如 "quote" / "fundamental" / "trade"
    Returns:
        对应的 ToolScope 枚举值
    Raises:
        ValueError: 非法名称
    """
    try:
        return ToolScope(name)
    except ValueError as e:
        raise ValueError(f"Unknown tool scope '{name}', valid values: {[s.value for s in ToolScope]}") from e


def get_scope_names() -> List[str]:
    """返回所有有效场景名称列表。"""
    return [s.value for s in ToolScope]


def classify_tools_by_description(tools_desc: Dict[str, str]) -> Dict[ToolScope, List[str]]:
    """
    辅助函数：基于工具描述文本的关键词启发式分类（用于批量打标参考）。

    注意：最终仍需人工审核修正；本脚本仅生成初始草稿。
    """
    keyword_map: Dict[ToolScope, List[str]] = {
        ToolScope.QUOTE: ["最新价", "价格", "报价", "tick", "盘口", "买卖档"],
        ToolScope.INDICATORS: ["MA", "均线", "MACD", "RSI", "布林带", "指标", "技术指标"],
        ToolScope.FUND_FLOW: ["资金流", "主力", "净流入", "席位", "broker"],
        ToolScope.FUNDAMENTAL: ["PE", "PB", "ROE", "财报", "财务报表", "估值", "市盈率"],
        ToolScope.MACRO: ["美债", "VIX", "非农", "失业率", "FOMC", "利率决议", "宏观"],
        ToolScope.NEWS: ["新闻", "公告", "舆情", "头条"],
        ToolScope.TRADE: ["买入", "卖出", "下单", "订单", "OMS", "交易", "平仓"],
        ToolScope.SEARCH: ["搜索", "研报", "下载", "知识库", "网页"],
        ToolScope.BACKTEST: ["回测", "backtest"],
        ToolScope.STRATEGY: ["策略", "algo", "量化策略"],
        ToolScope.SYSTEM: ["健康", "版本", "env", "环境"],
    }

    result: Dict[ToolScope, List[str]] = {scope: [] for scope in ToolScope}

    for name, desc in tools_desc.items():
        scores: Dict[ToolScope, int] = {}
        for scope, keywords in keyword_map.items():
            count = sum(1 for kw in keywords if kw.lower() in desc.lower())
            scores[scope] = count

        # 取最高分且 >0
        best_scope = max(scores.items(), key=lambda x: x[1])
        if best_scope[1] > 0:
            result[best_scope[0]].append(name)

    return result
