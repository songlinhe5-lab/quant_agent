# ⚙️ TODO — 回测/策略/交易引擎（拆分自 TODO.md 2026-08-13）

### 回测引擎升级（2026-07-12 新增，对标 QuantConnect LEAN）

> 最大结构性差距：当前策略代码在回测（`backtest_engine`）与实盘（`bot_runtime`）是两套路径，回测结果无法平移到实盘。方案详见 `MASTER_REVIEW.md §7.2 方案一`。

- [x] **[BT-01]** 回测/实盘同构抽象：定义统一 `StrategyContext`（`on_bar`/`on_tick`/`order`/`position` API），策略只写一次；`BacktestDriver`（历史回放）与 `LiveDriver`（Redis 行情流 + OMS 下单）双实现。**必须与 QUANT-01 (VectorBT) 一并设计，避免二次返工** — 📐 **设计已完成（2026-07-12）**：`docs/15. 回测实盘同构引擎设计.md`，拆分为 6 个子任务（依赖：a → b → {c,d} → e → f）：
  - [x] **[BT-01a]** 契约层：`backend/engine/` 骨架（`contracts.py`/`strategy.py`/`context.py`/`clock.py`），Pydantic 契约 + Strategy ABC + Context Protocol + SimClock/WallClock（~350 行，测试 ≥90%）✅ **49 tests**
  - [x] **[BT-01b]** BacktestDriver + SimBroker：撮合逻辑从 `event_engine` 平移 + PIT/幸存者偏差接线（DQ-01/02 首次进回测）+ RunManifest 填充（~400 行，测试 ≥80%，依赖 a）✅ **21 tests**
  - [x] **[BT-01c]** VectorBT 快路径 + 同构校验器（**= QUANT-01**）：`signals()` 执行计划 + 事件/矢量双轨一致性 CI 契约测试（3 组 Golden fixture）（~350 行，测试 ≥80%，依赖 b）✅ **9 tests**
  - [x] **[BT-01d]** ExecutionGateway + OmsExecutionAdapter：三级安全锁（`REAL_TRADE_EXECUTE`/`trading_mode`/kill_switch）+ OMS 落库 + Futu 下单 + `OrderStatus` 枚举收口 + 幂等（~300 行，测试 ≥85%，依赖 a，与 c 并行）✅ **15 tests**
  - [x] **[BT-01e]** LiveDriver：行情总线订阅（Protobuf）+ 降级轮询 + tick→bar 聚合（断点续聚）+ `to_thread` 隔离 + paper 模式（PT-01 前置）（~400 行，测试 ≥60%，依赖 b+d）✅ **18 tests**
  - [x] **[BT-01f]** 迁移收口：`adapters/legacy.py` 旧契约适配 + 路由 `engine=v2` 开关（`ENGINE_V2_ENABLED`）+ `deploy-to-oms` 新契约生成 + 存量 3 个 live 策略改写 + 双跑对账（~300 行，测试 ≥70%，依赖 c+d+e）✅ **10 tests**
- [x] **[BT-02]** 回测可复现性：回测报告绑定（策略代码版本 hash + 数据快照版本 + 参数 + 随机种子），同输入必得同输出；报告持久化 PostgreSQL — **依赖 DQ-03c**（`data_snapshot_id` + `manifest_hash` 引用链），详见 `docs/19 §九` · 前端徽章见 **FE-PROD-04** ✅ **2026-07-13**：`RunManifest` 扩展 manifest_hash/data_mode/reproducible；`backtest_reports` + `data_snapshots` ORM；`BacktestReportService` 持久化；`POST/GET /api/v1/backtest/reports`；同输入同输出 CI 契约（`test_backtest_reproducibility_bt02.py` 14 tests）。**注**：完整 SnapshotReader 读 Parquet 仍属 **DQ-03c**；BT-02 已接 DQ-03a 地基 + resolver 引用链
- [x] **[BT-03]** Walk-Forward 滚动验证：滚动窗口训练/验证拆分，检测策略性能漂移（从 P3 提级，回测可信度依赖此项）✅ **2026-07-13**：`engine/walk_forward.py`（窗口生成 + VectorExecutor 折跑 + IS/OOS 漂移检测）+ `app/walk_forward_app.py` + `POST /api/v1/backtest/walk-forward`；可选样本内 `param_grid`；`test_walk_forward_bt03.py` 15 tests
- [x] **[BT-04]** 蒙特卡洛压测：交易序列重排/自助抽样 1000 次路径，输出 5%/50%/95% 分位数曲线 + 最坏回撤（`docs/01 §5.4` 设计）✅ **2026-07-13**：`engine/monte_carlo.py`（trade_reshuffle / trade_bootstrap / return_bootstrap）+ `app/monte_carlo_app.py` + `POST /api/v1/backtest/monte-carlo`；交易不足自动降级日收益自助抽样；`test_monte_carlo_bt04.py` 14 tests
- [x] **[BT-05]** 参数网格搜索：参数范围设定 → `ProcessPoolExecutor` 并发 N 组回测 → 夏普比率热力图矩阵（ECharts heatmap）✅ **2026-07-13**：`engine/grid_search.py`（笛卡尔积 + ProcessPool + 夏普 heatmap/echarts_data）+ `app/grid_search_app.py` + `POST /api/v1/backtest/grid-search`；`test_grid_search_bt05.py` 11 tests
- [x] **[BT-06]** 过拟合检测：Deflated Sharpe Ratio + 参数敏感性报告（相邻参数格性能悬崖 = 过拟合警告）✅ **2026-07-13**：`engine/overfit.py`（Bailey DSR + 邻格悬崖）+ `app/overfit_app.py`（复用 BT-05 网格）+ `POST /api/v1/backtest/overfit`；`test_overfit_bt06.py` 11 tests


