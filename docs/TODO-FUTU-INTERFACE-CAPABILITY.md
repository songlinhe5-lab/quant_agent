# Futu OpenD 接口能力总览与开发规划

> 创建时间：2026-08-16
> **实测基线：2026-08-16 18:47（本机 Mac OpenD + futu-api 10.10.7008，脚本 `_test_futu_local.py`，26/26 调用无异常）**
> 版本：**v0.5（2026-08-22 · 落地状态刷新）**
> 状态：**F1~F4 + G1 + G2~G8 已全链路落地；剩 F0-4 容器内等价验证（部署级）/ F5-2 探针字段级 / G6 轮动 三项待做**（逐项核实见 §三）
> 配套专项 TODO（细节见分册，本文件不重复展开）：
> - `docs/TODO-FUTU-SEARCH-MACRO.md` — 行情搜索 / FedWatch / 市场基本面
> - `docs/TODO-FUTU-FUNDAMENTAL-SCREEN.md` — 财务三大表 / 选股因子 / 估值评级
> - `docs/TODO-FUTU-OPTION-COMBO-MARKETS.md` — 期权策略损益 / 组合交易 / 多市场
> - `docs/TODO-FUTU-EVENT-CONTRACT.md` — 预测市场（事件合约）
>
> **实测脚本**：`_test_futu_local.py`（裸连 OpenD，可复跑）

---

## 〇、系统现状速览（事实基准）

### 0.1 已接入的 Futu action（核实自 `data_subservice/futu_worker.py:36-123`）

| Action | 底层接口（futu SDK）| 状态 | 本机实测 |
|---|---|---|---|
| `QUOTE` | `get_stock_quote` | ✅ 已接 | ✅ 2 行，**含期权希腊字母 + IV** |
| `HISTORY` | `request_history_kline` | ✅ 已接 | ✅ 10 根日K，含 PE/换手率 |
| `ORDER_BOOK` | `get_order_book` | ✅ 已接 | ⚠️ 盘后档位 `n/a`（**字段结构未验证**）|
| `OPTION_CHAIN` | `get_option_chain` | ✅ 已接 | ✅ 美股 1118 行 |
| `FUND_FLOW` | `get_capital_flow` | ✅ 已接 | ✅ 332 行主力资金流 |
| `FUNDAMENTAL` | `get_market_snapshot`（**假基本面**，见 §0.4）| ⚠️ 残缺 | ⚠️ 需 G1 收口 |
| `WARRANT_CHAIN` | `get_warrant` | ✅ 已接 | ✅ 港股窝轮 3 行 |
| `SNAPSHOT` | `get_market_snapshot` | ✅ 已接 | ✅ 字段爆炸级（PE/PB/期权/窝轮/卖空可用量）|
| `STOCK_BASICINFO` | `get_stock_basicinfo` | ✅ 已接 | ✅ 3776 只港股 |
| `SCREEN_STOCKS` | `get_stock_filter` | ✅ 已接 | ⚠️ 返回 `n/a` 行（**字段结构未验证**）|
| `COMPANY_NEWS`/`STOCK_NEWS`/`NEWS` | `get_search_news` | ✅ 已接 | ✅ 5 条 |
| `ACCOUNT_INFO` | `get_acc_list`/`order_list_query`/`position_list_query` | ✅ 已接（只读）| ✅ 6 账户 / 0 订单 / 0 持仓 |
| `SUBSCRIBE`/`UNSUBSCRIBE` | `subscribe`/`unsubscribe` | ✅ 已接（BE-ARCH-08c⑤）| ✅ HK+US 双订阅 |
| `PLACE_ORDER`/`MODIFY_ORDER`/`QUERY_ORDER` | `place_order`/`modify_order`/`order_list_query` | ⚠️ 沙箱（OMS 未实装）| ⏸️ 冻结至 OMS |
| `EMERGENCY_LIQUIDATION` | Kill Switch 下沉 | ✅ 已接（沙箱）| ⏸️ 冻结至 OMS |
| `HEALTH` | 连接态自检 | ✅ 已接 | — |

### 0.2 架构红线（所有接入必须遵守）

