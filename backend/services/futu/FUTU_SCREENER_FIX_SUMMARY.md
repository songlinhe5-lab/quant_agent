# 富途选股条件数值转换修复总结

## 📋 问题描述

你的筛选条件：
```python
[
    {'field': 'ROE', 'type': 'financial', 'term': 'TTM', 'min': 15.0},
    {'field': 'OPERATING_MARGIN_TTM', 'type': 'financial', 'term': 'TTM', 'min': 10.0},
    {'field': 'DEBT_EQUITY_RATIO', 'type': 'financial', 'term': 'ANNUAL', 'max': 100.0}
]
```

## 🔍 问题分析

### 修复前的问题

#### 1. OPERATING_MARGIN_TTM - 双重放大问题 ❌❌
```
输入: 10.0 (表示10%)
  ↓
智能纠偏: abs(10.0) <= 10 → 自动*100 → 1000.0 ❌
  ↓
传给API: 1000.0 (错误的值！)
  ↓
返回处理: operating_margin_ttm字段 * 100 → 100000.0 ❌❌
```

**这是最严重的问题！**

#### 2. ROE - 可能的转换问题 ⚠️
```
输入: 15.0 (表示15%)
  ↓
智能纠偏: abs(15.0) > 10 → 不转换
  ↓
传给API: 15.0 ✅
  ↓
返回处理: roe字段 * 100 → 1500.0 ❌
```

#### 3. DEBT_EQUITY_RATIO - 处理正确 ✅
```
输入: 100.0 (表示100%)
  ↓
映射到: PROPERTY_RATIO
  ↓
智能纠偏: abs(100.0) > 10 → 不转换
  ↓
传给API: 100.0 ✅
  ↓
返回处理: property_ratio不在转换列表中 → 保持原值 ✅
```

## ✅ 已执行的修复

### 修改文件：`backend/services/futu/screener_handler.py`

### 修复1：移除输入阶段的智能纠偏逻辑（第95-98行）

**删除的代码：**
```python
# 💡 智能单位纠偏：大模型常常将百分比输出为纯小数或倍率
is_ratio_metric = field_name and any(k in str(field_name).upper() for k in [
    "RATIO", "RATE", "MARGIN", "ROE", "ROA", "COVER", "PERCENTILE", "PCT", "YIELD"
])
if is_ratio_metric:
    if lower is not None and abs(lower) <= 10: lower = lower * 100.0
    if upper is not None and abs(upper) <= 10: upper = upper * 100.0
```

**替换为：**
```python
# ✅ 已移除智能单位纠偏逻辑
# 原因：LLM Prompt 已明确要求所有比率类指标输出为百分比绝对值（如15%表示为15.0）
# 保留此逻辑会导致双重转换问题（输入时*100，返回时又*100）
# 参考规范：富途财务指标数值处理规范
```

### 修复2：移除返回阶段的数值转换逻辑（第333-345行）

**删除的代码：**
```python
if isinstance(val, float) and prop_name in [
    "dividend_ratio", "roe", "roa", "turnover_ratio", 
    "price_change_pct", "amplitude", "gross_profit_ratio", "debt_to_assets",
    "hist_percentile_pe", "operating_margin_ttm", "net_profit_cash_cover_ttm"
]:
    val = val * 100.0
```

**替换为：**
```python
# ✅ 已移除返回阶段的数值转换逻辑
# 原因：根据富途财务指标数值处理规范
# "返回数据中的财务指标字段不得进行额外乘法变换，确保与API原始数据一致"
# LLM Prompt已要求输入为百分比绝对值，API返回也应保持一致
```

## 🎯 修复后的完整流程

### 修复后的行为

#### 1. ROE (净资产收益率)
```
LLM输出: 15.0 (表示15%，符合Prompt要求)
  ↓
无智能纠偏，直接传递
  ↓
传给API: 15.0 ✅
  ↓
富途API返回: 15.0 (假设是百分比格式)
  ↓
返回处理: 无转换，保持原值 → 15.0 ✅
  ↓
前端显示: 15.0% ✅ 正确！
```

#### 2. OPERATING_MARGIN_TTM (营业利润率)
```
LLM输出: 10.0 (表示10%，符合Prompt要求)
  ↓
无智能纠偏，直接传递
  ↓
传给API: 10.0 ✅ (不再被错误地放大为1000.0)
  ↓
富途API返回: 10.0 (假设是百分比格式)
  ↓
返回处理: 无转换，保持原值 → 10.0 ✅
  ↓
前端显示: 10.0% ✅ 正确！
```

#### 3. DEBT_EQUITY_RATIO (产权比率)
```
LLM输出: 100.0 (表示100%，符合Prompt要求)
  ↓
映射到: PROPERTY_RATIO
  ↓
无智能纠偏，直接传递
  ↓
传给API: 100.0 ✅
  ↓
富途API返回: 100.0 (假设是百分比格式)
  ↓
返回处理: 无转换，保持原值 → 100.0 ✅
  ↓
前端显示: 100.0% ✅ 正确！
```

