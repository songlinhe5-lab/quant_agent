"""
选股器常量与字段映射表。

将验证器中庞大且高频初始化的字典、列表与正则移至全局静态内存，
防止在每次解析大模型生成的 DSL 过滤条件时，反复分配内存并触发垃圾回收 (GC) 导致 CPU 飙高。
"""

import re

_ALIAS_MAP = {
    "PE_PERCENTILE": "HIST_PERCENTILE_PE",
    "PE历史百分位": "HIST_PERCENTILE_PE",
    "PB_PERCENTILE": "HIST_PERCENTILE_PB",
    "PS_PERCENTILE": "HIST_PERCENTILE_PS",
    "DEBT_EQUITY_RATIO": "PROPERTY_RATIO",
    "产权比率": "PROPERTY_RATIO",
    "CURRENT_RATIO": "CURRENT_RATIO",
    "流动比率": "CURRENT_RATIO",
    "QUICK_RATIO": "QUICK_RATIO",
    "速动比率": "QUICK_RATIO",
    "GROSS_MARGIN": "GROSS_PROFIT_RATIO",
    "毛利率": "GROSS_PROFIT_RATIO",
    "OPERATING_MARGIN": "OPERATING_MARGIN_TTM",
    "营业利润率": "OPERATING_MARGIN_TTM",
    "NET_PROFIT_MARGIN": "NET_PROFIT_RATIO",
    "净利润率": "NET_PROFIT_RATIO",
    "DEBT_RATIO": "DEBT_TO_ASSETS",
    "资产负债率": "DEBT_TO_ASSETS",
    "CASH_COVER": "NET_PROFIT_CASH_COVER_TTM",
    "ROA": "ROA_TTM",
    "RETURN_ON_ASSETS": "ROA_TTM",
    "资产回报率": "ROA_TTM",
    "PRICE_TO_52W_HIGH": "CUR_PRICE_TO_HIGHEST52_WEEKS_RATIO",
    "PRICE_TO_52W_LOW": "CUR_PRICE_TO_LOWEST52_WEEKS_RATIO",
    "HIGH_TO_52W_HIGH": "HIGH_PRICE_TO_HIGHEST52_WEEKS_RATIO",
    "LOW_TO_52W_LOW": "LOW_PRICE_TO_LOWEST52_WEEKS_RATIO",
    "CHANGE_5MIN": "CHANGE_RATE_5MIN",
    "CHANGE_YTD": "CHANGE_RATE_BEGIN_YEAR",
    "FLOAT_MARKET_CAP": "FLOAT_MARKET_VAL",
    "SHAREHOLDERS_PROFIT_TTM": "SHAREHOLDER_NET_PROFIT_TTM",  # noqa: E501
    "CASH_EQUIVALENTS": "CASH_AND_CASH_EQUIVALENTS",
    "OPERATING_PROFIT_GROWTH": "OPERATING_PROFIT_GROWTH_RATE",  # noqa: E501
    "TOTAL_ASSETS_GROWTH": "TOTAL_ASSETS_GROWTH_RATE",
    "SHAREHOLDER_PROFIT_GROWTH": "PROFIT_TO_SHAREHOLDERS_GROWTH_RATE",  # noqa: E501
    "PROFIT_BEFORE_TAX_GROWTH": "PROFIT_BEFORE_TAX_GROWTH_RATE",
    "NOCF_PER_SHARE_GROWTH": "NOCF_PER_SHARE_GROWTH_RATE",  # noqa: E501
    "OPERATING_PROFIT_TOTAL_RATIO": "OPERATING_PROFIT_TO_TOTAL_PROFIT",
    "RSI_BOTTOM_DIVERGENCE": "RSI_BOTTOM_DIVERGE",  # noqa: E501
    "RSI_TOP_DIVERGENCE": "RSI_TOP_DIVERGE",
    "MACD_BOTTOM_DIVERGENCE": "MACD_BOTTOM_DIVERGE",  # noqa: E501
    "MACD_TOP_DIVERGENCE": "MACD_TOP_DIVERGE",
    "PB_RATE": "PB",
    "PE_RATE": "PE_TTM",
    "VOLUME_RATIO": "VOLUME_MULTIPLE",
}