1. **仅远程**：Futu OpenD 仅在 US-MASTER 主节点，由 `data_subservice`（`DS_CAPABILITIES=futu`）持长连接；主服务经 `DataSourceRouter.fetch_futu()`（`router.py:1209`）HTTP 代理，**禁主服务直连 / 持有 SDK**。
2. **键名归一已有一处 guard**：`router.py:1303 _futu_normalize_params` 统一做 `ticker→symbol` / `tickers→symbols`，与 action 无关，**新 action 自动继承**。但新 action 自带的入参（如 `option_code` / `strategy_type` / `plate_id`）**必须 router 与 worker 双侧同名**，否则重犯 BE-ARCH-08b（子服务收到 `None`，线上静默取不到数）。
3. **限流 + 缓存**：行情短缓存、财务/宏观长缓存（1 天级），接现有 `@with_global_retry` + `cache_mgr`。
4. **沙箱默认**：交易类必须默认 SIMULATE，仅 `REAL_TRADE_EXECUTE` + 二次确认才实盘（AGENTS.md §6）。
5. **零幻觉**：接口失败返回 `{"status":"error"}`，不降级假数据；**空结果 ≠ 零值**（见 §0.5）。

### 0.3 实测结论的边界（纠正 v0.2 的过度乐观）

**✅ 已解除的阻塞**：本机 Mac OpenD + futu-api 10.10.7008，26 项调用全部无异常返回。

**❌ v0.2 的 F0「阻塞项」不成立（已核实为误报）**：
- v0.2 声称 `connection_manager.py` 仍 `from futu import OpenD`。**实际 `data_subservice/futu_src/connection_manager.py:15-18` 早已是 `OpenQuoteContext` / `OpenSecTradeContext`**，全文无 `OpenD` 类引用（仅注释与日志字符串提及 OpenD 进程）。→ **原 F0-1 / F0-2 撤销，不要浪费一轮工作。**

**⚠️ 「26/26 通过」≠ 字段级契约验证通过**：脚本只断言"调用未抛异常"。以下三项实际未验证数据结构，**禁止据此排期**：
| 项 | 实测输出 | 真实含义 |
|---|---|---|
| `ORDER_BOOK` | 档位 `n/a` | 盘后无实时档位（预期），但脚本也没解包成功 → 结构未验 |
| `SCREEN_STOCKS` | 返回 `n/a` 行 | SDK 返回 `(list, last_page, all_count)` 元组，脚本未解包 → 结构未验 |
| `get_daily_short_volume` | 0 行 | 当日盘后无结算数据（T-1 语义），**不是"无卖空"** |

**剩余真实风险**（2026-08-16 23:30 复核）：
- S1 容器内 `socat` 转发 `172.19.0.1:11111 → 127.0.0.1:11111` 未固化为 systemd，重启即断。**仍未做**（F0-3）。
- ~~`BE-ARCH-08a` 未修 = 主镜像 import 阶段就崩~~ → **已解除**：`market_engine.py` 顶层 import 已收敛为 `from backend.services.futu.utils import is_futu_unsupported, mark_futu_unsupported`（纯函数、零 SDK），死代码已删。上线阻塞不复存在。

### 0.4 `FUNDAMENTAL` 是假基本面（代码证据）

`data_subservice/futu_src/option_fund_handler.py:314-336` → `get_fundamental()` 内部调的是 `quote_ctx.get_market_snapshot([...])`。即 Hermes `get_fundamental_data` 返回的 PE/PB/ROE 全部来自**行情快照的估值字段**，没有三大表、没有历史序列。用户一问"最近 4 季经营现金流"必穿。

> **⚠️ 2026-08-16 23:30 复核：此硬伤仍然存在。** `FINANCIALS` / `VALUATION` 两个 action 的管道已铺到 worker + capabilities + action map（F2-1~F2-3 完成），**但收口没做**：`business/facade.py:454 get_fundamental()` 依旧是 `enable_merge=False` 的单源 dispatch 到 `FUNDAMENTAL`，且 `business/` 下**没有任何 `get_financials` / `get_valuation` 域方法** —— 新管道只能经 router 直连，走不到 Facade。**G1 未收口 = 假基本面照旧。见 §三 F2-4。**

