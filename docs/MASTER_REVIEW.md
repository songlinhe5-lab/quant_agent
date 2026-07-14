# QuantEdge 全工程 Review 总汇（Master Review）

> **文档定位**：本工程所有架构、产品、前后端、客户端、部署 Review 的统一入口，每次 Review 结论在此汇总。  
> **最后更新**：2026-07-12 | **版本**：V3.0（第三轮 Review：业界对标与差距分析）  
> **详细规范**：各结论对应的完整规范见具体文档，此文件仅归档结论与待办。  
> ⚠️ **阅读提示**：§四/§五 为 2026-06-27 第二轮 Review 的待办快照，其中大部分已完成（完成状态以 `docs/TODO.md` 为准）。最新结论见 **§七 第三轮 Review**。

---

## 一、系统全局评分（V3.0 · 2026-07-12）

| 子系统 | V3.0 评分 | V2.0 评分 | 变化 | 本轮评语 |
|:---|:---:|:---:|:---:|:---|
| 产品设计 & UI | ⭐⭐⭐⭐☆ | ⭐⭐⭐⭐☆ | → | 设计文档完整，但告警中心/策略实验室**设计与任务脱节**（无 TODO 承接） |
| AI 工程规范 | ⭐⭐⭐⭐☆ | ⭐⭐⭐⭐☆ | → | RL-01~14 限流体系业界少见；Eval Golden Dataset 仍未落地 |
| 后端架构 | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | → | 三通道隔离/K线管道/熔断/限流感知全部落地，机构级水平 |
| 前端架构 | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐☆ | ↑ | V2.0 发现的 P0 漏洞（双布局/STALE/ErrorBoundary）全部修复 |
| 客户端架构 | ⭐⭐☆☆☆ | ⭐⭐⭐⭐☆ | ↓↓ | **纸面架构完整但代码零进展**，且 CLI-07 重开框架决策（Flutter vs Tauri Mobile），ADR-002 动摇 |
| 工程化部署 | ⭐⭐⭐⭐☆ | ⭐⭐⭐⭐☆ | → | CI/CD/备份/演练完成；但 DIST Phase 3~4 未部署，**加州主节点仍是单点** |
| 数据正确性 | ⭐⭐☆☆☆ | （未评估） | 新增 | 复权/时区已做（BE-16），但**无 point-in-time、无幸存者偏差处理、SVC 契约测试全空** |
| 质量工程 | ⭐⭐⭐☆☆ | （未评估） | 新增 | 单测 2156 个可观，但**覆盖率门禁从 70%/60% 静默降至 5%/10%**，E2E/压测/契约测试未做 |
| **整体** | **领先个人系统** | **领先个人系统** | → | 工程基建已收口，短板转移至：**产品功能闭环、数据正确性、客户端落地** |

---

## 二、架构决策记录（Architecture Decision Records）

> **所有 ADR 均已最终确认，后续 Vibe Coding 及代码审查均以此为基准，不再重复讨论。**

### ADR-001：前端框架 — 纯 Vite SPA（放弃 Next.js）

| 维度 | 纯 Vite SPA（已选）| Next.js App Router（已排除）|
|:---|:---|:---|
| 渲染延迟 | WebSocket Tick → Canvas，无服务端往返 | RSC 边界序列化增加开销 |
| 核心组件兼容 | Canvas/WebGL 原生无负担 | 所有图表组件需 `'use client'`，RSC 优势全失 |
| 部署成本 | 纯静态 → Cloudflare Pages，零 CPU | 必须维护 Node.js 进程 |
| 适配理由 | 量化看板：长期挂机、重客户端、无 SEO | 适合内容站、电商、SEO 场景 |

**结论**：React 18 + Vite + React Router v6。已更新 `AI_INSTRUCTIONS.md` / `docs/04` / `.cursor/rules/vibe-coding.mdc`。

---

### ADR-002：客户端框架 — Flutter 三端（放弃原生四端）

| 维度 | Flutter 三端（已选）| 原生四端（已排除）|
|:---|:---|:---|
| 代码复用 | 业务逻辑 ~90%，UI ~70% | 四套代码库独立维护 |
| 开发效率 | 单兵可维护 | 需 3-4 人分别维护 |
| 鸿蒙支持 | 华为官方 Flutter Fork | ArkTS 原生，生态尚不成熟 |
| 推送通知 | APNs + FCM + HMS Push Kit | 三套证书独立对接 |

**结论**：Flutter（Dart）统一 Android + iOS + HarmonyOS NEXT 三端。已更新 `AI_INSTRUCTIONS.md §2.4`。

---

### ADR-003：部署策略 — 双 VPS + Cloudflare 边缘 ⚠️ 已被 ADR-004/005 迭代

| 节点 | 选型 | 职责 | 月费 |
|:---|:---|:---|:---|
| 节点 A（香港）| 腾讯云轻量 2C/4G | Futu OpenD + Redis + PostgreSQL + FastAPI | ¥24 |
| 节点 B（境外）| Hetzner CX22 | Hermes Agent + Ollama + Grafana | ≈¥31 |
| Cloudflare 边缘 | 全部免费 | Pages + Tunnel + R2 + Workers + Access | ¥0 |