_VALID_FIELDS = [
    "MARKET_CAP",
    "PE_TTM",
    "PB",
    "PRICE",
    "AVG_VOLUME",
    "AVG_TURNOVER",
    "TURNOVER_RATIO",  # noqa: E501
    "PRICE_CHANGE_PCT",
    "AMPLITUDE",
    "ROE",
    "ROA_TTM",
    "DIVIDEND_RATIO",
    "BASIC_EPS",
    "NET_PROFIT",
    "REVENUE",
    "GROSS_PROFIT_RATIO",
    "OPERATING_MARGIN_TTM",
    "OPERATING_CASH_FLOW_TTM",  # noqa: E501
    "NET_PROFIT_CASH_COVER_TTM",
    "DEBT_TO_ASSETS",
    "PROPERTY_RATIO",
    "CURRENT_RATIO",
    "HIST_PERCENTILE_PE",
    "HIST_PERCENTILE_PB",
    "HIST_PERCENTILE_PS",
    "REVENUE_GROWTH",
    "NET_PROFIT_GROWTH",  # noqa: E501
    "EPS_GROWTH_RATE",
    "ROE_GROWTH_RATE",
    "STOCK_PLATE",
    "LISTED_DAYS",
    "PRICE_TO_52W_HIGH",
    "PRICE_TO_52W_LOW",
    "HIGH_TO_52W_HIGH",
    "LOW_TO_52W_LOW",
    "VOLUME_MULTIPLE",
    "BID_ASK_RATIO",
    "LOT_PRICE",
    "PE_ANNUAL",
    "CHANGE_5MIN",
    "CHANGE_YTD",
    "PS_TTM",
    "PCF_TTM",
    "TOTAL_SHARE",
    "FLOAT_SHARE",
    "FLOAT_MARKET_CAP",
    "NET_PROFIT_RATIO",
    "ROIC",
    "EBIT_TTM",
    "EBITDA",
    "EBIT_MARGIN",
    "EBITDA_MARGIN",
    "FINANCIAL_COST_RATE",
    "OPERATING_PROFIT_TTM",
    "SHAREHOLDERS_PROFIT_TTM",
    "QUICK_RATIO",  # noqa: E501
    "CURRENT_ASSET_RATIO",
    "CURRENT_DEBT_RATIO",
    "EQUITY_MULTIPLIER",
    "CASH_EQUIVALENTS",  # noqa: E501
    "TOTAL_ASSET_TURNOVER",
    "FIXED_ASSET_TURNOVER",
    "INVENTORY_TURNOVER",
    "ACCOUNTS_RECEIVABLE",  # noqa: E501
    "EBIT_GROWTH_RATE",
    "OPERATING_PROFIT_GROWTH",
    "TOTAL_ASSETS_GROWTH",
    "SHAREHOLDER_PROFIT_GROWTH",  # noqa: E501
    "PROFIT_BEFORE_TAX_GROWTH",
    "ROIC_GROWTH_RATE",
    "NOCF_GROWTH_RATE",
    "NOCF_PER_SHARE_GROWTH",  # noqa: E501
    "OPERATING_REVENUE_CASH_COVER",
    "OPERATING_PROFIT_TOTAL_RATIO",
    "DILUTED_EPS",
    "NOCF_PER_SHARE",  # noqa: E501
    "OPERATING_REVENUE_GROWTH_RATE",
    "MACD_GOLDEN_CROSS",
    "KDJ_GOLDEN_CROSS",
    "RSI_BOTTOM_DIVERGE",
    "RSI_TOP_DIVERGE",
    "MACD_BOTTOM_DIVERGE",
    "MACD_TOP_DIVERGE",
    "LONG_ARRANGEMENT",
    "SHORT_ARRANGEMENT",
]
_VALID_FIELDS_SET = frozenset(_VALID_FIELDS)

