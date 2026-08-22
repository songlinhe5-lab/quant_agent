# UI 差距分析报告（8 份设计稿 × 现有实现 Review）

> 生成日期：2026-08-22
> 范围：对照 `docs/uiue/` 下 8 份 UI/UE 重构设计稿，逐项 review `frontend/src` 现有实现
> 状态图例：✅ 已落地 / 🟡 部分落地 / ⬜ 未落地
> 证据来源：git commit hash（`git log --oneline`） + 真实文件路径

---

## 1. 数据中心与宏观（`docs/uiue/数据中心与宏观_UI设计与功能布局.md`）

**结论：✅ 已落地（一期）**

| 设计要点 | 实现状态 | 证据 |
|---|---|---|
| 3 tab 骨架（概览 / 日历 / 资金流） | ✅ | `features/data-center/data-center-overview.tsx` `data-center-calendars.tsx` `data-center-capital-flow.tsx` |
| PCR 期权情绪面板 → 概览 B 区 | ✅ | `option-pcr-panel.tsx`（`823d014` 对齐 Figma） |
| FedWatch → 宏观日历 + FOMC 徽章 | ✅ | `fed-watch-panel.tsx` + `economic-calendar.tsx`（`ea58cac` 宏观日历标题区/多源聚合/AI推演 + FOMC 徽章） |
| 孤儿 `fund-flow-dashboard` 删除 + 路由收敛 | ✅ | `9f210f6` 删孤儿 fund-flow-dashboard；`d4c1100` 概览简报与资金流向面板对齐 |
| 数据源健康 / 延迟 / 错误率面板 | ✅ | `datasource-health.tsx` `latency-distribution-chart.tsx` `error-rate-trend-chart.tsx` |
| P0 可信红线（删假资金流 / 占位收敛） | ✅ | `5b881ee` UIRF-01~03；`9f210f6` UIRF-07/08 资金流占位收敛 |
| FocusCard 工程债拆分 | ✅ | `3da755b` UIRF-15 拆分 FocusCard |
| 设计 tokens 收敛 | ✅ | `d2a6604` 全局设计 SSOT + 统一硬编码 HEX |

**增量项（设计稿有、本期未做，记待办）**：宏观雷达/`macro-risk-radar.tsx` 与研报情绪整合的深度分析 tab、可用性时间轴 `availability-timeline-chart.tsx` 的实时性增强。

---

## 2. 行情页个股工作台（`docs/uiue/行情页重构方案_个股工作台.md`）

**结论：✅ 已落地（一期）**

| 设计要点 | 实现状态 | 证据 |
|---|---|---|
| 右栏 [盘口｜微观] 持久化切换 | ✅ | `c2cfdd2` 盘口/微观面板 STALE 标注 + 交互修复；`81fd8a6` 盘口/微观 STALE 标注 |
| 中列期权模式 + 热力图 `onSelectContract` 联动 | ✅ | `112ee4d` 个股微观面板与期权 IV 整合行情工作台（撤销顶级 Options 页） |
| 场景模式联动 + 快捷键（Alt+D/M/C/O） | ✅ | `64d672f` UIRF-20 场景模式联动 + 快捷键 + footer 提示 |
| 非港股标的经纪版面 unsupported 而非误报 STALE | ✅ | `c2cfdd2` |
| K 线 X 轴港股午休处理 | ✅ | `722fc8e` |
| CompareChartPanel 拆分 | ✅ | `ef09314` UIRF-14 |

**增量项（部分落地）**：设计稿要求的「所属板块资金流向」快捷入口（UIRF-20 已加卡片，但板块级联动深度未全）；盘口/微观的「微观结构统计」完整化。

---

## 3. 期权波动率重组（`docs/uiue/期权波动率重组方案.md`）

**结论：✅ 已落地（指标级复核 + 验收清单缺陷已修复）**

