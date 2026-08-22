## 高频回测引擎(Backtest Engine)· UI/UE 重构设计

> 目标:把本页从"配置表单 + 结果渲染"升级为**可信的回测任务台**:假数据与装饰日志清零、任务生命周期状态机补齐、成本与随机种子等复现参数显性化,并与策略研发工作台完成双向互链。
> 范围:纯 UI/UE 设计,不改代码;设计 tokens 与既有导入稿一致(bg #0F0F14 / panel #16181F / up #34D399 / down #F87171 / warn #FBBF24 / ai #A78BFA / blue #60A5FA)。
> 配套 Figma 稿:《高频回测引擎_Figma导入稿.html》(3 帧:配置态 / 运行与报告态 / 状态机与可信规范)。
> 日期:2026-08-21 · 代码落点已核对 `features/trading/backtest*` 与 `backend/routers/backtest.py`(见文末事实索引)

---

### 一、现状诊断(截图 + 代码核对)

本页比策略研发工作台健康:模式横幅、快照 STALE 都是真状态。但存在一处 P0 可信问题与多处"名实不符":

1. **P0 · 收益分布图是编造的。** 回测成功后,前端用 Box-Muller 现场生成 1000 个假高斯收益(mean 0.05 / std 0.08)填充"收益分布"直方图(`use-backtest.ts:202-209`)——与真实回测结果毫无关系。讽刺的是 `backtest-utils.ts` 注释宣称"假数据常量已移除"。**图表可以没有,不能是假的。**
2. **运行中日志是硬编码装饰。** 进度区四条日志("初始化策略模块 PairsTradingBot / Z-Score=2.73 → 开多 / 累计成交 N 笔")与所选标的、策略完全无关(`backtest-config.tsx:151-156`);而 NDJSON 流里明明有真实 `stage/detail` 事件可用。与策略工作台的装饰开场白同型。
3. **失败也显示"回测完成"。** `handleRun` 的 `finally` 在除 abort 外的一切路径(含后端报错)都把进度置 100 且 `done=true`(`use-backtest.ts:216-221`)——后端返回 `{type:'error'}` 时按钮仍是完成态,用户无从得知失败。
4. **"Serverless" 是无代码支撑的文案。** 全仓无 serverless 基础设施;实际是每请求 `asyncio.create_task` + 进程池(`backend/routers/backtest.py:190-218`)。按钮文案改为"启动回测 · 单次沙箱推演",与全局 SANDBOX 语义对齐。后端 docstring 自称"SSE 流式"实为 NDJSON,同属名实不符(工程侧修正)。
5. **复现参数被写死在 payload。** `atr_multiplier=2.0 / commission_pct=0.0005 / slippage_pct=0.001 / random_seed=42` 硬编码于请求(`use-backtest.ts:160-162`),UI 不可见不可改——而 `random_seed` 恰是可复现性徽章(ReproducibilityBadge,已有 95 行组件)的核心输入。徽章在结果区展示"可复现",参数却不可调,逻辑断裂。
6. **策略下拉硬编码与动态混装。** 首项"内置底背离共振 (默认)"(`value=""`)与末项"自定义指标脚本 (Pine)"(`__custom_expr__`)为硬编码 option,中间项来自 `GET /strategy/list`——该接口同时是策略工作台草稿列表(status 写死 testing 的问题同源)。内置项应标注"内置引擎",草稿项带真实状态。
7. **原生表单控件。** 全页 select/input/checkbox 为裸 HTML 元素,未用栈内 shadcn/ui,视觉与交互(焦点、校验、禁用态)与其余页面不一致。
8. 工程债(不在本设计范围,列此备查):`use-backtest.ts` 290 行超 hook 上限 100;水下图 fallback 写死 `-12.3`(`backtest-charts.tsx:119`);useMemo 外声明、memo 内 mutate 且 eslint-disable;后端 `print()` 多处;文件里遗留无意义的 `'use client'` 指令;取消为纯客户端 AbortController(后端靠断连后 `finally` 清理,无 cancel 端点)。

**值得保留并放大的真状态:**

- **数据快照 STALE ≥3d 是真的**:后端按 `age = today - as_of_date` 实时计算(`routers/datalake.py:87-96`),`latest_published → snap_20260812` 是 DB 真实快照 id。这是好设计,增强为"STALE + 解释 + 切换建议"。
- **模式切换是真的**:`TradingModeBanner` 走 `GET/POST /oms/mode`,SANDBOX/PAPER/LIVE 三态 + LIVE 二次确认,全局挂载,本页无需重做。
- **免责声明横幅、可复现性徽章、快照解析链路**(SnapshotReader/SnapshotResolver)保留。

---

### 二、重构后功能分区

左右骨架保留(左配置 / 右执行与报告),左列按语义分组,右列升级为状态机驱动:

```
┌────────────────────────────────────────────────────────────┐
│ 全局 SANDBOX 横幅(TradingModeBanner,保留)      [切换模式]    │
├───────────────────────────┬────────────────────────────────┤
│ 左列 · 回测配置              │ 右列 · 执行与报告(状态机)          │
│ ① 任务与快照                 │ 未运行 → EmptyState 引导          │
│   标的 / 区间 / 粒度          │ 运行中 → 真实阶段进度 + 停止        │
│   快照选择(STALE 解释)       │ 成功   → 完整报告(见下)          │
│ ② 策略                      │ 失败   → 错误卡 + 重试            │
│   内置引擎 / 草稿(真实状态)   │ 已停止 → 已停止提示 + 重新运行      │
│   / Pine 自定义表达式          ├────────────────────────────────┤
│ ③ 资金与成本                 │ 报告:可复现徽章 + 免责声明        │
│   初始资金 / 佣金 / 滑点      │ Tear Sheet 6 卡                 │
│ ④ 高级与复现 ▾               │ [净值][回撤][收益分布][流水]       │
│   ATR 倍数 / random_seed     │ [限价挂单][调试日志]               │
│ ─────────────              │ 头部:[在策略研发工作台打开 ↗]      │
│ [▶ 启动回测·单次沙箱推演]      │                                │
│ [恢复上次参数]                │                                │
└───────────────────────────┴────────────────────────────────┘
```

**左列 · 配置(四组 + 动作)**

- **① 任务与快照**:标的(自动大写保留)、回测区间(1mo~max 七档保留)、数据粒度(1d~1m 保留)、快照选择器。快照行增强:STALE ≥3d 时琥珀徽章 + 说明"快照为 N 天前数据,结果口径以快照为准";点击展开可选其它 published 快照;接口失败回退提示保留并出提示卡。
- **② 策略**:单一选择器,选项分三组并带组标签——「内置引擎」底背离共振(标注"vectorbt 内置")、「我的草稿」来自 /strategy/list 且带真实状态徽章(依赖工作台侧状态真实化工单)、「自定义」Pine 表达式(选中后出现表达式输入 + 本地校验,保留)。
- **③ 资金与成本**:初始资金、佣金、滑点——后两项从 payload 硬编码提升为可见字段(默认值沿用 0.05% / 0.1%,标注"默认")。
- **④ 高级与复现(可折叠)**:ATR 倍数、random_seed(默认 42,可改,旁注"种子固定 → 结果可复现,徽章将记录此值")、调试模式开关(记录逐K线日志,开启后报告多一个调试日志 tab)。
- **动作区**:"启动回测 · 单次沙箱推演"为主按钮(运行中禁用,防重复提交);"恢复上次参数"为次按钮(本地记忆最近一次配置)。删除 "Serverless" 字样。

**右列 · 执行与报告(状态机)**

| 状态 | 呈现 |
|---|---|
| 未运行 | EmptyState"请运行回测推演" + 三步引导(选策略 → 定快照口径 → 启动),保留现文案 |
| 运行中 | 任务卡:真实进度条 + NDJSON `stage/detail` 逐行滚动(如"数据加载 snap_20260812 / 撮合中 / 生成报告")+ [停止];**无任何装饰日志** |
| 成功 | 报告区(见下);主按钮恢复可点 |
| 失败 | 错误卡:错误码 + 后端 `message` + [重试];进度条停在实际值,**不得置 100**(修 finally 逻辑) |
| 已停止 | "已手动停止"提示 + 保留最后一次成功结果(若有)+ [重新运行];注明"停止即断开流,后端任务异步取消" |

**报告区(成功态)**

- 头部:可复现性徽章(snapshot_id + seed + 参数摘要,复用 ReproducibilityBadge)+ 免责声明横幅(保留,文案统一为"沙箱推演结果,不构成投资建议")+ 右侧"在策略研发工作台打开 ↗"(与工作台侧互链闭环,呼应《策略研发工作台_UI重构设计》第三节)。
- Tear Sheet 指标条:年化收益 / 夏普 / 最大回撤 / 胜率 / 盈亏比 / Calmar 六卡(现有 8 项映射收敛展示,其余进 tooltip)。
- Tabs:净值曲线 / 回撤分析 / 收益分布 / 交易流水 / 限价挂单 / 调试日志(仅调试模式)。
- **收益分布 tab 规则**:渲染真实收益序列;后端结果未含 returns 序列前,该 tab 显示 EmptyState"收益序列字段待接入,暂不展示",**禁止假数据兜底**。

---

### 三、与策略研发工作台的分工(承接上轮决策)

- 本页 = **独立大规模回测**:`/backtest/run/stream`,内置引擎 + 草稿 + Pine,快照口径。
- 工作台 = **单策略沙箱推演**:`/strategy/run-sandbox/*`,参数寻优/Walk-Forward。
- 本期不合并;双向互链落地:本页报告头部 → 工作台打开当前草稿;工作台回测报告头部 → 本页(上轮已设计)。两侧共享组件(SnapshotPicker / ReproducibilityBadge / DynamicStrategyForm / ReturnsHistogram)保持复用,两套图表实现(权益/回撤)的合并列为三期决策项。

---

### 四、状态与可信规范

| 场景 | 规范 |
|---|---|
| SANDBOX / PAPER / LIVE | 全局横幅常驻;LIVE 切换二次确认(现状已合规,保留) |
| 快照 STALE | 琥珀徽章 + "N 天前数据"解释 + 切换入口;接口失败出降级提示卡 |
| 运行中 | 真实 stage 进度;停止 = 客户端断流 + 后端异步取消(文案注明) |
| 失败 | 错误卡(码 + message + 重试);进度不置 100;按钮不做完成态 |
| 数据真实 | 所有图表只渲染 Tool/接口返回;无数据 → EmptyState,禁止 mock/编造兜底(宪法 §3/§5) |
| 文案名实 | 删 "Serverless";"收益分布"等 tab 名与数据来源一致 |
| 数据过期(行情) | STALE 琥珀 + 区域降饱和(若未来接入实时行情) |

---

### 五、实施要点(设计层)

1. 删除 Box-Muller 假收益;收益分布 tab 接入真实 returns 序列(后端报告结构补字段,另立工单),接入前显示 EmptyState。
2. 删除四条装饰日志;运行中区域只渲染 NDJSON `progress/stage/detail`。
3. 修 `finally` 状态机:仅 `{type:'result'}` 行进成功态;`{type:'error'}`、网络错误、超时进失败态;abort 进已停止态。
4. 成本与复现参数(佣金/滑点/ATR/seed)显性化为表单字段,payload 默认值不变。
5. 按钮文案 "启动回测 · 单次沙箱推演";全页清理 "Serverless"。
6. 策略选择器三分组 + 内置/草稿/自定义标签;草稿状态徽章真实化(依赖工作台侧后端工单)。
7. 表单控件统一 shadcn(Select/Input/Switch/Collapsible),对齐栈规范。
8. 头部互链 + "恢复上次参数";use-backtest.ts 按状态机拆分(工程侧另行拆文件,满足 hook 行数上限)。

---

### 六、验收清单

- [ ] 收益分布图只展示真实收益序列;无数据时 EmptyState,全页无任何 mock/编造数据
- [ ] 运行中进度与日志全部来自真实 NDJSON 事件;无装饰文案
- [ ] 后端报错时:错误卡可见、可重试,进度停留实际值,按钮非完成态
- [ ] 停止后呈现"已停止"状态并可重新运行
- [ ] 佣金/滑点/ATR/random_seed 在 UI 可见可改,徽章记录与实际 payload 一致
- [ ] 快照 STALE 徽章有解释与切换入口;快照接口失败有降级提示
- [ ] 策略选择器三组分明,草稿带真实状态;无 "Serverless" 字样
- [ ] 报告头部与策略研发工作台互链可达;SANDBOX 横幅与模式切换保持现状

---

### 附:现状事实索引(供实施定位)

- 页面壳 `features/trading/backtest.tsx`(69 行);路由 `App.tsx:108`(`/backtest`)
- 配置表单 `backtest-config.tsx`(196 行:策略 L56-64、快照 L136、进度+假日志 L139-158、启动 L172-184)
- 结果渲染 `backtest-results.tsx`(234 行:空态 L45-54、免责 L58-63、Tear Sheet L66-86、两表 L152-234)
- 图表 `backtest-charts.tsx`(174 行:权益 L16-108、水下 L110-170 含写死 -12.3、直方图包装 L172-174)
- 状态 hook `use-backtest.ts`(290 行:假收益 L202-209、硬编码参数 L160-162、NDJSON 解析 L168-197、finally 缺陷 L216-221)
- 快照 `features/backtest/snapshot-picker.tsx`(66 行:STALE L34-36)、`hooks/use-datalake-snapshots.ts`(62 行);后端 `routers/datalake.py:87-96`
- 后端流 `backend/routers/backtest.py:190-218`(NDJSON,docstring 误称 SSE);内置引擎 `backend/backtest/strategies.py:13`
- 模式横幅 `components/layout/trading-mode-banner.tsx`(53 行)+ `trading-mode-actions.ts:70-99` + `routers/oms.py:340,347`
- 共享:ReproducibilityBadge(95 行)、DynamicStrategyForm(255 行)、ReturnsHistogramChart(62 行)
