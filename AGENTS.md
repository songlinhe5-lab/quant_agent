# Quant Agent — 跨 IDE 编码宪法

> **受众**：Cursor / Claude Code / Codex / Copilot 等**写仓库代码**的 Agent。
> **不是**盘中交易主脑。Hermes 运行时指令：`prompts/system/HERMES.md`。
> **版本**：V3.0（2026-08-17）| 冲突时以本文件为准；Cursor 适配器 `.cursor/rules/vibe-coding.mdc` 不得另立规则。
> **体积上限**：本文件保持 ≤500 行。细节按 §8 按需加载，禁止把 `docs/02. Vibe Coding与AI工程规范.md`/`AI_INSTRUCTIONS.md` 整本灌进上下文。

你是本仓库的编码 Agent：先 Grep 证明符号存在，再最小 diff。不要扮演华尔街毒舌主脑。

---

## 0. 加载规则

- 本文件是跨 IDE 的 **L0 SSOT**。已在上下文中则不要再 Read 一遍。
- Cursor 另注入 `.cursor/rules/vibe-coding.mdc`（指针 + fail-safe）。冲突 → 本文件。
- **禁止默认加载**（即使文件名很像指令）：`AI_INSTRUCTIONS.md`（L4 空壳）、`MEMORY.md`（会话笔记）、`docs/TODO-backend.md`、`docs/VIBE_CODING_COMMIT_RULES.md`。`docs/02. Vibe Coding与AI工程规范.md` 为单文件（约 940 行），**禁止整本灌入，仅按具体章节单节加载**（见下"什么问题读哪节"）：
  - 加载规则 / SSOT 层级 → **§0**
  - 反过度设计 / Clean Architecture / 少写代码 → **§2.3**
  - 禁止事项速查（Vibe Coding 独有红线）→ **§7**
  - 日志规范（print 禁令）→ **§6.1**（通用红线见本文件 §7）
- 操作流程在 `docs/02. Vibe Coding与AI工程规范.md`，按上表章节单节加载，禁止整本 940 行。
- 自动排除：遵守仓库根 `.aiexclude`（`node_modules/`、`.venv/`、lock、`data/`、日志、密钥）。

### 0.1 文档别名索引（按需加载入口）

下文 §2 / §8 用 `docs/NN` 简写引用，Agent 须**先查此表拿真实路径**再 `read_file` 具体章节。文件名形如 `docs/NN. 中文名.md`（`数字. ` 点+空格+中文），`search_file docs/NN*` 全局 glob 不可靠，务必用本表或 `search_file` 在 `docs/` 目录内按 `NN*` 查。

| 简写 | 真实文件 |
|:---|:---|
| docs/01 | docs/01. 产品功能与UIUE架构.md |
| docs/02 | docs/02. Vibe Coding与AI工程规范.md |
| docs/03 | docs/03. 后端架构与执行引擎.md |
| docs/04 | docs/04. 前端架构与零GC渲染.md |
| docs/05 | docs/05. 客户端架构与Tauri壳资源.md |
| docs/06 | docs/06. 工程化配置与部署方案.md |
| docs/07 | docs/07. 子系统架构速查手册.md |
| docs/08 | docs/08. 日志与可观测性规范.md |
| docs/09 | docs/09. 性能测试规范.md |
| docs/10 | docs/10. API接口规范.md |
| docs/11 | docs/11. 数据模型与领域设计.md |
| docs/12 | docs/12. 运维手册与应急预案.md |
| docs/13 | docs/13. 质量评估体系.md |
| docs/14 | docs/14. 分布式数据源服务架构.md |
| docs/15 | docs/15. 回测实盘同构引擎设计.md |
| docs/16 | docs/16. 策略实验室完整架构.md |
| docs/17 | docs/17. 纸面组合系统架构.md |
| docs/18 | docs/18. 多通道推送路由设计.md |
| docs/19 | docs/19. Parquet数据湖快照版本化设计.md |
| docs/20 | docs/20. 前端视觉设计规范.md |
| docs/21 | docs/21. 专家团多智能体协作系统.md |
| docs/22 | docs/22. Agent 工具链稳定性保障体系.md |
| docs/23 | docs/23. 业务数据源聚合Facade设计.md |
| docs/24 | docs/24. 因子研究平台架构设计.md |
| docs/25 | docs/25. 执行质量分析架构设计.md |
| docs/26 | docs/26. 事件驱动研究架构设计.md |
| docs/27 | docs/27. 组合风险模型架构设计.md |

---

## 1. 技术栈（零偏差）

**前端（纯 Vite SPA，禁止 Next.js）**

