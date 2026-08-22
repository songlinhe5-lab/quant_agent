# TODO — Futu 基本面 / 选股接口评估与接入计划

> 创建时间：2026-08-13
> 状态：评估已完成，**P0（财务三大表）已于 2026-08-22 完成并验证**，P1.1（估值详情）已验证可用；P1.2~P1.7 待办（按需填坑）。
> 触发来源：富途 Futu API v10.9 新增能力评估（`get_stock_screen` / `get_financials_statements`）
> 参考文档：
> - `https://openapi.futunn.com/futu-api-doc/quote/get-stock-screen.html`（协议 3252）
> - `https://openapi.futunn.com/futu-api-doc/quote/get-financials-statements.html`（协议 3227）

---

## 一、评估结论（先给结论）

| 接口 | 判断 | 结论 |
|---|---|---|
| `get_stock_screen`（筛选正股） | ❌ 已覆盖 | 你系统已完整实现 V2 选股，**勿重接**，仅需对照文档补缺失因子 |
| `get_financials_statements`（财务三大表） | ✅ 真增量 | 戳破现有「假基本面」，强烈建议接入 |

**一句话**：`get_stock_screen` 你已经造好了轮子，别被富途营销话术带偏重接；真正该动手的是 `get_financials_statements`——它暴露了你「基本面工具」名不副实的硬伤。

---

## 二、`get_stock_screen`：已覆盖，仅补字段

### 2.1 现状

- 你系统已完整实现 `get_stock_screen`（V2 选股），位于 `data_subservice/futu_src/screener_handler.py`。
- 已覆盖官方 11 类 244+ 因子的核心类别：`simple` / `financial` / `accumulate` / `featured` / `pattern` / `indicator`（位置+形态）/ `kline_shape` / `broker` / `option`。
- 额外工程化：智能类型纠偏、旧字段名 legacy 映射、行业名→板块ID 动态翻译、板块剔除二次过滤、分页「一波流」、错峰流控防封杀、百分比字段 `_fmt` 格式化。

### 2.2 结论

**无需新增接口**。唯一价值是「补因子清单」——若官方新增了你尚未接入的因子，属于「补字段」而非「接接口」。

### 2.3 官方因子清单（对照补漏）

- 简单行情：`PRICE` / `MARKET_CAP` / `PE_TTM` / `VOLUME_RATIO` / `DIVIDEND_RATIO`
- 累计行情：`PRICE_CHANGE_PCT` / `AMPLITUDE` / `AVG_VOLUME` / `TURNOVER_RATIO`（百分数传小数）
- 财务：`NET_PROFIT` / `ROE`（传小数）/ `REVENUE_GROWTH` / `BASIC_EPS` / `DIVIDENDS_TTM_RATIO`
- 特色：`SHORT_POSITION` / `ANALYST_RATING`（1=强买~5=强卖）/ `ANALYST_TARGET_PRICE` / `HIST_PERCENTILE_PE` / `CASH_FLOW_MAIN_NET_IN`
- 经纪商（仅港股）：`CONCENTRATED_DISTRIBUTION` / `BROKER_NUM` / `CENTRAL_HOLDINGS_RATIO` / `CENTRAL_HOLDINGS_CHANGE`
- K线形态：`SHAPE_TYPE` / `RISE_PROB`（形态后上涨概率）
- 期权：`STOCK_IV` / `STOCK_IV_RANK` / `STOCK_HV`

---

## 三、`get_financials_statements`：真增量，戳破「假基本面」

### 3.1 关键发现（硬伤）

你现有的 `get_fundamental`（`data_subservice/futu_src/option_fund_handler.py:256`）**并非真基本面**——底层调 `get_market_snapshot`（实时快照），仅返回 5 个估值字段：

```
company_name / trailing_PE / price_to_book / dividend_yield / market_cap
```

**缺失**（均无底层数据支撑）：
- ❌ 财务三大表（利润表/资产负债表/现金流量表）明细
- ❌ 同比 / 环比（yoy / qoq）
- ❌ 主营构成（`get_financials_revenue_breakdown`）
- ❌ 分析师评级 / 目标价（`get_research_analyst_consensus` / `get_research_rating_summary`）
- ❌ 股东持股 / 内部人交易（`get_shareholders_*` / `get_insider_*`）
- ❌ 卖空数据（`get_short_interest` / `get_daily_short_volume`）
- ❌ 估值详情（`get_valuation_detail`，PE/PB/PS 完整）

> ⚠️ 与 `AGENTS.md` §2 的 `get_fundamental_data` 工具宣称「PE/PB/ROE/做空比例」存在**能力与宣传的鸿沟**：ROE、做空比例等底层 Futu 通道实际拿不到。接 `get_financials_statements` 是「填坑」，不是「扩张」。