### 策略实验室落地（2026-07-12 新增，对标 QuantConnect IDE）

> 📐 **架构设计已完成（2026-07-12）**：`docs/16. 策略实验室完整架构.md`（V1.0）。摸底修正：前端已非单文件（三栏骨架已拆分），真实差距是 Store 未拆 Slice、AI 全路径直接覆盖无 Diff、版本仅文件系统、错误契约非结构化。通过「契约双轨过渡」（docs/16 §八）与 BT-01 排期解耦，不阻塞启动。任务按设计文档 §七 重述如下（依赖：01a → {02, 03a} → {03b, 04}，05 依赖 01a）：

- [x] **[STRAT-01a]** Store 拆分 + Topbar 接线 + 行数红线治理：单 `useStrategyStore` → 4 Slice（editor/ai/backtest/layout）；Topbar 三按钮接线为 Slice action；拆分 `backtest-report.tsx`(684行)/`right-sidebar.tsx`(416行) 至 ≤300 行，补 debug_logs Tab（~400 行，测试 ≥80%）
- [x] **[STRAT-02]** AI Diff 工作流：`ai.slice` Diff 状态机（idle→streaming→pendingDiff→applied）+ Monaco DiffEditor 覆盖层 + **四条来源路径收口**（AI Chat / Auto-Fix / AST 修复 / Hermes CustomEvent 全部经 [Apply] 确认，`setCode` 降为内部实现）；空编辑器例外直落（~350 行，测试 ≥85%，依赖 01a）
- [x] **[STRAT-03a]** 版本存储后端：`strategies` + `strategy_versions` 不可变快照表（Alembic）+ `strategy_version_service` + save/versions/restore/deploy 四端点改造（保存即版本、恢复即新版本、**deploy 只认 version_id** + 溯源注释）+ drafts 文件一次性导入；`code_hash` 与 `docs/15 RunManifest` 同算法（~400 行，测试 Service ≥80% / Router ≥70%，与 02 并行）
- [x] **[STRAT-03b]** 版本时间线前端：左侧栏时间线（seq/来源徽章/message/hash）+ 版本预览复用 Diff 状态机（source=version-restore）+ 一键恢复经 Diff 确认；预留 BT-02 回测摘要反查插槽（~250 行，测试 ≥70%，依赖 02+03a）
- [x] **[STRAT-04]** Auto-Debug 闭环：后端错误契约结构化（`error_code` 枚举 + `error_detail{exc_type/lineno/traceback/debug_tail}`，同步登记 docs/10）+ 前端结构化终端（行号跳转 Monaco 定位）+ FixContext 投喂（fix prompt 模板入 `prompts/`，注入沙箱约束清单防二次撞 AST 审查）+ 修复后一键重跑验证 + 同 errorRef 3 次熔断（~400 行，测试后端 ≥85% / 前端 ≥70%，依赖 02）
- [x] **[STRAT-05]** 参数面板收尾：`use-sandbox-run.ts`（AbortController 竞态取消 + 300ms debounce）+ 重跑 loading 蒙层 + parse-config 新旧契约双轨支持预留（~150 行，测试 ≥80%，依赖 01a）

### 纸面组合追踪（2026-07-12 新增，对标 QC Paper Trading）

> 当前沙箱只能单次推演。业界惯例：策略上实盘前必须有持续运行的纸面绩效档案，这是过拟合的最后一道防线。
> 📐 **架构设计已完成（2026-07-13）**：`docs/17. 纸面组合系统架构.md`（V1.0）。核心决策：PG 流水账本 SSOT（`paper_fills` 只增 + 持仓可重放重建）、EOD 结算数据驱动判定交易日（绕开无节假日表缺口）+ 补结算自愈、回测对比按交易日序号对齐 + TE 归因、偏离告警复用 ALERT-01 引擎。任务按设计文档 §八 拆分如下（依赖：01a → 01b → 01c → 02a → 02b；01a/01c/02a 不依赖 BT-01 可先行，01b 依赖 BT-01d/e）：

