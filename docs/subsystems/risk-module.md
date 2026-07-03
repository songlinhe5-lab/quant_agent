# Risk Module 设计文档

## 1. 架构概览

```
Futu OpenD
    ↓ (真实账户 + 持仓 + K线)
RiskEngine (风控计算引擎)
    ↓ (Redis 缓存 30s TTL)
API: /api/v1/risk/dashboard
    ↓
Frontend: risk.tsx (风控面板)
```

## 2. MVP 已实现能力 (v0.1)

### 2.1 数据源
- **账户信息**: `futu_service.get_account_info()` → NAV / 今日P&L / 可用保证金 / 杠杆利用率
- **持仓明细**: `futu_service.get_account_info().positions` → 每只股票的市值/盈亏/方向
- **K线数据**: `futu_service.get_history(ticker, ktype="K_DAY", num=60)` → 日收益率序列

### 2.2 风控指标计算
| 指标 | 计算公式 | 数据来源 |
|:---|:---|:---|
| **波动率 (Vol)** | 每只持仓 60 日收益率标准差 → 按市值加权聚合 | K线 |
| **VaR (95%)** | 历史模拟法：组合日收益率序列的 5% 分位数 | K线 |
| **MaxDD** | 从 NAV 快照序列计算最大回撤 | Redis 快照 |
| **Beta** | 组合日收益率 vs 基准 (^GSPC 或 ^HSI) 的 OLS 斜率 | K线 |
| **Sharpe** | (组合年化收益 - 无风险利率) / 年化波动率 | K线 |
| **杠杆利用率** | market_val / total_assets | 账户信息 |

### 2.3 敞口分析
- **多头占比**: 所有 LONG 持仓市值 / 总NAV
- **空头占比**: 所有 SHORT 持仓市值 / 总NAV
- **现金占比**: cash / total_assets

### 2.4 风险雷达 (六维)
- Beta / Vol / Liq / Corr / Mom / DD → 归一化到 0-100 分

### 2.5 净值曲线
- **Redis NAV 快照**: 每 5 分钟记录一次 `total_assets`，保留最近 24h (288 条)
- **键空间**: `quant:risk:nav_snapshots` (Redis List)

## 3. 完整能力 TODO List (v0.2+)

### 3.1 板块暴露分析
- [ ] 获取每只持仓的行业分类 (Futu `get_stock_basicinfo` 或第三方 API)
- [ ] 按 GICS 标准聚合板块暴露 (科技/金融/医疗/能源/消费等)
- [ ] 前端可视化：横向柱状图展示板块集中度

### 3.2 Beta/Alpha 归因
- [ ] 多因子归因：Market / Size / Value / Momentum
- [ ] 超额收益分解：Alpha vs Beta 贡献
- [ ] 前端可视化：净值曲线叠加基准对比

### 3.3 相关性矩阵
- [ ] 计算持仓间的相关系数矩阵 (60 日收益率)
- [ ] 前端热力图可视化
- [ ] 高相关性预警 (>0.8 提示集中度风险)

### 3.4 压力测试
- [ ] 历史情景回放：2008 金融危机 / 2020 疫情 / 2022 加息
- [ ] 假设情景：利率 +1% / 汇率 -5% / 波动率翻倍
- [ ] 前端展示：压力测试后的 NAV 变化

### 3.5 CVaR 分解
- [ ] Conditional VaR (Expected Shortfall)
- [ ] 按持仓分解 CVaR 贡献度
- [ ] 边际 VaR 分析

### 3.6 流动性风险
- [ ] 持仓日均成交额 vs 持仓市值 → 流动性覆盖率
- [ ] 大额持仓预警 (>10% NAV)
- [ ] 流动性评分 (0-100)

## 4. Redis 键空间约定

| Key | Type | TTL | 说明 |
|:---|:---|:---|:---|
| `quant:risk:portfolio` | String (JSON) | 30s | 风控面板全量数据缓存 |
| `quant:risk:nav_snapshots` | List | 无 | NAV 快照序列 (最多 288 条) |

## 5. 指标阈值定义

| 指标 | 安全 | 预警 | 超限 |
|:---|:---|:---|:---|
| **杠杆利用率** | <50% | 50-80% | >80% |
| **VaR (95%)** | >-$2K | -$2K~-$3K | <-$3K |
| **MaxDD** | >-10% | -10%~-15% | <-15% |
| **Beta** | <1.0 | 1.0-1.2 | >1.2 |
| **Sharpe** | >1.5 | 1.0-1.5 | <1.0 |

## 6. 文件清单

| 文件 | 职责 |
|:---|:---|
| `backend/services/risk_engine.py` | 风控计算引擎 (单例) |
| `backend/routers/risk.py` | Risk API 路由 |
| `backend/main.py` | 注册 risk router + NAV 快照 daemon |
| `frontend/src/features/trading/risk.tsx` | 前端风控面板 |
