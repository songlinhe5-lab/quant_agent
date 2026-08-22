# TODO — Futu 行情搜索 / FedWatch / 市场基本面评估与接入计划

> 创建时间：2026-08-13
> 状态：评估已完成，**代码未开始**（后期开动）
> 触发来源：富途 Futu API 行情搜索、资讯搜索、指标列表、市场基本面能力评估
> 参考文档：
> - `get_search_quote`：`https://openapi.futunn.com/futu-api-doc/quote/get-search-quote.html`
> - `get_search_news`：`https://openapi.futunn.com/futu-api-doc/quote/get-search-news.html`
> - `get_indicator_list`：`https://openapi.futunn.com/futu-api-doc/quote/get-indicator-list.html`
> - 行情接口总览：`https://openapi.futunn.com/futu-api-doc/quote/overview.html`

---

## 一、评估结论（先给结论）

| 接口类 | 判断 | 优先级 | 理由 |
|---|---|---|---|
| 行情搜索 `get_search_quote` | ✅ 接 | **P1** | 补「名称→代码」盲区，Agent 高频刚需 |
| 资讯搜索 `get_search_news` | ⚠️ 可选 | P2 | 与现有新闻链部分重复 |
| 指标列表 `get_indicator_list` | ❌ 跳过 | P3 | 指标已内置引擎化，用不上 |
| FedWatch（利率概率+点阵图） | ✅ 接 | **P1** | 补 FOMC 前瞻指引，Tier1 刚需 |
| 机构追踪（13F/ARK） | ⚠️ 可选 | P2 | 美股聪明钱，Finnhub 可部分替代 |
| 榜单/产业链/日历 | ❌ 低/重复 | P3 | 重复或增量有限 |

**一句话**：真正该动手的是**行情搜索**（补「名称→代码」）、**FedWatch**（补 FOMC 利率概率/点阵图）两个硬货；其余要么重复、要么用不上（指标列表纯属凑数）。

---

## 二、现状盘点

- **搜索**：`search.py` 适配器（tavily/bocha/jina + 待补 DDG）是**非结构化网页搜索**，无「关键词→标的代码」能力。
- **资讯**：`get_company_news` / `get_macro_news`（新闻检索），无「新闻+公告+评级」聚合搜索。
- **技术指标**：`calculate_technical_indicators`（MA/MACD/RSI/ATR/布林）已内置引擎化，指标集固定。
- **宏观**：FRED（`get_fred_macro_data`）+ 宏观日历（`macro_calendar_service`）+ VIX/P-C/Credit Spread，**缺 FedWatch 目标利率概率与点阵图**。
- **日历**：Finnhub/akshare 已有财报/派息/经济日历。
- **期权全维**：见 `TODO-FUTU-OPTION-COMBO-MARKETS.md`（已追加 P0.5 阶段）。
- **榜单/产业链**：无（ApeWisdom 已覆盖「热议榜」部分需求）。

---

## 三、TODO List

### 阶段 P1：行情搜索（ROI 高，补「名称→代码」盲区）

- [ ] **P1.1** 验证权限：确认 `get_search_quote` 可用（先验证再写代码）。
- [ ] **P1.2** 新增 `data_subservice/futu_src/search_quote_handler.py`（或扩展 `quote_handler.py`），实现 `get_search_quote(keyword)`：关键词 → 标的列表（代码/名称/市场）。
- [ ] **P1.3** 接入 `futu_worker.py` 的 `_FUTU_ACTION_MAP`：新增 action（如 `SEARCH_QUOTE`）。
- [ ] **P1.4** 主服务 `adapters/futu.py` 的 `capabilities` 声明 + `router.py` 路由。
- [ ] **P1.5** 对接 Hermes Agent 工具链：为「自然语言查股票」提供「名称→代码」解析能力（替代硬编码映射）。
- [ ] **P1.6** 单测 + 提交 PR。