**结论**：全套月费 ≈ ¥55，对比 AWS 方案节省 85%。~~已更新 `docs/06`~~ → 节点拓扑已被 ADR-005 取代，Cloudflare 边缘策略仍有效。

---

### ADR-004：分布式数据源架构 — 服务注册表 + 动态路由（2026-06-28）

**决策**：数据源从进程内单体升级为「ServiceRegistry 注册发现 + 加权路由 + failover + STALE 降级」的分布式架构，数据源可作为独立子服务（`data_subservice/`）部署在任意节点。

**依据**：YFinance/AKShare 存在 IP 限流，单 IP 无法支撑采集频率；多节点分摊 + 就近直连（境外源走加州、国内源走北京）。

**详细设计**：`docs/14. 分布式数据源服务架构.md`（V2.0，含限流感知 §十二）。

---

### ADR-005：主节点迁移 — 加州主节点 + 北京辅助节点（2026-07-08）

| 节点 | 职责 | 变更 |
|:---|:---|:---|
| 加州 VPS (38.60.126.42) | API + Worker + Redis + PostgreSQL + 境外数据源（YFinance/Finnhub/FRED/Futu） | 从数据子节点**升级为主节点** |
| 北京 VPS | 仅 AKShare 采集器（国内直连优势），经 Tailscale 内网回传 | 从主节点**降级为辅助节点** |

**依据**：Cloudflare Pages（前端）访问北京 VPS 存在跨境延迟（200-300ms）+ GFW 反向干扰；加州节点与 Cloudflare 链路最优，且境外数据源直连。

**风险（本轮 Review 标记）**：加州主节点为**单点**，宕机即全停。北京节点只有采集能力，无法接管 API/DB。DR 预案见 §七。

---

### ADR-006：客户端框架终审 — 确认 Flutter 三端，否决 Tauri Mobile（2026-07-12）

> **背景**：ADR-002 已决策 Flutter 三端，但 CLI-07 任务重开框架对比（Flutter vs Tauri Mobile v2.5）。经评估，维持原决策。

| 维度 | Flutter 3.22+（✅ 确认） | Tauri Mobile v2.9（❌ 否决） |
|:---|:---|:---|
| **渲染引擎** | Skia/Impeller 自绘引擎，CustomPainter 原生支持高频 K 线渲染 | 系统 WebView（WKWebView/Android WebView），金融图表性能受限 |
| **实时图表性能** | 60fps 自定义绘制 + RepaintBoundary 隔离，已验证设计 | WebView 内 Canvas/WebGL 性能不确定，无量化终端先例 |
| **HarmonyOS** | 华为官方 Flutter Fork，原生支持 | **不支持**，无鸿蒙适配计划 |
| **推送通知** | APNs + FCM + HMS Push Kit 三通道成熟插件 | 需自行对接原生推送插件，移动端插件生态不成熟 |
| **代码复用** | 与 Web 端零复用（Dart vs TypeScript），但移动端 UI 必须重写 | 可复用 React 前端代码（最大优势），但移动端体验妥协大 |
| **生态成熟度** | pub.dev 40k+ 包，Google Pay/Ads 生产验证，全球 34% 市占率 | v2.0 2024 年末稳定，移动端生态早期，社区反馈“生产就绪度不确定” |
| **单兵维护** | 单代码库三端，热重载开发效率高 | 桌面端优秀，移动端体验受限于 WebView |
| **生物识别下单** | local_auth 插件成熟（指纹/Face ID） | 需自行集成原生 API |

**终审结论**：**维持 ADR-002，Flutter 三端不变。**

**核心理由**：
1. 量化交易终端的核心体验是**实时 K 线 + 高频推送 + 下单操作**，Flutter 自绘引擎是唯一能保证 60fps 图表渲染的方案
2. HarmonyOS 支持是华为市场发布的硬性要求，Tauri 完全不支持
3. Tauri 的唯一优势（复用 React 代码）不足以弥补移动端体验的妥协——移动端 UI 必须为小屏幕重新设计，复用价值有限
4. Tauri Mobile v2.9 仍处于快速迭代期，生产稳定性未经大规模验证

**决策影响**：CLI-07 关闭，CLI-01~06 解冻，可按 Flutter 栈启动开发。

### ADR-007：Flutter 重度 K 线 — CustomPainter（CLI-03b · 2026-07-13）

> **文档**：`docs/ADR-007-flutter-kline-custompainter.md` · **状态**：Accepted

| 场景 | 方案 |
|:---|:---|
| 列表 / 卡片 | CLI-03 Sparkline + MiniCandle |
| 行情详情主图 | CLI-03b `CustomPainter` + `RepaintBoundary`（捏合/平移/十字线） |
| 禁止 | WebView 嵌 ECharts 作主图 |

**批准理由**：用户同步启动 CLI-03b；与 ADR-006「自绘 60fps」一致；列表保持轻量，主图限定详情页。

---

## 三、各文档 Review 结论摘要

### 📄 doc 01 — 产品功能与 UI/UX 架构

