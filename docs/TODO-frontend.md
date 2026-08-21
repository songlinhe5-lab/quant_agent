# 🖥️ TODO — 前端与产品（拆分自 TODO.md 2026-08-13）

### 🚨 前端框架迁移：Next.js → Pure Vite SPA（最高优先级，阻塞所有前端开发）

> **背景（2026-06-27 代码核实）**：ADR-001 已决策 Pure Vite SPA (React)，但实际代码是 v0.app 生成的 **Next.js App Router**，且处于 Vite/Next 混杂、`package.json` 缺失的破损状态——当前前端连 `pnpm install` 都无法运行。必须先完成迁移，文档与代码才能对齐，后续 [FE-01]~[FE-11] 才有意义。

- [x] **[MIG-01]** 抢救工程可运行性：在 `frontend/` 根目录重建 `package.json`（React 18 + Vite 5 + TypeScript 依赖），将错置于 `src/` 的 `pnpm-lock.yaml`、`postcss.config.mjs`、`next-env.d.ts` 归位/清理
- [x] **[MIG-02]** 新建 `frontend/vite.config.ts`：配置 `@vitejs/plugin-react`、`@/*` 路径别名、`/api` 与 `/ws` 开发代理到 `localhost:8000`
- [x] **[MIG-03]** 重建 Vite 入口：补齐 `src/main.tsx`（ReactDOM.createRoot）+ `src/App.tsx`，修正 `index.html` 中失效的 `/src/main.ts` 引用（应为 `.tsx`）
- [x] **[MIG-04]** 路由迁移：将 `src/app/(main)/*` 的 App Router 路由组（apm/backtest/copilot/data-center/oms/quotes/risk/screener/strategy/settings）改写为 **React Router v6** 路由配置，统一收口到 `src/router/index.tsx`
- [x] **[MIG-05]** 剥离 Next.js 专有 API：移除 `next/font/google`（改本地字体或 `@fontsource`）、`next/image`、`next/link`、`next/navigation`、`@vercel/analytics/next`、`Metadata` 等所有 `next/*` 引用
- [x] **[MIG-06]** 清理迁移残骸：删除 `next.config.mjs`、`next-env.d.ts`、`.next/`、伪 `dist/`，以及与 App Router 重复的 `src/views/`（与 React Router 视图二选一）
- [x] **[MIG-07]** 修正 `tsconfig.json`：移除 `"plugins":[{"name":"next"}]` 与 `.next/**` include，改为 Vite 标准 TS 配置
- [x] **[MIG-08]** 修复 `frontend/Dockerfile`：统一使用 pnpm、修正 COPY 指令、验证多阶段构建 + Nginx 部署链路
- [x] **[MIG-09]** 修正 `frontend/README.md`：重写为 "React 18 + Vite SPA"，与 ADR-001 / `docs/04.` 对齐
- [x] **[MIG-10]** 迁移验收：`pnpm install && pnpm build` 通过（25.35s）、`dist/` 目录成功生成、所有 7773 个模块转换完成


### 前端安全

- [x] **[SEC-07]** Access Token 存 Memory（`useRef`），Refresh Token 存 HttpOnly Cookie，禁止存 `localStorage`
- [x] **[SEC-08]** 所有用户输入（股票代码、策略表达式）需 XSS 过滤，Agent HTML 输出统一过 `DOMPurify`
- [x] **[SEC-09]** 删除持仓、取消订单等破坏性操作必须添加二次确认弹窗（二次确认 Modal）
- [x] **[SEC-13]** 用户登出时清除所有本地敏感缓存（内存 Token / IndexedDB / 本地存储），防止会话劫持


### 前端基础设施

- [x] **[FE-01]** ~~全局 `TradingDashboard` Keep-Alive~~ → **纠偏并闭环（2026-07-13）**：线上 SSOT=`DashboardLayout`+Router；URL 友好 Keep-Alive 见已完成的 **FE-ARCH-01**（`KeepAliveOutlet`）


- [x] **[FE-02]** 底部 `StatusBar` 组件：显示 WS 连接状态灯、当前延迟 ms、账户净值、当日盈亏
- [x] **[FE-03]** WebSocket 断线5步处理流程：断线 → 状态灯变红 → 图表 STALE overlay → 指数退避重连 → 重连成功后重订阅
- [x] **[FE-04]** 三级 Error Boundary：Module 级 / Panel 级 / Chart 级，分别隔离崩溃影响范围
- [x] **[FE-05]** `frontend/src/lib/logger.ts` 实现：level 过滤 + 生产环境上报 `/api/v1/logs`（前端侧完成，后端端点待实现）
- [x] **[FE-05b]** 前端日志后端端点 + APM 面板集成：
  - 后端：`POST /api/v1/logs` 接收前端日志（level/message/timestamp/context），写入 PostgreSQL `frontend_logs` 表
  - 后端：`GET /api/v1/logs` 查询接口（支持 level 筛选、时间范围、分页）
  - 前端：APM 面板增加"浏览器日志"Tab，展示前端错误、警告、性能指标
  - 前端：logger.ts 启用 `enableRemote: true`，完成前后端对接
- [x] **[FE-06]** Cmd+K 命令面板（Command Palette）：快速跳转标的、模块，键盘优先操作流
- [x] **[FE-07]** 高频 Tick 数据必须走 `Float64Array` + `useRef`，严禁触发 React state 重渲染
- [x] **[FE-08]** Bundle 分析：目标首次加载 JS < 300KB gzipped；大包（ECharts、PixiJS）必须 lazy import
- [x] **[FE-09]** 涨跌颜色：中国市场红涨绿跌 / 欧美市场绿涨红跌，根据 `marketRegion` 配置动态切换
- [x] **[FE-10]** 所有金融数字使用等宽字体（`font-variant-numeric: tabular-nums`），对齐小数点
- [x] **[FE-16]** API client 三通道封装（REST / WS / SSE）：统一 baseURL、错误码处理、请求拦截器自动用 Refresh Token 续期 Access Token
- [x] **[FE-17]** WebSocket 客户端封装：连接生命周期管理、自动重连（指数退避）、订阅去重、页面 `visibilitychange` 隐藏时暂停订阅
- [x] **[FE-18]** 前端 TypeScript 类型定义落地 `src/types/domain.ts`，与 `docs/11` 领域对象严格对齐（Quote/Kline/Position/Order 等）
- [x] **[FE-19]** IndexedDB 历史 K线本地缓存（减少重复 HTTP 拉取，离线可读最近行情）
- [x] **[FE-20]** Web Worker 指标计算下放：MACD / RSI / 布林带等重度计算移出主线程，防止阻塞渲染
- [x] **[FE-21]** i18n 国际化落地（中/英），收口现有 `src/locales/` 与 i18n context
- [x] **[FE-22]** 登录页 + 路由守卫：未鉴权访问自动跳转登录，对接 SEC-10 认证接口


## 🟡 P2 — 体验优化与工程质量（滚动迭代）

### 测试覆盖

