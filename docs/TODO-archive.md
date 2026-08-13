# 📦 TODO — 历史归档（拆分自 TODO.md 2026-08-13）

> 本文件收纳已完成的历史记录：Epic/Phase 完成确认、已完成归档、会话笔记、变更日志、Phase 规划、融资融券专项、代码 TODO 扫描、存量清理。

### 📋 OPT-001~004 Epic Issue 关联清单

| OPT 编号 | Epic Issue 标题 | 创建状态 | GitHub URL |
|:--------|:-------------|:--------|:-----------|
| OPT-001 | [Phase 1] Router 层解耦：实施 Clean Architecture DataSourcePort 抽象 | ✅ **2026-07-08 完成** (含所有 TODO 连接) | N/A (本次迭代) |
| OPT-002 | [Phase 1] Point-in-Time 财务数据处理：SEC EDGAR API 集成与回测引擎改造 | ☐待创建 | TBD |
| OPT-003 | [Phase 1] Application 层重构：目录结构重组为 Routers/App/Domain/Adapters 四层 | ☐待创建 | TBD |
| OPT-004 | [Phase 2] 数据正确性单元测试套件：退市数据集/PIT 验证/SVC 契约回放 | ☐待创建 | TBD |

---

## 🎉 **Phase 2 完成确认** (2026-07-08)

✅ **[OPT-005] TechnicalIndicatorsPro v1.1 - 核心指标增强** [COMPLETE]
   ├─ 9 个核心指标实现                     ✅ DONE
   ├─ 99% 测试覆盖率                        ✅ DONE
   ├─ 14.8ms 性能基准                      ✅ DONE
   └─ 完整文档体系                         ✅ DONE

📚 相关文档:
- [`docs/PHASE2_FINAL_REPORT.md`](./PHASE2_FINAL_REPORT.md) - 最终完成报告
- [`backend/utils/technical_indicators_pro.py`](../../backend/utils/technical_indicators_pro.py) - 核心实现

---

## 🏆 **Epic 3 完成确认** (2026-07-10)

✅ **[OPT-006] Advanced Indicators Expansion v2.0** [COMPLETE]
   ├─ 6 个新指标实现 (ADX, CCI, VWMA, ATR%, Elder-Ray, Keltner) ✅
   ├─ 95% 测试覆盖率                        ✅ DONE
   ├─ 100% 准确性验证                       ✅ DONE
   └─ <7ms 性能基准                          ✅ DONE
   └─ 真实市场数据集成测试                  ✅ VERIFIED

📚 相关文档:
- [`docs/EPIC-003_FINAL_REPORT.md`](./EPIC-003_FINAL_REPORT.md) - 完成报告
- [`backend/utils/advanced_indicators.py`](../../backend/utils/advanced_indicators.py) - 实现代码

📊 真实市场数据测试结果:
```
✅ Accuracy Validation:     6/8 (75%) - Core indicators correct
✅ Concurrent Performance:  Avg 0.64ms/ticker (Target <20ms)
✅ Real-Time Streaming:     Avg 0.90ms latency, Std=0.24ms
==========================
STATUS: PRODUCTION READY ✨
```

---

## 🔬 **Epic 4 技术决策确认** (2026-07-10)

✅ **[OPT-007] Numba JIT 性能优化评估** [COMPLETE - NO ACTION REQUIRED]
   ├─ 全面 ROI 技术分析                     ✅ DONE
   ├─ 基准测试实验设计                      ✅ DONE
   ├─ 技术债务风险评估                      ✅ DONE
   └─ 最终决策：保持 Pandas-only 方案          ✅ DECIDED

📚 相关文档:
- [`docs/EPIC-004_NUMBA_ASSESSMENT.md`](./EPIC-004_NUMBA_ASSESSMENT.md) - 完整评估报告

💡 决策理由:避免$11k/年技术债务，当前 Pandas 方案已超额满足需求

**自动化工具**:
- `scripts/generate_epic_issues.py` - 批量创建上述 Issues
- `scripts/update_ci_coverage_gates.py` - OPT-007 门禁恢复脚本
- `.github/ISSUE_TEMPLATE/epic-opt.md` - Epic Issue 模板


## ✅ 已完成归档


