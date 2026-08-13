# 📡 TODO — 数据源（拆分自 TODO.md 2026-08-13）

### 分布式数据源集群（四节点 · 多 VPS + 智能路由 + 监控）

> **架构决策（2026-07-13 · 对齐 docs/06 V9.0）**：
> **US-MASTER**（API/DB/OMS/Futu）+ **US-YF-A/B**（yfinance 双公网 IP）+ **CN-AKSHARE**（仅国内源）。
> 节点间 **Tailscale only**；主节点不声明 `yfinance` 能力（`DS_CAPABILITIES` 不含 yfinance），Yahoo 流量经 `YFinanceRouter` 打到 A/B。
> 顺序：骨架（已完成）→ Compose/部署 → 灰度 → 监控收口。

#### Phase 1 · 服务注册表 + 路由器骨架（主服务侧，可独立验证）

- [x] **[DIST-01]** `ServiceRegistry` 服务注册表实现：`backend/core/service_registry.py`，基于 Redis Hash + Sorted Set + Set 三结构协同，支持 `register` / `heartbeat` / `discover` / `deregister` / `cleanup_dead_nodes` / `mark_draining`；定义 `NodeInfo` Pydantic 模型
- [x] **[DIST-02]** `YFinanceRouter` 客户端路由器骨架：加权轮询 + 过滤熔断节点 + failover + STALE 缓存降级；复用 `core/circuit_breaker.py`
- [x] **[DIST-03]** 路由器单测：mock 子服务验证 failover 链路、熔断器触发、STALE 降级、加权轮询均衡性 (已在 DIST-02 测试中覆盖: 25 tests)
- [x] **[DIST-04]** `YFinanceService` 兼容外壳改造：通过 `YF_ROUTER_ENABLED` 开关在新/旧逻辑间切换，上层调用方零改动 ✅

#### Phase 2 · 子服务工程 + yfinance 核心逻辑迁移

- [x] **[DIST-05]** `data_subservice/` 子服务工程搭建：独立 FastAPI 包，含 `main.py`（启动注册 + 心跳）、`pyproject.toml`、`Dockerfile`
- [x] **[DIST-06]** 子服务 yfinance 核心逻辑迁移：`RateLimitedSession`、缓存、微批处理、宏观守护进程迁移至子服务
- [x] **[DIST-07]** 子服务 HTTP 接口：`/v1/quote`、`/v1/history`、`/v1/batch`、`/v1/macro`、`/v1/health`；429 时返回由主服务决定 failover
- [x] **[DIST-08]** 子服务 `RegistryClient`：启动注册 + 10s 心跳 + 停机注销 + 指数退避重试 ✅ **注册重试 5 次 + 心跳退避 + 8 tests**
- [x] **[DIST-09]** 子服务单测：接口契约验证、限流 429 返回、健康检查、注册/注销流程 ✅ **8 tests**

#### Phase 3 · 四节点通信 + 部署验证

- [x] **[DIST-10]** HMAC-SHA256 签名验证：子服务 auth 中间件 + 主服务侧自动签名 ✅ **已在 DIST-07 实现**
- [x] **[DIST-11]** Docker Compose：`docker-compose.yf-node.yml` + 本机 2×YF 联调 + 主节点 Router
- [x] **[DIST-12]** 灰度切换：`YF_ROUTER_ENABLED=true`，主节点 `DS_CAPABILITIES` 不声明 `yfinance`，对比新旧响应一致性
- [x] **[DIST-13]** US-MASTER 部署（`COMPOSE_PROFILES=master,monitoring`）— CI/CD → VPS_S1
- [x] **[DIST-14]** CN-AKSHARE 部署（slave profile），仅 AKShare→Redis；禁止 YF
- [x] **[DIST-14b]** US-YF-A + US-YF-B：两台美国辅助 VPS、独立公网 IP、对称 `data_subservice`、Registry 双实例对等 weight
- [x] **[DIST-15]** Tailscale：四节点入网 + ACL（master↔ds:8000、ds/cn→master:6379）+ 连通验证
- [x] **[DIST-16]** CI/CD 矩阵：master + yf-node×2 + slave
- [x] **[DIST-17]** 境外源在 US-MASTER 验证（Futu/Finnhub/FRED）；YF 流量应落在 A/B 而非 master
- [x] **[DIST-18]** akshare 在 CN 节点验证（国内直连）

