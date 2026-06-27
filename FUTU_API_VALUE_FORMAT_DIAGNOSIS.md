# 富途API数值格式问题诊断

## 🔍 发现的问题

你的筛选条件无法返回结果：
```python
[
    {'field': 'HIST_PERCENTILE_PE', 'type': 'featured', 'max': 40.0},
    {'field': 'CURRENT_RATIO', 'type': 'financial', 'term': 'ANNUAL', 'min': 200.0},
    {'field': 'DEBT_EQUITY_RATIO', 'type': 'financial', 'term': 'ANNUAL', 'max': 100.0}
]
```

## 📊 三种不同的数值格式规范

### 1. LLM Prompt 的要求（已修正前）
```
所有比率必须放大100倍输出为百分数绝对值：
- "ROE > 15%" → 15.0
- "流动比率>2" → 200.0
- "PE历史分位<40%" → 40.0
```

### 2. 测试用例的实际格式
```python
# 财务指标 (FinancialProperty) - 小数格式
{"field": "ROE", "type": "financial", "min": 0.20}  # 20%
{"field": "CURRENT_RATIO", "type": "financial", "min": 2.0}  # 比值2.0

# 特色指标 (FeaturedProperty) - 小数格式
{"field": "HIST_PERCENTILE_PE", "type": "featured", "max": 0.40}  # 40%

# 累计指标 (CumulativeProperty) - 小数格式
{"field": "TURNOVER_RATIO", "type": "accumulate", "min": 0.03}  # 3%
{"field": "PRICE_CHANGE_PCT", "type": "accumulate", "min": 0.05}  # 5%

# 简单指标 (SimpleProperty) - 混合格式？
{"field": "DIVIDEND_RATIO", "type": "simple", "min": 0.05}  # 5% (小数)
{"field": "PE_TTM", "type": "simple", "max": 20.0}  # 20倍 (原始值)
```

### 3. 富途API的实际要求（推测）

根据测试用例和代码分析：

| 字段类型 | 数值格式 | 示例 | 说明 |
|---------|---------|------|------|
| **SimpleProperty** | 原始值 | PE_TTM: 20.0 | 市盈率20倍 |
| **SimpleProperty** | 小数 | DIVIDEND_RATIO: 0.05 | 股息率5% |
| **FinancialProperty** | 小数/比值 | ROE: 0.20 | ROE 20% |
| **FinancialProperty** | 比值 | CURRENT_RATIO: 2.0 | 流动比率2.0 |
| **FeaturedProperty** | 小数 (0-1) | HIST_PERCENTILE_PE: 0.40 | PE分位40% |
| **CumulativeProperty** | 小数 | TURNOVER_RATIO: 0.03 | 换手率3% |

## ⚠️ 核心矛盾

**LLM Prompt 要求输出百分比绝对值，但测试用例和富途API期望的是小数格式！**

这导致了：
1. LLM输出: `CURRENT_RATIO min: 200.0` (表示200%)
2. 传给富途API: `200.0`
3. 富途API理解为: 流动比率 > 200 (几乎不可能满足)
4. 结果: 返回空列表 ❌

## ✅ 正确的格式应该是

```python
# Graham深度价值股的正确格式
[
    {'field': 'HIST_PERCENTILE_PE', 'type': 'featured', 'max': 0.40},  # 40%分位
    {'field': 'CURRENT_RATIO', 'type': 'financial', 'term': 'ANNUAL', 'min': 2.0},  # 流动比率>2
    {'field': 'PROPERTY_RATIO', 'type': 'financial', 'term': 'ANNUAL', 'max': 1.0}  # 产权比率<1 (即100%)
]
```

注意：
1. `HIST_PERCENTILE_PE`: 使用 0-1 小数 (0.40 = 40%)
2. `CURRENT_RATIO`: 使用原始比值 (2.0 = 流动比率2)
3. `PROPERTY_RATIO`: 使用原始比值 (1.0 = 100%)
4. 字段名应该是 `PROPERTY_RATIO`，不是 `DEBT_EQUITY_RATIO`

## 🔧 需要修复的地方

### 1. LLM Prompt (已完成)
已修正为区分不同字段类型的数值格式。

### 2. 可能需要恢复智能纠偏逻辑？

如果富途API确实期望小数格式，那么之前移除的智能纠偏可能是**错误的决定**！

需要验证：
- 富途API返回的数据是小数还是百分比？
- 如果返回小数(0.20)，前端显示时需要*100
- 如果返回百分比(20.0)，前端直接显示

### 3. 测试用例是否需要更新？

当前测试用例使用的是小数格式，这与修正后的Prompt一致 ✅

## 🎯 结论

**你的筛选条件有问题：**

❌ 错误:
```python
{'field': 'HIST_PERCENTILE_PE', 'type': 'featured', 'max': 40.0}  # 应该是 0.40
{'field': 'CURRENT_RATIO', 'type': 'financial', 'min': 200.0}  # 应该是 2.0
{'field': 'DEBT_EQUITY_RATIO', 'type': 'financial', 'max': 100.0}  # 字段名错误，应该是 PROPERTY_RATIO，值是 1.0
```

✅ 正确:
```python
{'field': 'HIST_PERCENTILE_PE', 'type': 'featured', 'max': 0.40}
{'field': 'CURRENT_RATIO', 'type': 'financial', 'term': 'ANNUAL', 'min': 2.0}
{'field': 'PROPERTY_RATIO', 'type': 'financial', 'term': 'ANNUAL', 'max': 1.0}
```

## 📝 后续行动

1. ✅ 已修正 LLM Prompt
2. ⚠️ 需要验证富途API返回的数据格式
3. ⚠️ 可能需要调整返回阶段的转换逻辑
4. ⚠️ 检查字段名映射是否正确（DEBT_EQUITY_RATIO → PROPERTY_RATIO）
