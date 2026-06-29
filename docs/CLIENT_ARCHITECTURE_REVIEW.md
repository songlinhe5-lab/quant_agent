# 客户端架构 Review 报告

> **审计范围**：Web 前端（React SPA）+ Flutter 移动端（Android/iOS/HarmonyOS）  
> **审计时间**：2026-06-29  
> **对照标准**：AGENTS.md 附录 A 工程规范 + docs/04 前端架构 + docs/05 客户端架构

---

## 一、Web 前端架构审计

### 1.1 严重问题（P0 — 必须立即修复）

#### P0-1：双路由系统并存，架构分裂

**现状**：存在两套互斥的路由系统：

| 文件 | 路由方案 | 布局组件 | 状态 |
|:---|:---|:---|:---|
| [App.tsx](file:///Users/stephenhe/Development/workspace/quant_agent/frontend/src/App.tsx) | `BrowserRouter` + 9 条子路由 | `DashboardLayout`（已废弃） | **实际生效** |
| [router/index.tsx](file:///Users/stephenhe/Development/workspace/quant_agent/frontend/src/router/index.tsx) | `createBrowserRouter` + 模块切换 | `TradingDashboard`（规范要求） | **未使用** |

**影响**：AI 生成代码时随机选用两套布局，导致组件污染；`TradingDashboard` 的模块保活（Keep-Alive）能力完全失效——每次路由切换卸载组件，K 线缩放状态、策略代码编辑进度全部丢失。

**修复方案**：
1. 废弃 [App.tsx](file:///Users/stephenhe/Development/workspace/quant_agent/frontend/src/App.tsx) 中的 `BrowserRouter` 分页路由
2. 统一使用 [router/index.tsx](file:///Users/stephenhe/Development/workspace/quant_agent/frontend/src/router/index.tsx) 的 `TradingDashboard` 模块切换模式
3. 删除 [dashboard-layout.tsx](file:///Users/stephenhe/Development/workspace/quant_agent/frontend/src/components/layout/dashboard-layout.tsx)

#### P0-2：Axios 违规使用（3 处）

**现状**：AGENTS.md A.3.1 明确禁止 Axios（"使用原生 Fetch"），但以下文件仍在使用：

| 文件 | 用途 |
|:---|:---|
| [services/api-client.ts](file:///Users/stephenhe/Development/workspace/quant_agent/frontend/src/services/api-client.ts) | 备用 API 客户端（ Axios 实例） |
| [lib/apiClient.ts](file:///Users/stephenhe/Development/workspace/quant_agent/frontend/src/lib/apiClient.ts) | 主 API 客户端（ Axios 实例） |
| [hooks/use-api.ts](file:///Users/stephenhe/Development/workspace/quant_agent/frontend/src/hooks/use-api.ts) | Hook 内直接 import axios |

**影响**：增加了不必要的依赖体积（Axios ~34KB gzip），且与规范冲突。存在两份 API 客户端导致维护混乱。

**修复方案**：
1. 将 `lib/apiClient.ts` 和 `services/api-client.ts` 统一为一份基于原生 `fetch` 的实现
2. Token 拦截器改用 fetch wrapper 实现
3. 401 跳转逻辑移至统一响应处理中间件
4. 从 `package.json` 移除 `axios` 依赖

#### P0-3：ProtectedRoute 被注释禁用

**现状**：[App.tsx#L44-L48](file:///Users/stephenhe/Development/workspace/quant_agent/frontend/src/App.tsx#L44-L48) 中认证保护路由被注释掉，标注"临时：不使用认证保护"。

**影响**：所有页面在未登录状态下可直接访问，安全漏洞。

**修复方案**：修复 `ProtectedRoute` 的 children prop 类型错误后重新启用。

### 1.2 架构偏差（P1 — 本月修复）

#### P1-1：实际目录结构与文档规范不一致

| 文档规范（subsystems/frontend/architecture.md） | 实际代码 | 偏差 |
|:---|:---|:---|
| `stores/market.store.ts` | [marketStore.ts](file:///Users/stephenhe/Development/workspace/quant_agent/frontend/src/stores/marketStore.ts) | 命名不符（驼峰 vs 点分） |
| `features/market-center/` | `features/quotes/` + `features/data-center/` | 模块拆分方式不同 |
| `hooks/websocket/useQuoteStream` | [hooks/use-ws-manager.ts](file:///Users/stephenhe/Development/workspace/quant_agent/frontend/src/hooks/use-ws-manager.ts) | 扁平结构，无子目录 |
| `hooks/market-data/useTickBuffer` | [hooks/use-market-data.ts](file:///Users/stephenhe/Development/workspace/quant_agent/frontend/src/hooks/use-market-data.ts) | 扁平结构 |
| `components/charts/lightweight/` | [features/quotes/lightweight-chart-canvas.tsx](file:///Users/stephenhe/Development/workspace/quant_agent/frontend/src/features/quotes/lightweight-chart-canvas.tsx) | 图表组件散落在 features 内 |
| `constants/market.constants.ts` | 不存在 | 缺失 |
| `lib/logger.ts` + `lib/cn.ts` | 存在于 `lib/` 下 | ✅ 一致 |

**建议**：以实际代码为准更新文档，或按文档重构目录。考虑到重构成本，建议**更新文档对齐实际代码**。

#### P1-2：Recharts 用于低频图表（7 处）

**现状**：`recharts` 在 [package.json](file:///Users/stephenhe/Development/workspace/quant_agent/frontend/package.json) 中存在，被 7 个文件使用：

- [features/strategy/workspace/backtest-report.tsx](file:///Users/stephenhe/Development/workspace/quant_agent/frontend/src/features/strategy/workspace/backtest-report.tsx)
- [features/trading/backtest.tsx](file:///Users/stephenhe/Development/workspace/quant_agent/frontend/src/features/trading/backtest.tsx)
- [features/data-center/macro-risk-radar.tsx](file:///Users/stephenhe/Development/workspace/quant_agent/frontend/src/features/data-center/macro-risk-radar.tsx)
- [features/copilot/sentiment-trend.tsx](file:///Users/stephenhe/Development/workspace/quant_agent/frontend/src/features/copilot/sentiment-trend.tsx)
- [features/data-center/macro-chart.tsx](file:///Users/stephenhe/Development/workspace/quant_agent/frontend/src/features/data-center/macro-chart.tsx)
- [features/trading/risk.tsx](file:///Users/stephenhe/Development/workspace/quant_agent/frontend/src/features/trading/risk.tsx)
- [components/ui/chart.tsx](file:///Users/stephenhe/Development/workspace/quant_agent/frontend/src/components/ui/chart.tsx)

**判定**：AGENTS.md 禁止"任何 DOM/SVG 图表库处理**高频数据**"。这些文件处理的是低频图表（回测报告、宏观雷达、情绪趋势），**技术上不违规**。但 AGENTS.md A.3.1 的"禁止技术"列表中确实列出了 `recharts`。

**建议**：明确规范——低频图表（回测/归因/宏观）允许使用 Recharts，高频图表（K 线/Tick/盘口）严禁。或统一迁移至 ECharts 以消除歧义。

#### P1-3：行情 Hook 中 useState 管理准实时数据

**现状**：[use-market-data.ts](file:///Users/stephenhe/Development/workspace/quant_agent/frontend/src/hooks/use-market-data.ts) 使用 `useState` 管理 `realQuote` 和 `realHistory`：

```typescript
const [realQuote, setRealQuote] = useState<any>(null)     // 每次报价更新触发 re-render
const [realHistory, setRealHistory] = useState<any[]>([])  // K 线历史更新触发 re-render
```

**影响**：`realQuote` 如果是 Tick 级更新频率（每秒数十次），会触发频繁的 React re-render。`realHistory` 作为 K 线历史（低频更新）使用 useState 可接受。

**建议**：
- `realQuote`（实时报价）→ 改用 `useRef` + 直接 DOM 突变（遵循零 GC 原则）
- `realHistory`（K 线历史）→ 保持 `useState`（低频，可接受）
- 需要进一步检查 WebSocket 消息回调中是否直接 `setRealQuote`

### 1.3 良好实践（已正确实现）

| 项目 | 文件 | 评价 |
|:---|:---|:---|
| WebSocket 管理器 | [use-ws-manager.ts](file:///Users/stephenhe/Development/workspace/quant_agent/frontend/src/hooks/use-ws-manager.ts) | 指数退避重连、心跳检测、状态机完整 |
| Zustand 状态管理 | [marketStore.ts](file:///Users/stephenhe/Development/workspace/quant_agent/frontend/src/stores/marketStore.ts) | 正确使用 persist + devtools，仅存低频状态 |
| 懒加载模块 | [App.tsx](file:///Users/stephenhe/Development/workspace/quant_agent/frontend/src/App.tsx) | 所有 Feature 模块使用 `lazy()` + `Suspense` |
| Lightweight-Charts | [lightweight-chart-canvas.tsx](file:///Users/stephenhe/Development/workspace/quant_agent/frontend/src/features/quotes/lightweight-chart-canvas.tsx) | K 线主图正确使用 Canvas 引擎 |
| PixiJS WebGL 盘口 | [order-book-webgl.tsx](file:///Users/stephenhe/Development/workspace/quant_agent/frontend/src/features/quotes/order-book-webgl.tsx) | Level 2 盘口正确使用 WebGL |
| AG Grid 数据网格 | screener-results-table.tsx | 选股结果正确使用虚拟滚动 |
| Monaco Editor | [monaco-editor.tsx](file:///Users/stephenhe/Development/workspace/quant_agent/frontend/src/features/strategy/workspace/monaco-editor.tsx) | 策略 IDE 代码编辑器正确集成 |
| Protobuf 序列化 | `lib/proto/market.ts` | WebSocket 行情使用 Protobuf 解码 |

---

## 二、Flutter 移动端架构审计

### 2.1 现状

Flutter 客户端目前处于**纯设计文档阶段**，无实际代码。[docs/05](file:///Users/stephenhe/Development/workspace/quant_agent/docs/05.%20客户端架构与Tauri壳资源.md) 文档完整覆盖了三端架构（Android/iOS/HarmonyOS）、技术栈选型、视觉规范、推送体系和 APM 监控。

### 2.2 文档评估

| 维度 | 评分 | 说明 |
|:---|:---:|:---|
| 架构决策（ADR） | ⭐⭐⭐⭐⭐ | Flutter 统一三端的决策论证充分，对比表格清晰 |
| 技术栈完整性 | ⭐⭐⭐⭐⭐ | Riverpod/go_router/Isar/flutter_secure_storage 选型合理 |
| 视觉规范 | ⭐⭐⭐⭐ | 颜色 Token 与 Web 端对齐，但缺少暗色/亮色双主题切换方案 |
| 高频数据管道 | ⭐⭐⭐⭐ | StreamProvider + Isolate 卸载方案正确，但缺少背压（Backpressure）策略 |
| 推送体系 | ⭐⭐⭐⭐⭐ | 三端推送优先级分层清晰，HMS Push Kit 独立接入方案完备 |
| APM 监控 | ⭐⭐⭐⭐ | 指标采集完整，但缺少崩溃堆栈符号化方案 |
| 交互规范 | ⭐⭐⭐⭐ | WS 断连处理、生命周期感知、K 线手势规范完整 |
| CI/CD | ⭐⭐⭐ | 缺少 HarmonyOS CI 方案（文档承认需本地构建） |

### 2.3 建议补充

1. **背压策略**：当 WebSocket 消息速率超过 UI 渲染能力时，需明确丢弃策略（如只保留最新 Tick）或采样策略
2. **离线模式**：Isar 缓存命中时的降级展示规范（标注"离线数据" + 最后同步时间）
3. **热更新**：是否考虑 Shorebird 或 Code Push 方案修复紧急 Bug（不经过商店审核）
4. **包体积优化**：Flutter 三端打包后的 APK/IPA 体积控制策略（Tree-shaking icons、deferred components）

---

## 三、Web 与移动端架构一致性评估

### 3.1 数据流一致性

```
后端 Gateway（统一数据源）
  ├── WebSocket → Web 前端（use-ws-manager.ts）
  └── WebSocket → Flutter App（ws_client.dart）
```

两端均通过后端 Gateway 获取数据，未直连外部数据源，符合 AGENTS.md A.5.1 数据流边界规范。

### 3.2 视觉一致性

| 维度 | Web 前端 | Flutter | 一致性 |
|:---|:---|:---|:---:|
| 主背景色 | `bg-zinc-950` (#09090B) | `Color(0xFF09090B)` | ✅ |
| 上涨色 | `text-emerald-400` (#34D399) | `Color(0xFF34D399)` | ✅ |
| 下跌色 | `text-red-400` (#F87171) | `Color(0xFFF87171)` | ✅ |
| 等宽数字 | JetBrains Mono | JetBrains Mono | ✅ |
| STALE 遮罩 | amber-500 + opacity-60 | warnBg + AnimatedOpacity | ✅ |
| 模式横幅 | （未实现） | ModeBanner Widget | ⚠️ Web 端缺失 |

### 3.3 功能对等性

| 功能模块 | Web 前端 | Flutter | 差距 |
|:---|:---:|:---:|:---|
| 行情 K 线 | ✅ LW-Charts | 📋 CustomPainter | 方案不同但功能对等 |
| Level 2 盘口 | ✅ PixiJS | 📋 CustomPainter | 方案不同 |
| 选股器 | ✅ 完整 | 📋 计划中 | |
| 策略 IDE | ✅ Monaco | ❌ 不实现 | 移动端不做策略开发 |
| 回测报告 | ✅ 完整 | 📋 简化版 | |
| OMS 订单 | ✅ 完整 | 📋 计划中 | |
| AI 副驾 | ✅ SSE 流 | 📋 SSE 流 | 对等 |
| 告警中心 | ❌ 缺失 | ❌ 缺失 | 两端均缺失 |
| 宏观数据 | ✅ 完整 | 📋 简化版 | |

---

## 四、综合评估与优先级

### 4.1 评分总览

| 维度 | Web 前端 | Flutter 移动端 |
|:---|:---:|:---:|
| 架构规范性 | 70/100 | 90/100（文档） |
| 代码实现度 | 85/100 | 0/100（未开始） |
| 文档完整度 | 75/100 | 95/100 |
| 性能架构 | 80/100 | 85/100（设计） |
| 安全性 | 60/100 | 90/100（设计） |

### 4.2 修复优先级

| 优先级 | 任务 | 影响面 |
|:---:|:---|:---|
| P0 | 废弃 DashboardLayout，统一 TradingDashboard | 全局架构 |
| P0 | 移除 Axios，统一原生 Fetch | 数据层 |
| P0 | 启用 ProtectedRoute 认证保护 | 安全 |
| P1 | 更新目录结构文档对齐实际代码 | 文档 |
| P1 | realQuote 改用 useRef（零 GC） | 性能 |
| P1 | 明确 Recharts 使用边界 | 规范 |
| P2 | Web 端补全模式横幅（SANDBOX/LIVE） | 安全 UX |
| P2 | Flutter 启动 Phase 1 开发 | 移动端 |

---

## 五、变更日志

| 日期 | 版本 | 内容 |
|:---|:---|:---|
| 2026-06-29 | V1.0 | 初始客户端架构审计，覆盖 Web 前端 + Flutter 移动端 |