_TYPE_ENFORCEMENTS = {
    "featured": frozenset(["HIST_PERCENTILE_PE", "HIST_PERCENTILE_PB", "HIST_PERCENTILE_PS"]),  # noqa: E501
    "financial": frozenset(
        [
            "ROE",
            "ROA_TTM",
            "DEBT_TO_ASSETS",
            "PROPERTY_RATIO",
            "CURRENT_RATIO",
            "QUICK_RATIO",
            "GROSS_PROFIT_RATIO",
            "NET_PROFIT_RATIO",
            "OPERATING_MARGIN_TTM",
            "NET_PROFIT_CASH_COVER_TTM",
            "REVENUE_GROWTH",
            "NET_PROFIT_GROWTH",
            "EPS_GROWTH_RATE",
            "ROE_GROWTH_RATE",
            "ROIC",
            "EBIT_TTM",
            "EBITDA",
            "EBIT_MARGIN",
            "EBITDA_MARGIN",
            "FINANCIAL_COST_RATE",
            "OPERATING_PROFIT_TTM",
            "SHAREHOLDERS_PROFIT_TTM",
            "CURRENT_ASSET_RATIO",
            "CURRENT_DEBT_RATIO",
            "EQUITY_MULTIPLIER",
            "CASH_EQUIVALENTS",
            "TOTAL_ASSET_TURNOVER",
            "FIXED_ASSET_TURNOVER",
            "INVENTORY_TURNOVER",
            "ACCOUNTS_RECEIVABLE",
            "EBIT_GROWTH_RATE",
            "OPERATING_PROFIT_GROWTH",
            "TOTAL_ASSETS_GROWTH",
            "SHAREHOLDER_PROFIT_GROWTH",
            "PROFIT_BEFORE_TAX_GROWTH",
            "ROIC_GROWTH_RATE",
            "NOCF_GROWTH_RATE",
            "NOCF_PER_SHARE_GROWTH",
            "OPERATING_REVENUE_CASH_COVER",
            "OPERATING_PROFIT_TOTAL_RATIO",
            "DILUTED_EPS",
            "NOCF_PER_SHARE",
            "NET_PROFIT",
            "REVENUE",
            "OPERATING_REVENUE_GROWTH_RATE",
        ]
    ),  # noqa: E501
    "accumulate": frozenset(
        [
            "PRICE_CHANGE_PCT",
            "AMPLITUDE",
            "AVG_VOLUME",
            "AVG_TURNOVER",
            "TURNOVER_RATIO",
            "CHANGE_5MIN",
            "CHANGE_YTD",
        ]
    ),  # noqa: E501
    "simple": frozenset(
        [
            "MARKET_CAP",
            "PE_TTM",
            "PB",
            "PRICE",
            "DIVIDEND_RATIO",
            "BASIC_EPS",
            "LISTED_DAYS",
            "PRICE_TO_52W_HIGH",
            "PRICE_TO_52W_LOW",
            "HIGH_TO_52W_HIGH",
            "LOW_TO_52W_LOW",
            "VOLUME_MULTIPLE",
            "BID_ASK_RATIO",
            "LOT_PRICE",
            "PE_ANNUAL",
            "PS_TTM",
            "PCF_TTM",
            "TOTAL_SHARE",
            "FLOAT_SHARE",
            "FLOAT_MARKET_CAP",
        ]
    ),  # noqa: E501
}