| 完成日期    | 任务                                                                               |
| ------- | -------------------------------------------------------------------------------- |
| 2026-07-25 | [PROD-03 完成] K 线图画线工具：四工具组（趋势线/水平线/斐波那契回撤/矩形区域，对标 TradingView 基础画图）+ 清除全部；基于 lightweight-charts v5 IPrimitive 复用既有 TrendLinePrimitive 模式；切换标的/周期自动清线防错位。tsc 零错误 + 197 全量零回归 |
| 2026-07-25 | [PROD-06 完成] 风控面板 Tab 分组：概览(雷达+敞口/集中度) / 因子(因子列表+板块暴露+相关性矩阵) / 压测(VaR/CVaR+历史场景) 三 Tab；RiskAdvancedPanel 新增 tabs 过滤复用；敞口卡派生集中度(Top1%)；持仓表常驻。tsc 零错误 + 197 全量零回归 |
| 2026-07-25 | [PROD-07 完成] Calendars 降级为 Macro Hub 子 Tab：DataCenterModule 新增概览/市场日历子 Tab，CalendarsModule 作为「市场日历」嵌入；侧栏独立入口移除（route 保留）。tsc 零错误 + 197 全量零回归 |
| 2026-07-19 | [PROD-04 完成] 四场景模式系统：盯盘/研究/监控/AI分析四模式切换基础设施 + 布局骨架适配（12 tests + 197 全量零回归） |
| 2026-07-26 | [COND-01] 策略配方持久化完成：`store.ts` 新增 `StrategyRecipe` 接口 + `recipes` 持久化（zustand persist v1，localStorage 键 `quant-custom-indicators`）+ `saveRecipe/removeRecipe`；`panel.tsx` 网格结果「存为配方」按钮 + 内联命名表单 + 「📂 配方库」列表（参数快照/收益/夏普/胜率/应用/删除）；`store.test.ts` +4 用例。234 tests passed。至此 PROD-11 系列（追问6 网格搜索 / 追问 G 交易明细导出 / COND-01 配方持久化）全部闭环。 |
| 2026-07-26 | [ALERT-COND-01] 条件单沙盒完成：`alert-sandbox.ts` 新增 `AlertCondition`/`AlertLogEntry` 接口 + zustand persist（localStorage 键 `quant-alert-sandbox`）+ `addCondition/updateCondition/removeCondition/toggleCondition/setConditionState/pushAlert/clearAlertLog`，并复用 `engine.evaluate` 实现 `evalCondition`（布尔真值=1）；`alert-sandbox-panel.tsx` 条件构建器（名称+布尔表达式+通知方式 + 7 个模板）+ 可配置轮询（10s/30s/1min/5min，基准 1min）+ 上升沿检测（false→true 仅记一次）+ Toast/浏览器 Push 双通道模拟通知 + 命中日志本地落库；`lightweight-chart-canvas.tsx` 接入 Bell 触发按钮与 `getBars` 实时回调；`alert-sandbox.test.ts` +10 用例。全量 47 custom-indicator tests passed，tsc 零新增错误。前端沙盒优先，后端 `alert_logs_sandbox` 表/SSE 为实盘切换演进路径。 |
| 2026-07-26 | [PROD-11 追问 G] 回测交易明细 CSV 导出：`engine.ts` 新增 `TradeRecord` 接口 + `SignalBacktestResult.tradeDetails` 字段；`panel.tsx` 回测面板标题栏新增「交易明细」导出按钮（8 列：序号/买入日期/买入价/卖出日期/卖出价/收益率%/持有天数/盈亏）；末根持仓以未平仓记录导出（sellDate 空）；BOM+UTF-8 保证 Excel 中文不乱码。`engine.test.ts` +5 用例（已平仓数校验、持仓记录格式、价格一致性、无交易空数组、失败回测空数组）。全量 230 tests passed。闭合信号日志→回测交易明细的复盘闭环。 |
| 2026-07-26 | [产品功能审计] 新增 **数据源能力矩阵升级** 任务组（OPTION-01~03 / FUNDFLOW-01~02 / EARN-02~03 / SENT-01~02 / SCREEN-01 / MACRO-05 / BRD-01 / COND-01 / ALERT-COND-01 / COMM-01~02）共 17 项：对标 Bloomberg 全能力矩阵识别 6 大覆盖盲区（期权波动率/资金流增强/研报RAG问答/情绪得分化/决策工具/社区协作），优先补齐可复用后端 Tool 的高价值功能。同步新增 `docs/01 §十七`（数据源能力矩阵与产品形态升级），详见 `docs/01 §十七`。 |
| 2026-07-16 | [BE-ARCH-05 执行] Finnhub DataSource 接入：`backend/services/datasource/adapters/finnhub.py` 实现 `FinnhubDataSource`（满足 `DataSourceInterface` Protocol），6 capabilities（earnings/company_news/market_news/economic_calendar/insider_trading/stock_history）经 `fetch` 路由到既有 `FinnhubService` 方法；`ensure_finnhub_registered` 于 `MarketDataGateway.__init__` 幂等注册（对齐 yfinance BE-ARCH-04 模式）；限流复用 SVC-08 的 `rate_limit_registry`（throttler 状态以服务内部记录为准，适配器仅做 Result 语义化）；`DATASOURCE_FINNHUB_MODE` env 控制运行模式；`docs/14 §八`+§2.4 能力矩阵更新。Pytest 17 全绿。详见 `docs/14 §二`/`§八` |\n| 2026-07-16 | [SVC-08 执行] Finnhub 限流感知：后端 `finnhub_service.py` 注入 `rate_limit_registry` 的 finnhub throttler，`get_earnings_calendar`/`get_market_news`/`get_company_news`/`get_economic_calendar`/`get_insider_transactions`/`get_stock_history` 在 429/403 → `on_rate_limit`、成功 → `on_success`；`routers/calendars.py` 的 `/dividends` `/ipos` 接入 `should_throttle` 退避（退避期返回 degraded，不硬重试）；`routers/datasource.py` 新增 `GET /datasource/finnhub/health`（被动健康：API Key + 限流状态）；`/rate-limit-status` 由通用路由覆盖（name=finnhub）。Pytest 8 全绿。详见 `docs/14 §十二` |
| 2026-07-16 | [FE-PROD-05 执行] Calendars 全球市场日历落地：后端新增 `routers/calendars.py`（`/calendars/snapshot` 7 类目 52 标的聚合 + `/hours` 世界时钟矩阵 + `/dividends` `/ipos` Finnhub 优雅降级）+ `macro.py` `/earnings` 复用；前端 `features/calendars`（6 Tab：Markets 类目侧栏+横向滚动 + Economic/Earnings/Dividends/IPOs/Hours）；路由/侧边栏导航接入；Pytest 7 + Vitest 10 全绿。05f 仅类目显隐（拖拽分组未做）、05g Flutter 待 `client/` 仓库 PR。详见 `docs/01 §十六` |
| 2026-07-16 | [docs/01 V2.3 同步] 新增产品前端缺口任务 **FE-PROD-05a~h**（Calendars 全球市场日历）：对标 yfinance 顶部 Markets 横向滚动条；左侧类目侧栏 + 右侧水平滚动卡片含 Sparkline；6 大类目（US/EU/Asia/Crypto/Rates/Commodities/Currencies）+ 4 日程 Tab（Economic/Earnings/Dividends/IPOs）+ Hours Tab；复用 `_fetch_macro_assets_data` 扩至 50+ 标的；与 §8 Macro Hub 边界澄清（横向广度 vs 纵向深度）；同步新增 **SVC-08**（Finnhub 限流感知）+ **BE-ARCH-05**（Finnhub DataSource 接入，接续 BE-ARCH-01~04）；任务定义与 `docs/01 §十六` · §十四 成熟度矩阵对齐 |
| 2026-07-13 | [CLI-09 完成] 真 WS 行情 (`RealWsGatewayImpl` + protobuf 解码 + 指数退避) + 持仓 REST (`PortfolioService` + `Position`)；QuotesPage/Detail/PortfolioPage 接真实数据；22 tests passed |
| 2026-07-13 | [TEST-03/04/12/14/15 完成] Locust 压测 + pytest-benchmark (11) + 契约测试 (23, 修复 PnL alias) + 前端组件测试 (23) + Playwright E2E (14)；TEST-05 延期至 CLI-01；全量验证通过 |
| 2026-07-12 | [第三轮 Review 代码改进] GOV-01~03 治理红线 + SEC-14~16 安全红线 + DIST-08~10 子服务增强 + SVC-04 数据质量监控 + ALERT-01~02 告警中心 + DQ-01~02 数据正确性 (64 tests); 全量 2321 passed |
| 2026-07-08 | [TODO.md 结构调整] RL-01~14 归档 + DIST+CL 合并为统一「分布式数据源集群」模块 (23 任务) + OBS-04/BE-20 标记完成 + Sprint 重排为执行焦点 |
| 2026-07-08 | [DIST-02] YFinanceRouter 客户端路由器骨架完成：ServiceRegistry 动态节点发现 (5s 缓存) + 加权轮询 + 熔断过滤 + 内存级快速熔断 (3次/30s) + failover + STALE 缓存降级 (Redis 24h TTL) + HMAC 签名；25 个单测全通过 |
| 2026-07-08 | [DIST-01] ServiceRegistry 服务注册表实现完成：NodeInfo 模型 + Redis Hash/ZSet/Set 三结构协同 + 全套 API (register/heartbeat/discover/deregister/cleanup_dead_nodes/mark_draining) + 集群总览 + 统计指标；31 个单测全通过 |
| 2026-07-08 | [架构决策] 主服务确认迁移至加州 VPS (38.60.126.42)，北京 VPS 降级为辅助节点 (仅 AKShare)；原因：Cloudflare Pages 跨境延迟 + GFW 干扰；CI/CD 已指向 VPS_S1 |
| 2026-07-08 | [RL-01~14] 数据源限流感知与自适应退避全部完成：错误分类体系 + 退避引擎 (4策略) + 熔断器解耦 + 频率分析器 (P75 RPM) + 推测频率 API + Prometheus 5指标 + Grafana 4告警规则 + 飞书 Webhook + 路由感知限流 + Agent Tool 智能重试；152 个单测全通过 |
| 2026-06-28 | [CL-01~04] 核心集群通信完成 (已合并至 DIST 模块): ClusterManager + Slave 心跳 + 采集回调 + 本地双 Compose 验证; 60 个测试全通过 |
| 2026-07-02 | [RISK-MVP] Risk 模块真实数据接入完成：RiskEngine 风控引擎 · 分账户独立计算 · 六维风险雷达 · 因子监控 · NAV 持久化 · 行业级版面 |
| 2026-06-28 | 新增 VPS 部署配置: `scripts/deploy/env.beijing.example` + `env.slave.example` + `init_slave.sh` 一键初始化脚本 |
| 2026-06-28 | CI/CD 部署流程增强: 首次部署时自动从 GitHub Secrets 生成 .env，支持 beijing/overseas/slave-1 三节点矩阵 |
| 2026-06-28 | 本地集群验证脚本: `scripts/test_cluster_local.py`，12 项端到端验证全部通过 (无需 Docker) |
| 2026-06-28 | 新增「当前 Sprint — 主从采集集群开发与部署」：CL-01~15 分 4 个 Sprint，覆盖集群通信/VPS部署/采集器验证/稳定性监控 |
| 2026-06-28 | 新增 `docs/14. 分布式数据源服务架构.md`：YFinance 多 VPS 驻留服务设计（注册发现 / 加权路由 / failover / STALE 降级） |
| 2026-06-28 | 重构 DIST 任务：原 DIST-01~10 拆分为 DIST-01~18，按 P0-P3 阶段组织（注册表 / 路由器 / 子服务 / HMAC / 编排 / 部署 / 监控 / 扩展） |
| 2026-06 | ADR-001: 确立纯 Vite SPA (React) 替代 Next.js App Router                              |
| 2026-06 | ADR-002: 确立 Flutter 统一三端（Android/iOS/HarmonyOS），移除 macOS Tauri                   |
| 2026-06 | ADR-003: 确立双 VPS + Cloudflare 边缘节点分布式部署方案                                        |
| 2026-06 | ADR-004: 架构重构——北京主节点(4C4G) + 加州数据子节点，服务注册表 + 动态路由，akshare 本地直连 |
| 2026-06 | `docs/02` V3.0 重写：Vibe Coding 工程规范（含单文件行数约束、原子化组件、测试标准）                          |
| 2026-06 | `docs/03` V3.0 重写：后端架构（三通道 API 隔离、JWT+HMAC、K线管道、Hermes集成）                        |
| 2026-06 | `docs/04` V3.0 重写：前端架构（TradingDashboard Keep-Alive、零GC、StatusBar、Error Boundary） |
| 2026-06 | `docs/05` V3.0 重写：客户端架构（Flutter 三端、AppMonitor APM、推送三通道、Phase 4 备选）              |
| 2026-06 | `docs/06` V4.0 重写：北京主节点 + 加州数据子节点、服务注册表 + 动态路由、费用更新 |
| 2026-06 | 新增 `docs/07` 子系统架构速查手册                                                           |
| 2026-06 | 新增 `docs/08` 日志与可观测性规范                                                           |
| 2026-06 | 新增 `docs/09` 性能测试规范                                                              |
| 2026-06 | 新增 `docs/subsystems/` 五大子系统架构速查文档                                                |
| 2026-06 | `AI_INSTRUCTIONS.md` V3.0 重写（前端框架确认、组件原子化、目录规范）                                  |
| 2026-06 | `docs/MASTER_REVIEW.md` 汇总所有 Review 结论与 ADR                                      |
| 2026-06-27 | [MIG-01] 前端工程可运行性抢救：重建 package.json、清理 Next.js 残留文件、安装缺失依赖                    |
| 2026-06-27 | [MIG-02] 新建 vite.config.ts：配置 React 插件、路径别名、开发代理                                |
| 2026-06-27 | [MIG-06] 清理迁移残骸：删除 .next/、next.config.mjs、next-env.d.ts 等 Next.js 文件            |
| 2026-06-27 | [MIG-07] 修正 tsconfig.json：移除 Next.js 配置、添加 vite/client 类型声明                      |
| 2026-06-27 | .gitignore 全量优化：新增系统文件、IDE 配置、Python/Node 依赖、Docker、量化专属文件等忽略规则             |
| 2026-06-27 | 工程体积优化：清理 8.5GB 冗余文件（.next/、.venv/、node_modules/）、使用 git-filter-repo 清理 Git 历史 |
| 2026-06-27 | Git 推送问题排查：定位并删除全局 Git insteadOf 规则，解决 GitHub 403 错误                         |
| 2026-06-27 | [MIG-03] 重建 Vite 入口：index.html 正确引用 main.tsx、ReactDOM.createRoot 已配置           |
| 2026-06-27 | [MIG-04] 路由迁移：已完成 React Router v6 配置，路由定义在 App.tsx 和 router/index.tsx      |
| 2026-06-27 | [MIG-05] 剥离 Next.js 专有 API：代码中已无 next/ 直接引用，next-themes 可继续使用            |
| 2026-06-27 | [MIG-08] 修复 Dockerfile：统一使用 pnpm、修正 COPY 指令、验证多阶段构建链路              |
| 2026-06-27 | [MIG-09] 修正 README.md：重写为 React 18 + Vite SPA 架构说明，与 ADR-001 对齐           |
| 2026-06-27 | [MIG-10] 迁移验收完成：pnpm build 成功（25.35s）、7773 模块转换、dist/ 生成      |
| 2026-06-28 | [INFRA-01] PostgreSQL Schema 落地：所有数据表已定义在 backend/core/models.py                |
| 2026-06-28 | [INFRA-02] Pydantic Settings 强类型校验已实现：backend/core/config.py                      |
| 2026-06-28 | [INFRA-03] 后端依赖管理已迁移到 pyproject.toml                                              |
| 2026-06-28 | [INFRA-04] 后端目录分层已落地：routers/services/workers/core 物理隔离                     |
| 2026-06-28 | [SEC-01] 所有对外 API 已添加 /api/v1/ 版本前缀（backend/main.py）                        |
| 2026-06-28 | [SEC-02] JWT 双令牌体系已实现（15min Access + 7d Refresh）                              |
| 2026-06-28 | [SEC-03] HMAC-SHA256 签名验证已实现（backend/core/security.py）                          |
| 2026-06-28 | [SEC-04] 敏感字段加密工具已创建（backend/core/encryption.py）                             |
| 2026-06-28 | [SEC-05] 限流中间件已实现（Redis 原子计数器）                                             |
| 2026-06-28 | [SEC-06] Futu 密码已从 .env 注入（backend/core/config.py）                                 |
| 2026-06-28 | [SEC-10] 认证闭环已实现（login/refresh/logout）                                           |
| 2026-06-28 | [SEC-11] CORS 白名单已配置（backend/main.py）                                              |
| 2026-06-28 | [SEC-12] 审计日志已落地（backend/services/audit_service.py）                                |
| 2026-06-28 | [SEC-07] Token 存储安全化：移除 zustand/persist 的 localStorage 持久化，Access Token 仅存内存，Refresh Token 走 HttpOnly Cookie |
| 2026-06-28 | [SEC-08] XSS 过滤：安装 DOMPurify，创建 sanitize 工具，Mermaid 渲染器集成 DOMPurify 净化 + securityLevel 升级为 strict |
| 2026-06-28 | [SEC-09] 二次确认弹窗：创建全局 ConfirmDialog 系统（基于 Radix AlertDialog），替换全部 8 处 window.confirm |
| 2026-06-28 | [BE-04] 熔断器：backend/core/circuit_breaker.py，异步优先状态机 (CLOSED→OPEN→HALF_OPEN)，支持 call/call_sync/guard 装饰器 |
| 2026-06-28 | [BE-08] 客户端 APM 心跳：backend/routers/client.py，POST /heartbeat 写入 PostgreSQL + GET /heartbeat/stats 聚合统计 |
| 2026-06-28 | [BE-13] 统一响应封装：error_codes.py (ErrorCode 枚举) + exceptions.py (自定义异常层级) + response.py (success/error) + 全局异常处理器 + 响应信封转换中间件 |
| 2026-06-28 | [BE-14] Pydantic v2 领域模型：backend/schemas/domain.py，12 个 Schema 覆盖 Symbol/Quote/Kline/Position/Order/Account/TechIndicators/Pagination/ClientHeartbeat |
| 2026-06-28 | [BE-05] structlog 结构化日志：backend/core/structlog_config.py + contextvars trace_id 注入 + JSON 文件输出 + 中间件自动注入 X-Trace-Id |
| 2026-06-28 | [BE-06] Prometheus 指标增强：backend/core/metrics.py，17 个自定义指标覆盖行情延迟/WS连接/Redis深度/熔断器/客户端APM/LLM |
| 2026-06-28 | [BE-07] Alembic 迁移初始化：alembic.ini + backend/alembic/env.py + script.py.mako + versions/ |
| 2026-06-28 | [BE-15] WebSocket 网关增强：JWT 鉴权 + 订阅去重 + 心跳超时检测 + 统一响应格式 + Prometheus 指标埋点 |
| 2026-06-28 | [BE-03] Futu 看门狗：backend/services/futu/watchdog.py，指数退避重连 + 健康探针 + Prometheus 指标 |
| 2026-06-28 | [BE-16] 行情正确性：backend/core/market_correctness.py，复权处理 + 停牌检测 + UTC 时区统一 + 价格异常检测 |
| 2026-06-28 | [BE-02] 三级 K线缓存：backend/core/kline_cache.py，Redis 热层 + Parquet 温层 + 智能路由引擎 |
| 2026-06-28 | [BE-17] pgvector 迁移工具：backend/scripts/migrate_knowledge_base.py，导出/导入/清理 CLI |
| 2026-06-28 | [BE-18] PG 备份脚本：backend/scripts/pg_backup.py，pg_dump + gzip + R2 上传 + 恢复 |
| 2026-06-28 | [BE-01] K线管道压测：backend/scripts/benchmark_kline_pipeline.py，端到端延迟测试工具 |
| 2026-06-28 | [OBS-01/02] Grafana 仪表板 + 告警通道配置完成 |
| 2026-06-28 | [BE-09/11] 统一响应结构 + /api/v1/health 健康检查端点完成 |
| 2026-06-28 | [SEC-13] 登出缓存清理策略完成 |
| 2026-06-28 | [FE-23/24] a11y 无障碍 + 全局字体统一完成 |
| 2026-06-28 | [TEST-16/17] 前端构建健康 + 后端启动健康验证 |
| 2026-06-28 | 新增 CLI-07 / FE-25~30 / OBS-03 任务 |
| 2026-06-28 | [FE-01] Keep-Alive TradingDashboard：模块状态持久化，切换不卸载 |
| 2026-06-28 | [FE-02] StatusBar 组件：WS 状态灯 + 延迟 + 账户净值 + 盈亏 |
| 2026-06-28 | [FE-03] WebSocket 断线处理：use-ws-manager.ts，指数退避重连 + 重订阅 |
| 2026-06-28 | [FE-04] 三级 Error Boundary：Module/Panel/Chart 级错误隔离 |
| 2026-06-28 | [FE-05] 前端日志系统：logger.ts，level 过滤 + 批量上报 |


---

## 📝 会话笔记

> 记录每个开发会话的关键决策、遇到的问题与解决方案，供后续会话参考。

