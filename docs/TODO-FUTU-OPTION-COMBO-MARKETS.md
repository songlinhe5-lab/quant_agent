# TODO — Futu 组合期权 / 新马日市场能力评估与接入计划

> 创建时间：2026-08-13
> 状态：评估已完成，**代码未开始**（后期开动）
> 触发来源：富途 Futu API 新增能力评估（组合期权 + 新马日市场）
> 参考文档：
> - `get_option_strategy`：`https://openapi.futunn.com/futu-api-doc/quote/get-option-strategy.html`
> - `get_option_strategy_analysis`：`https://openapi.futunn.com/futu-api-doc/quote/get-option-strategy-analysis.html`
> - `get_option_quote`：`https://openapi.futunn.com/futu-api-doc/quote/get-option-quote.html`
> - `place_combo_order`：`https://openapi.futunn.com/futu-api-doc/trade/place-combo-order.html`
> - `comboorder_tradinginfo_query`：`https://openapi.futunn.com/futu-api-doc/trade/comboorder-tradinginfo-query.html`

---

## 一、评估结论（先给结论）

| 能力 | 判断 | 结论 |
|---|---|---|
| 新马日（SG/MY/JP）股票行情+交易 | ⚠️ 价值低 | 长尾市场，无消费场景，暂缓 |
| 组合期权行情（strategy / analysis / quote） | ✅ 高价值 | 期权能力从「单腿」升级到「策略+损益分析」，质变 |
| 组合期权交易（combo order / 购买力） | ⚠️ 预留 | 交易层纯沙箱，OMS 未实装，现在接了下单也落不了地 |

**一句话**：新马日是三瓜俩枣的长尾，别被「支持 5 市场」话术带偏；真正值钱的是**组合期权的策略 + 损益分析**——它把系统从「卖单腿期权链数据」升级到「给期权策略做盈亏决策」。交易类接口现在接了下单也是沙箱空转，等 OMS 实装再说。

---

## 二、现状盘点（判断增量的依据）

### 2.1 现有期权能力

- 仅有**单腿期权链**：`data_subservice/futu_src/option_fund_handler.py::get_option_chain`
- 返回字段：IV / Greeks / 买卖价 / 量仓（经 `cache_mgr.compress_chain_data` 压缩）。
- 缓存：期权链 5 分钟 TTL（`cache_manager.py:15`）。
- **缺失（组合策略）**：组合策略（跨式/价差/蝶式）、期权损益分析（盈亏平衡点/最大盈亏/Greeks 敞口）、组合下单、购买力查询。
- **缺失（期权全维数据）**：IV/HV 波动率分析、Put/Call 比、0DTE 末日期权、财报期权、卖方策略、行权概率（见 §三 阶段 P1.5 期权全维数据）。

### 2.2 现有交易能力

- `trade_handler.py` 有单腿下单 / 账户查询，但**纯沙箱（SIMULATE）**。
- OMS 实盘工具未挂载（AGENTS.md §6：交易纯模拟推演，待 OMS 实装）。

### 2.3 现有市场覆盖

- 主战场：港股（00700.HK 等）+ A股（akshare/tushare）+ 美股（宏观 + 期权）。
- **无** SG/MY/JP 任何策略线、专家团、研报消费场景。

---

## 三、TODO List

### 阶段 P0：组合期权行情三件套（ROI 最高，先做）

- [x] **P0.1** 验证权限：✅ 2026-08-22 OpenD 在线实跑通过。`get_option_quote` / `get_option_strategy_analysis` 均可调用（US.AAPL 组合腿），无需额外权限卡。**关键发现**：futu 10.10 的 `option_legs` 每个元素必须是 `OptionStrategyLeg` 对象（code/action/quantity 三字段），传字符串报 `each item in option_legs must be OptionStrategyLeg`。
- [x] **P0.2** 组合期权行情三件套：✅ 已全部实现于 `option_fund_handler.py`：
  - `get_option_strategy`（组合策略定义）✅ **此前已实现**（L142，F3）
  - `get_option_strategy_analysis`（期权损益分析）✅ 本次实现：实测返回 `max_profit/max_loss/breakeven_points/prob_of_profit/delta/theta`（宽跨式 max_loss=-10116、breakeven=[103.84,311.16]），**损益字段来自真实返回，零幻觉，无 Black-Scholes 近似**。
  - `get_option_quote`（期权快照）✅ 本次实现：实测返回 38 列（price/IV/delta/gamma/vega/theta/rho/breakeven_point/leverage_ratio/effective_gearing）。