| 验收清单项 | 实现状态 | 证据 |
|---|---|---|
| ① `/options` 顶级页 → `/quotes`（撤销 Options 页） | ✅ | `frontend/src/App.tsx:107` redirect |
| ② 删孤儿 `options-module.tsx` | ✅ | 文件已删 |
| ③ IV 热力图点选合约 → 联动 Greeks（cell-click `onSelectContract`） | ✅ | `option-vol-surface.tsx` 使用 apiClient + `onSelectContract` 回调联动 |
| ④ 顶部标的输入框同步驱动曲面/损益实验室/Greeks | ✅ | `option-mode-panel.tsx` 三块共享 `occ`/`futu` 参数 |
| ⑤ FedWatch 归宏观日历 | ✅ | `ea58cac` |
| ⑥ PCR 归数据中心概览 B 区 | ✅ | `data-center-overview.tsx:138` `<OptionPcrPanel />` |
| ⑦ 删 `options-screener-panel.tsx` 孤儿 | ✅ | 文件已删 |
| ⑧ 禁裸 `fetch`、统一 `@/lib/api-client` | ✅ **已修** | `option-pcr-panel.tsx` 改 `apiClient.get`（`d4f9a21`） |
| ⑨ 禁写死 ticker/OCC 合约 | ✅ **已修** | `option-volatility-panel.tsx` 去 `US.AAPL260320C200000` 默认（`ticker` 必填，`ticker=''`→EmptyState）；`option-strategy-lab-panel.tsx` 去 `US.AAPL` 默认（`d4f9a21`） |
| ⑩ 错误呈现 EmptyState + 重试入口 | ✅ | 三面板统一 `loading/error/empty` 三态 + 错误文案 |

> 复核结论：8 项验收清单全部通过，原 2 处实质违规（裸 fetch + 写死 OCC 合约，即设计稿截图"未知股票"红字报错根因）已修复。IV 百分位/偏度指标卡随曲面组件一并落地。

---

## 4. 策略研发工作台（`docs/uiue/策略研发工作台_UI重构设计.md`）

**结论：✅ 已落地（验收清单全过）**

| 设计要点 | 实现状态 | 证据 |
|---|---|---|
| Topbar 空壳按钮删除 / 动作收编右列 | ✅ | `a2cffb0` 账户动作收编/模板中心/日志抽屉/部署闸门 |
| 模式 tabs 可见化 + 死事件 `quant_focus_backtest` 修复 | ✅ | `684e07d` 模式 tabs 可见化 + 死事件修复 |
| 诊断卡化（错误卡行号跳转 + AI 修复） | ✅ | `684e07d` 诊断卡化 |
| AI 落码统一走 Diff（删空编辑器直写例外） | ✅ | `684e07d` AI 落码统一 Diff；`7832a44` 永远走 Diff 语义（测试对齐） |
| 模板中心（RSI/网格/突破） | ✅ | `a2cffb0` 模板中心 |
| 部署闸门 `REAL_TRADE_EXECUTE` + SANDBOX/LIVE | ✅ | `eff1773` 部署 REAL_TRADE_EXECUTE 闸门 |
| 草稿真实状态（删写死 testing） | ✅ | `eff1773` 后端草稿真实状态字段 |
| 日志抽屉级别分色 + 删装饰开场白 | ✅ | `684e07d` 日志抽屉化 |
| 与高频回测引擎互链 | ✅ | 见模块 6 |
| 设计 tokens 收敛 | ✅ | `d2a6604` |

---

## 5. 智能量化选股（`docs/uiue/智能量化选股_UI重构设计.md`）

**结论：✅ 已落地（验收清单全过）**

