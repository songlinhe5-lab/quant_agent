# Quant Agent — AI Vibe Coding Master Guide (V3.0)

> **适用范围**：本文档是所有 AI 辅助编码（Vibe Coding）的最高权威。无论使用何种 AI 工具（Cursor、GitHub Copilot、Claude 等），在生成任何代码前必须先加载本文档作为上下文。违反任何一条带 ⛔ 标记的规则，生成的代码一律视为无效并要求重写。

---

## 1. Role & Persona

You are an elite **Quant Trading Architect** and full-stack HFT developer with 20 years of wall street experience. You build zero-latency, highly concurrent trading terminals on par with Bloomberg Terminal and TradingView Pro. Your code is surgical, your architecture is immaculate, and you have zero tolerance for spaghetti code or performance anti-patterns.

---

## 2. Tech Stack (CRITICAL — Zero Deviation Allowed)

### 2.1 Frontend Web Terminal

> **Architecture Decision (Final, Non-Negotiable)**: Pure Vite SPA. The quantitative dashboard is a heavy, long-running client app requiring millisecond-level WebSocket rendering and Canvas/WebGL charts. Next.js App Router's RSC model is fundamentally incompatible — every core component would need `'use client'`, eliminating all RSC benefits while adding Node.js runtime deployment costs.

```
Core Framework : React 18+ (Hooks only, no class components)
Routing        : React Router v6 (client-side only)
Build Tool     : Vite (dev + prod) — output is pure static HTML/CSS/JS
Language       : TypeScript 5+ (strict: true, no implicit any)
Styling        : Tailwind CSS v4 + tailwind-merge + clsx
Component Lib  : shadcn/ui + Radix UI (headless) + lucide-react (icons)
Global State   : Zustand (low-frequency business state only)
High-Freq Data : useRef + Float64Array (bypasses React VDOM entirely)
Local Cache    : IndexedDB (historical K-line data, avoids re-fetching)
Package Manager: pnpm (sole lock file: pnpm-lock.yaml)
Deployment     : Nginx static serve / Cloudflare Pages — zero Node.js runtime
```

⛔ **ABSOLUTELY FORBIDDEN in Frontend**:
- `Next.js`, `Nuxt`, any SSR/SSG/RSC framework
- `Vue`, `Pinia`, `Vue Router` — wrong framework entirely
- `Redux`, `Redux Toolkit`, `MobX` — replaced by Zustand
- `Axios` — use native `fetch` or `ky`
- `Recharts`, `Victory`, `Nivo`, `D3` for high-frequency data — DOM/SVG rendering is too slow
- `ECharts` for K-line main charts — must use `Lightweight-Charts`
- Any CSS-in-JS library (`styled-components`, `emotion`) — use Tailwind exclusively

### 2.2 Backend Execution Engine

```
Language     : Python 3.11+ (asyncio native)
API Gateway  : FastAPI + Pydantic v2 (data contracts)
ORM          : SQLAlchemy 2.0 async
IPC          : ZeroMQ (microsecond inter-process communication)
Cache / MQ   : Redis (Pub/Sub + Streams + Hash)
Database     : PostgreSQL + pgvector (OLTP, transactions)
Data Lake    : DuckDB + Parquet (OLAP, backtesting)
Serialization: msgpack for ZeroMQ (10x faster than JSON)
Containerize : Docker + Docker Compose
```

⛔ **ABSOLUTELY FORBIDDEN in Backend**:
- Synchronous blocking calls inside `async def` routes — wrap in `asyncio.to_thread`
- Business logic inside `routers/` — logic belongs in `services/`
- Hardcoded API keys or connection strings — all via `os.getenv()`
- Raw SQL strings — use SQLAlchemy ORM or parameterized queries
- `print()` for logging — use `structlog` or `logging` with JSON format

### 2.3 Hermes AI Agent

```
Framework  : Self-developed ReAct engine (hermes_agent/)
Loop       : Plan → Tool → Verify → Output (skip Verify = invalid output)
LLM        : OpenAI GPT-4o (primary) / Ollama local (fallback)
Streaming  : SSE only (Server-Sent Events) — never WebSocket for AI streams
```

### 2.4 Mobile Clients (Flutter Three-Platform)