> **详细文档**：`docs/PRODUCT_UI_REVIEW.md`

**核心发现**：功能模块深度接近业界水准，但**信息架构是最大短板**。9 个分离页面的跳转模式让用户不断丢失上下文，与专业终端的流畅感差距明显。

**重要决策**：
- 从"分页跳转"迁移至"持久单页 + 面板编排"架构（类 Bloomberg 三区域模型）
- AI 副驾从独立页面改为全局右侧抽屉（任何模块均可唤起）
- 新增全局命令面板（Cmd+K）和告警中心（当前完全缺失）
- 模块切换采用 keep-alive 保活策略（不卸载组件，保留内部状态）

**P0 待办**：
- [ ] 全局底部状态栏（Futu 状态 / Redis 状态 / WS 延迟 / 模式标识）
- [ ] AI 副驾改为全局右侧抽屉
- [ ] 右键上下文菜单统一规范（任何数据行）
- [ ] 模块切换 keep-alive（不卸载组件）

---

### 📄 doc 02 — Vibe Coding 与 AI 工程规范

> **详细文档**：`docs/02. Vibe Coding与AI工程规范.md`（已完整重写为 V3.0）

**核心发现**：原文档偏向理念描述，缺乏可执行的工程约束。

**重要决策**：
- YAGNI/KISS 原则防过度工程
- 文件行数硬限制（前端：原子 80 行 / 分子 150 行 / Feature 250 行；后端：Router 100 行 / Service 200 行）
- 组件 Atomic Design 层级（Atoms → Molecules → Organisms → Features → Pages）
- 单元测试随代码同步提交，覆盖率持续提升
- 全量 structlog 结构化日志（后端）+ `logger.ts` 统一接口（前端）
- 性能测试报告：pytest-benchmark + Locust + Lighthouse

**P1 待办**：
- [ ] 建立 `prompts/` 目录，系统级 Prompt 纳入版本控制
- [ ] LLM 模型版本锁定（防 Provider 静默升级）
- [ ] 建立 Eval 标准测试用例集（≥ 50 条 Golden Dataset）
- [ ] RAG 知识库新鲜度策略（各类文档 TTL 规范）

---

### 📄 doc 03 — 后端架构与执行引擎

> **详细文档**：`docs/03. 后端架构与执行引擎.md`（已完整重写为 V3.0）

**核心发现**：节点化 + ZeroMQ + Redis 总线 + DuckDB 设计达机构级水平，但 API 隔离、安全分级和实时管道文档缺失。

**重要决策**：
- 三通道 API 隔离：公开 REST / WebSocket（行情）/ SSE（AI 流）/ 内部 Tool API（HMAC 签名）
- K线实时管道：Tick → Redis 环形缓冲 → L1/L2/L3 三级缓存（Redis Hot / DuckDB Warm / Futu API Cold）
- 数据安全四级：极敏感（不落库）/ 高敏感（加密）/ 中敏感（脱敏展示）/ 公开
- JWT 双 Token（Access 15min + Refresh 7天）+ HTTP-only Cookie

**P0 待办**：
- [ ] 后端新增 `POST /api/v1/client/heartbeat` 接口（Flutter APM 心跳）
- [ ] Alembic 数据库迁移体系（禁止手动 DDL）
- [ ] Futu 断连恢复 SOP 文档化（在途订单处理流程）

**P1 待办**：
- [ ] OpenTelemetry 分布式追踪接入
- [ ] Futu API 行情订阅配额实时监控
- [ ] 统一健康检查 `/health`（存活）和 `/ready`（含 Redis/PG 连通性）

---

### 📄 doc 04 — 前端架构与零 GC 渲染

> **详细文档**：`docs/04. 前端架构与零GC渲染.md`（已完整重写为 V3.0）

**核心发现**：渲染引擎分层设计先进，但存在多个 P0 级交互漏洞。

**关键漏洞（已记录）**：

| 优先级 | 漏洞 | 修复方案 |
|:---:|:---|:---|
| P0 | 双布局系统并存（`TradingDashboard` vs `DashboardLayout`）| 废弃 `DashboardLayout`，统一使用 `TradingDashboard` |
| P0 | WS 断连无 STALE 遮罩，用户看到过期数据无感知 | 断连时全局叠加 STALE 遮罩 |
| P0 | TickerTape 用 60s REST 轮询，数据最多滞后 60s | 迁移至 WebSocket 推送 |
| P1 | `OmniSearch` 已存在但无 `Cmd+K` 绑定 | 在 `TradingDashboard` 绑定全局键盘事件 |
| P1 | 无全局底部状态栏 | 新建 `StatusBar` 组件 |
| P1 | 无三层 Error Boundary | 模块级 / 面板级 / 图表级 三层实现 |
| P2 | AI 副驾是独立整页，切换丢失上下文 | 改为全局右侧抽屉 |
| P2 | 实盘模式无明显标识 | 顶栏显示红色脉冲 `LIVE` Badge，不可关闭 |

