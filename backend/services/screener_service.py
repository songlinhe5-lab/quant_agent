import asyncio
import difflib
import hashlib
import json
import os
import random
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from openai.types.chat import ChatCompletionMessageParam
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from backend.core import models
from backend.core.database import SessionLocal, engine
from backend.core.redis_client import redis_client
from backend.services.futu import futu_service
from backend.services.llm_service import llm_service
from backend.services.notification_service import notification_service

# ==========================================
# 💡 Pydantic CPU 性能优化：将验证器中庞大且高频初始化的字典、列表与正则移至全局静态内存，  # noqa: E501
# 防止在每次解析大模型生成的 DSL 过滤条件时，反复分配内存并触发垃圾回收 (GC) 导致 CPU 飙高。  # noqa: E501
# ==========================================
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


class ScreenerFilter(BaseModel):
    field: str = Field(description="富途底层字段名或枚举，如 MARKET_CAP, MACD_GOLDEN_CROSS")  # noqa: E501
    field_zh: Optional[str] = Field(default=None, description="字段的中文显示名称")
    type: str = Field(
        description="字段类型：simple, financial, accumulate, plate, exclude_plate, featured, indicator, indicator_pattern, indicator_positional, kline_shape, broker, option"
    )  # noqa: E501
    term: Optional[str] = Field(default=None, description="财务周期，如 ANNUAL, TTM")
    min_value: Optional[float] = Field(
        default=None,
        description="最小值（纯数字，百分比需转为小数如 0.05）",
        serialization_alias="min",
    )  # noqa: E501
    max_value: Optional[float] = Field(
        default=None,
        description="最大值（纯数字，百分比需转为小数如 0.05）",
        serialization_alias="max",
    )  # noqa: E501
    value: Optional[List[str]] = Field(default=None, description="用于行业板块的数组，如 ['US.BK2991']")  # noqa: E501
    period: Optional[str] = Field(default=None, description="K线周期，如 K_DAY, K_15M")
    days: Optional[int] = Field(default=None, description="累计天数")
    position: Optional[str] = Field(default=None, description="位置关系: ABOVE, BELOW, CROSS_UP, CROSS_DOWN")  # noqa: E501
    second_indicator: Optional[str] = Field(default=None, description="对比的第二个指标名称")  # noqa: E501
    intervals: Optional[List[Dict[str, float]]] = Field(default=None, description="特定指标/期权区间")  # noqa: E501
    continuous_period: Optional[int] = Field(default=None, description="连续满足条件的期数（如连续3年则为3）")  # noqa: E501
    duration: Optional[int] = Field(default=None, description="历史时间窗口长度，配合 period_average 等使用")  # noqa: E501
    period_average: Optional[bool] = Field(default=None, description="是否周期求均值")
    future_duration: Optional[int] = Field(default=None, description="未来观测期/预测窗口")  # noqa: E501
    unit: Optional[float] = Field(default=None, description="量纲/单位换算")
    lower_included: Optional[bool] = Field(default=None, description="区间下限是否包含")
    upper_included: Optional[bool] = Field(default=None, description="区间上限是否包含")

    @model_validator(mode="before")
    @classmethod
    def fuzzy_match_field(cls, data: Any) -> Any:
        if isinstance(data, dict) and "field" in data:
            field_name = str(data["field"]).upper()
            f_type = str(data.get("type", "")).lower()

            # 💡 明确的字段映射字典 (拦截大模型幻觉与常见中文名，确保前端能正确展示中文映射)  # noqa: E501
            if field_name in _ALIAS_MAP:
                field_name = _ALIAS_MAP[field_name]
                data["field"] = field_name

            # 仅对我们常用的核心基础指标进行模糊纠错，高级指标形态直接透传给底层
            if field_name not in _VALID_FIELDS_SET and f_type not in [
                "plate",
                "exclude_plate",
            ]:  # noqa: E501
                matches = difflib.get_close_matches(field_name, _VALID_FIELDS, n=1, cutoff=0.6)  # noqa: E501
                if matches:
                    print(f"🔧 [Screener] 触发模糊匹配纠错: {field_name} -> {matches[0]}")  # noqa: E501
                    data["field"] = matches[0]
                else:
                    data["field"] = field_name

            # 💡 强制类型纠偏：防范大模型将 featured 错误归类为 simple 等情况
            is_enforced = False
            # 特例：DIVIDEND_RATIO 既可以是 simple (当前股息率) 也可以是 financial (当带有连续周期时)  # noqa: E501
            if data["field"] == "DIVIDEND_RATIO" and data.get("continuous_period"):
                data["type"] = "financial"
                is_enforced = True

            if not is_enforced:
                for correct_type, fields in _TYPE_ENFORCEMENTS.items():
                    if data["field"] in fields:
                        if str(data.get("type", "")).lower() != correct_type:
                            print(
                                f"🔧 [Screener] Pydantic 触发强制类型纠偏: {data['field']} 的类型从 {data.get('type')} 被修正为 {correct_type}"
                            )  # noqa: E501
                            data["type"] = correct_type
                        break

            # 💡 智能清洗：非财务指标严格剔除无用的 term（如 ANNUAL），防止前端展示误导
            current_type = data.get("type", "")
            if current_type == "financial":
                if not data.get("term"):
                    data["term"] = "ANNUAL"
            else:
                data.pop("term", None)

            for prefix in ["min", "max"]:
                val = data.get(f"{prefix}_value")
                if val is None:
                    val = data.get(prefix)

                if val is not None:
                    try:
                        f_val = float(val)
                        data[f"{prefix}_value"] = f_val
                        data[prefix] = f_val  # 同步兜底更新原生字典
                    except (ValueError, TypeError):
                        pass
        return data

    @model_validator(mode="after")
    def populate_field_zh(self) -> "ScreenerFilter":
        if not self.field_zh:
            self.field_zh = _FIELD_ZH_MAP.get(str(self.field).upper(), str(self.field))
        return self


class ScreenerDecision(BaseModel):
    dsl_display: str = Field(description="用作前端 UI 展示的短句，例如: market:hk pe:10~20")  # noqa: E501
    markets: List[str] = Field(description="市场代码，如 ['US'], ['HK'], ['SH', 'SZ']")
    exclude_st: bool = Field(default=False, description="是否剔除 ST 股")
    technical_patterns: Optional[List[str]] = Field(
        default=[], description="技术形态，如 ['macd_gold_cross', 'rsi_oversold']"
    )  # noqa: E501
    technical_patterns_zh: Optional[List[str]] = Field(default=[], description="技术形态的中文显示名称")  # noqa: E501
    filters: List[ScreenerFilter] = Field(description="结构化的选股条件数组")
    rag_rules: Optional[List[str]] = Field(default=[], description="系统注入的RAG参考规则")  # noqa: E501

    @field_validator("dsl_display", mode="after")
    @classmethod
    def validate_dsl_display_length(cls, v: str) -> str:
        max_len = 100  # 最长100个字符
        if len(v) > max_len:
            print(f"🔧 [Screener] dsl_display 长度超出 {max_len} 字符，已自动截断。原始: {v}")  # noqa: E501
            return v[: max_len - 3] + "..." if max_len > 3 else v[:max_len]
        return v

    @field_validator("technical_patterns", mode="before")
    @classmethod
    def filter_supported_patterns(cls, v: Any) -> List[str]:
        if not isinstance(v, list):
            return []
        filtered = [p for p in v if isinstance(p, str) and p.lower() in _SUPPORTED_PATTERNS]  # noqa: E501
        if len(filtered) < len(v):
            print(f"🔧 [Screener] 优雅降级: 自动忽略不支持的技术形态 {set(v) - set(filtered)}")  # noqa: E501
        return filtered

    @model_validator(mode="after")
    def auto_correct_model_hallucinations(self) -> "ScreenerDecision":
        """终极防线：自动纠正大模型的参数错位幻觉"""

        # 💡 全市场兜底：如果大模型没有指明任何市场，强制补全三大市场
        if not self.markets:
            self.markets = ["US", "HK", "SH", "SZ"]  # , "JP", "SG", "UK"]

        # 💡 将大模型生成的模糊中国市场缩写统一展开为具体的沪深两市
        if "CN" in [m.upper() for m in self.markets] or "A" in [m.upper() for m in self.markets]:  # noqa: E501
            self.markets = [m for m in self.markets if m.upper() not in ["CN", "A"]]
            if "SH" not in self.markets:
                self.markets.append("SH")  # noqa: E701
            if "SZ" not in self.markets:
                self.markets.append("SZ")  # noqa: E701

        has_volume_surge = False
        for f in self.filters:
            # 探测：大模型误将“连续3天放量”当做 days 参数传入了量比或成交量
            if f.field in ["VOLUME_MULTIPLE", "AVG_VOLUME"] and f.days and f.days >= 2:
                print(
                    f"🛡️ [Screener Pydantic] 拦截到非法指令: {f.field} 被大模型附带了 days={f.days}，自动触发降级转移至 volume_surge_3d。"
                )  # noqa: E501
                has_volume_surge = True
                f.days = None  # 剥离非法的 days 参数，保留其可能的 min_value 基准线

        # 💡 强制全局剔除板块条件 (响应“不要再加板块条件”的指令)
        self.filters = [f for f in self.filters if f.type not in ("plate", "exclude_plate")]  # noqa: E501

        # 💡 终极防线：为所有“连续增长/为正”的财务指标自动补上 min_value > 0 的兜底
        for f in self.filters:
            if f.type == "financial" and f.continuous_period and f.continuous_period > 1 and f.min_value is None:  # noqa: E501
                f.min_value = 0.0
                f.lower_included = False

        # 💡 侦测并拦截跨 Filter 的互斥条件 (需同时考虑 field 和 term，防止不同周期的同一指标被误伤)  # noqa: E501
        field_bounds = {}
        for f in self.filters:
            bound_key = (f.field, f.term)
            if bound_key not in field_bounds:
                field_bounds[bound_key] = {"min": float("-inf"), "max": float("inf")}

            if f.min_value is not None:
                field_bounds[bound_key]["min"] = max(field_bounds[bound_key]["min"], f.min_value)  # noqa: E501
            if f.max_value is not None:
                field_bounds[bound_key]["max"] = min(field_bounds[bound_key]["max"], f.max_value)  # noqa: E501

            if field_bounds[bound_key]["min"] > field_bounds[bound_key]["max"]:
                raise ValueError(
                    f"筛选条件存在逻辑互斥冲突：{f.field_zh or f.field}({f.term or '当前'}) 的最小值 ({field_bounds[bound_key]['min']}) 大于最大值 ({field_bounds[bound_key]['max']})，无法匹配到任何标的。"
                )  # noqa: E501

        if has_volume_surge:
            if self.technical_patterns is None:
                self.technical_patterns = []
            if "volume_surge_3d" not in self.technical_patterns:
                self.technical_patterns.append("volume_surge_3d")

        # 💡 填充中文技术形态与翻译 dsl_display
        if self.technical_patterns:
            self.technical_patterns_zh = [_TECH_ZH_MAP.get(p.lower(), p) for p in self.technical_patterns]  # noqa: E501

        if self.dsl_display:
            for pattern, zh in _TECH_REGEX_MAP.items():
                # 利用预编译好的正则，确保前端看到的 DSL 中只有纯中文
                self.dsl_display = pattern.sub(zh, self.dsl_display)

        return self