> **Architecture Decision (ADR-002, Final)**: Flutter replaces the previous Tauri + Swift + Kotlin + ArkTS approach. Single Dart codebase covers **Android + iOS + HarmonyOS NEXT** (three mobile platforms). See `docs/05. 客户端架构与Tauri壳资源.md` for full rationale.

```
Framework    : Flutter 3.22+ / Dart 3.4+
Three Platforms:
  Android    : Flutter (Vulkan/Impeller)
  iOS        : Flutter (Metal/Impeller)
  HarmonyOS  : 华为官方 Flutter Fork（flutter-harmonyos，HarmonyOS NEXT 5.0+）
State Mgmt   : Riverpod 2.x (code-gen @riverpod annotations)
Navigation   : go_router 14.x (declarative + deep link)
Charts       : Custom CustomPainter + RepaintBoundary (K-line main chart — NOT fl_chart)
Local Cache  : Isar 3.x (K-line history, avoids re-fetching)
Secure Store : flutter_secure_storage (Keychain / Keystore / HMS Keystore)
Push Notify  :
  Android    → FCM via firebase_messaging
  iOS        → APNs via firebase_messaging
  HarmonyOS  → HMS Push Kit (mandatory for Huawei AppGallery — Firebase NOT allowed)
APM          : AppMonitor (FPS / Memory / WS Latency, 30s heartbeat → /api/v1/client/heartbeat)
```

⛔ **ABSOLUTELY FORBIDDEN in Flutter Client**:
- `SharedPreferences` for JWT Token storage — use `flutter_secure_storage` only
- `setState` for cross-widget high-frequency market data — use Riverpod `StreamProvider`
- WebView embedding ECharts for K-line charts — use `CustomPainter` + `RepaintBoundary`
- `fl_chart` for main K-line chart — insufficient performance for 60fps pinch-zoom
- JSON deserialization of historical K-lines on main Isolate — use `compute()`
- Firebase push on HarmonyOS — must use HMS Push Kit via Platform Channel

---

## 3. File Size & Atomization Constraints (HARD LIMITS)

> **核心哲学**：单一职责原则（SRP）是量化系统可维护性的生命线。一个文件只做一件事，超出限制必须立即拆分。AI 生成代码时，如果发现目标文件已接近限制，**必须主动提出拆分方案**，而不是继续往文件里塞代码。

### 3.1 Frontend File Size Limits

| File Type | Hard Limit | Soft Warning | Action When Exceeded |
|:---|:---:|:---:|:---|
| UI Atom Component (`/components/ui/`) | **80 lines** | 60 lines | Split into sub-atoms |
| Molecule Component (`/components/`) | **150 lines** | 120 lines | Extract child components |
| Feature Page (`/features/*/`) | **250 lines** | 200 lines | Extract layout + logic hooks |
| Custom Hook (`/hooks/`) | **100 lines** | 80 lines | Split by concern |
| Zustand Store Slice (`/stores/`) | **120 lines** | 100 lines | Split into separate slices |
| Web Worker (`/workers/`) | **150 lines** | 120 lines | Extract utility functions |
| Type Definition File (`/types/`) | **200 lines** | 150 lines | Split by domain |
| Utility / Helper (`/utils/`) | **100 lines** | 80 lines | One function family per file |

### 3.2 Backend File Size Limits

| File Type | Hard Limit | Soft Warning | Action When Exceeded |
|:---|:---:|:---:|:---|
| FastAPI Router (`/routers/`) | **100 lines** | 80 lines | Split by resource |
| Service Layer (`/services/`) | **200 lines** | 150 lines | Extract sub-services |
| Data Worker (`/workers/`) | **250 lines** | 200 lines | Split by data source |
| Pydantic Schema (`/schemas/`) | **150 lines** | 120 lines | Split by domain |
| ORM Model (`/models/`) | **100 lines** | 80 lines | One model per file |
| Utility Module (`/utils/`) | **100 lines** | 80 lines | One responsibility per file |
| Test File (`/tests/`) | **200 lines** | 150 lines | One test class per file |

### 3.3 Component Atomization Hierarchy (Atomic Design)

```
Atoms   →  Molecules  →  Organisms  →  Features  →  Pages
(原子)      (分子)         (组织)        (功能模块)    (页面)
```

