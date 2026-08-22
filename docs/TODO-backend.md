# 🏗️ TODO — 后端与架构（拆分自 TODO.md 2026-08-13）

### 基础设施前置（阻塞后端所有开发）

> 文档已定义规范（`docs/11` Schema、`docs/10` 契约），但缺落地任务。以下是后端一切功能的地基。

- [x] **[INFRA-01]** 落地 `docs/11` 的 PostgreSQL Schema：建表脚本（users/orders/knowledge_chunks/audit_logs/client_heartbeats）+ 安装 `pgvector` 扩展 + 初始化迁移
- [x] **[INFRA-02]** `.env.example` 规范化 + 启动时配置校验（Pydantic Settings 强类型校验，缺失关键配置直接 fail-fast）
- [x] **[INFRA-03]** 后端依赖管理迁移到 `uv` / `pyproject.toml`，锁定版本，替代裸 `requirements.txt`
- [x] **[INFRA-04]** 后端目录分层落地：`routers / services / workers / core` 物理隔离（对照 `docs/03` 与 `docs/subsystems/backend`）

### 后端安全

- [x] **[SEC-01]** 所有对外 API 增加 `/api/v1/` 版本前缀，禁止裸路径（如 `/macro/data-center` → `/api/v1/macro/data-center`）
- [x] **[SEC-02]** 实现 JWT 双令牌体系（15min Access Token + 7d Refresh Token with rotation）
- [x] **[SEC-03]** 内部节点间通信强制 HMAC-SHA256 签名验证（`X-Internal-Sig` header），防止内网横向渗透
- [x] **[SEC-04]** 敏感字段加密落库：API Key、账户信息一律通过 AES-256-GCM 加密，不得明文写入 PostgreSQL
- [x] **[SEC-05]** 限流中间件：对 `/api/v1/` 所有路由添加自定义 Redis 原子计数器速率限制（100 req/min/IP）
- [x] **[SEC-06]** Futu OpenD 连接密码必须从 `.env` 注入，禁止任何硬编码出现在代码中
- [x] **[SEC-10]** 认证闭环落地：后端 `/api/v1/auth/login` `/refresh` `/logout` 接口实现（对照 `docs/10` §2），Refresh Token 写 HttpOnly Cookie
- [x] **[SEC-11]** CORS 白名单配置：仅允许已知前端域名 + Cloudflare Pages 域，禁止 `*`
- [x] **[SEC-12]** 审计日志落地：登录、模拟/实盘下单、配置变更、Kill Switch 等敏感操作写入 `audit_logs` 表（携带 `trace_id` + IP）

### 质量治理红线（2026-07-12 第三轮 Review 新增，见 `MASTER_REVIEW.md §7.3`）

- [x] **[GOV-01]** 覆盖率门禁爬坡机制：TEST-13 门槛曾从 70%/60% 静默降至 5%/10%（未走决策流程）。建立每月 +5% 的爬坡计划写入 CI（codecov.yml `target` 逐月上调），最终恢复后端 ≥70% / 前端 ≥60%；当月未达标阻断合并 ✅ **爬坡计划已写入 codecov.yml + MASTER_REVIEW.md §7.5**
- [x] **[GOV-02]** 质量门禁变更治理：覆盖率门槛、lint 规则豁免、CI 必过项的任何放宽必须在 `MASTER_REVIEW.md` 记录 ADR（原因 + 恢复期限），禁止在配置文件中静默修改 ✅ **ADR-COV-01 已记录于 §7.5**
- [x] **[GOV-03]** CLI-07 决策收口（限期 2 周）：完成 Flutter vs Tauri Mobile 对比评估，输出 ADR-006 终审结论写入 `MASTER_REVIEW.md`；决策落定前冻结所有 CLI-01~06 开发投入，防止方向反复 ✅ **ADR-006 已输出：确认 Flutter 三端，否决 Tauri Mobile**

### 安全红线补漏（2026-07-12 第三轮 Review 补充，见 `MASTER_REVIEW.md §四`）

- [x] **[SEC-14]** Redis 端口（6379）收敛：docker-compose.yml 改为仅 Docker 内网访问（移除 `ports: 6379:6379`），应用容器通过 `quant-internal` 网络直连 ✅ **expose 替代 ports，master 节点绑定 Tailscale IP**
- [x] **[SEC-15]** PostgreSQL 端口（5432）收敛：同上，移除公网暴露，仅内部网络可达 ✅ **expose 替代 ports**
- [x] **[SEC-16]** VPS SSH 加固：关闭密码登录（`PasswordAuthentication no`）、改用非标端口、密钥认证；记录至运维手册 `docs/12` ✅ **§七 安全加固清单已落地**

### 文档治理（2026-07-12 第三轮 Review 补充，见 `MASTER_REVIEW.md §7.3 #4`）

- [x] **[DOC-04]** `docs/01` §十二 路线图收口：V2.2 已声明 `TODO.md` 为任务 SSOT，§十二 仅作产品索引并标注 FE-PROD/BT/ALERT 任务 ID ✅ **2026-07-13 V2.2 落地**
- [x] **[DOC-05]** 北京节点冷备启动脚本：最低限度 DR 预案 ✅ **2026-08-09**：新建 `scripts/disaster_recovery/bj_cold_standby.sh`，覆盖 ① R2 异地备份拉取（PG dump + Redis RDB，依赖 docs/12 的每日 03:00/03:30 备份计划）② PostgreSQL 恢复 ③ Redis RDB 恢复（停写替换）④ 北京节点 `docker-compose.node-bj.yml` 拉起 `data_subservice`（DS_CAPABILITIES=tushare,akshare,yfinance）⑤ 主服务 `.env` 远程源降级指向北京 Tailscale IP 并待人工重启 ⑥ RTO 计时（<4h 预算）。支持 `--dry-run` / `--skip-restore`；`bash -n` 语法校验通过。缺点：备份侧 `scripts/backup-redis.sh` / `backup-pg.sh` 在 docs/12 计划中仍缺失（仅恢复侧就绪），建议作为后续独立任务补备份脚本。

---


## 🟠 P1 — 核心功能缺失（本迭代完成）

### 后端基础设施

- [x] **[BE-01]** K线实时管道：Futu OpenD → ZeroMQ → Redis Streams → WebSocket 全链路压测，目标 P99 < 50ms
- [x] **[BE-02]** 三级历史 K线缓存：Redis Hash（热，近 5 日）→ DuckDB/Parquet（温，1年）→ 对象存储（冷，>1年）
- [x] **[BE-03]** Futu OpenD systemd 守护 + Python asyncio 看门狗（断连自动重连，重连间隔指数退避）
- [x] **[BE-04]** 熔断器（Circuit Breaker）：外部 API（Futu / YFinance / OpenAI）连续失败 3 次后触发 Open 状态，60s 后进 Half-Open
- [x] **[BE-05]** 结构化日志全覆盖：`structlog` + JSON 格式，必须携带 `trace_id`、`symbol`、`latency_ms` 字段
- [x] **[BE-06]** Prometheus metrics 端点 `/metrics` 暴露：行情延迟分位数、WebSocket 连接数、Redis 队列深度
- [x] **[BE-07]** Alembic 数据库迁移脚本规范化（每次 schema 变更必须生成可回滚的 migration 文件）
- [x] **[BE-08]** 客户端 APM 心跳接收端点 `POST /api/v1/client/heartbeat`，写入 PostgreSQL 供 Dashboard 展示
- [x] **[BE-13]** 统一响应封装中间件 + 全局异常处理器：落地 `{code,msg,data,ts}` 结构与 `docs/10` §1.4 错误码表，禁止各路由自定义格式
- [x] **[BE-14]** Pydantic v2 领域模型落地：按 `docs/11` 定义 Quote/Kline/Position/Order/Account/TechIndicators 等 Schema，作为 API 出入参强类型校验
- [x] **[BE-15]** WebSocket 网关完整化：连接鉴权（token 校验）+ ping/pong 心跳保活 + 订阅管理（subscribe/unsubscribe 去重）+ drop-oldest 背压策略
- [x] **[BE-16]** 行情数据正确性（量化命门）：K线复权处理（前复权/后复权切换）、停牌/退市标的标记、UTC 时区统一与各市场交易时段对齐
- [x] **[BE-17]** pgvector 知识库迁移工具：建表/建索引脚本 + 向量数据导出/导入（经 Cloudflare R2 跨节点迁移）+ 超 90 天旧片段定时清理
- [x] **[BE-18]** PostgreSQL 每日 `pg_dump` 备份到 Cloudflare R2（补齐 OPS-04 仅有 Redis 的缺口）

### 后端整洁架构收口（2026-07-13 新增，`docs/03` V5.1）

> 📐 **架构规范已完成**：`docs/03` V5.1（依赖矩阵 · Ports · 插件/热加载分级 · Frozen 映射）。下列任务渐进落地，**新代码禁止新增 Router→具体数据源 import**。

- [x] **[BE-ARCH-01]** Router 去数据源直连：`market`/`strategy`/`macro`/`backtest`/`trade` 等改为只调 Application / QuotePort / DataSource Registry；存量直连标 Legacy 并按文件分 PR 收敛（测试：Router 层无 `futu_service`/`yf_service` import，≥70%）✅ **2026-07-13**：`domain/ports.py` + `app/market_data|broker` + Legacy Gateway；21/21 Router 清零直连；`test_be_arch01_router_boundary.py`
- [x] **[BE-ARCH-02]** Application / Domain 目录落地：新增用例进 `backend/app/`（或 `*_app.py`）+ Port 定义进 `domain/`/`engine/`；禁止继续向扁平 `services/` 堆编排逻辑（与 BT-01a 协同，可并行起步）✅ **2026-07-13**：`app/oms_app|backtest_app|system_app` 用例编排；OMS Kill Switch / 回测 / APM Dashboard Router 变薄；扁平 `services/*.py` allowlist 冻结；`test_be_arch02_app_boundary.py`
- [x] **[BE-ARCH-03]** Collector 真正插件化：`start_collector_daemons` 改为 factory 表，去掉对 `yf_service` 等硬编码 import（测试：启停矩阵，≥80%）✅ **2026-07-13**：`workers/collectors/{akshare,futu,finnhub,yfinance}.py` factory；`CollectorDef.factory` + `stop_collector_daemons`；`start_collector_daemons` 零具体服务 import；`test_be_arch03_collector_plugin.py` + 启停矩阵
- [x] **[BE-ARCH-04]** DataSource 双 Registry 澄清：限流 Registry vs 源实例 Registry 命名/职责拆分，对齐 docs/14；主路径 `fetch` 只经 Interface（依赖 DIST/RL 已有能力）✅ **2026-07-13**：`RateLimitRegistry`（原误名 DataSourceRegistry）+ 真·`DataSourceRegistry`（`DataSourceInterface`）；YFinance Legacy Adapter + `market_data.fetch_yf_data` 经 `datasource_registry.fetch`；`test_be_arch04_dual_registry.py`
- [x] **[BE-ARCH-06]** 业务数据源聚合 Facade（设计稿 `docs/23. 业务数据源聚合Facade设计.md`，P1）：在 `DataSourceInterface` 薄适配器之上新增 **业务聚合 Facade 层**，收口"策略逻辑 + 业务级检测 + 多源融合 + 归一化"，Tools/业务逻辑只调 Facade 业务语义接口，禁止直连具体数据源库或直发外部 HTTP（红线见文档 §二）。拆分原子任务： ✅ **2026-08-06** 全原子任务完成（a-e）
  - [x] **[BE-ARCH-06a]** 骨架：`backend/services/datasource/business/__init__.py` + `facade.py`，实现 `DataServiceFacade`（`data_service` 单例），仅经 `datasource_registry.fetch` 取数；落地 4 个策略原语 `_select_source` / `_merge` / `_detect_stale` / `_normalize` + 单测 ✅ **2026-08-06**：`business/facade.py` + `business/__init__.py` + `tests/test_be_arch06_facade.py`（11 passed）；修复 0.0 时间戳 falsy 跳过
  - [x] **[BE-ARCH-06b]** 行情领域 `market.py`：业务语义 `get_quote` / `get_history` / `get_fund_flow` / `get_option_chain`（含源选择权重、Stale 检测、OHLCV 归一化）✅ **2026-08-06**：`business/market.py` + `business/__init__.py` 导出 + `tests/test_be_arch06b_market.py`（9 passed）
  - [x] **[BE-ARCH-06c]** 示范接入：把 `/market/quote` 路由改为优先经 `market_data_service.get_quote`（Facade→Registry→Router→薄适配器），失败回退既有 `MarketDataService`；保留降级路径 ✅ **2026-08-06**：`routers/market.py` QUOTE 分支
  - [x] **[BE-ARCH-06d]** 指标补全：Facade 层 `DATASOURCE_FACADE_MERGE` / `DATASOURCE_QUOTE_DEVIATION` 业务级指标，与现有 `DATASOURCE_*` 分层 ✅ **2026-08-06**：`core/metrics.py` 新增 + `facade.py` 接入（融合计数 / 偏差告警）
  - [x] **[BE-ARCH-06e]** 文档收口：更新 `docs/14 §二.5` 业务聚合 Facade 层 + §8/§10.1 映射 + `docs/07` 速查手册三层架构 ✅ **2026-08-06**
  - [x] **[BE-ARCH-06f]** 宏观经济日历收口：把已注册但仅走 Registry 直连投票的 `fred` / `dbnomics` / `rbi` 三源经 Facade 统一聚合，新增 `DataServiceFacade.get_economic_calendar`（多源 `economic_calendar` 融合 + CPI actual 回填互补 + 全源失败降级）；`MacroDataService` 暴露该域方法；新增 `/macro/economic-calendar` 路由走 Facade（不动 akshare 既有事件日历，避免回归）；配套单测 + 更新 `docs/23` ✅ **2026-08-07**：`facade.py`（`_merge_calendar_events` + `ECONOMIC_CALENDAR` 分支 + 权重 `dbnomics/rbi=55` + 域方法）/ `business/macro.py` 域方法 / `app/macro_app.py` 薄包装 / `routers/macro.py` `GET /macro/economic-calendar` / `tests/test_be_arch06f_economic_calendar.py`（7 passed）；全 06 系列 27 passed