- [x] **P0.3** 接入 `futu_worker.py`：✅ `OPTION_STRATEGY`（已有）+ 本次新增 `OPTION_STRATEGY_ANALYSIS` / `OPTION_QUOTE`（`legs` 参数透传）。
- [x] **P0.4** 主服务路由：✅ `adapters/futu.py` capabilities 新增 `OPTION_STRATEGY_ANALYSIS` / `OPTION_QUOTE`；`router.py` 新增 `option_strategy_analysis` / `option_quote` 映射。
- [x] **P0.5** 接入 `@with_global_retry`：✅ 两个新方法均带 `@with_global_retry`（复用全局重试 + worker 线程池）。⚠️ legs 级组合行情入参结构复杂，未加 cache_mgr 短 TTL（依赖全局 retry + 推送降频，非阻塞；如需缓存留待高频消费场景再按组合哈希键接入）。
- [x] **P0.6** 单测：✅ 新增 `TestGetOptionStrategyAnalysis`（5 例：未连接/非法legs/空legs/损益字段解析/失败）+ `TestGetOptionQuote`（4 例：未连接/非法legs/成功/失败），`test_option_fund_handler.py` 共 **50 例全过**。
- [x] **P0.7** 提交 PR：✅ 已 commit。

### 阶段 P0.5：期权全维数据（深度补强，2026-08-13 追加评估）

> 来源：Futu 行情接口总览 `get_option_*` 系列，补齐现有单腿期权链缺失的专业维度。

- [x] **P0.5.1** 验证权限：✅ 2026-08-22 全部 8 接口 OpenD 在线实跑通过，无需额外权限卡。**枚举值修正**（SDK 10.10）：`OptionMarket`=US_SECURITY/HK_SECURITY/US_INDEX/HK_INDEX；`OptionStatisticDataType`=VOLUME/OPEN_INTEREST；`SellerType`=COVERED_CALL/CASH_SECURED_PUT。
- [x] **P0.5.2** 波动率：✅ `get_option_volatility`(IV) 此前已实现；本次补 `get_option_underlying_his_volatility`(HV，实测 250 条 iv/hv/underlying_price) + `get_option_underlying_overview`(标的总览，实测 20 列：iv/iv_rank/iv_percentile/hv_30d~365d+percentile/call·put量仓)。
- [x] **P0.5.3** Put/Call 比：✅ `get_option_market_statistic`（实测 250 条，put_call_ratio=0.636，time/call_value/put_value/total_value）。
- [x] **P0.5.4** 末日期权：✅ `get_option_zero_dte_screener`（实测 item_list.owner+chain_info/next_page）+ `get_option_zero_dte_contract`（实测 510 条 0DTE 合约：option/iv/delta/buy_break_even_point/sell_profit_probability）。
- [x] **P0.5.5** 财报期权：✅ `get_option_earnings_screener`（实测 owner/name/estimate_revenue_yoy/expected_move_ratio/all_count）。
- [x] **P0.5.6** 卖方策略：✅ `get_option_seller_screener`（实测 1000 条：option/premium/otm_degree/iv/interval_return/annualized_return/itm_probability）。
- [x] **P0.5.7** 行权概率：✅ `get_option_exercise_probability`（实测 5 条：date_str/security_price/strike_probability）。
- [x] **P0.5.8** 接入链路：✅ 8 个新方法均带 `@with_global_retry`；worker 新增 8 个 action（OPTION_UNDERLYING_HIS_VOL/OVERVIEW、OPTION_MARKET_STATISTIC、OPTION_ZERO_DTE_SCREENER/CONTRACT、OPTION_EARNINGS_SCREENER、OPTION_SELLER_SCREENER、OPTION_EXERCISE_PROBABILITY）+ adapter capabilities + router 映射，全链路打通。
- [x] **P0.5.9** 单测 + 提交 PR：✅ 新增 `TestOptionFullDim` 10 例，`test_option_fund_handler.py` 共 **60 例全过**；worker/service 61 例全过无回归。
- [x] **P0.5.10 主服务 business 层聚合**（2026-08-22 追加）：✅ `backend/services/datasource/business/option.py` 新增 8 个聚合方法（`get_option_underlying_his_volatility` / `get_option_underlying_overview` / `get_option_market_statistic` / `get_option_zero_dte_screener` / `get_option_zero_dte_contract` / `get_option_earnings_screener` / `get_option_seller_screener` / `get_option_exercise_probability`）+ **`get_option_put_call_panel`**（P0.5.3 产品级聚合：P/C 比派生 latest/avg_5d/signal 情绪判定，<0.7 偏谨慎 / >1.0 偏乐观，空数据降级不臆造）。`backend/routers/market.py` 新增 9 个 HTTP 端点（/option-underlying-his-volatility、/option-underlying-overview、/option-market-statistic、/option-put-call-panel、/option-zero-dte-screener、/option-zero-dte-contract、/option-earnings-screener、/option-seller-screener、/option-exercise-probability）。单测 `test_option_full_dim_service.py` **12 例全过**（8 个 dispatch + Put/Call 面板 4 例），期权相关 37 例全过无回归。