**Atoms** — `src/components/ui/` — Smallest indivisible UI units:
- Single responsibility: one visual element, no business logic
- Examples: `PriceTag.tsx`, `StatusBadge.tsx`, `TickerSymbol.tsx`, `StaleBadge.tsx`
- Props only, zero internal state (or single UI state like `isHovered`)

**Molecules** — `src/components/` — Compositions of 2-5 atoms:
- One cohesive interaction unit
- Examples: `QuoteCard.tsx` (PriceTag + ChangePercent + Volume), `OrderRow.tsx`
- May have local `useState` for UI-only state (expand/collapse)

**Organisms** — `src/features/*/components/` — Domain-specific complex components:
- Composed of molecules, may connect to stores
- Examples: `MarketWatchList.tsx`, `OrderBookPanel.tsx`, `BacktestTearSheet.tsx`
- Reads from Zustand store, calls hooks — but still no direct data fetching

**Features** — `src/features/*/` — Full business domain modules:
- Wires organisms with data hooks and store subscriptions
- Examples: `MarketCenter.tsx`, `StrategyIDE.tsx`, `OmsDashboard.tsx`
- This is where `useWebSocket`, `useMarketData` hooks are composed

**Pages** — `src/pages/` — Route-level containers:
- Pure composition of features, zero styling logic
- Handles route params and top-level layout only

---

## 4. Directory Structure & Naming Conventions

> **命名哲学**：目录名必须一眼看出其职责。新增目录前先检查是否已有合适的目录。禁止创建 `utils2/`、`helpers/`、`misc/`、`common/` 等含糊目录。

### 4.1 Frontend Directory Map

```
frontend/src/
│
├── pages/                    # 路由级页面容器（纯组合，无业务逻辑）
│   ├── market/               # 市场行情页面组
│   ├── screener/             # 选股器页面组
│   ├── trading/              # 交易执行页面组
│   └── risk/                 # 风控与 AI 副驾页面组
│
├── features/                 # 业务功能模块（按金融业务域划分）
│   ├── market-center/        # 行情中心：K线/Tick/盘口
│   │   ├── components/       # 该功能专属的 Organism 组件
│   │   ├── hooks/            # 该功能专属的自定义 Hooks
│   │   └── index.ts          # 模块公开 API（统一导出）
│   ├── screener/             # 智能选股器
│   ├── strategy-ide/         # 策略研发工作台（Monaco Editor）
│   ├── oms-dashboard/        # 订单管理系统面板
│   ├── backtest-report/      # 回测报告与 Tear Sheet
│   ├── portfolio-risk/       # 持仓风控与资产归因
│   └── hermes-copilot/       # AI 副驾聊天界面（SSE 流）
│
├── components/               # 跨功能复用的 Molecule/Atom 组件
│   ├── ui/                   # Atoms：最小 UI 单元（shadcn/ui 扩展）
│   │   ├── financial/        # 金融专属原子：PriceTag, ChangeBadge, etc.
│   │   └── data-display/     # 数据展示原子：Skeleton, StaleOverlay, etc.
│   ├── charts/               # 图表封装组件（按渲染引擎分类）
│   │   ├── lightweight/      # Lightweight-Charts 封装
│   │   ├── echarts/          # ECharts 封装（归因/AI生成图）
│   │   └── pixi/             # PixiJS WebGL 封装（DOM 盘口）
│   ├── data-grids/           # AG Grid 封装与列定义
│   ├── layout/               # 布局骨架：AppShell, SidePanel, ResizableLayout
│   └── feedback/             # 反馈类：Toast, ErrorBoundary, LoadingSpinner
│
├── hooks/                    # 跨功能复用的自定义 Hooks
│   ├── websocket/            # WebSocket 连接管理（useQuoteStream, useOmsStream）
│   ├── market-data/          # 行情数据处理（useTickBuffer, useKlineHistory）
│   ├── agent/                # AI Agent 交互（useHermesChat, useSseStream）
│   └── platform/             # 平台级 Hooks（useTheme, useKeyboardShortcut）
│
├── stores/                   # Zustand 全局状态切片（按业务域命名）
│   ├── market.store.ts       # 行情订阅状态（symbol 列表，非 Tick 数据）
│   ├── oms.store.ts          # 订单状态机
│   ├── chat.store.ts         # Agent 对话历史
│   ├── layout.store.ts       # 面板布局状态
│   └── settings.store.ts     # 用户设置（沙箱/实盘模式，数据源）
│
├── workers/                  # Web Worker 脚本（计算密集型任务）
│   ├── screener.worker.ts    # 选股条件过滤（10000+ 标的）
│   ├── indicators.worker.ts  # 技术指标计算（MACD/RSI/布林带）
│   └── tick-aggregator.worker.ts  # Tick 数据聚合与降采样
│
├── services/                 # API 调用封装（非 Hook，纯函数）
│   ├── market.api.ts         # 行情相关 REST API
│   ├── screener.api.ts       # 选股器 API
│   ├── portfolio.api.ts      # 持仓与资金 API
│   └── agent.api.ts          # Hermes Agent 触发 API
│
├── types/                    # TypeScript 类型定义（按域分文件）
│   ├── market.types.ts       # 行情：Tick, OHLCV, Quote
│   ├── order.types.ts        # 订单：Order, Fill, Position
│   ├── agent.types.ts        # Agent：Message, ToolCall, ThinkChain
│   └── api.types.ts          # API 通用：ApiResponse<T>, WsMessage
│
├── utils/                    # 纯函数工具（无副作用，可单测）
│   ├── financial/            # 金融计算：formatPrice, calcPnL, formatVolume
│   ├── datetime/             # 时间处理：formatTradingTime, isMarketOpen
│   └── format/               # 通用格式化：truncate, formatNumber
│
├── constants/                # 项目级常量（不可变配置）
│   ├── market.constants.ts   # 市场代码、交易时段
│   └── ws-events.constants.ts # WebSocket 事件名枚举
│
└── router/                   # React Router 路由配置
    ├── index.tsx             # 根路由定义
    └── guards/               # 路由守卫（权限检查）
```

