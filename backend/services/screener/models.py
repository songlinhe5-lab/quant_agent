"""选股器 Pydantic 数据模型：ScreenerFilter + ScreenerDecision"""

import difflib
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from backend.services.screener.constants import (
    _ALIAS_MAP,
    _FIELD_ZH_MAP,
    _SUPPORTED_PATTERNS,
    _TECH_REGEX_MAP,
    _TECH_ZH_MAP,
    _TYPE_ENFORCEMENTS,
    _VALID_FIELDS,
    _VALID_FIELDS_SET,
)


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
            # 探测：大模型误将"连续3天放量"当做 days 参数传入了量比或成交量
            if f.field in ["VOLUME_MULTIPLE", "AVG_VOLUME"] and f.days and f.days >= 2:
                print(
                    f"🛡️ [Screener Pydantic] 拦截到非法指令: {f.field} 被大模型附带了 days={f.days}，自动触发降级转移至 volume_surge_3d。"
                )  # noqa: E501
                has_volume_surge = True
                f.days = None  # 剥离非法的 days 参数，保留其可能的 min_value 基准线

        # 💡 强制全局剔除板块条件 (响应"不要再加板块条件"的指令)
        self.filters = [f for f in self.filters if f.type not in ("plate", "exclude_plate")]  # noqa: E501

        # 💡 终极防线：为所有"连续增长/为正"的财务指标自动补上 min_value > 0 的兜底
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