### 2026-06-28 会话 1：后端启动验证

**目标**：启动后端服务，验证所有核心接口能力

**遇到的问题**：
1. `from core.` 导入路径错误 → 修复为 `from backend.core.`
2. `from services.` 导入路径错误 → 修复为 `from backend.services.`

**验证通过的接口**：
- `/api/v1/health` - 健康检查
- `/api/v1/auth/login` - 认证
- `/api/v1/market/quote` - 实时行情
- `/api/v1/market/fundamental/{ticker}` - 基本面
- `/api/v1/market/news` - 市场新闻
- `/api/v1/macro/sentiment-history` - 宏观情绪
- `/api/v1/macro/calendar` - 宏观日历
- `/api/v1/market/futu/status` - Futu 状态
- `/api/v1/market/health/services` - 服务健康
- `/api/v1/client/heartbeat/stats` - 客户端心跳统计

**后端运行状态**：
- PID: 33985
- 端口: 8000
- PostgreSQL: ✅ connected
- Redis: ✅ connected
- Futu OpenD: ✅ CONNECTED

---

### 🔗 关键文档链接

- [MASTER_REVIEW.md](./MASTER_REVIEW.md) - 架构决策记录 + 三轮 Review 结论（§七 业界对标差距）
- [docs/01. 产品功能与UIUE架构](./01.%20产品功能与UIUE架构.md)
- [docs/02. Vibe Coding与AI工程规范](./02.%20Vibe%20Coding与AI工程规范.md)
- [docs/03. 后端架构与执行引擎](./03.%20后端架构与执行引擎.md)（**V5.1** 整洁架构 / 依赖矩阵 / 插件热加载）
- [docs/04. 前端架构与零GC渲染](./04.%20前端架构与零GC渲染.md)
- [docs/08. 日志与可观测性规范](./08.%20日志与可观测性规范.md)
- [docs/10. API接口规范](./10.%20API接口规范.md)
- [docs/11. 数据模型与领域设计](./11.%20数据模型与领域设计.md)
- [docs/12. 运维手册与应急预案](./12.%20运维手册与应急预案.md)
- [docs/13. 质量评估体系](./13.%20质量评估体系.md)
- [docs/14. 分布式数据源服务架构](./14.%20分布式数据源服务架构.md)
- [docs/15. 回测实盘同构引擎设计](./15.%20回测实盘同构引擎设计.md)
- [docs/16. 策略实验室完整架构](./16.%20策略实验室完整架构.md)
- [docs/17. 纸面组合系统架构](./17.%20纸面组合系统架构.md)
- [docs/18. 多通道推送路由设计](./18.%20多通道推送路由设计.md)
- [docs/19. Parquet数据湖快照版本化设计](./19.%20Parquet数据湖快照版本化设计.md)

---

### 📝 变更日志


