# 客户端子系统架构文档（Flutter 三端：Android / iOS / HarmonyOS）

> 最后更新：2026-06-27 | 版本：V2.0  
> 三端：Android | iOS | HarmonyOS NEXT

## 一、目录架构图

```
client/flutter_app/lib/
├── main.dart                            应用入口（ProviderScope + Theme + GoRouter）
│
├── core/                                平台无关核心层（不含任何 UI 代码）
│   ├── network/
│   │   ├── ws_client.dart               WebSocket 客户端（指数退避重连）
│   │   ├── sse_client.dart              SSE 客户端（Hermes Agent 流式输出）
│   │   ├── api_client.dart              Dio HTTP 客户端
│   │   └── auth_interceptor.dart        JWT 自动刷新
│   ├── storage/
│   │   ├── secure_storage.dart          Token 加密存储（Keychain/Keystore/HMS Keystore）
│   │   └── isar_service.dart            K线历史本地缓存（Isar DB）
│   ├── monitoring/
│   │   ├── app_monitor.dart             APM 指标采集（FPS/内存/WS延迟，30s 心跳）
│   │   └── crash_reporter.dart          Firebase Crashlytics 上报
│   └── di/providers.dart               Riverpod 全局 Provider 声明
│
├── features/                            业务功能（按金融域划分）
│   ├── auth/                            认证（Login + 生物识别）
│   ├── portfolio/                       持仓总览
│   ├── market/                          行情 + K线
│   ├── oms/                             订单管理
│   ├── risk/                            风控面板
│   ├── alert/                           告警中心
│   └── copilot/                         AI 副驾（SSE 流）
│
├── shared/
│   ├── widgets/financial/               量化 UI 原子组件
│   │   ├── price_text.dart              等宽数字价格文本
│   │   ├── change_badge.dart            涨跌幅 Badge（颜色语义）
│   │   ├── stale_overlay.dart           数据过期遮罩（WS 断连时显示）
│   │   ├── kill_switch_fab.dart         一键熔断悬浮按钮（含持仓页必须有）
│   │   └── mode_banner.dart             SANDBOX/LIVE 模式横幅（不可关闭）
│   ├── widgets/charts/
│   │   ├── kline_chart.dart             K线主图（CustomPainter + RepaintBoundary）
│   │   └── mini_chart.dart              自选列表缩略走势图
│   ├── widgets/layout/
│   │   ├── adaptive_layout.dart         自适应布局（手机 <600 / 平板折叠屏 ≥600）
│   │   └── bottom_nav.dart              底部 Tab 导航
│   ├── theme/
│   │   ├── color_tokens.dart            颜色语义 Token（与 Web 端 Tailwind 色严格对齐）
│   │   └── text_styles.dart             JetBrains Mono 等宽字体
│   └── utils/
│       ├── financial_formatter.dart     价格/成交量/涨幅格式化
│       └── market_time.dart            A股/港股/美股交易时段判断
│
└── platform/
    ├── android/                         FCM 推送渠道配置
    ├── ios/                             APNs Critical Alert 权限请求
    └── harmonyos/                       HMS Push Kit + 分布式软总线接入
```

**工程目录**：
```
client/flutter_app/
├── android/
├── ios/
├── ohos/           ← HarmonyOS NEXT（华为 Flutter Fork 生成）
└── pubspec.yaml
```

## 二、高频数据流（Flutter 零 GC 路径）

```
WebSocket 帧到达（dart:io WebSocket）
  ↓ WsClient.tickStream（broadcast Stream）
  ↓ Riverpod StreamProvider（自动订阅/取消，无内存泄漏）
  ↓ ConsumerWidget ref.listen（仅变化时触发）
  ↓ RepaintBoundary.markNeedsPaint()
Canvas CustomPainter.paint()（不触发 Widget Tree rebuild）
```

**严禁路径**：
```
WebSocket 帧 → setState → Widget Tree 全量重建  ❌ 卡顿 UI
WebSocket 帧 → ChangeNotifier.notifyListeners  ❌ 全局重建
```

