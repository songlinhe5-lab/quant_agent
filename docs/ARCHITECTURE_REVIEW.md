# 🏛️ Quant Agent 全栈架构深度审计报告 & 全面 TODO 清单

> **审计基准**：对标 QuantConnect、TradingView、Bloomberg Terminal 等业界头部量化系统  
> **审计范围**：产品设计、AI工程规范、前后端架构、工程化部署、安全性  
> **审计时间**：2026-06-27  
> **文档状态**：V1.0 — 架构现状评估与改进路线图

---

## 一、架构总体评分与核心优势

| 维度 | 评分 | 优势摘要 |
|:---|:---|:---|
| 产品设计完整度 | ⭐⭐⭐⭐☆ | 四大业务域清晰，多端覆盖策略完备，路线图有演进阶段 |
| AI 工程规范 | ⭐⭐⭐⭐☆ | AGENTS.md 人设定位与工具矩阵是业界少见的工程级规范 |
| 前端架构设计 | ⭐⭐⭐⭐⭐ | 多级渲染分层（ECharts/LW-Charts/PixiJS/AG Grid）设计极为先进 |
| 后端架构设计 | ⭐⭐⭐⭐⭐ | 节点化+ZeroMQ+Redis 总线+DuckDB 混合存储，设计已达机构级 |
| 工程化部署 | ⭐⭐⭐☆☆ | Docker Compose 骨架完整，但安全加固、回滚、监控规范缺失 |
| **整体评估** | **领先业界个人系统** | 架构设计超越大多数开源量化框架，但文档与实现之间存在几处关键偏差 |

---

## 二、🏗️ 已定架构决策（Architecture Decision Records）

> 以下决策已最终确定，后续 Vibe Coding 及代码审查均以此为基准，不再重复讨论。

### ADR-001：前端框架选型 — 纯 Vite SPA，放弃 Next.js

| 维度 | 纯 Vite SPA（已选） | Next.js App Router（已排除） |
|:---|:---|:---|
| **渲染延迟** | WebSocket Tick → Zustand → Canvas，无服务端往返 | RSC 网络边界序列化增加不必要开销 |
| **核心组件兼容性** | 原生支持 Canvas/WebGL，无心智负担 | 所有图表/WS 组件必须加 `'use client'`，RSC 优势全失 |
| **部署成本** | 纯静态文件 → Nginx / Cloudflare Pages，零 CPU | 必须维护 Node.js 进程，高并发下难以精细管理内存 |
| **扩展性** | 浏览器内性能调优（内存泄漏、重绘）完全可控 | 引入服务端状态与客户端状态的同步复杂度 |
| **适配理由** | 量化看板：长期挂机、重客户端状态、无 SEO 需求 | 适合内容站点、电商、需要首屏秒开+SEO 的场景 |

**结论**：移除 Next.js，迁移至 React Router v6 + Vite 构建链。

---

## 三、🚨 紧急修复项（Critical — 影响架构一致性）

### 2.1 技术栈矛盾：Vue 3 vs React/Next.js

**问题描述**：`AI_INSTRUCTIONS.md`（实际约束 AI 编码的文件）声明前端为 **Vue 3**，而 `docs/02` `docs/04` 规定为 **React 18+**，实际代码目录存在 `next-env.d.ts`、大量 `.tsx` 文件，说明实现层已是 **React / Next.js**。三个地方三套说法，导致 AI Vibe Coding 时随机生成 Vue 或 React 代码，污染代码库。

- [ ] **立即将 `AI_INSTRUCTIONS.md` 的前端技术栈全面更正为 React 18 + Next.js + TypeScript**
- [ ] **确认前端框架最终选型**（纯 Vite SPA 还是 Next.js App Router），并在 README、docs/04、AI_INSTRUCTIONS.md 三处保持一致
- [ ] **在所有文档中删除对 Vue 的引用**（包括 `docs/04` 中误写的「Vue 的响应式追踪系统」）
- [x] ~~**更新 `docs/frontend.md`** 反映真实的目录结构与框架版本~~ → 该文件已废弃删除 (DOC-03)

### 2.2 Futu OpenD 部署前提缺失文档

- [x] ~~**补充 Futu OpenD 的宿主机要求文档**（不能运行在 ARM 架构 Linux 上，必须 x86）~~ → ✅ `docs/12` §八
- [x] ~~**明确 OpenD 的跨地域部署限制**（港股实盘必须低延迟香港节点，不同于数据抓取节点）~~ → ✅ `docs/12` §八