### 阶段 P1：组合期权交易（预留，待 OMS 实装）

- [x] **P1.1** 预留骨架：✅ 2026-08-22 在 `trade_handler.py` 实现 `place_combo_order`（`_build_combo_legs` 把 [{code,trd_side,qty_ratio}] 转 `ComboLeg`）+ `comboorder_tradinginfo_query`；worker 新增 `PLACE_COMBO_ORDER` / `COMBO_TRADINGINFO_QUERY` action；service 包装。**SDK 核查**：`place_combo_order` / `comboorder_tradinginfo_query` 均存在，`ComboLeg` 字段 = code/trd_side/qty_ratio/position_id/pred_side。
- [x] **P1.2** 沙箱约束：✅ `_resolve_trd_env` 严守 AGENTS.md §6——默认 SIMULATE；仅 `REAL_TRADE_EXECUTE=1` **且** `force_real=True`（调用方二次确认）才 REAL，两者缺一回落 SIMULATE。单测覆盖：无标志时 force_real 仍 SIMULATE、有标志+确认才 REAL。
- [x] **P1.3** 待 OMS 实装：✅ 骨架方法内注明「OMS 组合实盘工具尚未实装，当前为骨架预留；SIMULATE 盘可推演组合成交」。真实下单逻辑待 OMS 实装后填充（占位明确，非静默空转）。
- [x] **P1.4** 单测 + 提交 PR：✅ 新增 `test_trade_combo_order.py` **9 例全过**（SIMULATE 成功/沙箱约束×2/非法腿/空腿/网关未连/SDK失败/交易信息查询成功+失败）；worker/service 61 例无回归。

### 阶段 P2：新马日市场（暂缓，有需求再启）

- [ ] **P2.1** 明确是否有 SG/MY/JP 的策略/用户/研报消费场景（当前无，默认不接）。
- [ ] **P2.2** 若确有需求：行情走 `quote_handler`（扩展市场映射），交易走 `trade_handler`，参考 HK/US 现有路径。
- [ ] **P2.3** 记录决策到 `MEMORY.md`：新马日为长尾，无消费场景，暂不投入。

### 阶段 P3：文档与宣传对齐

- [ ] **P3.1** 同步 `AGENTS.md` §2 期权工具描述：区分「单腿期权链（现状）」与「组合策略+损益分析（新增后）」。
- [ ] **P3.2** `MEMORY.md` 沉淀：组合期权是期权能力质变（单腿→策略+损益）、交易类受沙箱约束、新马日暂缓。
- [ ] **P3.3** `DEPLOYMENT_CHECKLIST.md` 或 `docs/14` 补组合期权接入说明 + 权限门槛。

---

## 四、落地关键点（架构红线，务必遵守）

1. **仅远程**：行情三件套下沉 `data_subservice`，主服务经 `DataSourceRouter.fetch_futu()` HTTP 代理；交易类走 `trade_handler`，**禁止主服务直连 OpenD / 持有 SDK**。
2. **沙箱默认**：交易类必须默认 SIMULATE，仅 `REAL_TRADE_EXECUTE` 标志 + 二次确认才实盘（AGENTS.md §6）。
3. **权限门槛**：组合期权行情/交易需 Futu 开通对应市场期权权限，接入前先验证（P0.1）。
4. **零幻觉**：损益分析（盈亏平衡点/最大盈亏/Greeks 敞口）必须来自 `get_option_strategy_analysis` 真实返回，严禁用 Black-Scholes 近似凑数（除非明确自研定价，走 C++ 模块，另立项）。
5. **缓存/限流**：期权行情高频，短 TTL（5 分钟级）；接 `@with_global_retry` + 错峰流控，防网关拥堵级联超时。

---

## 五、参考资料

- 现有期权链实现：`data_subservice/futu_src/option_fund_handler.py::get_option_chain`
- 现有交易实现：`data_subservice/futu_src/trade_handler.py`
- worker 路由：`data_subservice/futu_worker.py`
- 适配器：`backend/services/datasource/adapters/futu.py`
- 官方文档：见文件头部 5 个链接