_FIELD_ZH_MAP = {
    "MACD_GOLD_CROSS": "MACD金叉",
    "MACD_GOLDEN_CROSS": "MACD金叉",
    "RSI_OVERSOLD": "RSI超卖",  # noqa: E501
    "KDJ_GOLD_CROSS": "KDJ金叉",
    "KDJ_GOLDEN_CROSS": "KDJ金叉",
    "RSI_BOTTOM_DIVERGE": "RSI底背离",  # noqa: E501
    "RSI_TOP_DIVERGE": "RSI顶背离",
    "MACD_BOTTOM_DIVERGE": "MACD底背离",
    "MACD_TOP_DIVERGE": "MACD顶背离",  # noqa: E501
    "MARKET_CAP": "市值",
    "PE_TTM": "市盈率",
    "PB": "市净率",
    "PRICE": "最新价",
    "AVG_VOLUME": "成交量",
    "AVG_TURNOVER": "成交额",
    "TURNOVER_RATIO": "换手率",
    "PRICE_CHANGE_PCT": "涨跌幅",
    "AMPLITUDE": "振幅",
    "ROE": "净资产收益率",
    "ROA_TTM": "总资产回报率",
    "DIVIDEND_RATIO": "股息率",
    "BASIC_EPS": "每股收益",
    "NET_PROFIT": "净利润",
    "REVENUE": "营收",
    "GROSS_PROFIT_RATIO": "毛利率",
    "OPERATING_MARGIN_TTM": "营业利润率",
    "OPERATING_CASH_FLOW_TTM": "经营现金流",
    "NET_PROFIT_CASH_COVER_TTM": "盈利现金覆盖率",
    "DEBT_TO_ASSETS": "资产负债率",
    "PROPERTY_RATIO": "产权比率",
    "CURRENT_RATIO": "流动比率",
    "HIST_PERCENTILE_PE": "PE历史分位",  # noqa: E501
    "HIST_PERCENTILE_PB": "PB历史分位",
    "HIST_PERCENTILE_PS": "PS历史分位",
    "REVENUE_GROWTH": "营收增长率",
    "NET_PROFIT_GROWTH": "净利润增长率",
    "EPS_GROWTH_RATE": "EPS增长率",
    "ROE_GROWTH_RATE": "ROE增长率",
    "VOLUME_MULTIPLE": "量比",
    "LISTED_DAYS": "上市天数",
    "PRICE_TO_52W_HIGH": "距52周最高价比例",
    "CUR_PRICE_TO_HIGHEST52_WEEKS_RATIO": "距52周最高价比例",  # noqa: E501
    "CUR_PRICE_TO_HIGHEST_52WEEKS_RATIO": "距52周最高价比例",
    "PRICE_TO_52W_LOW": "距52周最低价比例",
    "CUR_PRICE_TO_LOWEST52_WEEKS_RATIO": "距52周最低价比例",  # noqa: E501
    "CUR_PRICE_TO_LOWEST_52WEEKS_RATIO": "距52周最低价比例",
}

_TECH_ZH_MAP = {
    "macd_gold_cross": "MACD金叉",
    "macd_golden_cross": "MACD金叉",
    "rsi_oversold": "RSI超卖",  # noqa: E501
    "kdj_gold_cross": "KDJ金叉",
    "kdj_golden_cross": "KDJ金叉",
    "rsi_bottom_diverge": "RSI底背离",  # noqa: E501
    "rsi_top_diverge": "RSI顶背离",
    "macd_bottom_diverge": "MACD底背离",
    "macd_top_diverge": "MACD顶背离",  # noqa: E501
    "vcp_pattern": "VCP形态",
    "gap_up": "跳空高开",
    "volume_surge_3d": "连续三天放量",
    "insider_net_buy": "高管净买入",
}

_TECH_REGEX_MAP = {re.compile(r"(?i)\b" + eng.replace("_", r"[_ ]?") + r"\b"): zh for eng, zh in _TECH_ZH_MAP.items()}  # noqa: E501
_SUPPORTED_PATTERNS = frozenset(
    {
        "macd_gold_cross",
        "rsi_oversold",
        "kdj_gold_cross",
        "rsi_bottom_diverge",
        "rsi_top_diverge",
        "macd_bottom_diverge",
        "macd_top_diverge",
        "vcp_pattern",
        "gap_up",
        "volume_surge_3d",
        "insider_net_buy",
    }
)  # noqa: E501
