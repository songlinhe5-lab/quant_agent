# ADR-007：Flutter 端重度 K 线 — CustomPainter（CLI-03b）

> **状态**：Accepted  
> **日期**：2026-07-13  
> **关联**：CLI-03 / CLI-03b · `docs/05` V4.0 · ADR-006  

---

## 背景

V4.0 将「自研全量 CustomPainter K 线」从 P0 降级为可选 **CLI-03b**，要求另立 ADR 后方可开工。CLI-03（sparkline / 简 K）仍是列表与概览的默认路径。用户于 2026-07-13 明确要求同步启动 CLI-03 与 CLI-03b。

## 决策

| 场景 | 方案 | 说明 |
|:---|:---|:---|
| 自选列表 / 卡片 | **CLI-03** Sparkline + MiniCandle | 轻量、无手势、数据点 ≤ 120 |
| 行情详情主图 | **CLI-03b** `CustomPainter` + `RepaintBoundary` | 捏合缩放、平移、长按十字线；目标 60fps |
| 禁止 | WebView 嵌 ECharts / fl_chart 做主图 | 与 ADR-006「自绘引擎」一致 |

## 范围与非目标

**做**：
- Domain `CandleBar` 实体（纯 Dart）
- `KlinePainter` 矢量绘制 OHLC + 网格 + 十字线
- `KlineChart` 手势层（scale / pan / long-press）+ `RepaintBoundary`
- 详情路由 `/quotes/:symbol`

**不做（本 ADR）**：
- 指标副图（MACD/RSI）— 后续迭代，优先走后端摘要
- Level 2 / Tick 回放
- 与 Web Lightweight-Charts 像素级对齐

## 性能约束

1. 高频路径禁止 `setState` 灌 Tick；手势状态用局部 `ValueNotifier` / 控制器，仅 `markNeedsPaint`
2. OHLC 使用 `Float64List` 连续缓冲，避免逐 bar 对象分配
3. 可见窗口裁剪：只 paint `startIndex…endIndex`
4. 单文件 Painter ≤ 300 行；逻辑拆 `kline_viewport.dart`

## 后果

- CLI-03b 解冻，与 CLI-03 同 PR 落地脚手架级图表（合成数据可演示）
- 真实行情仍经 `MarketStreamGateway` / REST（后续接 Gateway，不直连外部源）

## 替代方案（否决）

| 方案 | 否决理由 |
|:---|:---|
| fl_chart / syncfusion 主图 | 高频更新与手势定制成本高，难保 60fps |
| WebView + LW-Charts | 与薄客户端自绘决策冲突，鸿蒙 WebView 风险 |
| 仅深链打开 Web 行情 | 随身监控无离线/推送落地体验 |

---

**批准**：Accepted（产品指令 + 架构对齐 ADR-006）