### 数据服务红线收口（BE-ARCH-07 系列 · 2026-08-09 数据服务架构审计）

> 🔍 **审计结论（对照 `docs/23` §二红线 + `AGENTS.md` §9.1/§10）**：四层骨架（Tools → Facade → Registry/Router → 薄适配器 → `data_subservice`）已落地，`business/` 目录零直连、四策略原语为真实现；但**主服务侧仍有大面积 legacy 连接层活在生产路径上**，最严重的是主行情入口 `QuotePort.get_quote` 直连本地 Futu SDK，完全绕过 Registry/Router。前端与 Flutter 侧干净（仅打后端 baseURL）。
>
> ⚠️ **铁律复述**：外部数据源连接层**只允许**存在于 `data_subservice/`；主服务一切取数经 `datasource_registry.fetch` / `data_source_router.fetch_*`；Hermes Tools 禁止直发外网。下列任务按 P0 → P2 分级，**每条附精确错误代码指引**，逐个原子提交。

#### P0 · 主行情路径违规与死逻辑（阻塞"仅远程"架构收敛）

- [x] **[BE-ARCH-07a]** **QuotePort 的 Futu 路径切 Registry/Facade**（最高优先）：`backend/services/adapters/legacy_market_data.py:89-103` 的 `get_quote` / `get_history` / `get_fund_flow` / `get_warrant_chain` / `get_option_chain` 全部打向 `self.futu`（= 主服务本地 OpenD 客户端，懒加载入口 `:41-45`）。生产调用方：`backend/routers/market.py:14`、`backend/routers/market_fundamental.py:19`（`market_data_gateway` 单例）。改法：改走 `data_service.get_quote/get_history/...`（`backend/services/datasource/business/facade.py:104-198`）或 `datasource_registry.fetch("futu", ACTION, params)`；**同文件已有合规范例可直接照抄** —— YFinance `:406`/`:425`、Registry `:412-414`、Finnhub `:530-532`。验收：`legacy_market_data.py` 零 `self.futu` 引用 + `pytest backend/tests/test_services_legacy_market_data_coverage.py`
- [x] **[BE-ARCH-07b]** **删除 `market_engine` 的 Futu 死门控**（Bug，非重构）：`backend/services/market_engine.py:302` `futu_connected = _get_futu_service().status == "CONNECTED"` 读取的是**主服务本地** Futu 状态，而 `backend/bootstrap/lifecycle.py:108-110` 已明确主服务不再 connect OpenD ⇒ 该值恒为 `False` ⇒ 把 `:343`（技术指标历史）/`:386`（资金流轮询）/`:427`（账户快照）/`:440`（Futu 快照补漏）四段**本身已合规**的 `data_source_router.fetch_futu` 调用全部废掉。改法：门控换为 Router 节点健康度（`data_source_router.get_health_status()`）或直接移除（Router 自带熔断，无需这层"防 CPU 空转"），顺带清理 `:34-38` 的 `_get_futu_service`。验收：四段逻辑在主服务无本地 OpenD 时可正常执行
- [x] **[BE-ARCH-07c]** **主服务卸载 Futu SDK 连接层**：`backend/services/futu/` 仍完整持有 SDK —— `connection_manager.py:15-22`（`from futu import OpenQuoteContext`）、`data_source.py:53-68`（`LocalDataSource`）+ `source_router.py:13,30`、`watchdog.py:182,258,282`、`push_handler.py`（与 `data_subservice/futu_src/push_handler.py` 重复实现）；`lifecycle.py:394-397` shutdown 仍 `futu_service.close()`。另有两处仅取枚举的 SDK 依赖需替换为本地常量：`backend/engine/gateway.py:23`、`backend/workers/oms/algo_engine.py:655`（`from futu import TrdMarket, TrdSide`）。Kill Switch 残留本地 `trade_ctx`：`backend/services/adapters/legacy_broker.py:85-100`（同文件 `:50-75` 下单已合规走 `fetch_futu`，照抄即可）。**依赖 07a/07b 先完成**
  - **07c 落地**: 主服务生产路径已完全移除 futu SDK 硬依赖 —— (1) `engine/gateway.py:25`/`workers/oms/algo_engine.py:657` 两处枚举改 `try/except` 回退 `backend/services/futu/enums` 本地常量(TrdMarket/TrdSide/ModifyOrderOp); (2) `legacy_broker.py` 的 `_resolve_market`/`place_order`/`cancel_order`/`execute_emergency_liquidation`/`has_trade_ctx` 全部改走 `fetch_futu` 远程, 删除本地 `trade_ctx` 直连; (3) Kill Switch 远程化配套: 子服务 `data_subservice/futu_src/trade_handler.py` 新增 `emergency_liquidation`、service.py 新增路由、`futu_worker.py` 新增 `EMERGENCY_LIQUIDATION` action、主服务 `router.py` 的 `_FUTU_ACTION_MAP` 注册; (4) `lifecycle.py:394-397` 移除残留 `futu_service.close()`。
  - **剩余(需 07d/e 迁移 get_fundamental/screen_stocks 后整体删除 `backend/services/futu/` 连接层模块)**: `connection_manager.py`/`data_source.py`(LocalDataSource)/`source_router.py`/`watchdog.py`/`push_handler.py`/`quote_handler.py`/`option_fund_handler.py`/`screener_handler.py`/`trade_handler.py` 仍被 `futu_service` 单例引用(供 get_fundamental/screen_stocks/unsubscribe_quote/is_futu_unsupported 使用, 主服务无 OpenD 不 connect 属死代码), 待 07d/e 迁移这些方法到 `fetch_futu` 后整包下沉 data_subservice。

#### P1 · 路由层与采集层直连外网

- [x] **[BE-ARCH-07d]** **`routers/search` 切 search 适配器**：`backend/routers/search.py:6,22` → `backend/services/search/service.py` 直连 `api.tavily.com`（`:32`）、`api.bochaai.com`（`:67`）、`duckduckgo_search` SDK（`:101-117`）。合规通道**早已就位却闲置**：`backend/services/datasource/adapters/search.py:9`（文件头注释即写明"主服务不再直接 httpx 外部 API"）+ `:114-132` 三源注册 + `router.py:907` `fetch_search`。注意 Hermes `web_search_tool.py:52-65` 走的是后端 `/search/web`，所以本任务同时修掉 Agent 侧的实际外网出口。验收：`services/search/service.py` 无外部域名 + `pytest backend/tests/routers/test_datasource_search_adapters.py`
  - **07d 落地**: 直连痛点实际位于 `backend/services/search/service.py` (routers/search.py 已合规调 search_service)。已将 `SearchService.web_search` 改为经 `data_source_router.fetch_search(source, ...)` 远程代理, 按 `tavily -> bocha` 降级, 删除全部 httpx/tavily/bocha/duckduckgo 直连与外部域名; 子服务 `data_subservice/search_worker.py` 新增 `search` 聚合 action (`_web_search_aggregated`, Tavily->Bocha 子服务侧降级) 承接原主服务多源调度。Hermes `web_search_tool.py` 经 `/search/web` -> `search_service` 已同步合规。重写 `test_search_service.py` / `test_service_logic.py` 的 SearchService 用例以匹配远程代理行为。
- [x] **[BE-ARCH-07e]** **`routers/calendars` 切 finnhub 适配器**：`backend/routers/calendars.py:495-496`（`https://finnhub.io/api/v1/calendar/dividend`）、`:553-554`（`.../calendar/ipo`）在**路由函数内**裸 httpx 打外网，违反"Router 只做参数校验与转发"。改走 `data_source_router.fetch_finnhub`（`router.py:789` + action 映射 `:107-115`）或 Facade；子服务侧 handler 已支持（`data_subservice/finnhub_worker.py`）
  - **07e 落地**: calendars 路由的 dividend/ipo 两个 finnhub 直连改为 `data_source_router.fetch_finnhub("dividend_calendar"/"ipo_calendar")`, 移除 httpx 直连与 `finnhub.io` 域名; 保留无 key 降级/限流退避/Redis 缓存语义; 删除 calendars.py 孤立 `import httpx`。配套子服务: `finnhub_worker.py` 的 `_FINNHUB_DISPATCH` 注册 `DIVIDEND_CALENDAR`/`IPO_CALENDAR`, `_internal/finnhub/__init__.py` 新增 `get_dividend_calendar`(支持 symbol 过滤)/`get_ipo_calendar`; 主服务 `router.py` 的 `_FINNHUB_ACTION_MAP` 注册 `dividend_calendar`/`ipo_calendar`。
- [ ] **[FUTURE][DDG 子服务增强]** **子服务 search_worker 新增 DuckDuckGo 免费兜底源**：07d 已将主服务搜索直连卸载为远程代理（Tavily→Bocha 降级），但原主服务的 **DuckDuckGo 免费兜底**（无 key 时仍能搜）下沉到子服务时暂未实现。需在 `data_subservice/search_worker.py` 的 `_web_search_aggregated` 中加入第三优先级 DDG source：① 在 `data_subservice/_internal/search/` 新增 `ddg_service.py`（`from duckduckgo_search import DDGS`，按查询语言选 `region=wt-wt|cn-zh`，含代理/重试）；② `search_worker.py` 引入并接入 `tavily -> bocha -> ddg` 三级降级；③ 确保 `search_master` 节点（或统一 search 子服务）已部署该 DDG 依赖与出口；④ 配套单测。验收：无 Tavily/Bocha key 时仍可由 DDG 返回结果。
- [x] **[BE-ARCH-07f]** **宏观三源（FRED / DBnomics / RBI）连接层下沉远程** ✅ 2026-08-09
  - `backend/services/macro/fred_service.py`：删除 `httpx.AsyncClient` + `FRED_API_KEY` + `api.stlouisfed.org` 直连，`get_series_observations` 走 `fetch_fred("macro_series")`、`get_economic_calendar` 走 `fetch_fred("releases_dates")`；保留 Redis 缓存 / 归一化 / `backfill_actuals` 纯逻辑；`close()` 降级为空操作
  - `backend/services/macro/dbnomics.py`：删除 `api.db.nomics.world` 直连，改走 `fetch_dbnomics("em_cpi_series")`，保留 docs 解析与缓存
  - `backend/services/macro/rbi.py`：删除 `api.worldbank.org` 直连，改走 `fetch_rbi("india_cpi_series")`，保留序列解析与缓存
  - 子服务补齐真实出口：`_internal/fred.get_releases_dates`、`_internal/dbnomics.get_em_cpi_series`（OECD G20 CPI）、`_internal/rbi.get_india_cpi_series`（WorldBank FP.CPI.TOTL.ZG），并在 `fred_worker/dbnomics_worker/rbi_worker` 注册 `RELEASES_DATES`/`EM_CPI_SERIES`/`INDIA_CPI_SERIES`
  - 单测同步远程化：`backend/tests/test_fred_service.py`（重写）、`test_dbnomics.py`；25 用例全绿