**重要规范新增**：
- WS 断连 5 步处理流程（立即遮罩 → 指数退避重连 → 成功淡出 → 全失败通知）
- 涨跌幅七档细分颜色（从 `text-emerald-300` 到 `text-red-300`）
- 玻璃态卡片统一样式、等宽数字强制规范（`font-mono tabular-nums`）

---

### 📄 doc 05 — 客户端架构（Flutter 薄客户端）

> **详细文档**：`docs/05. 客户端架构与Tauri壳资源.md`（**V4.0** 实施前 Review 重写）

**V4.0 核心**：Clean Architecture 四层（Presentation→Application→Domain←Infrastructure）· Gateway Ports 统一出站 · 端侧极简（监控/告警/简化交易；IDE/选股/回测留 Web）· 模块对齐 Web 五域 · Figma Design System 指引。

**技术栈确定**：

```
框架：Flutter 3.22+ / Dart 3.4+
三端：Android (Vulkan) | iOS (Metal) | HarmonyOS NEXT (Vulkan)
状态管理：Riverpod 2.x（代码生成版）
路由：go_router 14.x
K线图表：Custom CustomPainter + RepaintBoundary（非 fl_chart）
本地缓存：Isar 3.x
安全存储：flutter_secure_storage（非 SharedPreferences）
推送：FCM (Android) + APNs (iOS) + HMS Push Kit (HarmonyOS)
```

**客户端 APM 监控系统（新增）**：
- Flutter `AppMonitor` 每 30s 上报：FPS / 内存 / WS 延迟 / 错误数
- 后端新接口：`POST /api/v1/client/heartbeat`
- Web 前端新增 `/client-apm` 独立看板（与 `/apm` 后端日志分离）

**Phase 4 备选（不纳入主线）**：
- 穿戴设备原生 App（Apple Watch / 华为 Watch GT，超出 Flutter 能力）
- 桌面端（Flutter macOS 或 Tauri v2，按需评估）
- AI 语音交互（前提：OMS 执行链路完整）
- WebGPU 移动端图表（当前 Flutter WebGPU 实验阶段）

---

### 📄 doc 06 — 工程化配置与部署方案

> **详细文档**：`docs/06. 工程化配置与部署方案.md`（**V9.0 · 四节点**）

**拓扑冻结（2026-07-13）**：US-MASTER（API/DB/OMS/Futu）+ US-YF-A/B（yfinance 双公网 IP）+ CN-AKSHARE（仅国内源）；节点间 Tailscale；主节点默认不直连 Yahoo。

**Cloudflare 免费资源利用**：

| 产品 | 用途 | 免费额度 |
|:---|:---|:---|
| Pages | 前端 SPA 全球 CDN | 无限请求 |
| Tunnel | 替代暴露公网端口（零信任接入）| 免费 |
| R2 | 报告/回测/备份对象存储 | 10GB/月 |
| Workers | 宏观数据边缘缓存代理 | 10万次/日 |
| Access | 管理页面零信任鉴权（Grafana 等）| 免费（≤50用户）|

**GitHub 免费资源利用（全新）**：
- `ghcr.io` 替代 Docker Hub（私有镜像免费）
- GitHub Actions 完整 CI/CD 流水线（质量门禁 → 镜像构建 → Pages 部署 → SSH 部署 → 通知）
- GitHub Releases 分发 Flutter APK/IPA

**Redis 关键规范**：
- 内存策略：`allkeys-lru` + `maxmemory 2gb`
- 双持久化：AOF（`appendfsync everysec`）+ RDB（`save 900 1` / `save 300 10`）
- Key 命名：`{namespace}:{subject}:{scope}`（如 `quote:tick:HK.00700`）
- 每日自动备份到 Cloudflare R2

**pgvector 迁移方案（全新）**：
- 导出：`pg_dump -t knowledge_chunks -F c`
- 中转：上传至 Cloudflare R2
- 恢复：`pg_restore` + `REINDEX INDEX CONCURRENTLY`
- 定期清理：`DELETE FROM knowledge_chunks WHERE expires_at < NOW()`

---

## 四、全工程 P0 漏洞汇总（必须修复）

> 以下问题直接影响系统稳定性或用户安全，是编码工作最高优先级。

### 前端 P0

- [ ] `DashboardLayout`（Next.js 路由）与 `TradingDashboard`（模块切换）双布局并存 → 废弃前者
- [ ] WS 断连无 STALE 遮罩 → 实现 `StaleOverlay` + 全局 WS 生命周期管理
- [ ] TickerTape 60s REST 轮询 → 迁移至 WebSocket 实时推送
- [ ] 无三层 Error Boundary → 实现模块级 / 面板级 / 图表级

### 客户端 P0

- [ ] JWT Token 存 SharedPreferences（明文）→ 迁移至 `flutter_secure_storage`
- [ ] Kill Switch FAB 未在所有含持仓页面显示
- [ ] HarmonyOS 端未接 HMS Push Kit（华为市场审核必须）
- [ ] WS 断连无 StaleOverlay

### 后端 P0

- [ ] 后端未有 `POST /api/v1/client/heartbeat` 接口（客户端 APM 依赖）
- [ ] 未使用 Alembic 管理 Schema 变更（手动 DDL 风险）

### 部署 P0