### 0.5 空结果语义陷阱（本次实测暴露，必须写进实现）

探针里 `ORDER_BOOK` 无档位、`daily_short_volume` 0 行、`QUERY_ORDER`/持仓 0 条，**全部是"盘后/无数据"而非故障**。但系统当前**无法区分"盘后正常空"与"连接故障空"**，两者都会被当成可用数据或误报告警。
- `global_state` 已能返回市场状态（本次实测 `ASHARE_AFTER_HOURS_END`）→ 可作为 STALE / 空结果判定依据。
- → G8 任务。

---

## 一、接口能力盘点（实测结论）

### 1.1 实时推送 ✅ 已覆盖
`subscribe` / `unsubscribe` + Handler 已接（BE-ARCH-08c 全链路闭环），实测 HK+US 双订阅成功。

### 1.2 拉取类行情

| 接口 | 实测 | 结论 |
|---|---|---|
| `get_market_snapshot` / `get_stock_quote` / `get_order_book` | ✅ | 已接 |
| `request_history_kline` | ✅ | 已接，返回含 PE/换手率 |
| `get_capital_flow` | ✅ | 已接（仅净流入序列）|
| **`get_capital_distribution`** | ✅ **已接**（`CAPITAL_DISTRIBUTION`）| 主力/散户 8 档分层，比 FUND_FLOW 深一层 → G3 ✅ |
| `get_market_state` / `get_plate_list` | ✅ 已入探针（F5-1）| **仍未接入** → G8 / G6 轮动 |
| `get_owner_plate` / `get_plate_stock` | ❔ 未实测 | → F5 补探针（G6 轮动前置）|

### 1.3 基本面（核心缺口区，本次全部实测可用）

| 接口 | 实测 | 优先级 | 结论 |
|---|---|---|---|
| `get_financials_statements` | ✅ | **P0** | action 已接，**Facade 未收口** → G1 ⚠️ |
| `get_valuation_detail` | ✅ | **P1** | action 已接，**Facade 未收口** → G1 ⚠️ |
| `get_research_analyst_consensus` | ✅ | **P1** | 已接 → G7 ✅ |
| `get_short_selling_rank` | ✅ 2 行 | **P0** | 已接 → G2 ✅ |
| `get_daily_short_volume` | ✅ 0 行（T-1）| **P0** | 已接，T-1 语义已实现 → G2 ✅ |
| `get_shareholders_*` / `get_corporate_actions_*` | ❔ 未实测 | P2 | → F5 补探针 |

### 1.4 衍生品

| 接口 | 实测 | 结论 |
|---|---|---|
| `get_option_chain` / `get_warrant` | ✅ | 已接 |
| **`get_option_strategy`** | ✅ **已接**（`OPTION_STRATEGY`）| 入参必须**正股/ETF/指数**（非期权 code）→ G4 ✅ |
| **`get_option_volatility`** | ✅ **已接**（`OPTION_VOLATILITY`）| 入参必须**期权 code**（与上者相反）→ G4 ✅ |
| `get_stock_quote` 期权希腊字母 | ✅ | **重要发现**：QUOTE 已直接返回 `implied_volatility` / `delta` / `gamma` / `vega` / `theta` / `rho` → **Greeks 无需自算 BS**，可直取官方口径 |

### 1.5 市场 / 宏观 / 榜单

| 接口 | 实测 | 结论 |
|---|---|---|
| **`get_fed_watch_target_rate`** | ✅ **已接**（`FED_WATCH`）| Tier1 FOMC 隐含概率，现有宏观日历没有这个 → G5 ✅ |
| **`get_heat_map_data`** | ✅ **已接**（`HEAT_MAP`）| 板块热力图，前端刚需 → G6 ✅ |
| `get_stock_filter` | ⚠️ 已接但结构未验 | → F5 |

### 1.6 交易侧（只读实测通过，写操作冻结）

| 接口 | 实测 | 结论 |
|---|---|---|
| `get_acc_list` | ✅ 6 账户 | 只读可用 |
| `order_list_query` / `position_list_query` | ✅ 0 条（未 unlock）| 只读可用，依赖 OMS 解锁 |
| `place_order` / `modify_order` | ⏸️ | 冻结至 OMS 实装 |

