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

### 量化研究进阶能力（2026-08-23 新增，docs/01 V2.5 业界对标规划）

> 四个新任务序列，产品定义见 `docs/01 §二十五~§二十八`，实现架构见 `docs/24~27`。红线：研究类计算一律绑定 `data_snapshot_id`（禁 live 数据出结论）；数字结论必须可溯源；覆盖率 ≥80%。
> 优先级：FACT / TCA = P2（下季度）；EVT / RMOD = P3（长期）。

#### 因子研究平台（FACT · P2 · 📐 docs/24）

> 补齐「有因子生产（AI-02/03）、无因子验证」缺口；对标 Alphalens。依赖：01 → 02 → 03 → 04 → 05。

- [ ] **[FACT-01]** 因子面板计算 + IC 分析：`domain/factor_lab/panel.py`（T×N 截面，复用 Alpha158）+ `ic.py`（Pearson/Rank IC × 前向 1/5/20 日 + 累计 IC/IR/胜率 + 截面覆盖率哨兵）（~350 行，测试 ≥80% 含 golden case，依赖 DQ-03 快照读取）
- [ ] **[FACT-02]** 分层回测 + 中性化：`quantile.py`（等权 5 分位逐日调仓净值 + 多空价差 + 换手率）+ `neutralize.py`（对数市值/行业截面回归取残差）（~300 行，测试 ≥80%，依赖 FACT-01）
- [ ] **[FACT-03]** 因子库版本化：`factor_registry` PG 表（版本/血缘/IC 摘要）+ `routers/factor_lab.py` 全端点（analyze/report/registry/lineage）（~250 行，测试 ≥80%，依赖 FACT-02）
- [ ] **[FACT-04]** 前端报告面板：策略实验室新 Tab（IC 时序/分层净值族/相关性热力/中性化对比）+ AG Grid 因子库（~300 行，测试 ≥70%，依赖 FACT-03）
- [ ] **[FACT-05]** 联动闭环：选股器条件引用已入库因子 + §二十一 挖掘结果一键送分析（~150 行，依赖 FACT-04）

#### 执行质量分析（TCA · P2 · 📐 docs/25）

> 三层账本（回测/纸面 `paper_fills`/实盘 OMS）按 `signal_id` 对齐，量化执行损耗并反向哺回测滑点参数；对标 Bloomberg EMSX。依赖：01 → 02 → 03 → 04；先决：PT-01（✅）+ BT 成交明细。

- [ ] **[TCA-01]** 信号对齐：`signal_id` 规范（策略版本+标的+信号时刻+方向）+ `services/tca/aligner.py`（±5s 容错窗）+ `tca_fills` 派生表迁移（含回测成交补 signal_id）（~300 行，测试 ≥80%）
- [ ] **[TCA-02]** 指标计算：`domain/tca/metrics.py`（实施缺口/三段分解/机会成本/层间 NAV 偏差，纯函数）（~250 行，测试 ≥90% 含手工样例对照，依赖 TCA-01）
- [ ] **[TCA-03]** 端点 + 增量触发：`routers/tca.py`（summary/fills/slippage-hist/apply-backtest-default/recompute）+ 增量计算（禁全量重算）+ `REAL_TRADE_EXECUTE` 门禁（L3 未开启显式置空）（~250 行，测试 ≥80%，依赖 TCA-02）
- [ ] **[TCA-04]** 前端 OMS Tab：三层 NAV 叠加/滑点直方（>3σ 标红）/逐笔偏差 AG Grid + 实测滑点一键设为回测默认参数（留审计）（~300 行，测试 ≥70%，依赖 TCA-03）

#### 事件驱动研究（EVT · P3 · 📐 docs/26）

> 把已有日历数据（§16/§20）从「提醒」升级为「可回测规律」；对标 FactSet Events。依赖：01 → {02, 03} → 04；样本 < 30 禁出统计结论。

- [ ] **[EVT-01]** 事件归一：`event_registry` 表 + 三日历源（财经/财报/分红IPO）归一为 `EventRecord`（类型/日期/严重度/来源/快照）（~250 行，测试 ≥80%，无依赖可先行）
- [ ] **[EVT-02]** 研究引擎：`domain/event_study/engine.py`（事件时间对齐 + 市场/行业调整异常收益 + CAR/CAAR + bootstrap 置信带）+ `pead.py`（SUE 分位漂移）（~400 行，测试 ≥80% 含 golden，依赖 EVT-01 + DQ-03 快照）
- [ ] **[EVT-03]** 持仓暴露扫描 + 告警：`exposure.py`（持仓/纸面 × 未来 N 日事件，高危 + 仓位阈值 → AlertEngine P2 通道）（~200 行，测试 ≥80%，依赖 EVT-01 + ALERT 引擎）
- [ ] **[EVT-04]** 前端数据中心 Tab：事件窗口曲线/样本明细/暴露时间轴/PEAD 漂移 + 统计结论一键生成策略草稿（流转 §四，仅草稿）（~300 行，测试 ≥70%，依赖 EVT-02/03）

#### 组合风险模型进阶（RMOD · P3 · 📐 docs/27）

> 模型层（供 §七 展示层 / §二十三 优化器 / §十 告警消费），与 `RISK-02~08` 分工不重复；对标 Barra 简化版 + Bloomberg PORT。依赖：01 → {02, 03} → 04。