- [ ] Redis 端口（6379）暴露至公网（应仅 Docker 内网访问）
- [ ] PostgreSQL 端口（5432）暴露至公网（同上）
- [ ] VPS SSH 未关闭密码登录，未改非标端口

---

## 五、全工程待办清单（按优先级）

### 🔴 P0 — 立即实施

**前端**：
- [ ] 废弃 `DashboardLayout`，统一 `TradingDashboard` 模块切换架构
- [ ] 实现全局底部状态栏 `StatusBar`（WS / Redis / Futu 状态 + 模式标识）
- [ ] TickerTape 迁移 WebSocket
- [ ] STALE 遮罩 + WS 断连 5 步处理流程
- [ ] 三层 Error Boundary

**客户端**：
- [ ] Flutter 项目初始化（三端：Android / iOS / HarmonyOS）
- [ ] `flutter_secure_storage` 替换 SharedPreferences
- [ ] `AppMonitor` APM 采集 + 心跳上报

**后端**：
- [ ] `POST /api/v1/client/heartbeat` 接口
- [ ] Web 前端 `/client-apm` 独立看板页面
- [ ] Alembic 迁移体系建立

**部署**：
- [ ] Cloudflare Tunnel 替换公网端口暴露
- [ ] Cloudflare Pages 部署前端
- [ ] Redis / PostgreSQL 端口改为仅 Docker 内网

### 🟠 P1 — 本月完成

**前端**：
- [ ] `Cmd+K` 全局命令面板（升级现有 OmniSearch）
- [ ] 右键上下文菜单 `FinancialContextMenu`（任何数据行）
- [ ] AI 副驾改为全局右侧抽屉
- [ ] 实盘模式横幅（红色脉冲，不可关闭）
- [ ] 键盘快捷键体系 `useKeyboardShortcuts`

**客户端**：
- [ ] 暗色主题 + 颜色 Token（与 Web 端严格对齐）
- [ ] WebSocket 行情接入（断连重试 + StaleOverlay）
- [ ] Kill Switch FAB（含持仓页强制显示）
- [ ] 生命周期感知（App 后台暂停 WS，防耗电）
- [ ] Android + iOS 推送通知（FCM + APNs）

**后端**：
- [ ] Futu OpenD systemd 守护进程 + asyncio Watchdog
- [ ] 统一健康检查 `/health` 和 `/ready`
- [ ] Futu API 行情订阅配额实时监控

**部署**：
- [ ] GitHub Actions 完整 CI/CD 流水线（含自动部署到节点 A）
- [ ] ghcr.io 替换 Docker Hub
- [ ] Redis + pgvector 自动备份到 Cloudflare R2
- [ ] SSH 加固（禁密码登录 + 改端口）

### 🟡 P2 — 本季度

**产品**：
- [ ] 全局命令面板 Cmd+K（股票搜索 + 功能导航 + 快速操作）
- [ ] 告警中心（价格告警 + 指标告警 + 策略信号 + Telegram 推送）
- [ ] 回测工坊完整升级（月度热力图 + 蒙特卡洛 + 参数网格搜索）
- [ ] 风控面板完整重建（因子暴露 + 归因分析 + 压力测试）

**客户端**：
- [ ] K线主图（CustomPainter，捏合缩放 + 长按十字线）
- [ ] OMS 订单管理
- [ ] AI 副驾（SSE 流 + 打字机效果）
- [ ] HarmonyOS Flutter Fork 适配 + HMS Push Kit

**AI/Agent**：
- [ ] `prompts/` 目录建立，Prompt 版本控制
- [ ] Eval 标准测试用例集（≥ 50 条）
- [ ] RAG 知识库 TTL 策略 + 自动清理
- [ ] LLM 模型版本锁定

**部署**：
- [ ] 节点 B（境外 VPS）部署 Hermes Agent + Ollama
- [ ] Cloudflare Workers 宏观数据边缘缓存
- [ ] Redis 主从复制（节点 A 主 → 节点 B 从）

### 🟢 P3 — 长期规划

- [ ] 策略版本时间线（可视化版本历史 + 一键恢复）
- [ ] Walk-Forward 滚动验证（策略衰减检测）
- [ ] 面板布局快照（保存/恢复多套工作模式）
- [ ] HarmonyOS 折叠屏 + 分布式软总线流转
- [ ] Web Vitals 监控接入 Grafana
- [ ] Flutter Isolate 并发重构（技术指标计算卸载）
- [ ] 多地域部署评估（超出个人系统需求）

---

## 六、技术栈最终确认（零偏差参考）