---

## 三、产品设计层 TODO（Product Design）

### 3.1 用户权限与多账户体系（当前：完全缺失）

- [ ] **账户隔离模型设计**：单机个人使用 vs 家庭/团队多账户，需明确产品边界
- [ ] **API Key 统一管理方案**：设计 Futu、LLM Provider、数据源等 API Key 的加密存储与轮换策略，而非散落在 `.env`
- [ ] **沙箱 vs 实盘的视觉防错设计**：在 UI 上用醒目的颜色标识（如橙色警告横幅）区分当前处于模拟盘还是实盘模式，防止误操作

### 3.2 告警与通知体系（当前：仅文档提及推送，无产品规范）

- [ ] **定义告警触发事件清单**：止损触发、全局熔断、持仓超限、API 断连、数据源降级等事件的推送等级与优先级
- [ ] **多通道通知路由策略**：APNs/FCM（高优先级）→ Telegram Bot（中优先级）→ 邮件（低频摘要），需设计路由降级规则
- [ ] **告警静默期（Silence Window）设计**：交易时段外的非紧急告警应合并为日报摘要，避免信息噪音

### 3.3 策略版本管理与审计追踪（当前：无）

- [ ] **策略代码版本管理**：策略每次修改必须生成版本快照（含代码哈希、修改时间、回测结果摘要），支持回滚对比
- [ ] **实盘操作审计日志**：所有 `buy/sell` 指令、参数修改、熔断触发必须落盘为不可篡改的审计日志（append-only log）
- [ ] **回测结果持久化**：Tear Sheet 完整数据（绩效曲线、指标集合）持久化至 PostgreSQL，支持历史对比分析

### 3.4 免费数据源局限性风险管理（当前：乐观假设）

- [ ] **YFinance 429 限速的自动检测与告警**：当触发 HTTP 429 时，系统须主动告知用户当前数据降级状态及恢复预计时间
- [ ] **数据质量监控**：设计数据完整性校验（如检测 Tick 序列中的异常零值、时间戳跳跃），防止脏数据污染回测
- [ ] **Futu API 行情订阅配额监控**：Futu 免费账户对实时订阅标的数量有限制，需实时显示当前配额使用率

### 3.5 产品功能优先级重新审视

- [ ] **HarmonyOS 端开发时机评估**：在 iOS/Android 端未完成 Phase 1 前，明确暂缓鸿蒙端开发，避免分散精力
- [ ] **Strategy Marketplace（策略市场）优先级降级**：个人单兵阶段不应发展社区生态，建议降至 Phase 4 或单独立项
- [ ] **Web3 链上数据优先级评估**：与量化股票的核心场景相关性较低，建议作为可选插件而非核心规划

---

## 四、AI 工程规范层 TODO（AI Engineering）

### 4.1 Prompt 版本管理（当前：散落在代码和文档中）

- [ ] **建立 `prompts/` 目录**：将所有系统级 Prompt（AGENTS.md 中的各工具 Prompt、策略生成 Prompt、报告生成 Prompt）统一纳入版本控制
- [ ] **Prompt 变更需附带 Eval 结果**：修改任何核心 Prompt 后，必须运行标准化的幻觉测试用例集并附结果提交 PR
- [ ] **Prompt 注释规范**：每个 Prompt 文件头部注明：使用场景、目标模型、输入变量、预期输出格式、最后测试日期

### 4.2 LLM 模型管理（当前：未指定版本锁定）

- [ ] **模型版本钉定策略**：在配置文件中明确锁定 LLM 模型版本（如 `gpt-4o-2024-11-20`），防止 Provider 静默升级导致的 Prompt 失效
- [ ] **多模型路由策略设计**：轻量任务（新闻摘要、指标计算）→ 快速小模型；深度研报、策略生成 → 旗舰大模型，成本与质量分级
- [ ] **本地模型降级链路**：当 OpenAI API 不可用时，自动路由至本地 Ollama（如 Qwen2.5-Coder），配置健康检测与自动切换逻辑

### 4.3 Agent Eval 评估框架（当前：仅概念提及）