#### Phase 4 · 稳定性 + 监控 + 扩展

- [x] **[DIST-19]** CN 断连降级：MASTER 返回 STALE 而非裸错 ✅ `data_source_router.py` AKShare STALE 缓存降级（远程+本地均失败→Redis STALE 回退 + `degraded:true` 标记）
- [x] **[DIST-20]** Grafana：节点心跳、YF 分节点 429、failover、STALE ✅ `metrics.py` 7 个 Prometheus 指标 + `distributed-nodes-dashboard.json` 面板 + router 集成
- [x] **[DIST-21]** 告警：节点熔断 / YF 存活 <2 / 全挂，接飞书 Webhook ✅ `alerting.yml` 5 条规则（心跳超时/YF 低/全挂/CN 断连/STALE 高频）
- [x] **[DIST-22]** finnhub 迁子服务（可选第三类辅节点）✅ `finnhub_worker.py` + `main.py` lifespan 集成（`DS_CAPABILITIES=finnhub` 启用）
- [x] **[DIST-23]** futu/trade 守护在 US-MASTER（systemd + Watchdog）✅ `scripts/deploy/quant-worker.service`（WatchdogSec=60 + Restart=always + 安全加固）

### ~~数据源限流感知与自适应退避~~ ✅ 全部完成

> RL-01~14 已全部完成并归档，详见下方「已完成归档」。
> 核心能力：错误分类体系 (ErrorCategory) + 退避引擎 (RateLimitThrottler) + 频率分析器 (RateLimitAnalyzer) + Prometheus 指标 + Grafana 告警 + Agent Tool 智能重试 + 路由感知限流。

---


### 三方服务测试与监控（数据源是系统命脉）

> 量化系统所有结论 100% 依赖外部数据源（Futu / YFinance / Finnhub / OpenAI / Ollama / FRED）。三方 API 静默变更字段、限流、宕机是最高频的生产事故源，必须独立测试 + 持续监控。

- [x] **[SVC-01]** 三方数据源契约测试（录制回放）：用 `vcrpy` 录制真实响应为固定 fixture，CI 离线回放，三方改字段时立即让解析层测试变红 ✅ **2026-08-09**：
  - **录制点**：`DataSourceRouter._send_request` 发出的 `httpx` 调用（到 `data_subservice` 的 `POST /api/v1/data`）。cassettes 预置在 `backend/tests/cassettes/`（finnhub_quote / fmp_quote / futu_quote / yfinance_quote / fred_macro_series）。
  - **契约载体**：子服务响应 `{"code":0,"data":...}` → router `_normalize_response` → `{"status":"success","data":...}`；适配器解析 `data` 字段。任一源（Yahoo/Finnhub/FMP/Futu/FRED）改字段 → 对应断言变红。
  - **离线工作流**：默认 `record_mode='none'` 离线回放（`match_on=["method","path"]` 忽略 host/port/签名，端口无关）；`QUANT_RECORD=1` 时连 `ContractMockSubservice`（线程内 mock 子服务）补录 cassette。
  - 新建 `backend/tests/contract_helpers.py`（`ContractMockSubservice` + `get_vcr` + cassette 管理）、`backend/tests/test_contract_replay.py`（5 个契约用例，覆盖 finnhub/fmp/futu/yfinance/fred 字段契约断言）；`conftest.py` 注册 `contract_replay` 标记；`.env.example` 补 `QUANT_RECORD` 说明。
  - 守门：`test_contract_replay.py`（5 用例）离线回放全绿；`vcrpy` 依赖入 `pyproject.toml` + `uv.lock`。