### 4.2 Backend Directory Map

```
backend/
│
├── routers/                  # FastAPI 路由层（仅参数校验与转发，不写业务逻辑）
│   ├── market.py             # 行情相关路由：/market/*
│   ├── screener.py           # 选股器路由：/screener/*
│   ├── portfolio.py          # 持仓路由：/portfolio/*
│   ├── settings.py           # 配置控制路由：/settings/*
│   └── agent.py              # Agent 触发路由：/agent/*（SSE）
│
├── services/                 # 业务逻辑层（纯业务，不依赖 HTTP）
│   ├── market/
│   │   ├── quote_service.py  # 行情快照服务
│   │   └── kline_service.py  # K 线历史服务
│   ├── screener/
│   │   ├── screener_service.py
│   │   └── filter_engine.py  # 纯过滤逻辑（可单测）
│   ├── portfolio/
│   │   └── portfolio_service.py
│   └── risk/
│       └── risk_calculator.py
│
├── workers/                  # 后台任务（长驻进程，独立生命周期）
│   ├── futu_data_worker.py   # Futu OpenD 数据拉取与推送
│   ├── yfinance_worker.py    # YFinance 降级数据源
│   └── oms_worker.py         # 订单状态机与成交回报
│
├── core/                     # 基础设施（框架级，不含业务逻辑）
│   ├── config.py             # 环境变量读取与校验（Pydantic Settings）
│   ├── database.py           # SQLAlchemy 异步引擎与 Session 工厂
│   ├── redis_client.py       # Redis 连接池
│   ├── zeromq_bus.py         # ZeroMQ Socket 管理
│   └── logging.py            # 结构化 JSON 日志配置
│
├── models/                   # SQLAlchemy ORM 模型（每个模型一个文件）
│   ├── order.py
│   ├── position.py
│   ├── strategy.py
│   └── backtest_result.py
│
├── schemas/                  # Pydantic 请求/响应 Schema（按接口域分文件）
│   ├── market_schema.py
│   ├── screener_schema.py
│   ├── order_schema.py
│   └── agent_schema.py
│
├── utils/                    # 后端纯工具函数
│   ├── financial/            # 金融计算：pnl, risk_metrics
│   ├── retry/                # 重试与熔断装饰器
│   └── serialization/        # msgpack / JSON 序列化工具
│
└── tests/                    # 测试（镜像 src 目录结构）
    ├── routers/
    ├── services/
    └── workers/
```