- [ ] **建立标准化测试用例集（Golden Dataset）**：覆盖每个 Tool 的正常调用、边界值、数据源故障等场景，至少 50+ 用例
- [ ] **定义幻觉检测指标**：AI 输出中的数字准确率（与 Tool 真实返回值比对）、引用溯源完整率、DSL 输出格式合规率
- [ ] **每周自动 Eval 运行**：将 Eval 脚本接入 GitHub Actions，每周定时运行并生成质量报告（Eval 分数趋势图）
- [ ] **Streaming Token 计量监控**：接入 LLM Provider 的 Usage API，按 Tool 类型分类记录 Token 消耗，设置月度预算上限告警

### 4.4 RAG 知识库治理（当前：有工具但无治理规范）

- [ ] **知识库新鲜度策略**：定义各类文档的 TTL（如财报 90 天过期、新闻 7 天过期、宏观政策 30 天过期），自动触发 `delete_global_knowledge`
- [ ] **Embedding 模型版本管理**：记录向量化时使用的模型版本，模型升级时需重建全量索引（避免混合版本的向量不可比问题）
- [ ] **RAG 检索质量监控**：记录每次检索的相似度得分，低于阈值时告警并触发知识库清理流程

---

## 五、前端架构层 TODO（Frontend Architecture）

### 5.1 框架迁移：Next.js → 纯 Vite SPA（最高优先级）

**架构决策（已定，不再讨论）**：量化看板是重型客户端应用（毫秒级 WebSocket 渲染 + Canvas/WebGL 图表），不需要 SEO 或首屏秒开。Next.js App Router 的 RSC 模型与此背道而驰：所有核心组件都需 `'use client'`，RSC 优势全部丧失，同时引入 Node.js 运行时部署成本。**最终选型：React 18 + Vite SPA + React Router v6**，打包为纯静态文件由 Nginx/Cloudflare Pages 托管，零服务端运行时开销。

- [ ] **从 `frontend/` 中移除 Next.js 依赖**：卸载 `next`、`@next/*` 包，删除 `next.config.*`、`next-env.d.ts`、`.next/` 目录
- [ ] **迁移路由层至 React Router v6**：将 `frontend/src/app/` (App Router 约定) 重组为标准 `src/pages/` + `src/router/` 结构
- [ ] **迁移构建配置至纯 Vite**：创建 `vite.config.ts`，配置 `@vitejs/plugin-react`、路径别名、后端代理（替代 Next.js `rewrites`）
- [ ] **统一包管理器**：根目录存在 `yarn.lock` 和 `pnpm-lock.yaml` 两个锁文件，选一删一，统一为 `pnpm`
- [ ] **`node_modules` 不应在根目录**：检查根目录 `node_modules` 是否为误装，前端依赖统一在 `frontend/` 下管理

### 5.2 性能规范文档化（当前：有规范但未成为可执行约束）

- [ ] **建立性能预算（Performance Budget）文档**：明确首屏 LCP < 2.5s、TTI < 3.5s、行情 WebSocket 消息处理延迟 < 16ms 等硬性指标
- [ ] **接入 Web Vitals 监控**：在生产环境采集 Core Web Vitals 并推送至 Grafana（项目已有 Grafana 配置），建立前端性能基线
- [ ] **React Profiler 性能基准录制**：在引入每个高频渲染组件（Tick 行情、Order Book）后，强制录制 Profiler 快照并入库归档
- [ ] **Bundle 分析接入 CI**：在 GitHub Actions 中加入 `bundle-analyzer` 检测，PR 新增 bundle 超过阈值时自动评论警告

### 5.3 前端安全规范（当前：完全缺失）

- [ ] **CSP（Content Security Policy）配置**：禁止内联脚本、限制字体/图片来源，防止 XSS 攻击
- [ ] **API Token 存储规范**：JWT/Session Token 禁止存入 `localStorage`，必须使用 `httpOnly Cookie` 存储
- [ ] **DOMPurify 覆盖率验证**：确认所有 AI 生成的 HTML（ECharts 配置、Markdown 渲染）都经过 DOMPurify 过滤，并在 CI 中加入自动检测
- [ ] **敏感数据脱敏展示规范**：账户资金、持仓数量等敏感字段，在非「实盘聚焦」模式下应默认显示为 `***`（隐藏模式）

### 5.4 可访问性与国际化（当前：有 locales 目录但无文档规范）

- [ ] **国际化（i18n）完整规范**：确认中英文两套文案的覆盖范围，建立缺失 Key 的 CI 检测机制，防止发布时出现裸 Key
- [ ] **键盘导航规范**：交易系统中关键操作（下单、撤单、熔断）必须支持键盘快捷键，减少鼠标依赖
- [ ] **图表无障碍（a11y）支持**：K 线图、资金曲线需提供 `aria-label` 描述，确保屏幕阅读器用户可获取数据摘要

