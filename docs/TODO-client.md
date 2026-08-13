# 📱 TODO — 客户端 Flutter（拆分自 TODO.md 2026-08-13）

### 客户端（Flutter）

> **架构 SSOT**：`docs/05` **V4.1**（整洁四层 · Gateway Ports · 薄客户端 · Figma DS）。ADR-006 已收口；地基 **CLI-01~07 / ARCH** 已完成；演进路线 **CLI-08~14** 见下。**不做**端上策略 IDE / 完整选股 / 回测工坊。

- [x] **[CLI-01]** Flutter 三端脚手架：四层目录（presentation/application/domain/infrastructure）+ Riverpod 注入 Ports + go_router Shell（Mobile/Tablet）——按 `docs/05` V4.0，非堆砌全量 Feature ✅ **2026-07-13**（`client/flutter_app/` · analyze 清洁 · 4 tests）
- [x] **[CLI-02]** `AppTelemetry` Adapter：FPS / 内存 / WS 延迟，30s → `POST /api/v1/client/heartbeat` ✅ **2026-07-13**（`HttpAppTelemetry` + `TelemetryLifecycle` · 8 tests）
- [x] **[CLI-03]** 轻量行情图（sparkline / 简 K）；~~P0 自研全量 CustomPainter K 线~~ → 可选 **CLI-03b**（另立 ADR） ✅ **2026-07-13**
- [x] **[CLI-03b]** （可选）重度 K 线 CustomPainter + RepaintBoundary，60fps——须 ADR 批准后启动 ✅ **2026-07-13**（**ADR-007** Accepted · 详情页捏合/平移/十字线）
- [x] **[CLI-04]** `AuthTokenStore`：`flutter_secure_storage`（Keychain/Keystore/OHOS） ✅ **2026-07-13**（`SecureAuthTokenStore` + Bearer 拦截 + `/login` 守卫 · `MemorySecureKvStore` 单测）
- [x] **[CLI-05]** 推送三通道 + `ui_hint` 深链（APNs / FCM / HMS · 对齐 docs/18） ✅ **2026-07-13**（`PushNotificationPort` + FCM/APNs/HMS Shell · `resolveAlertNavigation` · P0 Overlay / Toast / 角标）
- [x] **[CLI-06]** HarmonyOS NEXT：`platform/harmonyos/` + HMS 鉴权 / Push ✅ **2026-07-13**（MethodChannel 契约 · `HmsPushAdapter` · `loginWithHms` · `ohos/README`）
- [x] **[CLI-07]** 框架决策 → ADR-006：确认 Flutter，否决 Tauri Mobile ✅
- [x] **[CLI-ARCH-01]** 分层依赖门禁：folder lint / 测试禁止 Feature→Infrastructure 实现直连 ✅ **2026-07-13**（`LayerBoundaryChecker` · `cli_arch01_layer_boundary_test`）
- [x] **[CLI-ARCH-02]** Figma Variables → Dart `AppColors` Token 同步表（`docs/05` §八） ✅ **2026-07-13**（`design/figma_variables_sync.json` · `color_tokens.dart` · `cli_arch02_figma_token_sync_test`）

#### 演进路线 Phase 1 · 可随身监控（`docs/05` §十一）

> 薄客户端主路径：监控 / 告警 / 持仓只读；不算端上策略 IDE。