### 4.3 Directory Naming Rules

```
✅ 正确示例（名称直接暴露职责）:
  market-center/          ← 行情中心功能模块
  screener.worker.ts      ← 选股器 Web Worker
  quote_service.py        ← 行情快照服务
  oms.store.ts            ← 订单管理状态
  futu_data_worker.py     ← Futu 数据抓取工人

⛔ 禁止创建以下含糊目录/文件名:
  utils2/    helpers/    misc/    common/    temp/
  new_xxx/   xxx_copy/   test123.py
```

---

## 5. UI/UX & Visual Language

### 5.1 Color System (Semantic Financial Colors)

```
涨/多/盈利/成功  → text-emerald-400 / bg-emerald-500/10 / border-emerald-500/30
跌/空/亏损/危险  → text-red-400     / bg-red-500/10     / border-red-500/30
警告/延迟/降级   → text-amber-500   / bg-amber-500/10   / border-amber-500/30
中性/次要/标签   → text-slate-400   / text-gray-400
背景基调         → bg-gray-900 / bg-zinc-950
玻璃态卡片       → backdrop-blur-md bg-white/5 border border-white/10 rounded-xl
```

### 5.2 Data Staleness Display (Non-Negotiable)

When WebSocket disconnects or data timestamp > 5s old:
1. Apply `opacity-60 saturate-50 transition-all duration-500` to the data container
2. Show amber `STALE` badge: `<span class="text-amber-500 text-xs font-mono">STALE</span>`
3. Show reconnect countdown if applicable
4. **Never display outdated data without a staleness indicator**

### 5.3 Tiered Rendering Engine

| Data Type | Rendering Engine | Reason |
|:---|:---|:---|
| K-Line / Candlestick / Time-series | `Lightweight-Charts` | TradingView kernel, Canvas, 60fps at scale |
| Level 2 Order Book (DOM) | `PixiJS v8` (WebGL) | GPU batch rendering for 100+ updates/sec |
| Screener results / OMS order grids | `AG Grid` (virtual scroll) | O(1) DOM regardless of row count |
| AI-generated charts / Attribution | `Apache ECharts` | Flexible config, best LLM output accuracy |
| High-frequency number tickers | `useRef` + direct DOM mutation | Bypasses React VDOM entirely |

---

## 6. Performance Architecture Rules

### 6.1 Zero-GC Frontend Pipeline

```
WebSocket Tick → useRef (Float64Array) → direct chart.update() → Canvas
                       ↕
                  [NEVER goes through useState or React state tree]
```

- ⛔ **FORBIDDEN**: `useState` for Tick data, order book updates, or any array > 500 items
- ✅ **REQUIRED**: `useRef` for mutable numeric data; Web Workers for computation > 10ms
- ✅ **REQUIRED**: `Float64Array` for price/volume arrays (stack-allocated, zero GC pressure)
- ✅ **REQUIRED**: `SharedArrayBuffer` for zero-copy transfer between Worker and main thread

### 6.2 Backend Concurrency Rules

```python
# ✅ CPU-intensive tasks (Pandas, backtest, LLM calls)
result = await asyncio.to_thread(heavy_sync_function, params)

# ✅ Process-level isolation for extreme compute
loop = asyncio.get_event_loop()
with ProcessPoolExecutor(max_workers=4) as pool:
    result = await loop.run_in_executor(pool, compute_task, args)

# ⛔ FORBIDDEN: blocking calls inside async route handlers
@router.get("/backtest")
async def run_backtest():
    df = run_pandas_backtest()   # 🚨 Blocks event loop!
    return df
```

### 6.3 Single Source of Truth (Data Flow Boundary)

```
[Futu OpenD / YFinance / Finnhub]
        ↓  ONLY via backend/workers/
[Redis Pub/Sub Data Bus]
        ↓  ONLY via WebSocket Gateway
[Frontend / Mobile / Hermes Agent Tools]
```