---

## 二、功能规划（G 系列 · 按价值排序）

> **定位区分**：F 系列 = 接口接入（管道），G 系列 = 产品功能（水）。**只接管道不算完成**——每个 G 必须打通到前端或 Hermes 可用为止。

### G1 — 真基本面收口（P0，戳破硬伤）

**痛点**：`FUNDAMENTAL` = 行情快照（证据 §0.4）。Hermes 拿不到三大表与历史序列，"零幻觉"红线实际漏风。
**依赖**：`get_financials_statements`（✅）+ `get_valuation_detail`（✅）+ 已接 `SNAPSHOT`
**功能增量**：
- 新 action `FINANCIALS`（三大表）+ `VALUATION`（估值明细）
- **`field_id → 中文字段名` 常量映射表**（Futu 返回数字 id，不映射等于不可用）+ `next_key` 分页
- Facade `get_fundamental` 升级为**三源合并**（快照估值 + 三大表 + 估值明细），**逐字段标注 source**
- Hermes `get_fundamental_data` / `analyze_financial_report` 改取真源
**验收**：问"AAPL 最近 4 季经营现金流"能给出带时间戳的真实序列；`FUNDAMENTAL` 不再单独作为财务结论来源。
**分册**：`TODO-FUTU-FUNDAMENTAL-SCREEN.md` 阶段 P0

### G2 — 港股卖空拥挤度监控（P0，真 alpha）

**痛点**：系统目前**无卖空主源**。空头拥挤度是港股最有效的反转 / 挤空信号之一。
**依赖**：`get_short_selling_rank`（✅ 2 行）+ `get_daily_short_volume`（✅ T-1）+ 已接 `SNAPSHOT`（含 `short_available_volume` / `short_sell_rate`）
**功能增量**：
- 新 action `SHORT_SELLING`（子模式 `rank` | `daily`）
- 派生指标：卖空成交占比、5/20 日 Z-score、拥挤度历史分位
- 接 AlertEngine：占比突破 N 日分位 → 告警（挤空候选 / 崩塌预警）
- 与 HKEX / SFC 监管源交叉验证一致性
**⚠️ 实现红线**：`daily_short_volume` 当日盘后返回 **0 行**，必须按 **T-1 结算**语义处理。把 0 行输出成"卖空为 0"即违反零幻觉——**必须返回"无数据/STALE"**。
**验收**：卖空榜页 + 告警可触发 + 0 行场景返回无数据而非 0。

### G3 — 主力筹码分层与背离信号（P1）

**痛点**：`FUND_FLOW` 只有净流入序列，无法区分"主力吸筹"与"散户接盘"。
**依赖**：`get_capital_distribution`（✅ 8 档 in/out + `update_time`）+ 已接 `FUND_FLOW`
**功能增量**：
- 新 action `CAPITAL_DISTRIBUTION`
- 派生：主力净额 =(super+big) in−out；散户净额 =(mid+small) in−out；**背离信号** = 主力净流入 ∧ 散户净流出（及反向）
- 前端：分层堆叠柱 / 瀑布（ECharts，暗黑配色，AGENTS.md §8.5）
**验收**：背离信号可在复盘中回溯；主力/散户口径写入文档防口径漂移。

### G4 — 期权策略损益实验室（P0/P1）

**痛点**：已有 option_chain，但没有"选腿 → 损益曲线 → 真实 IV"闭环；若 Greeks 自算 BS 会与官方口径打架。
**依赖**：`get_option_strategy`（✅ 正股入参）+ `get_option_volatility`（✅ 期权 code 入参）+ 已接 `OPTION_CHAIN` / `QUOTE`（已含官方 Greeks + IV，见 §1.4）
**功能增量**：
- 新 action `OPTION_STRATEGY` + `OPTION_VOLATILITY`
- **入参互斥校验**（两接口入参正好相反）：传错必须给可读错误，而不是返回空让人以为"没数据"
- 派生：损益曲线（当前 / 到期）、盈亏平衡点、最大盈亏、IV 微笑与期限结构
- Greeks 一律标注 `source=official`，禁止与自算值混用
**验收**：给定正股 + 策略类型能出损益曲线；Greeks 来源可追溯。
**分册**：`TODO-FUTU-OPTION-COMBO-MARKETS.md` 阶段 P0 / P0.5