- [x] **[TEST-01]** 后端核心路径（行情管道、认证、OMS）单元测试覆盖率 ≥ 70%
- [x] **[TEST-02]** 前端 Zustand Store、自定义 Hooks 单元测试覆盖率 ≥ 60%
- [x] **[TEST-03]** Locust 压测：`/ws/quotes` 1000 并发连接，目标 P95 延迟 < 100ms ✅ **2026-07-13**：`scripts/locust_ws_stress.py`（WebSocketClient + QuotesWebSocketUser + RestApiUser）+ `scripts/locust.conf` 配置
- [x] **[TEST-04]** pytest-benchmark：K线聚合计算 baseline，防止性能回归 ✅ **2026-07-13**：`test_benchmark_test04.py`（11 benchmarks: MA/RSI/MACD/BOLL 计算 + 1000 规则评估 + 指标评估器 + K线 JSON/Parquet 序列化）
- [ ] **[TEST-05]** Flutter widget test + integration test 基础覆盖，UI 交互无崩溃（依赖 CLI 脚手架已就绪；随 **CLI-08~12** 功能交付补测，目标关键路径无崩溃）
- [x] **[TEST-06]** pre-commit hooks：后端 `ruff` + `black` + `mypy`，前端 `eslint` + `prettier` + `tsc --noEmit`，提交即拦截
- [x] **[TEST-07]** 依赖漏洞扫描纳入 CI：`pip-audit` / `pnpm audit`，高危漏洞阻断合并
- [x] **[TEST-08]** 测试框架与脚手架搭建：后端 `pytest` + `conftest.py` 公共 fixtures + 测试数据工厂（factory）；前端 `vitest` + Testing Library + MSW setup；建立可复用的 mock 数据集
- [x] **[TEST-09]** 存量代码补单测：对现有 `tools/`、`hermes_agent/`、`backend/services/` 已有但未覆盖的核心逻辑补齐单测（先补关键路径，存量优先于新功能）
- [x] **[TEST-10]** 每个 Tool 独立单测：mock 外部数据源响应，校验 Tool 入参解析、出参结构、异常分支（数据源失败时的降级返回）
- [x] **[TEST-11]** Hermes Agent ReAct 循环单测：mock LLM + mock Tool，验证推理步进、Tool 路由、熔断中止（连续失败 3 次）、上下文裁剪逻辑
- [x] **[TEST-12]** 前后端契约测试：以 `docs/10`/`docs/11` 为基准，校验后端 Pydantic Schema 与前端 TS 类型一致性，接口变更时自动暴露 break ✅ **2026-07-13**：`test_contract_test12.py`（23 tests: 枚举对齐 8 + 字段映射 6 + API 结构 3 + WS 消息 3 + 类型兼容 3）；修复 PnL/Pnl alias 不一致（PositionModel + AccountModel）
- [x] **[TEST-13]** 覆盖率门禁与趋势：CI 强制后端 ≥40% / 前端 ≥15%（2026-07 月目标，每月 +5% 爬坡至 70%/60%），接入 codecov 输出覆盖率趋势，禁止覆盖率倒退
- [x] **[TEST-14]** 前端关键组件测试：行情列表、K线图容器、订单确认弹窗、登录表单等核心交互组件的渲染与交互断言 ✅ **2026-07-13**：`tests/features/key-components.test.ts`（23 tests: marketStore 4 + useWatchlist 6 + formatCurrency 4 + formatLargeNumber 3 + getChangeBgColor 4 + getMarketCSSVariables 2）
- [x] **[TEST-15]** E2E 端到端测试（Playwright）：覆盖关键用户流（登录 → 看行情 → 选股 → Agent 对话 → 模拟下单），CI 夜间跑 ✅ **2026-07-13**：`playwright.config.ts` + `e2e/flows.spec.ts`（14 tests: 登录守卫 2 + 导航 3 + 页面健康 5 + 资源加载 2 + a11y 2）；vitest.config.ts 排除 e2e/**
- [x] **[TEST-16]** 前端构建健康：`pnpm build` 零 TS 错误、零 ESLint 错误，产物体积基准监控
- [x] **[TEST-17]** 后端启动健康：所有路由模块导入无报错，`/api/v1/health` 端点返回 200

### 前端体验

- [x] **[FE-11]** 数据加载态三状态：Skeleton → 真实数据 / STALE overlay（数据超 30s 未刷新）/ Empty State ✅ **2026-07-13**
- [x] **[FE-12]** 右键上下文菜单：在行情列表中右键可直接打开分析、添加自选、复制代码等快捷操作 ✅ **2026-07-13**
- [x] **[FE-13]** 滚动列表全部虚拟化（AG Grid 虚拟滚动，持仓/订单列表 `@tanstack/react-virtual`） ✅ **2026-07-13**（OMS/自选用 lite virtualizer；选股 pageSize≥50 用 AG Grid）
- [x] **[FE-14]** Lighthouse 性能分数 ≥ 85（禁用所有动画后作为基准测量） ✅ **2026-07-13**（desktop **95** / mobile 51；`?lighthouse=1` + `.reduce-motion`；报告 `.lighthouse/baseline-desktop.report.html`）
- [x] **[FE-15]** 移动端响应式：`< 768px` 折叠为单栏，底部 Tab Bar 代替左侧 Sidebar ✅ **2026-07-13**
- [x] **[FE-23]** a11y 无障碍：关键交互补 `aria-label`、键盘可达性（Tab 序）、WCAG AA 对比度校验
- [x] **[FE-24]** 全局字体统一：`font-family: 'Geist Mono', 'Inter', system-ui, sans-serif`，金融数字强制 `font-variant-numeric: tabular-nums`
- [x] **[FE-25]** 视觉主题统一：深色模式为主，参考 Linear/Vercel 风格，统一配色变量与组件风格 ✅ **2026-07-13**
- [x] **[FE-26]** 视觉稿参考：收集并整理 Linear / Vercel / Robinhood 等标杆产品的视觉特征，形成设计规范 ✅ **2026-07-13**（`docs/20. 前端视觉设计规范.md`）
- [x] **[FE-27]** 前端性能监控：接入 Web Vitals (LCP / INP / CLS / TTFB)，开发阶段 HUD 实时显示，生产环境经 heartbeat 上报 ✅ **2026-07-13**（随 OBS-03）
- [x] **[FE-28]** 交互细节优化：统一 Loading 状态、Toast 通知、过渡动画时长与缓动曲线 ✅ **2026-07-13**
- [x] **[FE-29]** 响应式布局完善：确保 1280px / 1440px / 1920px 三档分辨率下布局合理无溢出 ✅ **2026-07-13**
- [x] **[FE-30]** 前端错误边界完善：全局 ErrorBoundary + 模块级降级，捕获渲染崩溃并上报日志 ✅ **2026-07-13**

### 产品功能前端缺口（2026-07-13 新增，源自 `docs/01` V2.2）

> 填补产品文档 V2.2 标注的 UI 缺口；与后端序列（ALERT / BT / DQ / PT）并行推进，对接点见各任务依赖说明。

- [x] **[FE-PROD-01]** 全局 AI 副驾右侧抽屉：`DashboardLayout` 级常驻抽屉（`Cmd+Shift+A` / 右侧把手），任意模块可展开/折叠且不卸载主工作区；与 Settings 抽屉（§十五）**互斥展开**；SSE 流式 + ECharts/Mermaid 内联渲染；迁移现有页内 Copilot 嵌入（`docs/01 §9.2~9.4` · P0）✅ **2026-07-13**

- [x] **[FE-PROD-02]** 三模式顶栏与横幅：SANDBOX 🟡 / PAPER 🟠 / LIVE 🔴 顶栏模式切换器 + 底栏 `[模式: …]` 联动；PAPER↔LIVE 切换二次确认弹窗（纸面检查点摘要可先占位文案，**PT-02b** 完成后接真实 Sharpe/TE/运行天数）；扩展已完成的 OMS-11 二元横幅（`docs/01 §1.6` · P0）✅ **2026-07-13**
- [x] **[FE-PROD-03]** P0 告警 AlertOverlay：P0 全屏不可关闭浮层（标题/摘要/查看详情/全部已读）；P1~P3 走右上角 Toast 栈；消费告警 payload `ui_hint`（如 `{route,symbol}`）一键跳转行情；WS 断连时告警历史 STALE 标注（`docs/01 §10.5` · P2 · 依赖 **ALERT-03c** WS 推送频道 ✅ + **ALERT-04** 告警中心页 ✅）✅ **2026-07-13**
- [x] **[FE-PROD-04]** 回测数据快照选择器：回测工坊参数区 `[数据快照 ▾ latest_published | snap_YYYYMMDD | …]`；报告页 **可复现性徽章**（`code_hash` · `manifest_hash` · `reproducible: true\|false`）；对接 **DQ-03e** `GET /api/v1/datalake/snapshots`（`docs/01 §5.0` · P1 · 依赖 **DQ-03c** manifest 发布 + **BT-02** 回测 manifest 写入）✅ **2026-07-13**

#### Calendars 全球市场日历（2026-07-16 新增，源自 `docs/01` V2.3 §十六）

> 对标 yfinance 顶部 Markets 横向滚动条：左侧类目侧栏 + 右侧水平滚动行情卡片（含 Sparkline）；6 大类目（US/EU/Asia/Crypto/Rates/Commodities/Currencies）+ 4 个日程 Tab（Economic/Earnings/Dividends/IPOs）+ Hours Tab。复用 `_fetch_macro_assets_data` 扩至 50+ 标的。详细设计见 `docs/01 §十六`。

- [x] **[FE-PROD-05a]** 后端：`/api/v1/calendars/snapshot` 端点，扩 `macro/assets` 至 50+ 标的 + 类目聚合（`CalendarCategory`：us/eu/asia/crypto/rates/commodities/currencies）+ Sparkline 字段（60 点分钟级）；复用 `yf_macro_cache_*` Redis 缓存（P1 · ✅ 2026-07-16 · 7 大类目 **实际 52 标的 ✅ 达 50+** · ⚠️ Sparkline 取 `yf_macro_cache_*` **日线**非分钟级）
- [x] **[FE-PROD-05b]** 后端：新增 `/api/v1/calendars/dividends` `/api/v1/calendars/ipos` `/api/v1/calendars/hours` 三个端点；hours 完整实现（五时区世界时钟矩阵）；dividends/ipos 优先 Finnhub，未配置 `FINNHUB_API_KEY` 时优雅降级返回 `unavailable`（P1 · ✅ 2026-07-16 · ⚠️ 仅 Finnhub，缺失原始要求的 **Futu 港股分红 + AKShare IPO**）
- [x] **[FE-PROD-05c]** 前端：`CalendarsModule` 一级路由（`/calendars`）+ 顶部 6 Tab 切换（Markets/Economic/Earnings/Dividends/IPOs/Hours）+ 时区切换器；接入 §1.2 IA 侧边栏导航（`📅 Calendars`）（P1 · ✅ 2026-07-16）
- [x] **[FE-PROD-05d]** 前端：类目侧栏（sticky 176px，7 类目 + 自定义可见性入口）+ 横向滚动卡片行（复用 `AssetButton`/`MiniTrendLine` SVG Sparkline，对齐 `docs/20` 视觉规范）+ 滚动按钮（P1 · ✅ 2026-07-16 · ⚠️ Sparkline 用 SVG 复用既有组件，Canvas 批量绘制优化见下方备注）
- [x] **[FE-PROD-05e]** 前端：Earnings（复用 `/macro/earnings`）/Dividends/IPOs/Hours Tab；Economic/Earnings/Dividends/IPOs 用统一 `ScheduleTable`，Hours 为五时区世界时钟 + 市场时段矩阵（P2 · ✅ 2026-07-16 · ⚠️ Hours 24h 热力网格简化为市场时段矩阵表）
- [x] **[FE-PROD-05f]** 前端：自定义类目（类目可见性开关 + localStorage 持久化，侧栏"自定义类目"面板）✅ 2026-07-16 · ⚠️ 仅做显隐，拖拽建组/命名未做（P3 简化）
- [ ] **[FE-PROD-05g]** Flutter 移动端适配：横向滚动 → 纵向卡片堆叠；类目侧栏 → 折叠面板（Accordion）；复用 `docs/05 §4.2` `DataTile` + `§4.5` `SparklinePainter`（P2，依赖 05d · ~300 行 · ⏸️ 待 `client/` Flutter 仓库单独 PR，Web 端响应式布局已覆盖 <768px）
- [x] **[FE-PROD-05h]** 测试：Pytest（snapshot 缓存/聚合/STALE · hours · dividends/ipos 降级 · /macro/earnings 复用，7 用例）+ Vitest（模块渲染/Tab 切换/STALE 角标/utils 纯函数，10 用例）（P1 · ✅ 2026-07-16）
- [x] **[SVC-08]** Finnhub 限流感知与健康检查：复用 `docs/14 §12` 限流退避体系；`/api/v1/datasource/finnhub/health`（新增被动健康端点）+ `/rate-limit-status`（通用路由 `routers/datasource.py` 已覆盖 name=finnhub）；`FinnhubService` 全方法 429/403 → `on_rate_limit`、成功 → `on_success`，calendars dividends/ipos 接入 `should_throttle` 退避（P2 · ✅ 2026-07-16 · 8 用例）
- [x] **[BE-ARCH-05]** DataSource 新增 Finnhub Source：实现 `DataSourceInterface` Protocol（`FinnhubDataSource`）+ 注册到 `DataSourceRegistry`（`ensure_finnhub_registered`，于 `MarketDataGateway.__init__` 幂等注册，对齐 yfinance 模式）；`DATASOURCE_FINNHUB_MODE` env 控制 internal/external/hybrid；更新 `docs/14 §八` + §2.4 能力矩阵（6 capabilities：earnings/company_news/market_news/economic_calendar/insider_trading/stock_history）；限流复用 SVC-08 的 `rate_limit_registry`（P2 · ✅ 2026-07-16 · 17 用例）

**依赖图**：

- `FE-PROD-05a` → `{FE-PROD-05d, FE-PROD-05c}`
- `FE-PROD-05d` → `FE-PROD-05f` (P3)
- `FE-PROD-05b` → `FE-PROD-05e` → `FE-PROD-05g`
- `FE-PROD-05h`（覆盖率门禁，依赖各前置）
- `SVC-08` / `BE-ARCH-05` 与 `FE-PROD-05a` 并行

**验收**：6 大类目 × ≥ 5 标的 = ≥ 30 卡 + 4 日程 Tab 全通；首屏 LCP < 1.2s；横向滚动 FPS ≥ 55；Lighthouse ≥ 90（desktop）。详见 `docs/01 §16.8`。

### 前端架构债（2026-07-13 · `docs/04` V4.0）

- [x] **[FE-ARCH-01]** 路由友好 Keep-Alive：`KeepAliveOutlet` 缓存已访问 pathname（最多 8），保留 URL；`ModuleErrorBoundary` 隔离崩溃 ✅ **2026-07-13**
- [x] **[FE-ARCH-02]** 巨型文件拆分：oms / right-sidebar / backtest-report 拆至 ≤300；`components/ui/sidebar.tsx` 为 shadcn 原语例外（不改写）✅ **2026-07-13**
- [x] **[FE-ARCH-03]** 清除 `recharts`：macro / risk / sentiment / backtest / report 全部迁 ECharts 并移除依赖 ✅ **2026-07-13**
- [x] **[FE-ARCH-04]** 死代码清理：双布局 TradingDashboard 链 · axios 死客户端 · 空 stub · `package-lock.json` ✅ **2026-07-13**


### 产品与 UI/UE 治理（2026-07-08 Review 新增，源自 `docs/01` V2.3 产品审查）

> 核心评价：AI 集成深度（ReAct Agent + NLP 选股 + 三模式门禁）业界领先，但图表交互深度、布局灵活性、AI 上下文感知与 TradingView/QuantConnect 仍有代差。
> 原则：**强化 AI 差异化护城河** + **补齐图表交互短板** + **布局从"常规 SaaS"升级为"量化工作台"**。

#### P0 — 核心差异化释放

- [x] **[PROD-01]** AI 副驾页面上下文自动注入：
  - 在选股器打开 AI 时自动携带当前筛选条件/结果摘要
  - 在 K 线页打开时自动携带当前标的 + 周期 + 技术指标
  - 在风控页打开时自动携带当前组合摘要
  - 目标：从"通用 ChatBot"升级为"场景感知助手"
  - 实现：`useCopilotContextStore` 承接页面上下文；选股器/K线/风控三页 effect 写入；`chat-context.handleSend` 在会话首条消息自动注入 prompt；抽屉顶部"📎 已附加上下文"卡片可手动移除；`quant_copilot_invoke` 单标的推送走 skipPageContext 避免重复
- [x] **[PROD-02]** AI 分析结果内联标注：AI 输出的买卖信号/支撑压力位直接标注在 K 线图上（箭头/区域高亮），而非仅在对话框中输出文字
  - 目标：让 AI 副驾的研判从"对话框文字"升级为"K 线图内联标注"
  - 协议：AI 在个股研判后输出 ` ```chart-annotations ` 围栏 JSON（symbol/signals/levels/zones），AGENTS.md §7 已写入主脑输出规范
  - 后端：`hermes_agent/agent.py` 在 `collected_content` 中检测 `chart-annotations` 块并 yield `{"type":"chart_annotation","data":...}`（与 `strategy_code` 同范式）
  - 前端：`chat-context.tsx` 消费事件 → 写入 `useChartAnnotationStore`（按 symbol 匹配）；`lightweight-chart-canvas.tsx` 订阅 store 渲染——`signals`→`createSeriesMarkers` 箭头、`levels`→`createPriceLine` 价格线、`zones`→`BaselineSeries` 半透明区域带；图表右上角「🤖 AI 标注」徽标可一键清除；点击标记触发 toast 提示

#### P1 — 图表交互与布局升级

- [x] **[PROD-03]** K 线图画线工具（第一批）：趋势线 / 水平线 / 斐波那契回撤 / 矩形区域，对标 TradingView 基础画图能力 ✅ **2026-07-25**：`lightweight-chart-canvas.tsx` 在既有 `TrendLinePrimitive`（v5 IPrimitive）基础上扩展 `HLinePrimitive` / `RectanglePrimitive` / `FibRetracementPrimitive`，工具栏由单一 Pencil 升级为四工具组（趋势线两点/水平线单击/斐波那契两点/矩形两点）+ 清除全部；`drawTool` 状态机 + `drawingsRef` 管理 + 切换标的/周期自动清线防错位。tsc 零错误 + 197 全量零回归
- [x] **[PROD-04]** 四场景模式系统（布局 + 密度 + 焦点色 + AI 角色）✅ **2026-07-19**：
  - `scene-mode-types.ts`（四模式元数据）+ `useSceneModeStore.ts`（Zustand + localStorage）
  - `globals.css` `--density-scale` / `--scene-accent` CSS 变量 + `[data-scene-mode]` 选择器
  - `scene-mode-switcher.tsx` 顶栏分段切换器 + `use-scene-hotkey.ts` Cmd+Shift+M
  - `dashboard-layout.tsx` data 属性 + Sidebar 显隐 + AI 分析全屏 + 研究模式自动展开 Copilot
  - `fullscreen-copilot.tsx` AI 分析模式全宽对话工作台
  - `global-copilot-drawer.tsx` 盯盘模式隐藏 EdgeHandle
  - 12 tests passed + tsc 零错误 + 全量 197 tests 零回归
  - 待后续迭代：盯盘 K线全屏/研究多面板拖拽/监控专属布局/AI快捷指令栏
- [x] **[PROD-04a]** 盯盘模式专属布局（K线全屏 + 盘口悬浮 + 异动高对比）`frontend/src/features/trading/quotes.tsx` 接入 `useSceneModeStore`，`sceneMode==='watch'` 时切换全屏 K 线 + 右下角悬浮盘口（DOM/成交流水）；新增 `anomaly-flash.tsx`（监听 `market_tick`/`quote_update` 的 `change_pct`，>2% 时基于 `--scene-accent` 脉冲闪烁并标注异动方向）与 `floating-watchlist.tsx`（可拖拽悬浮球 + 自选浮层）；`globals.css` 增加 `scene-anomaly-flash` 动画。
  - Quotes 模块判断 sceneMode='watch' 时切换全屏 K 线布局
  - 自选列表改为可拖拽悬浮球样式
  - 盘口异动 > 2% 时高对比闪烁动画
  - 强调色 `hsl(var(--scene-accent))` 应用于异动 UI
  - 依赖：无（可立即开始）
- [x] **[PROD-04b]** AI 分析模式快捷指令栏与上下文感知`fullscreen-copilot.tsx` 新增快捷指令栏（🌤️今日早报 / ⚖️对比分析 / 📡期权链 / 🌐宏观雷达 / 📋查询自选），点击经 `handleSend` 发起指令并显式要求调用 Hermes 工具生成内联图表/数据卡片；ticker 类指令自动从 `useMarketStore.currentTicker` 注入当前聚焦标的；进入 AI 模式时 `useEffect` 将全局 currentTicker 写入 `useCopilotContextStore` 实现跨模式 ticker 携带；顶栏 Brain / 会话按钮 / 指令栏统一改用 PROD-04c 的 `scene` 强调色与 `scene-accent-transition`。另修复 PROD-04a 中误用 `s.sceneMode`（应为 `s.mode`），否则 watch 模式永不触发。
  - FullscreenCopilot 补充快捷指令栏：[今日早报][对比分析][期权链][宏观雷达][选股]
  - 从其他模式切换至 AI 分析时自动携带当前标的 ticker
  - 内联图表/数据卡片自动生成（对接 Hermes 工具调用）
  - 依赖：无（可立即开始）
- [x] **[PROD-04c]** 强调色全局动态应用 + 模式切换过渡动画`tailwind.config.js` 注册 `scene` 色（`hsl(var(--scene-accent))`）；`globals.css` 在各场景块内将 `--ring` 覆盖为场景强调色（全局 Focus Ring 动态化），并新增 `.scene-accent-transition` 过渡工具类；`global-copilot-drawer.tsx` 的 AI 把手/Brain/会话切换/上下文条/拖动条全部改用 `text-scene`/`bg-scene`；`alert-toast-stack.tsx` 告警铃铛与非 P1 卡片描边改用场景强调色（P1 保留琥珀语义色）。模式切换时强调色 200ms 平滑过渡。
  - Alert、Focus Ring、AI Badge 等关键 UI 应用 `hsl(var(--scene-accent))`
  - 模式切换时 `transition: all 200ms` 平滑过渡
  - 依赖：无（可立即开始）
- [ ] **[PROD-04d]** 信息密度系统扩展（间距/圆角/行高响应式）
  - 扩展 CSS 变量：`--density-gap`、`--density-pad`、`--density-radius`
  - 表格 / Grid 组件按密度调整列宽、行高
  - 极密模式设最小 fontSize 11px 下限
  - 依赖：PROD-04c
- [x] **[PROD-04e]** 研究模式多面板拖拽布局
  - 启用 ResizablePanelGroup 三栏拖拽（代码/回测/AI）
  - 底部 Terminal 面板
  - 键盘优先交互（Cmd+1/2/3 快速跳转面板）
  - 依赖：STRAT-01~05（策略实验室核心）
  - *2026-07-26 完成：`quotes.tsx` 在 `research` 场景渲染 `StrategyIDE`（三栏 ResizablePanelGroup + 底部 Terminal），并接入全局 ⌘1/2/3 面板跳转（代码聚焦 Monaco、回测切 report、AI 助手聚焦输入框）；拖拽手柄/提示条/Topbar 部署按钮统一为 scene 强调色。*
- [x] **[PROD-04f]** 监控模式专属布局（告警流 + Bot矩阵 + 风控仪表盘）
  - 监控模式下告警流自动升格为主视图
  - Bot 状态矩阵 + 风控仪表盘优先级布局
  - 依赖：ALERT-03~05, RISK-01~08
  - *2026-07-26 完成：新增 `MonitorModeLayout`，在 `monitor` 场景渲染——左侧实时告警流（EventsList）升格为主视图，右侧列上 Bot 状态矩阵（复用 `OmsBotGrid` + `useOms` 实时数据流）、下风控仪表盘（`RiskModule`）；顶栏含节点运行数与未读告警数；强调色统一为 scene。*
- [x] **[PROD-04g]** 移动端场景模式适配
  - 移动 TabBar 补充模式圆盘或底部菜单
  - 小屏幕 (<768px) 强制 density-scale=1.0，禁用极密
  - 依赖：PROD-05（多分辨率适配规范）
  - *2026-07-26 完成：`mobile-tab-bar.tsx` 列数扩为 6，新增场景模式圆盘按钮（当前模式 emoji + scene 强调色圆环）与底部 2×2 切换菜单（SCENE_META 标签/提示）；`globals.css` 增加 `@media (max-width:767px)` 强制 `--density-scale:1`（!important）禁用盯盘 1.2/研究 0.9 极密。*
- [x] **[PROD-05]** 多分辨率适配规范：
  - 1280px：AI 抽屉改为 overlay（不挤压主工作区）
  - 1920px+：自动展开更多面板（盘口+新闻流默认可见）
  - 超宽屏 21:9：支持三栏并排（行情+策略+AI）
  - 落地：`frontend/src/styles/globals.css` 新增 PROD-05 响应式基础设施——`global-copilot-drawer` 已 `fixed` overlay（1280px 达标）；新增 `@media (min-width:1920px)` 下 `.resp-auto-panels [data-secondary-panel]{display:block}` 与 `@media (min-width:2560px)` 下 `.resp-3col` 三栏网格工具类（21:9 达标）。
  - ✅ **[PROD-05 深化]** 多分辨率适配已真正驱动业务页：默认行情工作区 `QuotesModule`（`frontend/src/features/trading/quotes.tsx`）已挂 `resp-auto-panels` + `data-secondary-panel`，≥1920px 自动展开「新闻流」次面板（新建自包含 `market-news-panel.tsx`，复用 `NewsStream` + `GET /macro/news`）；并挂 `resp-3col`，≥2560px 揭示第三栏「AI 副驾」（内联 `AIChat`），形成 **行情 + 策略/新闻 + AI** 三栏并排。基础设施增强：`.resp-3col` 由 `align-items:start` 改为 `stretch` 以满高（当时无既有消费方，安全）；新增 `.resp-3col > [data-ultrawide-ai]{display:flex}` 揭示规则。旧 ⚠️「需逐页挂 class 消费」已闭合。
  - ✅ **[PROD-05 深化 · 超宽屏固定三栏]** research 场景 `StrategyIDE`（`frontend/src/features/strategy/layout/strategy-ide.tsx`）现通过 `useMediaQuery('(min-width:2560px)')`（`frontend/src/hooks/use-media-query.ts`，SSR 安全）条件渲染：≥2560px 出 **非拖拽固定三栏**（复用 `.resp-3col` 网格 + 新增 `.ide-3col` 列模板锁定 IDE 比例 explorer 15% / editor 1fr / AI 26%，去间距改边框分隔），≤2559px 保留原 `react-resizable-panels` 可拖拽布局——绕开内联 `display:flex` 覆盖 grid 的样式优先级雷区，且无需维护两套布局语义。
  - ✅ **[PROD-05 深化 · 盯盘全屏可折叠新闻流]** 进阶建议 1 落地：盯盘全屏（`quotes.tsx` 的 `isWatchScene` 分支）新增 `WatchNewsOverlay`（`frontend/src/features/trading/watch-news-overlay.tsx`），默认收起、仅右上角一个展开钮，复用 `MarketNewsPanel`；用 `min-[1920px]:` 任意媒体变体门控——**仅 ≥1920px 揭示**（小屏聚焦模式零干扰），浮层锚定在右侧盘口悬浮（w-72）左侧（`right-[19.5rem]`）避免遮挡；外层 `pointer-events-none` 仅按钮/面板可交互，K 线拖拽不受影响。
  - ✅ **[PROD-05 深化 · 新闻浮层滑入动画 + 毛玻璃]** 进阶建议 2 落地：`globals.css` 新增 `@keyframes resp-slide-in-right`（`animate-slide-in-right` 工具类，挂载即右侧滑入）；`WatchNewsOverlay` 展开面板加 `animate-slide-in-right` 并强化玻璃感（`backdrop-blur-xl bg-card/70`），作战室质感拉满。
  - ✅ **[PROD-05 深化 · 通用 motion 工具族]** 进阶建议 2（沉淀 motion 工具类）落地：`globals.css` 将原单条 `animate-slide-in-right` 扩为 `resp-*` motion 工具族——`resp-slide-in-right`（右滑入）、`resp-fade-up`（上滑淡入）、`resp-scale-in`（缩放淡入），统一挂载即播、缓出曲线一致；`WatchNewsOverlay` 改用 `resp-slide-in-right`。后续面板入场动画直接复用，无需各写 keyframes。
  - ✅ **[PROD-05 深化 · research 固定三栏侧栏入场]** 进阶建议 1 落地：超宽屏固定三栏的左右栏接 `resp-fade-up`（左栏即时、右栏 `animationDelay:0.06s` 错峰），中央编辑器作为锚点不动画，进出 2560px 边界切换时形成层次感入场。
  - ✅ **[PROD-05 · motion 工具族补 resp-slide-in-left]** 进阶建议 2 部分落地：`globals.css` 补 `resp-slide-in-left`（左锚定 popover 入场，方向对称）；但**驳回**其与 AI 副驾抽屉的接线——`global-copilot-drawer` 是 `fixed right-0` 靠 `transition-[width]` 宽度擦除动画（右锚定），非左侧滑入；挂 `resp-slide-in-left`（挂载期 keyframe）会轴错 + 与 width 过渡打架 + 只能进不能出。该工具仅留给未来左锚定抽屉。
  - ❌ **[PROD-05 · 新闻浮层滑入时位移盘口 · 驳回]** 进阶建议 1 伪前提：新闻浮层锚定 `right-[19.5rem]`、盘口 `right-3 w-72`（左沿在 18.75rem），二者相隔 0.75rem **本就不叠压**，无需位移避让。驳回。
  - ✅ **[PROD-05 深化 · 无障碍兜底 prefers-reduced-motion]** 进阶建议 1 落地：`globals.css` 新增 `@media (prefers-reduced-motion: reduce)` 关掉整套 `resp-*` 入场动画（`animation:none !important`）。系统开启「减少动态效果」时 research 固定三栏 / 新闻浮层 / 盘口的入场动画全部禁用，跨 2560px 边界重挂不再闪动。无障碍基线补齐。
  - ✅ **[PROD-05 深化 · watch 盘口入场统一]** 进阶建议 2 落地：盯盘全屏盘口悬浮容器（`quotes.tsx` watch 分支）接 `resp-fade-up`，与新闻浮层统一 `resp-*` motion 语言；盘口为常驻核心元素，仅 watch 场景挂载时入场一次，符号切换不重挂。
  - ❌ **[PROD-05 · research 加 min-[1920px] 兜底 · 驳回]** 进阶建议 1 伪前提：research 在 <2560px 早已是 `ResizablePanelGroup (15/60/25)` 三栏且可拖拽；`.resp-3col` 固定栏专供 ≥2560（21:9）去拖拽把手。给 research 加 `min-[1920px]:` 兜底会把 1920–2559 正常大屏的拖拽缩放能力剥夺，属回归。驳回。
  - ⏸️ **[PROD-05 · 场景级三栏比例配置 · 暂缓/YAGNI]** 进阶建议 2（把 `.ide-3col` 比例抽成「盯盘/研究/风控」场景配置表）暂不做：当前仅 research 用固定三栏，monitor 走自有 grid、watch 不用 `resp-3col` 固定栏——为单一消费方建场景配置抽象属过度设计。待第二个场景真正需要固定三栏时再抽 `SCENE_THREE_COL_RATIOS`。
  - ✅ **[PROD-05 深化 · 跨 2560 边界入场动画只播一次]** 进阶追问 A 落地：`strategy-ide.tsx` 新增 `ultrawideEntered` state 锁 + 320ms 延时锁定；`playEntry = isUltrawide && !ultrawideEntered` 仅在「首次进入超宽屏」给左右栏挂 `resp-fade-up`（右栏 `animationDelay:0.06s` 仅 playEntry 时下发）。用户在 2559↔2560 间反复拖拽窗口时，固定三栏子树反复重挂不再重播入场动画，消除闪烁。`prefers-reduced-motion` 用户本就无动画，锁逻辑无副作用。
  - ❌ **[PROD-05 · monitor 大屏加超宽屏固定三栏 · 驳回]** 进阶追问 B 伪前提：monitor 是行情墙 tiled-grid（多标的并列卡片）架构，本就非 explorer/editor/AI 线性三栏流；强加 `.resp-3col` 固定三栏是削足适履。其自有 grid 已天然填满超大屏，无需固定三栏介入。属拍脑袋的对称强迫症，驳回。
  - ❌ **[PROD-05 · 抽 useEntryOnce hook 复用入场锁 · 驳回/YAGNI]** 进阶追问 1 过度抽象：一次性入场锁目前仅 `strategy-ide.tsx` 一处消费（解跨 2560 边界重挂闪烁），watch 浮层是用户主动展开的交互反馈无需锁。为单一消费方抽 `useEntryOnce(mediaQuery)` 是提前抽象（YAGNI），且 320ms 锁定魔法数耦合动画时长，抽出去反而多一层间接。待第二处真实场景出现时再抽。
  - ❌ **[PROD-05 · watch 浮层展开只播一次 · 驳回]** 进阶追问 2 伪前提：watch 新闻浮层是用户主动点击展开→面板挂载→`resp-slide-in-right` 播放，收起卸载、再展开重播是**合理交互反馈**（提示「新闻流出现」），非噪音。改「只首次播放」反而让二次展开无过渡、体验割裂；`prefers-reduced-motion` 已兜底。保留每次展开滑入现状。
- [x] **[PROD-06]** 风控面板 Tab 分组（当前 7 个图表区域平铺，一屏放不下）：✅ **2026-07-25**：`AccountSection`（risk-account-section.tsx）新增概览/因子/压测三 Tab，`RiskAdvancedPanel` 支持 `tabs` 过滤复用；敞口卡派生集中度(Top1%)；持仓表常驻。tsc 零错误 + 197 全量零回归
  - Tab 1「概览」：雷达图 + 集中度 + Beta
  - Tab 2「因子」：因子暴露 + 归因 + 相关性矩阵
  - Tab 3「压测」：VaR + CVaR + 历史场景 + 流动性

#### P2 — 产品结构优化

- [x] **[PROD-07]** Calendars 降级为 Macro Hub 子 Tab：✅ **2026-07-25**：`DataCenterModule`(data-center.tsx) 新增概览/市场日历子 Tab，`CalendarsModule` 作为「市场日历」子 Tab 嵌入；侧栏独立入口已移除（route 保留可深链）。tsc 零错误 + 197 全量零回归
  - 当前为独立一级模块（§16 占文档 24%），与 §8 Macro Hub 功能重叠
  - 调整为 Macro Hub 内「全球市场」 Tab，减少一级导航膨胀（12→11 个模块）
  - 保留横向滚动卡片布局，但不再作为独立路由
- [x] **[PROD-08]** 纸面组合状态透明化：
  - 在 §1.6 三模式说明中加醒目提示「⚠️ PAPER 模式依赖 PT-01~02，当前未实现」
  - 前端 PAPER 模式切换时显示「功能开发中」引导
  - 落地：`frontend/src/features/paper/page.tsx` 顶部加模拟环境透明化横幅（⚠️ PAPER：SimBroker 虚拟账本、无真实券商对接/实盘执行）。注：`docs/01` 在本仓库不存在，故仅落地前端横幅；横幅措辞按零幻觉原则改为「真实券商/实盘未打通」，未谎称「未实现」（PT-02b 纸面列表已实装）
- [x] **[PROD-09]** 图表内下单（拖拽式）：✅ **2026-07-25**：新增 `useTradeStore`（模拟持仓/待确认订单，沙箱推演，OMS 未实装）+ `order-confirm-modal.tsx`（买卖/限价止损/数量/SL/TP 确认弹窗）；`lightweight-chart-canvas.tsx` 工具栏新增「下单模式」按钮（带持仓数角标）+ 提示横幅；下单模式下在图上按住拖拽生成紫色预览价格线，松手按相对现价推断方向（低于现价=BUY/高于=SELL）弹出确认框；确认后持仓以 entry(实线)/SL(红虚)/TP(绿虚) 价格线渲染于图上，可拖拽 SL/TP/entry 线直接调整（6px 命中检测，实时跟随、松手落库）。tsc 零错误 + 197 全量零回归
- [x] **[PROD-10]** 策略实验室回测报告布局优化：✅ **2026-07-25**：`main-tabs.tsx` 移除 Tab 切换，`MonacoEditorTab` 常驻挂载（保留滚动位置），回测报告改为可缩放底部面板（`ResizablePanelGroup` 垂直方向，代码 55% / 报告 45%，带 `id`/`order` 稳定条件渲染）；顶部工具栏新增「查看/隐藏回测报告」切换；`activeWorkspaceTab='report'` 语义重映射为"打开报告面板"（沙箱/优化完成后自动展开，代码仍可见）；Monaco 启用 `automaticLayout` 以适配面板缩放。tsc 零错误 + 197 全量零回归
  - 旧方案：回测报告与代码共享 Tab，切换丢失代码滚动位置

#### P3 — 长期差异化

- [x] **[PROD-11]** 自定义指标脚本（对标 TradingView Pine Script）：✅ **2026-07-25**：`custom-indicator/engine.ts`（纯函数表达式引擎：递归下降解析器 + 向量化求值，支持字段 OPEN/HIGH/LOW/CLOSE/VOLUME、命名空间 KDJ.{K,D,J}/MACD.{DIFF,DEA,HIST}/BB.{UPPER,LOWER,MID}、函数 MA/EMA/RSI/REF/CROSS/HHV/LLV/ABS/SQRT/MAX/MIN，MA/EMA/RSI 支持单参(作用于CLOSE)或双参；复用 worker 同款 RSI/KDJ/MACD/BOLL 算法）+ `suggestPane`(振荡器自动建议副图) + `collectBoolSignals`(上穿跳变收集) + `runSignalBacktest`(事件驱动回测)；`store.ts`（zustand persist 持久化用户脚本 + `signalLog` 信号日志上限50）；`panel.tsx`（图表内抽屉：列表/新增/编辑/删除/显隐 + 实时语法校验与结果预览 + 语法帮助 + 列表项「信号回测」按钮与结果卡片 + 信号触发日志区块）；`lightweight-chart-canvas.tsx` 工具栏「ƒ」按钮：数值型按 `pane`(overlay 主图/separate 独立副图/auto) 选坐标（separate 走 `ci-separate` priceScale 贴底副图，避免 RSI/MACD 扭曲主图价格尺度），布尔型以主图 markers 标记 + 末根上穿实时写入 `signalLog` 并弹 Toast 提醒（延迟 2s 武装，避开首屏历史信号轰炸）。预置 RSI(14)/RSI(14)>KDJ.K/MA5上穿MA20 示例，默认隐藏。新增 `engine.test.ts`（15 用例）。tsc 零错误 + 212 全量零回归

  - **追问2 · 信号触发 Toast + 浏览器系统通知（跨标签页）**：✅ **2026-07-25**：`lightweight-chart-canvas.tsx` 末根上穿在弹 Toast 同时 `new Notification` 联动浏览器系统通知（后台/跨标签页仍可见）；`ciNotifAskedRef` 仅首次 default 权限时请求一次，避免重复弹窗；Toast 仍走延迟 2s 武装（仅实时新信号提醒）。
  - **追问3 · 自定义表达式接入真实回测引擎**：✅ **2026-07-25**：`engine.ts` 新增 `runCustomExprBacktest(expr, bars, initialCapital)` 生成与后端 `/backtest/run` 完全兼容的 `equity_curve/trades/metrics`（含总收益/年化/夏普/最大回撤/胜率/盈亏比），UI 全部自动复用（Tear Sheet / 权益曲线 / 水下图 / 交易明细）；`use-backtest.ts` 新增 `customExpr` 状态 + `handleRun` 分支（选「__custom_expr__」策略时经 `/market/history` 拉真实 K 线 → 映射 CIBar → 本地计算 → `setBacktestResult`+`setRawReturns`，interval/period 映射 ktype/num 并支持中断）；`backtest-config.tsx` 策略下拉加「自定义指标脚本 (Pine)」选项 + 表达式 textarea（实时校验，红错/绿对提示）；`backtest.tsx` 透传。新增 `engine.test.ts` 用例。`tsc` 零错误 + 214 测试零回归
  - **追问4 · 信号触发日志导出复盘 CSV**：✅ **2026-07-25**：`panel.tsx` 信号日志区块头部新增「导出」按钮（`Download` 图标），一键将**全量** `signalLog`（store 上限 50，面板仅展示 12 条）生成 CSV 下载（字段：指标ID/名称/表达式/触发日期/触发时间），含字段引号转义 + BOM 头保证 Excel 中文不乱码，文件名带日期。`tsc` 零错误 + 214 测试零回归
  - **追问5 · 自定义表达式参数化（@参数）**：✅ **2026-07-26**：`engine.ts` 词法器识别 `@name` 参数令牌、语法树新增 `param` 节点、求值器从 `params` 映射代入（缺失返回 `ok:false` 而非抛错，与 UI 消费一致）；新增 `listParams(expr)` 提取引用参数（去重保序）；`validate(expr, params?)` 支持参数校验（缺失报错）；`collectBoolSignals/runSignalBacktest/runCustomExprBacktest` 全部透传 `params`；`store.ts` 的 `CustomIndicator` 加 `params?: Record<string,number>`；`panel.tsx` 编辑表单按 `listParams` 自动生成参数输入框（数值）、保存写入指标、`evaluate` 预览与「信号回测」均代入 `params`；`lightweight-chart-canvas.tsx` 渲染时 `evaluate(ind.expr, bars, ind.params)`。新增 `engine.test.ts` 参数化用例（listParams/代入/缺失/validate/回测）。`tsc` 仅剩无关文件 `fullscreen-copilot.tsx` 预存错误，本改动零错误 + 219 测试零回归
  - **追问6 · 参数网格搜索（@参数穷举）**：✅ **2026-07-26**：`engine.ts` 新增 `runParamGridSearch(expr, bars, grid, opts?)`——对含 `@参数` 的自定义表达式做 min/max/step 笛卡尔积穷举，逐组复用 `runCustomExprBacktest` 计算回测指标（累计收益/夏普/胜率/最大回撤/交易数），按选定指标排序返回 Top-N 与全局最优 `best`；组合数上限 1000 保护（超限返回明确错误），K 线不足/空网格优雅报错，非法或非布尔组合标记为 `ok:false` 不参与排序。UI 在编辑表单参数区下新增「网格搜索最优参数」折叠面板：逐参数 min/max/step 输入 + 排序维度选择（累计收益/夏普/胜率/最小回撤）+ 运行按钮 + Top-N 结果表（排名/参数组合/收益%/夏普/一键「应用」回填参数）。前端同源复用 `evaluate` 引擎，零新增数据依赖。`tsc` 本改动零错误 + 225 测试零回归（含 6 个新增网格搜索用例）
  - **增强（追问1 · 副图独立坐标）**：store 增加 `pane` 字段（overlay 主图 / separate 独立副图 / 未设=auto）；`engine.suggestPane()` 对振荡器(RSI/KDJ/MACD/BB)自动建议 separate，避免 RSI(0-100) 叠加主图扭曲价格尺度；图表端 separate 走独立 priceScale(`ci-separate`) + scaleMargins 贴底副图。
  - **增强（追问2 · 信号接入提醒/回测）**：`engine.collectBoolSignals()` 收集布尔表达式上穿(0->1)跳变点；store 新增 `signalLog`（持久化、上限50）；图表端检测「末根 K 线上穿」实时 push 触发点（去重，不递归），面板新增「信号触发日志」区（时间/名称/表达式 + 清空），可直接对接交易提醒与回测条件触发。新增 `engine.test.ts`（12 用例）。tsc 零错误 + 209 全量零回归
- [x] **[PROD-12]** 多图表同步十字线：✅ **2026-07-25**：新增 `chart-crosshair-sync.ts` 单例同步管理器（按 `syncGroup` 分组）；`LightweightChartCanvas` 接入注册/广播/应用（带防回环锁，外部同步不二次广播）；`quotes.tsx` 新增「同步对比」分屏模式（上下双图、各自独立 WebSocket/历史数据，共享 `syncGroup='default'`），移动任一图十字线同组其他图同步跳动。tsc 零错误 + 197 全量零回归

#### AI 全模块渗透（三层架构：主动推送 / 嵌入式辅助 / 按需调用）

> 设计原则：可关闭（每模块独立开关）/ 有阈值（异动>2%才触发）/ 可折叠（默认一行摘要）/ 不阻断（P0风控除外）/ 有溯源（数据来源+置信度）

- [ ] **[AI-01]** 市场指挥中心 · 异动解说员（P1）：
  - 价格异动 >2% 时 K 线上方浮动气泡："📰 财报 miss 预期，营收低于共识 8%"
  - 形态识别（头肩顶/双底/三角收敛）→ K 线叠加虚线标注 + 历史胜率
  - 盘口解读：大单集中检测 → 盘口面板底部一行提示
- [ ] **[AI-02]** 智能选股器 · 因子顾问（P1）：
  - 条件构建时主动建议："加 ROE>10% 可排除价值陷阱，历史胜率 +12%"
  - 结果异常标记：PE 异常低 → "⚠️ 疑似一次性收益扭曲，建议查看扣非 PE"
  - 结果摘要卡：行业集中度/因子偏向/建议补充约束
- [ ] **[AI-03]** 回测工坊 · 报告解读员（P1）：
  - Tear Sheet 顶部 AI 摘要："年化 23% 但 Sharpe 仅 0.9，收益主要来自杠杆而非 Alpha"
  - 过拟合预警：参数敏感性差异 >40% 时主动提示
  - [🤖 AI 优化建议] 按钮：加波动率过滤 / ATR 动态止损 / 行业中性约束
- [ ] **[AI-04]** OMS · 执行风控官（P1）：
  - 下单确认弹窗内 AI 预检："⚠️ VIX=28（高波动），建议减半仓位或改用限价单"
  - 持仓健康诊断（每日）："AAPL 已偏离入场逻辑，原策略信号失效，建议止盈"
  - Bot 异常诊断：连续止损 → 分析原因 + 建议暂停/切换策略
- [ ] **[AI-05]** 风控面板 · 风险预警员（P1）：
  - 雷达图维度变红时主动推送："集中度 82/100，若纳指回调 5%，组合预计 -3.4%"
  - 压测情景推荐：基于当前持仓推荐最相关的 3 个历史情景
  - 对冲建议：因子暴露 >0.8 时建议具体对冲操作
- [ ] **[AI-06]** 告警中心 · 分诊员（P2）：
  - 告警触发时关联分析："AAPL 突破 + 同日 3 只科技股突破 → 板块性行情"
  - 多告警同时触发时智能排序：止损优先，价格突破可延后
  - 新建告警时规则建议："加 RSI>75 过滤假突破？历史假突破率 34%"
- [ ] **[AI-07]** 纸面组合 · 实盘教练（P2）：
  - deploy 前 AI 就绪评估：运行天数/Sharpe/样本量/偏差分析
  - 纸面 vs 回测偏差预警："纸面 Sharpe 0.8 vs 回测 1.6，主因滑点未计入"
  - 周度绩效归因自动生成：选股贡献/择时贡献/行业贡献
- [ ] **[AI-08]** 宏观数据中心 · 事件推演（P2）：
  - 高危事件旁 AI 推演卡："FOMC 若加息 25bp → 港股科技预计 -2~3%"
  - 指标与持仓关联：VIX hover → "你的组合 Beta 1.1，VIX 每升 5 点日波动 +¥8,200"
- [ ] **[AI-09]** AI 推送偏好设置（P2）：
  - Settings 中每模块独立开关（市场异动/选股建议/回测解读/风控预警/告警分诊）
  - 触发阈值可调（异动 1%/2%/5%）
  - 自然语言配置："把告警推到 Telegram，只推 P0 和 P1"

#### 数据源能力矩阵与产品形态升级（2026-07-26 产品功能审计）

> **背景**：对标 Bloomberg Terminal 全能力矩阵，识别现有工具链覆盖盲区，优先补齐可直接复用后端 Tool 的高价值功能。
> **产品设计文档**：`docs/01 §十七`（数据源能力矩阵与产品形态升级）

##### 期权与波动率曲面（已有 `get_broker_market_data(action="OPTION_CHAIN")` 后端基础）

- [x] **[OPTION-01]** 个股期权隐含波动率实时面板（P1）：
  - 前端：选定标的 → 期权链表格（行=行权价、列=到期日）+ 单元格 IV% 渐变色热力图
  - 后端：扩 `OPTION_CHAIN` action 返回 Greeks（Delta/Gamma/Vega/Theta）+ IV
  - 预期工时：FE 8h + BE 4h
- [x] **[OPTION-02]** 波动率曲面 3D 可视化（P2）：
  - ECharts GL 三维曲面图（X=行权价、Y=到期日、Z=IV）
  - 叠加 skew 曲线（横截面）+ term structure 曲线（纵截面）
  - 依赖 OPTION-01
  - 预期工时：FE 6h
- [x] **[OPTION-03]** Put/Call Ratio 实时面板（P1）：
  - 总 PCR + 分到期日 PCR + 历史 20 日均值对比线
  - 后端复用 `get_macro_sentiment_history` 的 PCR 数据源
  - 前端 ECharts 双轴（柱状 PCR + 折线标的收盘价），关联市场情绪解读
  - 预期工时：FE 4h + BE 2h
- [x] **[OPTION-04]** 期权数据真实源接入与 mock 清退收尾（P1）：
  - 后端 `FutuAdapter._fetch_option_chain` 接入真实 Futu 期权链（`Ctx.get_option_chain_by_date_strike`），取消 `数据源已死` 告警，恢复 OPTION-01 面板真实数据
  - 后端 `/iv-rank` 接入真实历史 IV 序列源（Redis/DB），取消 `random` 伪造告警，恢复 IV Rank 计算
  - 验收：OPTION-01 期权 IV 曲面面板 + IV Rank 在真实数据源下可用，全链路零 mock
  - 依赖 OPTION-01（mock 已清退，待真实源接入）
  - 预期工时：BE 6h

##### 资金流向增强（已有 `action="FUND_FLOW"` 后端基础）

- [ ] **[FUNDFLOW-01]** 北向资金/主力资金实时看板（P1）：
  - A股：北向资金净流入（日/周/月）+ 行业分布饼图
  - 港股：南向资金 + 港股通十大成交榜
  - 美股：大单（Block Trade）净流入 + 机构持仓变化 Tide Chart
  - 前端组件：`FundFlowDashboard`（Tab 切换三市场）
  - 预期工时：FE 8h + BE 4h
- [ ] **[FUNDFLOW-02]** 龙虎榜/经纪商席位排行（P2）：
  - 港股 Broker Queue（买入最多 / 卖出最多经纪商）+ 席位异动标记
  - A股龙虎榜：机构 vs 游资标签 + 近3日净买额排序
  - 依赖 FUNDFLOW-01 后端数据管道
  - 预期工时：FE 6h + BE 4h

##### 财报与研报本地 RAG（已有 `analyze_financial_report` + `search_global_knowledge`）

- [ ] **[EARN-02]** 财报/研报 RAG 问答面板（P1）：
  - 前端：`EarningsQAPanel` 聊天式面板（上传 PDF / 粘贴文本 / 拉取已入库报告）
  - 后端：`POST /api/v1/rag/chat` — 输入问题 + 指定报告 ID → RAG 检索 + LLM 回答（带引用章节跳转）
  - 支持追问链（conversation_id 持续上下文）
  - 预期工时：FE 8h + BE 6h
- [ ] **[EARN-03]** 研报语义检索增强（P2）：
  - 自然语言检索："找出所有提到 CapEx 上修的公司"
  - 检索结果展示：相关段落高亮 + 原文跳转 + 报告日期 / 分析师来源
  - 依赖 EARN-02 问答面板作为 UI 入口
  - 预期工时：FE 4h + BE 4h

##### 宏观日历高危事件雷达（已有 `get_macro_calendar`）

- [ ] **[MACRO-05]** 高危事件自动标红与倒计时（P1）：
  - 前端：Macro Hub 侧边栏增加「🔥 高危事件」卡片（FOMC/NFP/CPI 自动标红 + 倒计时天时分）
  - 点击展开：事件详情（前值 vs 预期 vs 共识分歧宽度） + ⚡ AI 推演卡（"若加息25bp → 港股科技预计 -2~3%"）
  - 依赖 AI-08（事件推演）后端能力
  - 预期工时：FE 6h + BE 2h

##### 情绪量化（已有 `get_macro_sentiment_history` + `get_company_news`）

- [ ] **[SENT-01]** 市场情绪综合得分面板（P1）：
  - 后端：加权合成 VIX(30%) + P/C Ratio(25%) + Credit Spread(25%) + 新闻情绪(20%) → 0~100 情绪指数（0=极度恐惧、100=极度贪婪）
  - 前端：Fear & Greed Index 风格仪表盘 + 历史时间序列折线图 + 极端位（<20 / >80）标注
  - 预期工时：FE 4h + BE 4h
- [ ] **[SENT-02]** 个股舆情情感时间序列（P2）：
  - 基于 `get_company_news` 的新闻标题/摘要做 NLP 情感打分（-1~+1），绘制每日情感均值折线
  - 叠加股价走势副图（情感滞后 or 同步）
  - 预期工时：FE 4h + BE 4h

##### 决策工具产品形态

- [x] **[BRD-01]** 早报刊物一键生成器（P1）：✅ 已完成
  - 触发方式：Dashboard 顶部「☕ 生成早报」按钮 + 定时任务（日盘前 15min 自动推送，worker 守护注册）
  - 内容编排：宏观日历 → 核心标的监控 → 新闻提纯 → 多空概率矩阵 → 主脑综合研判
  - 严格遵循 `AGENTS.md §7` 早报模板 + 新闻卡片格式
  - 输出：浏览器端 Markdown 预览 + 一键复制 / 分享为 URL（落地页 `/briefing/:id`）
  - 后端：编排 `get_macro_calendar` + `get_broker_market_data(QUOTE)` + `get_macro_news` + `get_macro_sentiment_history` → LLM 组装 Markdown（`services/morning_briefing/`：generator + storage(Redis/内存兜底) + scheduler）；路由 `POST /api/v1/briefing/generate`、`GET /briefing/latest`、`GET /briefing/share/{id}`
  - 前端：Navbar 按钮 → Dialog（react-markdown 渲染 + 复制 + 分享链接）；LLM 失败有数据兜底骨架
  - 单测 `tests/test_morning_briefing_generator.py` 覆盖正常/LLM 失败兜底/模块封装三路径
  - 🔧 **市场切换（后续增强）**：`MARKET_TICKERS = {全球/美股/港股/A股}` 按市场选不同监控标的；Modal 顶部 Select 下拉切换市场（默认全球），切换即按该市场重新生成；分享页 `/briefing/:id` 头部展示市场标签。**分享页保持 ProtectedRoute 内，不对未登录公开**。
  - 🔧 **本地验证（本机实跑，非仅留 CI）**：前端 `npm run type-check` + `npm run build` 全绿；后端 `pytest tests/test_morning_briefing_generator.py` 3 用例全 PASS。验证过程抓出 4 个会进 CI 的真实 bug 并已修复：① navbar 漏 import `MorningBriefingModal`（自 BRD-01 首提交即缺失，前端构建一直挂）；② 早报 `apiClient` 解包错 `res.data.data`→应为 `res.data`（`morning-briefing-modal`/`briefing-share-page` 两处 TS 类型错）；③ `fullscreen-copilot` 缺必填 `kind` 字段（补 `analysis` 枚举）；④ **后端 `generator.py` 的 `ToolRegistry` 导入路径错**（`backend.core.tool_registry` 不存在，应为 `hermes_agent.tool_registry`——会导致整个早报引擎 import 失败、端点 500）+ 市场切换改写时 `MARKET_TICKERS`/`get_tickers_for_market` 与 `_collect_data(market, tickers)` 调用未真正落盘，已补全。
  - 预期工时：FE 6h + BE 6h
- [x] **[COND-01]** 自定义指标网格搜索结果保存为"策略配方"（P2）：
  - ✅ 已完成 `runParamGridSearch` 引擎 + UI（PROD-11 追问6）
  - ✅ 已完成回测交易明细 CSV 导出（PROD-11 追问 G · `0a43300`）
  - ✅ 已完成策略配方持久化（COND-01 · `f96f9ee`）：`store.ts` 新增 `StrategyRecipe` 接口 + `recipes` 持久化 + `saveRecipe/removeRecipe` action（zustand persist version=1，localStorage 键 `quant-custom-indicators`）；`panel.tsx` 网格结果「存为配方」按钮 + 内联命名/备注表单 + 「📂 配方库」列表（参数快照/收益/夏普/胜率/应用/删除）；`store.test.ts` +4 用例。全量 234 tests passed
  - 注：采用前端 localStorage 持久化（与 indicators/signalLog 同源），未引入后端 `strategy_recipes` 表（保持客户端优先、零后端依赖，符合沙箱推演定位）
  - 配方列表（我保存的策略配方）+ 一键对比 + 导出 JSON / 分享
  - 预期工时：FE 6h + BE 4h
- [x] **[ALERT-COND-01]** 条件单沙盒（P2）：
  - 前端：条件构建器（选择指标 + 运算符 + 阈值，支持 AND/OR 组合）→ 模拟命中通知（浏览器弹窗 / App Push 沙盒）
  - 后端：沙盒引擎轮询 1min 持续评估，命中后写 `alert_logs_sandbox` 表 + 前端消费 SSE
  - 目前 OMS 未实装，仅模拟通知，待实盘切换后可直接复用为真条件单
  - 预期工时：FE 8h + BE 8h
  - ✅ 状态：**已完成（前端沙盒优先，2026-07-26）**。采用前端 localStorage 持久化（与 indicators/signalLog 同源），未引入后端 `alert_logs_sandbox` 表（保持客户端优先、零后端依赖，符合沙盒推演定位）；轮询引擎在面板挂载时按可配置间隔（默认 30s，可选 10s/30s/1min/5min，规格基准 1min）持续评估末根 K 线，上升沿命中即写本地 `alertLog` + Toast/浏览器 Push 双通道模拟通知。后端 SSE 表为后续实盘切换的演进路径。

##### 社区与协作（数据治理层）

- [ ] **[COMM-01]** 数据源健康度统一看板（P2）：
  - 前端：`DataSourceHealthDashboard` — 卡片矩阵（每个数据源一个卡片：名称 / 状态 / 延迟 / 今日调用量 / 成功率 / 限流次数）
  - 实时数据来源：`/api/v1/datasource/{name}/health` + `rate_limit_registry` 状态
  - 报警：数据源 STALE > 5min → 卡片变红 + WebSocket 推送
  - 预期工时：FE 6h
- [ ] **[COMM-02]** 数据源贡献投票与需求看板（P3）：
  - 前端：展示「已接入 / 开发中 / 社区投票中」三类数据源
  - 用户可投票（1 票/天），影响下一个接入优先级
  - 后端：投票记录 + 计数器，防止刷票
  - 预期工时：FE 4h + BE 3h

##### 智能选股器产品化

- [ ] **[SCREEN-01]** 选股条件保存与分享（P1）：
  - 前端：筛选器面板「💾 保存条件」→ 命名 + 描述 → `saved_screens` 表
  - 「📂 我的筛选条件」下拉列表（加载 / 删除 / 重命名）
  - 「🔗 分享」→ 生成可分享 URL（编码筛选条件为 query params，对方打开自动填充）
  - 预期工时：FE 6h + BE 3h

---

### AI Copilot 一体两态重构（COPILOT 系列 · 2026-08-21）

> **设计稿**：`AI Copilot_UI重构设计.md` (v1.0) + `AI Copilot_Figma导入稿.html`
> **核心决策**：**一体两态** —— 保留全局浮动抽屉（轻量随问随答）+ 左导航新增「投研」工作台（深度投研会与资产沉淀），两形态共享同一 Zustand 会话状态。
> **现状诊断**：5 个 P0（双 ChatProvider 不同步 / 假附件入口 / 思维链事件丢弃 / 事件名冲突 / 投研会无持久化）+ 6 个 P1（13 专家挤 520px / 模拟恐惧贪婪指数 / 无鉴权 / 迭代上限无披露 / 三套快捷指令 / 文件超限）。

#### P0 — 阻塞性架构债（必须先解）

- [x] **[COPILOT-01]** **会话状态提升为 Zustand store 单例**（P0-1 根治）：✅ `854e43c`
  - `chat-context.tsx`（480 行巨石 Provider）→ 拆为 `useChatStore`（Zustand，会话/消息/流状态）+ `chat-stream-service.ts`（≤200 行，SSE 解析独立）
  - 抽屉（`global-copilot-drawer.tsx`）与投研页（`/research`）订阅同一 store，根治双 `<ChatProvider>` 实例会话互不可见
  - 保留现有能力：折叠不卸载 / 页面上下文注入 / 会话双层持久化 / tool_call_id 精准重组 / Markdown 导出
  - 依赖：无（所有后续 COPILOT 任务的前置）
  - 预期工时：FE 12h
- [ ] **[COPILOT-02]** **撤下假附件入口 + 上下文 chip 可视化**（P0-3）：
  - 移除 `chat-input-box.tsx` 的图片/PDF 上传三入口（选择/粘贴/拖拽，L78-139）
  - 输入区左下改放「附加页面上下文」chip（虚线 "+ 附加本页上下文"，有上下文时显示实线 chip + kind 图标：kline=蜡烛/risk=盾/screener=漏斗/analysis=星）
  - 后端 `chat.py:215` 的 `attachments=None` 硬编码保留（附件上传 `POST /chat/uploads` 列为 roadmap）
  - 依赖：COPILOT-01
  - 预期工时：FE 4h
- [ ] **[COPILOT-03]** **思维链四阶段进度器**（P0-4）：
  - 消费真实事件：`reasoning_chunk`（Plan）→ `tool_start/tool_result`（Tool）→ 二次同类 tool 或 `</think>` 标记（Verify）→ `text_chunk`（Output）
  - 视觉：四阶段进度条 `[规划 Plan]──[调用工具 Tool]──[核验 Verify]──[输出 Output]`，Plan=紫色呼吸点+可展开推理片段，Tool=chip 名称+参数摘要，heartbeat 驱动呼吸动画
  - 30s 无任何事件 → amber「响应缓慢，后端可能排队」，不转假圈
  - 依赖：COPILOT-01
  - 预期工时：FE 8h
- [ ] **[COPILOT-04]** **统一事件协议**（P0-5）：
  - `copilot-prefill` 与 `quant_copilot_invoke` 二选一收敛为 `quant_copilot_invoke`（detail 携带 `{prompt, symbol, kind}`）
  - 修复 `symbol-context-menu.tsx:45-52` dispatch 的 `copilot-prefill` 无监听者问题
  - 全仓监听统一为 `quant_copilot_invoke`（`chat-context.tsx:453-461` 已有路径）
  - 依赖：无（可与 COPILOT-01 并行）
  - 预期工时：FE 2h
- [ ] **[COPILOT-05]** **投研会历史诚实空态 + 后端 save_session**（P0-2）：
  - 后端：`expert_team_service.py` 补 `save_session`（Redis 热 TTL 12h + PG 冷，对齐 chat 双层模式），`GET /expert-team/sessions` 返回真实历史
  - 前端：辩论室历史区在后端落库前显示 EmptyState「投研会记录将在后端持久化上线后出现——当前刷新即失」，**禁止用内存数据伪装历史**
  - 依赖：BE 侧 save_session 实现
  - 预期工时：FE 4h + BE 6h

#### P1 — 体验缺陷修复

- [ ] **[COPILOT-06]** **投研会迁出抽屉 → 投研页辩论室**（P1-1）：
  - 13 专家配置区（`roster-panel.tsx` 232 行）+ 流式辩论（`team-session.tsx` 202 行）从 520px 抽屉整体迁至左导航「投研」页宽屏
  - 抽屉头部不再出现「对话 / AI 投研团队」tab 切换，只保留对话
  - 依赖：COPILOT-01, COPILOT-05
  - 预期工时：FE 8h
- [ ] **[COPILOT-07]** **移除模拟恐惧贪婪指数**（P1-2）：
  - `session-sidebar.tsx:40-52` 的装饰性恐惧贪婪指数（与真实数据无链路）删除
  - 依赖：无
  - 预期工时：FE 1h
- [ ] **[COPILOT-08]** **投研会鉴权 + API 口径统一**（P1-3）：
  - 后端：`/expert-team/analyze` 补 `Depends(get_current_user)`（`expert_team.py:18-47`）
  - 前端：`expert-team-client.ts:91-142` 从裸 `apiClient.stream` 改走 `fetchWithAuth`（对齐 `chat-context.tsx:243` 口径）
  - 依赖：BE 侧 Depends 实现
  - 预期工时：FE 2h + BE 2h
- [ ] **[COPILOT-09]** **迭代上限 UI 披露**（P1-4）：
  - `max_iterations=8` 达限时在消息流顶部渲染 amber 提示条「已达 8 步推理上限，以下为降级模型兜底总结」
  - 依赖：COPILOT-01（需从 store 读取迭代计数）
  - 预期工时：FE 2h
- [ ] **[COPILOT-10]** **快捷指令统一配置源**（P1-5）：
  - 合并三套快捷指令为单一配置模块：页面级四件套（预填式，`STOCK_QUICK_COMMANDS`）+ 场景级（投研页欢迎区）+ 动态建议（后端 `/chat/suggestions`，失败回退静态四条并标注兜底角标）
  - 消除 `chat-context.tsx:17-22` / `fullscreen-copilot.tsx:23-64` / `chat.py:138-159` 三处并存
  - 依赖：无
  - 预期工时：FE 4h + BE 2h
- [ ] **[COPILOT-11]** **超限文件拆分**（P1-6）：
  - `chat-message-item.tsx`(589) → 按消息类型拆为 text/tool/strategy/chart 四个分子组件（各 ≤150）
  - `chat-input-box.tsx`(286) / `session-sidebar.tsx`(251) / `roster-panel.tsx`(232) / `team-session.tsx`(202) 按职责拆分至规范行数内
  - 后端：`agent.py`(1144) / `chat.py`(383) / `orchestrator.py`(546) 按 AGENTS.md §3 硬顶拆分
  - 依赖：COPILOT-01（`chat-context.tsx` 480 行在 Zustand 提升时同步拆）
  - 预期工时：FE 8h + BE 6h

#### 新功能 — 投研工作台（形态 B · 左导航「投研」）

- [ ] **[COPILOT-12]** **左导航新增「投研」路由 + 三列布局骨架**：
  - `/research` 路由 + 三列骨架：B1 会话中心(240px) / B2 主区(≥880px, 1fr) / B3 运行信息(280px, 可折叠)
  - 页面标题条：「投研」+ 副标题"Hermes ReAct · {tools_count} tools · {model_name}"（数据来自注册表，禁止写死）
  - 右侧：SANDBOX/LIVE 全局徽章（与策略工作台同口径）
  - 依赖：COPILOT-01
  - 预期工时：FE 6h
- [ ] **[COPILOT-13]** **B1 会话中心**：
  - 顶部双按钮：`+ 新对话`（蓝）/ `+ 发起投研会`（紫 `#A78BFA`）
  - 搜索框 + 分组列表（今天 / 近 7 天 / 更早）+ 类型图标（💬 对话 / ⚖️ 投研会）+ 投研会结果徽章（多/空/中性，来自 `chief_report.bullish_probability` 分档）
  - 悬停操作：删除（加二次确认 inline）；重命名入口待后端落库后开放
  - 底部：导出当前会话 Markdown（现状能力迁移）
  - 依赖：COPILOT-12
  - 预期工时：FE 6h
- [ ] **[COPILOT-14]** **B2 对话模式（宽屏版）**：
  - 复用抽屉 MessageStream 组件实例（与抽屉共享，非新组件）
  - 宽屏增强：消息流最大宽度 760px 居中；长工具结果表格展开完整；助手消息右上操作栏（复制 / 重答 / 存入资产库）
  - 顶部工具条：`ReAct · 第 n/8 步` + session_id 短码 + 导出按钮
  - 图表注解卡点击联动个股工作台（深链 `/market/:ticker`）
  - 依赖：COPILOT-12, COPILOT-01
  - 预期工时：FE 6h
- [ ] **[COPILOT-15]** **B2 辩论室·组局态（Proposition Composer）**：
  - 四组配置居中 720px：① 投研命题 textarea（3 行起，占位符示例 + "从当前持仓生成"辅助按钮）② 投研场景 4 张单选卡（金融投研/完整投决会/交易决策/代码审查，数据来自 `GET /expert-team/scenarios`，静态镜像标兜底角标）③ 出战阵容 13 专家网格（多选，默认按场景推荐勾选，代码域 4 人仅代码审查场景出现）④ 辩论轮数分段控件 1/2/3
  - 底部 CTA：`▶ 发起投研会`（紫），命题空禁用
  - 预估耗时提示：`≈ 专家数 × 轮数 × 20s`（标注"估算"）
  - 依赖：COPILOT-12
  - 预期工时：FE 8h
- [ ] **[COPILOT-16]** **B2 辩论室·辩论态（Debate Room）**：
  - 三列：观点流（按事件顺序追加，可折叠上一轮）/ 实时阵营面板(220px，多/空/中性人数柱 + 平均信心滑动)
  - 顶部横向轮次时间线：R1 ✓ → R2 ●(进行中) → 首席收敛 ○
  - 专家卡：头像·角色·阵营色边（多=emerald / 空=red / 中性=gray）+ stance 徽章 + confidence 条 + challenges 列表
  - `round_complete` 事件：时间线打勾 + 轮分隔条「第 N 轮结束 · 共识度 X%」
  - 断流处置：SSE 中断 → amber 横幅「连接中断 · 已保留 N 条观点 · 重试」
  - 停止按钮：■ 中止，落「已停止」态（保留已产出，明示未完成）
  - 依赖：COPILOT-15
  - 预期工时：FE 10h
- [ ] **[COPILOT-17]** **B2 辩论室·收敛态（Chief Report）**：
  - 首席投资官报告卡（居中 760px）：① 概率仪表（`bullish_probability` 0-100 半环仪表，≥60 emerald / 40-60 gray / <40 red）② 结论摘要段落（流式渲染）③ 关键分歧保留区（多/空两列对照）④ 元信息行（专家数·轮数·总耗时·模型）
  - 操作行：`存入资产库` / `导出 Markdown` / `调整阵容重跑`（回填组局态）/ `追问首席`（以该会话继续对话模式）
  - 依赖：COPILOT-16
  - 预期工时：FE 6h
- [ ] **[COPILOT-18]** **B2 资产库**：
  - 卡片列表：类型图标（📄 对话导出 / ⚖️ 首席报告）+ 标题 + 来源会话 + 日期；搜索框；点开只读预览（Markdown 渲染）
  - 数据来源：对话导出（从"下载文件"升级为"同时存档"）+ 首席报告存档
  - 后端落库前显示 EmptyState「还没有沉淀的研究成果——完成一次投研会或导出对话后，这里会成为你的研究档案室」
  - 依赖：COPILOT-05
  - 预期工时：FE 4h
- [ ] **[COPILOT-19]** **B3 运行信息列（可折叠）**：
  - 页面上下文：`useCopilotContextStore` 内容（kind 图标 + summary 摘要），「附加到下一条消息」开关
  - 工具调用记录：本次会话 tools 流水——名称、耗时、缓存命中角标（`tool_registry.py:94-122` Redis 缓存）、失败红点；连续失败 3 次的工具显示熔断徽章「已熔断 · 检查数据源」
  - 运行参数：模型名（LLM_MODEL）、迭代 `n/8`、会话 TTL（热 12h）
  - 折叠后关键状态（迭代数、熔断）以头部微徽章透出
  - 依赖：COPILOT-12
  - 预期工时：FE 4h
- [ ] **[COPILOT-20]** **抽屉头部「展开」按钮**：
  - 点击跳转 `/research?session={id}`，同一 session_id 无缝进入投研页继续
  - 流式进行中「展开」按钮显示脉冲点，提示"流不会中断"
  - 反向：投研页头部「收起」按钮返回抽屉形态
  - 依赖：COPILOT-12, COPILOT-01
  - 预期工时：FE 2h

#### 数字可信与状态规范

- [ ] **[COPILOT-21]** **工具失败明示 + 数据 STALE 角标**：
  - 工具失败的消息渲染红色失败块「数据获取失败：{原因}，以下结论不含该项数据」——禁止估计值兜底
  - 工具结果卡显示取数时间戳；超 5 分钟（行情类）/ 1 日（基本面类）加 STALE 角标（`text-amber-500` + 区域 `opacity-60 saturate-50`）
  - 依赖：COPILOT-01
  - 预期工时：FE 3h
- [ ] **[COPILOT-22]** **SANDBOX/LIVE 全局徽章 + 策略卡**：
  - `strategy_code` 事件渲染为 SANDBOX 卡：深色代码预览 + 徽章「SANDBOX · 未实盘」+ 按钮"去策略研发工作台"（深链携带代码块 id）
  - LIVE 文案永不出现在 `REAL_TRADE_EXECUTE` 闸门通过之前
  - 交易执行类工具（`manage_broker_orders_and_account`）的任何调用在工具记录里标红边
  - 依赖：COPILOT-01
  - 预期工时：FE 3h

#### 依赖图

```
COPILOT-01 (Zustand 提升) ──► {COPILOT-02, COPILOT-03, COPILOT-09, COPILOT-11}
COPILOT-01 ──► COPILOT-12 (投研页骨架) ──► {COPILOT-13, COPILOT-14, COPILOT-15, COPILOT-19, COPILOT-20}
COPILOT-15 ──► COPILOT-16 ──► COPILOT-17
COPILOT-05 (投研会持久化) ──► COPILOT-06 ──► COPILOT-18
COPILOT-04 (事件协议) 独立
COPILOT-07 (移除假指数) 独立
COPILOT-08 (鉴权) BE 依赖
COPILOT-10 (快捷指令) 独立
COPILOT-21/22 (数字可信) ──► COPILOT-01
```

#### 验收清单（对齐设计稿 §10）

1. 抽屉与投研页可互跳同一会话，流式不中断（COPILOT-01 + COPILOT-20）
2. 右键"问 AI 分析"预填 100% 到达输入框（COPILOT-04）
3. 思维链进度器四阶段由真实事件驱动，无事件时不假动（COPILOT-03）
4. UI 中不存在图片/PDF 上传入口（COPILOT-02）
5. 投研会三态完整：组局配置来自真实 scenarios 端点 / 辩论态流式渲染带断流横幅 / 收敛态概率仪表+分歧保留（COPILOT-15~17）
6. 投研会历史区在后端落库前保持诚实空态（COPILOT-05）
7. 所有数字可溯源到工具调用；失败明示不估计（COPILOT-21）
8. 无一处假数据/装饰指数（COPILOT-07）
9. 行数：新拆文件全部低于 AGENTS.md §3 硬顶（COPILOT-11）

---