```
Web 终端（前端）
  框架：React 18 + Vite SPA + React Router v6（纯静态，无 SSR）
  语言：TypeScript 5+（strict: true）
  样式：Tailwind CSS v4 + tailwind-merge + clsx
  状态：Zustand（低频业务）+ useRef/Float64Array（高频行情）
  图表：Lightweight-Charts（K线）| PixiJS v8（盘口）| AG Grid（表格）| ECharts（AI生成图）
  构建：Vite | 包管理：pnpm | 部署：Cloudflare Pages

后端
  语言：Python 3.11+ (asyncio)
  框架：FastAPI + Pydantic v2 + SQLAlchemy 2.0 async
  数据：PostgreSQL 16 + pgvector | Redis 7 | DuckDB / Parquet
  任务：ZeroMQ | asyncio.to_thread | ProcessPoolExecutor
  日志：structlog (JSON) | 追踪：OpenTelemetry
  部署：Uvicorn 4 workers + Gunicorn | Docker Compose

Hermes Agent
  框架：自研 ReAct（Plan → Tool → Verify → Output）
  LLM：OpenAI GPT-4o（主）| Ollama 本地（降级）
  流式：SSE（Server-Sent Events）
  向量：pgvector（PostgreSQL 内置）

移动客户端（三端）
  框架：Flutter 3.22+ / Dart 3.4+
  平台：Android (Vulkan) | iOS (Metal) | HarmonyOS NEXT（华为 Flutter Fork）
  状态：Riverpod 2.x（代码生成）| go_router 14.x
  图表：CustomPainter + RepaintBoundary（K线）
  存储：Isar 3.x（K线缓存）| flutter_secure_storage（Token）
  推送：FCM | APNs | HMS Push Kit

基础设施（ADR-005 · 2026-07-08 更新）
  主节点（加州 38.60.126.42）：API + Worker + Redis + PostgreSQL + 境外数据源 + Futu
  辅助节点（北京）：仅 AKShare 采集器，Tailscale 内网回传
  CDN/安全：Cloudflare Pages + Tunnel + R2 + Workers（免费）
  CI/CD：GitHub Actions + ghcr.io（免费，矩阵部署 master/slave）
  监控：Prometheus + Grafana + 飞书 Webhook 告警（自建）
```

---

## 七、第三轮 Review（2026-07-12）：业界对标与结构性差距

> 本轮 Review 前提：第二轮（§四/§五）的工程基建任务已基本收口（MIG/INFRA/SEC/BE/FE 全部完成，OMS 核心闭环完成，RL 限流体系完成）。**短板已从"工程基建"转移至"产品功能闭环、数据正确性、质量门禁"三个层面。**

### 7.1 与业界成熟产品的差距矩阵

| 能力域 | 业界标杆 | 标杆核心能力 | QuantEdge 现状 | 差距等级 |
|:---|:---|:---|:---|:---:|
| **回测引擎** | QuantConnect LEAN | **回测/实盘同构**：同一份策略代码不改一行跑回测和实盘；事件驱动引擎统一 Time/Data/Order 抽象 | `backtest_engine` 与 `bot_runtime` 是两套代码路径，策略从回测到实盘需要改写 | 🔴 结构性 |
| **数据正确性** | LEAN / Norgate | **Point-in-time 数据**（财报重述前的原始值）+ **幸存者偏差处理**（含退市股票的历史全集） | 复权/时区已做（BE-16），但历史数据只有当前存续标的，财务数据无 as-of 语义 → **回测结果系统性偏乐观** | 🔴 结构性 |
| **告警引擎** | TradingView Alerts | 服务端常驻告警：价格/指标/自定义脚本条件，秒级触发，多通道送达，年可用性 99.9% | `docs/01 §十` 设计完整，**代码与任务均为零**；仅有运维侧 Grafana 告警 | 🔴 功能缺失 |
| **策略研发 IDE** | QuantConnect / TradingView Pine | 云端 IDE + 版本管理 + 一键部署 + 社区脚本库 | `docs/01 §四` 设计完整（Monaco + AI Diff + Auto-Debug），**无任务承接**，现状是单文件 strategy.tsx | 🟠 设计未落地 |
| **回测报告深度** | QuantConnect / PyFolio | Tear Sheet + Walk-Forward + 参数寻优热力图 + 过拟合检测（PBO / Deflated Sharpe） | 手动循环沙箱统计；QUANT-01 (VectorBT) 长期滞留 P3 | 🟠 深度不足 |
| **模拟盘追踪** | QuantConnect Paper Trading | Paper trading 长期绩效档案：策略实盘前必须有 N 个月纸面记录 | 沙箱可单次推演，但**无持续运行的纸面组合与绩效归档** | 🟠 功能缺失 |
| **组合风险** | Bloomberg PORT | 多因子模型归因 + 压力测试 + 流动性评估 | Risk MVP 已上线（六维雷达/分账户），RISK-01~08 进阶未做，Beta/流动性仍是占位值 | 🟡 进行中 |
| **NLP 选股** | 问财 | 自然语言 → DSL → 结果解释链路成熟 | 已具备（screen_stocks 自然语言直传），属对齐项 | 🟢 已对齐 |
| **移动端体验** | moomoo/富途牛牛 | 三端 App + 推送 + 生物识别下单 | **代码零进展**（CLI-01~06 全空），且框架决策被 CLI-07 重开 | 🔴 落地为零 |
| **高可用** | 机构级标配 | 主备切换 / 多活 | 加州单主节点，宕机即全停；北京节点无接管能力 | 🟡 个人系统可接受，需最低限度 DR |

### 7.2 三个结构性改进方案（按投入产出排序）