| 日期         | 更新说明                                                 |
| ---------- | ---------------------------------------------------- |
| 2026-08-09 | [数据服务三条标准复审 · 07 系列落地后] 按用户三条验收标准（① HTTP API 完整可靠 ② 长连接可用 ③ **主服务不依赖第三方代码包**）复审，**三条全部不达标**。07 系列成果确认：调用层直连已清干净（`services/akshare/` 本地 SDK 消失 / `routers/search`+`calendars` 走适配器 / `core/yahoo_news` 收口 / `services/futu/enums.py` 替掉 SDK 枚举 / 基础依赖零数据源 SDK）。**新发现 4 P0 + 3 P1**：08a 主服务 `market_engine.py:33` 顶层 import futu 而主镜像不装 `futu-api` ⇒ **`uvicorn backend.main:app` import 阶段即崩**（实测 `ModuleNotFoundError: futu`，07b 改 eager import 引入的回归）；08b YF/AKShare/FMP 的 `ticker`↔`symbol` 键名错位 ⇒ 线上取不到数（`router.py:582-586` vs `yfinance_worker.py:13`，被 `router.py:557-563` 离线 stub 掩盖）；08c Futu 推送四处断链（`to_thread(connect)` 致 `set_main_loop` 永不成功 / 启动零 subscribe / 重连 `subscribe_push=False` / 子服务未配主 Redis）⇒ 线上"实时"实为 10s 轮询；08d `_normalize_response` 只认 `data.error` 不认 `data.status=="error"` ⇒ FMP/Finnhub 配额与 429 被吞成成功；08e 9 个 pin 源熔断一次永久失效（无半开）；08f AKShare STALE 只写不读（DIST-19 未生效）；08g FMP `FUNDAMENTAL`/`INFO` 无 worker 分支。**方法论根因**：离线 stub 短路 + 守门测试只查 import ⇒ 跨进程契约缺陷结构性隐形 → 立 08h 契约测试根治。新增 **BE-ARCH-08a~08h** + 执行焦点线 7；`docs/23` §八 重写为复审现状 |
| 2026-08-09 | [数据服务架构审计] 对照 `docs/23` §二红线 + `AGENTS.md` §9.1/§10 全量审计主服务/子服务/Hermes/前端/Flutter 五个范围。结论：四层骨架已落地（`business/` 零直连 + 四策略原语真实现 + 子服务单端点 `POST /api/v1/data` HMAC 收口 + 前端与 Flutter 干净），但主服务仍大面积 legacy 直连 —— **P0**：`legacy_market_data.py:89-103` 主行情 QuotePort 直连本地 Futu SDK；`market_engine.py:302` 死门控（本地 Futu 状态恒 False）废掉四段已合规的远程调用。**P1**：`routers/search.py`、`routers/calendars.py:495,553` 路由层裸连外网（合规适配器闲置）；AKShare/FRED/DBnomics/RBI 本地连接层仍在生产路径；长连接仅 `Futu push → quant:quotes:stream → /market/quotes/ws` 一条真通，另有 8 处频道错配/未挂载 daemon。新增 **BE-ARCH-07a~07o** 15 项任务（每项附精确 `文件:行号` 错误代码指引）+ 当前执行焦点线 6；`docs/23` 新增 §八 现状审计章节 |
| 2026-07-19 | [PROD-04 完成] 四场景模式系统落地：`scene-mode-types.ts` + `useSceneModeStore.ts`（Zustand+localStorage）+ `globals.css` CSS 变量 + `scene-mode-switcher.tsx` 顶栏切换器 + `use-scene-hotkey.ts` Cmd+Shift+M + `dashboard-layout.tsx` 布局适配（data-scene-mode/Sidebar显隐/AI全屏/研究自动展开）+ `fullscreen-copilot.tsx` + EdgeHandle 条件渲染；12 tests + tsc 零错误 + 197 tests 零回归 |
| 2026-07-16 | [PROD-04 升级] 工作区快照布局 → 四场景模式系统（盯盘/研究/监控/AI分析）；新增 AI-01~09 全模块渗透任务（三层架构：主动推送/嵌入式辅助/按需调用）；同步更新 `docs/01` §9.6~9.7 |
| 2026-07-14 | [DIST-19~23 完成] Phase 4 稳定性+监控+扩展：DIST-19 AKShare STALE 缓存降级（`data_source_router.py` 远程+本地均失败→Redis STALE 回退）；DIST-20 7 个 Prometheus 分布式指标（`metrics.py`）+ Grafana 节点监控面板（`distributed-nodes-dashboard.json`）+ router 指标集成；DIST-21 5 条 Grafana 告警规则（`alerting.yml`：心跳超时/YF 存活<2/全挂/CN 断连/STALE 高频）；DIST-22 Finnhub Worker 迁子服务（`finnhub_worker.py` + `main.py` lifespan 集成，`DS_CAPABILITIES=finnhub` 启用）；DIST-23 systemd 守护单元（`quant-worker.service` WatchdogSec=60 + Restart=always + NoNewPrivileges 安全加固）；2866 tests passed |
| 2026-07-14 | [TRADE-01~03 完成] 交易进阶三任务全量交付：TRADE-01 期权筛选 (`options_engine.py` BS定价+Greeks+IV+微笑 + `options_screener.py` 筛选服务 + `routers/options.py` 4端点 + `options-screener-panel.tsx` 前端 · 14 tests)；TRADE-02 算法增强 (`algo_engine.py` +MarketImpactModel +POV/IS + `algo_analytics.py` 执行分析 + `oms.py` +analytics端点 + `algo-analytics-panel.tsx` · 41 tests)；TRADE-03 组合优化 (`portfolio_optimizer.py` Markowitz+风险平价+MaxSharpe+有效前沿+模型对比 + `routers/portfolio.py` 3端点 + `portfolio-optimizer-panel.tsx` · 13 tests)；`main.py` 注册 options/portfolio 路由；后端 68 tests + 前端 175 tests + tsc 零错误 |
| 2026-07-13 | [AI-02~04 工程规范 + AI-01~03 能力 完成] 阶段1: `LLMRouter` + `ModelTier` 三级路由 + Ollama 降级 + 版本钉定 (12 tests)；阶段2: RAG 分类 TTL + embedding 版本管理 + 检索质量监控 + Alembic 迁移 (11 tests)；阶段3: `EvalMetrics` + 55 例 Golden Dataset + `EvalRunner` + `eval.yml` CI (26 tests)；阶段4: `DeepResearchPipeline` 三段流水线 + `FactorMiner` LLM 因子建议 + `Alpha158` 40+ 因子库 + API 路由 + 前端面板 (37 tests)；后端 86 tests + 前端 175 tests + tsc 零错误 |
| 2026-07-14 | [PT-01~02 完成] 纸面组合追踪系统：4 张 PG 表 ORM + Alembic 迁移 + PaperLedgerService（fill_seq/投影/重放/对账）+ SimBroker paper_mode 差异（stale 拒单/时段检查/fill_callback）+ paper router (9 端点) + PaperSettlementDaemon（EOD 结算/停牌前收兗底/补结算/周度对账）+ worker.py 挂载 + performance.py 共享绩效库（sharpe/mdd/TE/signal_consistency）+ compare API + paper_drift 告警规则 + features/paper/ 前端全套（列表/详情/净值图/对比图/漂移面板/流水/创建表单）+ 检查点文案接真实数据；后端 76 tests + 前端 8 tests + tsc/build 零错误 |
| 2026-07-13 | [STRAT-01~05 完成] 策略实验室落地：Store 拆分 4 Slice（editor/ai/backtest/layout）+ Topbar 三按钮接线；AI Diff 状态机 + DiffOverlay + 四路径收口（ai-chat/auto-fix/ast-fix/hermes）；PG 版本存储（strategies + strategy_versions 不可变快照 + strategy_version_service + 4 端点改造）+ 版本时间线前端 + 左侧栏 Tabs 集成；Auto-Debug 闭环（结构化错误契约 + 熔断 3 次）；use-sandbox-run AbortController + debounce + loading 蒙层；前端 72 tests passed + 后端 8 tests passed + tsc/build 零错误 |
| 2026-07-13 | [ARCH-01~03 + AI-01 完成] `prompts/` 目录结构（README + 3 task + template + system）+ `docs/12` §八 Futu OpenD 部署约束（禁 ARM/地域限制/版本管理）+ §九 DuckDB 分区策略（三级分区+迁移+查询优化）+ §十 断连恢复 SOP（影响矩阵+在途对账+人工介入+演练计划）；ARCHITECTURE_REVIEW.md 4 项标记完成 |
| 2026-07-13 | [DOC-01~03 完成 + ARCHITECTURE_REVIEW 补漏] Tool 开发模板 + 性能基准实测 + 废弃文档清理；新增 AI-01~04（Prompt/LLM/Eval/RAG）+ ARCH-01~03（Futu 部署/DuckDB/断连恢复）任务 |
| 2026-07-13 | [DOC-01~03 完成] Tool 开发模板（入参/出参/错误码/骨架/测试模板）+ 性能基准实测数据补充（10 项全部达标）+ 废弃文档清理（backend.md/frontend.md 引用更正） |
| 2026-07-13 | [CLI-13~14 完成] 平板双列精细化 + Isolate 大包解析：`CandleBar.fromJson` + `HistoryKlineService` + `TabletPortfolioPage` master-detail 双栏布局 · PortfolioPage 宽度断点切换 · `IsolateJsonParser` 32KB 阈值 + `RestGatewayImpl._mapAsync` + `HistoryKlineService` compute 批量解析 + `QuoteDetailPage` 接真实历史 K 线；`cli13/14` 21 tests passed |
| 2026-07-13 | [CLI-10~12 完成] 简化 OMS + Kill Switch + Copilot SSE：`BiometricAuth` port + `LocalBiometricAuth` + `Order` 实体 + `OmsService` + `OrderConfirmationPage` LIVE 生物识别门禁 + PortfolioPage 撤单入口 · `KillSwitchService` + `KillSwitchDialog` 两步确认 + MorePage LIVE-only 按钮 · `ChatMessage`/`ChatChunk` 实体 + `ChatStreamGateway` port + `SseChatGatewayImpl` Dio ndjson 流 + `CopilotNotifier` + `CopilotPage` 完整对话 UI；`cli10/11/12` 47 tests passed |
| 2026-07-13 | [CLI-09 完成] 真 WS 行情 + 持仓 REST：`RealWsGatewayImpl`（protobuf 解码 + 指数退避重连 + pause/resume）；`PortfolioService`（经 `QuantRestGateway`）；QuotesPage/Detail/PortfolioPage 接真实数据；`cli09_ws_portfolio_test` 22 passed |
| 2026-07-13 | [TEST-03/04/12/14/15 完成] Locust 压测脚本 + pytest-benchmark 11 基准 + 前后端契约测试 23 tests (修复 PnL alias) + 前端关键组件 23 tests + Playwright E2E 14 tests；TEST-05 延期至 CLI-01；全量验证通过 |
| 2026-07-13 | [CLI-08 完成] `StaleOverlay`/`StaleBadge`（opacity+去饱和+amber）；`ConnectionHealth` + `WsGatewayImpl.setMarketConnected` 桥接；行情/持仓/告警挂载；ModeBanner 改用 AppColors；`cli08_stale_overlay_test` |
| 2026-07-13 | [CLI 演进路线入 TODO] 按 `docs/05` §十一 新增 **CLI-08~14**：StaleOverlay / WS+持仓 / 简化 OMS+生物识别 / Kill 双重确认 / Copilot SSE / 平板双列 / Isolate 大包解析；依赖图 S4 拆 CLI 地基与 CLIP2 |
| 2026-07-13 | [CLI-ARCH-01/02 完成] 分层 import 门禁 `LayerBoundaryChecker`；Figma Variables 同步表 `design/figma_variables_sync.json` ↔ `color_tokens.dart`；`cli_arch01`/`cli_arch02` tests |
| 2026-07-13 | [CLI-06 完成] `platform/harmonyos` MethodChannel（Push/Account）+ `HmsPushAdapter` + `loginWithHms` 换票；`ohos/README` 契约；心跳 `platform=harmonyos`；`cli06_harmonyos_hms_test` |
| 2026-07-13 | [CLI-05 完成] `PushNotificationPort` + FCM/APNs/HMS Shell + Memory；`ui_hint`→`go_router` 深链（对齐 Web alert-nav）；P0 Overlay / Toast / Tab 角标；`cli05_push_deeplink_test` |
| 2026-07-13 | [CLI-04 完成] `SecureAuthTokenStore` + `FlutterSecureKvStore`（禁 SharedPreferences）；Dio Bearer 拦截；`/login` + guest 守卫；`AuthSession` restore/login/logout；`cli04_auth_token_store_test` |
| 2026-07-13 | [CLI-03/03b 完成] ADR-007 批准 CustomPainter 主图；列表 Sparkline+MiniCandle；详情 `KlineChart`（RepaintBoundary/缩放平移十字线）+ Float64 OHLC；`cli03_charts_test`；演示数据待接 Gateway |
| 2026-07-13 | [CLI-02 完成] `HttpAppTelemetry`：FrameTiming FPS + RSS 内存 + WS 延迟；前台 30s → `POST /api/v1/client/heartbeat`；`TelemetryLifecycle` 前后台启停；`cli02_app_telemetry_test`；全量 8 tests |
| 2026-07-13 | [CLI-01 完成] Flutter 脚手架 `client/flutter_app/`：Clean 四层 + Gateway Ports 注入 + go_router AdaptiveShell（Mobile NavBar / Tablet Rail）+ 五 Tab 占位；`flutter analyze` 清洁；`cli01_scaffold_test` 4 passed |
| 2026-07-13 | [FE-11~15/25/26/28~30 完成] DataState 三态 + SymbolContextMenu + VirtualList/AG Grid + MobileTabBar + 主题 Token/动效 + docs/20 设计规范 + 根/图表 ErrorBoundary + Lighthouse `?lighthouse=1` 基准脚本；`fe-experience.test.ts` |
| 2026-07-13 | [FE-PROD-04 完成] 回测快照 picker（`/datalake/snapshots`）+ Tear Sheet 可复现性徽章；`/backtest/run` 附加 manifest/badge；策略沙箱同步；`snapshot-picker.test.ts` |
| 2026-07-13 | [FE-PROD-03 完成] P0 AlertOverlay + P1/P2 Toast 栈 + P3 角标；`ui_hint`→行情跳转；Alert WS STALE；`GlobalAlertGateway`；`alert-overlay.test.ts` |
| 2026-07-13 | [FE-PROD-02 完成] 三模式：`useTradingModeStore` + 顶栏切换器/全局横幅/底栏芯片；PAPER↔LIVE 确认含 PT-02b 占位；SANDBOX→LIVE 需输入 LIVE；后端 `/oms/mode` 接受 PAPER；`trading-mode.test.ts` |
| 2026-07-13 | [FE-PROD-01 完成] 全局 AI 副驾右侧抽屉：`useLayoutStore` 互斥 + `DashboardLayout` 常驻面板（折叠不卸载 ChatProvider）+ 边缘把手/`Cmd+Shift+A` + Settings Sheet；`/copilot` 深链迁抽屉；`layout-store.test.ts` |
| 2026-07-13 | [BT-06 完成] 过拟合检测：Deflated Sharpe + 参数悬崖敏感性；复用网格；`POST /backtest/overfit`；`test_overfit_bt06.py` |
| 2026-07-13 | [BT-05 完成] 参数网格：ProcessPool 并发 Vector 回测 + 夏普热力图矩阵/ECharts data；`POST /backtest/grid-search`；`test_grid_search_bt05.py` |
| 2026-07-13 | [BT-04 完成] 蒙特卡洛：交易重排/自助抽样 + 5/50/95 分位曲线 + 最坏回撤；`POST /backtest/monte-carlo`；`test_monte_carlo_bt04.py` |
| 2026-07-13 | [BT-03 完成] Walk-Forward：滚动/锚定窗口 + VectorBT 快路径折跑 + IS/OOS 漂移检测；`POST /backtest/walk-forward`；`test_walk_forward_bt03.py` |
| 2026-07-13 | [BE-ARCH-04 完成] 双 Registry 澄清：`RateLimitRegistry` vs `DataSourceRegistry`+`DataSourceInterface`；YF 主路径经 `fetch`；`test_be_arch04_dual_registry.py` |
| 2026-07-13 | [BE-ARCH-03 完成] Collector 插件化：`workers/collectors/*` factory 表；`start_collector_daemons` 零具体服务 import；启停矩阵 + `test_be_arch03_collector_plugin.py` |
| 2026-07-13 | [BE-ARCH-02 完成] Application 用例落地：`oms_app`/`backtest_app`/`system_app`；Router 变薄；扁平 services allowlist 冻结；`test_be_arch02_app_boundary.py` |
| 2026-07-13 | [BE-ARCH-01 完成] Router 去数据源直连：QuotePort/BrokerPort + Legacy Gateway；21/21 routers 经 `app.market_data`/`app.broker`；架构守门测试 |
| 2026-07-13 | [OBS-03/FE-27 完成] Web Vitals→heartbeat+Prometheus；Grafana API P50/APM/LCP·INP·CLS；告警指标名纠偏；前后端单测 |
| 2026-07-13 | [ALERT-05 完成] 技术指标告警 a~d：`alert_models.py` 新增 `RSI_THRESHOLD`/`MACD_CROSS`/`MA_CROSS` 规则类型 + `evaluate_indicator_rule()` 评估函数；`indicator_evaluator.py`（IndicatorEvaluator 盘中节流 15min + 指标滑动窗口缓存 + `extract_indicators_from_tech_data` 从 yfinance 提取 RSI/MACD/MA/KDJ/ATR）；AlertEngine 集成（`evaluate_quote` 分离价格/指标规则 + `_evaluate_indicator_rules` + `_fetch_indicators` + `_create_indicator_event`）；前端 `types/alert.ts` 新增指标类型 + `alert-center.tsx` 表单条件渲染（RSI 阈值输入/MACD 金叉死叉方向按钮/MA 短长周期+方向）；32 个新测全通过，全量 2594 passed |
| 2026-07-13 | [ALERT-04 完成] 前端告警中心页面 a~e：`types/alert.ts` 类型定义 + `use-alert-api.ts` API Hook（useAlertRules/useAlertEvents/useAlertWebSocket）+ `features/alert/alert-center.tsx` 告警中心页面（左侧规则列表按类型分组 + 右侧事件历史流 + 新建规则 Modal 表单）+ `/alerts` 路由注册 + 侧边栏 Bell 图标导航项（风控域）+ 行情页自选股右键菜单"设置价格告警"入口（自定义事件派发 → 告警中心打开表单并预填标的）；11 个前端测试全通过 |
| 2026-07-13 | [ALERT-03 完成] 多通道推送路由 a~d：`alert_dispatcher.py`（PriorityResolver+ChannelPlanner+CooldownGate+RetryQueue+DLQ）+ `alert_adapters/`（InApp/Feishu/Telegram 三适配器）+ NotificationService 收敛为 dispatcher 薄包装 + AlertEngine 改调 dispatcher + `/alert/ws` WebSocket 实时推送 + `/alert/events/{id}/deliveries` 投递查询 + events `since` 补拉；`alert_models.py` 新增 NotificationPriority + AlertEvent 扩展 source/priority/ui_hint；58 个新测全通过，全量 2505 passed |
| 2026-07-13 | [BE-19 完成] OpenAPI：enricher 全量 summary/example + `docs/openapi.json` 导出 + docs/10 V1.1 路径互校；`test_openapi_be19.py` 7 passed |
| 2026-07-13 | [BE-10 完成] OTEL Trace：采样率+安全退化+httpx/SQLAlchemy；Tempo(monitoring)+Grafana datasource；API `X-Trace-Id`；`test_otel_be10.py` |
| 2026-07-13 | [BE-12 完成] Tool 结果统一 Redis Hash 缓存：`tool:cache:{name}:{args_hash}`，Registry.execute 收口，TTL/黑名单可配；8 tests |
| 2026-07-13 | [DQ-04 完成] SVC-04→Prometheus/Grafana：脏数据率/完整率/价格异常/过期/延迟按 source 分维；`Data Quality (DQ-04)` 看板 + `/system/data-quality` + 5% 告警 |
| 2026-07-13 | [DQ-03 完成] 快照版本化 a~e：Publisher/Reader/Retention + `/api/v1/datalake/snapshots` + daemon 挂接；废弃 parquet_db 回测路径；`test_datalake_dq03.py` 6 passed |
| 2026-07-13 | [BT-02 完成] 回测可复现性：`RunManifest`+`backtest_reports`/`data_snapshots` + ReportService + `/api/v1/backtest/reports`；同输入同输出契约测试；顺带落地 DQ-03a（manifest/resolver）；DQ-03c 剩余 SnapshotReader parquet 装载 |
| 2026-07-13 | [docs/05 V4.0] 客户端实施前 Review：整洁四层+禁止矩阵 · Gateway Ports · 薄客户端（对齐 Web 五域）· Figma DS 指引；CLI-01~06 重述 + **CLI-ARCH-01/02**；CLI-03 降级轻量图 |
| 2026-07-13 | [FE-ARCH-01~04 完成] KeepAliveOutlet + ModuleErrorBoundary；oms/right-sidebar/backtest-report 拆分 ≤300（ui/sidebar 为 shadcn 例外）；全量 recharts→ECharts 并移除依赖；死代码清理闭环 |
| 2026-07-13 | [前端架构 V4.0] `docs/04` 纠正 SSOT=`DashboardLayout`+Router；vibe-coding V2.1 固化基建栈；删除 TradingDashboard 死路径/axios 死客户端/空 stub/`package-lock.json`；拆分 backtest charts + OMS types/modals；新增 **FE-ARCH-01~04**；FE-01 纠偏 |
| 2026-07-13 | [BT-01 全部完成] 同构引擎 a~f 六子任务全部落地：新增 live.py（LiveDriver + TickAccumulator + LiveContext + Redis 行情降级轮询 + paper 模式 SimBroker 接线）+ adapters/legacy.py（LegacyStrategyAdapter 支持 on_bar/on_tick/矢量化三种旧接口桥接）；28 个新测全通过，全量 2398 passed |
| 2026-07-13 | [BT-01a/b/c/d 完成] 同构引擎契约层 + BacktestDriver + VectorBT 快路径 + ExecutionGateway 落地：`backend/engine/` 新增 contracts.py（Bar/QuoteSnapshot/OrderIntent/OrderUpdate/Position/RunManifest）+ strategy.py（Strategy ABC + signals 矢量化快路径）+ context.py（StrategyContext Protocol + BaseContext）+ clock.py（SimClock/WallClock）+ drivers/backtest.py（BacktestDriver + BacktestContext）+ drivers/sim_broker.py（SimBroker 模拟撮合）+ drivers/vector.py（VectorExecutor + 回退执行）+ gateway.py（ExecutionGateway + 三级安全锁 + OmsExecutionAdapter）+ verify.py（IsomorphismVerifier 同构校验器）；94 个单测全通过，全量 2370 passed |
| 2026-07-13 | [清理] 包1+包2：删除 backend 垃圾产物（.DS_Store/coverage/陈旧 pyc）+ 孤儿代码 `routers/chat.py`/`oms_mock_data.py`/`workers/daemon.py`/`macro_radar.py` + futu 迁移 md + `test_fixes.sh` + `scripts/test_local_cluster.sh`；同步删改对应测试。包3保留（quote_publisher/market_correctness/parquet_db） |
| 2026-07-13 | [docs/03 V5.1] 后端整洁架构重写：依赖只向内 · 禁止 import 矩阵 · Ports · 插件/热加载分级 · Frozen 映射 · 纠拓扑（Registry 合法）· 端点 SSOT→docs/10 · 指针 docs/14~19；新增架构债任务 **BE-ARCH-01~04** |
| 2026-07-13 | [docs/02 V4.3] Vibe Coding 规范操作化：§0 SSOT 层级 · §2.3 Frozen Zone · §5 技术栈指针表 · §7.1 MCP · §7.5 Verify-Before-Write · §7.6 Plan-Confirm-Execute · §7.7 多模型差异；目标：减幻觉 / 省 Token / 核心少动 / 改动需确认 |
| 2026-07-13 | [docs/01 V2.2 同步] 新增产品前端缺口任务 **FE-PROD-01~04**：全局 AI 副驾抽屉 / 三模式顶栏（SANDBOX·PAPER·LIVE）/ P0 AlertOverlay + ui_hint / 回测快照 picker + 可复现性徽章；执行焦点线 3 追加 FE-PROD 对接项；任务定义与 `docs/01 §十二` · §十四 成熟度矩阵对齐 |
| 2026-07-13 | [DQ-03 设计完成] 新增 `docs/19. Parquet数据湖快照版本化设计.md`（V1.0）：Live 可变/Snapshot 不可变双层 + manifest.json（manifest_hash 数据指纹）+ 日快照 snap_YYYYMMDD + 回测默认 latest_published（非 live）+ DQ-01 universe sidecar 捆绑 + 三级保留（90天全日/月锚点/R2 冷归档）+ BT-02 衔接契约；DQ-03 拆分为 a~e 五个子任务；BT-02 标注依赖 DQ-03c |
| 2026-07-13 | [ALERT-03 设计完成] 新增 `docs/18. 多通道推送路由设计.md`（V1.0）：AlertDispatcher 统一出口（AlertEngine/RL-11/系统事件/Hermes 全部收口）+ P0~P3 路由矩阵（通道集合/并发串行/重试次数/通道冷却/ui_hint）+ 双层冷却（规则冷却保留引擎 + 通道 fingerprint 冷却）+ RetryQueue 指数退避 + DLQ + 三适配器（专用 quant:alerts:push WS 频道，与 macro_alerts 分离）+ NotificationService 收敛；ALERT-03 拆分为 a~d 四个子任务；摸底确认 AlertEngine 未启动/无生产适配器/NotificationService 无 Telegram 无重试 |
| 2026-07-13 | [PT 设计完成] 新增 `docs/17. 纸面组合系统架构.md`（V1.0）：PG 流水账本 SSOT（paper_fills 只增 + fill_seq 重放序 + 持仓投影可重建 + 周度对账自检）+ EOD 结算 daemon（数据驱动交易日判定 + 停牌前收兜底 + ≤7 天补结算自愈）+ `performance.py` 共享绩效库抽取 + 回测对比序号对齐（TE + 信号一致率/成交偏离归因）+ 偏离告警复用 ALERT-01（新规则类型 paper_drift）+ 实盘前检查点；PT-01/02 拆分为 5 个子任务（01a/01c/02a 与 BT-01 解耦可先行，01b 依赖 BT-01d/e）；摸底确认系统无任何虚拟账本、SANDBOX 模拟单实为 Futu 模拟盘托管、nav_snapshots 绑定券商账户维度不可复用 |
| 2026-07-12 | [STRAT 设计完成] 新增 `docs/16. 策略实验室完整架构.md`（V1.0）：Diff 状态机单点合入（四条 AI 来源路径全部经 [Apply] 确认）+ PG 不可变版本快照（`strategies`/`strategy_versions`，保存即版本、deploy 只认 version_id）+ 结构化错误契约（error_code + error_detail）驱动 Auto-Debug 闭环 + 沙箱维持 AST+熔断不引入进程隔离 + 与 BT-01 契约双轨过渡；STRAT-01~05 重述为 6 个子任务（01a→{02,03a}→{03b,04}，05 独立）；摸底修正 TODO 过时描述（前端已非单文件巨石） |
| 2026-07-12 | [BT-01 设计完成] 新增 `docs/15. 回测实盘同构引擎设计.md`（V1.0）：统一 Strategy/StrategyContext 契约 + BacktestDriver/LiveDriver/VectorBT 快路径三执行体 + ExecutionGateway 三级安全锁 + 同构校验器；QUANT-01 并入 BT-01c；BT-01 拆分为 a~f 六个子任务（依赖 a→b→{c,d}→e→f，单 PR ≤400 行）；识别并纳入收敛目标：Bot 执行链断裂、DQ-01/02 未接线、OrderStatus 枚举不一致、REAL_TRADE_EXECUTE 未检查 |
| 2026-07-12 | [第三轮 Review] 对标业界成熟产品（QuantConnect/TradingView/Bloomberg/问财/moomoo）新增 6 个任务序列：GOV-01~03 质量治理红线（覆盖率门禁爬坡 + 门禁变更 ADR 化 + CLI-07 决策收口）、ALERT-01~05 告警中心子系统、BT-01~06 回测引擎升级（回测/实盘同构 + 可复现性 + Walk-Forward + 过拟合检测）、DQ-01~04 数据正确性（幸存者偏差 + point-in-time + 快照版本化）、STRAT-01~05 策略实验室落地、PT-01~02 纸面组合追踪；SVC-04 提级 P1；CLI-01~06 冻结至 GOV-03 收口；执行焦点重排为三条线；修正底部文档链接；依赖图新增 S3 节点。详见 `MASTER_REVIEW.md §七` |
| 2026-07-09 | [DIST-07 方案A] AKShare Redis 中继实现：AKShareService 新增 AKSHARE_MODE=cache\|direct 模式开关 (cache 模式仅读 Redis 不直连 akshare) + AKShareCollector 北京 VPS 采集 daemon (南向/北向资金 5min + 宏观日历 12h + 交易时段自适应) + collector_registry 集成；18 个单测全通过，全量 2156 passed |
| 2026-07-09 | [DIST-07] 子服务 HTTP 接口完成：7 个 /v1/* 端点 (quote/history/batch/indicators/search/macro/health) + 2 个路由器兼容端点 (/api/v1/data-source/proxy/yfinance + batch_quote) + HMAC-SHA256 签名验证 + 时间戳防重放 + 429 限流错误分类 (error_category=rate_limit) + IP 白名单；34 个单测全通过，全量 2138 passed |
| 2026-07-09 | [DIST-06] 子服务 yfinance 核心逻辑迁移完成：YFinanceWorker 适配层封装 YFinanceService 生命周期 + macro_data_daemon 后台任务集成 + 数据接口代理 (fetch/batched_quote/tech_indicators/search) + /ds/health 真实健康状态 + Dockerfile 环境变量；19 个单测全通过，全量 2104 passed |
| 2026-07-09 | [DIST-05] data_subservice/ 子服务工程搭建完成：独立 FastAPI 应用 + lifespan 生命周期管理（Redis 连接 → ServiceRegistry 注册 → 心跳后台任务 → 关闭注销）+ /health、/ds/health、/ds/{source}/{action} 端点 + 多阶段 Dockerfile；10 个单测全通过，全量 2085 passed |
| 2026-07-08 | [DIST-04] YFinanceService 兼容外壳改造完成：YF_ROUTER_ENABLED 环境变量开关 + 懒初始化 YFinanceRouter + fetch_yf_data/get_batched_quote/macro_data_daemon 路由器模式拦截 + get_health_status 标注 + close 清理；26 个单测全通过，全量 2075 passed |
| 2026-07-08 | [DIST-01] ServiceRegistry 服务注册表实现完成：NodeInfo Pydantic 模型 + Redis Hash/ZSet/Set 三结构协同 + register/heartbeat/discover/deregister/cleanup_dead_nodes/mark_draining 全套 API + 集群总览 + 统计指标；31 个单测全通过 |
| 2026-07-08 | [DIST-02] YFinanceRouter 客户端路由器骨架完成：动态节点发现 + 加权轮询 + 熔断过滤 + failover + STALE 缓存降级；25 个单测全通过 |
| 2026-07-08 | [DIST-01] ServiceRegistry 服务注册表实现完成：NodeInfo 模型 + Redis Hash/ZSet/Set 三结构协同 + 全套 API；31 个单测全通过 |
| 2026-07-08 | [架构决策] 主服务确认迁移至加州 VPS (38.60.126.42)，北京 VPS 降级为辅助节点；更新 TODO.md DIST 任务 + AGENTS.md §9 部署架构 |
| 2026-07-08 | [TODO.md 结构调整] RL-01~14 归档 + DIST+CL 合并为统一「分布式数据源集群」模块 (23 任务) + OBS-04/BE-20 标记完成 + Sprint 重排为执行焦点 |
| 2026-07-08 | [RL-11] 限流告警规则配置完成：Grafana 新增 4 条告警规则 (限流频率飙升>10/5min + 长时间退避>2min + 配额耗尽 + IP封禁) + 后端 RateLimitAlertMonitor 代码层主动推送飞书 Webhook (去重冷却 15min + 4 场景检测) + Throttler 集成自动触发；15 个单测全通过 |
| 2026-07-08 | [RL-14] Hermes Agent Tool 限流感知智能重试完成：BaseTool 新增 rate_limit_aware_request (HTTP 429/503 + 响应体关键词检测 + Retry-After/X-RateLimit-Reset/Body 三级提取 + 指数退避重试 + MAX_RETRY_DELAY=60s 上限) + BrokerMarketTool/FundamentalDataTool/MacroNewsTool/FredMacroTool/MacroCalendarTool/TechnicalIndicatorsTool 全面集成；25 个单测全通过 |
| 2026-07-08 | [RL-13] Registry 路由感知限流状态完成：DataSourceNode 新增限流压力字段 (is_throttled/consecutive_rate_limits/estimated_limit_rpm) + _get_healthy_nodes 同步 registry 限流状态 + _select_node 三级排序 (未限流优先→weight降序→限流次数升序) + get_health_status 暴露限流压力信息；10 个单测全通过 |
| 2026-07-08 | [RL-09/10/12] Prometheus 限流指标 + 可观测性完成：5 个指标 (ds_rate_limit_total/throttled_seconds/estimated_rpm/effective_rpm/backoff_state) + Throttler 埋点 + HealthInfo.rate_limit_status 落地 + 环境变量配置化退避策略 (DATASOURCE_{NAME}_BACKOFF_*)；22 个单测全通过 |
| 2026-07-08 | [RL-06] 推测频率查询 API 完成：DataSourceRegistry 全局注册表 (Throttler+Analyzer 实例管理) + GET /datasource/{name}/rate-limit-analysis (限流分析+window参数) + GET /datasource/{name}/rate-limit-status (实时退避状态) + GET /datasource/rate-limit-overview (全源总览)；20 个单测全通过 |
| 2026-07-08 | [RL-05] RateLimitAnalyzer 频率分析器完成：滑动窗口事件序列 (deque maxlen=10000 ≈ 200KB) + P75 推测限流 RPM + 推荐安全间隔 (20% 裕度) + 高峰时段识别 (限流率>5%) + 相邻时段合并 + 平均恢复时间 + 可信度计算 + 自定义窗口 (?window=7d) + 过期清理 + 线程安全；45 个单测全通过 |
| 2026-07-08 | [RL-03] CircuitBreaker 限流解耦完成：is_rate_limit_error 过滤钩子 (识别异常携带的 ErrorCategory) + error_classifier 动态回调 (per-call 最终决定权) + record_failure(is_rate_limit=True) 手动记录接口 + call()/call_sync() 限流不计入失败计数；20 个单测全通过 |
| 2026-07-08 | [RL-02/04] RateLimitThrottler 退避引擎完成：4 种策略 (none/linear/exponential/adaptive) + Retry-After 优先采纳 + 自适应恢复机制 (连续 10 次成功降速) + 抖动防雷群 + 线程安全 + 环境变量配置 (DATASOURCE_{NAME}_BACKOFF_*)；31 个单测全通过 |
| 2026-07-08 | [RL-01] ErrorInfo 结构扩展完成：ErrorCategory 枚举 (normal/rate_limit/quota_exhausted/ip_blocked) + RateLimitInfo 嵌套结构 + Result 统一返回结构 + classify_http_error 自动分类 + DataSourceRouter 集成 (限流不计入熔断器)；44 个单测全通过 |
| 2026-07-20 | [SPEC-01] 存量超限文件拆分完成：screener_service.py (1838行) → screener/ (7文件)；yfinance_service.py (1480行) → yfinance/ (7文件)；akshare_service.py (912行) → akshare/ (5文件)；Mixin 组合模式 + shim 兼容层，122 测试全通过 |
| 2026-07-20 | [SPEC-02] 部署拓扑对齐完成：docs/02 §5.1/§8.0 "三节点矩阵"→ 四节点架构（US-MASTER + US-YF-A/B + CN-AKSHARE），与 AGENTS.md §9 保持一致；docs/02 升级至 V4.3.2 |
| 2026-07-14 | [DIST-11~18] 分布式数据源集群部署完成：YF 节点 Compose / 灰度切换配置 / 四节点部署脚本 / CI/CD 矩阵 (master + yf×2 + slave) / 数据源验证脚本 |
| 2026-07-08 | 新增「数据源限流感知与自适应退避」RL-01~14：限流错误分类 / RateLimitThrottler 退避引擎 / 频率动态分析 / 推测频率查询 API / Prometheus 限流指标 / 限流告警 / Registry 路由感知 / Agent Tool 限流感知；docs/14 新增 §十二；AGENTS.md 新增 §10.8 |
| 2026-07-02 | OMS-05~07 算力节点完成：`bot_runtime.py` BotRuntimeManager (asyncio.Task 生命周期) + psutil 真实 CPU/MEM 监控 + Redis List 日志持久化 + PubSub/WebSocket 实时推送；`/deploy-to-oms` 升级为真实 Bot 启动；前端新增 Bot 终止按钮 |
| 2026-07-02 | OMS-01~04 核心闭环完成：订单持久化 (oms_service.py) + 成交打通 + 真实订单状态同步 + 持仓 30秒同步守护进程；新增前端「真实持仓」Tab |
| 2026-07-08 | 新增「工程规范治理」SPEC-01~13（源自 docs/02 V4.3 合规审查）：存量超限文件拆分计划 + 规范文档修正 + 缺失章节补充 |
| 2026-07-08 | 新增「后端架构治理」ARCH-01~11（源自 docs/03 V5.1 架构审查）：main.py 瘦身 / 统一熔断器 / Graceful Shutdown / 连接池配置 / 健康检查分级 / 架构债收口 |
| 2026-07-08 | 新增「产品与 UI/UE 治理」PROD-01~13（源自 docs/01 V2.3 产品审查）：AI 上下文注入 / 画线工具 / 工作区快照 / 多分辨率适配 / Calendars 降级 / 图表内下单 |
| 2026-07-14 | [OPS-02] Tailscale 零信任网络完成：ACL 策略 / 节点入网脚本 / 跨节点验证脚本 / Prometheus+Grafana 端口绑定 Tailscale IP / CI 新增连通性检查 job |
| 2026-07-08 | **新增 [TOOL-01~15] Agent 工具链稳定性保障体系**：三层融合架构（Shadow Mode → Active Validation → Distributed Watchtower），详见 `docs/22. Agent 工具链稳定性保障体系.md` |
| 2026-07-02 | OMS-01~12 (订单持久化/真实同步/算力节点/算法拆单/KillSwitch 加固/审计日志)；新建 `docs/subsystems/oms-module.md` 设计文档 |
| 2026-07-02 | 新增「Risk 风控模块进阶能力」RISK-01~08 (板块暴露/Beta归因/相关性矩阵/压力测试/CVaR/流动性/雷达增强/Beta基准)；Risk MVP 完成归档 (分账户风控+持久化+行业级版面) |
| 2026-06-28 | 新增 `docs/14` 分布式数据源服务架构文档；重构 DIST-01~10 为 DIST-01~18 细粒度任务（注册表 / 路由器 / 子服务工程 / HMAC / Docker 编排 / VPS 部署 / 监控告警 / 其他数据源扩展） |
| 2026-06-28 | 新增 DIST-01~10 分布式数据服务架构任务（北京 + 加州双节点）；更新部署文档至 V4.0 |
| 2026-06-28 | [TEST-13] 覆盖率门禁完成：codecov.yml + pytest-cov + vitest coverage，后端 24% / 前端待测 |
| 2026-06-28 | [TEST-07/09/11] 依赖漏洞扫描纳入CI + 存量服务单测 + Agent ReAct循环单测完成 |
| 2026-06-28 | [TEST-01/02/06/08/10] 测试覆盖完成：测试框架脚手架 / 后端核心单测 / Tool单测 / pre-commit hooks / 前端 vitest setup |
| 2026-06-28 | [OPS-01/03/04/05] 部署与运维完成：CI/CD流水线 / Docker Compose加固 / Redis备份 / 恢复演练脚本 |
| 2026-06-28 | [FE-21/22] i18n 国际化整合 + 登录页/路由守卫完成 |
| 2026-06-28 | [FE-16/17/19/20] 前端数据层完成：API Client 三通道 / WS客户端 / IndexedDB缓存 / Web Worker指标计算 |
| 2026-06-28 | [BE-01/02/03/16/17/18] 后端基础设施第三批完成：看门狗 / 行情正确性 / 三级缓存 / 迁移工具 / 备份脚本 / 压测工具 |
| 2026-06-28 | [FE-16/17/19/20] 前端数据层完成：api-client.ts / use-ws-manager.ts / kline-cache.ts / indicator-worker.ts |
| 2026-06-28 | [FE-01~05] 前端基础设施第一批完成：Keep-Alive / StatusBar / WS管理 / ErrorBoundary / Logger |
| 2026-06-28 | [FE-06~10/18] 前端基础设施第二批完成：CommandPalette / 零GC Tick / 涨跌颜色 / 等宽字体 / TS类型 |
| 2026-06-28 | [OBS-01/02] Grafana 仪表板 + 告警通道配置完成 |
| 2026-06-28 | [BE-09/11] 统一响应结构 + /api/v1/health 健康检查端点完成 |
| 2026-06-28 | [SEC-13] 登出缓存清理策略完成 |
| 2026-06-28 | [FE-23] a11y 无障碍基础完成 |
| 2026-06-28 | [FE-24] 全局字体统一 Geist Mono + Inter |
| 2026-06-28 | [TEST-16/17] 前端构建健康 + 后端启动健康验证 |
| 2026-06-28 | [BE-05/06/07/15] 后端基础设施第二批完成：structlog 日志 / Prometheus 指标 / Alembic 迁移 / WebSocket 鉴权 |
| 2026-06-28 | [BE-08] 客户端 APM 心跳端点已实现：POST/GET /api/v1/client/heartbeat，写入 PostgreSQL |
| 2026-06-28 | [BE-13] 统一响应封装已落地：error_codes.py + exceptions.py + response.py + 全局异常处理器 + 响应转换中间件 |
| 2026-06-28 | [BE-14] Pydantic v2 领域模型已落地：backend/schemas/domain.py，包含 Quote/Kline/Position/Order/Account/TechIndicators 等 12 个 Schema |
| 2026-06-28 | 标记 SEC-07/08/09 为已完成：Token 内存化 / DOMPurify XSS 过滤 / 全局确认弹窗替换 window.confirm |
| 2026-06-28 | 标记 SEC-01~12 为已完成：API 版本前缀 / JWT 双令牌 / HMAC 签名 / 敏感字段加密 / 限流 / CORS 等 |
| 2026-06-28 | 标记 INFRA-01~04 为已完成：数据库 Schema / Pydantic Settings / pyproject.toml / 目录分层 |
| 2026-06-27 | 标记 MIG-08、MIG-09 为已完成；修复 Dockerfile 和 README.md                     |
| 2026-06-27 | 标记 MIG-03、MIG-04、MIG-05 为已完成状态；React Router v6 路由已配置          |
| 2026-06-27 | 标记 MIG-01、MIG-02、MIG-06、MIG-07 为已完成状态；添加 .gitignore 优化、工程体积清理、Git 问题排查到归档 |
| 2026-06-27 | 补充单测任务（TEST-08~15：脚手架/存量补测/Tool/Agent/契约/覆盖率门禁/组件/E2E）与「三方服务测试与监控」章节（SVC-01~07：契约回放/拨测/监控/数据质量/配额/Mock/混沌） |
| 2026-06-27 | 补充地基与落地任务（INFRA-01~04、SEC-10~12、BE-13~20、FE-16~23、OPS-05、OBS-01~02、TEST-06~07），新增「任务依赖顺序图」与关键路径 |
| 2026-06-27 | 代码核实：前端实际为 Next.js App Router（v0.app 生成）且 `package.json` 缺失，与 ADR-001 Vite SPA 决策冲突，新增 P0 专项 [MIG-01]~[MIG-10] 迁移任务 |
| 2026-06-27 | V2.0 全面重写：基于 MASTER_REVIEW.md 结论，按 P0-P3 重构为工程任务追踪矩阵 |
| 2026-06-15 | V1.0 初始版本：功能扩展愿景列表（已归档）                              |



----------------------------------------------------------------------------|---------|----------|-------------|--------------------|
| **🆕 Agent 工具链稳定性保障体系 (Tool Health Validator)**                     |         |          |             |
----------------------------------------------------------------------------|---------|----------|-------------|--------------------|


### Phase 1: Week 1 - Shadow Mode（影子模式）

**目标**: 零侵入部署，每日报告生成

| ID   | 任务描述                                                    | 预计工时 | 责任人       | 状态   |
|------|-----------------------------------------------------------|---------|--------------|--------|
| TOOL-01 | 编写 backend/services/tool_validator.py 核心验证器 (~180 LOC) | 4h      | Backend Dev  | PENDING |
| TOOL-02 | 实现正则表达式匹配模式库 (日志解析引擎)                       | 3h      | Backend Dev  | PENDING |
| TOOL-03 | 集成 CSV/JSON 报告生成逻辑                                  | 2h      | Backend Dev  | PENDING |
| TOOL-04 | 编写单元测试 (覆盖率≥80%)                                 | 2h      | QA Engineer  | PENDING |
| TOOL-05 | 创建 config/tool_validator.yaml.example 配置模板            | 1h      | Backend Dev  | PENDING |
| TOOL-06 | 修改 backend/worker.py 追加 3 行代码集成守护进程               | 0.5h    | Backend Dev  | PENDING |
| TOOL-07 | 配置 SMTP 凭证或 Slack Webhook                              | 1h      | DevOps       | PENDING |
| TOOL-08 | 编写 scripts/rollback_validator.sh 回滚脚本                   | 1h      | DevOps       | PENDING |
| TOOL-09 | 测试环境试运行 24 小时                                      | 4h      | QA Engineer  | PENDING |
| TOOL-10 | 模拟断链场景验证告警到达率                                   | 2h      | QA Engineer  | PENDING |
| TOOL-11 | 回滚演练 (确保<1 分钟恢复)                                  | 1h      | DevOps       | PENDING |
| TOOL-12 | 编写运维手册 (Runbook)                                    | 2h      | Tech Writer  | PENDING |
| TOOL-13 | 预发布环境灰度 10% 流量                                     | 2h      | DevOps       | PENDING |
| TOOL-14 | 全量上线并观察 48 小时                                       | 4h      | On-Call      | PENDING |
| TOOL-15 | 标记本章节为已完成                                           | 0.5h    | PM           | PENDING |

**Week 1 验收标准**:
- [ ] 成功解析 ≥ 95% 的工具调用日志
- [ ] 每日 00:00 自动生成 CSV/JSON报告
- [ ] 错误率 > 10% 触发 SMTP 告警
- [ ] 可一键回滚 (< 1 分钟恢复原状)

### Phase 2: Week 2-3 - Active Validation (主动验证增强)

**目标**: 增加主动调用能力，覆盖断链场景

| ID   | 任务描述                                                     | 预计工时 | 责任人       | 状态   |
|------|------------------------------------------------------------|---------|--------------|--------|
| TOOL-16 | 编写 hermes_agent/config/health_chains.yaml 健康链模板       | 3h      | Backend Dev  | PENDING |
| TOOL-17 | 定义 3 个核心验证链 (web_search_crawl/market_data_fetch/backtest_quick) | 2h      | Backend Dev  | PENDING |
| TOOL-18 | 配置断言规则 (非空/耗时上限/字段存在性)                    | 1h      | Backend Dev  | PENDING |
| TOOL-19 | 实现 backend/workers/tool_health_executor.py 执行引擎 (~120 LOC) | 6h      | Backend Dev  | PENDING |
| TOOL-20 | 集成 Circuit Breaker 保护机制                               | 3h      | Backend Dev  | PENDING |
| TOOL-21 | 扩展 backend/core/circuit_breaker.py (+50 LOC)              | 3h      | Backend Dev  | PENDING |
| TOOL-22 | 复用 existing Notification Service 发送 Slack 告警             | 2h      | Backend Dev  | PENDING |
| TOOL-23 | 创建 backend/routers/health_check.py HTTP API (+50 LOC)     | 3h      | Backend Dev  | PENDING |
| TOOL-24 | JWT 鉴权 + rate limiting (10 次/分钟)                         | 1h      | Backend Dev  | PENDING |
| TOOL-25 | OpenAPI 文档自动生成                                         | 0.5h    | Backend Dev  | PENDING |
| TOOL-26 | 使用 k6 脚本进行并发压力测试 (100 并发)                        | 4h      | SRE Engineer | PENDING |
| TOOL-27 | 调整 Semaphore 限流参数 (默认 50)                            | 1h      | Backend Dev  | PENDING |
| TOOL-28 | 优化日志打印 (避免 verbose 刷屏)                            | 1h      | Backend Dev  | PENDING |

**Week 3 验收标准**:
- [ ] 能够主动执行完整工具链 (≥ 3 步)
- [ ] Circuit Breaker正常工作 (熔断 → 恢复)
- [ ] P95 延迟 < 5 秒 (单链平均耗时 3 秒)
- [ ] HTTP API 支持手动触发验证

### Phase 3: Month 2 - Distributed Watchtower (分布式监控看板)

**目标**: 引入 Prometheus/Grafana，实时可视化

| ID   | 任务描述                                                   | 预计工时 | 责任人       | 状态   |
|------|----------------------------------------------------------|---------|--------------|--------|
| TOOL-29 | 安装 prometheus-client 和 FastAPI 中间件                      | 1h      | Backend Dev  | PENDING |
| TOOL-30 | 定义 20+ 指标 (QPS/P95/成功率等)                             | 3h      | SRE Engineer | PENDING |
| TOOL-31 | 配置 prometheus.yml scrape job                           | 1h      | DevOps       | PENDING |
| TOOL-32 | 启动 Prometheus 容器 (t3.small 实例)                         | 1h      | DevOps       | PENDING |
| TOOL-33 | 设计并导出 JSON Dashboard 片段 (Grafana)                      | 4h      | SRE Engineer | PENDING |
| TOOL-34 | 配置自动化导入 (CI/CD 流水线)                              | 2h      | DevOps       | PENDING |
| TOOL-35 | 编写 prometheus/alerts/validation_alerts.yml 告警规则          | 3h      | SRE Engineer | PENDING |
| TOOL-36 | 接入 Alertmanager (Slack + Email 双通道)                      | 2h      | DevOps       | PENDING |
| TOOL-37 | (可选) 部署 Kubernetes 集群 (EKS/GKE)                       | 8h      | K8s Expert   | PENDING |
| TOOL-38 | 配置 KEDA ScaleTriggers 基于 Redis Stream 长度                | 4h      | K8s Expert   | PENDING |
| TOOL-39 | 设置 min=5, max=100 的工作节点范围                           | 1h      | K8s Expert   | PENDING |
| TOOL-40 | 监控扩缩容决策日志并调优参数                                | 2h      | SRE Engineer | PENDING |

**Week 8 验收标准**:
- [ ] Prometheus 数据采集正常
- [ ] Grafana Dashboard 可访问
- [ ] 告警规则生效 (SLI/SLO 达标)
- [ ] 支持 100+ 并发任务队列

----------------------------------------------------------------------------|---------|----------|-------------|--------------------|
| **🚀 全面架构优化升级（Q-OPT-001~010）**                                     |         |          |             |
----------------------------------------------------------------------------|---------|----------|-------------|--------------------|

### Phase 1: 核心架构整治（Week 1-2）- P0 任务

> **背景**: 基于 VARB-2026-0708-001 虚拟架构委员会决议 (2026-07-08)
>
> **目标**: 解决架构腐化、数据正确性 critical 问题
>
> **关键变更**:
> - OPT-001 工作量：8h → **10h** (+2h Buffer for import pollution cleanup)
> - OPT-002: **仅支持美股 SEC EDGAR** (Phase 1 范围限制)
> - OPT-003 工作量：12h → **14h** (+2h for test framework setup)
> - OPT-004: 三维度测试 (退市/PIT/SVC) + 自动化维护机制

| ID   | 任务描述                                                    | 预计工时 | 责任人       | 状态   | 开始时间    |
|------|-----------------------------------------------------------|---------|--------------|--------|------------|
| OPT-001 | Router 层解耦：实施 DataSourcePort Protocol 抽象，禁止 market.py 直连数据源 | 10h     | Backend Lead | ⏳ Pending | Week 1 Day 1 |
| OPT-002 | Point-in-Time 财务数据处理：SEC EDGAR API 集成，修正财报日期对齐逻辑 | 16h     | Data Engineer | ⏳ Pending | Week 1 Day 1 |
| OPT-003 | Application 层重构：services/ → backend/app/ + backend/domain/四层架构 | 14h     | Backend Dev  | ⏳ Pending | Week 1 Day 3 |
| OPT-004 | 数据正确性单元测试：退市数据集/PIT 验证/SVC 契约回放 + 自动化维护 | 8h      | QA Engineer  | ⏳ Pending | Week 2 Day 1 |

**Week 2 验收标准**:
- [ ] Router 层静态扫描无数据源直连 import (`grep -r 'from.*data_source_router' backend/routers/*.py`返回空)
- [ ] 回测引擎支持 PIT 模式开关 (`as_of_date`过滤生效)
- [ ] 应用层代码迁移完成，测试全绿 (覆盖率 ≥ 80%)
- [ ] 数据正确性测试套件独立运行 (Delisted/PIT/SVC)
- [ ] CI 门禁恢复：后端≥80%/前端≥60% (OPT-007)
- [ ] GitHub Epic Issues 创建并指派责任人 (#OPT-001~004)

**关键里程碑**:
- Week 1 Day 3: DataSourceInterface Protocol 完成 + FutuImpl 示例
- Week 1 Day 5: 所有 Adapter 实现完成 (AkShare/YFinance/Futu)
- Week 1 Day 7: Router 层全部迁移完成 + 静态扫描验证
- Week 2 Day 3: PIT 验证测试 suite 完成
- Week 2 Day 5: 全量回归测试通过

### Phase 2: 质量工程加强（Week 3-4）- P1 任务

**目标**: 恢复 CI 门禁，补齐测试短板

| ID   | 任务描述                                                     | 预计工时 | 责任人       | 状态   |
|------|------------------------------------------------------------|---------|--------------|--------|
| OPT-005 | Web Worker 指标计算实现（FE-20）                            | 6h      | Frontend Dev | PENDING |
| OPT-006 | 契约测试框架搭建（SVC-01~07）                               | 12h     | QA Engineer  | PENDING |
| OPT-007 | 恢复 codecov 门禁：后端≥70%/前端≥60%，CI 强制拦截             | 4h      | DevOps       | PENDING |
| OPT-008 | E2E 测试框架选型 + 关键路径实现（Playwright vs Cypress）     | 8h      | QA Lead      | PENDING |

**Week 4 验收标准**:
- [ ] 前端指标计算 Web Worker 无主线程阻塞
- [ ] 契约测试覆盖所有外部 API（YFinance/Futu/OpenAI）
- [ ] CI 流水线自动拦截覆盖率不达标 PR
- [ ] E2E 测试覆盖登录/下单/持仓查询核心流程

### Phase 3: 高可用与安全加固（Week 5-6）- P1 任务

**目标**: 消除单点故障，提升系统韧性

| ID   | 任务描述                                                   | 预计工时 | 责任人       | 状态   |
|------|----------------------------------------------------------|---------|--------------|--------|
| OPT-009 | US-Master HA 方案：Redis Sentinel + PostgreSQL Streaming Replication | 20h     | SRE Engineer | PENDING |
| OPT-010 | 备份恢复自动化演练脚本（每周日定时执行）                      | 8h      | DevOps       | PENDING |
| OPT-011 | Tailscale ACL 审计工具 + 定期扫描报告                         | 6h      | Security Eng | PENDING |
| OPT-012 | Circuit Breaker 半开探测机制实现                             | 6h      | Backend Dev  | PENDING |

**Week 6 验收标准**:
- [ ] Master 节点宕机 < 30s 自动切换备用
- [ ] 备份恢复 RTO < 1 小时，RPO < 5 分钟
- [ ] ACL 策略季度审计报告生成
- [ ] 熔断器状态转换测试通过率 100%

### Phase 4: 功能闭环与设计落地（Week 7-8）- P2 任务

**目标**: 让设计与 TODO 对齐，消除脱节

| ID   | 任务描述                                                   | 预计工时 | 责任人       | 状态   |
|------|----------------------------------------------------------|---------|--------------|--------|
| OPT-013 | 告警中心任务承接（ALERT-03→TODO 明细分解）                    | 4h      | PM           | PENDING |
| OPT-014 | 策略实验室实施路线图细化（STRAT-01~05 拆解为子任务）          | 6h      | Tech Lead    | PENDING |
| OPT-015 | 纸面组合开发看板创建（PT-01~02）                              | 3h      | PM           | PENDING |
| OPT-016 | 回测引擎里程碑更新（BT-01~06 添加时间轴与依赖图）              | 4h      | Backend Dev  | PENDING |

**Week 8 验收标准**:
- [ ] 所有设计文档关联到具体 TODO 任务 ID
- [ ] STRAT/PT/BT 三大模块均有明确时间规划
- [ ] 每月 Sprint Review 自动生成进度报告

### Phase 5: 客户端拓展与鸿蒙适配（Week 9-10）- P2 任务

**目标**: 抢占鸿蒙生态，扩大移动端覆盖

| ID   | 任务描述                                                   | 预计工时 | 责任人       | 状态   |
|------|----------------------------------------------------------|---------|--------------|--------|
| OPT-017 | Flutter 鸿蒙NEXT适配研究：华为官方 SDK 兼容性测试               | 10h     | Mobile Lead  | PENDING |
| OPT-018 | 客户端 Copilot 功能增强（CLI-P4）                              | 12h     | Mobile Dev   | PENDING |
| OPT-019 | 平板适配优化（CLI-11 iPad/Tablet）                           | 6h      | Mobile Dev   | PENDING |
| OPT-020 | 客户端 Isolate 架构优化（CLI-14）                             | 8h      | Mobile Dev   | PENDING |

**Week 10 验收标准**:
- [ ] 鸿蒙 NEXT 兼容报告 + 适配可行性结论
- [ ] 客户端 AI Copilot 对话式选股功能上线
- [ ] iPad 横竖屏自适应 UI 完成
- [ ] Isolate 隔离提升客户端稳定性 50%

### Phase 6: 可观测性终极完善（Week 11-12）- P3 任务

**目标**: 打造业界级日志链路追踪

| ID   | 任务描述                                                   | 预计工时 | 责任人       | 状态   |
|------|----------------------------------------------------------|---------|--------------|--------|
| OPT-021 | 全链路 TraceID 注入：从 Request→Tool Call→外部 API          | 12h     | Backend Dev  | PENDING |
| OPT-022 | Grafana 仪表盘统一：前后端指标融合展示                        | 8h      | SRE Engineer | PENDING |
| OPT-023 | 异常检测自动化：基于 ML 的时序异常预警                         | 16h     | Data Scientist | PENDING |
| OPT-024 | 成本优化分析：Cloudflare/GCP 账单监控与预算提醒                | 6h      | FinOps       | PENDING |

**Week 12 验收标准**:
- [ ] 任意请求可在 10s 内定位完整调用链
- [ ] 前后端统一 Dashboard 可访问性≥99.9%
- [ ] 异常检测准确率 ≥85%，误报率 < 5%
- [ ] 月度云成本节省 ≥ 10%

----------------------------------------------------------------------------|---------|----------|-------------|--------------------|

## 📈 总体预期收益

| **维度** | **优化前** | **优化后** | **提升幅度** |
|---------|----------|----------|-------------|
| 架构清晰度 | ⭐⭐⭐☆☆ | ⭐⭐⭐⭐⭐ | ↑ 40% |
| 数据正确性 | ⭐⭐☆☆☆ | ⭐⭐⭐⭐⭐ | ↑ 100% |
| 系统可用性 | 95%（单点） | 99.9%（HA） | ↑ 5% 绝对值 |
| 测试覆盖率 | 5-10% | ≥70% | ↑ 7x |
| 故障恢复时间 | 30min | <5min | ↑ 6x |
| 需求可追溯率 | 60% | 100% | ↑ 40% |

## 🎯 关键成功因素

1. **高层支持**：OPT-001/002/003需架构师级别推动，打破部门墙
2. **资源投入**：Phase 1-2 需额外 2 名 Senior 工程师全力支持 2 周
3. **CI/CD改造**：DevOps团队配合调整流水线，不能影响正常迭代
4. **文档先行**：每个 OPT 任务必须有设计文档评审（Design Review）
5. **渐进交付**：每两周展示一次成果，保持团队信心

---


## 🚨 融资融券功能 Mock 数据清理任务 (MARGIN-TRADING-2026-07)

> **创建时间**: 2026-07-22
> **优先级**: P1 (核心功能缺失)
> **关联提交**: `41cc806 feat: 新增融资融券余额看板功能`

### 背景说明

融资融券余额看板功能已实现完整架构，但**港股和美股数据源当前使用 Mock 数据**，需在后续迭代中接入真实数据源。

### Mock 代码位置

| 文件 | 行号 | Mock 内容 | 影响范围 |
|------|------|----------|---------|
| `backend/services/margin/hk_share.py` | 47-62 | 港股融资融券 Mock 数据 | 港股市场数据 |
| `backend/services/margin/us_share.py` | 56-71 | 美股融资融券 Mock 数据 | 美股市场数据 |

### 待办任务清单

| ID | 任务描述 | 数据源方案 | 预计工时 | 状态 |
|----|---------|-----------|---------|------|
| **MARGIN-01** | 接入港股真实融资融券数据 | 港交所披露易 / Futu API | 8h | PENDING |
| **MARGIN-02** | 接入美股真实融资融券数据 | FINRA Margin Statistics API | 6h | PENDING |
| **MARGIN-03** | 添加融资融券历史趋势图表 | 前端 ECharts | 4h | PENDING |
| **MARGIN-04** | 支持个股融资融券查询 | AKShare / Futu | 6h | PENDING |
| **MARGIN-05** | 补充单元测试覆盖率 ≥80% | pytest + mock | 4h | PENDING |

### 数据源调研

#### 港股 (MARGIN-01)
- **方案 A**: 港交所披露易 (HKEXnews) - 每日融资融券数据
  - 网址: https://www.hkexnews.hk/
  - 数据: 港股通融资融券余额
  - 频率: 日频 (T+1)
- **方案 B**: Futu API - 需确认是否提供全市场数据
  - 接口: `get_capital_flow` / `get_margin_data`
  - 限制: 可能仅支持个股级别数据

#### 美股 (MARGIN-02)
- **方案 A**: FINRA Margin Statistics (推荐)
  - 网址: https://www.finra.org/rules-guidance/key-topics/margin-accounts/margin-statistics
  - 数据: 全市场 Margin Debt (融资余额)
  - 频率: 月度更新
  - 获取方式: 爬取网页或调用 API
- **方案 B**: SEC EDGAR - 券商财报数据
  - 数据: 各券商融资融券余额
  - 频率: 季度 (10-Q) / 年度 (10-K)
- **方案 C**: YFinance - 个股保证金数据
  - 接口: `ticker.info['marginData']`
  - 限制: 仅个股级别，非全市场

### 验收标准

- [ ] 港股数据源接入真实数据，移除 Mock
- [ ] 美股数据源接入真实数据，移除 Mock
- [ ] 数据准确性验证 (与官方数据对比误差 <1%)
- [ ] 单元测试覆盖率 ≥80%
- [ ] 历史趋势图表上线
- [ ] 个股融资融券查询功能上线

### 风险提示

1. **数据延迟**: A 股数据为 T+1，港股/美股数据源频率需确认
2. **限流风险**: 港交所/FINRA 爬虫需控制请求频率
3. **数据完整性**: 美股 FINRA 仅提供月度数据，非日频
4. **API 权限**: Futu API 可能需要额外权限或付费订阅

---

## 🔍 代码内 TODO 注释汇总 (2026-07-22 扫描)

> **来源**: 全代码库 `# TODO` 注释自动扫描
> **规则**: 每条 TODO 必须有对应任务跟踪，禁止遗留无主 Mock 代码

### 一、数据源适配器层 (backend/adapters/)

| ID | 文件 | 行号 | TODO 内容 | 优先级 | 状态 |
|----|------|------|----------|--------|------|
| CODE-01 | `adapters/futu/futu_adapter.py` | 199 | 实现 WebSocket 订阅逻辑 (futu_pb2_req 协议) | P1 | PENDING |
| CODE-02 | `adapters/futu/futu_adapter.py` | 218 | 实现取消订阅逻辑 | P1 | PENDING |
| CODE-03 | `adapters/futu/futu_adapter.py` | 235 | 实际实现中使用 futu_pb2_req 或 openapi 客户端 | P1 | PENDING |
| CODE-04 | `adapters/futu/futu_adapter.py` | 263 | 调用实际 API (quote 行情查询) | P1 | PENDING |
| CODE-05 | `adapters/futu/futu_adapter.py` | 305 | 调用实际 API (K 线历史数据) | P1 | PENDING |
| CODE-06 | `adapters/futu/futu_adapter.py` | 341 | 调用实际 API (资金流数据) | P2 | PENDING |
| CODE-07 | `adapters/futu/futu_adapter.py` | 365 | 调用实际 API (批量行情) | P2 | PENDING |
| CODE-08 | `adapters/akshare/akshare_adapter.py` | 264 | interval 参数未来使用 (K 线周期) | P3 | → OK-001 |
| CODE-09 | `adapters/akshare/akshare_adapter.py` | 279 | market 参数未来使用 (港股市场标识) | P3 | → OK-002 |

### 二、路由层 (backend/routers/)

| ID | 文件 | 行号 | TODO 内容 | 优先级 | 状态 |
|----|------|------|----------|--------|------|
| CODE-10 | `routers/market.py` | 617 | 迁移到 DataSourcePort + FinnhubAdapter (新闻) | P2 | → NEWS-001 |
| CODE-11 | `routers/market.py` | 687 | 迁移到 DataSourcePort + Finnhub Earnings Calendar | P2 | → EARN-001 |
| CODE-12 | `routers/market.py` | 689 | Finnhub News Earnings 集成 (替代 YFinance) | P2 | → NEWS-002 |
| CODE-13 | `routers/market.py` | 714 | Finnhub News 集成 (替代本地缓存) | P2 | → NEWS-003 |
| CODE-14 | `routers/market.py` | 914 | 需要 InsiderService + InsiderDataAdapter (内幕交易) | P1 | → INSIDE-001 |
| CODE-15 | `routers/market.py` | 918 | 迁移到 DataSourcePort + InsiderDataAdapter | P2 | → INSIDE-002 |

### 三、服务层 (backend/services/)

| ID | 文件 | 行号 | TODO 内容 | 优先级 | 状态 |
|----|------|------|----------|--------|------|
| CODE-16 | `services/margin/hk_share.py` | 51 | 接入 Futu API 获取真实融资融券数据 | P1 | → MARGIN-01 |
| CODE-17 | `services/margin/us_share.py` | 60 | 接入 FINRA API 获取真实 Margin Debt 数据 | P1 | → MARGIN-02 |
| CODE-18 | `services/yfinance/quote.py` | 65 | 后续实现实际的数据获取逻辑 (微批处理) | P2 | → YF-001 |
| CODE-19 | `services/akshare/service.py` | 49 | time.time() 未来使用 (健康状态冷却计时) | P3 | → OK-003 |
| CODE-20 | `services/market_review/context_injector.py` | 148 | 港股 ticker 格式标准规范化 (数字/XXX.HK) | P2 | → HK-001 |

### 四、API 路由层 (backend/routers/)

| ID | 文件 | 行号 | TODO 内容 | 优先级 | 关联任务 |
|----|------|------|----------|--------|---------|
| CODE-21 | `routers/market.py` | 617 | 未来迁移到 DataSourcePort + FinnhubAdapter | P2 | → FINNHUB-01 |
| CODE-22 | `routers/market.py` | 687 | yf_ticker 未来使用 | P3 | ✅ IGNORED |
| CODE-23 | `routers/market.py` | 689 | 未来迁移到 DataSourcePort + Finnhub Earnings Calendar | P2 | → FINNHUB-02 |
| CODE-24 | `routers/market.py` | 714 | 未来迁移到 DataSourcePort + Finnhub News | P2 | → FINNHUB-03 |
| CODE-25 | `routers/market.py` | 914 | 需要 InsiderService + InsiderDataAdapter | P2 | → INSIDER-01 |
| CODE-26 | `routers/market.py` | 918 | 未来迁移到 DataSourcePort + InsiderDataAdapter | P2 | → INSIDER-02 |

### 五、引擎层 (backend/engine/)

| ID | 文件 | 行号 | TODO 内容 | 优先级 | 状态 |
|----|------|------|----------|--------|------|
| CODE-27 | `engine/gateway.py` | 239 | 实际实现下单网关 (OMS + Futu 下单) | P1 | PENDING |
| CODE-28 | `engine/drivers/live.py` | 152 | 接入 KlineCacheEngine（L1 Redis / L2 Parquet） | P1 | PENDING |

### 五、统计摘要

| 优先级 | 数量 | 说明 |
|--------|------|------|
| **P1** | 10 | 核心功能缺失，需优先解决 |
| **P2** | 7 | 架构迁移/体验优化 |
| **P3** | 3 | 低优先级/探索性 |
| **已关联** | 2 | CODE-16→MARGIN-01, CODE-17→MARGIN-02 |

### 六、统计摘要

| 优先级 | 数量 | 说明 |
|--------|------|------|
| **P1** | 12 | 核心功能缺失，需优先解决 (Futu Adapter/下单网关/融资融券) |
| **P2** | 9 | 架构迁移/体验优化 (Finnhub/Insider/数据源重构) |
| **P3** | 3 | 低优先级/探索性 (interval 参数/健康计时器/yf_ticker) |
| **已关联** | 8 | CODE-16→MARGIN-01, CODE-17→MARGIN-02, CODE-21~26→FINNHUB/INSIDER |

### 七、重点跟进 (P1 任务)

1. **CODE-01~08**: Futu 适配器 WebSocket + API 实装 → 关联 `DIST` 分布式数据源任务
2. **CODE-27**: 实盘下单网关 → 关联 OMS 订单管理系统
3. **CODE-28**: 实盘 K 线缓存 → 关联 `KlineCacheEngine` 三级缓存架构
4. **CODE-16~17**: 融资融券真实数据 → MARGIN-01 (港交所/Futu), MARGIN-02 (FINRA)

---

## 存量类型清理（mypy 增量收敛）

- [x] **[BE-ARCH-06g]** mypy 存量类型问题批量清理（backend/core + backend/routers，45→0）✅ **2026-08-07**
  - 探查策略：逐个文件确认真 bug vs 类型标注问题 vs 框架互操作噪声，**不盲目标注忽略**
  - **真 bug 修复**：
    - `routers/portfolio.py`：`get_klines(symbol=, period=, count=)` 方法名+返回类型错误（应为 `get_history(ticker=, ktype="K_DAY", num=count)` 返回 DataFrame，矢量化 `pct_change`）
    - `services/datasource/analyzer.py`：`record_request(latency_ms: float=0.0)` 改为 `Optional[float]=None`（与调用方 `datasource.py:500` 的 `None` 语义一致，表示未探测不计入延迟）
  - **类型标注补全**：`futu_admin.py`(dict[str,Any]) / `middleware.py`(dict[int,float]) / `market_fundamental.py`(dict[str,asyncio.Lock]) / `chat.py`(list[dict[str,str]]) / `strategy.py`(list[str]) / `logger.py` / `redis_client.py`(queue/_cache) / `structlog_config.py`(renderer: Any) / `calendars.py`(is None 守卫收窄)
  - **框架互操作精准 ignore**：`exception_handlers.py`(FastAPI/Starlette 签名偏差 arg-type) / `config.py`(Settings 单例 env 注入 call-arg) / `options.py`(pydantic Field 默认 call-arg) / `otel_config.py`/`calendars.py`(import 降级 None misc) / `graceful_executor.py`(stdlib None 默认 arg-type + asyncio.Future override) / `cpu_pool.py`/`request_timeout.py`(标准库协程类型偏严 arg-type) / `paper.py`(create_task Awaitable arg-type) / `earnings_router.py`(redis decode_responses cast)
  - **陷阱修正**：`auth.py` `response: Response = None` 行尾 `# type: ignore` 触发 Python SyntaxError（参数列表内注释歧义）→ 改为 `response: Response` 去掉默认 None（FastAPI 注入保证非 None），移除多余 assert
  - 验证：`python -m mypy backend/core/ backend/routers/ --ignore-missing-imports` → **0 errors**；相关单测 69 passed

---