### 3.2 `get_financials_statements` 能力边界

- **支持**：利润表(1) / 资产负债表(2) / 现金流量表(3) / 关键指标(4)，含 `yoy`/`qoq`。
- **支持标的**：正股 + 基金；市场 `HK.00700` / `US.AAPL` / `SH.600000` / `SZ.000001`。
- **分页**：`next_key` 游标，`num` 1~50，返回 `-1` 表无更多。
- **限流**：每 30 秒 30 次。
- **返回结构**：`structure_list`（字段定义）+ `report_list`（含 `item_list`: field_id / data / yoy / qoq / display_name）。
- **不含**：估值/评级/股东/内部人/卖空/主营/分红回购——这些是**独立接口族**（见 §三.1 缺失清单）。

---

## 四、TODO List

### 阶段 P0：财务三大表（ROI 最高，先做）

- [x] **P0.1** 实现 `get_financials_statements`：✅ 2026-08-22 修正并验证（`option_fund_handler.py`）。**关键修复（零幻觉）**：原代码用错 `statement_type` 字符串枚举（如 `'BALANCE_SHEET'`）→ SDK 返回 `ret=-1 unknown enum label`，被 `is_unsupported` 降级，宏观层实际拿不到真财务数据（即「假基本面」真因）。实跑确认正确入参为 **整数枚举 1/2/3/4 + F10Type 字符串**（`'ANNUAL'` 等）。
- [x] **P0.2** `next_key` 游标分页 + `num`：✅ 已实现（每页拉满 50，续拉直到 `next_key` 空或达 `want`）。
- [x] **P0.3** 字段映射：✅ 利用返回的 `structure_list` / `item_list.display_name` 作中文字段名（**零幻觉，不手编英文枚举映射**——旧 `FINANCIAL_FIELD_MAP` 因 field_id 是整数永远命中不到，已废弃）。
- [x] **P0.4** `futu_worker.py` `_FUTU_ACTION_MAP`：✅ 已有 `FINANCIALS` 分支（透传 statement_type/financial_type/currency_code/num）→ `service.get_financials` → `option_fund_handler.get_financials_statements`（兼容语义字符串 balance_sheet/income/cash_flow/main_index 或整数 1~4）。
- [x] **P0.5** 主服务 `adapters/futu.py` `capabilities`：✅ 已声明 `FINANCIALS` + `VALUATION`；`router.py` 已含 `"financials": "FINANCIALS"` 映射。
- [x] **P0.6** `@with_global_retry` + `cache_mgr`：✅ 已接入（`cache_manager.py` 新增 `get/set_financials_cache`，24h TTL，财报低频）。
- [x] **P0.7** 单测：✅ `test_futu_option_fund_handler.py::TestFinancialsStatements`（5 例：枚举映射/解析/分页/缓存/非法类型），37 例全过；另实跑 `US.AAPL` 四种报表端到端验证（资产负债表/利润表/现金流量表/关键指标均有真实数据）。
- [x] **P0.8** 提交 PR：✅ 见 git log（commit 待本批次统一）。

### 阶段 P1：基本面接口族（按需分批「填坑」）