| 项 | 锁定 |
|:---|:---|
| 框架/路由/构建 | React 18 Hooks + React Router v6 + Vite + TS `strict` |
| 布局 SSOT | `DashboardLayout` + `App.tsx`（禁止平行路由入口） |
| 样式/组件 | Tailwind + tailwind-merge + shadcn/ui + Radix + lucide-react |
| HTTP / 实时 | `@/lib/api-client`（原生 fetch）/ 原生 WS + SSE |
| 状态 | Zustand（低频）+ `useRef`/TypedArray（Tick） |
| 包管理 | **仅** pnpm（禁止 package-lock / yarn.lock） |

运行时：`main.tsx → AuthProvider → App.tsx`；页面在 `features/`；壳在 `components/layout/`；`components/ui/` 禁止业务逻辑。

**后端**

Python 3.11 + FastAPI + Pydantic v2 + SQLAlchemy 2.0 async + Redis + PostgreSQL/pgvector + DuckDB/Parquet。包管理 uv。日志 structlog，禁止 `print()`。

**Hermes（改 `hermes_agent/` 时）**

自研 ReAct：`Plan → Tool → Verify → Output`。SSE 传思维链，禁止用 WS。主模型 `deepseek-v4-flash`（`LLM_MODEL`）。

**移动端**：Flutter 三端（Android / iOS / HarmonyOS），独立仓 `client/flutter_app/`，详规 `docs/05`。禁止在本仓复活 Tauri/Swift/Kotlin 平行客户端。

**禁止引入**：Next.js/Nuxt/任意 SSR；Vue/Pinia；Redux/MobX；Axios；K 线主图用 ECharts；新代码 `recharts`/`victory`/`nivo`（分析图用 ECharts；存量 recharts 只许删）。

---

## 2. 架构边界

```
外部 API  →  仅 data_subservice（及 workers 采集）
         →  DataSourceRouter / Registry HTTP+HMAC
         →  Facade / 后端 API
         →  前端 · Flutter · Hermes Tools
```

- 主服务镜像**不得**安装 `futu-api` / `yfinance` / `akshare` 等数据 SDK；禁止 `from futu import`。
- 前端 / 移动端 / Hermes Tools **禁止**直连外部数据源；Tools 只打内网后端。
- `routers/` 只做校验与转发，业务在 `services/`。
- 禁止 async 路由里同步阻塞：用 `asyncio.to_thread` 或进程池。
- 密钥与连接串只从环境变量读取，禁止硬编码、禁止提交 `.env`。

数据源细则：按任务**单章**加载——框架接口 `docs/14` §2 / Facade 层 `docs/14` §2.5 / 熔断降级 `docs/14` §5.4 / HMAC 签名 `docs/14` §6.3 / 限流退避 `docs/14` §12 / 扩展新源 `docs/14` §9；业务聚合 `docs/23` §二·§3（现状审计 SSOT 见 `docs/23` §八）；部署拓扑 `docs/06` §一·§1.5。拓扑：US-MASTER + US-YF-A/B + CN-DATA；Yahoo 不得集中单 IP。主服务经 `DataSourceRouter.fetch_*()`，OpenD 仅主节点 `data_subservice` 持有。

**部署踩坑（写 compose / 连 OpenD 时必看）**：容器访问宿主服务用 Tailscale IP，禁止写死 docker0/`172.17/172.19` 网关。Futu OpenD 是唯一例外：须监听 `0.0.0.0:11111`（禁止改回 `127.0.0.1`），容器内 `FUTU_HOST=host.docker.internal`。端口不对公网暴露。健康检查分级：`/health/live` 不依赖数据源；`ready` 才查 Redis/PG/数据源。

---

## 3. 前端铁律

| 场景 | 必须 | 禁止 |
|:---|:---|:---|
| K 线 / 分时 | Lightweight-Charts | ECharts、Recharts |
| Level 2 盘口 | PixiJS v8 | DOM 节点墙 |
| >1000 行列表 | AG Grid | 原生 table |
| 热力 / AI 图 / 归因 | ECharts | PixiJS |
| 实时数字 | `useRef` + DOM 突变 | `useState` 存 Tick |

零 GC：Tick 禁止进 React 状态；高频数组用 TypedArray；>1000 条计算进 `frontend/workers/`。

STALE：断连或超时必须显示 `text-amber-500` 的 STALE 标签，区域 `opacity-60 saturate-50`，禁止无标注地展示过期数。

颜色：涨 `text-emerald-400`；跌 `text-red-400`；警告 `text-amber-500`；背景 `bg-gray-900`。

PROD 禁止注入 mock（仅 `import.meta.env.DEV && VITE_ENABLE_MOCK==='true'`，且须 `DEMO · 假数据` 角标）。后端禁止用假数据凑界面。空态/初始化必须可见，禁止白屏：

| 用途 | 组件 |
|:---|:---|
| 初始化 | `components/ui/data-display/InitOverlay.tsx` |
| 空页面 | `components/ui/data-display/EmptyState.tsx` |
| 数据源+时间 | `components/ui/data-display/DataSourceBadge.tsx` |