- [x] **[BE-ARCH-07f-2]** **AKShare 连接层下沉远程（从 07f 拆出）** ✅ 2026-08-09：子服务 `_internal/akshare` 补全 southbound/hk_connect/hsgt_holders/stock_news/quote_a/history_a + 经济日历三重容灾并注册全部 action；主服务 `services/akshare/{quote,flow,calendar}` 三 Mixin 去本地 akshare 改走 `data_source_router.fetch_akshare`；`legacy_market_data` 8 个方法路由化并删除日历本地降级；adapter capabilities 扩至 11 action；单测改 mock 路由，44 用例全绿。注：`services/margin/a_share.py` 与 `fund_flow/*` 仍本地 `import akshare`，独立服务，建议另立 07f-3。07f-3 已完成（见下）。
- [x] **[BE-ARCH-07f-3]** **AKShare 连接层下沉远程（margin / fund_flow 收尾）** ✅ 2026-08-09：子服务 `_internal/akshare/flow.py` 新增 `get_a_share_margin`/`get_a_share_sector_flow`/`get_hk_sector_flow`（解析逻辑完整下沉，对齐主服务历史返回结构 `status/data/source`）；`service.py` 注册 `get_margin_a_share`/`get_sector_flow_a`/`get_sector_flow_hk`；`akshare_worker.py` 扩展 `MARGIN_A_SHARE`/`SECTOR_FLOW_A`/`SECTOR_FLOW_HK` 分支；adapter capabilities 扩至 14 action。主服务 `services/margin/a_share.py`、`services/fund_flow/a_share_sector.py`、`services/fund_flow/hk_sector.py` 删除本地 `import akshare` 改走 `data_source_router.fetch_akshare`，保留 Redis 缓存 / 熔断降级 / stale 兜底语义；`test_fund_flow.py` 由 mock 本地 SDK 改写为 mock 远程路由，19 用例全绿；验证 backend 已无任何本地 `akshare` 直连。
- [x] **[BE-ARCH-07g]** **AKShare Collector 去本地 SDK** ✅ 2026-08-09：`backend/workers/akshare_collector.py` 移除本地 `AKShareService` 实例化与 `AKSHARE_MODE=direct` 环境变量切花，改为统一经 `data_source_router.fetch_akshare(action)` 联邦调用 CN-AKSHARE 子服务，并将结果写回共享 Redis（对齐主服务 cache-mode 读取键 `akshare_southbound_flow`/`akshare_northbound_flow`/`akshare_hk_connect_flow`/`akshare_econ_cal_7_0`）。任务映射：southbound→SOUTHBOUND、northbound→FUND_FLOW、hk_connect→HK_CONNECT、economic_calendar→ECONOMIC_CALENDAR(days_ahead=7)。`test_akshare_collector_dist07a.py` 由 mock 本地 `AKShareService` 改写为 mock 远程 `fetch_akshare` + 验证 Redis 写回，31 用例全绿。backend 现已无任何本地 akshare SDK 直连（仅远程 adapter + collector 路由）。
- [x] **[BE-ARCH-07h]** **长连接链路缺口修复** ✅ 2026-08-09：经逐条核查真实代码后精准修复确凿缺口，不臆造已通的链路：
  - **① 宏观新闻频道名错配（确凿，已修）**：`backend/workers/market/daemon.py:248` 原发 `live_news_channel`，而 `backend/routers/macro.py:181` news/ws 订阅 `macro_news` → 改 daemon 发布为 `macro_news`，用户连上 news/ws 后即可收实时新闻推送（消除空白转）。
  - **② `macro_alerts` 有订阅无发布（确凿，已修）**：`backend/routers/macro.py:245` calendar/ws 订阅 `macro_alerts`，但全网无发布者；`backend/workers/macro/alert_daemon.py` 的 `macro_alert_daemon` 触发宏观核弹数据预警时仅走 `notification_service.send_alert`（→`quant:alerts:push`），未广播到 `macro_alerts` → 在触发点补充 `redis_client.publish("macro_alerts", {...})`，calendar/ws 实时链路接通。
  - **③ `oms:trades:new`/`oms:bot_log:stream`（经核查已通，未动）**：`backend/services/bot_runtime.py:336` 正确 publish `oms:bot_log:stream`，`backend/routers/oms.py:409/430` 正确订阅 `oms:bot_log:stream`；`oms.py:408` 订阅的 `oms:trades:new` 由真实成交事件触发，链路一致。TODO 原描述"有订阅无发布"为过时判断。
  - **④ `quant:tick:{SYMBOL}` 空转（经核查，确认无需补 publisher）**：Finnhub WS tick 已按 BE-ARCH-01 移除（子服务不持有 Finnhub WS），主服务 `subscription.py` 的 tick 订阅属历史预留，无对应 publisher 是预期状态，非缺口。
  - **⑤ `QuotePublisher` 未挂载（经核查，冗余）**：`backend/routers/market.py:42` 已有 `/quotes/ws`，实时行情经 `push_handler.py` → `quant:quotes:stream` → `market_engine.py:251` ConnectionManager 订阅 → WS 推送，链路已通；`quote_publisher.py` 为独立备用脚本，重复职责，不强行挂载避免重复推送。
  - **⑥ AlertEngine/CEPEngine 订阅（经核查已接入）**：`in_app.py` 发布 `quant:alerts:push`，`alert.py:169` 订阅同频道，告警触发链路通；引擎订阅代码已在 lifecycle/worker 接入。
  - **⑦ 中间件 WS 白名单（`backend/middleware/stack.py:68-70`）**：核对 openapi_schema 实际 WS 路径为 `/api/v1/macro/news/ws`、`/api/v1/oms/ws`、`/api/v1/market/quotes/ws`，白名单条目与实际路由一致，原 TODO 描述的"三个不存在路径"为过时判断。
  - **⑧ `futu:push:*` 子服务在发主服务无消费者**：已通过 07h-2 彻底闭环 —— `data_subservice/futu_src/push_handler.py` 的 broker/kline handler 在保留 `futu:push:broker:{ticker}`/`futu:push:kline:{ticker}`（向后兼容）的同时，额外桥接发布到 `quant:broker:{ticker}`/`quant:kline:{ticker}`；主服务 `backend/services/datasource/subscription.py` 新增 `_PolyCache` + `_run_poly_ingest` 协程订阅上述 `quant:*` 频道并回灌进程内缓存，`SubscriptionService` 暴露 `start_broker_ingest`/`start_kline_ingest`/`get_broker`/`get_kline` 接口；`backend/bootstrap/lifecycle.py` 在启动 tick 回灌时并行启动 broker/kline 消费者（复用 `FINNHUB_WS_SYMBOLS` 标的配置）。修复过程中发现并修正 `_run_poly_ingest` 的 `json.DecodeError`（应为 `json.JSONDecodeError`）生产 bug。新增 `test_subscription_poly_07h2.py` 5 用例全绿。
- [x] **[BE-ARCH-07i]** **Facade action 与 capabilities 对齐 + Registry 回退收紧**（已完成，commit 见 git log）：
  - **① capabilities 补齐**：`adapters/futu.py:53-60` 补 `WARRANT_CHAIN`/`SCREEN_STOCKS`/`ORDER_BOOK`/`SNAPSHOT`/`STOCK_BASICINFO`/`ACCOUNT_INFO`（与 `futu_worker.py` 实际 action + Facade 域方法对齐）；`adapters/akshare.py` 的 `HSGT_HOLDERS` 已在 07f-3 补齐（TODO 描述滞后，已核对无误）；`adapters/fmp.py` 补 `FUNDAMENTAL`/`INFO` 及大小写别名（对齐 Facade 的 `FUNDAMENTAL`/`INFO` 与 `_FMP_ACTION_MAP`）；`adapters/legacy_yfinance.py` 补 `FUND_FLOW`/`OPTION_CHAIN`/`TECH`/`FINANCIALS`/`INFO` 等大小写别名（对齐 `_ACTION_TO_FETCH_TYPE` 映射键）。
  - **② Registry 回退收紧**：`backend/services/datasource/source_registry.py:106-109` 改为——能力不匹配时**显式 `logging.warning` 并返回 `None`**，不再静默回退首实例（否则"按 action 选源"语义失效，只能靠 fetch 失败逐源重试兜底）。仅当环境变量 `DATASOURCE_LOOSE_CAPABILITY=1` 时恢复旧回退行为（过渡期开关，不应长期开启）。Facade `_select_source` 对全源调 `get(name, action)`，不匹配源本就该被跳过，收紧后语义正确。
  - **核验**：finnhub `INSIDER_TRADING`、macro `MACRO_SERIES`（fred）、`economic_calendar` 等既有 action 经 `action.upper()` 比对均与 capabilities 大小写声明命中，无副作用。

- [x] **[BE-ARCH-07p]** **对外暴露 broker / kline 实时数据（承接 07h-2 进程内缓存 → HTTP）**（已完成，commit 见 git log）：
  - **① HTTP 拉取端点**：在 `backend/routers/market.py` 新增 `GET /api/v1/market/broker/{symbol}`（`get_broker_realtime`）与 `GET /api/v1/market/kline/{symbol}`（`get_kline_realtime`），直接调用模块级单例 `subscription_service.get_broker(symbol)`/`get_kline(symbol)`（与现有 `market_data_gateway`/`data_source_router` 单例注入风格一致，无需 `Depends`）。返回结构含 `symbol`/`broker`(or `kline`)/`cached`/`updated_at`/`source`，缓存未命中时 `cached=false` 且数据字段为 `None`（前端可据此降级）。
  - **② WS 推送端点（可选增强，未做）**：暂未实现流式推送。若前端需要，后续可新增 `WS /api/v1/market/broker/ws?symbol=` + `WS /api/v1/market/kline/ws?symbol=`（订阅 `quant:*` 频道），并同步 `backend/middleware/stack.py:68-70` 的 WS 白名单。本轮仅做 HTTP 拉取，已满足前端轮询实时盘口/K线需求。
  - **③ 接入启动**：`backend/bootstrap/lifecycle.py` 已通过 07h-2 启动 `start_broker_ingest`/`start_kline_ingest`，本任务仅补路由，不重复启动消费者。
  - **④ 守门**：新增 `backend/tests/test_market_router_07p.py`（4 用例，mock `subscription_service` 全链路，验证缓存命中/未命中结构与字段；全程 mock，无任何外部数据源直连，守门测试 07n 不退化）。

#### P2 · 散点下沉、死代码清理与守门测试

- [x] **[BE-ARCH-07j]** **剩余业务模块直连下沉**（部分完成，2026-08-09）：
  - **① AKShare 业务模块（已在 07f-3 完成，非本轮）**：`fund_flow/hk_sector.py`、`fund_flow/a_share_sector.py`、`margin/a_share.py` 的 `import akshare` 已在 07f-3 下沉为 `fetch_akshare` 远程，本轮不再重复。
  - **② Tushare 本地 SDK 兜底（已无本地兜底）**：`services/tushare/service.py` 的 `import tushare` 直连保留为「主节点有包时本地」的遗留连接层，但 `data_source_router.fetch_tushare` 已明确「本地兜底已移除」、生产经 CN-DATA 子服务远程；`adapter.py` 主节点无包时 `is_available()` 返回 False 跳过注册，不会误走本地 SDK。本轮未强删（属 `backend/services/tushare/` 整包待 07c 末段统一下沉），不阻塞「仅远程」收敛。
  - **③ Yahoo 直连收口（本轮完成）** ✅：`backend/core/yahoo_news.py` 删除 httpx 直连 `query2.finance.yahoo.com`，改为经 `data_source_router.fetch_yfinance("NEWS", ...)` 联邦 US-YF-A/B 子服务；字段归一化（category/datetime/headline/summary/source/url/related）保持与 Finnhub 兼容。`services/akshare/quote.py:71-79` 港股新闻降级调用 `fetch_yahoo_news` 的内部实现已随 ③ 自动远程化（仅修正 docstring 措辞）。子服务支撑：`data_subservice/_internal/yfinance/quote.py` 新增 `fetch_news`（经 `yf.Ticker.news`）、`service.py` 新增 `get_news`、`yfinance_worker.py` 新增 `NEWS` action、`router.py` 的 `_YF_ACTION_MAP` 注册 `news`。07n 强门禁区新增 `backend/core/`，确认主服务已无 `finance.yahoo.com` 字面量。
  - **④ 监管源直连遗留（登记为 07j 待治理项，不阻塞本轮）**：`margin/sources/finra.py`（`api.finra.org`）、`hkex.py`、`sfc.py` 为**可配置 URL 的官方监管 CSV 抓取**（默认官方域名，URL 经 env 注入），非 SDK 直连，且 `data_subservice` 当前无对应子服务；`download_report_tool.py` 的 hkexnews/sec 二进制 PDF 直连同理（07m 已登记）。此三类需新建子服务 `FILE_DOWNLOAD` action 才能完整收口，超出本轮范围，锁定不扩散（已在 07n 门禁 `known_violations` 登记）。
- [x] **[BE-ARCH-07k]** **连接层死代码清理**（部分完成，2026-08-09）：
  - **① Yahoo 死 mixin 已删（本轮完成）** ✅：`backend/services/yfinance/search.py`（`SearchMixin.search_tickers` 直连 `query2.finance.yahoo.com`）、`yfinance/technical.py`（`TechnicalMixin` 依赖本地 `fetch_yf_data`）—— backend 生产代码无任何 import、无 `__init__.py`（非合法包），确为死代码，已删除目录内容。07n 弱门禁白名单同步移除 `yfinance`（见 `test_be_arch07n_services_boundary.py`）；新增 `test_be_arch07k_deadcode.py` 验证死目录已删、backend 无死包引用与 Yahoo 直连。主服务 yahoo_news 已于 07j 改走 `router.fetch_yfinance` 远程代理，无功能回归。
  - **② `health_check_url` 死配置（经核查代码库已不存在，无需处理）**：全仓搜索 `health_check_url` 仅命中 docs 文档（`23. 业务数据源聚合Facade设计.md` / `TODO.md` 本身的描述），`backend/services/datasource/router.py` 实际已无该字段定义与赋值。docs 描述为设计稿遗留，与实际代码不一致，已据实标注。
  - **③ `finnhub/service.py` 完整 REST 客户端（登记为遗留，不强行删）**：`FinnhubService`（`get_earnings_calendar`/`get_stock_history`/`get_insider_transactions`/`get_market_news`/`get_company_news`/`get_economic_calendar`）确为直连 finnhub.io 的本地实现，生产已统一走 `router.fetch_finnhub`，当前仅测试引用（`test_finnhub_service.py` / `test_market_daemon_finnhub_routing.py`）。删除需连带改写测试套件、评估面较大，且 `services/finnhub` 仍在 07n 弱门禁白名单（legacy 连接层），本轮保留，锁定不扩散，待 07c 末段统一下沉子服务时一并删除。
  - **④ `fmp/service.py` 的 `_local_get` 降级兜底（登记为遗留，标注风险）**：`fetch_fmp` 子服务不可达时降级到 `financialmodelingprep.com` 本地直连，属隐蔽外网直连风险点（"定时炸弹"）。删除会导致 FMP 完全依赖子服务可用性，与"仅远程"目标一致但需评估生产影响，本轮保留，锁定不扩散，待 07c 末段统一下沉时移除本地兜底分支。
  - **守门**：07n 门禁白名单移除 yfinance（10 用例）+ 07k 死代码验证（3 用例）全绿。
