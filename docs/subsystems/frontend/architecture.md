# 前端子系统架构文档

> 最后更新：2026-06-27 | 版本：V2.0

## 一、目录架构图

```
frontend/src/
├── main.tsx                  应用入口，挂载 React + Router + Providers
├── App.tsx                   根组件，全局布局骨架
├── router/
│   └── index.tsx             React Router v6 路由配置
│
├── pages/                    路由级容器（纯组合，无业务逻辑）
│   ├── market/               市场指挥中心
│   ├── screener/             智能选股器
│   ├── strategy-ide/         策略实验室
│   ├── backtest/             回测工坊
│   ├── oms/                  订单中心
│   ├── risk/                 风控面板
│   ├── macro-hub/            宏观数据中心
│   ├── alert-center/         告警中心（新增）
│   └── settings/             系统设置
│
├── features/                 业务功能模块（按金融业务域）
│   ├── market-center/        行情：K线/Tick/盘口
│   ├── screener/             选股器：NLP + 条件过滤 + 结果表格
│   ├── strategy-ide/         策略研发：Monaco + AI + 回测
│   ├── backtest-report/      回测报告：Tear Sheet + 蒙特卡洛
│   ├── oms-dashboard/        订单管理：持仓 + 挂单 + 算法委托
│   ├── portfolio-risk/       风控：因子暴露 + 归因 + 压测
│   ├── macro-hub/            宏观：六象限雷达 + 财经日历
│   └── hermes-copilot/       AI 副驾：SSE 流 + ECharts 渲染
│
├── components/
│   ├── ui/                   Atoms（shadcn/ui 扩展）
│   │   ├── financial/        金融原子：PriceTag ChangeBadge StaleBadge
│   │   └── data-display/     数据原子：Skeleton DataCard
│   ├── charts/               图表封装（按引擎分类）
│   │   ├── lightweight/      Lightweight-Charts 封装（K线主图）
│   │   ├── echarts/          ECharts 封装（归因/AI图）
│   │   └── pixi/             PixiJS WebGL（DOM 盘口）
│   ├── data-grids/           AG Grid 封装（选股/订单列表）
│   ├── layout/               AppShell SidePanel ResizableLayout
│   └── feedback/             ErrorBoundary Toast LoadingSpinner
│
├── hooks/
│   ├── websocket/            useQuoteStream useOmsStream
│   ├── market-data/          useTickBuffer useKlineHistory
│   ├── agent/                useHermesChat useSseStream
│   └── platform/             useKeyboardShortcut useTheme
│
├── stores/                   Zustand 切片
│   ├── market.store.ts       行情订阅状态（symbol 列表）
│   ├── oms.store.ts          订单状态机
│   ├── chat.store.ts         Agent 对话历史
│   ├── layout.store.ts       面板折叠/激活 Tab
│   └── settings.store.ts     用户配置（沙箱/实盘）
│
├── workers/                  Web Worker 脚本
│   ├── screener.worker.ts    选股过滤（10000+标的）
│   ├── indicators.worker.ts  技术指标计算
│   └── tick-aggregator.ts    Tick 聚合与降采样
│
├── services/                 REST API 调用（纯函数，非 Hook）
│   ├── market.api.ts
│   ├── screener.api.ts
│   └── agent.api.ts
│
├── types/                    TypeScript 类型定义
│   ├── market.types.ts       Tick OHLCV Quote
│   ├── order.types.ts        Order Fill Position
│   ├── agent.types.ts        Message ToolCall
│   └── api.types.ts          ApiResponse WsMessage
│
├── utils/
│   ├── financial/            formatPrice calcPnL formatVolume
│   ├── datetime/             formatTradingTime isMarketOpen
│   └── format/               truncate formatNumber
│
├── lib/
│   ├── logger.ts             统一前端日志接口
│   └── cn.ts                 Tailwind class 合并工具
│
└── constants/
    ├── market.constants.ts   市场代码 交易时段
    └── ws-events.constants.ts WebSocket 事件枚举
```

## 二、高频数据流（零 GC 路径）

```
WebSocket 帧到达
  ↓ useQuoteStream Hook（非 React state 路径）
  ↓ Float64Array 环形缓冲区（useRef）
  ↓ requestAnimationFrame 节流
  ↓ 图表实例 .update() 直调
Canvas/WebGL 重绘（绕过 React VDOM）
```

**严禁路径**（触发 React 重渲染的高频数据流）：
```
WebSocket 帧 → useState → React Diff → DOM Patch  ❌ 这会 GC 卡顿
```

## 三、渲染引擎选用决策表

| 数据特征 | 更新频率 | 数据量 | 选用引擎 | 理由 |
|:---|:---:|:---:|:---|:---|
| K 线主图 / 分时图 | 高（实时） | 1-10万点 | Lightweight-Charts | Canvas，60fps 专用 |
| Level 2 盘口 | 极高（每秒数十次） | 10-20档 | PixiJS v8 (WebGL) | GPU 批渲染 |
| 选股结果 / 订单列表 | 低（点击触发） | 1-5万行 | AG Grid | 虚拟滚动，O(1) DOM |
| AI 生成图 / 归因图 | 极低（按需） | 动态 | ECharts | LLM 输出准确率最高 |
| 数字跳动（价格） | 高 | 1个值 | useRef + DOM 直写 | 零 React 开销 |

## 四、性能基准（见 docs/09.）

| 指标 | 目标 | 当前状态 |
|:---|:---:|:---:|
| Tick → Canvas 延迟 | ≤ 16ms (60fps) | 待测 |
| AG Grid 5000行初始渲染 | ≤ 200ms | 待测 |
| JS Bundle 初始大小 | < 500KB gzip | 待测 |
| TTI (Time to Interactive) | ≤ 3s | 待测 |

## 五、测试覆盖情况

| 模块 | 目标覆盖率 | 测试工具 |
|:---|:---:|:---|
| hooks/ | 70% | Vitest + MSW |
| stores/ | 80% | Vitest |
| utils/ | 90% | Vitest |
| features/ (交互逻辑) | 60% | Vitest + RTL |

## 六、关键交互漏洞与修复优先级

> 详细规范见 `docs/04. 前端架构与零GC渲染.md` §四

| 优先级 | 问题 | 修复文件 |
|:---:|:---|:---|
| P0 | 废弃 `DashboardLayout`，统一使用 `TradingDashboard` | `App.tsx` / 路由配置 |
| P0 | WS 断连时无 STALE 遮罩，用户无感知 | `features/*/` 各模块根组件 |
| P0 | TickerTape 使用 REST 60s 轮询，改 WebSocket | `navbar.tsx` |
| P1 | 无全局底部状态栏（新建 `StatusBar`）| `components/layout/status-bar.tsx` |
| P1 | `Cmd+K` 快捷键未绑定 OmniSearch | `trading-dashboard.tsx` |
| P1 | 无三层 ErrorBoundary | `components/feedback/` |
| P2 | 无右键上下文菜单 | `components/ui/financial-context-menu.tsx` |
| P2 | AI 副驾应改为全局右侧抽屉 | `features/trading/copilot/` |
| P2 | 破坏性操作（全平仓）无二次确认 | `features/trading/oms/` |

## 七、变更记录

| 日期 | 变更 |
|:---|:---|
| 2026-06-27 V2.0 | 补充关键交互漏洞清单与修复优先级 |
| 2026-06-27 V1.0 | 初始版本，基于实际代码结构整理 |