- [x] **[SVC-02]** 三方服务可用性拨测：定时探活 Futu OpenD / YFinance / Finnhub / OpenAI / Ollama / FRED，成功率与延迟写入 Prometheus metrics ✅ **2026-08-09**：
  - **新建 `backend/services/datasource/probe_daemon.py`**：`DataSourceProbeDaemon` 周期（默认 60s）并发拨测 7 个依赖（futu/yfinance/finnhub/fmp/fred 经 `datasource_registry.fetch`，openai/ollama 经 `LLMRouter.health_check()`）。每次探针：计时 → 分类错误（rate_limit/circuit_open/auth/timeout/network/unreachable）→ 写 `call_metrics.record_probe` + Prometheus 探针指标。
  - **独立探针指标（与业务维度解耦）**：`quant_datasource_probe_success`(Gauge 最近成败)、`quant_datasource_probe_latency_milliseconds`(Histogram)、`quant_datasource_probe_total`(Counter)、`quant_datasource_probe_failures_total`(Counter)。业务调用维度 `quant_datasource_availability` 仅在业务流量下刷新；探针维度周期主动刷新，无流量也能反映源存活——正是 SVC-02 价值。
  - **lifecycle 挂接**：`bootstrap/lifecycle.py` startup/stop 挂载 `data_source_probe_daemon`（同 SVC-03/05 模式）。
  - **守门**：`backend/tests/test_datasource_probe.py`（4 用例）验证成功/失败分类/熔断分类/异常不可达，注入底层 fetch/llm_health 真实驱动 daemon 循环，全部离线通过。
  - 探针 action 选用各源最轻量接口（quote/macro_series），失败不触达业务限流退避/熔断器，避免对故障源施压。
- [x] **[SVC-03]** 三方服务监控面板 + 告警 ✅ **2026-08-09**：
  - **Grafana 数据源（API 层，已天然具备）**：`backend/routers/datasource.py` 的 `GET /datasource/health-overview` + `GET /datasource/{name}/health` 经 `call_metrics_store`（已记录 success/calls + 延迟样本）+ `_build_health_card` 返回完整 `status`(含 stale/throttled/blocked/quota_exhausted 等熔断态)、`success_rate`、`today_calls`、`latency_avg_ms/p95_ms`、`rl_*` 限流明细 —— Grafana 可直接 scrape 此 JSON 端点实现成功率/延迟/熔断面板，无需新建采集层。
  - **告警缺口补齐（本轮新增）**：新建 `backend/services/datasource/health_monitor.py` 的 `DataSourceHealthMonitor`，周期（默认 60s）扫描各源当日成功率 + 可达性，成功率 < 95%（且当日调用 ≥ 20 样本防低流量误报）或源失联 → 经 `notification_service.send_alert` 推送**飞书告警（接 OBS-02）**；内置队列解耦 + 15min 去重冷却防告警风暴；`lifecycle.startup` 启动、`lifecycle.shutdown` 停止、`/health/deep` 暴露 `datasource_health_monitor` 探针。
  - 守门：`test_datasource_health_monitor.py`（8 用例，覆盖阈值/去重/生命周期/端到端推送）全绿。
  - 注：限流类告警仍由 `alert_monitor.py`(RL-11) 独立覆盖，本模块不重复告警；Grafana 面板 JSON 属前端展示层，可后续独立交付。