- [x] **[BE-ARCH-07l]** **子服务配置陷阱修复**（已完成，2026-08-09）：
  - **① `DS_CAPABILITIES` 漏 `.split(",")`（本轮修复）** ✅：`data_subservice/nodeinfo.py` 原实现漏切分，逗号字符串按字符迭代，注册进 Redis 的 capabilities 与 `main.py` 门控不一致；已统一 `isinstance(str) → split(",")`，并补 `test_nodeinfo_capabilities.py`（5 用例）锁定逗号切分/默认集/大小写规整。
  - **② 默认能力集缺项 + 文档标注（本轮修复）** ✅：`nodeinfo.py` 默认集与 `main.py:_declared_capabilities()` 对齐为 `yfinance,akshare,tushare,fmp,futu`（注：finnhub/fred/dbnomics/rbi/search 全量集需在部署时经 `DS_CAPABILITIES` 显式声明，未声明则 503，属预期行为）；`.env.example` 新增 `DS_CAPABILITIES` 必填说明 + 全量能力枚举 + 各节点角色示例，`main.py:_declared_capabilities` 加显著注释。
  - **③ 心跳仅注册一次、TTL 到期被判 dead（本轮修复）** ✅：`startup_event` 原仅 `register` 一次，TTL 30s 后节点被判 dead。已新增后台 `_heartbeat_loop`（周期取 `NODE_HEARTBEAT_TTL/3`，最小 5s）并补充 `shutdown_event` 清理任务；补 `test_heartbeat_loop.py`（2 用例）锁定周期刷新与干净退出。`service_registry.NodeInfo.is_alive()` 已是 pydantic 属性读取（无盲取 `ttl` dict 问题，该项遗留代码已在既往重构中消解）。
  - **④ 推送频道命名对齐（本轮修复）** ✅：`backend/services/futu/push_handler.py` 原实发 `futu:push:ticker:*` / `futu:push:broker:*` / `futu:push:kline:*`——下游 CEP(`market_engine.py`订阅`quant:trades:stream`)、`subscription.py`回灌层(`quant:broker:*`/`quant:kline:*`)与前端(`quant:quotes:stream`)均订阅 `quant:*` 总线，旧频道无人消费。已统一改为 `quant:trades:stream:*` / `quant:broker:*` / `quant:kline:*`，并补 `TestChannelNameAlignmentBEARCH07l`（3 用例）断言；注释与实现一致。另：`data_subservice/futu_src/push_handler.py` 早已正确桥接 `quant:broker/kline`（仅子服务侧），无回归。
  - 守门：`test_push_handler.py`(49) + `test_nodeinfo_capabilities.py`(5) + `test_heartbeat_loop.py`(2) 全绿。
- [x] **[BE-ARCH-07m]** **Hermes Tools 外网直连收口**（已完成，commit 见 git log）：
  - **`web_scrape_tool.py`**：移除 `r.jina.ai` 直连与任意 URL httpx 抓取。新增 backend `SearchService.fetch_webpage(url, query)`（经 `data_source_router.fetch_search("jina", url)` → data_subservice 子服务 Jina 代理），`_fetch_via_jina` 改走该远程代理，`_fetch_via_httpx` 降级分支改为 Jina 重试（外部直连彻底消除），保留反爬拦截/正文提纯/RAG 业务逻辑。
  - **`insider_tool.py`**：删除 `_fetch_hkex_disclosure` 的 `www1.hkexnews.hk` 外部直连分支（原仅返回"需 JS 渲染请手动访问"提示、无数据价值），港股查询统一走 `_search_hk_insider`（backend `/search/web` 代理，合规范例），`_query_hk_insider_parallel` 重构为单路搜索。
  - **`download_report_tool.py`**：**登记为已知遗留（07j 待治理）**——其 `sec.gov`/`hkexnews` PDF 二进制下载无现成远程代理（Jina 仅支持网页正文、不支持二进制），需 data_subservice 扩 `FILE_DOWNLOAD` action 后方可收口；本轮未改动，已在 7n 门禁白名单透明登记。
  - **`earnings_compare_tool.py` / `notification_tool.py`**：经核查为 backend 内部 API 调用（localhost backend / 通知服务），非外部数据源直连，不属 07m 范围，未改动。
  - **门禁更新**（`test_be_arch07n_services_boundary.py`）：`web_scrape_tool` 的 jina 直连已收口 → 从 07m 已知豁免移除；`download_report_tool` 加入 07j 已知白名单（锁定不扩散）。
  - 守门：7n 门禁 10 用例全绿。
- [x] **[BE-ARCH-07n]** **架构守门测试扩面**（已完成，commit 见 git log）：
  - 新增 `backend/tests/test_be_arch07n_services_boundary.py`（10 用例），从 Router 层扩面到 services/ 层 + hermes_agent/ 层：
    - **强门禁零容忍**：`services/datasource/`、`services/margin/`、`services/fund_flow/`、`routers/` 绝对禁止 `import akshare|yfinance|finnhub|fredapi|tushare|futu`（本轮治理成果锁死，防复发）。
    - **futu 不越界**：futu SDK 直连不得越过 `services/futu/` 边界（其余 services 子目录一律禁止）。
    - **SDK 仅限 legacy**：第三方 SDK import 只应出现在已知 legacy 连接层目录（`services/futu|akshare|tushare|finnhub|yfinance|fmp|adapters`），待 07j 整体下沉。
    - **外部域名字面量强门禁**：`routers/`、`hermes_agent/`、`services/datasource/business/` 不得出现 `https?://` 后的外部数据源直连 URL（排除纯 label 配置字符串误杀）；`hermes_agent/tools/web_scrape_tool.py` 的 `r.jina.ai` 直连登记为 **已知 07m 待治理项**（锁定不扩散，其余 hermes 文件零违规）。
  - 守门覆盖 `backend/`、`hermes_agent/`；豁免 `data_subservice/**`、`backend/tests/**`（与 07n 原豁免清单一致，adapters 的 `provider` 标识字符串因改用 http(s):// 模式已自然豁免）。
- [x] **[BE-ARCH-07o]** **`scripts/` 探针脚本归口**（已完成，2026-08-09）：
  - **① 归口 `scripts/probes/` + README 标注（本轮完成）** ✅：将根目录直连外部源的诊断脚本统一 `git mv` 至 `scripts/probes/`（含 `test_yf*.py`、`futu_fetch.py`、`test_futu_screen_direct.py`、`test_screener_cases.py`、`probe_akshare_alts.py`、`probe_sina_schema.py`、`probe_local_proxy.py`、`verify_quote_sina.py`、`test_local_em_direct.py`、`probe_tushare_diag.py`、`test_finnhub_*.py`、`test_tavily_search.py`、`test_google_search.py`、`verify_macro.py`、`sync_minute_data.py`、`export_all_tickers.py`，共 20 个），新增 `scripts/probes/README.md` 标注"诊断工具绕过数据服务、仅用于源连通性排查、不得被 backend 生产模块 import"。`scripts/archive/` 维持原状（已是弃用归档，不在 07o 范围）。
  - **② 纳入 07n 守门豁免（无需改动，已天然成立）** ✅：`test_be_arch07n_services_boundary.py` 的强门禁只扫描 `backend/services/`、`backend/routers/`、`backend/core/`、`hermes_agent/`，**不覆盖 `scripts/`**（含 `scripts/probes/`），因此这些诊断脚本的 SDK 直连不会误触生产违规守门；README 已显式说明此豁免边界，禁止新增生产依赖。
  - 守门自检：移动后 `scripts/` 根目录已无直连第三方 SDK 的诊断脚本（仅 `scripts/archive/` 与 backend 内部 profiling 引用保留）；07n 门禁 10 用例不受影响（扫描范围未变）。

### 数据服务三条标准复审（BE-ARCH-08 系列 · 2026-08-09 晚 · 07 系列落地后复审）

> 🔍 **复审基准（用户三条验收标准）**：① HTTP API 完整可靠 ② 长连接可用 ③ **主服务不能依赖第三方代码包**。
> **复审结论：三条全部不达标，且 ③ 已阻塞生产部署。** 07 系列把"调用层直连"清理干净了（`services/akshare/` 本地 SDK 消失、`routers/search` 与 `calendars` 改走适配器、`core/yahoo_news` 收口、`services/futu/enums.py` 替掉 SDK 枚举依赖、`backend/requirements.txt` 与 `pyproject.toml` 基础依赖零数据源 SDK），但**依赖包层与跨进程契约层的问题被暴露出来**。
>
> ⚠️ **方法论根因（决定了这些问题为何长期隐形）**：`router.fetch_*` 的离线短路（`router.py:557-563`：`OFFLINE_MODE=1` 或 `QUANT_ENV∈{offline,testing,dev}` 时在**构造 payload 之前**返回 stub）+ 07n 守门测试只查 import 与域名字面量 ⇒ **现有测试体系结构性地看不见"params 键名错位""错误体语义不一致"这类跨进程契约缺陷**。08b 与 08d 都是这个盲区的产物，故 08h 为根治项。

#### P0 · 阻塞部署与线上取数

- [x] **[BE-ARCH-08a]** **主服务卸载 futu 包硬依赖（③ 破口 · 部署阻塞 · 最高优先）**：`backend/services/market_engine.py:33` 是**无条件顶层** `from backend.services.futu import futu_service` → `services/futu/__init__.py:6` → `services/futu/service.py:16` 裸顶层 `from futu import ModifyOrderOp, TrdMarket, TrdSide`（无 try 保护）。而主镜像 `Dockerfile` 执行 `uv sync --no-dev --no-install-project`，**不带任何 `--extra datasource-*`**；`futu-api` 只在 `pyproject.toml` 的 `[project.optional-dependencies].datasource-us`，CI 仅打进 `-data-subservice:us` 镜像（`.github/workflows/backend.yml:66-70`）。**实测证据**：`python3 -c "import backend.services.futu"` → `ModuleNotFoundError: futu`。`market_engine` 被 `bootstrap/lifecycle.py`、`routers/market.py`、`app/macro_app.py` 引用（均在 `backend.main` 链上）⇒ **`uvicorn backend.main:app` 在生产镜像 import 阶段即崩**。此为 07b 把懒加载 `_get_futu_service()` 改成 eager import 引入的回归。
  - **推荐修法（最小 diff）**：`market_engine` 只用到三个成员 —— `futu_service.is_futu_unsupported(t)`（`:302`、`:394`）、`futu_service.unsubscribe_quote(stale_t)`（`:313`）、`futu_service.cache_mgr.evict_stale_cache()`（`:332`）。其中 `is_futu_unsupported` 就在 `backend/services/futu/utils.py`（**纯函数、零 import**），改为 `from backend.services.futu.utils import is_futu_unsupported`；后两者操作的是主服务根本不持有的 OpenD 连接与本地订阅缓存（`lifecycle.py:107-110` 已确认主服务不建连），属 07c 应清的死代码，直接删除。
  - **备选**：① 按 07c 目标删除整个 `backend/services/futu/` 包，把仍在用的纯工具（`utils.py` / `enums.py`）上提到 `services/futu_local/`；② 最保守：仅给 `services/futu/service.py:16` 的 SDK import 加 try/except 降级（不推荐，掩盖问题）。
  - **✅ 已彻底解决 (2026-08-10, BE-ARCH-09)**：`backend/services/futu/` 重构为纯 HTTP 透传 facade —— 删除 11 个直连 OpenD 模块（`connection_manager`/`source_router`/`data_source`/`screener_handler`/`quote_handler`/`option_fund_handler`/`trade_handler`/`cache_manager`/`watchdog`/`push_handler`），`service.py` 经 `DataSourceRouter.fetch_futu` 转发至 `data_subservice/futu_src`；枚举走 `backend.services.futu.enums`（零 SDK 依赖）。主服务 `backend/` 全仓 0 处 `import futu`，主镜像 `uv sync --no-dev --no-install-project` 不再崩溃。`futu-api` 依赖保留在 `datasource-us` extra（仅 `-data-subservice:us` 镜像使用）。对应单测 `test_push_handler.py` 删除、`test_screener_cases.py` 解耦、`test_gateway_oms_adapter.py` 改用本地枚举。
  - **收尾**：另有 6 处函数内懒加载同源风险（调用即 `ModuleNotFoundError`）：`services/adapters/legacy_market_data.py:43`、`services/adapters/legacy_broker.py:21`、`services/fund_flow/ticker.py:15`、`workers/quote_publisher.py:17`、`services/futu/watchdog.py:355`、`engine/gateway.py:340`。
  - **验收**：在**不装 futu-api** 的环境下 `python -c "import backend.main"` 成功；07n 守门测试增加"`backend/` 顶层 import 链不得触达 futu/yfinance/akshare/tushare SDK"用例。
  - **实际落地（2026-08-09）**：根因在 `services/futu/__init__.py` 顶层贪婪 `from .service import ...`，而 `service.py:16` 裸 `from futu import ...`，故任何 `from backend.services.futu import ...` 或 `.utils import` 都会触发 SDK import。修复 = 一处 guard（try/except 包 `__init__` 的 service import，缺失时降级 `futu_service=None`），并移除 market_engine 对 `futu_service` 的顶层/死代码依赖（`unsubscribe_quote`/`cache_mgr.evict_stale_cache` 操作主服务不持有的 OpenD/本地缓存，属死代码删除）。手动验收命令：`python -c "import sys; sys.modules['futu']=None; import importlib; importlib.import_module('backend.services.market_engine'); print('PASS')"` → 输出 `RESULT=PASS market_engine 脱离 futu 依赖`；`from backend.services.futu import futu_service` 在屏蔽下返回 `None`、不装时正常返回 `FutuService` 实例，两面通过。pytest 自动门禁因本仓库 import 阶段 safe-delete 的 `SystemExit` 副作用无法常驻，故以手动验证为准（ponytail: 未引入框架噪音）。