### G5 — FedWatch FOMC 隐含概率面板（P1）

**痛点**：AGENTS.md §5 Tier1 要求紧盯 FOMC，但现有宏观日历只有事件时间 + 前值/预期，**没有市场隐含概率**。
**依赖**：`get_fed_watch_target_rate`（✅）
**功能增量**：
- 新 action `FED_WATCH` → `business/macro.py` + Facade `get_fed_watch`
- 概率**快照留存**，展示相邻交易日的概率迁移（Δ）——概率变化本身才是信号
- 注入早报模板 Tier1 段（AGENTS.md §7）
- Hermes：回答"市场认为 9 月降息概率多少"必须引用此源
**验收**：早报 FOMC 段带隐含概率 + 数据时间戳；概率迁移可回看。
**分册**：`TODO-FUTU-SEARCH-MACRO.md` 阶段 P1

### G6 — 板块热力图（P1）

**依赖**：`get_heat_map_data`（✅）；板块轮动需 `get_plate_list` / `get_plate_stock` / `get_owner_plate`（**❔ 未实测**）
**功能增量**：新 action `HEAT_MAP`；前端 ECharts treemap（暗黑配色）；数据源 + 更新时间角标。
**范围约束**：**先只做热力图**（单接口即可）。板块成分与轮动强度**必须等 F5 探针验证后**再排期，避免又出现"文档写可用、实际不支持"。
**验收**：热力图页可用 + 数据源/时间标注。

### G7 — 分析师共识 vs 实际「预期差」（P1）

**依赖**：`get_research_analyst_consensus`（✅）+ G1 的 `get_financials_statements`（实际值）
**功能增量**：**不是单接口包装**——共识目标价 / 评级分布 + 实际财报值 → 预期差信号（beat/miss 幅度、评级净上调数）。
**⚠️ 输出红线**：共识是**卖方观点，不是事实**。展示与 Hermes 引用必须显式标注为第三方预期，禁止当作预测结论输出。
**验收**：个股页"共识 vs 实际"对照；引用带来源与更新时间。

### G8 — 数据正确性基座（P1，不炫但是地基）

**依赖（4 项均 ❔ 未实测，需 F5 先验）**：`get_rehab`（复权因子）、`get_trading_days`（交易日历）、`get_history_kl_quota`（K线额度）、`get_market_state`（市场状态）
**为什么值得单列**：
| 接口 | 修什么 |
|---|---|
| `get_rehab` | 复权因子权威来源。回测与技术指标的地基，因子错 = 全部信号错 |
| `get_trading_days` | G2 的 T-1 语义、K线对齐、"今天是否交易日"判定都要它 |
| `get_history_kl_quota` | Futu 历史 K 线有配额；无额度查询 → 批量拉取时静默失败 |
| `get_market_state` | 区分"盘后正常空"与"故障空"（§0.5），消除误报告警与假 STALE |
**验收**：空结果能被正确归因（盘后 / 无数据 / 故障三态可分）；复权因子来源可追溯。

---

## 三、TODO 任务清单

### 优先级与依赖

```
BE-ARCH-08a（主镜像 futu 硬依赖）  ← 未修则新功能无法上线，最高优先
        │
F0（容器侧落地）──> F1..F4（接口接入）──> G1..G7（产品功能）
        │
F5（未实测能力补探针）────────────────> G6 轮动 / G8 全部
```

> **状态基准：2026-08-16 23:30 逐项按代码核实**（非按提交记录推断）。核实口径见每项括注的文件:行号。

### F0 — 容器侧落地

- [x] ~~**F0-1** `connection_manager.py`: `from futu import OpenD` → 新 context 类~~ — **误报撤销**，`connection_manager.py:15-18` 早已是 `OpenQuoteContext`/`OpenSecTradeContext`
- [x] ~~**F0-2** `futu_service` 内部 `OpenD` 引用替换~~ — **误报撤销**，全文无 `OpenD` 类引用
- [x] **F0-3** S1 容器 `socat` 转发固化为 systemd —— ✅ **已有脚本**：`scripts/deploy/docker-gw-forward@.service` 完整 systemd template unit（端口 11111 → 宿主 loopback，含安装/校验说明）。实际 S1 是否已启用为部署动作。
- [ ] **F0-4** S1 容器内经 `data_subservice` 复跑 `_test_futu_local.py` 等价验证 —— **未做**（本机通过 ≠ 容器通过，这条不做则全部落地都只是本机结论）