- [x] **[PT-01a]** 账本与数据模型：`paper_portfolios`/`paper_fills`/`paper_positions`/`paper_nav_daily` 四表（Alembic）+ `paper_ledger_service`（fill_seq 分配 / 持仓投影 / 重放重建）+ `quant:paper:*` Redis 键空间（~350 行，测试 ≥85%，无依赖可立即启动）✅ **17 tests**
- [x] **[PT-01b]** 执行接线：SimBroker paper 行为差异（stale 拒单 / 交易时段检查 / 现金持仓约束）+ Fill→Ledger 同步落库 + 重启恢复 + 创建组合 API（paper Bot 部署）（~400 行，测试 ≥80%，依赖 01a + **BT-01d/e**）✅ **8 tests**
- [x] **[PT-01c]** 结算 daemon：PaperSettlementDaemon 挂 worker.py——盘中快照（Redis 环形 288 点）+ EOD 结算（kline_warehouse 收盘价 / 停牌前收兜底 + stale 标记）+ ≤7 天补结算自愈 + 周度重放对账（~350 行，测试 ≥80%，依赖 01a）✅ **16 tests**
- [x] **[PT-02a]** 绩效与对比后端：`performance.py` 共享绩效库抽取（sharpe/mdd/TE 纯函数，回测三处内联后续切换）+ compare API（序号对齐 / TE / 信号一致率+成交偏离归因）+ benchmark 快照双轨（BT-02 前 Redis / 后外键）+ AlertEngine `paper_drift` 规则类型（~400 行，performance ≥90% 其余 ≥80%，依赖 01c）✅ **35 tests**
- [x] **[PT-02b]** 前端页面：`features/paper/` 全套（AG Grid 列表 / 净值图盘中虚线+日终实线 / 对比叠加图复用 SandboxChart 模式 / 偏离面板）+ deploy-to-oms 实盘前检查点文案（纸面天数/Sharpe/TE 三项硬数据展示）（~400 行，测试 ≥70%，依赖 02a）✅ **8 tests**


### 策略与量化

- [x] **[QUANT-01]** 集成 VectorBT 极速回测引擎（替换手动循环，支持 Numba 矢量化）——**已并入 BT-01c 统一设计与实施**（见 `docs/15` §4.2），本条不再单独排期 ✅
- [x] **[QUANT-02]** Screen-to-Backtest 一键流程：选股结果直接进入组合回测 → 绩效报告 Tear Sheet（依赖 BT-01）✅ **4 tests**
- [x] **[QUANT-03]** 复杂横截面选股：Pandas 内存引擎支持 `RSI(14) > KDJ.K` 等跨指标表达式 ✅ **11 tests**
- [x] **[QUANT-04]** 盘中实时 CEP 异动筛选（基于 WebSocket 流的微秒级内存事件引擎）✅ **5 tests**

### AI 能力

- [x] ~~**[AI-01]** Multi-Agent 深度研报：聚类发现 Agent + 数据深挖 Agent + 图表交付 Agent 三段流水线~~ ✅ **2026-07-13**（`DeepResearchPipeline` + 三段流水线 + API + 前端面板 + 8 tests）
- [x] ~~**[AI-02]** AI 驱动因子挖掘：LLM + 网格搜索，自动推荐胜率最高的参数组合~~ ✅ **2026-07-13**（`FactorMiner` + LLM 建议 + grid search + API + 前端面板 + 7 tests）
- [x] ~~**[AI-03]** 集成 Microsoft Qlib DataServer 高性能时序数据湖 + Alpha158 因子库~~ ✅ **2026-07-13**（`Alpha158` 40+ 因子 + `FACTOR_REGISTRY` + API + 前端面板 + 22 tests）

### 交易进阶

- [x] **[TRADE-01]** 高级期权筛选器：IV Rank、波动率微笑、Greeks (Delta/Gamma/Vega) 筛选 ✅ **2026-07-14**（`options_engine.py` BS定价+Greeks+IV+微笑 · `options_screener.py` 筛选服务 · `routers/options.py` 4端点 · `options-screener-panel.tsx` 前端 · 14 tests）
- [x] **[TRADE-02]** TWAP / VWAP 算法拆单执行，降低大单冲击成本 ✅ **2026-07-14**（`algo_engine.py` +MarketImpactModel +POV/IS算法 · `algo_analytics.py` 执行分析 · `oms.py` +analytics端点 · `algo-analytics-panel.tsx` 前端 · 41 tests）
- [x] **[TRADE-03]** 投资组合优化：风险平价 / 马科维茨模型自动输出仓位权重 ✅ **2026-07-14**（`portfolio_optimizer.py` Markowitz+风险平价+MaxSharpe+有效前沿+模型对比 · `routers/portfolio.py` 3端点 · `portfolio-optimizer-panel.tsx` 前端 · 13 tests）