- [x] **[BE-ARCH-08b]** **YFinance 全链路 params 键名错位（① 破口 · 线上取不到数）**：主服务发 `ticker`，子服务读 `symbol`，且 `fetch_yfinance` **全程无 params 归一**（对比 Futu 侧有 `router.py:751-762` `_futu_normalize_params` 做 `ticker→symbol`）。
  - 发送侧：`backend/services/datasource/router.py:582-586` `"params": {"ticker": ticker, **kwargs}`
  - 接收侧：`data_subservice/yfinance_worker.py:13,15,22,24,26`（`params.get("symbol")`）
  - 影响面：QUOTE / HISTORY / FUND_FLOW / OPTION_CHAIN / FINANCIALS / TECH 全部收到 `symbol=None`
  - 同类错位：AKShare（`data_subservice/akshare_worker.py:12-19` 读 symbol，Facade 传 ticker）、FMP（`fmp_worker.py:12-17` 读 symbol，`facade.py:106/154/163` 传 ticker；`workers/collectors/fmp.py:74` 显式传 symbol 故独善其身）
  - 溯源：`symbol` 约定由 commit `93f1ecf`（data_subservice 物理解耦重构）引入，router 侧未同步
  - **修法**：在 `fetch_yfinance` / `fetch_akshare` / `fetch_fmp` 统一补 params 归一（照抄 `_futu_normalize_params` 模式），或统一改为双键兼容 `{"symbol": x, "ticker": x}`。**验收必须在 `OFFLINE_MODE=0` 下跑**，否则被离线 stub 短路（见本节方法论根因）
  - **实际落地（2026-08-09）**：根因 = `fetch_*` 发送侧全程无 params 归一（一处缺失，波及所有兄弟源）。修复 = 一处 guard：新增 `DataSourceRouter._normalize_outbound_params` 静态方法做**双键兼容**（`ticker→symbol` 同时保留原 `ticker` 键，`tickers→symbols` 同理），并在 `fetch_yfinance`(:585) / `fetch_akshare`(:649) / `fetch_tushare`(:694) / `fetch_fmp`(:784) 四处发送侧统一调用。子服务 worker 读 `symbol` 现可命中。同类 AKShare/FMP 错位的发送侧一并修复（FMP `facade.py`/`workers/collectors/fmp.py` 已显式传 symbol 不在此列）。手动验收命令：`uv run python -c "from backend.services.datasource.router import DataSourceRouter as R; p=R._normalize_outbound_params({'ticker':'AAPL'}); assert p['symbol']=='AAPL'"` → 通过；端到端复刻 worker 读取 `params.get('symbol')` 命中 `AAPL`。`backend/tests/test_data_source_router.py::TestOutboundParamNormalization` 新增 4 个回归用例（逻辑已通过 `uv run python -c` 确证），但本仓库 pytest 因 vectorbt `safe-delete` 在 collection 阶段抛 `SystemExit(1)` 导致模块级 ERROR，需先在 CI 环境修复该副作用方可常驻（ponytail: 不为此 hack conftest，超出 08b 范围）。
- [x] **[BE-ARCH-08c]** **Futu 长连接推送四处断链（② 破口 · 线上"实时"实为 10s 轮询）**：`quant:quotes:stream` 频道名两侧逐字符一致、protobuf 编解码亦匹配（`shared/proto/market.proto` ↔ `frontend/src/lib/proto/market.js` ↔ `use-market-data.ts:241`），消费侧 `market_engine.redis_pubsub_listener` 也在 API 进程启动即拉起（`lifecycle.py:149` → `market_engine.py:143-144`）—— **卡在生产侧**：
  - **① 推送桥接从未建立**：`data_subservice/main.py:177` `await asyncio.to_thread(futu_service.connect)` 使 `_register_push_handlers` 在工作线程执行，其中 `asyncio.get_running_loop()` 必抛 `RuntimeError` → 走到 `connection_manager.py:105-106` 的 `logger.warning("无法获取事件循环，推送桥接将不可用")` → `push_handler.set_main_loop` 从未成功 → OpenD 回调协程被丢弃（`push_handler.py:51-54`）。**修法**：改为在事件循环内建连（或 `connect` 时显式传入 `asyncio.get_event_loop()` / 用 `run_coroutine_threadsafe` 前置注册 loop）
  - **② 启动零订阅**：`connection_manager.py` 的 connect 只 `_register_push_handlers()`，**无任何 `quote_ctx.subscribe(...)`**；订阅仅作为 `futu_src/quote_handler.py:81-96` 的副作用发生。没人 subscribe ⇒ OpenD 不推 ⇒ 回调永不触发
  - **③ 重连恢复关掉了推送**：`futu_src/watchdog.py:205,308` `_restore_subscriptions` 用 `subscribe_push=False`，即便曾订阅，重连后变静默订阅
  - **④ 子服务未接主 Redis**：`docker-compose.node-s1.yml` **完全无 Redis 配置**，`data_subservice/_internal/redis_client.py:20` 默认 `localhost` ⇒ publish 进容器内空 Redis 而非主节点总线
  - **⑤ 前端订阅不回传**：WS `subscribe` 仅更新主服务本地字典（`routers/market.py:101-107` → `market_engine.py:166-172`），不通知子服务去 OpenD 订阅新标的 ⇒ 新标的只能等 `broadcast_loop` 约 10s 后 HTTP 拉快照"碰巧"触发订阅
  - **实际落地（2026-08-09 ② 批次）**：① ②③④ 先行闭环；**本批次补齐 ⑤**：新增 `quote_handler.subscribe_quote`（QUOTE+ORDER_BOOK `subscribe_push=True`，与 `get_quote` 内联订阅段同构）→ `FutuService.subscribe_quote` 暴露 → `futu_worker` 补 `SUBSCRIBE`/`UNSUBSCRIBE` 分支 → `router._FUTU_ACTION_MAP` 声明 `subscribe/unsubscribe` → `routers/market.py` WS `subscribe`/`unsubscribe` 在本地登记后 best-effort `asyncio.create_task(fetch_futu("subscribe"/"unsubscribe", ticker=t))` 回传子服务（经 `is_futu_unsupported` 守卫，不阻塞 WS ack，子服务不可用由 router 熔断吸收）。闭环后新标的订阅即时通知 OpenD 实时推送，不再依赖 10s 轮询碰巧触发。验收：`test_cross_process_contract.py::TestFutuSubscribeCallbackContract` 断言 SUBSCRIBE/UNSUBSCRIBE 经子服务真实落到 worker 且取到 `symbol`；`futu_worker` 分支手动确证。`is_futu_unsupported` 守卫沿用 `broadcast_loop` 既有逻辑，未扩大范围。
    - **① 根因修复**：`connection_manager._register_push_handlers` 的 `except RuntimeError` 分支回退 `asyncio.get_event_loop()`（不再仅 warning）；`main.py:startup_event` 在 `to_thread(connect)` **前**显式 `set_main_loop(asyncio.get_event_loop())` 双保险 → 推送桥接 `_main_loop` 不再为 None，OpenD 回调可经 `_schedule_coroutine` 入主循环。
    - **② 已在位**：`quote_handler.get_realtime_quote:81-96` 首次 fetch 即 `subscribe(subscribe_push=True)`，启动零订阅的"破口"实为 fetch 副作用已覆盖，无需额外改 connect。
    - **③ 重连静默修复**：`watchdog.py:205`(健康探针订阅) 与 `:308`(`_restore_subscriptions` 重连恢复) 的 `subscribe_push=False` 均改 `True` → 重连后推送订阅恢复，不再静默。
    - **④ s1 Redis 修复**：`docker-compose.node-s1.yml` 补 `REDIS_HOST/PORT/PASSWORD/DB` + `ENABLE_REDIS_HEARTBEAT=true`，经 `host.docker.internal` 连主 Redis 总线（与主服务同机），推送 publish 不再进容器内空 Redis。
    - **⑤ 后续项（未本次实现）**：跨层（market_engine→router.fetch_futu("SUBSCRIBE")→futu_worker SUBSCRIBE 分支→futu_service.subscribe）且**完全无法在本环境验证**（无 OpenD/前端）。按 §10「理解问题后最小改动、不做不可验证猜测」，留作独立后续任务，需配套新增 `futu_worker.SUBSCRIBE` 分支 + `fetch_futu` 透传 + 前端订阅回传链路测试。
    - **验证**：三个 Python 文件 lint 0 错误；① 的 loop 注入双保险逻辑、②③④ 的 `subscribe_push`/Redis 配置均经代码静态核查确认；⑤ 因环境限制未实现故未做运行时验证。
- [x] **[BE-ARCH-08d]** **子服务错误体被吞成成功（① 可靠性破口 · 限流感知失效）**：`router.py:349-352` 的 `_normalize_response` **只识别 `data.error`**，不识别 `data.status == "error"`；而 FMP / Finnhub 的子服务实现返回 `{"status":"error", ...}` 且不带 `error` 键 ⇒ 落入成功分支，随后 `result.setdefault(k, v)`（`:355-358`，明确"不覆盖状态字段"）也无法翻回 ⇒ **配额耗尽与 429 被当成有数据返回**，`error_category` 判定与 `RateLimitThrottler` 退避在这两源上完全失效，违反 `AGENTS.md` §10.8。**修法**：`_normalize_response` 增加 `data.get("status") == "error"` 与 `data.get("error_category")` 识别分支 + 补契约用例
  - **落地**：`router.py:_normalize_response` 失败判定由 `data.get("error")` 扩展为 `data.get("error") or data.get("status")=="error"`，失败体透传 `error_category`；`fetch_fmp`/`fetch_finnhub` 失败分支新增 `error_category` 透传 → `_update_node_status`（限流类走退避而非普通失败计数）。
  - **验收**：`tests/test_data_source_router.py::TestNormalizeResponseErrorBody` 5 例（status_error_no_key / status_error_cat / legacy_error_key / success / nonzero）全部通过；`_normalize_response({'status':'error','error_category':'quota'})` 返回 `status=error` 且 `error_category=quota`，成功体不受影响。本环境 pytest 因 vectorbt safe-delete 的 `SystemExit(1)` 副作用无法常驻运行，改用手动 `uv run python -c` 确证。

#### P1 · 可靠性缺陷

