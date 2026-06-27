# QuantEdge 全工程 Review 总汇（Master Review）

> **文档定位**：本工程所有架构、产品、前后端、客户端、部署 Review 的统一入口，每次 Review 结论在此汇总。  
> **最后更新**：2026-06-27 | **版本**：V2.0  
> **详细规范**：各结论对应的完整规范见具体文档，此文件仅归档结论与待办。

---

## 一、系统全局评分（最新）

| 子系统 | 评分 | V1.0 评分 | 变化 | 核心改进 |
|:---|:---:|:---:|:---:|:---|
| 产品设计 & UI | ⭐⭐⭐⭐☆ | ⭐⭐⭐⭐☆ | → | 信息架构重设计、告警中心、Cmd+K 命令面板已规划 |
| AI 工程规范 | ⭐⭐⭐⭐☆ | ⭐⭐⭐⭐☆ | → | AGENTS.md 工具矩阵领先，Eval 框架待落地 |
| 后端架构 | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | → | V3.0 补全 K线管道、三层缓存、安全分级 |
| 前端架构 | ⭐⭐⭐⭐☆ | ⭐⭐⭐⭐⭐ | ↓ | 发现双布局并存、WS 断连无遮罩等 P0 漏洞 |
| 客户端架构 | ⭐⭐⭐⭐☆ | ⭐⭐⭐☆☆ | ↑ | Flutter 三端统一（ADR-002），架构决策大幅提升 |
| 工程化部署 | ⭐⭐⭐⭐☆ | ⭐⭐⭐☆☆ | ↑ | Cloudflare 免费资源体系 + 双 VPS 拓扑 + 完整 CI/CD |
| **整体** | **领先个人系统** | **领先个人系统** | → | 架构设计达机构级水平，文档与实现一致性大幅提升 |

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

### ADR-003：部署策略 — 双 VPS + Cloudflare 边缘

| 节点 | 选型 | 职责 | 月费 |
|:---|:---|:---|:---|
| 节点 A（香港）| 腾讯云轻量 2C/4G | Futu OpenD + Redis + PostgreSQL + FastAPI | ¥24 |
| 节点 B（境外）| Hetzner CX22 | Hermes Agent + Ollama + Grafana | ≈¥31 |
| Cloudflare 边缘 | 全部免费 | Pages + Tunnel + R2 + Workers + Access | ¥0 |

**结论**：全套月费 ≈ ¥55，对比 AWS 方案节省 85%。已更新 `docs/06` / `docs/subsystems/deployment`。

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

### 📄 doc 05 — 客户端架构（Flutter 三端）

> **详细文档**：`docs/05. 客户端架构与Tauri壳资源.md`（已完整重写为 V3.0）

**核心发现**：原四端原生方案（Tauri + Swift + Kotlin + ArkTS）对单兵开发者不可维护，已完成架构转型决策（ADR-002）。

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

> **详细文档**：`docs/06. 工程化配置与部署方案.md`（已完整重写为 V3.0）

**核心发现**：原方案只有基础 Docker Compose 骨架，缺乏安全加固、免费资源利用和完整 CI/CD。

**Cloudflare 免费资源利用（全新）**：

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

基础设施
  VPS A（香港）：腾讯云轻量 2C/4G → Futu + 核心服务（¥24/月）
  VPS B（境外）：Hetzner CX22 → AI + 监控（€4/月）
  CDN/安全：Cloudflare Pages + Tunnel + R2 + Workers（免费）
  CI/CD：GitHub Actions + ghcr.io（免费）
  监控：Prometheus + Grafana（自建）
```

---

## 七、文档更新记录

| 日期 | 文档 | 版本 | 主要变更 |
|:---|:---|:---|:---|
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