**方案一：回测/实盘同构引擎（对标 LEAN，最高价值）**

```
现状：策略代码 ──(回测)──> backtest_engine.py（手动循环）
      策略代码'──(实盘)──> bot_runtime.py（另一套 API）

目标：策略代码 ──> 统一 StrategyContext 抽象（on_bar/on_tick/order API）
                    ├─ BacktestDriver（历史数据回放，VectorBT 加速）
                    └─ LiveDriver（Redis 行情流 + OMS 真实下单）
```

策略只写一次，通过 Driver 注入决定跑回测还是实盘。这是消除"回测很好、实盘翻车"的过拟合温床的前提，也让 Screen-to-Backtest-to-Live 闭环成为可能。**建议在 QUANT-01 引入 VectorBT 时一并设计，避免二次返工。**

> 📐 **2026-07-12 设计已完成**：详见 `docs/15. 回测实盘同构引擎设计.md`（V1.0，含 QUANT-01 合并设计、六个子任务拆分 BT-01a~f 与评审清单），待评审后实施。

**方案二：数据正确性补课（Point-in-time + 幸存者偏差）**

- 历史标的全集：K线数据湖补充已退市标的（Futu/YFinance 可取），回测标的池按"当日实际存续"生成
- 财务数据 as-of：财报数据存储加 `announce_date`，回测时只允许读取"当时已公布"的数据
- 数据快照版本化：回测报告绑定数据湖快照版本，保证可复现
- 这三项不做，所有回测收益率都有系统性高估，机构级绝不允许

**方案三：告警中心作为独立子系统（对标 TradingView Alerts）**

- 后端 `alert_engine` worker：订阅 Redis 行情流，规则匹配（价格穿越/指标阈值/策略信号），触发写入 `alerts` 表 + 多通道推送（应用内 WS / 飞书 / Telegram）
- 前端告警中心页面 + 规则 CRUD（`docs/01 §十` 布局已设计好）
- 这是从"盯盘工具"到"无人值守系统"的分水岭功能，也是移动端存在的核心理由（推送）

### 7.3 质量与治理红线（本轮新发现）

| # | 问题 | 证据 | 处置 |
|:---|:---|:---|:---|
| 1 | **覆盖率门禁静默降级** | TEST-13 从"后端 ≥70% / 前端 ≥60%"改为"≥5% / ≥10%" | 门禁数字必须走 ADR 流程变更；新增任务恢复爬坡机制（每月 +5%） |
| 2 | **SVC-01~07 全部未动** | 数据源契约测试/拨测/数据质量校验零进展，而系统 100% 依赖外部数据 | SVC-04（数据质量）提级为 P1，与 DIST Phase 3 部署并行 |
| 3 | **ADR-002 被 CLI-07 重开** | Flutter 三端决策后 0 行代码，又新增"对比 Tauri Mobile"任务 | 限期两周做完 CLI-07 决策收口，写 ADR-006 终审；决策悬置比选错更伤 |
| 4 | **doc 01 路线图与 TODO.md 双轨** | doc 01 §十二 的 P0 清单与 TODO.md 各自维护，多数已完成项在 doc 01 未勾选 | doc 01 路线图改为指针，唯一任务清单收口到 TODO.md |
| 5 | **加州主节点单点** | ADR-005 后北京仅剩采集，无 API/DB 接管能力 | 最低限度 DR：R2 备份异地可恢复演练 + 北京节点冷备启动脚本（不追求热备） |

### 7.4 本轮新增任务序列（详见 `docs/TODO.md`）

| 序列 | 主题 | 优先级 | 对标 |
|:---|:---|:---:|:---|
| `ALERT-01~05` | 告警中心子系统（引擎/规则CRUD/多通道/前端页面/移动推送）📐 ALERT-03 设计已完成 → `docs/18` | P1 | TradingView Alerts |
| `BT-01~06` | 回测引擎升级（同构抽象/VectorBT/Walk-Forward/蒙特卡洛/网格寻优/过拟合检测）📐 BT-01 设计已完成 → `docs/15` | P1~P2 | QuantConnect LEAN |
| `DQ-01~04` | 数据正确性（退市标的全集/财务 as-of/数据快照版本化/质量看板）📐 DQ-03 设计已完成 → `docs/19` | P1 | LEAN / Norgate |
| `STRAT-01~05` | 策略实验室落地（IDE 骨架/AI Diff/版本时间线/Auto-Debug/参数面板）📐 设计已完成 → `docs/16` | P2 | QuantConnect IDE |
| `PT-01~02` | 纸面组合追踪（常驻 paper trading + 绩效档案）📐 设计已完成 → `docs/17` | P2 | QC Paper Trading |
| `GOV-01~03` | 质量治理（覆盖率爬坡/门禁变更走 ADR/CLI-07 决策收口） | P0 | — |
| `SEC-14~16` | 安全红线补漏（Redis/PG 端口收敛 + SSH 加固） | P0 | — |
| `DOC-04~05` | 文档治理（doc 01 收口 + 北京冷备脚本） | P1 | — |

### 7.5 质量门禁变更 ADR（GOV-02 落地）