**行数（硬顶；接近上限先拆，禁止继续塞）**：ui 原子 80 / 分子 150 / feature 页 250 / hook 100 / store slice 120 / router 100 / service 200 / worker 250。任何文件禁止 >1000 行；说不清类型时软顶 300。

---

## 4. 后端铁律

- API 统一 `{status, message, data, timestamp}`；错误带 `error_code`。
- 新接口先写 Pydantic 模型再写路由。
- Futu 百分比传小数：ROE 15% → `0.15`，禁止传 `15`。
- 实盘函数必须先查 `REAL_TRADE_EXECUTE`（默认 false）；未开则沙箱返回，不发单。UI 必须显示 SANDBOX / LIVE 横幅。
- ZeroMQ 用 msgpack，`LINGER=0`。
- 限流（`rate_limit` / `quota_exhausted` / `ip_blocked`）**不计入**熔断失败计数；退避期内禁止硬重试。
- `/api/v1/health` 不得依赖数据源；分级见 `live` / `ready` / `deep`。
- 主 app 只经 `DataSourceRegistry.fetch`；禁止业务层 `yf.Ticker()` / `futu_client.get_quote()`。

---

## 5. 改 Hermes 代码时

- Tools 禁止直连外网；走后端 HTTP。
- 数字类输出必须来自 Tool；失败须明示，禁止估计值。
- 同一 Tool 连续失败 3 次必须熔断并报告（名 / 原因 / 建议检查项）。
- 运行时人设与早报模板在 `prompts/system/HERMES.md`，不要把编码铁律写进那份 prompt。

---

## 6. 工程

**测试**：改业务逻辑必须同 PR 带测；禁止单测打真实 Redis/PG/Futu/外网。

**Git**：`feat|fix|perf|docs|refactor|test(scope): 说明`。一条 commit 一个目的；建议 <200 行，硬顶 500 行；禁止 SuperCommit（>15 文件或 >1000 行）。配置/CI 与业务代码分开提交。禁止 force-push `main`。主干：`develop` ← `main`（仅 develop→main 的 PR）。开发从 `develop` 拉分支。

**Docker**：必须 healthcheck；生产镜像禁止 `:latest`。

**日志**：structlog / 前端 `logger`；级别 DEBUG/INFO/WARNING/ERROR/CRITICAL 语义见 `docs/02. Vibe Coding与AI工程规范.md` **§6.2**。

**Ponytail（少写代码）**：先问是否已有 helper / 标准库 / 现有依赖。不造未要求的抽象。修 Bug 改共享根因，不要每个调用方加一层 guard。复杂逻辑留一个可运行检查。

---

## 7. 红线速查（前端图表/状态/Tick 等详见 §3，后端 API/实盘等详见 §4）

| 禁止 | 替代 |
|:---|:---|
| Vue / Next / Axios | React / Vite / fetch |
| 路由里同步阻塞 / 写业务 | `to_thread` / `services/` |
| 各模块直连外部 API | Gateway / data_subservice |
| 无 `REAL_TRADE_EXECUTE` 实盘 | 先检查环境变量 |
| 提交 `.env` | gitignore |
| 生产 `:latest` | 精确版本 tag |
| ZeroMQ 用 JSON | msgpack |
| `print()` | structlog |
| 裸 `except:` | 具名异常 |

---

## 8. 按需加载（禁止开场灌整库）

> `docs/NN` 简写 → 真实文件见 **§0.1 文档别名索引**。加载时按右侧章节定位，禁止整本灌入。

| 任务 | 再读 | 不要读 |
|:---|:---|:---|
| 修 Bug | 目标文件 + 对应 test + 1 个调用方 | 全目录、`*.log`、lock |
| 新 Router | 同类 router 1 个 + service/schema | 技术栈散文、无关 docs |
| 新 UI | `features/<domain>/` 1 个参考组件 + store slice | `node_modules/`、全量 docs |
| 数据源/Facade | `docs/23` §二·§3（三层边界）/ `docs/14` §2.5（Facade 层）单章 + TODO 条目 | 03+04+06+14 一起灌 |
| 前端渲染 | `docs/04` §2（布局）/ §3.1（颜色）/ §3.6（空状态）/ §6（零 GC）/ §4.6（WS 断连） | `HERMES.md` 早报模板 |
| 部署 | `docs/06` §一（拓扑）/ §1.5（Tailscale）/ §3.2（CI/CD）/ §四（采集器） | |
| SOP / 冻结区 | `docs/02. Vibe Coding与AI工程规范.md` **§0**（加载规则）/ **§2.3**（反过度设计+Clean Arch）/ **§7**（禁止事项速查） | `docs/02. Vibe Coding与AI工程规范.md` 全文、`AI_INSTRUCTIONS.md`、`MEMORY.md` |

不确定路径时：**先 Grep，再 Read**。单次任务涉及文件 >5 先拆或等人确认。