### 阶段 P1：FedWatch（补 FOMC 前瞻指引）

- [ ] **P1.7** 验证权限：确认 `get_fed_watch_target_rate` / `get_fed_watch_dot_plot` 可用。
- [ ] **P1.8** 新增 `data_subservice/futu_src/fedwatch_handler.py`，实现：
  - `get_fed_watch_target_rate`（目标利率概率）
  - `get_fed_watch_dot_plot`（点阵图）
- [ ] **P1.9** 接入 `futu_worker.py` + 主服务 `capabilities`/`router.py` 路由。
- [ ] **P1.10** 研判层接入：FedWatch 利率概率喂进 AGENTS.md §5 宏观风控（Tier1 FOMC 前瞻指引）。
- [ ] **P1.11** 单测 + 提交 PR。

### 阶段 P2：可选（按需再启）

- [ ] **P2.1** 资讯搜索 `get_search_news`：若需「新闻+公告+评级」聚合检索再接，否则用现有新闻链。
- [x] **P2.2** 机构追踪 `get_institution_*` / ARK 持仓：✅ 2026-08-22 实现并实测（美股聪明钱）。**权限验证**：6 接口 OpenD 实跑全部可用（`get_institution_list`/`holding_list`/`holding_change`/`distribution`/`profile` + `get_ark_fund_holding`/`get_ark_active_transaction`），真实 13F 数据（`institution_holding_list` source=13F数据汇总，实测 Vanguard ID=1951572549、AAPL holding_pct=7.14%）。**增量**：ARK 持仓/每日交易是 Finnhub 无的数据，与 insider(内部人)互补。已接入 `quote_handler.py` 7 方法 + service + worker（`INSTITUTION_*`/`ARK_*` 7 action）+ adapter + router。**SDK 枚举**：`ArkHoldingType`=POSITION/INCREASE/DECREASE/NEW/SOLD_OUT、`ArkCycleType`=ONE_DAY/FIVE_DAY/TEN_DAY/THIRTY_DAY/SIXTY_DAY。单测 `TestInstitutionArk` 9 例全过。
- [ ] **P2.3** 榜单（盘前/盘后/领涨领跌/卖空）：ApeWisdom 已覆盖热议榜，Futu 榜单美股盘前盘后数据增量有限。

### 阶段 P3：跳过（记录结论）

- [ ] **P3.1** 指标列表 `get_indicator_list`：跳过（指标已内置引擎化，无自定义指标需求）。
- [ ] **P3.2** 产业链 `get_industrial_chain_*`：跳过（akshare 板块数据可替代）。
- [ ] **P3.3** 日历（财报/派息/经济）：跳过（Finnhub/akshare 已有）。
- [ ] **P3.4** 上述跳过项记入 `MEMORY.md`，避免后人重复评估。

### 阶段 P4：文档对齐

- [ ] **P4.1** `MEMORY.md` 沉淀：行情搜索补「名称→代码」、FedWatch 补 FOMC 概率，其余低价值跳过。
- [ ] **P4.2** `AGENTS.md` §5 宏观监控补 FedWatch 利率概率作为新信号源。
- [ ] **P4.3** `DEPLOYMENT_CHECKLIST.md` 补行情搜索/FedWatch 接入说明 + 权限门槛。

---

## 四、落地关键点（架构红线）

1. **仅远程**：下沉 `data_subservice`，主服务经 `DataSourceRouter.fetch_futu()` HTTP 代理，禁主服务直连 OpenD。
2. **先验证权限再写代码**（同 Finnhub 403 教训）。
3. **行情搜索是高频刚需**：Agent 每次「查 XX 股票」都触发，需接 `cache_mgr` 缓存 + 限流，避免频繁打 Futu。
4. **FedWatch 是低频数据**：利率概率/点阵图更新频率低，可长 TTL 缓存。
5. **零幻觉**：利率概率/点阵图必须来自 Futu 真实返回，严禁自行估算。

---