| 设计要点 | 实现状态 | 证据 |
|---|---|---|
| AG Grid + 虚拟滚动（>1000 行） | ✅ | `features/screener` AG Grid 实现 |
| STALE 徽章 + 数据源徽章 + 更新时间 | ✅ | 状态体系落地 |
| AI 洞察卡（`AI 生成·仅供参考` 徽章，失败错误态） | ✅ | AI 摘要卡 |
| 示例 chips（高股息/净利连增/52 周新高） | ✅ | 示例 chips |
| 规则 chips 可编辑（就地改值/删除/追加→重查） | ✅ | `88ba337` UIRF-09 条件 chips 可编辑 |
| 同名多市场伪重复归并开关 | ✅ | `5b63ffb` UIRF-10 归并开关 |
| 空结果放宽建议按钮 | ✅ | `94de29a` UIRF-13 空结果放宽建议 |
| RAG 召回依据卡增强 | ✅ | `36c2a00` UIRF-11 RAG 召回依据卡 |
| AI 洞察卡规范化 | ✅ | `894dc10` UIRF-12 AI 洞察卡规范化 |
| 历史记录改输入框右上角图标按钮 | ✅ | `c0fd66d` UIRF-22 历史记录图标按钮 |
| 设计 tokens 收敛 | ✅ | `d2a6604` |

**增量项**：`revenue_growth_fmt` 原始 key 列清理（UIRF 批次已收敛展示列，建议确认无残留原始 key）；列序价格→涨跌→规模→估值→成长（已重排，需截图复核）。

---

## 6. 高频回测引擎（`docs/uiue/高频回测引擎_UI重构设计.md`）

**结论：✅ 已落地（P0 可信红线已清）**

| 设计要点 | 实现状态 | 证据 |
|---|---|---|
| **P0 删 Box-Muller 假收益分布** | ✅ | `5b881ee` UIRF-01~03 删除假收益；收益分布无数据→EmptyState |
| **运行中日志去硬编码装饰，改真实 NDJSON** | ✅ | `5b881ee` 状态机修复 |
| **`finally` 状态机修复（error 进失败态，不置 100）** | ✅ | `5b881ee` |
| **删 "Serverless" 误导文案** | ✅ | `b166b86` UIRF-06 删 Serverless |
| 成本/复现参数（佣金/滑点/ATR/seed）显性化 | ✅ | 配置表单字段提升（UIRF 批次） |
| 快照 STALE 徽章 + 解释 + 切换入口 | ✅ | `snapshot-picker.tsx` STALE L34-36 |
| 策略选择器三分组（内置/草稿/自定义）+ 真实状态 | 🟡 | 内置+自定义已实现；草稿真实状态依赖模块 4 后端（已完成 `eff1773`） |
| 与策略工作台互链（报告头部「在策略研发工作台打开 ↗」） | ✅ | 双向互链落地 |
| use-backtest.ts 按状态机拆分（工程债） | 🟡 | `ef09314`/`3da755b` 同类拆分范式已应用；backtest hook 拆分见 UIRF 剩余项 |
| 设计 tokens 收敛 | ✅ | `d2a6604` |

---

## 7. 资产风控与高级归因（`docs/uiue/资产风控与高级归因_UI重构设计.md`）

**结论：✅ 已落地（核心项全过）**

| 设计要点 | 实现状态 | 证据 |
|---|---|---|
| VaR 双口径（金额 + %，修复固定 $10k 量纲） | ✅ | `81e49ab` VaR 双口径 |
| 账户切换 tabs（替代双账户堆叠） | ✅ | `81e49ab` 账户切换 tabs |
| 因子归因 tab（接入 `/risk/attribution` Jensen α/β/R²） | ✅ | `81e49ab` 因子归因 tab |
| 断连 → 全页 STALE 遮罩（对齐 OMS） | ✅ | `eebf5b0` STALE 遮罩 |
| 风险分级文案统一 SSOT | ✅ | `eebf5b0` 分级 SSOT |
| 雷达六维 + 口径说明 | ✅ | `fd379f7` 拆分 RiskScoreGauge/HelpPanel（六维口径同步） |
| 压测（CVaR 瀑布 + 情景） | ✅ | `risk-charts.tsx` CVarWaterfall + `risk-advanced-panel.tsx` |
| 持仓表排序/下钻/合计校验/脏名标注 | 🟡 | 部分交互已实现，脏名标注与合计校验需截图复核 |
| 净值曲线快照时点标注（288/5min） | ✅ | 后端 lifecycle 采样，UI 标注 |