- [ ] **[RMOD-01]** 因子构建 + 协方差估计：`domain/risk_model/factors.py`（市场/行业/风格因子收益）+ `cov.py`（因子协方差 + 对角特异风险，Ledoit-Wolf 收缩可选）（~350 行，测试 ≥85%，依赖 DQ-03 快照 + §二十一 因子体系）
- [ ] **[RMOD-02]** 风险分解 + 预算：`decompose.py`（MCTR/CTR 持仓×因子两级，勾稽误差 <1% 内置断言）+ 预算检查端点（超支可联动告警）（~250 行，测试 ≥85%，依赖 RMOD-01）
- [ ] **[RMOD-03]** Black-Litterman：均衡收益 + 观点融合（置信度必填 → Ω 映射，AI 观点强制溯源；极端情形收敛性 golden case）（~300 行，测试 ≥85%，依赖 RMOD-01）
- [ ] **[RMOD-04]** 前端进阶 Tab + 优化器接入：风险瀑布/协方差热力/预算条/观点表单 + `/portfolio/optimize` 可选 `model_id`（不破坏现有接口）（~300 行，测试 ≥70%，依赖 RMOD-02/03）

### 公司财报看板（FIN · P2 · 📐 docs/28 · 2026-08-31 新增）

> 产品定义 `docs/01 §二十九`，实现架构 `docs/28`。补齐「只有二手快照式基本面、无一手申报事实层」缺口；对标 SEC EDGAR XBRL + Koyfin/TIKR + Daloopa。
> 红线：一手采集只允许在 `data_subservice`；回测/因子只读 `value_as_reported` + `filed_at <= as_of`；缺失科目置空禁补 0；LLM 抽取值必须带 `source_page`。
> 依赖：01 → 02 → 03 → {04 → 06, 05} → 07；08 与主链并行。**建议先做 01~03**，事实层脏则上层全部推倒重来。

- [x] **[FIN-01]** 一手采集：`data_subservice/filings_worker.py` + `_internal/sec_edgar.py`（`submissions` / `companyfacts` / `frames` 三端点）+ 披露易 `titleSearchServlet` + 巨潮 `hisAnnouncement`；描述性 UA + ≤10 req/s 限流 + fixture 锁响应结构（~400 行，测试 ≥80%，禁打真实外网）✅ **40 tests**（2026-08-31；`main.py` 注册 `source=filings`，能力声明 `DS_CAPABILITIES=...,filings`，部署须配 `SEC_EDGAR_USER_AGENT`）
- [x] **[FIN-02]** 归一化引擎：`domain/financials/concept_map.json`（声明式标签链，禁服务层 if-else）+ `mapper.py` + `periods.py`（YTD 拆分 / Q4=FY−9M）+ `checks.py`（三表勾稽）（~450 行，测试 ≥85% 含 20 家 golden case，依赖 FIN-01）✅ **96 tests / 覆盖率 98%**（2026-08-31；35 个标准科目 × 4 taxonomy；golden 21 家含 us-gaap 12 家 + ifrs 4 家 + tushare 4 家 + futu 1 家；`split_ytd` 无 9M 时只出 H2、禁把 H2 当 Q4；勾稽失败只标 `check_failed` 不丢数。⚠️ `ifrs-full` / `tushare` / `futu` 三条链在 `concept_map.json` 里标 `verified: false`，接真源前须实测校对；futu 以 `display_name`（中文）为 key，`field_id` 是整数不可作键——见 `option_fund_handler` 实测注释）
- [x] **[FIN-03]** 双时间轴存储：`financial_facts` / `filings` PG 迁移（唯一键 `entity+concept+start+end+unit`，**禁按 fy 去重**）+ PIT 查询 + Parquet 宽表接 docs/19 快照（~350 行，测试 ≥85%，依赖 FIN-02）✅ **18 tests / 覆盖率 100%**（2026-08-31；迁移 `fin03a`（`down_revision=pt01a`）；`core/financials_models.py` + `services/financials/{repository,parquet_store}.py`。⚠️ 两处需知：① 时点科目 `period_start` 为 NULL，而 PG 的 NULL 互不相等会让唯一约束失效，故加非空列 `period_start_key`（时点值写 `""`）承载唯一键，写入时两列须同步；② PIT 取值三档（`repository.pit_value`）：`as_of < 首次披露` → 不可知；`首次披露 ≤ as_of < 重述` → 只给 `as_reported`；`as_of ≥ 重述` → 给 `latest`。**现有内存 `financial_pit.PointInTimeStore` 未替换**，回测侧调用方切换放到 FIN-04 接入时做，本次不波及回测）
- [ ] **[FIN-04]** Facade 收口 + `routers/financials.py` 全端点（statements/facts/analytics/peers/filings/restatements/backfill）+ 回填走进程池（~300 行，测试 ≥80%，依赖 FIN-03）
- [ ] **[FIN-05]** 分析引擎：`domain/financials/analytics.py`（common-size / TTM / DuPont / 现金流质量 / Piotroski F · Altman Z · Beneish M，须输出分项）（~350 行，测试 ≥85% 含手算对照，依赖 FIN-03）
- [ ] **[FIN-06]** 同业与行业：peer set 解析（SIC / 申万 / Futu 板块 + 手工固定）+ EDGAR `frames` 截面分位 + 行业聚合（样本 <8 禁出分位结论）（~250 行，测试 ≥80%，依赖 FIN-04）
- [ ] **[FIN-07]** 前端 `features/financials/`：报表 AG Grid（含 common-size 与口径切换）/ 趋势 / DuPont / 同业散点 / 质量记分卡 / 归档时间轴 / 重述 diff（~500 行分 7 组件，测试 ≥70%，依赖 FIN-05/06）
- [ ] **[FIN-08]** 文本层：MD&A 与风险因素逐年 diff（Lazy Prices 依据）+ 港A PDF 定点抽取强制 `source_page`/`source_text` + RAG 引用跳回原文（~300 行，测试 ≥75%，依赖 FIN-01 + 既有 RAG）