- [x] **[SVC-04]** ⬆️ **已提级 P1（2026-07-12）** 数据质量校验：行情字段完整性、价格异常值（如 0 价/跳变）、时间戳新鲜度检测，脏数据拦截并告警，严禁污染下游分析（与 DIST Phase 3 部署并行推进，结果汇入 DQ-04 看板）✅ **DataQualityMonitor + 19 tests**
  - **[2026-08-09 验证 + 加固]**：实测 SVC-04 已真实落地且接线生效——`quote_publisher.py` 第 129 行对每条行情调用 `get_quality_monitor(source).validate_quote(...)`；`routers/system.py` 暴露 `GET /api/v1/system/data-quality`（DQ-04 看板数据源）；`core/metrics.py` 已建 `quant_data_quality_*` 全套 Prometheus 指标（脏数据率/完整率/价格异常/过期/质量等级/校验次数）。端到端验证：正常 quote 通过、脏数据（零价+负量+过期）被拦截分类、Prometheus 实时刷新、告警回调触发。
  - **修复脏数据率语义 bug**：原 `dirty_rate = anomaly_count / total_records` 在单条记录触发多条异常时 >1（实测 300%），污染 DQ-04 面板。改为 `dirty_records / total_records`（含异常记录数 / 总记录数，恒 ≤1）。`QualityMetrics` 新增 `dirty_records` 字段，`validate_quote` 累加，`reset()` 随重建归零。新增 `test_data_quality_dirtyrate_fix.py`（3 用例）回归。SVC-04 全量测试 26+ 全绿。
- [x] **[SVC-05]** 三方配额与成本监控：OpenAI token 消耗 / 调用次数 / Finnhub 速率配额实时统计，逼近上限提前告警，防止超额停服或账单爆炸
  - **交付（2026-08-09）**：
    - 新建 `backend/services/ai_narrator/token_usage_store.py` 的 `TokenUsageStore`：Redis 分日分桶记录 LLM `prompt_tokens/completion_tokens/total_tokens/calls`，注册 Prometheus 指标 `llm_token_usage_total` / `llm_token_usage_today`；Redis 不可用时内存降级累计（`get_today` 返回降级标记）。
    - 在 `llm_service.py` 的 `generate` / `generate_pydantic` 成功路径插桩 `_record_token_usage(response)`，从 OpenAI `response.usage` 提取 token 消耗，fire-and-forget 异步写入（异常安全，不拖累热路径）。
    - 新建 `backend/services/ai_narrator/quota_monitor.py` 的 `QuotaCostMonitor`：周期（默认 60s）扫描 ① LLM 当日 token 消耗 vs `LLM_DAILY_TOKEN_BUDGET`（达 80% warning / 100% critical）② Finnhub 当日 `rl_quota_exhausted > 0`（硬停服 critical）→ 经 `notification_service.send_alert` 推送飞书（接 OBS-02）；内置队列解耦 + 15min 去重冷却防告警风暴。
    - `lifecycle.startup` / `shutdown` 挂接 `quota_cost_monitor`，`/health/deep` 暴露 `quota_cost_monitor` 探针。
    - 守门：`test_quota_cost_monitor.py`（13 用例，覆盖 token 累计/降级/预算 warning·critical·阈值下不告警/预算禁用/Finnhub 配额耗尽/去重/生命周期/端到端推送）全绿；`.env.example` 补 `LLM_DAILY_TOKEN_BUDGET` / `LLM_TOKEN_METRICS_ENABLED` 说明。