### F5 — 未实测能力补探针

- [x] **F5-1** 扩 `_test_futu_local.py` —— **已做**：脚本已由 266 行扩至 **533 行**，`get_rehab:410` / `request_trading_days:419`（10.10 实际方法名，非 `get_trading_days`）/ `get_history_kl_quota:431` / `get_market_state:441` / `get_plate_list:378` 均已入列并以 `❔` 前缀标注未定稿
- [ ] **F5-2** 断言升级为**字段级**（行数 + 关键列存在），补验 §0.3 的 `ORDER_BOOK` / `SCREEN_STOCKS` / `daily_short_volume` 三项 —— **未完成**
- [x] **F5-3 硬规则**：未实测能力一律标 ❔，禁止进入 P0/P1 排期 —— 探针已按此执行

### F1 — P0 卖空数据主源（支撑 G2）✅ 全链路完成

- [x] F1-1 卖空 handler
- [x] F1-2 `futu_worker.py:64` `SHORT_SELLING` action（rank / daily 子模式）
- [x] F1-3 `adapters/futu.py:73` capabilities + `router.py:117` action map
- [x] F1-4 **T-1 语义**：`routers/market_fundamental.py:552-560` docstring 明载"daily 模式当日盘后 0 行如实返回 no_data，不输出卖空为 0"
- [x] F1-5 HKEX / SFC 交叉验证（同上端点聚合）

### F2 — P0 财务三大表 + 估值（支撑 G1）⚠️ **管道通、收口断**

- [x] F2-1 `option_fund_handler.py` 补 `get_financials_statements` + `get_valuation_detail`
- [x] F2-2 `field_id → 字段名` 映射表（`option_fund_handler.py`）
- [x] F2-3 新 action `FINANCIALS`（`futu_worker.py:54`）/ `VALUATION`（`:62`）+ capabilities（`adapters/futu.py:71-72`）+ action map（`router.py:114-115`）
- [x] **F2-4 收口**：✅ **已完成**（2026-08-22 复核，v0.4 标注已过时）：`facade.py:490 get_fundamental_merged` 三源合并（futu FINANCIALS+VALUATION / fmp / yfinance）+ `facade.py:814 _fetch_futu_fundamental` 已 `_dispatch("FINANCIALS")`+`_dispatch("VALUATION")` 走真三大表+估值明细。假基本面已戳破。

### F3 — P0/P1 期权策略（支撑 G4）✅ 完成

- [x] F3-1 `get_option_strategy` + `get_option_volatility` 接入
- [x] F3-2 入参互斥校验（正股 vs 期权 code）
- [x] F3-3 全链路：`futu_worker.py:78/84` + `adapters/futu.py:74-75` + `router.py:119-120` + `business/option.py:42/58/73`（含 `get_option_strategy_lab`）

### F4 — P1 资金分布 / FedWatch / 热力图 / 分析师 ✅ 完成

- [x] F4-1 `CAPITAL_DISTRIBUTION`（`futu_worker.py:88` + `business/market.py:49`）
- [x] F4-2 `FED_WATCH`（`futu_worker.py:98` + `router.py:124`）
- [x] F4-3 `HEAT_MAP`（`futu_worker.py:101` + `business/market.py:54`）
- [x] F4-4 `ANALYST_CONSENSUS`（`futu_worker.py:93` + `facade.py:667`，另有 `facade.py:680 get_analyst_vs_actual` 直接支撑 G7）

### G 系列功能任务