### 5.5 错误处理体系（当前：分散且不统一）

- [ ] **全局 Error Boundary 层级设计**：定义页面级、面板级、图表级三层 Error Boundary，避免单个图表崩溃导致整页白屏
- [ ] **统一的网络请求错误处理规范**：WebSocket 断连、REST 超时、SSE 中断的 UI 降级展示需要统一（`STALE` 标签、透明度降低、重连倒计时）
- [ ] **接入 Sentry 或等效崩溃收集**：前端异常上报与后端 Python 异常统一归集，支持 AI Agent 自动读取日志诊断

---

## 六、后端架构层 TODO（Backend Architecture）

### 6.1 API 规范与安全（当前：无版本管理，无认证规范）

- [ ] **API 版本化**：所有 REST 端点迁移至 `/api/v1/` 前缀，为未来 Breaking Change 预留升级通道
- [ ] **统一认证方案**：设计 JWT 认证中间件（即使个人使用，也需防止云端 VPS 上的接口被公网扫描利用）
- [ ] **速率限制器（Rate Limiter）统一规范**：对 `/sse/agent`（LLM 消耗大）、`/market/screener`（计算密集）等接口设置独立的速率限制，防止误操作拖垮服务
- [ ] **统一健康检查端点**：实现 `/health`（存活检查）和 `/ready`（就绪检查，含 Redis/PG 连通性），供 Docker 和负载均衡使用

### 6.2 可观测性（当前：有 Prometheus + Grafana 文件但无文档规范）

- [ ] **补充 `docs/07. 可观测性与监控方案.md`**：将现有的 `prometheus.yml`、`grafana/` 目录的监控体系文档化
- [ ] **定义核心业务指标（Golden Signals）**：为量化系统特化 4 个黄金信号：延迟（Tick 到 UI 端到端延迟）、流量（Tick/s）、错误率（API 失败率）、饱和度（Redis 内存使用率）
- [ ] **接入 OpenTelemetry 分布式追踪**：对跨节点的请求链路（前端 → WebSocket Gateway → Redis → Data Node → Futu OpenD）进行端到端 Trace，定位性能瓶颈
- [ ] **结构化日志规范（JSON Log）**：统一后端所有模块的日志格式为 JSON（含 `timestamp`、`level`、`service`、`trace_id`、`message`），替换当前的自由格式字符串日志

### 6.3 数据库治理（当前：缺失迁移策略）

- [ ] **引入 Alembic 数据库迁移**：建立 `backend/migrations/` 目录，所有 Schema 变更必须通过 Alembic 版本化管理，禁止手动执行 DDL
- [ ] **PostgreSQL 连接池规范**：明确最大连接数配置（与 Docker 内存限制挂钩），避免高并发时 PG 连接耗尽
- [ ] **Redis 内存淘汰策略文档化**：明确 `maxmemory-policy` 配置（推荐 `allkeys-lru`），防止 Redis 内存满后随机删除关键状态数据
- [x] ~~**DuckDB 数据湖分区策略**：定义 Parquet 文件的分区规则（按标的+日期分区），避免单文件过大影响查询性能~~ → ✅ `docs/12` §九

### 6.4 故障恢复与熔断（当前：原则有，实现缺文档）

- [x] ~~**Futu OpenD 断连恢复流程文档化**：OpenD 断线时，OMS 节点的在途订单如何处理？需定义“暂停接单 → 断线检测 → 重连 → 状态对账”的完整 SOP~~ → ✅ `docs/12` §十
- [ ] **Redis 主从或持久化策略**：当前使用单机 Redis（存在 `dump.rdb`），需明确 RDB/AOF 持久化配置，防止重启后行情缓存全丢
- [ ] **数据源降级链路测试**：建立定期演练机制，手动触发 YFinance 429 / Futu 断连，验证降级切换是否如预期工作

---

## 七、工程化与部署 TODO（DevOps & Infrastructure）

### 7.1 安全加固（当前：仅有密码建议，无系统性规范）