## 四.5、P1 执行状态（2026-08-22）

- [x] **P1.1 权限验证**：✅ `get_search_quote` / `get_fed_watch_dot_plot` 均 OpenD 在线实跑通过，真实返回结构已拿到（零幻觉）。
- [x] **P1.2 行情搜索**：✅ 实现 `quote_handler.get_search_quote(keyword, max_count)` + L1 内存缓存（`cache_mgr.search_quote`，TTL 10 分钟）+ service `get_search_quote` + worker `SEARCH_QUOTE` + adapter capability + router `search_quote` 映射 + facade `search_quote`。实测：中文「腾讯」→HK.00700、「AAPL」→US.AAPL 均正确。
- [x] **P1.3 缓存**：✅ `_SEARCH_QUOTE_TTL=600`，10 分钟缓存（Agent 高频刚需，降频防穿透）。
- [x] **P1.4 限流**：✅ 依赖既有全局 `with_global_retry` + worker 线程池，配合缓存已足够；搜索不在 ticker 流内，无额外限流瓶颈。
- [x] **P1.5 Agent 对接**：✅ facade 层 `search_quote(keyword)`（`_dispatch("SEARCH_QUOTE")`，prefer futu），供 Agent 工具链「名称→代码」解析，替代硬编码映射。
- [x] **P1.6 单测**：✅ 新增 `get_search_quote` 4 例（空关键词/成功/缓存命中/失败）+ `get_fed_watch_dot_plot` 2 例，`test_futu_quote_handler.py` 共 **55 例全过**。
- [x] **P1.7 FedWatch 目标利率**：✅ **此前已完成**（`quote_handler.get_fed_watch_target_rate` L180 + worker `FED_WATCH` + adapter + router + 主服务 macro 研判层 + 单测 L507-545）。
- [x] **P1.8 FedWatch 点阵图**：✅ 本次补 `quote_handler.get_fed_watch_dot_plot`（返回 year/rate/vote_count/is_median/median_rate/current_rate）+ service `get_fed_watch_dot_plot` + worker `FED_WATCH_DOT_PLOT` + adapter + router。
- [x] **P1.9 官方文档**：✅ 文件头部 4 个链接均为真实官方 URL（get-search-quote / get-search-news / get-indicator-list / overview），无需替换。
- [x] **P1.10 主服务研判层接入**：✅ 2026-08-22 完成。`FedWatchTool`(get_fed_watch) 此前已存在并走 `/macro/fed-watch`；本次补齐专家辩论层接入——`data_collector._DATA_COLLECTORS` 新增 `fed_watch → get_fed_watch`（市场级无 ticker）；`expert_registry` 给 `MACRO_STRATEGIST` / `PORTFOLIO_RISK_MANAGER` 的 `available_tools` 追加 `get_fed_watch`，`financial_research` / `full_investment` 场景 `data_requirements` 追加 `fed_watch`；`macro_app.get_macro_assets` 额外把 FedWatch 派生为 `sentimentIndicators.fed_watch` + 风险雷达「FOMC政策」轴（降息概率→宽松倾向分，失败静默降级）。**FedWatch target_rate 现作为 Tier1 FOMC 前瞻信号进入宏观研判/风控层**。
- [x] **P1.11 单测 + 提交 PR**：✅ 新增 `TestFedWatchInExpertTeam` 6 例（_DATA_COLLECTORS 映射 / 专家 available_tools / 场景 data_requirements / collect_shared_data 调用 get_fed_watch 且不传 ticker）。

---

## 五、参考资料

- 现有搜索适配器：`backend/services/datasource/adapters/search.py`
- 现有宏观：`backend/services/macro/`（fred_service / macro_calendar_service / dbnomics / rbi）
- 现有期权实现：`data_subservice/futu_src/option_fund_handler.py`
- 适配器：`backend/services/datasource/adapters/futu.py`
- 官方文档：见文件头部 4 个链接
