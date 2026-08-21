---
kind: frontend_style
name: Quant Agent 前端视觉风格体系（Tailwind + shadcn/ui + CSS 变量 Token）
category: frontend_style
scope:
    - '**'
source_files:
    - frontend/tailwind.config.js
    - frontend/src/styles/globals.css
    - frontend/components.json
    - frontend/package.json
    - frontend/src/components/layout/theme-provider.tsx
    - frontend/src/lib/motion.ts
    - docs/20. 前端视觉设计规范.md
    - client/flutter_app/design/FIGMA_TOKEN_SYNC.md
---

## 1. 系统概览

Quant Agent 的前端（`frontend/`，Vite + React 18）采用 **Tailwind CSS 3** 作为原子样式引擎，搭配 **shadcn/ui**（基于 Radix UI primitives）构建可复用的基础组件库；主题与品牌色通过 **CSS Custom Properties (CSS Variables)** 集中声明，配合 `next-themes` 实现明暗主题切换。Flutter 客户端（`client/flutter_app/`）则通过 Figma Variables → Dart Token 的同步表与 Web 端语义色对齐。

## 2. 关键文件与包

- `frontend/tailwind.config.js`：定义产品断点（sm/md/lg/desktop/wide/ultrawide）、颜色映射、圆角与过渡时长扩展。
- `frontend/src/styles/globals.css`：全局 CSS 入口，声明 `:root` / `.dark` 两套 CSS 变量（背景、前景、card、border、ring、bull/bear/warn/info/ai），并包含 `.glass-card`、`.segment-tabs`、`.sparkline`、`.stale-data`、场景模式 `[data-scene-mode]`、多分辨率响应式类（`resp-auto-panels`、`resp-3col`）及价格跳动动画。
- `frontend/components.json`：shadcn/ui 配置，style=`new-york`、RSC+TSX、CSS Variables、别名 `@/components`、`@/components/ui`、`@/lib/utils`、图标库 `lucide`。
- `frontend/package.json`：依赖 Tailwind、Radix UI（accordion/dialog/dropdown/popover/select/tooltip/toast 等）、ag-grid、lightweight-charts、echarts、zustand、sonner、i18next、next-themes、tailwind-merge、class-variance-authority 等。
- `frontend/src/components/layout/theme-provider.tsx`：对 `next-themes` 的轻量封装。
- `frontend/src/lib/motion.ts`：统一动效常量（fast/base/slow/flash/toast 毫秒值、EASING、MOTION_CLASS）。
- `docs/20. 前端视觉设计规范.md`：视觉规范文档，将 Linear/Vercel/Robinhood 特征映射到本仓 Token，规定语义色、断点、组件气质检查清单。
- `client/flutter_app/design/FIGMA_TOKEN_SYNC.md`：Figma Variables → Dart `AppColors`/`AppSpace`/`AppRadius` 的同步表，约束 Flutter 端禁止硬编码十六进制色值。

## 3. 架构与设计约定

### 3.1 设计令牌（Design Tokens）
- 所有颜色、圆角、动效时长均以 CSS 变量形式在 `globals.css` 中声明，Tailwind 通过 `hsl(var(--xxx))` 引用，使主题切换只需切换 `:root` / `.dark` 下的变量值。
- 金融语义色独立于通用语义：`--color-bull`（涨/多/盈）、`--color-bear`（跌/空/亏）、`--color-warn`（警告/STALE）、`--color-info`（信息）、`--color-ai`（AI）。这些在 Tailwind 中被映射为 `text-bull`、`text-bear`、`text-warn`、`text-info`。
- 场景强调色 `--scene-accent` 通过 HTML 根节点的 `data-scene-mode` 属性（watch/research/monitor/ai-analysis）动态覆盖，用于 Alert/Focus Ring/AI Badge 等关键 UI 的高亮。
- 密度缩放 `--density-scale` 控制面板紧凑度，移动端强制回退到 1。

### 3.2 主题策略
- 使用 `next-themes` 提供 `<ThemeProvider>`，通过 `darkMode: 'class'` 切换 `html.dark` 类名。
- 深色主题遵循“近黑底 + 白字层级 + 玻璃面板克制”的 Vercel/Linear 风格，背景 `#0F0F14`，面板分层使用 `--card` / `--secondary`。

### 3.3 组件库组织
- 基础组件集中在 `src/components/ui/*`，每个 Radix 子模块对应一个文件（button、dialog、popover、select、toast、table、tabs 等），并通过 `class-variance-authority` + `clsx` + `tailwind-merge` 管理变体。
- 业务布局组件在 `src/components/layout/*`（dashboard-layout、navbar、theme-provider、protected-route、mobile-tab-bar 等）。
- 数据展示组件在 `src/components/ui/data-display/*`（DataSourceBadge、EmptyState、InitOverlay、segment-tabs、sparkline）。

### 3.4 响应式策略
- 自定义断点：`desktop: 1280px`、`wide: 1440px`、`ultrawide: 1920px`，配合 `resp-auto-panels`、`resp-3col`、`resp-slide-in-right/left`、`resp-fade-up`、`resp-scale-in` 等工具类实现多分辨率布局。
- 超宽屏（≥2560px）启用三栏网格（行情 + 策略 + AI 副驾），research 场景专用 `.resp-3col.ide-3col` 保持 IDE 比例。
- 移动端（<768px）禁用极密布局（density-scale 强制为 1），改用底部 Tab Bar。

### 3.5 动效规范
- 统一通过 `src/lib/motion.ts` 暴露 `MOTION`（150/200/300/400/4500ms）和 `EASING`（standard/emphasized cubic-bezier）。
- 价格涨跌闪烁 `.tick-up/.tick-down` 使用 400ms 动画；Lighthouse 基准模式下通过 `.reduce-motion` 关闭全部动画。
- Toast 自动消失 4500ms，同屏上限 3（由 sonner 默认行为 + 项目配置保障）。

### 3.6 Flutter 客户端对齐
- Flutter 端通过 `design/figma_variables_sync.json` 与 `lib/presentation/theme/color_tokens.dart` 同步 Figma 变量，Web 端的 `--color-bull`/`bear`/`warn` 与 Dart `AppColors.*` 一一对应。
- 间距采用 4px 栅格（s1=4, s2=8, s3=12, s4=16, s6=24），圆角 sm/md/lg 分别 8/12/16px。
- 规范明确禁止 Feature Widget 内硬编码 `#RRGGBB`，必须引用 `AppColors.*`。

## 4. 约定与约束

- **颜色来源**：所有颜色必须通过 CSS 变量或 Tailwind 语义色（bull/bear/warn/info）引用，禁止在组件中硬编码十六进制色值。
- **面板风格**：优先使用 `.glass-card` 组合（半透明背景 + 细边框），避免多层阴影堆叠。
- **数字排版**：金融数字一律使用 `font-mono tabular-nums`，保证列对齐。
- **状态可视化**：数据过期统一走 `.stale-data`（降透明度 + 去饱和）+ `.stale-badge` 文案。
- **场景模式**：通过根节点 `data-scene-mode` 切换 `--scene-accent` 与 `--density-scale`，移动端强制 density=1。
- **无障碍**：用户开启「减少动态效果」时，所有 `resp-*` 入场动画通过 `prefers-reduced-motion` 自动禁用。
- **组件生成**：新增 UI 组件通过 shadcn/ui 脚手架生成，遵循 `new-york` 风格与 `cssVariables: true` 配置。
- **跨端一致性**：Flutter 与 Web 共享同一套语义色命名与数值，变更需同时更新 `figma_variables_sync.json` 并运行对应测试。