- [x] **[SVC-06]** 三方服务 Mock/Stub：本地开发与 CI 全程可离线运行，不依赖真实 API Key，保证测试确定性与可重复
  - **交付（2026-08-09）**：
    - 新建 `backend/services/ai_narrator/llm_stub.py` 的 `LLMStubProvider`：构造与 OpenAI 响应结构兼容的确定性假响应（含 `usage.prompt/completion/total_tokens`），支持文本模式（`make_text_response`）与 JSON 模式（`make_json_response` 返回 pydantic 最小合法实例 JSON，确保 `generate_pydantic` 校验通过）；`is_offline_llm_enabled()` 在 `QUANT_ENV∈{offline,testing,dev}` 或 `LLM_STUB=1` 时启用。
    - `llm_service.py` 接入：`LLMService._is_offline()` + `_offline_override`（测试可注入）；`generate` / `generate_pydantic` 离线分支短路到 stub（保留 `await self._record_token_usage(...)` 验证 SVC-05 计量链路）；`_record_token_usage` 改为 `async` 并直接 `await store.record(...)`（异常安全，消除 fire-and-forget 调度不确定性）。
    - 新建 `backend/services/datasource/offline_stub.py`：统一确定性 stub 数据（yfinance/akshare/tushare/futu/fmp/finnhub/fred/dbnomics/rbi/search 等），`build_offline_response(source, action, **params)` 返回 `{"success":True,"offline_stub":True,...}`；`is_offline_mode_enabled()` 在 `OFFLINE_MODE=1` 或 `QUANT_ENV=offline` 时启用（**刻意不把 testing/dev 纳入**，避免破坏既有 router 集成测试，它们依赖 conftest 的远程节点 mock 走真实路径）。
    - `data_source_router.py` 接入：`_maybe_offline(source, action, **params)` 统一拦截，在 10 个 `fetch_*` 方法入口注入短路（OFFLINE_MODE=1 时连子服务节点都不触网）。
    - `conftest.py` 注册 `live_network` pytest 标记（需真实网络/Key 的集成测试默认 skip）。
    - 守门：`test_offline_stubs.py`（16 用例，覆盖离线开关判定/LLM 文本·JSON·token 计量联动/router 全源短路/live_network 标记）全绿；既有 `test_data_source_router.py` 未引入新失败（6 个 akshare 失败为预先存在，依赖已移除的本地降级通道，与本次无关）。
- [x] **[SVC-07]** 降级与混沌测试：模拟 Futu 断连 / YFinance 超时 / OpenAI 限流，验证熔断器（BE-04）、数据源自动切换、Ollama 降级（对照 `docs/12` 应急预案）真实生效
  - **交付（2026-08-09）**：
    - 守门：`test_chaos_degradation.py`（12 用例），**真实驱动状态机**（只在最底层注入故障，不 mock 被测逻辑本身）：
      - **A. 熔断器 CircuitBreaker (BE-04)**：`test_circuit_breaker_open_after_max_failures`（连续失败 → OPEN → 抛 `CircuitBreakerOpenError`）、`test_circuit_breaker_half_open_then_closed`（超时 → HALF_OPEN → 成功 → CLOSED）、`test_circuit_breaker_rate_limit_skips_failure`（限流错误不计入熔断计数）、`test_circuit_breaker_prometheus_state_transition`（熔断状态变化反映到 Prometheus `CIRCUIT_BREAKER_STATE` 指标）。
      - **B. LLM Ollama 降级 (AI-02)**：`test_llm_fallback_to_ollama_on_repeated_failure`（主供应商连续失败达阈值 → `is_fallback_active=True` 且 `get_client` 返回 Ollama client；主供应商恢复 → 切回）、`test_llm_fallback_threshold_not_reached`、`test_llm_fallback_disabled`。
      - **C. DataSourceRouter 节点熔断 + failover**：`test_router_failover_on_node_failure`（主节点连续失败 → unhealthy + `circuit_breaker_until` 设置 → `_select_node` 自动选备节点）、`test_router_rate_limit_does_not_trip_breaker`（限流类错误只 failover 不熔断）、`test_router_no_local_fallback_on_total_outage`（全节点失联 → 返回失败且**无本地兜底**，符合移除本地 SDK 降级通道架构红线）。
      - **D. 端到端降级编排**：`test_futu_total_outage_no_local_fallback`（Futu 全失联 → 返回错误且无本地兜底）。
      - **E. 隔离性**：`test_parallel_circuit_breaker_isolation`（独立服务熔断状态互不干扰）。
    - 全绿。验证重点：日志实测触发「节点 yf_a 触发熔断」「无健康子服务节点可用（后端已移除本地兜底）」「Futu 远程节点不可用（后端已移除本地兜底）」，证明降级/熔断/切换链路真实生效，而非 mock 假结果。