class ScreenerService:
    """
    选股器后台服务
    负责转译 LLM 结构化 JSON、调用券商 API 执行过滤并执行定时订阅任务。
    """

    def __init__(self):
        self._rag_corpus = []
        self.reload_rag_corpus()

    def reload_rag_corpus(self):
        """重载本地向量数据库检索引擎 (支持热更新)"""
        # 1. 默认内置核心指标，作为文件加载失败时的兜底
        default_corpus = [
            {
                "desc": "毛利率 gross margin",
                "rule": "- 毛利率(gross_margin) -> GROSS_PROFIT_RATIO (financial)",
            },  # noqa: E501
            {
                "desc": "营业利润率 operating margin",
                "rule": "- 营业利润率(operating_margin) -> OPERATING_MARGIN_TTM (financial)",
            },  # noqa: E501
            {
                "desc": "经营现金流 operating cash flow",
                "rule": "- 经营现金流(operating_cash_flow) -> OPERATING_CASH_FLOW_TTM (financial)",
            },  # noqa: E501
            {
                "desc": "盈利现金覆盖率 cash cover",
                "rule": "- 盈利现金覆盖率(cash_cover) -> NET_PROFIT_CASH_COVER_TTM (financial)",
            },  # noqa: E501
            {
                "desc": "资产负债率 debt ratio",
                "rule": "- 资产负债率(debt_ratio) -> DEBT_TO_ASSETS (financial)",
            },  # noqa: E501
            {
                "desc": "产权比率 debt equity ratio",
                "rule": "- 产权比率(debt_equity_ratio) -> PROPERTY_RATIO (financial)",
            },  # noqa: E501
            {
                "desc": "流动比率 current ratio",
                "rule": "- 流动比率(current_ratio) -> CURRENT_RATIO (financial)",
            },  # noqa: E501
            {
                "desc": "PE历史百分位 pe percentile",
                "rule": "- PE历史百分位(pe_percentile) -> HIST_PERCENTILE_PE (featured)",
            },  # noqa: E501
            {
                "desc": "营收同比增长率 revenue growth",
                "rule": "- 营收同比增长率(revenue_growth) -> REVENUE_GROWTH (financial)",
            },  # noqa: E501
            {
                "desc": "净利润同比增长率 net profit growth",
                "rule": "- 净利润同比增长率(net_profit_growth) -> NET_PROFIT_GROWTH (financial)",
            },  # noqa: E501
            {
                "desc": "EPS同比增长率 eps growth",
                "rule": "- EPS同比增长率(eps_growth) -> EPS_GROWTH_RATE (financial)",
            },  # noqa: E501
            {
                "desc": "ROE同比增长率 roe growth",
                "rule": "- ROE同比增长率(roe_growth) -> ROE_GROWTH_RATE (financial)",
            },  # noqa: E501
            {
                "desc": "放量 企稳 量比 爆量 volume up surge stabilize",
                "rule": "- 放量/量比(volume_ratio) -> 必须映射为 VOLUME_MULTIPLE (simple)，代表当前成交量相对过去均量的倍数。例如放量要求 min_value: 1.5 或 2.0；企稳(stabilize) -> 映射为 PRICE_CHANGE_PCT (accumulate) 限制波动(如 min_value: -0.03, max_value: 0.03)",
            },  # noqa: E501
            {
                "desc": "上市天数 上市时间 次新股 listed days",
                "rule": "- 上市时间/上市天数/次新股(listed_days) -> LISTED_DAYS (simple)，注意：大模型需自行将年/月换算为绝对天数，如1年即 min_value: 365.0；不满3个月即 max_value: 90.0",
            },  # noqa: E501
            {
                "desc": "上海 A股 上证 沪市 沪股 上海证券交易所",
                "rule": '- 市场指定: 沪市/上证 -> 请严格确保最终 JSON 的 markets 数组中包含 "SH"，不要混淆为 SZ',
            },  # noqa: E501
            {
                "desc": "深圳 A股 深证 深市 深股 深圳证券交易所",
                "rule": '- 市场指定: 深市/深证 -> 请严格确保最终 JSON 的 markets 数组中包含 "SZ"，不要混淆为 SH',
            },  # noqa: E501
            {
                "desc": "A股 中国股市",
                "rule": '- 市场指定: A股/中国股市 -> 请严格确保最终 JSON 的 markets 数组中同时包含 "SH" 和 "SZ"，绝对不能写成 "CN"。',
            },  # noqa: E501
            {
                "desc": "日本 日本股市 日股 东京证券交易所",
                "rule": '- 市场指定: 日本/日股 -> 请确保 markets 数组包含 "JP"',
            },  # noqa: E501
            {
                "desc": "新加坡 新加坡股市 SGX",
                "rule": '- 市场指定: 新加坡 -> 请确保 markets 数组包含 "SG"',
            },  # noqa: E501
            {
                "desc": "英国 伦敦股市 LSE",
                "rule": '- 市场指定: 英国 -> 请确保 markets 数组包含 "UK"',
            },  # noqa: E501
            {
                "desc": "换手率 turnover rate ratio",
                "rule": "- 换手率(turnover_rate) -> 必须映射为 TURNOVER_RATIO (accumulate)，这是一个百分比指标（如 3% 输出 0.03），绝对不能错写成 AVG_TURNOVER(成交额)！",
            },  # noqa: E501
            {
                "desc": "成交额 交易额 turnover amount",
                "rule": "- 成交额/交易额(turnover) -> 必须映射为 AVG_TURNOVER (accumulate)，这是一个代表资金规模的绝对数值，绝对不能错写成 换手率(TURNOVER_RATIO)！",
            },  # noqa: E501
            {
                "desc": "创历史新高 突破52周新高 即将新高 接近最高点 price to 52w high",
                "rule": "- 创历史新高/接近52周新高(price_to_52w_high) -> 必须映射为 PRICE_TO_52W_HIGH (simple)，代表(现价-52周高)/52周高，需转换为真实小数格式。若是“即将创新高/接近新高”，建议设 min_value: -0.05, max_value: 0.0；若是“已突破新高”，建议设 min_value: 0.0",
            },  # noqa: E501
            {
                "desc": "跳空高开 高开 gap up",
                "rule": '- 跳空高开(gap_up) -> 由于底层不支持跨字段计算，请将其降级为技术形态：在最外层 technical_patterns 数组中加入 "gap_up"。',
            },  # noqa: E501
            {
                "desc": "连续放量 连续三天放量 volume surge 3 days",
                "rule": '- 连续放量/连续3天放量(continuous volume surge) -> 由于底层量比不支持时间序列，请将其降级为技术形态：在最外层 technical_patterns 数组中加入 "volume_surge_3d"。',
            },  # noqa: E501
            {
                "desc": "缩量 地量 萎缩 极度萎缩 volume shrink",
                "rule": "- 缩量/地量(volume_shrink) -> 必须映射为 VOLUME_MULTIPLE (simple)，设置 max_value: 0.5（代表当前量比仅为过去的一半及以下）。",
            },  # noqa: E501
            {
                "desc": "均线附近 长期均线 多头排列 均线上方 moving average",
                "rule": "- 均线附近/均线多头(moving_average) -> 映射为 LONG_ARRANGEMENT (kline_shape)，代表价格处于均线系统上方或多头排列企稳形态。",
            },  # noqa: E501
            {
                "desc": "业绩预增 业绩预告 盈利预喜 earnings guidance",
                "rule": "- 业绩预增/预告(earnings_guidance) -> 请映射为 NET_PROFIT_GROWTH (financial)，并将 term 设为 SURPRISE_LATEST（代表财报预测/快报），设置 min_value > 0（例如预增50%即 min_value: 0.5）。",
            },  # noqa: E501
            {
                "desc": "扭亏为盈 业绩扭亏 turnaround",
                "rule": "- 扭亏为盈(turnaround) -> 必须输出两个独立的 NET_PROFIT (financial) 条件：1. term 设为 SURPRISE_LATEST，min_value: 0.0（代表预告/快报当期盈利）；2. term 设为 ANNUAL，max_value: 0.0（代表上一年度亏损）。",
            },  # noqa: E501
            {
                "desc": "连续分红 连续派息 历史分红 continuous dividend",
                "rule": "- 连续N年分红/派息(continuous_dividend) -> 必须映射为 DIVIDEND_RATIO，且 type 必须设为 financial，term 设为 ANNUAL，min_value: 0.0，lower_included: false，continuous_period: N。⚠️注意：如果同时有“当前股息率>x%”要求，请务必分为两个独立的 filter 输出！",
            },  # noqa: E501
            {
                "desc": "短期债务 短期负债 流动负债 没有短期负债 short term debt",
                "rule": "- 短期债务/流动负债(short_term_debt) -> 映射为 CURRENT_DEBT_RATIO (financial)。若是要求“没有短期负债/无短期债务压力”，请严格限制 max_value: 0.1（代表流动负债占总负债极小），或者配合使用 QUICK_RATIO (financial) 设置 min_value: 1.0 剔除存货水分。",
            },  # noqa: E501
            {
                "desc": "行业 板块 概念 银行股 科技股 医药股 消费股 sector industry plate",
                "rule": '- 行业/板块/概念(industry/plate) -> 映射为 type: "plate"（或 "exclude_plate" 用于剔除），并将具体的行业名称（如 ["银行", "半导体", "医药", "消费"]）放入 value 数组中。注意：不需要自己猜测富途板块代码，直接填中文名称即可！',
            },  # noqa: E501
            {
                "desc": "研发投入 研发费用 R&D research",
                "rule": '- 研发投入/研发费用(R&D) -> 富途底层暂不支持直接筛选研发数据！请忽略此数值条件，但必须根据上下文语义（如“科技先锋”）转化为行业筛选：输出 field: "STOCK_PLATE", type: "plate", value: ["科技"] 等。',
            },  # noqa: E501
            {
                "desc": "高管增持 高管买入 内幕交易 净买入 insider net buy",
                "rule": '- 高管增持/净买入(insider_buy) -> 富途底层不支持，必须降级为另类数据二次过滤：请在最外层 technical_patterns 数组中加入 "insider_net_buy"。',
            },  # noqa: E501
        ]

        self._rag_corpus = []

        # 2. 尝试从本地 CSV 动态加载数百个额外指标
        import pandas as pd

        csv_path = os.path.join(os.path.dirname(__file__), "..", "data", "indicators.csv")  # noqa: E501
        if os.path.exists(csv_path):
            try:
                df = pd.read_csv(csv_path)
                if "desc" in df.columns and "rule" in df.columns:
                    for _, row in df.iterrows():
                        if pd.notna(row["desc"]) and pd.notna(row["rule"]):
                            self._rag_corpus.append(
                                {
                                    "desc": str(row["desc"]).strip(),
                                    "rule": str(row["rule"]).strip(),
                                }
                            )  # noqa: E501
                    print(f"✅ [Screener] 成功从 CSV 动态加载 {len(self._rag_corpus)} 条指标 RAG 规则库！")  # noqa: E501
            except Exception as e:
                print(f"⚠️ [Screener] 从 CSV 加载外部指标失败，使用兜底规则: {e}")

        # 3. 如果没读到任何外部数据，使用硬编码兜底
        if not self._rag_corpus:
            self._rag_corpus = default_corpus

        # 4. 初始化 Embedding 模型 (支持 OpenAI 兼容接口或本地 SentenceTransformers)
        emb_api_key = os.getenv("EMBEDDING_API_KEY") or os.getenv("OPENAI_API_KEY", "")
        if emb_api_key:
            import requests

            emb_base_url = os.getenv("EMBEDDING_BASE_URL", "https://api.openai.com/v1").rstrip("/")
            emb_model = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
            print(f"☁️ [Screener] 检测到云端 Embedding 密钥，启用 {emb_model} 模型进行向量化")  # noqa: E501

            def get_embeddings(texts):
                headers = {
                    "Authorization": f"Bearer {emb_api_key}",
                    "Content-Type": "application/json",
                }  # noqa: E501
                res = requests.post(
                    f"{emb_base_url}/embeddings",
                    headers=headers,
                    json={"input": texts, "model": emb_model},
                    timeout=30,
                )  # noqa: E501
                if res.status_code == 200:
                    return [d["embedding"] for d in res.json().get("data", [])]
                print(f"⚠️ OpenAI Embedding API 失败: {res.text}")
                return []

            self._embed_func = get_embeddings
        else:
            try:
                from sentence_transformers import SentenceTransformer

                model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
                print("💻 [Screener] 启用本地 SentenceTransformer 模型进行向量化")
                self._embed_func = lambda texts: model.encode(texts).tolist()
            except ImportError:
                print("⚠️ [Screener] 未安装 sentence_transformers 且未配置 API Key，将降级全量返回规则。")  # noqa: E501
                self._embed_func = None

        embed_func = self._embed_func
        if not embed_func:
            self._pg_enabled = False
            return {"count": len(self._rag_corpus), "warning": "missing_deps"}

        # 5. 向量化并灌入 PostgreSQL (pgvector)
        try:
            from sqlalchemy import text

            with engine.begin() as conn:
                self._pg_enabled = conn.dialect.name == "postgresql"
                if not self._pg_enabled:
                    print("⚠️ [Screener] 当前非 PostgreSQL 数据库，自动降级为全量规则兜底模式。")  # noqa: E501
                    return {"count": len(self._rag_corpus), "warning": "not_postgres"}

                # ⚠️ 极度重要：仅清理系统的公共冷启动知识库，绝对保留用户的私有规则 (user_id IS NOT NULL)  # noqa: E501
                conn.execute(text("DELETE FROM quant_screener_rules WHERE user_id IS NULL"))  # noqa: E501

                docs = [doc["desc"] for doc in self._rag_corpus]
                metadatas = [{"rule": doc["rule"]} for doc in self._rag_corpus]
                ids = [f"rule_{i}" for i in range(len(self._rag_corpus))]

                from rich.progress import track

                batch_size = 60
                batches = list(range(0, len(docs), batch_size))

                for i in track(
                    batches,
                    description="[cyan]🧠 正在向量化 RAG 规则并灌入 PostgreSQL...[/cyan]",
                ):  # noqa: E501
                    b_docs = docs[i : i + batch_size]
                    b_metas = metadatas[i : i + batch_size]
                    b_ids = ids[i : i + batch_size]

                    b_embs = embed_func(b_docs)
                    if not b_embs:
                        continue  # noqa: E701

                    for j in range(len(b_docs)):
                        # pgvector 直接接受形如 '[0.1, 0.2, ...]' 的字符串格式
                        emb_str = f"[{','.join(map(str, b_embs[j]))}]"
                        # 💡 动态提取规则类型，作为标量过滤 (Scalar Filtering) 的测试字段  # noqa: E501
                        rule_type = "financial" if "financial" in b_metas[j]["rule"] else "simple"  # noqa: E501
                        conn.execute(
                            text("""
                            INSERT INTO quant_screener_rules (id, desc_text, rule_text, rule_type, embedding)
                            VALUES (:id, :desc, :rule, :rtype, CAST(:emb AS vector))
                            ON CONFLICT (id) DO UPDATE SET
                                desc_text = EXCLUDED.desc_text,
                                rule_text = EXCLUDED.rule_text,
                                rule_type = EXCLUDED.rule_type,
                                embedding = EXCLUDED.embedding
                        """),
                            {
                                "id": b_ids[j],
                                "desc": b_docs[j],
                                "rule": b_metas[j]["rule"],
                                "rtype": rule_type,
                                "emb": emb_str,
                            },
                        )  # noqa: E501

            print(f"✅ [Screener] PostgreSQL (pgvector) 引擎就绪！共完成 {len(self._rag_corpus)} 条规则的嵌入向量化。")  # noqa: E501
            return {"count": len(self._rag_corpus)}
        except Exception as e:
            print(f"⚠️ [Screener] Postgres 向量存储初始化异常: {e}")
            self._pg_enabled = False
            return {"count": len(self._rag_corpus), "warning": "db_error"}

    async def _retrieve_relevant_fields(self, query: str, user_id: Optional[int] = None) -> str:  # noqa: E501
        """
        [RAG 动态检索基座]
        """
        embed_func = getattr(self, "_embed_func", None)
        if not getattr(self, "_pg_enabled", False) or not embed_func:
            return "\n".join([str(doc.get("rule", "")) for doc in self._rag_corpus])

        try:

            def _query_vectordb():
                q_emb = embed_func([query])
                if not q_emb:
                    return []  # noqa: E701

                from sqlalchemy import or_

                with SessionLocal() as db:
                    # ==== 💡 SQLAlchemy 混合检索 (Hybrid Search) ====
                    # pgvector 支持直接在 ORM 中调用 .cosine_distance()
                    distance_col = models.ScreenerRule.embedding.cosine_distance(q_emb[0])  # noqa: E501

                    results = (
                        db.query(models.ScreenerRule, distance_col.label("distance"))
                        # 0. 🔐 强制多租户标量过滤 (Multi-Tenant Filter): 仅检索当前用户的私有规则，以及系统的公共规则  # noqa: E501
                        .filter(
                            or_(
                                models.ScreenerRule.user_id == user_id,
                                models.ScreenerRule.user_id.is_(None),
                            )
                        )  # noqa: E501
                        # 1. 标量过滤 (Scalar Filter): 假设我们只关心 "financial" 和 "simple" 这两个大类的指标  # noqa: E501
                        .filter(models.ScreenerRule.rule_type.in_(["financial", "simple"]))  # noqa: E501
                        # 2. 向量过滤 (Vector Filter): 余弦距离阈值卡控 (必须小于 0.6)
                        .filter(distance_col < 0.6)
                        # 3. 向量排序 (Vector Sort): 按相似度从高到低 (距离从低到高) 排序  # noqa: E501
                        .order_by(distance_col.asc())
                        .limit(5)
                        .all()
                    )

                    top_rules = []
                    for rule, distance in results:
                        # 计算余弦相似度百分比：(1 - distance) * 100
                        similarity_pct = (1.0 - distance) * 100
                        top_rules.append(f"{rule.rule_text} (匹配度: {similarity_pct:.1f}%)")  # noqa: E501
                        # print(f"🎯 [Screener RAG] 召回: {rule.id} (余弦距离: {distance:.3f}, 标量类别: {rule.rule_type})")  # noqa: E501

                    return top_rules

            top_rules = await asyncio.to_thread(_query_vectordb)
            if top_rules:
                return "\n".join(top_rules)
            return "\n".join([str(doc.get("rule", "")) for doc in self._rag_corpus])
        except Exception as e:
            print(f"⚠️ [Screener RAG] 向量检索异常，已安全降级至返回全量规则兜底: {e}")
            return "\n".join([str(doc.get("rule", "")) for doc in self._rag_corpus])

    async def add_custom_rule(self, desc_text: str, rule_text: str, user_id: int) -> Dict[str, Any]:  # noqa: E501
        """用户上传并向量化私有选股规则"""
        embed_func = getattr(self, "_embed_func", None)
        if not getattr(self, "_pg_enabled", False) or not embed_func:
            return {
                "status": "error",
                "message": "向量数据库未启用，无法保存私有规则。",
            }  # noqa: E501

        import uuid

        rule_id = f"user_{user_id}_{uuid.uuid4().hex[:8]}"
        rule_type = "financial" if "financial" in rule_text else "simple"

        def _insert():
            # 1. 向量化用户上传的自然语言描述
            embs = embed_func([desc_text])
            if not embs:
                raise ValueError("Embedding 生成失败")

            with SessionLocal() as db:
                # 2. 存入数据库，强绑定 user_id 标签
                new_rule = models.ScreenerRule(
                    id=rule_id,
                    desc_text=desc_text,
                    rule_text=rule_text,
                    rule_type=rule_type,
                    user_id=user_id,
                    embedding=embs[0],
                )
                db.add(new_rule)
                db.commit()
            return rule_id

        try:
            r_id = await asyncio.to_thread(_insert)
            return {"status": "success", "id": r_id, "message": "私有规则添加成功"}
        except Exception as e:
            print(f"⚠️ [Screener] 添加私有规则失败: {e}")
            return {"status": "error", "message": str(e)}

    async def get_custom_rules(self, user_id: int) -> List[Dict[str, Any]]:
        """获取指定用户的私有规则列表"""
        if not getattr(self, "_pg_enabled", False):
            return []

        def _get():
            with SessionLocal() as db:
                rules = db.query(models.ScreenerRule).filter(models.ScreenerRule.user_id == user_id).all()  # noqa: E501
                return [
                    {
                        "id": r.id,
                        "desc": r.desc_text,
                        "rule": r.rule_text,
                        "type": r.rule_type,
                    }
                    for r in rules
                ]  # noqa: E501

        try:
            return await asyncio.to_thread(_get)
        except Exception as e:
            print(f"⚠️ [Screener] 获取私有规则失败: {e}")
            return []

    async def delete_custom_rule(self, rule_id: str, user_id: int) -> bool:
        """安全删除指定的私有规则（强依赖 user_id 鉴权防止越权删除）"""
        if not getattr(self, "_pg_enabled", False):
            return False

        def _del():
            with SessionLocal() as db:
                rule = (
                    db.query(models.ScreenerRule)
                    .filter(
                        models.ScreenerRule.id == rule_id,
                        models.ScreenerRule.user_id == user_id,
                    )
                    .first()
                )
                if rule:
                    db.delete(rule)
                    db.commit()
                    return True
                return False

        try:
            return await asyncio.to_thread(_del)
        except Exception as e:
            print(f"⚠️ [Screener] 删除私有规则失败: {e}")
            return False

    def _normalize_nlp_query(self, query: str) -> str:
        """
        对自然语言查询进行标准化处理，提高缓存命中率。
        包括转换为小写、移除标点符号、将连续空格替换为单空格。
        """
        # 1. 转换为小写
        normalized_query = query.lower()
        # 2. 移除所有非字母、数字、中文和空格的字符 (标点符号)
        # re.UNICODE 标志用于正确处理 Unicode 字符集 (如中文)
        normalized_query = re.sub(r"[^\w\s\u4e00-\u9fa5]", " ", normalized_query, flags=re.UNICODE)  # noqa: E501
        # 3. 将连续的空格替换为单个空格
        normalized_query = re.sub(r"\s+", " ", normalized_query)
        # 4. 移除首尾空格
        return normalized_query.strip()

    async def translate_nlp_to_dsl(self, nlp_query: str, user_id: Optional[int] = None) -> str:  # noqa: E501
        """调用大模型将自然语言智能转译为强类型的底层筛选 JSON"""
        # 1. ⚡ Redis 语义缓存：直接计算 MD5，若存在则实现毫秒级秒回
        normalized_nlp_query = self._normalize_nlp_query(nlp_query)
        query_hash = hashlib.md5(normalized_nlp_query.encode("utf-8")).hexdigest()
        # 💡 添加 v8 版本号：新增全市场兜底逻辑，废弃之前遗漏市场的残缺 JSON
        cache_key = f"quant:screener:nlp_cache:v8:{query_hash}"

        try:
            cached_dsl = await redis_client.get(cache_key)
            if cached_dsl:
                print(f"⚡ [Screener] NLP 语义缓存命中，直接秒回: {nlp_query} (归一化查询: {normalized_nlp_query})")  # noqa: E501
                return cached_dsl.decode("utf-8") if isinstance(cached_dsl, bytes) else str(cached_dsl)  # noqa: E501
        except Exception as e:
            print(f"⚠️ [Screener] Redis 读取 NLP 缓存失败: {e}")

        if not hasattr(self, "_nlp_locks"):
            self._nlp_locks = {}

        if cache_key not in self._nlp_locks:
            self._nlp_locks[cache_key] = asyncio.Lock()

        async with self._nlp_locks[cache_key]:
            try:
                cached_double = await redis_client.get(cache_key)
                if cached_double:
                    return cached_double.decode("utf-8") if isinstance(cached_double, bytes) else str(cached_double)  # noqa: E501
            except Exception:
                pass

            # 1. 执行 RAG 动态召回，获取与当前用户自然语言最相关的可用指标列表
            rag_fields_str = await self._retrieve_relevant_fields(nlp_query, user_id)
            # print(f"\n🧠 [Screener RAG] 分析出用户的原始意图，从知识库注入了以下映射语义:\n{rag_fields_str}\n")  # noqa: E501

            # 2. 组装终极 Prompt (高频常驻指标 + RAG 注入指标)
            prompt = f"""你是一个顶级量化研发专家。请将用户的自然语言选股条件转换为标准的 JSON 格式。

    【字段映射规则 - 严格白名单】
    ⚠️ 绝对禁止虚构字段！你必须且只能从以下列表的精确字段名中进行挑选（包括对应的 type）。遇到不支持的指标（如“营收萎缩”），必须转换为已有相近指标（如 REVENUE_GROWTH 最大值设为0），如果完全无法对应则直接忽略该条件。绝不允许自己捏造任何英文变量名！

    📌 高频核心指标（常驻）：
    - 市值(mktcap) -> MARKET_CAP (simple)
    - 市盈率(pe) -> PE_TTM (simple)
    - 市净率(pb) -> PB (simple)
    - PE历史分位 -> HIST_PERCENTILE_PE (featured)
    - PB历史分位 -> HIST_PERCENTILE_PB (featured)
    - PS历史分位 -> HIST_PERCENTILE_PS (featured)
    - 最新价(price) -> PRICE (simple)
    - 成交量(vol) -> AVG_VOLUME (accumulate)
    - 成交额(turnover) -> AVG_TURNOVER (accumulate)
    - 换手率(turnover_rate) -> TURNOVER_RATIO (accumulate)
    - 涨跌幅(change) -> PRICE_CHANGE_PCT (accumulate)
    - 振幅(amplitude) -> AMPLITUDE (accumulate)
    - 净资产收益率(roe) -> ROE (financial)
    - 资产回报率(roa) -> ROA_TTM (financial)
    - 股息率(div_yield) -> DIVIDEND_RATIO (simple)
    - 滚动股息率(div_yield_ttm) -> DIVIDEND_RATIO (simple)
    - 每股收益(eps) -> BASIC_EPS (financial)
    - 净利润(net_profit) -> NET_PROFIT (financial)
    - 营收(revenue) -> REVENUE (financial)
    - 量比/放量(volume_ratio) -> VOLUME_MULTIPLE (simple) (例如放量1.2倍即 min_value: 1.2)

    🎯 动态补充指标（RAG 根据你的意图召回的可能需要的冷门指标）：{rag_fields_str}

    【数值换算规则 - 极度重要】
    1. 所有金额单位必须计算为绝对纯数字！例如："100M" 或 "1000万" 必须输出为 10000000.0，"1亿" 必须输出为 100000000.0，"100亿" 为 10000000000.0。
    2. ⚠️ 富途底层规范 - 严格小数输入：
       - **所有比率(Ratio)、利润率(Margin)、百分位(Percentile)、ROE/ROA等百分比指标**: 必须统一输出为**真实小数格式**！例如："ROE>15%" → 0.15；"PE历史分位<40%" → 0.40；"营业利润率>10%" → 0.10。
       - **财务倍数比值指标 (如流动比率, 产权比率)**: 必须输出真实比值！例如："流动比率>2" → 2.0；"产权比率<1" → 1.0。
       - **绝对数值指标 (如市盈率, 市净率)**: 保持原始数值。例如："PE<20" → 20.0。
    3. "等于 10" 转化为 min_value: 9.5, max_value: 10.5。
    4. 财务周期："最新单季"输出 "LATEST"；"中报"输出 "Q6"；"三季报"输出 "Q9"；年报输出 "ANNUAL"。注意：富途不支持 term="TTM"，凡是要求"滚动/TTM"的指标请直接选择自带 _TTM 后缀的独立字段（如 ROA_TTM, PE_TTM），且不需要为其指定 term。

    【大师法则平替】
    - Piotroski F-Score: NET_PROFIT > 0, OPERATING_CASH_FLOW_TTM > 0, NET_PROFIT_CASH_COVER_TTM > 1.0
    - Graham 估值/债务安全: HIST_PERCENTILE_PE < 0.40, CURRENT_RATIO >= 2.0, PROPERTY_RATIO < 1.0
    - Buffett 护城河: ROE > 0.15, OPERATING_MARGIN_TTM > 0.10, PROPERTY_RATIO < 1.0

    【原生技术/K线形态支持】
    富途原生支持海量技术形态过滤，必须以对象结构存入 filters 数组中，禁止降级到 Pandas 二次过滤！
    - 具体技术指标数值过滤与获取 (type: indicator): 例如 RSI, MACD, KDJ, BOLL, EMA 等。支持 min_value / max_value。必须指定 period (如 "K_DAY")。
    - 技术形态 (type: indicator_pattern): MACD_GOLD_CROSS (MACD金叉), MACD_DEATH_CROSS (死叉), RSI_OVERSOLD (RSI超卖), RSI_OVERBOUGHT (超买), KDJ_GOLD_CROSS (KDJ金叉), BOLL_BREAK_UPPER (突破布林带上轨), RSI_BOTTOM_DIVERGE (RSI底背离), RSI_TOP_DIVERGE (RSI顶背离), MACD_BOTTOM_DIVERGE (MACD底背离), MACD_TOP_DIVERGE (MACD顶背离) 等。必须指定 period (如 "K_DAY", "K_60M")。
    - K线形态 (type: kline_shape): LONG_ARRANGEMENT (多头排列), SHORT_ARRANGEMENT (空头排列), MORNING_STAR (曙光初现), THREE_RED_SOLDIERS (红三兵) 等。必须指定 period。
    - 指标位置 (type: indicator_positional): 例如价格上穿均线，field 填 PRICE，second_indicator 填 MA，position 填 CROSS_UP，period 填 K_DAY。
    - 资金流/经纪商/期权: type 填 broker 或 option。
    - 💡 高级形态降级: 若用户要求 "VCP形态" (波动率收缩) / "跳空高开" / "连续三天放量" 等富途不支持的复杂形态，请将其写入最外层的 `technical_patterns` 字符串数组中，值为 "vcp_pattern", "gap_up", "volume_surge_3d" 等。

    【时序逻辑处理法则】
    如果用户要求“连续N年/期增长”或“连续N年/期为正/盈利”：
    1. 请不要拆分为多个独立的 filter。
    2. 必须定位到对应的 **增长率 (GROWTH_RATE)** 或本体指标，并使用 `continuous_period` 属性！
       - 例如："ROIC连续3年增长" -> {{"field": "ROIC_GROWTH_RATE", "type": "financial", "term": "ANNUAL", "min_value": 0.0, "lower_included": false, "continuous_period": 3}}
       - 例如："连续5年持续盈利" -> {{"field": "NET_PROFIT", "type": "financial", "term": "ANNUAL", "min_value": 0.0, "lower_included": false, "continuous_period": 5}}
       - 例如："连续5年分红" -> {{"field": "DIVIDEND_RATIO", "type": "financial", "term": "ANNUAL", "min_value": 0.0, "lower_included": false, "continuous_period": 5}}

    如果用户要求某指标的长期均值 (如“过去5年平均ROE>20%”)：
    使用 `period_average` (布尔值) 与 `duration` (期数) 组合。
       - 例如："近5年平均ROE>20%" -> {{"field": "ROE", "type": "financial", "term": "ANNUAL", "min_value": 0.20, "period_average": true, "duration": 5}}

    请确保 `dsl_display` 字段非常简洁，使用代码风格概括。⚠️ 注意：dsl_display 中的技术形态（如 RSI底背离、MACD金叉等）以及属性（如 放量、量比等）请务必直接使用**中文**展示，不要使用英文枚举名！例如："US 市值>100亿 PE<20 RSI底背离 放量>1.2"，字数尽量控制在 50 字以内。
    请输出如下 JSON 结构（不要使用代码 标记）：
    {{
      "dsl_display": "market:hk pe:10~20 mktcap:>10B MACD金叉",
      "markets": ["HK"],
      "exclude_st": false,
      "technical_patterns": [],
      "filters": [
         {{"field": "PE_TTM", "type": "simple", "min_value": 10.0, "max_value": 20.0}},
         {{"field": "MARKET_CAP", "type": "simple", "term": "ANNUAL", "min_value": 10000000000.0}},
         {{"field": "MACD_GOLD_CROSS", "type": "indicator_pattern", "period": "K_DAY"}}
      ]
    }}"""  # noqa: E501
            messages: List[ChatCompletionMessageParam] = [
                {"role": "system", "content": prompt},
                {"role": "user", "content": nlp_query},
            ]

            max_retries = 2
            result_dsl = ""
            decision = None

            try:
                for attempt in range(max_retries + 1):
                    resp = await llm_service.get_client().chat.completions.create(
                        model=llm_service.get_model(),
                        temperature=0.0,
                        response_format={"type": "json_object"},
                        messages=messages,
                    )
                    result_dsl = resp.choices[0].message.content or ""
                    print(f"🤖 [Screener] LLM 原始输出 DSL JSON (Attempt {attempt + 1}):\n{result_dsl}")  # noqa: E501

                    if not result_dsl or not result_dsl.strip():
                        print("⚠️ [Screener] LLM 返回空内容，重试中...")
                        messages.append(
                            {
                                "role": "user",
                                "content": "你返回了空内容，请重新生成合法的 JSON。",
                            }
                        )  # noqa: E501
                        continue

                    try:
                        decision = ScreenerDecision.model_validate_json(result_dsl)
                        print("✅ [Screener] LLM 输出通过 Pydantic 预验证")
                        break  # 验证成功，跳出循环
                    except ValidationError as ve:
                        print("⚠️ [Screener] LLM 输出未通过预验证，尝试自动修复...")
                        err_msgs = []
                        for err in ve.errors():
                            err_msg = f"错误位置: {err['loc']}, 类型: {err['type']}, 消息: {err.get('msg', '')}"  # noqa: E501
                            print(f"   - {err_msg}")
                            err_msgs.append(err_msg)

                        if attempt < max_retries:
                            # 将助手的不合法输出和验证报错反馈给模型进行自我修复
                            messages.append({"role": "assistant", "content": result_dsl})  # noqa: E501
                            messages.append(
                                {
                                    "role": "user",
                                    "content": "你的 JSON 输出不符合 Pydantic 校验规范，报错如下：\n"
                                    + "\n".join(err_msgs)
                                    + "\n请修正这些错误并重新输出完整的 JSON 对象。",  # noqa: E501
                                }
                            )
                        else:
                            print("❌ [Screener] 达到最大重试次数，自动修复失败")
                            # 放弃修复，后续交由兜底逻辑处理
                            decision = None

                # 如果经过重试仍然没有有效的 decision，使用兜底
                if not decision:
                    print("⚠️ [Screener] 无法生成合法 JSON，使用兜底默认值")
                    result_dsl = '{"dsl_display": "market:us mktcap:>10B pe:10~50", "markets": ["US"], "exclude_st": false, "filters": [{"field": "MARKET_CAP", "type": "simple", "term": "ANNUAL", "min_value": 1e10}, {"field": "PE_TTM", "type": "simple", "term": "TTM", "min_value": 10.0, "max_value": 50.0}]}'  # noqa: E501
                    decision = ScreenerDecision.model_validate_json(result_dsl)

                # 3. 异步缓存成功的转译结果 (自然语言的语义通常不会变，长效缓存 30 天)
                try:
                    if rag_fields_str:
                        # 截取召回内容并作为数组存入 JSON，一并写入 Redis 缓存
                        decision.rag_rules = [r.strip() for r in rag_fields_str.split("\n") if r.strip()]  # noqa: E501

                    # 💡 定制化 JSON 格式：让 RAG 规则展示为单行，其他结构保持树形
                    decision_dict = decision.model_dump(by_alias=True, exclude_none=True)  # noqa: E501
                    rag_rules_data = decision_dict.pop("rag_rules", None)

                    # 确保支持中文字符原样输出
                    result_dsl = json.dumps(decision_dict, indent=2, ensure_ascii=False)

                    if rag_rules_data is not None:
                        rag_str = json.dumps(rag_rules_data, ensure_ascii=False)  # 默认序列化为单行  # noqa: E501
                        if decision_dict:
                            # 剥除末尾的换行和右大括号，将 rag_rules 以单行属性无缝注入
                            result_dsl = result_dsl.rstrip("}\n\r ") + f',\n  "rag_rules": {rag_str}\n}}'  # noqa: E501
                        else:
                            result_dsl = f'{{\n  "rag_rules": {rag_str}\n}}'

                    # 💡 增加随机 Jitter 防雪崩 (30天 + 1~24小时抖动)
                    ttl = 2592000 + random.randint(3600, 86400)
                    await redis_client.setex(cache_key, ttl, result_dsl)
                except Exception as e:
                    print(f"⚠️ [Screener] Redis 写入 NLP 缓存失败或转译修正异常: {e}")

                return result_dsl
            except Exception as e:
                print(f"⚠️ [ScreenerService] DSL 转译失败: {e}")
                fallback = {
                    "dsl_display": "market:hk,sh,sz,us mktcap:>10B pe:10~50",
                    "markets": ["HK", "SH", "SZ", "US"],
                    "exclude_st": False,
                    "filters": [
                        {
                            "field": "MARKET_CAP",
                            "type": "simple",
                            "term": "ANNUAL",
                            "min_value": 1e10,
                        },
                        {
                            "field": "PE_TTM",
                            "type": "simple",
                            "term": "TTM",
                            "min_value": 10.0,
                            "max_value": 50.0,
                        },
                    ],  # noqa: E501
                }
                return json.dumps(fallback, indent=2, ensure_ascii=False)

    def parse_dsl_to_futu_filters(self, json_string: str):
        """将 Agent 的 JSON 转译为 Futu API 认识的 StockField 查询数组"""
        try:
            decision = ScreenerDecision.model_validate_json(json_string)
        except ValidationError as e:
            err_msgs = []
            # 💡 打印原始 Pydantic 错误详情到日志，方便调试
            print("❌ [Screener] Pydantic 验证失败详情:")
            for err in e.errors():
                print(f"   - 位置: {err['loc']}, 类型: {err['type']}, 消息: {err.get('msg', '')}")  # noqa: E501
                if "ctx" in err:
                    print(f"     上下文: {err['ctx']}")

            for err in e.errors():
                loc_list = list(err["loc"])
                human_loc = "->".join(map(str, loc_list))

                # 💡 将晦涩的 Pydantic 路径翻译为自然语言
                if len(loc_list) >= 3 and loc_list[0] == "filters":
                    idx = int(loc_list[1]) + 1
                    field_key = str(loc_list[2])
                    field_zh = {
                        "field": "筛选指标",
                        "type": "数据类型",
                        "term": "财报周期",
                        "min_value": "最小值",
                        "max_value": "最大值",
                    }.get(field_key, field_key)
                    human_loc = f"第 {idx} 个条件的「{field_zh}」"
                elif len(loc_list) == 1:
                    human_loc = {
                        "markets": "「交易市场」",
                        "exclude_st": "「剔除ST选项」",
                    }.get(str(loc_list[0]), str(loc_list[0]))

                err_msgs.append(f"{human_loc}类型或格式不匹配")

            raise ValueError(f"AI 生成的筛选条件越界: {', '.join(err_msgs)}。请尝试使用主流的量化财务指标。")  # noqa: E501
        except Exception as e:
            raise ValueError(f"大模型输出结构异常: {e}")

        futu_filters = []
        for f in decision.filters:
            # 💡 极简序列化：通过 by_alias 自动将 min_value 转为 min，并通过 exclude_none 剔除无用的空值  # noqa: E501
            cond = f.model_dump(by_alias=True, exclude_none=True)
            if cond.get("type") != "financial":
                cond.pop("term", None)

            # 💡 剔除附加给前端展示的中文名，防止污染发往富途底层的请求参数引发报错
            cond.pop("field_zh", None)

            # 💡 还原对底层 Futu 的真实字段名
            if cond.get("field") == "VOLUME_MULTIPLE":
                cond["field"] = "VOLUME_RATIO"

            futu_filters.append(cond)

        post_filters = {
            "exclude_st": decision.exclude_st,
            "technical_patterns": decision.technical_patterns or [],
        }

        return decision.markets, futu_filters, post_filters

    async def apply_technical_pattern_filtering(
        self, final_data: List[Dict[str, Any]], tech_patterns: List[str]
    ) -> List[Dict[str, Any]]:  # noqa: E501
        if not final_data:
            return final_data

        print(f"🔍 [Screener] 执行技术面二次流水线计算: {tech_patterns}，当前候选池 {len(final_data)} 只")  # noqa: E501
        from datetime import datetime, timezone

        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        candidates = [r["symbol"] for r in final_data]

        # 1. 进阶优化：Redis Pipeline 极速批量查询缓存
        pipe = redis_client.pipeline()
        for sym in candidates:
            pipe.get(f"quant:tech:patterns:{sym}:{today_str}")
        cache_res = await pipe.execute()

        hit_patterns = {}
        hit_values = {}
        miss_symbols = []
        for sym, cached in zip(candidates, cache_res):
            if cached:
                parsed = json.loads(cached)
                # 兼容旧版的纯数组缓存结构
                if isinstance(parsed, dict):
                    hit_patterns[sym] = parsed.get("patterns", [])
                    hit_values[sym] = parsed.get("values", {})
                else:
                    hit_patterns[sym] = parsed
                    hit_values[sym] = {}
            else:
                miss_symbols.append(sym)

        # 💡 【核心防护】：彻底解决海量数据拉取导致的 API 额度耗尽与限流问题
        if miss_symbols:
            if not tech_patterns:
                # 场景 1：用户未指定形态过滤，纯粹只是为了 UI 附加标签。直接跳过拉取，仅展示已命中缓存的！  # noqa: E501
                print(f"⚡ [Screener] 当前未指定技术形态，主动跳过 {len(miss_symbols)} 只标的的 K 线拉取。")  # noqa: E501
            else:
                # 场景 2：直接拒绝拉取大量标的历史K线，防 API 熔断及额度榨干
                print(
                    f"⚠️ [Screener] 为防止 API 限流及消耗过多历史K线额度，取消实时批量拉取 {len(miss_symbols)} 只标的的历史K线数据。"
                )  # noqa: E501

        valid_tech_data = []

        PATTERN_ZH_MAP = {
            "macd_gold_cross": "MACD金叉",
            "rsi_oversold": "RSI超卖",
            "kdj_gold_cross": "KDJ金叉",
            "rsi_bottom_diverge": "RSI底背离",
            "rsi_top_diverge": "RSI顶背离",
            "macd_bottom_diverge": "MACD底背离",
            "macd_top_diverge": "MACD顶背离",
            "vcp_pattern": "VCP形态",
            "gap_up": "跳空高开",
            "volume_surge_3d": "连续三天放量",
            "insider_net_buy": "高管净买入",
        }

        # 剥离需要交给 Finnhub 等第三方服务的另类数据形态
        pure_tech_patterns = [p for p in tech_patterns if p != "insider_net_buy"]

        for r in final_data:
            sym = r["symbol"]
            # 将计算得到的技术指标值附加到结果字典中，前端检测到新 Key 会自动渲染为新列
            if sym in hit_values and hit_values[sym]:
                r.update(hit_values[sym])

            # 将命中的形态转换为中文标签并作为新列加入
            pats = hit_patterns.get(sym, [])
            if pats:
                r["matched_patterns"] = ", ".join([str(PATTERN_ZH_MAP.get(p, p)) for p in pats])  # noqa: E501

            # 💡 纯技术面放行逻辑
            if not pure_tech_patterns or all(p in pats for p in pure_tech_patterns):
                valid_tech_data.append(r)

        # ==========================================
        # 💡 另类数据 (Alternative Data) 联邦过滤
        # ==========================================
        if "insider_net_buy" in tech_patterns and valid_tech_data:
            print(f"🕵️‍♂️ [Screener] 执行另类数据过滤: 高管净买入，当前候选池 {len(valid_tech_data)} 只")  # noqa: E501
            from datetime import datetime, timedelta

            from backend.services.finnhub_service import finnhub_service

            async def _check_insider(row_data):
                try:
                    res = await finnhub_service.get_insider_transactions(row_data["symbol"], limit=30)  # noqa: E501
                    if res.get("status") == "success" and res.get("data"):
                        txs = res.get("data", [])
                        one_month_ago = datetime.now() - timedelta(days=30)
                        net_change = sum(
                            tx.get("change", 0)
                            for tx in txs
                            if tx.get("date") and datetime.strptime(tx.get("date"), "%Y-%m-%d") >= one_month_ago  # noqa: E501
                        )
                        if net_change > 0:
                            pats = row_data.get("matched_patterns", "")
                            row_data["matched_patterns"] = (pats + ", 高管净买入").strip(", ")  # noqa: E501
                            return row_data
                except Exception:
                    pass
                return None

            tasks = [_check_insider(r) for r in valid_tech_data]
            results = await asyncio.gather(*tasks)
            valid_tech_data = [r for r in results if r is not None]

        print(f"✅ [Screener] 技术形态流水线计算完成，最终剩余 {len(valid_tech_data)} 只")  # noqa: E501
        return valid_tech_data

    async def screener_subscription_daemon(self) -> None:
        """后台任务：每天 18:00 自动执行订阅的选股条件，并通过通知渠道推送"""

        # 💡 同步 DB 操作隔离：将 SQLAlchemy 查询/提交封装为独立函数，通过 to_thread 执行，防止阻塞事件循环
        def _fetch_due_subscriptions(time_str: str):
            """线程安全：查询到达触发时间的活跃订阅"""
            with SessionLocal() as db:
                subs = (
                    db.query(models.ScreenerSubscription)
                    .filter(
                        models.ScreenerSubscription.is_active,
                        models.ScreenerSubscription.trigger_time == time_str,
                    )
                    .all()
                )
                # 序列化为轻量字典列表，避免 ORM 对象跨线程泄漏
                return [
                    {
                        "id": s.id,
                        "name": s.name,
                        "dsl": s.dsl,
                        "last_triggered_at": s.last_triggered_at,
                    }
                    for s in subs
                ]

        def _mark_triggered(sub_id: str, trigger_time):
            """线程安全：更新订阅的 last_triggered_at 防重触发"""
            with SessionLocal() as db:
                sub = db.query(models.ScreenerSubscription).filter(models.ScreenerSubscription.id == sub_id).first()
                if sub:
                    sub.last_triggered_at = trigger_time
                    db.commit()

        while True:
            try:
                now = datetime.now()
                current_time_str = now.strftime("%H:%M")

                subs_to_run = await asyncio.to_thread(_fetch_due_subscriptions, current_time_str)

                if subs_to_run:
                    print(
                        f"🚀 [Screener Daemon] {current_time_str} - 检测到 {len(subs_to_run)} 个订阅任务到达触发时间..."
                    )  # noqa: E501

                for sub in subs_to_run:
                    # 核心防重触发机制：检查上次触发是否在今天
                    if sub["last_triggered_at"] and sub["last_triggered_at"].date() == now.date():  # noqa: E501
                        print(f"🟡 [Screener Daemon] 任务 '{sub['name']}' 今日已触发过，跳过。")  # noqa: E501
                        continue

                    # 💡 分布式锁防重复执行：防止多节点并发时，同一用户的同一任务被多台机器一起执行并重复推送  # noqa: E501
                    lock_key = f"quant:lock:screener_sub:{sub['id']}:{now.strftime('%Y%m%d')}"  # noqa: E501
                    if not await redis_client.set(lock_key, "1", nx=True, ex=86400):
                        continue

                    print(f"  -> 🚀 [Screener Daemon] 开始执行订阅任务: {sub['name']}")
                    max_retries = 3
                    for attempt in range(max_retries):
                        try:
                            markets, futu_filters, post_filters = self.parse_dsl_to_futu_filters(sub["dsl"])  # noqa: E501
                            tasks = [futu_service.screen_stocks(market=m, filters=futu_filters) for m in markets]  # type: ignore  # noqa: E501
                            results = await asyncio.gather(*tasks, return_exceptions=True)  # noqa: E501

                            final_data = []
                            has_error = False
                            error_msg = ""
                            for res in results:
                                if isinstance(res, BaseException):
                                    has_error = True
                                    error_msg = str(res)
                                elif isinstance(res, dict) and res.get("status") == "success":  # noqa: E501
                                    final_data.extend(res.get("data", []))
                                elif isinstance(res, dict) and res.get("status") == "error":  # noqa: E501
                                    has_error = True
                                    error_msg = res.get("message", "Unknown error")

                            if has_error and not final_data:
                                raise ValueError(f"底层筛选 API 失败: {error_msg}")

                            # 内存二次过滤
                            if post_filters.get("exclude_st"):
                                final_data = [
                                    r
                                    for r in final_data
                                    if "ST" not in r.get("name", "").upper() and "退" not in r.get("name", "")
                                ]  # noqa: E501

                            # 内存技术面二次过滤
                            tech_patterns = post_filters.get("technical_patterns", [])  # noqa: E501
                            if final_data:
                                final_data = await self.apply_technical_pattern_filtering(final_data, tech_patterns)  # noqa: E501

                            if final_data:
                                top_10 = final_data[:10]

                                # 💡 并发拉取这 10 只股票的最新一条新闻
                                async def _fetch_latest_news(ticker):
                                    try:
                                        is_asian = (
                                            any(x in ticker.upper() for x in ["HK", "SH", "SZ"]) or ticker.isdigit()
                                        )  # noqa: E501
                                        if is_asian:
                                            from backend.services.akshare_service import (  # noqa: E501
                                                akshare_service,
                                            )

                                            res = await akshare_service.get_company_news(ticker)  # noqa: E501
                                        else:
                                            from backend.services.finnhub_service import (  # noqa: E501
                                                finnhub_service,
                                            )

                                            res = await finnhub_service.get_company_news(ticker, days_back=3)  # noqa: E501
                                        if res.get("status") == "success" and res.get("data"):  # noqa: E501
                                            return res["data"][0].get("headline", "")  # noqa: E501
                                    except Exception:
                                        pass
                                    return ""

                                news_list = await asyncio.gather(
                                    *[_fetch_latest_news(r["symbol"]) for r in top_10],
                                    return_exceptions=True,
                                )  # noqa: E501

                                # 💡 组装信息让大模型进行一句话点评
                                stock_contexts = []
                                for r, news in zip(top_10, news_list):
                                    if isinstance(news, BaseException):
                                        news = ""  # noqa: E701
                                    chg = r.get(
                                        "chg",
                                        r.get(
                                            "price_change_pct",
                                            r.get("change_rate", 0),
                                        ),
                                    )  # noqa: E501
                                    news_str = f", 最新动态: {news}" if news else ""
                                    stock_contexts.append(
                                        f"- {r.get('name', r['symbol'])} ({r['symbol']}): 今日涨跌 {chg:.2f}%{news_str}"
                                    )  # noqa: E501

                                stocks_info_str = "\n".join(stock_contexts)
                                llm_comments = ""

                                try:
                                    prompt = f"你是华尔街顶级量化分析师。以下是系统刚筛选出的 {len(top_10)} 只金股及最新盘面动态：\n\n{stocks_info_str}\n\n请你用毒舌、专业的金融黑话，为每只股票写一句精简的短评（结合其涨跌幅和最新新闻，判断其动能或风险）。\n格式要求严格如下：\n- **[股票名称]**: [一句话短评]"  # noqa: E501
                                    resp = await llm_service.get_client().chat.completions.create(  # noqa: E501
                                        model=llm_service.get_model(),
                                        temperature=0.7,
                                        messages=[{"role": "user", "content": prompt}],  # noqa: E501
                                    )
                                    content = resp.choices[0].message.content
                                    llm_comments = content.strip() if content else ""  # noqa: E501
                                    llm_comments = re.sub(r"^```[a-zA-Z]*\n", "", llm_comments)  # noqa: E501
                                    llm_comments = re.sub(r"\n```$", "", llm_comments).strip()  # noqa: E501
                                except Exception as e:
                                    print(f"⚠️ [Screener Daemon] LLM 点评失败: {e}")
                                    llm_comments = "\n".join(
                                        [f"- **{r.get('name', r['symbol'])}**: 暂无点评 (LLM 解析失败)" for r in top_10]
                                    )  # noqa: E501

                                tech_str = f"\n\n⚙️ 命中技术形态: {', '.join(tech_patterns)}" if tech_patterns else ""  # noqa: E501
                                msg = f"🔔 [智能选股日报] {sub['name']}\n\nAgent 根据您的订阅条件，在全市场扫盘发现 {len(final_data)} 只符合条件的标的。{tech_str}\n\n🔥 核心金股 Top 10 点评:\n{llm_comments}"  # noqa: E501
                                await notification_service.send_alert(msg)
                            else:
                                # 没有任何结果，也推送报告
                                msg = f"🔔 [智能选股日报] {sub['name']}\n\nAgent 扫盘完成，今日全市场未匹配到符合您严苛条件的标的。"  # noqa: E501
                                await notification_service.send_alert(msg)

                            # 💡 成功发送或无结果后，更新数据库中的 last_triggered_at 时间戳，防死循环  # noqa: E501
                            await asyncio.to_thread(_mark_triggered, sub["id"], now)
                            print(f"  -> ✅ [Screener Daemon] 任务 '{sub['name']}' 执行并推送完毕，已更新触发时间。")  # noqa: E501
                            break  # 退出重试循环

                        except Exception as inner_e:
                            print(f"⚠️ [Screener Daemon] 执行子任务 {sub['name']} 失败 (第 {attempt + 1} 次): {inner_e}")  # noqa: E501
                            if attempt < max_retries - 1:
                                await asyncio.sleep(10 * (attempt + 1))  # 失败后线性退避休眠再试  # noqa: E501
                            else:
                                # 彻底失败，推送到包括钉钉在内的通知渠道并更时间戳防死循环  # noqa: E501
                                await asyncio.to_thread(_mark_triggered, sub["id"], now)
                                err_msg = f"🚨 [智能选股报错] 任务 '{sub['name']}' 连续 {max_retries} 次执行失败！\n\n异常详情: {inner_e}"  # noqa: E501
                                asyncio.create_task(notification_service.send_alert(err_msg))

                    await asyncio.sleep(2)  # 错峰请求

                # 💡 及时释放大对象：ORM 模型列表与多市场的海量 JSON 返回值
                subs_to_run = None
                results = None
                final_data = None

                # 每 60 秒轮询一次，确保不会错过任何分钟级别的触发
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"⚠️ [Screener Daemon] 订阅任务守护进程异常: {e}")
                await asyncio.sleep(30)

    async def daily_market_summary_daemon(self) -> None:
        """后台任务：每天 16:00 自动盘点全市场最强概念股并推送到 Telegram/通知渠道"""
        while True:
            try:
                now = datetime.now()
                # 每天 16:00 准时执行 (若在海外服务器部署，请自行根据 UTC 偏置调整小时数)  # noqa: E501
                if now.hour == 16 and now.minute == 0:
                    # 💡 分布式锁：选出唯一 Leader 节点执行，防止多服务器重复推送报告
                    lock_key = f"quant:lock:daily_summary:{now.strftime('%Y%m%d')}"
                    if not await redis_client.set(lock_key, "1", nx=True, ex=3600):
                        await asyncio.sleep(60)
                        continue

                    print("🚀 [Screener Daemon] 开始执行每日 16:00 最强概念股盘点...")

                    # 1. 设定底层扫盘策略: 涨幅>5%, 成交额>1亿, 换手率>2%
                    json_payload = json.dumps(
                        {
                            "dsl_display": "market:hk,sh,sz,us exclude_st:true change:>5 turnover:>100M turnover_rate:>2",  # noqa: E501
                            "markets": ["HK", "SH", "SZ", "US"],
                            "exclude_st": True,
                            "filters": [
                                {
                                    "field": "PRICE_CHANGE_PCT",
                                    "type": "accumulate",
                                    "min_value": 0.05,
                                },  # noqa: E501
                                {
                                    "field": "AVG_TURNOVER",
                                    "type": "accumulate",
                                    "min_value": 100000000.0,
                                },  # noqa: E501
                                {
                                    "field": "TURNOVER_RATIO",
                                    "type": "accumulate",
                                    "min_value": 0.02,
                                },  # noqa: E501
                            ],
                        }
                    )
                    markets, futu_filters, post_filters = self.parse_dsl_to_futu_filters(json_payload)  # noqa: E501

                    tasks = [futu_service.screen_stocks(market=m, filters=futu_filters) for m in markets]  # type: ignore  # noqa: E501
                    results = await asyncio.gather(*tasks, return_exceptions=True)

                    final_data = []
                    for res in results:
                        if isinstance(res, dict) and res.get("status") == "success":
                            final_data.extend(res.get("data", []))

                    # 内存二次过滤
                    if post_filters.get("exclude_st"):
                        final_data = [
                            r
                            for r in final_data
                            if "ST" not in r.get("name", "").upper() and "退" not in r.get("name", "")
                        ]  # noqa: E501

                    if final_data:
                        # 排序：按涨跌幅降序
                        final_data.sort(
                            key=lambda x: x.get("change_rate", 0) if x.get("change_rate") is not None else 0,
                            reverse=True,
                        )  # noqa: E501
                        top_stocks = final_data[:20]  # 截取前 20 只绝对龙头

                        # 2. 调用大模型进行主线概念总结

                        stocks_info = "\n".join(
                            [
                                f"- {r.get('name', '')} ({r.get('symbol', '')}): 涨跌幅 {r.get('change_rate', 0):.2f}%, 换手率 {r.get('turnover_rate', 0):.2f}%, 成交额 {r.get('turnover', 0) / 1e8:.2f}亿"
                                for r in top_stocks
                            ]
                        )  # noqa: E501

                        prompt = f"""你是一个顶尖的华尔街量化分析师。以下是今天全市场（A股、港股、美股）扫描出的量价齐升、资金抢筹的最强标的 Top 20：\n\n{stocks_info}\n\n请你根据这些股票的名称、行业属性和近期的宏观/科技趋势，用毒舌且专业的风格，写一份简短的《16:00 强势股复盘报告》。\n要求：\n1. 提取出 1-2 个今天最核心的炒作概念/主线。\n2. 点评几个最具代表性的龙头股。\n3. 提示追高风险或资金接盘情况。\n4. 格式使用清晰的 Markdown，字数控制在 400 字以内。"""  # noqa: E501

                        try:
                            resp = await llm_service.get_client().chat.completions.create(
                                model=llm_service.get_model(),
                                temperature=0.7,
                                messages=[
                                    {
                                        "role": "system",
                                        "content": "你是一个资深量化交易主脑。",
                                    },
                                    {"role": "user", "content": prompt},
                                ],
                            )  # noqa: E501
                            content = resp.choices[0].message.content
                            report = content.strip() if content else ""

                            # 剔除可能包含的大模型包裹标记 (如 ```... ```)
                            report = re.sub(r"^```[a-zA-Z]*\n", "", report)
                            report = re.sub(r"\n```$", "", report)
                            report = report.strip()

                            # 3. 通过 Notification Tool 广发放通知
                            await notification_service.send_alert(f"🔥 [Quant Agent] 每日强势股主线复盘\n\n{report}")  # noqa: E501
                        except Exception as e:
                            print(f"⚠️ [Screener Daemon] LLM 总结失败: {e}")

                    # 💡 及时释放大对象：全市场扫盘的 JSON 结果体积巨大，防止在休眠期内驻留内存  # noqa: E501
                    results = None
                    final_data = None
                    top_stocks = None

                    await asyncio.sleep(60)
                else:
                    await asyncio.sleep(30)
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"⚠️ [Screener Daemon] 强势股盘点任务异常: {e}")
                await asyncio.sleep(30)

    async def clean_obsolete_knowledge_base_daemon(self) -> None:
        """后台任务：每天凌晨 00:00 自动清理 PostgreSQL 中超过 90 天的陈旧网页向量数据"""  # noqa: E501
        while True:
            try:
                now = datetime.now()
                # 每天凌晨 00:00 准时执行
                if now.hour == 0 and now.minute == 0:
                    # 💡 分布式锁：选出唯一 Leader 节点执行清理，防止数据库并发死锁
                    lock_key = f"quant:lock:clean_kb:{now.strftime('%Y%m%d')}"
                    if not await redis_client.set(lock_key, "1", nx=True, ex=3600):
                        await asyncio.sleep(60)
                        continue

                    print("🧹 [Knowledge Base Daemon] 开始清理 PG 知识库中超过 90 天的陈旧网页向量...")  # noqa: E501

                    def _do_clean():
                        import time

                        from sqlalchemy import text

                        try:
                            cutoff_ts = int(time.time()) - (90 * 24 * 3600)
                            with engine.begin() as conn:
                                # 检查表是否存在以防首次启动时报错
                                table_exists = conn.execute(
                                    text(
                                        "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'webpage_knowledge_base')"
                                    )
                                ).scalar()  # noqa: E501
                                if table_exists:
                                    res = conn.execute(
                                        text("DELETE FROM webpage_knowledge_base WHERE timestamp < :cutoff"),
                                        {"cutoff": cutoff_ts},
                                    )  # noqa: E501
                                    print(
                                        f"✅ [Knowledge Base Daemon] 清理成功！共删除 {res.rowcount} 个陈旧网页碎片块。"
                                    )  # noqa: E501
                        except Exception as e:
                            print(f"⚠️ [Knowledge Base Daemon] 知识库清理失败: {e}")

                    await asyncio.to_thread(_do_clean)
                    await asyncio.sleep(60)  # 错峰，确保同一分钟内不重复触发
                else:
                    await asyncio.sleep(30)
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"⚠️ [Knowledge Base Daemon] 清理任务异常: {e}")
                await asyncio.sleep(30)

    async def summarize_results(self, stocks: List[Dict[str, Any]]) -> str:
        """一键总结前端传入的选股器结果"""
        if not stocks:
            return "暂无选股结果可供分析。"

        # 仅取前 10 只龙头股进行分析，防范大模型 Token 溢出并控制生成速度
        top_stocks = stocks[:10]

        # 💡 并发拉取这 10 只股票的最新一条新闻
        async def _fetch_latest_news(ticker):
            try:
                is_asian = any(x in ticker.upper() for x in ["HK", "SH", "SZ"]) or ticker.isdigit()  # noqa: E501
                if is_asian:
                    from backend.services.akshare_service import akshare_service

                    res = await akshare_service.get_company_news(ticker)
                else:
                    from backend.services.finnhub_service import finnhub_service

                    res = await finnhub_service.get_company_news(ticker, days_back=3)
                if res.get("status") == "success" and res.get("data"):
                    return res["data"][0].get("headline", "")
            except Exception:
                pass
            return ""

        news_list = await asyncio.gather(
            *[_fetch_latest_news(r["symbol"]) for r in top_stocks],
            return_exceptions=True,
        )  # noqa: E501

        stock_contexts = []
        for r, news in zip(top_stocks, news_list):
            if isinstance(news, BaseException):
                news = ""  # noqa: E701
            chg = r.get("chg", r.get("price_change_pct", r.get("change_rate", 0)))
            news_str = f", 最新动态: {news}" if news else ""
            stock_contexts.append(f"- {r.get('name', r['symbol'])} ({r['symbol']}): 涨跌幅 {chg:.2f}%{news_str}")  # noqa: E501

        stocks_info_str = "\n".join(stock_contexts)

        prompt = f"你是华尔街顶级量化分析师。以下是用户刚刚使用选股器筛选出的前 {len(top_stocks)} 只标的及最新盘面动态：\n\n{stocks_info_str}\n\n请你用毒舌、专业的金融黑话，写一份简短的《AI 选股结果一键洞察》。\n要求：\n1. 提炼出这批股票共有的 1-2 个核心炒作概念或主线属性。\n2. 点评最具代表性的 2-3 只龙头股。\n3. 提示目前追高或介入的系统性风险。\n4. 格式使用清晰的 Markdown，字数控制在 400 字以内。"  # noqa: E501

        try:
            resp = await llm_service.get_client().chat.completions.create(
                model=llm_service.get_model(),
                temperature=0.7,
                messages=[{"role": "user", "content": prompt}],
            )  # noqa: E501
            content = resp.choices[0].message.content
            report = content.strip() if content else "暂无分析结果"
            return re.sub(r"\n```$", "", re.sub(r"^```[a-zA-Z]*\n", "", report)).strip()
        except Exception as e:
            print(f"⚠️ [Screener Service] LLM 总结失败: {e}")
            return f"生成分析报告失败: {e}"


# 导出全局单例
screener_service = ScreenerService()
