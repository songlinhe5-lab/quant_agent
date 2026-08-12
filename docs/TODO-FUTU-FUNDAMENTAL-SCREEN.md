# TODO — Futu 基本面 / 选股接口评估与接入计划

> 创建时间：2026-08-13
> 状态：评估已完成，**代码未开始**（后期开动）
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

- [ ] **P0.1** 新增 `data_subservice/futu_src/fundamental_handler.py`（或扩展 `option_fund_handler.py`），实现 `get_financials_statements(ticker, statement_type, financial_type)`。
- [ ] **P0.2** 处理 `next_key` 游标分页 + `num` 参数（1~50）。
- [ ] **P0.3** 字段映射：`field_id` → 中文 `display_name`（利用返回的 `structure_list`），构造结构化三大表 + yoy/qoq。
- [ ] **P0.4** 接入 `futu_worker.py` 的 `_FUTU_ACTION_MAP`：新增 action（如 `FINANCIAL_STATEMENTS`）。
- [ ] **P0.5** 主服务 `adapters/futu.py` 的 `capabilities` 声明新 action + `router.py` 路由。
- [ ] **P0.6** 接入现有 `@with_global_retry` + `cache_mgr` 缓存（财报低频，缓存周期可设 1 天级）。
- [ ] **P0.7** 单测：正常返回、分页、字段映射、异常兜底、限流退避。
- [ ] **P0.8** 提交 PR。

### 阶段 P1：基本面接口族（按需分批「填坑」）

- [ ] **P1.1** 估值详情 `get_valuation_detail`（PE/PB/PS 完整）——优先，补 `get_fundamental` 的估值残缺。
- [ ] **P1.2** 分析师评级 `get_research_analyst_consensus` / `get_research_rating_summary`。
- [ ] **P1.3** 主营构成 `get_financials_revenue_breakdown`。
- [ ] **P1.4** 卖空数据 `get_short_interest` / `get_daily_short_volume`（美股）。
- [ ] **P1.5** 股东持股 / 内部人交易 `get_shareholders_*` / `get_insider_*`。
- [ ] **P1.6** 分红/回购/拆股 `get_corporate_actions_*`。
- [ ] **P1.7** 十大经纪商 `get_top_ten_buy_sell_brokers`（港股）。
- [ ] **P1.8** 资金流向 `get_capital_flow` / `get_capital_distribution`。
- [ ] **P1.9** 每批单测 + 提交 PR（Vibe Coding 即时 commit）。

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