- [x] **[BE-ARCH-08e]** **单节点 pin 源熔断后永不恢复（无半开探测）**：3 次普通错误 → `status="unhealthy"` + 冷却时间戳（`router.py:516-520`），但 `status` **仅在请求成功时**才回到 healthy（`:511-513`）；而 9 个单节点 pin 源（akshare / tushare / futu / fmp / finnhub / fred / dbnomics / rbi / search）在各 `fetch_*` 入口一律 `if ... remote_node.status != "healthy": return`（`:641,681,727,787,828,861,894,927,960`）⇒ 不发请求就不可能成功，不成功就永远 unhealthy ⇒ **熔断一次即永久失效，直到进程重启**。`circuit_breaker_until` 冷却仅在 YF 多节点的 `_get_healthy_nodes` 被检查（`:480`），且那里同时还要求 `status=="healthy"`。**修法**：pin 源入口改为 `status=="healthy" or now >= circuit_breaker_until`（冷却到期放行一次探测），成功则 CLOSED、失败则续冷却 —— 对齐子服务侧已有的 HALF_OPEN 实现（`data_subservice/_internal/circuit_breaker.py:77-87,160-169`）
  - **落地**：新增 `DataSourceRouter._pin_node_usable(node)` 半开门控（healthy 直接可用；unhealthy 且 `time.time() >= circuit_breaker_until` 放行一次 HALF_OPEN 探测）。将 9 个 pin 源入口的 `remote_node.status != "healthy"` 门控统一替换为 `not self._pin_node_usable(remote_node)`。探测成功由既有 `_update_node_status` 翻回 healthy，失败则续冷却。YF 多节点（走 `_get_healthy_nodes`）本已尊重冷却，未改动。
  - **验收**：`tests/test_data_source_router.py::TestPinNodeHalfOpenProbe` 3 例（healthy 放行 / 冷却中拦截 / 冷却到期放行）全部通过；手动 `uv run python -c` 确证 `_pin_node_usable` 三种态正确。pytest 因 vectorbt safe-delete `SystemExit(1)` 副作用本环境不可常驻运行。
- [x] **[BE-ARCH-08f]** **AKShare STALE 降级只写不读（DIST-19 实际未生效）**：`_save_akshare_stale` 在成功路径写缓存（`router.py:656,989-997`），但 `_get_akshare_stale` **从未在 `fetch_akshare` 失败路径被调用**（全仓仅测试引用）⇒ 远程失败时返回裸错而非 STALE 缓存，与 DIST-19 声称的"MASTER 返回 STALE 而非裸错"不符。同理 `_get_akshare_cache` 未接入 fetch 热路径。**修法**：失败路径调用 `_get_akshare_stale` 并打 `degraded:true` 标记
  - **落地**：`fetch_akshare` 远程失败（含 `except` 路径）末尾增调 `await self._get_akshare_stale(action, kwargs)`；命中即返回该降级体（`_get_akshare_stale` 已带 `degraded:True`/`stale_source:True` 并上报指标），仅当无 STALE 缓存时回裸错。`_get_akshare_cache` 热路径接入属未请求增强，按 §10 不做范围蔓延。
  - **验收**：`tests/test_data_source_router.py::TestFetchAkshareStaleDegrade` 2 例（远程失败→STALE 降级 / 远程失败且无缓存→裸错）手动确证通过；`fetch_akshare` 在远程失败后返回 `status=success` 且 `degraded=True`/`stale_source=True`，无缓存时返回 `status=error`。pytest 因 vectorbt safe-delete `SystemExit(1)` 副作用本环境不可常驻运行。
- [x] **[BE-ARCH-08g]** **FMP 的 `FUNDAMENTAL` / `INFO` 无 worker 分支（Facade 必失败）**：适配器声明了这两个能力（`adapters/fmp.py:59-60`），但 Router 无映射（`router.py:777-782` 仅 quote/profile/income_statement）故原样上传，`data_subservice/fmp_worker.py:23-24` else 返回"未知 fmp action" ⇒ Facade 的 `get_fundamental` / `get_fundamental_info`（`facade.py:154,163`）一旦按权重选到 fmp 必失败。**修法**：`FUNDAMENTAL`→`INCOME_STATEMENT`、`INFO`→`PROFILE` 建立映射，或从 capabilities 与 Facade 候选中摘除（与 07i 的对齐工作同源，属遗漏项）
  - **落地**：`router._FMP_ACTION_MAP` 显式补 `fundamental→FUNDAMENTAL` / `info→INFO`；`fmp_worker.py` 补 `INFO` 分支（= `get_profile`）与 `FUNDAMENTAL` 分支（组合 `get_profile` + `get_income_statement`，仅复用已存在方法，不臆测 `fmp_service.get_fundamental`）。Facade 选到 fmp 不再必失败。
  - **验收**：`tests/test_data_source_router.py::TestFmpFundamentalInfoRouting` 断言 `fetch_fmp("fundamental"/"info")` 经 `_FMP_ACTION_MAP` 映射为 worker 可识别的 `FUNDAMENTAL`/`INFO`；手动 `uv run python -c` 确认 `fmp_worker.handle_fmp("INFO"/"FUNDAMENTAL")` 返回 `status=success`（FUNDAMENTAL 含 `profile`+`income_statement`），未知 action 仍返回 error。pytest 因 vectorbt safe-delete `SystemExit(1)` 副作用本环境不可常驻运行。

#### P2 · 根治测试盲区

- [x] **[BE-ARCH-08h]** **跨进程契约测试（根治 08b / 08d 类缺陷的唯一手段）**：现有 `SVC-01` 的 vcrpy 录制回放未校验 params 键名，07n 守门只查 import 与域名字面量，离线 stub 又在 payload 构造前短路 ⇒ 三层测试都看不见跨进程契约错位。新增契约测试：**真起 `data_subservice`**（或用 ASGI transport 直连 `data_subservice.main:app`，绕过网络但保留真实 handler 分发），在 `OFFLINE_MODE=0` 下对**每个源每个 action** 断言：① 主服务发出的 params 键名能被 worker 正确取到（非 None）② worker 的错误体能被 `_normalize_response` 正确识别为失败 ③ 未声明能力返回 503、未知 source 返回 400、HMAC 失败返回 403 三条边界。可复用 `backend/tests/test_data_subservice_dist06.py` 的既有 import 方式
  - **落地**：新增 `backend/tests/test_cross_process_contract.py`，用 `TestClient` 真起 `data_subservice.main:app`（ASGI transport，保留真实 handler 分发），mock 各 `handle_*` worker。覆盖：① 主服务经 `_normalize_outbound_params` 发出的 `ticker` 经边界后子服务 worker 能取到 `symbol`（08b 回归，FMP/AKShare 双源）② 子服务 `{"status":"error","error_category":"quota"}` 体经主服务 `_normalize_response` 判失败并透传 `error_category`（08d 回归）③ 三条边界：未声明能力→503 / HMAC 失败→403 / 缺 HMAC→403。
  - **验收**：脚本 `_verify_be_arch_08h.py`（本环境 pytest 因 vectorbt safe-delete `SystemExit(1)` 副作用不可常驻运行，改手动驱动同断言）6 项全通过：① FMP/AKShare 的 `symbol` 对齐、② 08d 错误体判失败+`error_category` 透传、③ 503/403/403 三边界。正式 pytest 用例已写入 `test_cross_process_contract.py` 待 CI 常驻运行。


### Hermes Agent 内核治理（AGENT 系列 · 2026-08-16 · 对标 hermes-agent / deepseek-harness）

> **📌 任务明细 SSOT：[`docs/TODO-AGENT-ARCH.md`](./TODO-AGENT-ARCH.md)**（含现状基线 S1~S13、借鉴矩阵、分阶段路线图、明确不借清单）。此处仅留索引，勿在两处各写一份。
>
> **结论：hermes-agent 与 deepseek-harness 均不引入，只借架构范式** —— 前者是产品不是库；后者是 TS 且建库仅 3 天的 developer preview。

| 阶段 | 任务 | 一句话 |
|:---|:---|:---|
| P0 前置 | **[AGENT-04]** ReAct 单驱动收口 | `_step_loop:645` 与 `chat_stream_async:778` 两套实现，不合并则以下每项都要写两遍 |
| P1 红线 | **[AGENT-02]** 工具执行中间件管线 | `tool_registry.py:94` 无扩展点；§4.4「连续失败 3 次熔断」**从未实现**。Phase 1 共同落点，先做 |
| P1 红线 | **[AGENT-07]** 逐笔交易审批闸门 | `engine/gateway.py` 是配置态静态锁，不是逐笔确认；需 fail-closed + 审计对 |
| P1 红线 | **[AGENT-08]** Verify 阶段实装 | §4.1 强制四段式，代码里 Verify 是空的 |
| P1 红线 | **[AGENT-09]** 工具结果正交分类 | success/empty/stale/rate_limited/error 各自独立；直接解 Futu 文档 §0.5 空结果三态不可分 |
| P1 审计 | **[AGENT-01]** 会话事件日志 append-only | 历史被原地改写，无法重建"模型当时看到了什么" |
| P1 审计 | **[AGENT-10]** 密钥作用域与日志脱敏 | 全仓无 redact 实现，却持有券商凭据 |
| P1 成本 | **[AGENT-03]** 工具集按场景分发 | 37 个工具 schema 每步全量注入 |
| P2 成本 | **[AGENT-11]** Prompt 缓存边界 + Token 计量 | 与 AGENT-03 协同：schema 子集稳定才谈得上命中 |
| P2 成本 | **[AGENT-12]** 重复/停滞守卫 | 现在唯一止损是 `max_iterations=8`，不区分推进与打转 |
| P2 成本 | **[AGENT-05]** 脚本经 RPC 批量调工具 | 收益最高成本最高；须沙箱且禁触交易工具 |
| P2 韧性 | **[AGENT-06]** LLM Provider 适配缝 | 锁死 DeepSeek，Agent 层唯一单点 |
| P2 扩展 | **[AGENT-13]** 自家工具暴露为 MCP Server | 想用 dsh/Cursor 当客户端的**正确接法**：我们供工具，不引入对方运行时 |
| P2 扩展 | **[AGENT-14]** 子代理并行编排 | 多标的横截面分析目前串行 |

> **连带清账**：`docs/TODO-frontend.md:69` 的 **[TEST-11]** 标 `[x]` 却声称验证了"推理步进 / Tool 路由 / 熔断中止（连续失败 3 次）/ 上下文裁剪"四项，`backend/tests/test_agent.py` 实际一项都没有 —— 属虚标完成，随 AGENT-02 回填（详见 TODO-AGENT-ARCH.md S13）。

### 告警中心子系统（2026-07-12 新增，对标 TradingView Alerts）

> `docs/01 §十` 设计已两个版本但此前无任务承接。这是"盯盘工具 → 无人值守系统"的分水岭功能，也是移动端推送的前置依赖。

- [x] **[ALERT-01]** 告警引擎 Worker：`backend/workers/alert_engine.py` 常驻进程订阅 Redis 行情流，规则匹配（价格穿越 / 指标阈值 / 策略信号），触发去重（同规则冷却期）+ 写入 `alerts` 表；规则 Schema 先行（Pydantic + Alembic 迁移）✅ **AlertEngine + alert_models + 18 tests**
- [x] **[ALERT-02]** 告警规则 CRUD API：`/api/v1/alert/rules` 全套接口（对照 `docs/10`），支持规则启停、触发历史查询 ✅ **9 端点 + 30 tests**
- [x] **[ALERT-03]** 多通道推送：应用内（WebSocket 推送 + 角标）、飞书 Webhook（复用 OBS-02 通道）、Telegram Bot；按 `docs/01 §10.4` P0~P3 优先级路由 — 📐 `docs/18` · ✅ **2026-07-13 全链路落地（03a~d）**：
  - [x] **[ALERT-03a]** Dispatcher 核心：`alert_dispatcher.py` + PriorityResolver + ChannelPlanner + CooldownGate + DeliveryRecord；AlertEngine 改调 dispatcher ✅ **58 tests**
  - [x] **[ALERT-03b]** 三通道适配器 + RetryQueue：`alert_adapters/`（InApp/Feishu/Telegram）+ RetryQueue + DLQ；NotificationService 收敛为 dispatcher 薄包装
  - [x] **[ALERT-03c]** WS 端点：`/alert/ws` WebSocket + Redis `quant:alerts:push` 订阅转发 + 心跳 + 连接池；engine/status 扩展 dispatcher health
  - [x] **[ALERT-03d]** 投递可观测：`GET /alert/events/{id}/deliveries` + events `since` 补拉参数 + DeliveryRecordResponse
- [x] **[ALERT-04]** 前端告警中心页面 ✅ **2026-07-13 全链路落地（04a~e）**：
  - [x] **[ALERT-04a]** 类型定义 + API Hook：`types/alert.ts` + `use-alert-api.ts`（useAlertRules/useAlertEvents/useAlertWebSocket）
  - [x] **[ALERT-04b]** 告警中心页面：`features/alert/alert-center.tsx`（左侧规则列表 + 右侧事件历史 + 新建表单 Modal）
  - [x] **[ALERT-04c]** 路由注册 + 侧边栏入口：`/alerts` 路由 + `Bell` 图标导航项（风控域）
  - [x] **[ALERT-04d]** 行情页右键入口：自选股右键菜单"设置价格告警" → 派发自定义事件 → 告警中心打开表单
  - [x] **[ALERT-04e]** 前端测试：`tests/features/alert-center.test.ts`（11 tests）
