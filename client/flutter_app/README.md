# Quant Agent Flutter Client (CLI-01)

> **定位**：随身监控 / 告警 / 简化交易薄客户端（docs/05 **V4.1**）  
> **路径**：`client/flutter_app/`  
> **演进任务**：`docs/TODO.md` **CLI-08~14**（Phase 1~3）· **CLI-P4-***（Phase 4）

## 分层

```
lib/
├── domain/            Entities + Ports（纯 Dart）
├── application/       Use cases（跨 Feature）
├── infrastructure/    Adapters（Dio / SecureStorage / WS stub / APM stub）
├── features/          五域 Feature 占位页
├── presentation/      Shell / Theme / 壳层 Widgets
├── platform/          android / ios / harmonyos 占位
├── injection.dart     Port → Adapter 唯一组装点
└── main.dart
```

## 运行

```bash
cd client/flutter_app
flutter pub get
flutter run
flutter test
flutter analyze
```

API 基址：`--dart-define=API_BASE_URL=https://your-host`  
版本号：`--dart-define=APP_VERSION=0.1.0`

## APM（CLI-02）

- `HttpAppTelemetry` 采集 FPS（FrameTiming）/ 内存（RSS）/ WS 延迟
- 前台每 **30s** `POST /api/v1/client/heartbeat`（对齐 BE-08）
- `TelemetryLifecycle`：`resumed` 启动、`paused` 停止

## 行情图（CLI-03 / CLI-03b · ADR-007）

- 列表：`Sparkline` + `MiniCandleChart`
- 详情 `/quotes/:symbol`：`KlineChart`（CustomPainter + RepaintBoundary，捏合/平移/长按十字线）
- OHLC：`CandleSeries`（Float64List）可见窗口裁剪

## 鉴权（CLI-04）

- `SecureAuthTokenStore` → `flutter_secure_storage`（Keychain / Keystore；禁 SharedPreferences）
- Dio `AuthBearerInterceptor` 自动附带 Bearer；跳过 `/auth/login` · `/auth/refresh`
- `/login` + `go_router` 守卫；「更多」页登出
- 单测用 `MemorySecureKvStore`（`test/cli04_auth_token_store_test.dart`）

## 推送 + 深链（CLI-05）

- Port：`PushNotificationPort`（FCM / APNs / HMS + Memory）
- `ui_hint` → `resolveAlertNavigation` → `/quotes/:symbol` 等（对齐 Web `alert-nav.ts`）
- P0 全屏 Overlay · P1/P2 Toast · 告警 Tab 角标
- `PushLifecycle` 启停 + 冷启动 `consumeInitialMessage`
- 测试：`test/cli05_push_deeplink_test.dart`

## HarmonyOS / HMS（CLI-06）

- `lib/platform/harmonyos/`：`hms_push` / `hms_auth` MethodChannel 契约（Feature 禁止直连）
- `HmsPushAdapter`：`isAvailable` → token / EventChannel 消息 → `AlertPush`
- `loginWithHms`：Account Kit → `POST /api/v1/auth/hms` 换 JWT
- 构建：`--dart-define=HARMONYOS=true`；工程说明：`ohos/README.md`
- 测试：`test/cli06_harmonyos_hms_test.dart`

## 架构门禁（CLI-ARCH-01 / 02）

- **ARCH-01**：`lib/tooling/layer_boundary.dart` 扫描 import 矩阵（禁 Feature→Infrastructure / Domain 无 Flutter）
- **ARCH-02**：`design/figma_variables_sync.json` ↔ `presentation/theme/color_tokens.dart`
- 测试：`cli_arch01_layer_boundary_test` · `cli_arch02_figma_token_sync_test`

## 下一跳（docs/05 §十一 → TODO CLI-08~14）

| ID | 内容 |
|:---|:---|
| CLI-08 ✅ | StaleOverlay + ConnectionHealth |
| CLI-09a/b | 真 WS 行情 + 持仓 REST |
| CLI-10~12 | 简化 OMS / Kill / Copilot SSE |
| CLI-13~14 | 平板双列 / Isolate 大包 |

## STALE（CLI-08）

- `StaleOverlay` / `StaleBadge`：断连时 opacity 0.6 + 去饱和 + amber 标签
- `ConnectionHealth`：`marketLive` / `alertsLive`；`ConnectionHealthSync` 桥接 `MarketStreamGateway.marketConnection`
- 挂载：行情列表·详情、持仓、告警
- 测试：`test/cli08_stale_overlay_test.dart`