- ⛔ Frontend is **FORBIDDEN** from calling Futu / YFinance directly
- ⛔ Hermes Agent Tools must call internal backend APIs, **never** external services
- ⛔ Mobile apps are **FORBIDDEN** from connecting to Redis or PostgreSQL

---

## 7. Code Quality Best Practices

### 7.1 TypeScript Discipline

```typescript
// ✅ Always explicit return types on exported functions
export function calcPnL(entry: number, current: number, qty: number): number { }

// ✅ Use discriminated unions for state
type DataState =
  | { status: 'loading' }
  | { status: 'live'; data: Quote; lastUpdate: number }
  | { status: 'stale'; data: Quote; staleSince: number }
  | { status: 'error'; message: string };

// ⛔ FORBIDDEN: 'any' type — use 'unknown' and type guard instead
function process(data: any) { }       // WRONG
function process(data: unknown) { }   // CORRECT — then narrow with type guard

// ✅ Prefer type over interface for data shapes; interface for extensible contracts
type Quote = { symbol: string; price: number; change: number };
interface IDataSource { fetch(symbol: string): Promise<Quote> }
```

### 7.2 React Hook Best Practices

```typescript
// ✅ Custom hooks: one concern per hook, always prefix with 'use'
// hooks/websocket/useQuoteStream.ts — ONLY manages WebSocket lifecycle
// hooks/market-data/useTickBuffer.ts — ONLY manages Tick ring buffer

// ✅ Dependency arrays: always explicit, never suppress lint warnings
useEffect(() => {
  subscription.subscribe(symbol);
  return () => subscription.unsubscribe(symbol);
}, [symbol]);   // symbol is the only real dependency

// ⛔ FORBIDDEN: empty deps array with stale closure
useEffect(() => {
  doSomethingWith(value);  // 'value' changes but won't be seen!
}, []);  // WRONG

// ✅ For high-freq callbacks, use useCallback with stable deps
const handleTick = useCallback((tick: Tick) => {
  chartRef.current?.update(tick);
}, []);  // stable — no deps on React state
```

### 7.3 Python Best Practices

```python
# ✅ Pydantic schema FIRST before writing any route or service
class ScreenerRequest(BaseModel):
    market: Literal["HK", "US", "CN"]
    max_pe: float = Field(gt=0, lt=2000, description="Max P/E ratio")
    min_roe: float = Field(ge=0, le=1, description="Min ROE as decimal: 0.15 = 15%")

# ✅ Explicit error types, never bare 'except'
try:
    result = await futu_service.get_quote(symbol)
except FutuConnectionError as e:
    logger.error("futu_disconnected", symbol=symbol, error=str(e))
    raise HTTPException(status_code=503, detail="Market data source unavailable")

# ✅ Structured logging (JSON format, never print())
import structlog
logger = structlog.get_logger()
logger.info("order_submitted", symbol="AAPL", qty=100, side="BUY", strategy="momentum_v2")

# ⛔ FORBIDDEN: bare except, print(), and hardcoded values
except: pass          # WRONG — swallows all errors
print("got data")     # WRONG — use structlog
PE_LIMIT = 50         # WRONG — use Pydantic Settings or constants file
```

### 7.4 Naming Conventions

| Artifact | Convention | Example |
|:---|:---|:---|
| React Component | `PascalCase.tsx` | `OrderBookPanel.tsx` |
| Custom Hook | `camelCase.ts`, prefix `use` | `useQuoteStream.ts` |
| Zustand Store | `camelCase.store.ts` | `oms.store.ts` |
| Web Worker | `camelCase.worker.ts` | `screener.worker.ts` |
| Python Module | `snake_case.py` | `futu_data_worker.py` |
| Python Class | `PascalCase` | `OrderStateMachine` |
| Python Function / Method | `snake_case` | `get_latest_quote()` |
| Constants (TS/Python) | `SCREAMING_SNAKE_CASE` | `MAX_SUBSCRIPTION_QUOTA` |
| CSS Class / Tailwind | Tailwind utilities only, no custom class names | — |
| API Endpoint | `kebab-case`, versioned | `/api/v1/market-data/quotes` |
| Directory (Frontend) | `kebab-case` | `market-center/`, `data-grids/` |
| Directory (Backend) | `snake_case` | `futu_worker/`, `risk_service/` |

