# Quant Agent - 前端架构 (React 18 + Vite SPA)

本项目前端采用 **React 18** + **Vite 5** 构建纯 SPA（单页应用），专为高频量化交易看板与大模型交互设计，强调"极速渲染、防抖节流、暗色高对比度"。

## 🚀 核心技术栈

- **核心框架**: React 18 (`useEffect` + `useRef` + `memo`) + Vite 5
- **路由系统**: React Router v6（模块切换模式，非页面路由）
- **样式系统**: Tailwind CSS + 暗色主题（Glass Panel 玻璃态 UI）
- **数据可视化**: ECharts 5（严格遵守暗色与 Tailwind 颜色体系的 JSON 规范）
- **状态管理**: React Context + Zustand（按需选用）
- **数据请求**: Axios + WebSocket 客户端（三通道封装）

## 🏗️ 架构原则（ADR-001）

1. **TradingDashboard Keep-Alive 模式**
   - 所有功能模块作为 `TradingDashboard` 的子组件，通过 state 切换
   - 禁止使用 React Router 页面路由导致组件卸载，防止行情订阅因页面切换断开
   - 参考：`docs/04. 前端架构与零GC渲染.md` §二

2. **零GC 高频渲染**
   - 行情高频 Tick 数据必须走 `Float64Array` + `useRef`，严禁触发 React state 重渲染
   - Web Worker 下放 MACD/RSI/布林带等重度计算，防止阻塞主线程
   - 参考：`docs/04. 前端架构与零GC渲染.md` §三

3. **三级 Error Boundary**
   - Module 级 / Panel 级 / Chart 级，分别隔离崩溃影响范围
   - 参考：`docs/04. 前端架构与零GC渲染.md` §四

4. **UI 视觉规范**
   - 全局强制遵循暗黑金融质感风格（底色 `#050505` 或冷灰 `#0f172a`）
   - 数据上涨/看多必须使用绿 (`#10b981`)，下跌/看空必须使用红 (`#ef4444`)
   - 中国市场红涨绿跌 / 欧美市场绿涨红跌，根据 `marketRegion` 动态切换
   - 所有金融数字使用等宽字体（`font-variant-numeric: tabular-nums`）

## 📁 目录结构

```
frontend/src/
├── components/        # 通用组件（Button, Dialog, Toast, etc.）
├── features/          # 功能模块（按业务领域组织）
│   ├── auth/         # 登录认证
│   ├── trading/      # 交易相关（quotes, screener, strategy, etc.）
│   ├── settings/     # 设置页面
│   └── ...
├── router/           # React Router 配置
├── services/         # API 客户端（REST / WS / SSE 三通道）
├── stores/           # Zustand 状态管理（按需）
├── styles/           # 全局样式（Tailwind + CSS 变量）
├── types/            # TypeScript 类型定义
├── hooks/            # 自定义 React Hooks
├── workers/          # Web Worker 脚本
├── App.tsx           # 应用根组件（路由配置）
└── main.tsx          # Vite 入口文件
```

## 🛠️ 快速开始

```bash
# 安装依赖（使用 pnpm）
pnpm install

# 启动开发服务器 (HMR)
pnpm dev

# 生产环境构建
pnpm build

# 预览生产构建
pnpm preview
```

## 🔧 开发规范

1. **组件原子化**：严格按照 `docs/02. Vibe Coding 工程规范.md` 执行
2. **单文件行数约束**：≤ 150 行，超出必须拆分
3. **TypeScript 严格模式**：禁止 `any` 类型，必须与 `docs/11. 领域对象与TS类型契约.md` 对齐
4. **路径别名**：统一使用 `@/` 开头（配置在 `vite.config.ts` 和 `tsconfig.json`）

## 📝 参考文档

- `docs/04. 前端架构与零GC渲染.md` - 前端架构详细设计
- `docs/02. Vibe Coding 工程规范.md` - 开发规范与约束
- `docs/11. 领域对象与TS类型契约.md` - TypeScript 类型契约
- `AI_INSTRUCTIONS.md` - AI 辅助开发指令
