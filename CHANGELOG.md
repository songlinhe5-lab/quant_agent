# CHANGELOG

所有重大版本变更、架构决策（ADR）与功能里程碑均记录于此。  
格式遵循 [Keep a Changelog](https://keepachangelog.com/)，版本语义参考 [Semantic Versioning](https://semver.org/)。

---

## [Unreleased] — 开发中

### Added
- `docs/10. API接口规范.md` — REST/WebSocket/SSE/内部 Tool API 完整契约文档
- `docs/11. 数据模型与领域设计.md` — 领域对象、PostgreSQL Schema、Redis Key 命名规范
- `docs/12. 运维手册与应急预案.md` — 生产 VPS 日常运维与故障应急 Runbook

---

## [0.3.0] — 2026-06-27 · 文档系统 V3.0 全面重写

### Changed (Breaking)
- **ADR-001**: 前端框架从 Next.js App Router 切换为 **Pure Vite SPA (React 18+)**。  
  原因：量化看板核心诉求是高频 WebSocket 渲染，RSC 模型与重客户端状态架构背道而驰。
- **ADR-002**: 客户端从 Tauri + Swift/Kotlin/ArkTS 切换为 **Flutter 统一三端（Android/iOS/HarmonyOS NEXT）**。  
  原因：单一代码库，降低跨平台维护成本，Impeller 渲染引擎满足 60fps K线要求。
- **ADR-003**: 部署架构升级为 **双 VPS（香港 + 国际）+ Cloudflare 边缘节点** 分布式方案。  
  原因：充分利用 Cloudflare 免费资源（Pages/Tunnel/R2/Workers），隔离核心执行能力与 AI 推理能力。

### Added
- `docs/02.` V3.0：Vibe Coding 工程规范，增加单文件行数约束、原子化组件、Test-Alongside 标准
- `docs/03.` V3.0：后端架构，增加三通道 API 隔离、JWT+HMAC 双层鉴权、K线三级缓存、Hermes Agent 集成协议
- `docs/04.` V3.0：前端架构，增加 TradingDashboard Keep-Alive 模块切换、零GC数据管道、StatusBar、三级 Error Boundary
- `docs/05.` V3.0：客户端架构，重写为 Flutter 三端，增加 AppMonitor APM、推送三通道、Phase 4 备选
- `docs/06.` V3.0：工程化部署，增加双 VPS 拓扑、Cloudflare 资源利用方案、Redis/pgvector 规范
- `docs/07.` 子系统架构速查手册（新建）
- `docs/08.` 日志与可观测性规范（新建）
- `docs/09.` 性能测试规范（新建）
- `docs/subsystems/*/architecture.md` 五大子系统速查文档（新建）
- `docs/MASTER_REVIEW.md` 架构审计总报告（新建）
- `AI_INSTRUCTIONS.md` V3.0 全面重写（Vibe Coding 指导规范）
- `.cursor/rules/vibe-coding.mdc` Cursor 规则文件（新建）

### Removed
- `docs/backend.md` — 已过时，内容迁移至 `docs/03.`（删除）
- `docs/frontend.md` — 已过时，内容迁移至 `docs/04.`（删除）

---

## [0.2.0] — 2026-06-15 · 功能扩展规划

### Added
- `docs/TODO.md` V1.0：初始功能 TODO 列表（VectorBT、Qlib、多模态等进阶方向）

### Changed
- 选股器增加自然语言 DSL 解析能力
- Screen-to-Backtest 一键流程打通

---

## [0.1.0] — 2026-06 · 初始系统搭建

### Added
- 基础项目结构：`backend/` + `hermes_agent/` + `tools/` + `frontend/`
- FastAPI 基础接口：行情查询、选股、Agent SSE 推流
- Hermes Agent ReAct 推理引擎（自研）
- Tools 集合：`get_broker_market_data`、`get_fundamental_data`、`get_macro_news` 等 14 个工具
- 基础 React 前端：行情看板、Agent 对话界面
- Docker Compose 本地开发环境
- `docs/01.` 产品功能与 UI/UX 架构
- `AGENTS.md` 主脑 Agent 系统指令
- `docs/README.md` 系统总体概览

---

## 版本号规范

```
主版本.次版本.修订号
│      │      └── Bug 修复、文档修正、配置调整
│      └────────── 新功能、新文档、非破坏性变更
└───────────────── 破坏性架构变更（ADR 级别）
```