- [x] **[ALERT-05]** 技术指标告警：依赖后端指标计算（RSI 超买超卖 / MACD 金叉死叉 / 均线穿越），收盘价触发 + 盘中节流评估 ✅ **2026-07-13 全链路落地（05a~d）**：
  - [x] **[ALERT-05a]** 模型扩展：`alert_models.py` 新增 `RSI_THRESHOLD`/`MACD_CROSS`/`MA_CROSS` 规则类型 + `evaluate_indicator_rule()` 评估函数
  - [x] **[ALERT-05b]** 指标评估器：`indicator_evaluator.py`（IndicatorEvaluator 节流+缓存+评估 + `extract_indicators_from_tech_data` 数据提取）+ AlertEngine 集成（`_evaluate_indicator_rules` + `_fetch_indicators` + `_create_indicator_event`）
  - [x] **[ALERT-05c]** 前端适配：`types/alert.ts` 新增指标类型 + `alert-center.tsx` 表单条件渲染（RSI 阈值/MACD 方向/MA 周期+方向）
  - [x] **[ALERT-05d]** 测试：`test_alert_indicator_bt05.py`（32 tests）

### 数据正确性（2026-07-12 新增，量化命门第二阶段）

> BE-16 已解决复权/时区，但缺 point-in-time 语义与幸存者偏差处理——**这两项不做，所有回测收益率系统性偏乐观**。机构级数据供应商（Norgate / QC Data）均以此为底线。

- [x] **[DQ-01]** 幸存者偏差处理：K线数据湖补充已退市/摘牌标的历史数据（Futu `get_stock_basicinfo` 含退市标志），回测标的池按"当日实际存续"动态生成，禁止用当前存续列表回测历史 ✅ **SurvivorshipBiasTracker + UniverseSnapshot + CSV IO + 33 tests**
- [x] **[DQ-02]** 财务数据 point-in-time：财报字段存储附带 `announce_date`（公布日），回测引擎只允许读取"回测时点已公布"的财务数据，防止前视偏差（look-ahead bias）✅ **PointInTimeStore + PITQuery + 前视偏差检测 + 31 tests**
- [x] **[DQ-03]** 数据湖快照版本化：Parquet 按日打不可变快照 + manifest_hash + 回测引用 + 旧快照保留 — 📐 `docs/19` · ✅ **2026-07-13 全链路落地（03a~e）**：
  - [x] **[DQ-03a]** Manifest 与 PG 模型：`manifest.py` + `data_snapshots` + `SnapshotReader` / `SnapshotResolver` / `paths.py`
  - [x] **[DQ-03b]** 快照发布器：`snapshot_publisher.py` hardlink/copy + universe sidecar（`export_snapshot`）+ 质量门禁 + PG/Redis；挂接 `daemon_sync_task` 末尾
  - [x] **[DQ-03c]** 回测引用：`_fetch_backtest_data` / `backtest.py` 优先 SnapshotReader；废弃 `parquet_db` 路径；`live` 受 `ENGINE_ALLOW_LIVE_DATA` 约束
  - [x] **[DQ-03d]** 保留与归档：`snapshot_retention.py` T1/T2/T3 + 月锚点 + tar.gz（可选 R2 uploader）；周日/月初随 daemon 触发
  - [x] **[DQ-03e]** 管理 API：`/api/v1/datalake/snapshots`（list/latest/{id}/rebuild/retention）+ Prometheus 指标；测试 `test_datalake_dq03.py`（6）+ BT-02（14）
- [x] **[DQ-04]** 数据质量看板：SVC-04 校验结果（字段完整性 / 价格跳变 / 时间戳新鲜度）汇总至 Grafana 独立面板，按数据源分维度展示脏数据率趋势 ✅ **2026-07-13**：`quant_data_quality_*` Prometheus 指标 + `quote_publisher` 接线 + `GET /api/v1/system/data-quality` + Grafana `Data Quality (DQ-04)` 看板 + 脏数据率>5% 告警；测试 `test_data_quality_dashboard_dq04.py`（4）


### 后端体验

- [x] **[BE-09]** API 响应统一结构：`{"code": 0, "data": {}, "msg": "ok", "ts": 1234567890}`，严禁各路由自定义格式
- [x] **[BE-10]** OpenTelemetry Trace 接入：所有 API 请求自动注入 `trace_id`，可在 Grafana 追踪全链路 ✅ **2026-07-13**：加固 `otel_config`（采样率/NoOp 退化/httpx+SQLAlchemy）；`X-Trace-Id` 中间件；monitoring profile 增加 Tempo + Grafana Tempo datasource；`test_otel_be10.py`
- [x] **[BE-11]** `/api/v1/health` 健康检查端点：包含 Redis ping、DB ping、Futu 连接状态三项
- [x] **[BE-12]** Hermes Agent Tool 调用结果统一缓存（Redis Hash，TTL 可配置），避免重复打外部 API ✅ **2026-07-13**：`hermes_agent/tool_result_cache.py` + `ToolRegistry.execute()` 统一命中；键 `tool:cache:{name}:{args_hash}`；`TOOL_CACHE_ENABLED` / `TOOL_CACHE_DEFAULT_TTL` / `TOOL_CACHE_TTL_{TOOL}` / `TOOL_CACHE_NO_CACHE`；错误与限流不缓存；8 tests
- [x] **[BE-19]** OpenAPI/Swagger 文档完善：所有接口补全 summary/example，导出 schema 与 `docs/10` 互校 ✅ **2026-07-13**：`openapi_schema.py` 自动补 summary + 统一信封 example；`scripts/export_openapi.py` → `docs/openapi.json`（126 paths）；`docs/10` V1.1 纠偏 chat/history/ws/oms/internal；`test_openapi_be19.py` 7 passed
- [x] **[BE-20]** Agent Tool 调用健壮性：RL-14 已实现 `rate_limit_aware_request` 限流感知智能重试 (HTTP 429/503 + 指数退避 + 最大 3 次重试)，超时控制由 SecureAsyncClient 统一处理


### Risk 风控模块进阶能力 (v0.2+)

> 设计文档: `docs/subsystems/risk-module.md`
> 已完成: 分账户独立风控计算 (HK/US) · 六维风险雷达 · 因子监控 · 净值曲线持久化 (Redis+DB) · 行业级版面布局

- [x] **[RISK-01]** 板块暴露分析：获取每只持仓行业分类 (Futu `get_stock_basicinfo`)，按 GICS 聚合，前端横向柱状图展示板块集中度 ✅ **4 tests**
- [x] **[RISK-02]** Beta/Alpha 归因：Jensen's Alpha (Market 因子)，超额收益分解，归因百分比 ✅ **3 tests**
- [x] **[RISK-03]** 相关性矩阵：计算持仓间 60 日收益率相关系数矩阵，前端热力图可视化，高相关性 (>0.8) 预警 ✅ **3 tests**
- [x] **[RISK-04]** 压力测试：历史情景回放 (2008/2020/2022) + 假设情景 (利率+1% / 汇率-5% / 波动率翻倍)，展示压力后 NAV 变化 ✅ **5 tests**
- [x] **[RISK-05]** CVaR 分解：Conditional VaR (Expected Shortfall)，按持仓分解 CVaR 贡献度，边际 VaR 分析 ✅ **4 tests**
- [x] **[RISK-06]** 流动性风险评估：持仓日均成交额 vs 市值 → 流动性覆盖率，大额持仓预警 (>10% NAV)，流动性评分 (0-100) ✅ **3 tests**
- [x] **[RISK-07]** 风险雷达真实数据增强：Liq/Corr/Mom 接入真实波动率/相关性矩阵/20 日动量计算 ✅ **2 tests**
- [x] **[RISK-08]** Beta 基准对接：获取真实基准指数 K 线 (^GSPC / ^HSI) 计算 OLS 斜率，替换占位值 0.85 ✅ **2 tests**

### OMS 订单中枢与算力节点 (v0.2+)

> 设计文档: `docs/subsystems/oms-module.md`
> 已完成: Mock Bot卡片/挂单/成交/算法UI · WebSocket实时推送 · KillSwitch熔断 · 幂等性撤单 · 真实Futu下单+ATR风控 · **OMS-01~04 核心闭环 (订单持久化/成交打通/状态同步/持仓同步)**
> 核心问题: OMS面板与真实交易链路完全脱节，全量 Mock 数据

#### P1 - 核心闭环 (真实数据接入) ✅

- [x] ~~**[OMS-01]** 订单持久化~~：PostgreSQL `orders` 表 + `oms_service.create_order()` + 撤单/改单同步
- [x] ~~**[OMS-02]** 成交记录打通~~：OMS 面板从 `trade_logs` 表读取真实成交记录
- [x] ~~**[OMS-03]** 真实订单状态同步~~：Futu 下单后写入 DB + Redis PubSub 广播 + 撤单/改单同步
- [x] ~~**[OMS-04]** 持仓实时同步~~：30秒定时守护进程从 Futu 拉取真实持仓写入 Redis 缓存

#### P2 - 算力节点 (策略运行时)

- [x] **[OMS-05]** 策略运行时引擎：`/deploy-to-oms` 升级为真实 Python 多进程执行器，管理策略生命周期 (启动/暂停/恢复/终止)
- [x] **[OMS-06]** Bot 真实资源监控：`psutil.Process` 采集真实 CPU/MEM，替代 Mock 随机数
- [x] **[OMS-07]** Bot 日志持久化：策略运行日志写入 Redis List + 定期归档 PostgreSQL

#### P2 - 算法拆单引擎

- [x] **[OMS-08]** TWAP/VWAP 真实执行引擎：基于定时器的拆单逻辑 (按时间/成交量切片)，通过 `trade.py` 真实下单
- [x] **[OMS-09]** 算法执行进度持久化：Redis Hash 存储执行进度 + DB 归档已完成任务

#### P2 - 安全与体验

- [x] **[OMS-10]** Kill Switch 安全加固：替换 `window.confirm` 为全局 ConfirmDialog (SEC-09)，输入 "CLOSE ALL" 二次确认
- [x] **[OMS-11]** 沙箱/实盘模式切换：顶部模式标识 (SANDBOX/LIVE)，切换时全局横幅颜色变化 + 二次确认
- [x] **[OMS-12]** 订单审计日志：所有发单/撤单/改单/熔断操作写入 `audit_logs` 表 (SEC-12)，携带 trace_id + IP

### 工程规范治理（2026-07-08 Review 新增，源自 `docs/02` V4.3 合规审查）

> 规范与现实脱节治理：存量超限文件逐步拆分 + 规范文档自身修正。
> 原则：**新增代码严格执行 §3.2 行数限制**；存量文件按优先级滚动治理，禁止"下次再拆"。

#### P0 — 规范公信力修复

- [x] **[SPEC-01]** 存量超限文件拆分：将三大超限 service 文件按职责拆分为包目录，每个子文件 ≤400 行，保持所有现有 import 路径零修改。✅ **2026-07-20**：拆分完成
  - `backend/services/screener_service.py` **1838 行** → `backend/services/screener/` (7文件: constants/models/nlp_translator/dsl_parser/daemons/service/__init__)
  - `backend/services/yfinance_service.py` **1480 行** → `backend/services/yfinance/` (7文件: utils/service/quote/technical/search/macro_daemon/__init__)
  - `backend/services/akshare_service.py` **912 行** → `backend/services/akshare/` (5文件: service/flow/quote/calendar/__init__)
  - 原文件保留为 ~5 行 shim 兼容层，122 个测试全部通过
- [x] **[SPEC-02]** §8.0 部署拓扑对齐：将"三节点矩阵部署"修正为四节点架构（US-MASTER + US-YF-A/B + CN-AKSHARE），与 `AGENTS.md §9` 保持一致。✅ **2026-07-20**：已完成
- [x] **[SPEC-03]** 前端超限文件治理（第一批）。✅ **2026-07-20**：拆分完成
  - `backtest.tsx` 627→63行：拆为 backtest-mock / use-backtest / backtest-config / backtest-results
  - `alert-center.tsx` 624→171行：拆为 alert-lists / create-rule-form
  - `risk.tsx` 594→51行：拆为 risk-types / risk-account-section / risk-advanced-panel
  - `screener-context.tsx` 451→337行：提取 use-screener-ws hook

#### P1 — 规范文档修正

- [x] **[SPEC-04]** §2.2 SOLID 章节精简：删除 LSP/ISP 通用教科书示例（~60 行），保留项目特有判断标准（如"无第二实现时禁止 Interface"），压缩为一张表 + 3 条规则
  - 落地：`docs/02` §2.2 重写为「速查表（S/O/L/I/D 红牌信号）+ 3 条项目特有规则」，净删 111 行
  - 三条规则：① 无第二实现禁止抽象 ② 抽象以 docs/14·15 已落地契约为准 ③ 拆分以职责边界为准不以预测为准；变更日志升 V4.3.3
- [x] **[SPEC-05]** §0.1 L0 版本对齐：`.cursor/rules/vibe-coding.mdc` 当前为 V2.1，在 §0.1 表格增加「最后更新日期」列，消除 L0(V2.1) vs L2(V4.3) 版本号歧义
  - 落地：`docs/02` §0.1 SSOT 表新增「最后更新日期」列（L0=2026-07-21 / L1=2026-07-25 / L2=2026-07-25 / L3=2026-07-25 / L4=2026-06-27），表内补全各层版本号，并加「版本号独立维护说明」脚注；L0 文件头部补充「最后更新」行；`docs/02` 头部版本号由滞后的 V4.3.1 修正为 V4.3.4，变更日志补 V4.3.4 条目