- [x] **[CLI-08]** `StaleOverlay` + 主题收口：WS/推送断连时行情·持仓·告警区强制 STALE（`opacity-60` + amber 标签）；ModeBanner 已有、Token 见 ARCH-02——补齐 Overlay 挂载与单测（`docs/05` §6.1 / §7） ✅ **2026-07-13**（`ConnectionHealth` + `StaleOverlay` · 行情/持仓/告警挂载 · `cli08_stale_overlay_test`）
- [x] **[CLI-09a]** `MarketStreamGateway` 真 WS：订阅行情频道 + 指数退避重连 + 前后台 pause/resume；列表/详情接真实 Tick（替换演示数据）；STALE 联动 **CLI-08** ✅ **2026-07-13**（`RealWsGatewayImpl` + `QuoteDataDecoder` + `LiveQuotesNotifier` · QuotesPage/Detail 接真实 WS · `cli09_ws_portfolio_test` 22 passed）
- [x] **[CLI-09b]** 持仓 REST：`GET /api/v1/...` 持仓摘要 → Portfolio Tab（只读 KPI + 列表）；经 `QuantRestGateway`，禁 Feature 直连 Dio ✅ **2026-07-13**（`PortfolioService` + `Position` 实体 · PortfolioPage KPI+列表 · 经 `QuantRestGateway`）

#### 演进路线 Phase 2 · 交易与鸿蒙

- [x] **[CLI-10]** 简化 OMS：撤单 + 小额下单确认单；LIVE 模式强制生物识别（`local_auth`）；沙箱默认不发真实单（对齐 `REAL_TRADE_EXECUTE`） ✅ **2026-07-13**（`BiometricAuth` port + `LocalBiometricAuth` + `Order` 实体 + `OmsService` + `OrderConfirmationPage` LIVE 生物识别门禁 + PortfolioPage 撤单入口 · `cli10_oms_biometric_test` 16 passed）
- [x] **[CLI-11]** Kill Switch 双重确认：确认短语 + 生物识别；仅 LIVE 可见；对接后端 Kill API；失败熔断提示 ✅ **2026-07-13**（`KillSwitchService` + `KillSwitchNotifier` + `KillSwitchDialog` 两步确认 · MorePage LIVE-only 按钮 · `cli11_kill_switch_test` 12 passed）
- [x] **[CLI-12]** Copilot SSE：精简对话页接后端 SSE；流式 token；复用 Gateway，不做端上 Tool 直连 ✅ **2026-07-13**（`ChatMessage`/`ChatChunk` 实体 + `ChatStreamGateway` port + `SseChatGatewayImpl` Dio stream + `CopilotNotifier` 流式状态管理 + `CopilotPage` 完整对话 UI · `cli12_copilot_sse_test` 19 passed）

#### 演进路线 Phase 3 · 体验增强（可选）

- [x] **[CLI-13]** 平板双列精细化：≥600 Rail 主从（持仓选中 → 简图/下单确认）；不复制 Web 五栏 IDE ✅ **2026-07-13**（`CandleBar.fromJson` + `HistoryKlineService` + `TabletPortfolioPage` master-detail 双栏布局 · PortfolioPage 宽度断点切换 · `cli13_tablet_portfolio_test` 12 passed）
- [x] **[CLI-03b]** 重度 K 线（原 Phase 3「另立 ADR」）→ 已由 **ADR-007** + CLI-03b 收口 ✅
- [x] **[CLI-14]** Isolate / `compute` 卸载大包 JSON（历史 K 线 / 告警补拉）；主 Isolate 禁止同步解析超大 payload ✅ **2026-07-13**（`IsolateJsonParser` 32KB 阈值 + `RestGatewayImpl._mapAsync` Isolate 解析 + `HistoryKlineService` compute 批量解析 + `QuoteDetailPage` 接真实历史 K 线 · `cli14_isolate_json_test` 9 passed）

#### 演进路线 Phase 4 · 探索（不排期）

> 见下方 P3「客户端探索」**CLI-P4-01~03**；默认不做 Tauri Mobile（ADR-006）。


### 客户端探索（Phase 4）

- [ ] **[CLI-P4-01]** Apple Watch / Android Wear 价格预警极简卡片
- [ ] **[CLI-P4-02]** 语音指令模式（Whisper 语音转文字 → Hermes Agent）
- [ ] **[CLI-P4-03]** Flutter Web 低成本替代移动端 H5 嵌入场景