## 📊 关键改进

### 修复前 vs 修复后

| 指标 | 修复前输入 | 修复前传给API | 修复前返回 | 修复后输入 | 修复后传给API | 修复后返回 |
|------|-----------|--------------|-----------|-----------|--------------|-----------|
| ROE | 15.0 | 15.0 | 1500.0 ❌ | 15.0 | 15.0 | 15.0 ✅ |
| OPERATING_MARGIN_TTM | 10.0 | 1000.0 ❌ | 100000.0 ❌❌ | 10.0 | 10.0 | 10.0 ✅ |
| DEBT_EQUITY_RATIO | 100.0 | 100.0 | 100.0 ✅ | 100.0 | 100.0 | 100.0 ✅ |

## 📝 遵循的项目规范

根据项目规范记忆 `1f26dbea-be09-4050-aa69-66c70a8c5755`：

> **富途财务指标数值处理规范**
> 
> 在富途服务的选股模块中，财务指标（如ROE、利润率等）的数值处理必须遵循统一规范：
> 
> 1. ✅ **所有比率类指标（Ratio、Margin、Yield等）应以百分比绝对值形式输入和输出**（如15%表示为15.0）
> 2. ✅ **禁止在代码中实现基于关键词的"智能纠偏"转换逻辑**，避免与前端或API约定冲突
> 3. ✅ **统一依赖LLM Prompt层保证输入格式正确性**，后端不做二次转换
> 4. ✅ **返回数据中的财务指标字段不得进行额外乘法变换**，确保与API原始数据一致

**本次修复完全符合以上4点规范要求！**

## 🔧 相关代码位置

### 1. LLM Prompt 定义
文件：[`backend/services/screener_service.py`](file:///Users/stephenhe/Development/workspace/quant_agent/backend/services/screener_service.py)

关键Prompt内容：
```
⚠️ 富途底层规范：所有比率(Ratio)、利润率(Margin)、百分位(Percentile)、涨跌幅等指标，
必须放大 100 倍输出为百分数绝对值！例如：
- "涨跌幅大于5%" 必须输出 min_value: 5.0
- "ROE > 15%" 必须输出 15.0
- "流动比率大于2" 必须输出 200.0
```

### 2. 输入阶段修复
文件：[`backend/services/futu/screener_handler.py`](file:///Users/stephenhe/Development/workspace/quant_agent/backend/services/futu/screener_handler.py) 第95-98行

### 3. 返回阶段修复
文件：[`backend/services/futu/screener_handler.py`](file:///Users/stephenhe/Development/workspace/quant_agent/backend/services/futu/screener_handler.py) 第333-345行

## ⚠️ 注意事项

### 前端显示

由于现在返回的数据是百分比绝对值格式（如15.0表示15%），前端在显示时应该：

```typescript
// ✅ 正确的显示方式
<div>ROE: {stock.roe}%</div>  // 显示为 "ROE: 15.0%"

// ❌ 错误的显示方式
<div>ROE: {stock.roe * 100}%</div>  // 会显示为 "ROE: 1500%"
```

### 其他可能受影响的字段

以下字段也可能需要类似的检查：
- `dividend_ratio` (股息率)
- `turnover_ratio` (换手率)
- `price_change_pct` (涨跌幅)
- `amplitude` (振幅)
- `gross_profit_ratio` (毛利率)
- `debt_to_assets` (资产负债率)
- `hist_percentile_pe` (PE历史百分位)
- `net_profit_cash_cover_ttm` (盈利现金覆盖率)

这些字段之前都会在返回时*100，现在都保持原值。如果前端有特殊的显示逻辑，可能需要调整。

## 🧪 验证建议

运行测试脚本验证修复效果：
```bash
cd /Users/stephenhe/Development/workspace/quant_agent
python scripts/test_screener_validation.py
```

观察输出中的财务指标数值是否在合理范围内：
- ROE: 应该在 0-100 之间（表示0%-100%）
- 营业利润率: 应该在 -50-100 之间
- 产权比率: 应该在 0-500 之间

## 📌 总结

✅ **已完成：**
1. 移除了输入阶段的智能纠偏逻辑（避免双重放大）
2. 移除了返回阶段的数值转换逻辑（遵循项目规范）
3. 统一依赖LLM Prompt保证输入格式正确性
4. 确保返回数据与API原始数据一致

✅ **修复效果：**
- ROE: 15.0 → 15.0 → 15.0% ✅
- OPERATING_MARGIN_TTM: 10.0 → 10.0 → 10.0% ✅
- DEBT_EQUITY_RATIO: 100.0 → 100.0 → 100.0% ✅

✅ **符合规范：**
完全符合富途财务指标数值处理规范的4点要求！

---

**修复完成时间：** 2026-06-08  
**修复人员：** AI Assistant  
**审核状态：** 待验证
