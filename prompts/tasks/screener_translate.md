---
id: prompt-screener-001
name: 选股 NLP → DSL 翻译
target_model: gpt-4o
input_variables:
  - nlp_query: 用户自然语言选股条件（string）
  - rag_fields_str: RAG 动态补充指标列表（string，运行时注入）
output_format: "JSON {dsl_display, markets, exclude_st, technical_patterns, filters[]}"
last_tested: 2026-07-13
eval_score: TBD
changelog: |
  2026-07-13: 初始归档。完整 Prompt 含富途字段映射、数值换算规则、大师法则、技术形态支持等，
              因含运行时变量注入（rag_fields_str），保留在 backend/services/screener_service.py 中。
---

# 选股 NLP → DSL 翻译 Prompt

> **注意**：此 Prompt 包含运行时变量注入（`{rag_fields_str}`），完整版本保留在代码中：
> `backend/services/screener_service.py` `_translate_nlp_to_dsl()` 方法内。

## 核心职责

将用户的自然语言选股条件翻译为富途 Screener API 的结构化 JSON DSL。

## 关键规则摘要

1. **金额单位**：所有金额必须为纯数字（"100亿" → 10000000000.0）
2. **百分比指标**：ROE>15% → 0.15（真实小数）
3. **财务周期**：最新单季→LATEST，中报→Q6，三季报→Q9，年报→ANNUAL
4. **大师法则**：Piotroski/Graham/Buffett 条件映射
5. **技术形态**：MACD金叉/RSI超卖等存入 `filters[]` 的 `indicator_pattern` 类型
6. **连续增长**：使用 `continuous_period` 属性，不拆多个 filter
7. **dsl_display**：中文技术形态名，≤50字

## 输出 JSON Schema

```json
{
  "dsl_display": "market:hk pe:10~20 mktcap:>10B MACD金叉",
  "markets": ["HK"],
  "exclude_st": false,
  "technical_patterns": [],
  "filters": [
    {"field": "PE_TTM", "type": "simple", "min_value": 10.0, "max_value": 20.0},
    {"field": "MARKET_CAP", "type": "simple", "term": "ANNUAL", "min_value": 10000000000.0},
    {"field": "MACD_GOLD_CROSS", "type": "indicator_pattern", "period": "K_DAY"}
  ]
}
```