> **规则**：覆盖率门槛、lint 规则豁免、CI 必过项的任何放宽必须在此记录 ADR，禁止在配置文件中静默修改。

#### ADR-COV-01：覆盖率门禁静默降级与恢复计划

- **日期**：2026-07-12
- **状态**：已批准
- **背景**：TEST-13 覆盖率门禁从「后端 ≥70% / 前端 ≥60%」静默降至「后端 ≥5% / 前端 ≥10%」，未走任何决策流程。原因：工程基建期大量代码迁移（MIG/SEC/BE），测试未同步补齐，为避免 CI 阻塞临时下调。
- **决策**：
  - 承认临时降级的合理性（工程基建期优先保证功能落地）
  - 但程序不合规（未记录 ADR），此后禁止
  - 启动爬坡计划：每月 +5%，2026-12 恢复至后端 ≥70% / 前端 ≥60%
- **爬坡时间表**：

| 月份 | 后端目标 | 前端目标 |
|:---|:---:|:---:|
| 2026-07 | 40% | 15% |
| 2026-08 | 45% | 20% |
| 2026-09 | 50% | 25% |
| 2026-10 | 55% | 35% |
| 2026-11 | 60% | 45% |
| 2026-12 | 70% | 60% |

- **恢复期限**：2026-12-31 前必须达标，届时未达标则阻断合并（`informational: false`）
- **变更流程**：此后任何门禁调整必须在此表格记录 ADR，包含原因 + 恢复期限 + 审批人

---

## 八、文档更新记录

| 日期 | 文档 | 版本 | 主要变更 |
|:---|:---|:---|:---|
| 2026-07-13 | `docs/06. 工程化配置与部署方案.md` | V9.0 | 四节点：US-MASTER + US-YF-A/B + CN-AKSHARE；Tailscale ACL；YF 双 IP 抗限流 |
| 2026-06-27 | `AI_INSTRUCTIONS.md` | V3.0 | 前端栈确认 Vite SPA；客户端栈更新为 Flutter 三端 |
| 2026-06-27 | `.cursor/rules/vibe-coding.mdc` | V2.0 | 框架更新；MVVM Clean Architecture 数据分层 |
| 2026-06-27 | `docs/02. Vibe Coding与AI工程规范.md` | V3.0 | 完整重写：YAGNI + 测试规范 + 日志规范 + 技术栈 |
| 2026-06-27 | `docs/03. 后端架构与执行引擎.md` | V3.0 | 完整重写：三通道隔离 + K线管道 + 安全分级 + Hermes 集成 |
| 2026-06-27 | `docs/04. 前端架构与零GC渲染.md` | V3.0 | 完整重写：布局体系 + 视觉规范 + 交互完整性 + 错误处理 |
| 2026-06-27 | `docs/05. 客户端架构与Tauri壳资源.md` | V3.0 | 完整重写：Flutter 三端（Android/iOS/HarmonyOS）+ APM 监控 |
| 2026-06-27 | `docs/06. 工程化配置与部署方案.md` | V3.0 | 完整重写：Cloudflare 免费体系 + 双节点拓扑 + 完整 CI/CD |
| 2026-06-27 | `docs/07. 子系统架构速查手册.md` | V1.1 | 客户端层更新为 Flutter 三端 |
| 2026-06-27 | `docs/08. 日志与可观测性规范.md` | V1.0 | 新增：structlog 后端 + logger.ts 前端 + Grafana 看板 |
| 2026-06-27 | `docs/09. 性能测试规范.md` | V1.0 | 新增：SLO 基准 + pytest-benchmark + Locust + Lighthouse |
| 2026-06-27 | `docs/subsystems/*/architecture.md` | V1.0 | 新增：前端/后端/Agent/部署/客户端 5 个子系统速查文档 |
| 2026-06-27 | `docs/ARCHITECTURE_REVIEW.md` | V1.0 | 初始架构审计：ADR-001 前端框架决策；P0/P1 待办清单 |
| 2026-06-27 | `docs/PRODUCT_UI_REVIEW.md` | V1.0 | 初始产品 UI 审计：信息架构重设计；逐页功能深度优化 |
| 2026-06-27 | `docs/MASTER_REVIEW.md`（本文件）| V2.0 | 统一汇总所有 Review 结论；全工程 P0 漏洞清单；技术栈最终确认 |
| 2026-07-12 | `docs/MASTER_REVIEW.md`（本文件）| V3.0 | 第三轮 Review：补记 ADR-004/005；新增 §七 业界对标差距矩阵 + 三大结构性改进方案（同构引擎/数据正确性/告警中心）+ 质量治理红线；评分更新（客户端↓、前端↑、新增数据正确性/质量工程维度） |
| 2026-07-12 | `docs/01. 产品功能与UIUE架构.md` | V2.1 | §十二 路线图完成状态同步 + 收口至 TODO.md；新增 §十二.5 业界能力差距对标 |
| 2026-07-12 | `docs/TODO.md` | — | 新增 GOV/ALERT/BT/DQ/STRAT/PT 六个任务序列；SVC-04 提级 P1；执行焦点更新 |