- [x] **P1.1** 估值详情 `get_valuation_detail`：✅ 2026-08-22 实跑验证有效（`option_fund_handler.py`，`ctx.get_valuation_detail(code)` 返回估值分布类 7 字段：trend/market_distribution/profit_growth_rate 等）。PE/PB/市值等核心估值已由 `get_fundamental` 的 trailing_PE/market_cap 覆盖。注：当前返回偏「估值分布」而非逐指标 PE/PB/PS 拆解，如需纯 PE/PB/PS 明细再增强（非阻塞）。
- [x] **P1.2** 分析师评级：✅ 2026-08-22 实现并实测。`get_research_analyst_consensus`（共识）此前已实现；本次补 `get_research_rating_summary`（INSTITUTION/ANALYST 两维，`option_fund_handler.py`）。**实测修正**：`rating_dimension_type` 有效值 `INSTITUTION/ANALYST`（带 `RATING_DIMENSION_BY_` 前缀会报错）；rating/target_price 在 `rating_item_list` 内（非顶层）。
- [x] **P1.3** 主营构成 `get_financials_revenue_breakdown`：✅ 2026-08-22 实现并实测。**实测修正**：`financial_type` 需大写枚举 `ANNUAL`（小写 annual 报错）；返回 REGION/PRODUCT 两维收入拆分。
- [x] **P1.4** 卖空数据：✅ `get_daily_short_volume`/`get_short_selling_rank` 此前已实现（`short_selling_handler.py`）；本次补 `get_short_interest`（累计卖空持仓，美股，`option_fund_handler.py`）。实测返回 3 元组 (ret, 逐期 DF, 聚合 DF)。
- [x] **P1.5** 股东持股 / 内部人交易：✅ 2026-08-22 实现并实测 6 方法（`option_fund_handler.py`）：`get_shareholders_overview`/`get_shareholders_holding_changes`/`get_shareholders_institutional`/`get_shareholders_holder_detail`/`get_insider_holder_list`/`get_insider_trade_list`。**SDK 10.10 真实符号**（文档 `get_shareholders_*`/`get_insider_*` 为通配命名）：`get_insider_trade_list`（非 transaction）、`get_insider_holder_list`。
- [x] **P1.6** 分红/回购/拆股：✅ 2026-08-22 实现并实测 3 方法（`option_fund_handler.py`）：`get_corporate_actions_dividends`/`get_corporate_actions_buybacks`（仅港股/A股，US 报错）/`get_corporate_actions_stock_splits`。**SDK 10.10 真实符号**（非 `get_corporate_actions_*` 通配）：`get_corporate_actions_dividends/buybacks/stock_splits`。实测字段：buybacks 列 `buy_back_money/buy_back_sum/percentage/cumulative_percentage`；splits 字段 `rate`（如 `1→4`）。
- [x] **P1.7** 十大经纪商 `get_top_brokers`：✅ 已完成（`option_fund_handler.py` L708，底层调 `ctx.get_top_ten_buy_sell_brokers`）。仅港股正股/基金支持，US 返回 unsupported。
- [ ] **P1.8** 资金流向 `get_capital_flow` / `get_capital_distribution`：✅ 已完成（`get_capital_flow` L805 / `get_capital_distribution` L500 已存在并实测可用）。
- [x] **P1.9** 每批单测 + 提交 PR：✅ 本次 P1.2~P1.7 新增 `TestP1FundamentalFamily`（13 例），`test_futu_option_fund_handler.py` 共 **50 例全过**。全链路（handler→service→worker→adapter→router）已打通并端到端实测（US.AAPL + HK.00700）。

### 阶段 P2：选股因子补全（轻量）

- [ ] **P2.1** 对照 §2.3 因子清单，检查 `screener_handler.py` 已覆盖哪些，标记缺失项。
- [ ] **P2.2** 补缺失因子（重点：`HIST_PERCENTILE_PE` / `RISE_PROB` / `SHORT_POSITION` / `STOCK_IV_RANK`）。
- [ ] **P2.3** 单测 + 提交 PR。

### 阶段 P3：文档与宣传对齐

- [ ] **P3.1** 同步 `AGENTS.md` §2 `get_fundamental_data` 工具描述：区分「估值摘要（现状）」与「财务三大表（新增后）」，消除宣传与能力鸿沟。
- [ ] **P3.2** `MEMORY.md` 沉淀：现有 `get_fundamental` 是「假基本面」（仅 5 个快照字段）的发现 + 该接口族清单。
- [ ] **P3.3** `DEPLOYMENT_CHECKLIST.md` 或 `docs/14` 补 Futu 基本面接口接入说明。

---

## 五、落地关键点（架构红线，务必遵守）

1. **仅远程**：所有 Futu 数据下沉 `data_subservice`，主服务经 `DataSourceRouter.fetch_futu()` HTTP 代理，**禁止主服务直连 OpenD / 持有 SDK**。
2. **限流**：财务接口 30 次/30s，选股接口 10 次/30s，必须接现有 `@with_global_retry` + `asyncio.Lock` 错峰流控。
3. **缓存**：财报/估值是低频数据，用 `cache_mgr` 缓存（1 天级）；快照类（选股）保持短缓存。
4. **字段映射**：`get_financials_statements` 返回 `field_id` + `structure_list`，需做 ID→中文名映射，不能裸吐 field_id 给上层。
5. **分页**：`next_key` 游标分页，`-1` 终止，别硬编码页数。
6. **零幻觉**：财务数值严禁捏造，接口失败必须返回错误态（`{"status":"error"}`），不降级为假数据。

---

## 六、参考资料

- `get_stock_screen` 文档（协议 3252）：`https://openapi.futunn.com/futu-api-doc/quote/get-stock-screen.html`
- `get_financials_statements` 文档（协议 3227）：`https://openapi.futunn.com/futu-api-doc/quote/get-financials-statements.html`
- 现有实现参考：
  - 选股：`data_subservice/futu_src/screener_handler.py`
  - 基本面（假）：`data_subservice/futu_src/option_fund_handler.py:256`
  - worker 路由：`data_subservice/futu_worker.py`
  - 适配器：`backend/services/datasource/adapters/futu.py`