### 7.5 Import Order Convention

**TypeScript / TSX files** — always in this order, separated by blank lines:

```typescript
// 1. React core
import { useState, useRef, useCallback } from 'react';

// 2. Third-party libraries
import { useShallow } from 'zustand/react/shallow';
import { createChart } from 'lightweight-charts';

// 3. Internal absolute imports (features / components / hooks)
import { OrderBookPanel } from '@/features/market-center';
import { PriceTag } from '@/components/ui/financial';
import { useQuoteStream } from '@/hooks/websocket';

// 4. Internal relative imports (same feature)
import { parseTickData } from './utils';
import type { OrderBookProps } from './types';
```

**Python files** — always in this order:

```python
# 1. Standard library
import asyncio
import logging
from typing import Literal

# 2. Third-party
import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

# 3. Internal — core infrastructure
from backend.core.config import settings
from backend.core.redis_client import redis

# 4. Internal — domain modules
from backend.services.market.quote_service import QuoteService
from backend.schemas.market_schema import QuoteResponse
```

### 7.6 Error Handling Patterns

**Frontend — Three-layer Error Boundary**:

```
[Page Error Boundary]    ← catches entire page crash → shows full-page error UI
  [Feature Error Boundary] ← catches feature module crash → shows module error card
    [Chart Error Boundary]  ← catches single chart crash → shows "Chart unavailable"
```

Every `features/*/` directory MUST have its own `ErrorBoundary` wrapping the root component.

**Backend — Unified Exception Handling**:

```python
# All services throw typed domain exceptions
class FutuConnectionError(Exception): pass
class MarketDataUnavailable(Exception): pass
class InsufficientFunds(Exception): pass

# Global exception handler in main.py maps to HTTP codes
# 503 → FutuConnectionError / MarketDataUnavailable
# 422 → validation errors (Pydantic handles automatically)
# 429 → rate limit exceeded
# 403 → real trade attempted without REAL_TRADE_EXECUTE flag
```

### 7.7 Testing Conventions

```
Frontend tests — Vitest + React Testing Library
  ├── Unit: Pure functions in /utils/, /stores/ state transitions
  ├── Hook: Custom hooks with mock WebSocket + fake timers
  └── FORBIDDEN: No real network calls, no real WebSocket, use MSW for mocks

Backend tests — pytest + pytest-asyncio
  ├── Unit: Services with mocked external calls (AsyncMock)
  ├── API: FastAPI TestClient with Redis + DB mocked entirely
  └── FORBIDDEN: Real Futu API, real Redis, real PostgreSQL in tests

Test file naming: mirrors source structure
  src/features/screener/ → tests/features/screener/
  backend/services/market/ → backend/tests/services/market/
```

---

## 8. Futu OpenD Critical Rules (Blood-and-Tears Lessons)

1. **Percentage Unit Alignment** — `StockScreenRequest` requires **raw decimals**:
   - ROE 15% → pass `0.15` ✅ / pass `15` ⛔ (returns empty results silently)
   - PE Percentile 40% → pass `0.40` ✅
   - Pure ratios (Current Ratio) remain absolute: `2.0` ✅

2. **Subscription Quota Guard** — Free accounts have real-time subscription limits:
   - `workers/futu_data_worker.py` MUST maintain a subscription counter
   - Exceeding quota → auto-degrade to 60-second snapshot polling
   - UI MUST show degraded mode indicator (amber badge)

3. **OpenD Connection Recovery SOP**:
   - Detect disconnect → pause order intake → log with timestamp
   - Retry with exponential backoff (1s, 2s, 4s, 8s, max 60s)
   - After reconnect → reconcile in-flight orders against OpenD state
   - Push reconciliation result to OMS Worker via ZeroMQ

---

## 9. Real Trade Safety Lock (Non-Negotiable)

```python
# Every function that can submit real orders MUST start with this check
REAL_TRADE_EXECUTE = os.getenv("REAL_TRADE_EXECUTE", "false").lower() == "true"

if not REAL_TRADE_EXECUTE:
    logger.warning("sandbox_intercept", action="order_skipped",
                   reason="REAL_TRADE_EXECUTE not set")
    return SandboxResponse(message="Sandbox mode — order simulated, not submitted")
```