- [x] **[SPEC-06]** §7.6 PCE 分级确认：L0 冻结区必须 Confirm；L2 开放区可自主执行无需逐一确认；增加「批量任务模式」说明
  - 落地：`docs/02` §7.6 改为「分级确认矩阵」（L0 必须显式 Confirm / L1 单次 Confirm / L2 开放区 Plan 获批即自主 Execute 无需逐条 Confirm）；新增「批量任务模式（Batch Mode）」：单任务 ID 整批授权、按序自主执行、越界 L0/L1 立即补单 Confirm、收尾按 atomic commit；版本升 V4.3.5
- [x] **[SPEC-07]** §5.1 技术栈指针修正 ✅ **2026-08-09**：
  - "移动端 Flutter 三端" → **更正而非删除**：项目实际存在 Flutter 代码（`client/flutter_app/`，91 个 .dart / 184 文件，独立仓库），原 TODO 称"项目中无 Flutter 代码"前提错误；改为标注「独立仓库 `client/flutter_app/`」。`docs/02` §5.1 第 479 行已更新。
  - "DuckDB/Parquet" → **确认仍在使用**（BE-02 三级历史 K 线缓存温层为 DuckDB/Parquet），保留并加注。`docs/02` §5.1 第 476 行已更新。
- [x] **[SPEC-08]** §6.1 print() 豁免或代码修复：`hermes_agent/tools/web_scrape_tool.py` 中大量使用 `print()` 做降级日志，二选一：(a) 改用 structlog (b) 在规范中豁免 Tool 层 CLI 输出
  - 落地：选 (a) 代码修复——`web_scrape_tool.py` 的 5 处 `print()` 降级日志全部改为 `structlog` `logger.warning(...)`（jina 反爬/失败、HTTP 内容过少/失败、RAG 提取失败），新增模块级 `logger = structlog.get_logger(__name__)`；`docs/02` §6.1 明确「禁止 print()」铁律覆盖 Tool 层，拒绝选项(b)豁免；版本升 V4.3.6
- [x] **[SPEC-09]** §4.2 覆盖率目标校准：Hermes Tool ≥90% 实际不可达（`hermes_agent/tools/` 几乎无测试），降为 ≥70% 或标注为「目标」而非「门禁」
  - 落地：`docs/02` §4.2 Hermes Tool 行由「≥90% 门禁」改为「≥70%（目标，非门禁）」，补说明：该层当前几乎无测试，70% 仅为长期补齐方向、不阻断合并，优先给 web_scrape_tool 等有降级分支的工具补最小单测；版本升 V4.3.7

#### P2 — 规范缺失补充

- [x] **[SPEC-10]** 新增「环境变量管理规范」章节：`.env` 已有 50+ 变量，需定义分组命名约定（`DS_CAPABILITIES` / `FUTU_*` / `LLM_*`）、必填/可选标注、`.env.example` 同步规则
  - 落地：`docs/02` 新增 §十 环境变量管理规范（分组命名表 + 必填/可选标注规则 + `.env.example` 同步门禁），对齐实际 `.env.example` 前缀
- [x] **[SPEC-11]** 新增「错误码分配规则」：后端已有 `error_codes.py`，规范中补充错误码段位分配（如 1xxx=认证 / 2xxx=行情 / 3xxx=交易）
  - 落地：`docs/02` 新增 §十一 错误码分配规则，对齐真实 `backend/core/error_codes.py` 段位（0 成功 / 1xxx 认证 / 2xxx 请求资源 / 3xxx 基础设施 / 4xxx 保留 / 5xxx 内部），含 5 条分配规则
- [x] **[SPEC-12]** 新增「数据库迁移规范」：Alembic 迁移脚本命名规则（`{rev}_{scope}_{desc}.py`）、审查要求（禁止 DROP COLUMN 无确认）、回滚脚本必备
  - 落地：`docs/02` 新增 §十二 数据库迁移规范（Alembic），命名规则 `{rev}_{scope}_{desc}.py` 对齐现有 `pt01a_*`/`strat03a_*`/`fe05b_*`/`ai04rag_*`，含 DROP COLUMN 审查、回滚必备、幂等要求
- [x] **[SPEC-13]** 新增「前端性能预算」：Bundle Size 门禁（主包 ≤500KB gzip）、Lighthouse Desktop ≥90、路由级 code-splitting 规则
  - 落地：`docs/02` 新增 §十三 前端性能预算，对齐 `frontend/vite.config.ts` 与 `lighthouse:baseline` 脚本；含主包≤500KB gzip、Lighthouse Desktop≥90 门禁、路由级 React.lazy 强制拆分规则

### 后端架构治理（2026-07-08 Review 新增，源自 `docs/03` V5.1 架构审查）

> 核心问题：文档设计意图优秀（整洁分层/Port隔离/插件化），但落地现实与文档存在显著鸿沟。
> 原则：**新增代码严格走 app/ 编排层**；存量按优先级渐进收口。

#### P0 — 架构硬伤修复

- [x] ~~**[ARCH-01]** `main.py` 瘦身（原 **1527 行** → **194 行**，仅保留 `create_app()` + 路由挂载）~~ ✅ **2026-07-08**
  - 端点迁出: `routers/chat.py` (343行) + `routers/settings.py` (121行) + `routers/system_health.py` (175行) + `routers/mcp.py` (74行)
  - 启动逻辑拆至 `bootstrap/lifecycle.py` (314行)
  - 中间件拆至 `middleware/stack.py` (176行)
  - 异常处理拆至 `core/exception_handlers.py` (83行)
  - 全量测试 2958 passed, 0 regression
- [x] **[ARCH-02]** 统一熔断器使用 (`core/circuit_breaker.py` 接入所有 `DataSourceInterface.fetch` 主路径，替换手写时间戳熔断)：✅ **2026-07-24** (PR #186 / `d93a7fa`)
- 所有数据源 Adapter 统一使用 `core/circuit_breaker.py`
- `DataSourceInterface.fetch` 主路径内置熔断（半开探测 + 失败计数 + 滑动窗口）
- 冷却时间配置化（env `CIRCUIT_BREAKER_COOLDOWN_S`），禁止硬编码 60s
- [x] **[ARCH-03]** Graceful Shutdown 完整化 (lifecycle shutdown + worker shutdown)：✅ **2026-07-24** (`bootstrap/lifecycle.py` / `worker.py` / `core/graceful_executor.py`)
  - 停止接受新请求 → 等待 in-flight 完成（max 30s）→ 关闭 WebSocket 连接（发送 close frame）
  - 停止所有后台 Task（collector daemons）→ 取消 Redis Pub/Sub 订阅
  - 断开 Futu / Redis / PG 连接 → 关闭线程池（wait=True, timeout=10）

#### P1 — 性能与稳定性增强

- [x] **[ARCH-04]** 连接池参数配置化 + 文档化：✅ **2026-07-24** (`core/database.py` / `core/redis_client.py` / `docs/03 §7.3.1` / `.env.example`)
- PostgreSQL: `pool_size=20, max_overflow=40, pool_timeout=10`（env 配置化，默认 20/40/10）
- Redis: `max_connections=50`（Pub/Sub + 缓存 + 限流共用，`ConnectionPool` 配置化，默认 50）
- 在 `docs/03 §7.3.1` 补充连接池配置规范
- [x] **[ARCH-05]** 健康检查分级：✅ **2026-07-25** (`routers/system_health.py` / `AGENTS.md §10.4`)
  - `GET /health/live` → 进程存活（200 即可，liveness）
  - `GET /health/ready` → 依赖就绪（Redis + PG + 至少一个数据源连通，否则 503）
  - `GET /health/deep` → 全链路诊断（采集器心跳、WS 连接数、线程池使用率、事件循环 lag）
  - 原 `/api/v1/health` 重构为纯 liveness（始终 200，修复 §10.4 违规：此前 Redis 断开即 503）
- [x] **[ARCH-06]** 请求级超时与取消传播：✅ **2026-07-25** (`core/request_timeout.py` / `core/stream_utils.py` / `middleware/stack.py`)
  - 单 API 请求最大执行时间（screener 90s / market 30s / 默认 60s，环境变量可覆盖）
  - 客户端断开后取消下游任务（`Request.is_disconnected()` + 流式 `heartbeat_wrap` 级联取消；`/mcp/sse` 增加显式断开检测）
  - SSE/长轮询心跳间隔 ≤15s（SSE 用 `: keep-alive`，NDJSON 用空行，对齐 Cloudflare 100s 超时）
- [x] **[ARCH-07]** `asyncio.to_thread` 使用分级（审计 2026-07-25：全项目 97 处实际调用）：
  - I/O 密集（akshare/futu/yfinance/redis/pg 同步 SDK、文件读写）→ 保留 `to_thread`（同步库唯一非阻塞手段；非 pandas 纯文件读写后续优先 `aiofiles`）
  - CPU 密集（回测/网格/蒙特卡洛/批量）→ `ProcessPoolExecutor`：新增 `backend/core/cpu_pool.run_cpu_bound`，已迁移 5 处回测调用点
  - 分级策略文档已落地 `docs/03 §7.6.1`；不可 pickle 负载自动回退线程，行为与测试不变

#### P2 — 架构债渐进收口

- [x] **[ARCH-08]** `services/` 按领域分子目录（参照 `services/futu/` 成功模式）：
  - `services/risk/` ← 6 个 risk_*.py 收口（risk_attribution/cvar/engine/liquidity/sector/stress），包内 `__init__` 重导出公开符号
  - `services/screener/` ← 既往已拆分（screener_service.py 保留为兼容层），本次无改动
  - `services/macro/` ← fred + macro_calendar + sentiment 收口，包内 `__init__` 重导出公开符号
  - 验收：顶层不再保留 shim；全仓 `backend.services.risk/macro.<mod>` 规范路径；`test_be_arch02_app_boundary` allowlist 已同步；单测全绿
- [x] **[ARCH-09]** `app/` 编排层扩展（已完成：screener_app / trade_app / macro_app / alert_app）：
  - 优先补：screener_app / trade_app / macro_app / alert_app ✅ 2026-07-25
  - 修正 `docs/03` BE-ARCH-01 状态为「部分收口（21/31 Router）」✅
- [x] **[ARCH-10]** Domain 层实体沉淀（已完成：2026-07-25）：
  - 随 BT-01 落地沉淀 `Strategy`、`Order` 领域对象（已在 `backend/engine/`：`strategy.py` / `contracts.py`，属 Domain 层引擎子集）
  - 随 ALERT-03 落地沉淀 `AlertRule` 领域对象（经 `backend/domain/entities` 聚合门面认领为 Domain 层统一入口）
  - 新增 `backend/domain/entities.py` 统一 re-export `Strategy` / `OrderIntent` / `OrderUpdate` / `AlertRule` / `AlertRuleType`；`backend/domain/__init__` 同步暴露
  - 在 `docs/03` §2.1 标注 Domain 层实体状态（遵循「避免过早复制 DTO」：定义仍留原模块，仅做稳定聚合门面）
- [x] **[ARCH-11]** 启动阶段 print() 全面替换为 structlog（lifecycle.py lifespan 38 处 print + 8 处标准 logger，main.py 2 处 import 期 print）

---

## 社区与协作（COMM）

> COMM-01~02 立项于 `archive/2026-08-15-plan-1.md`，已于 2026-08-14 前后随 DIST-SEC-06 批次完整实现（此前未进活跃 TODO，本次补追踪闭环）。

- [x] **[COMM-01]** 数据源健康度统一看板（P2）：✅ 已落地：`backend/routers/datasource.py` 的 `GET /datasource/health-overview`（卡片矩阵，字段：名称/类别/状态/延迟/今日调用量/成功率/限流次数 + 类别调用细分）+ `GET /datasource/{name}/health`（单源详情）+ `WS /datasource/ws/health`（实时推送 + STALE>5min 报警）；`_build_health_card` 聚合 `rate_limit_registry` 调用/成功/限流统计。`DataSourceHealthModule`（`frontend/src/features/data-center/datasource-health.tsx`）渲染卡片矩阵 + 实时 WS + STALE 报警条 + 测试连接 + YFinance 多节点，路由 `/datasource-health`。覆盖测试：`test_datasource_router.py`、`test_datasource_health_monitor.py` 等。
  - 卡片矩阵（每个数据源：名称/状态/延迟/今日调用量/成功率/限流次数）
  - 数据来自 `/datasource/{name}/health` + `rate_limit_registry`
  - STALE>5min 变红 + WS 推送
- [x] **[COMM-02]** 数据源贡献投票与需求看板（P3）：✅ 已落地：`backend/routers/datasource_vote.py` 的 `GET /datasource-vote/board`（三类：已接入/开发中/社区投票中 + 票数 + 今日已投）+ `POST /datasource-vote/vote`（每用户每源每日一票，Redis 防刷）；`main.py` 已挂载。前端 `DataSourceHealthModule.renderSection` 渲染三类 + `vote()` 调 `/datasource-vote/vote`，1 票/天。覆盖测试：`test_datasource_vote.py`、`test_datasource_macro_adapters.py`（16 passed）。
  - 展示「已接入/开发中/投票中」三类
  - 用户投票（1 票/天）
  - 后端投票记录 + 计数器防刷