- [ ] **建立 `docs/08. 安全加固手册.md`**，覆盖以下内容：
  - [ ] VPS SSH 加固：禁用密码登录，仅允许 SSH 密钥认证；修改默认 22 端口
  - [ ] 防火墙规则（UFW/iptables）：明确白名单 IP 规则，Redis（6379）和 PostgreSQL（5432）仅允许 Worker 节点 IP 访问
  - [ ] Docker 网络隔离：后端服务不应暴露 Redis/PG 端口至 `0.0.0.0`，应通过 Docker 内部网络通信
  - [ ] GitHub Actions Secrets 管理：列出需要配置的所有 Secret（API Key、VPS 密码、Futu 账户信息）
- [ ] **定期密钥轮换 SOP**：定义 LLM API Key、Futu 账户凭证的轮换周期与操作步骤

### 7.2 部署可靠性（当前：有 Docker Compose 但无回滚机制）

- [ ] **蓝绿部署或滚动更新策略**：当前 `docker-compose up -d --build` 会造成短暂停机。设计零停机更新方案（至少保证 OMS 节点在更新期间不丢单）
- [ ] **部署前健康预检脚本**：`deploy.sh` 执行前自动检查：新镜像能否正常启动、数据库迁移是否成功，失败则自动回滚至上一版本
- [ ] **环境变量校验**：服务启动时自动校验所有必需的环境变量是否已设置，缺失则拒绝启动并打印清晰错误

### 7.3 国内 VPS 特殊网络适配（当前：文档完全未提及）

- [ ] **境内节点访问 GitHub / PyPI / npm 的镜像配置文档**：在 `Dockerfile` 和 `deploy.sh` 中针对国内节点自动切换为清华/阿里云镜像源
- [ ] **LLM API 的网络代理配置**：国内 VPS 访问 OpenAI API 的代理配置方案（HTTP_PROXY 环境变量）及稳定性验证
- [ ] **境外 Data Worker 节点到境内主节点的网络延迟基准测试**：不同 VPS 组合下的 RTT 测试报告，确保 Tick 数据跨节点传输延迟在可接受范围内

### 7.4 数据备份与灾难恢复（当前：完全缺失）

- [ ] **PostgreSQL 定时备份方案**：配置 `pg_dump` 定时任务（每日凌晨），将备份压缩上传至对象存储（或 GitHub Private Repo）
- [ ] **DuckDB/Parquet 数据湖备份策略**：定义历史 K 线数据的备份频率与存储位置
- [ ] **灾难恢复演练 SOP**：每季度执行一次从备份完整恢复的演练，验证恢复时间目标（RTO）是否满足要求
- [ ] **`quant_agent.db`（SQLite）的处理**：根目录存在 SQLite 文件，需明确其用途，如为遗留产物应清理，如有用途应纳入备份体系

### 7.5 CI/CD 完善（当前：仅有基础框架）

- [ ] **PR 合并检查清单强制化**：在 GitHub Branch Protection Rules 中强制要求：所有测试通过 + Lint 检查通过 + Bundle 大小检查通过，方可 Merge
- [ ] **自动化集成测试环境**：PR 合并前在 GitHub Actions 中启动完整的 Docker Compose 堆栈（含 Redis Mock / PG 测试库），运行端到端接口测试
- [ ] **依赖安全扫描**：在 CI 中接入 `pip-audit` 和 `npm audit`，自动检测已知 CVE 漏洞
- [ ] **Docker 镜像签名与分发**：生产镜像推送至 GitHub Container Registry（GHCR），Tag 规范（`vYYYY.MM.DD-{git-sha}`），禁止使用 `latest` Tag 部署实盘

---

## 八、微观结构与高频进阶 TODO（HFT Roadmap）

> 以下条目优先级为 Phase 3+，仅供路线图参考，不影响当前开发进程

- [ ] **Level 2 Order Book 重建引擎**：基于 Futu Level 2 逐笔数据，在内存中实时维护完整的买卖十档价量（价格→数量 的 Sorted Map），供 PixiJS 渲染盘口瀑布图
- [ ] **订单流失衡（OFI）因子计算**：实时计算买卖盘口净压力（OFI = Δ买量 - Δ卖量），作为短线高频入场信号
- [ ] **TWAP / VWAP 算法拆单引擎**：在 OMS 节点实现时间加权/成交量加权拆单，大单分批执行，降低市场冲击成本
- [ ] **C++ 核心模块评估时机**：当 Python 实现的 Tick 处理延迟超过 500μs 时，启动 Rust/C++ 核心重写计划

---

## 九、变更日志

| 日期 | 版本 | 更新说明 |
|:---|:---|:---|
| 2026-06-27 | V1.0 | 初始架构审计报告，覆盖产品、AI、前后端、工程化五大维度 |
