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

- [ ] **P0.1** 验证权限：确认 Futu OpenD 账户是否已开通**组合期权行情权限**（`get_option_strategy` 需对应市场期权权限）。无权限则一切免谈，先解决权限。
- [ ] **P0.2** 新增 `data_subservice/futu_src/option_strategy_handler.py`（或扩展 `option_fund_handler.py`），实现：
  - `get_option_strategy`（组合策略定义：跨式/价差/蝶式等）
  - `get_option_strategy_analysis`（期权损益分析：盈亏平衡点 / 最大盈亏 / Greeks 敞口）
  - `get_option_quote`（期权快照）
- [ ] **P0.3** 接入 `futu_worker.py` 的 `_FUTU_ACTION_MAP`：新增 action（如 `OPTION_STRATEGY` / `OPTION_STRATEGY_ANALYSIS` / `OPTION_QUOTE`）。
- [ ] **P0.4** 主服务 `adapters/futu.py` 的 `capabilities` 声明新 action + `router.py` 路由。
- [ ] **P0.5** 接入 `@with_global_retry` + `cache_mgr` 缓存（期权行情高频，短 TTL 与现有期权链一致）。
- [ ] **P0.6** 单测：策略解析、损益分析字段（盈亏平衡点/最大盈亏/Greeks）、异常兜底、限流退避。
- [ ] **P0.7** 提交 PR。

### 阶段 P0.5：期权全维数据（深度补强，2026-08-13 追加评估）

> 来源：Futu 行情接口总览 `get_option_*` 系列，补齐现有单腿期权链缺失的专业维度。

- [ ] **P0.5.1** 验证权限：确认 OpenD 账户开通对应期权数据权限。
- [ ] **P0.5.2** 波动率：`get_option_volatility`（IV）+ `get_option_underlying_his_volatility`（HV）+ `get_option_underlying_overview`（标的总览）。
- [ ] **P0.5.3** Put/Call 比：`get_option_market_statistic`（市场整体指标，含 P/C 比），对标 AGENTS.md 期权多空比情绪指标。
- [ ] **P0.5.4** 末日期权：`get_option_zero_dte_screener` + `get_option_zero_dte_contract`（0DTE）。
- [ ] **P0.5.5** 财报期权：`get_option_earnings_screener`。
- [ ] **P0.5.6** 卖方策略：`get_option_seller_screener`。
- [ ] **P0.5.7** 行权概率：`get_option_exercise_probability`。
- [ ] **P0.5.8** 接入 `futu_worker.py` + 主服务 `capabilities`/`router.py` 路由 + `@with_global_retry` 缓存。
- [ ] **P0.5.9** 单测 + 提交 PR。

### 阶段 P1：组合期权交易（预留，待 OMS 实装）

- [ ] **P1.1** 在 `trade_handler.py` 预留 `place_combo_order` / `comboorder_tradinginfo_query` 的 action 定义与路由骨架。
- [ ] **P1.2** 严守 AGENTS.md §6 沙箱约束：默认 SIMULATE，仅 `REAL_TRADE_EXECUTE` 标志 + 二次确认才实盘。
- [ ] **P1.3** 等 OMS 实盘工具实装后，再填充真实下单逻辑。
- [ ] **P1.4** 单测（模拟下单）+ 提交 PR。

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