**大 JSON 卸载（历史 K线）**：
```
rawJson → compute(_parseKlines, raw) → 子 Isolate → 主线程接收 List<KlineBar>
```

## 三、渲染策略决策表

| 场景 | 必须用 | 严禁用 |
|:---|:---|:---|
| K线主图 / 分时图 | `CustomPainter` + `RepaintBoundary` | WebView 内嵌 ECharts |
| 行情列表（5000+ 行） | `ListView.builder` 虚拟列表 | `Column` + 静态 `children` |
| 数字价格跳动 | Riverpod `select`（只监听单字段变化） | 整个 Provider `notifyListeners` |
| 低频归因图表 | `fl_chart` 或 `syncfusion_flutter_charts` | CustomPainter（过度工程） |

## 四、推送通知三端对照

| 优先级 | 场景 | Android (FCM) | iOS (APNs) | HarmonyOS (HMS) |
|:---:|:---|:---:|:---:|:---:|
| P0 | 止损触发 / 全局熔断 | FCM high | APNs critical-alert | HMS urgent |
| P1 | 策略信号触发 | FCM high | APNs time-sensitive | HMS high |
| P2 | 委托成交 | FCM normal | APNs active | HMS normal |
| P3 | AI 研报完成 | FCM low | APNs passive | HMS low |

> **HarmonyOS 特别说明**：华为应用市场要求必须使用 HMS Push Kit，不接受 Firebase。  
> 通过 Platform Channel 调用鸿蒙原生 HMS Push SDK，独立对接。

## 五、客户端 APM 心跳数据格式

```json
POST /api/v1/client/heartbeat

{
  "client_id":       "uuid-xxx",
  "platform":        "android",   // "android" | "ios" | "harmonyos"
  "app_version":     "1.2.0",
  "fps_current":     59.8,
  "memory_mb":       132,
  "ws_latency_ms":   12,
  "ws_disconnect_count": 0,
  "error_count":     0,
  "active_screen":   "/portfolio",
  "trading_mode":    "sandbox",
  "timestamp":       "2026-06-27T14:35:00Z"
}
```

Web 端 `/client-apm` 独立看板消费此数据，与 `/apm` 后端日志页面**完全独立**。

## 六、关键交互漏洞与修复优先级

| 优先级 | 问题 | 修复位置 |
|:---:|:---|:---|
| P0 | WS 断连无 STALE 遮罩 | `stale_overlay.dart` 嵌入每个行情 Widget |
| P0 | JWT 存 SharedPreferences（明文）| 迁移至 `flutter_secure_storage` |
| P0 | Kill Switch 不在所有含持仓页面 | `kill_switch_fab.dart`（Scaffold floatingActionButton）|
| P1 | 实盘模式无明显标识 | `mode_banner.dart` 嵌入 AppBar 下方 |
| P1 | App 后台不暂停 WS（耗电/耗流量）| `WsLifecycleObserver` 绑定 WidgetsBinding |
| P1 | HarmonyOS 未接 HMS Push（华为市场审核会驳回）| `platform/harmonyos/hms_push.dart` |
| P2 | 无生物识别（下单前）| `local_auth` 包 |
| P2 | 无证书固定（MITM 风险）| `api_client.dart` SSL Pinning |

## 七、性能基准（见 docs/09.）

| 指标 | 目标 | 备注 |
|:---|:---:|:---|
| K线 60fps 渲染维持 | ≥ 30 分钟 | 不得因内存增长掉帧 |
| 后台耗电（WS 暂停）| ≤ 1% / 小时 | 生命周期感知必须实现 |
| 冷启动到行情可见 | ≤ 2.5s | Isar 本地缓存优先展示 |
| APM 心跳体积 | ≤ 1KB / 次 | 30s 一次，不占用行情通道带宽 |

## 八、变更记录

| 日期 | 变更 |
|:---|:---|
| 2026-06-27 V2.0 | 三端更新为 Android / iOS / HarmonyOS（移除 macOS）；鸿蒙从 Phase 4 升级为主线 |
| 2026-06-27 V1.0 | 初始版本（Flutter 三端，含 macOS，已废弃） |