- [x] **G1** 真基本面收口 —— ✅ **已完成**（F2-4 已收口：`get_fundamental_merged` 三源合并 + `_fetch_futu_fundamental` 走 FINANCIALS/VALUATION）
- [x] **G2** 港股卖空拥挤度监控 —— 后端 `facade.py:819 get_short_selling` + 端点 `market_fundamental.py:552` + 工具 `short_selling_tool.py` + 前端 `features/data-center/short-selling-panel.tsx`
- [x] **G3** 主力筹码分层与背离 —— `business/market.py:49` + 前端 `features/data-center/capital-distribution-panel.tsx`
- [x] **G4** 期权策略损益实验室 —— `business/option.py:73 get_option_strategy_lab` + 工具 `option_strategy_lab_tool.py` / `option_volatility_tool.py` + 前端 `features/options/option-strategy-lab-panel.tsx`
- [x] **G5** FedWatch 面板 —— 工具 `fed_watch_tool.py` + 前端 `features/options/fed-watch-panel.tsx`
- [x] **G6** 板块热力图 —— 工具 `heat_map_tool.py` + 前端 `features/data-center/sector-heatmap-panel.tsx`。**板块轮动仍未做**（依赖 `get_plate_stock` / `get_owner_plate`，F5-1 已探针但未接入）
- [x] **G7** 共识 vs 实际预期差 —— `facade.py:680 get_analyst_vs_actual` + 工具 `analyst_consensus_tool.py` / `earnings_compare_tool.py`
- [x] **G8** 数据正确性基座 —— ✅ **2026-08-22 完成**：`REHAB` / `TRADING_DAYS` / `MARKET_STATE` / `KL_QUOTA` 四个 action 全链路接入（`quote_handler.py` 4 方法 + service + `futu_worker.py` 4 action + `adapters/futu.py` capabilities + `router.py` 映射）。全部 OpenD 实跑零幻觉：`get_rehab`（复权因子 26 行，30 列 forward/backward_adj_factor）、`request_trading_days`（交易日历 WHOLE，10.10 方法名）、`get_history_kl_quota`（额度 used/remaining+明细）、`get_market_state`（CLOSED/AUCTION，入参 code 列表）。空结果三态归因（§0.5）数据源已就绪。单测 `TestG8DataCorrectness` 7 例全过。

### 本轮剩余清单（按优先级）

| 优先级 | 任务 | 一句话 |
|---|---|---|
| P1 | **F0-4** | 容器内等价验证（部署级，需 S1 环境）；不做则部分"已完成"只是本机结论 |
| P2 | F5-2 | 探针断言升级到字段级 |
| P2 | G6 轮动 | 板块成分接入（依赖 get_plate_stock / get_owner_plate） |

### 验收标准（每个任务通用）

1. 本机 `_test_futu_local.py` 复跑通过（**字段级断言**，非仅无异常）
2. S1 容器内经 `data_subservice` 等价验证通过
3. 跨进程契约测试覆盖（扩 `backend/tests/test_cross_process_contract.py`，防 BE-ARCH-08b 类键名错位复发）
4. 前端或 Hermes 至少一端可用（只接管道不算完成）
5. PR merge（Vibe Coding 即时 commit）

---

## 四、落地检查清单（全链路 10 步，每次接入必做）

> v0.2 的 7 步清单**缺 Facade / API / Hermes / 前端**四层，照它做出来的功能是半截管道。以下为完整链路。

| # | 层 | 落点 |
|---|---|---|
| 1 | 权限验证 | `_test_futu_local.py` 字段级断言（**已实测的免验**）|
| 2 | Handler | `data_subservice/futu_src/<x>_handler.py` |
| 3 | 子服务 Service | `data_subservice/futu_src/service.py` 加 `_route` 包装 |
| 4 | Worker action | `data_subservice/futu_worker.py:36-123` 加分支 |
| 5 | 适配器能力声明 | `backend/services/datasource/adapters/futu.py:57` `capabilities` |
| 6 | 路由 action 映射 | `backend/services/datasource/router.py:97` `_FUTU_ACTION_MAP` |
| 7 | Facade 域方法 | `backend/services/datasource/business/{market,fundamental,option,macro}.py` + `facade.py:187+` |
| 8 | API / Hermes | `backend/routers/*.py` + `hermes_agent/tools/*.py` |
| 9 | 前端 | `frontend/src/features/*`（图表遵守 AGENTS.md §8.5 暗黑配色）|
| 10 | 测试 + 缓存重试 | `@with_global_retry` + `cache_mgr`；单测 + 跨进程契约测试；PR |

