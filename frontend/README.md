# Quant Agent - 前端架构 (Vue 3 + Vite)

本项目前端采用 **Vue 3 (Composition API)** + **Vite** 构建，专为高频量化交易看板与大模型交互设计，强调“极速渲染、防抖节流、暗色高对比度”。

## 🚀 核心技术栈

- **核心框架**: Vue 3 (`<script setup>`) + Vite
- **样式系统**: Tailwind CSS (支持深度暗色主题与玻璃态 UI 设计)
- **数据可视化**: ECharts (严格遵守暗色与 Tailwind 颜色体系的 JSON 规范)
- **状态与数据流**: 基于 `composables/` 封装的单向数据流与生命周期管理

## 🏗️ 架构原则

1. **视图与数据流解耦 (Clean Architecture)**
   - 表现层 (`views/`, `components/`) 仅负责高颜值的静态渲染和 CSS 动画。
   - 业务逻辑层、复杂数据处理（防抖/节流）、以及与 FastAPI 后端交互的 WebSocket 长链接流统一剥离至 `useMarketData` 等 Composable 统一管控。
   
2. **极致性能与内存安全**
   - 行情高频 Tick 更新强制挂载严格的清理机制（避免 `Interval` 内存泄漏）。
   - 监听 `document.hidden` 页面可见性 API：当标签页被隐藏时，自动暂停模拟数据或 WebSocket 订阅流以节省算力。

3. **UI 视觉与无障碍**
   - 全局强制遵循暗黑金融质感风格（底色推荐 `#050505` 或冷灰 `#0f172a`）。
   - 数据上涨/看多必须使用绿 (`#10b981`)，下跌/看空必须使用红 (`#ef4444`)。
   - 重要交互按钮须满足 WCAG AA 级高对比度，并配有完整的 `aria-label` 属性。

## 🛠️ 快速开始

```bash
# 安装依赖
npm install

# 启动开发服务器 (HMR)
npm run dev

# 生产环境构建
npm run build
```