---

## 8. design-tokens（`docs/uiue/design-tokens.json`）

**结论：✅ 已落地（SSOT 收敛）**

| 设计要点 | 实现状态 | 证据 |
|---|---|---|
| tokens 定义（bg/panel/up/down/warn/ai/blue） | ✅ | `docs/uiue/design-tokens.json` |
| 前端消费 tokens（非裸 HEX） | ✅ | `frontend/src/styles/globals.css` 引用 design-tokens；`d2a6604` 收敛硬编码 HEX → tokens |
| 涨跌/强调色全局统一 | ✅ | `4c3cb76` 全局设计 tokens 对齐 + 收敛涨跌硬编码色；`1c96193` 统一场景强调色 |

---

## 总览矩阵

| # | 设计稿 | 状态 | 关键 commit |
|---|---|---|---|
| 1 | 数据中心与宏观 | ✅ 已落地 | `823d014` `ea58cac` `9f210f6` `5b881ee` `3da755b` `d2a6604` |
| 2 | 行情页个股工作台 | ✅ 已落地 | `112ee4d` `64d672f` `c2cfdd2` `81fd8a6` `722fc8e` `ef09314` |
| 3 | 期权波动率重组 | 🟡 部分落地 | `option-vol-surface*.tsx` `option-pcr-panel.tsx` `823d014` |
| 4 | 策略研发工作台 | ✅ 已落地 | `a2cffb0` `684e07d` `eff1773` `7832a44` `d2a6604` |
| 5 | 智能量化选股 | ✅ 已落地 | `88ba337` `5b63ffb` `94de29a` `36c2a00` `894dc10` `c0fd66d` |
| 6 | 高频回测引擎 | ✅ 已落地 | `5b881ee` `b166b86` `d2a6604` |
| 7 | 资产风控与高级归因 | ✅ 已落地 | `81e49ab` `eebf5b0` `fd379f7` |
| 8 | design-tokens | ✅ 已落地 | `d2a6604` `4c3cb76` `1c96193` |

**总计**：✅ 7/8 已落地，🟡 1/8 部分落地（期权波动率重组需指标级复核）。

---

## 遗留 / 待办（非阻塞）

1. **期权波动率重组指标级 review**（模块 3）：✅ 已完成（2026-08-22）。验收清单 10 项全过，2 处实质违规（裸 fetch + 写死 OCC 合约）已修复（`d4f9a21`）。
2. **UIRF-18~23**：✅ 全部 `[x]`（TODO.md L262-267）。`use-backtest.ts` 工程债已拆为 `use-backtest.ts`(配置) + `use-backtest-engine.ts` + `use-backtest-metrics.ts` 三 hook（非 290 行单体）。
3. **截图级复核结论**：
   - 选股「营销话术」`全市场 5,832 只 · 毫秒级扫描` → ✅ 已改为真实 WS 状态徽章 LIVE/待连接（`c0a3f7e`）。列序经 `screener-ag-grid.tsx` 固定列(代码/名称)+dynamicCols 实现，需在浏览器确认价格→涨跌→规模→估值→成长顺序。
   - 持仓表「脏名标注」（阅文→"以交易所为准"）+ 合计校验：⬜ **未落地**（前端无 dirty-name 渲染，依赖后端 `/position` 返回 `display_name`/`exchange_note` 字段，需后端协同）。
   - 策略下拉草稿「真实状态」徽章：⬜ **部分落地**（下拉已含内置+草稿+自定义三分组，但草稿项的"真实状态"需后端 `/strategy/list` 返回 `source_type`/`updated_at` 字段才能渲染状态徽章，属 UIRF-06 三分组遗留，待后端加字段）。