**键名红线**（第 4↔6 步之间）：新增入参必须 router 与 worker 双侧同名。`_futu_normalize_params`（`router.py:1303`）只管 `ticker→symbol`，其余键名错位它兜不住。

---

## 五、实测结论摘要（2026-08-16 18:47）

1. 港股 LV2 + 美股对照，**26 项调用全部无异常** → 原"待验证"标记全部解锁
2. **P0 卖空 + P0 财务三大表 + P0 期权策略 + P1 资金分布/估值/共识/FedWatch/热力图** 全部可用
3. **QUOTE 已返回官方 Greeks + IV** → 期权 Greeks 不必自算 BS（本次最有价值的发现之一）
4. `get_option_strategy` 只收正股/ETF/指数，`get_option_volatility` 只收期权 code → **入参正好相反，必须配对校验**
5. `get_fed_watch_target_rate` 可用 → 补上宏观日历缺失的 FOMC 隐含概率
6. 交易只读全通但返回空（未 unlock），OMS 路线明确
7. **纠错**：v0.2 的 F0「`OpenD` 老式 import」阻塞项**不成立**，已撤销
8. **边界**：26/26 只证明"调用不报错"；`ORDER_BOOK` / `SCREEN_STOCKS` / `daily_short_volume` 字段结构仍未验证

---

## 六、参考资料

- 官方行情总览：`https://openapi.futunn.com/futu-api-doc/quote/overview.html`
- 官方交易总览：`https://openapi.futunn.com/futu-api-doc/trade/overview.html`
- 现有实现：`data_subservice/futu_src/`
- Worker 路由：`data_subservice/futu_worker.py`
- 适配器：`backend/services/datasource/adapters/futu.py`
- 主服务路由：`backend/services/datasource/router.py`（`fetch_futu:1209`、`_FUTU_ACTION_MAP:97`、`_futu_normalize_params:1303`）
- Facade：`backend/services/datasource/business/facade.py`
- 架构红线：`docs/23. 业务数据源聚合Facade设计.md`
- **本机实测脚本**：`_test_futu_local.py`
- 分册 TODO：`TODO-FUTU-SEARCH-MACRO.md` / `TODO-FUTU-FUNDAMENTAL-SCREEN.md` / `TODO-FUTU-OPTION-COMBO-MARKETS.md` / `TODO-FUTU-EVENT-CONTRACT.md`

---

## 变更日志

| 日期 | 版本 | 变更 |
|---|---|---|
| 2026-08-22 | v0.5 | **落地状态刷新（逐项按代码核实）**：F2-4/G1 已收口（`get_fundamental_merged` 三源合并 + `_fetch_futu_fundamental` 走 FINANCIALS/VALUATION，假基本面已戳破）；F0-3 已有 systemd 脚本（`docker-gw-forward@.service`）；**G8 数据正确性基座全链路完成**（REHAB/TRADING_DAYS/MARKET_STATE/KL_QUOTA 四 action，OpenD 实跑零幻觉 + `TestG8DataCorrectness` 7 例）。剩 F0-4 容器验证（部署级）/ F5-2 探针字段级 / G6 轮动 |
| 2026-08-16 23:30 | v0.4 | **落地状态刷新（逐项按代码核实）**：F1/F3/F4 + G2~G7 全链路完成（含前端面板）；F5-1 探针已扩至 533 行；`BE-ARCH-08a` 上线阻塞已解除。**遗留三项**：F2-4/G1 收口未做（`facade.py:454` 仍单源，假基本面照旧）、G8 四个基座 action 零落地、F0-3/F0-4 容器侧未验 |
| 2026-08-16 | v0.3 | 功能规划定稿：新增 G1~G8 功能级任务 + F5 补探针；纠正 F0 误报（`connection_manager` 早已 10.10 适配）；标注"26/26 ≠ 字段级验证"；落地清单 7 步 → 10 步全链路；补 §0.4 假基本面代码证据、§0.5 空结果语义陷阱 |
| 2026-08-16 | v0.2 | 本机实测回填（26/26） |
| 2026-08-16 | v0.1 | 初稿：接口能力总览 |