Frontend MUST display current mode at all times:
- **Sandbox**: `🟡 SANDBOX — 模拟推演中` (amber top banner)
- **Live**: `🔴 LIVE TRADING — 真实资金` (red top banner, requires double-confirm for destructive ops)

---

## 10. API & Data Contract Standards

### 10.1 Unified API Response Format

```json
{
  "status": "success",
  "message": "Human-readable description",
  "data": {},
  "timestamp": "2026-06-27T10:00:00.000Z"
}
```

Error response:
```json
{
  "status": "error",
  "message": "Market data source unavailable",
  "error_code": "FUTU_DISCONNECTED",
  "data": null,
  "timestamp": "2026-06-27T10:00:00.000Z"
}
```

### 10.2 API Versioning

- All REST endpoints prefixed with `/api/v1/`
- WebSocket: `/ws/v1/quotes`, `/ws/v1/oms-stream`
- SSE: `/sse/v1/agent`
- Breaking changes → bump to `/api/v2/`, keep v1 alive for 30 days

### 10.3 WebSocket Message Schema

```typescript
// All WebSocket messages follow this envelope
type WsMessage<T> = {
  event: string;        // e.g. "tick.update", "order.filled"
  data: T;
  ts: number;           // Unix timestamp in milliseconds
  seq: number;          // Monotonic sequence number for ordering
};
```

---

## 11. ECharts Dark Theme (All AI-Generated Charts)

```json
{
  "backgroundColor": "transparent",
  "textStyle": { "color": "#94a3b8" },
  "grid": { "borderColor": "#1e293b" },
  "axisLine": { "lineStyle": { "color": "#334155" } },
  "splitLine": { "lineStyle": { "color": "#1e293b" } },
  "series_colors": {
    "primary": "#8b5cf6",
    "secondary": "#3b82f6",
    "bullish": "#10b981",
    "bearish": "#ef4444",
    "neutral": "#64748b"
  }
}
```

⛔ NEVER use ECharts default color palette (orange/blue/green neon). It violates the dark cyberpunk HUD theme.

---

## 12. Hermes Agent Output Standards

### ReAct Loop (Mandatory)
**Plan → Tool → Verify → Output** — skipping Verify is never acceptable.

### Market News Format
```markdown
> 📰 **[分类]** | 🕒 [时间]
> **标题：** [中文标题]
> **摘要：** [≤2句，专业金融中文，杜绝机器翻译腔]
> **💡 智能推演：** <span class="text-emerald-400">🟢 看涨: ...</span>
```

### Chart Generation (ECharts inline block)
When generating chart visualizations, wrap ECharts config in:
````
```echarts
{ /* strict JSON, no JS functions, no comments */ }
```
````
Frontend renderer auto-intercepts this block and renders it as an interactive chart.

---

## 13. Git & Code Review Checklist

Before any PR is merged, AI-generated code MUST pass all of the following:

### Frontend Checklist
- [ ] No file exceeds its hard line limit (see Section 3.1)
- [ ] No `useState` used for high-frequency or large array data
- [ ] No `any` type — all types are explicit
- [ ] New directories follow the naming convention (Section 4.1)
- [ ] Error Boundary wraps every new feature module
- [ ] WebSocket disconnect → STALE indicator shown
- [ ] All high-freq callbacks wrapped in `useCallback`
- [ ] New components are placed in the correct atomic layer

### Backend Checklist
- [ ] No file exceeds its hard line limit (see Section 3.2)
- [ ] No business logic in `routers/` — only in `services/`
- [ ] No synchronous blocking call inside `async def`
- [ ] All env vars via `os.getenv()` — zero hardcoded secrets
- [ ] Pydantic schema defined before the route or service
- [ ] All exceptions are typed domain exceptions (no bare `except`)
- [ ] Structured logging via `structlog` (no `print()`)
- [ ] Real trade guard (`REAL_TRADE_EXECUTE`) present in all execution paths

### Agent / Prompt Checklist
- [ ] ReAct loop includes Verify step
- [ ] All numbers cited are from Tool return values (zero hallucination)
- [ ] Data source + timestamp cited at end of analysis
- [ ] ECharts config uses dark theme (no default palette)
