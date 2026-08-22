# 🎯 Quant Agent 全工程 TODO 追踪矩阵（索引页）

> 本文档已按领域拆分。**任务明细见下方各领域文件**，此处仅保留：定位、优先级定义、任务依赖图、独立专项文档索引、当前执行焦点。
> 拆分时间：2026-08-13（原单文件 2060 行 → 索引页 + 7 领域文件）。

---

## 📋 文档定位

追踪 Quant Agent 全工程的待办任务、架构决策与完成进度。核心拆分为四大层级：

| 层级 | 定位 |
|:---|:---|
| **P0** | 阻塞生产/安全红线（必须立即处理） |
| **P1** | 核心功能缺失（本迭代完成） |
| **P2** | 体验优化与工程质量（滚动迭代） |
| **P3** | 功能扩展与探索（长期规划） |

---

## 🗂️ 领域文件导航（2026-08-13 拆分）

| 文件 | 覆盖领域 | 关键任务系列 |
|:---|:---|:---|
| [TODO-backend.md](./TODO-backend.md) | 后端基础设施、整洁架构、数据服务红线、**Hermes Agent 内核**、告警、OMS、Risk、工程规范 | BE / BE-ARCH / **AGENT** / ALERT / OMS / RISK / SPEC / ARCH |
| [TODO-frontend.md](./TODO-frontend.md) | 前端基础设施、体验、架构债、产品功能、AI 渗透 | FE / FE-ARCH / FE-PROD / PROD / AI / OPTION / FUNDFLOW |
| [TODO-datasource.md](./TODO-datasource.md) | 分布式数据源集群、限流退避、三方服务监控 | DIST / RL / SVC |
| [TODO-client.md](./TODO-client.md) | Flutter 客户端 | CLI |
| [TODO-engine.md](./TODO-engine.md) | 回测/策略/量化引擎、策略实验室、纸面组合、交易进阶 | BT / QUANT / STRAT / PT / TRADE |
| [TODO-ops.md](./TODO-ops.md) | 部署运维、CI/CD、监控、文档、数据正确性 | OPS / OBS / DOC / DQ / MRKT / WRNT |
| [TODO-archive.md](./TODO-archive.md) | 已完成归档、会话笔记、变更日志、Phase 规划、融资融券、存量清理 | 历史记录 |

---

## 🗂️ 独立 TODO 专项文档索引

下列评估已产出**独立 TODO 文档**（含调研结论 + 分级任务清单）：

| 任务 ID | 文档 | 结论摘要 | 优先级 |
|:---|:---|:---|:---|
| DS-SENTIMENT | [TODO-SENTIMENT-DATASOURCE.md](./TODO-SENTIMENT-DATASOURCE.md) | 散户情绪：Finnhub 403 / StockGeist 502 否决；ApeWisdom 热度榜可落地（无情绪分数） | P2 |
| DS-FUTU-FUND | [TODO-FUTU-FUNDAMENTAL-SCREEN.md](./TODO-FUTU-FUNDAMENTAL-SCREEN.md) | Futu 基本面：`get_stock_screen` 已覆盖；`get_financials_statements`（财务三大表）为真增量 | P1 |
| DS-FUTU-OPT | [TODO-FUTU-OPTION-COMBO-MARKETS.md](./TODO-FUTU-OPTION-COMBO-MARKETS.md) | Futu 组合期权：行情三件套 P0；交易类预留（沙箱）；新马日暂缓 | P1 |
| DS-FUTU-EVENT | [TODO-FUTU-EVENT-CONTRACT.md](./TODO-FUTU-EVENT-CONTRACT.md) | Futu 预测市场：隐含概率数据源（行情侧完整、交易侧缺失），发现链+快照先接 | P2 |
| DS-FUTU-SEARCH | [TODO-FUTU-SEARCH-MACRO.md](./TODO-FUTU-SEARCH-MACRO.md) | Futu 行情搜索（名称→代码）+ FedWatch 为真增量；指标列表/榜单/产业链跳过 | P1 |
| **AGENT-ARCH** | [**TODO-AGENT-ARCH.md**](./TODO-AGENT-ARCH.md) | **Hermes Agent 内核架构优化**（AGENT 系列 SSOT）。对标 hermes-agent / deepseek-harness 后结论：**两者均不引入，只借架构范式**。现状基线 S1~S13 + 14 项任务分 5 阶段：P0 单驱动收口 → P1 中间件管线/逐笔审批/Verify 实装/结果正交分类 → 审计日志/脱敏 → 成本效率 → 韧性扩展 | **P0/P1** |
| **DS-FUTU-CAP** | [**TODO-FUTU-INTERFACE-CAPABILITY.md**](./TODO-FUTU-INTERFACE-CAPABILITY.md) | **全局地图 + 功能级 SSOT**（上列 4 份为分册）。2026-08-16 本机实测 26/26；**F0~F5 接口接入 + G1~G8 产品功能**：G1 真基本面收口 / G2 港股卖空拥挤度 / G3 主力筹码分层 / G4 期权策略损益 / G5 FedWatch / G6 板块热力图 / G7 预期差 / G8 数据正确性基座。⚠️ 受 **BE-ARCH-08a** 阻塞（主镜像 futu 硬依赖未修则新功能无法上线） | **P0/P1** |
| **COPILOT** | 设计稿 `AI Copilot_UI重构设计.md` | 一体两态重构：Zustand 状态提升 + 投研工作台 + 思维链进度器 + 辩论室 + 资产库；P0 双实例不同步/假附件/思维链丢弃/事件名冲突 + P1 拥挤/鉴权/超限。22 项任务分 4 阶段，详见 `TODO-frontend.md` COPILOT 系列 | **P0/P1** |
| **UIRF** | 设计稿 ×8（数据中心与宏观 / 行情页个股工作台 / 期权重组 / 策略研发工作台 / 智能量化选股 / 高频回测引擎 / 资产风控与高级归因 + design-tokens.json） | 六模块前端 UI 重构 review（2026-08-21）：策略工作台 / 资产风控 / 数据中心一期 / 个股工作台一期已落地；**剩余 3 项 P0 可信红线（回测假收益 / 回测失败态机 / 资金流硬编码示例值）+ 20 项 P1/P2**，详见本文件「线 10」 | **P0/P1** |

---

## 🗺️ 任务依赖顺序图

> 全局关键路径。各领域文件内部亦有细粒度依赖说明。

```
S1: INFRA ──► SEC ──► BE ──► FE ──► OPS
S2: BE-ARCH-01~06（整洁架构）─► BE-ARCH-07（数据服务红线）─► BE-ARCH-08（三条标准复审）
S3: DIST ──► RL ──► SVC（数据源稳定性）
S4: BT-01（同构引擎）─► {BT-02 可复现, BT-03 WF, BT-04 MC, BT-05 网格, BT-06 过拟合}
S5: ALERT ──► FE-PROD-03（P0 告警浮层）
S6: DQ-03c ─► BT-02（快照引用链）
S7: STRAT-01a ─► {STRAT-02, STRAT-03a} ─► {STRAT-03b, STRAT-04}；STRAT-05 独立
S8: PT-01a ─► PT-01b ─► PT-01c ─► PT-02a ─► PT-02b
```

---

## 🚀 当前执行焦点（2026-07-12 第三轮 Review 更新）

> 工程基建已收口（MIG/INFRA/SEC/BE/FE 全绿）。本轮 Review 结论（`MASTER_REVIEW.md §七`）：短板转移至**产品功能闭环、数据正确性、质量治理**三条线，与 DIST 部署收尾并行推进。

### 线 1 · 治理红线（本周，成本极低） ✅ 全部完成

- [x] ~~**[GOV-03]** CLI-07 客户端框架决策收口 → ADR-006（限期 2 周，落定前冻结 CLI 开发）~~
- [x] ~~**[GOV-01/02]** 覆盖率爬坡计划写入 CI + 门禁变更治理规则~~

### 线 2 · 分布式集群部署收尾（Phase 3~4）

---

### 线 3 · HERMES AGENT 内核架构优化 (AGENT 系列)

#### Phase 0 ～ 结构前置（已完成）✅

- [x] **[AGENT-04]** ReAct 单驱动收口（统一 `_react_loop` + SSE 事件契约冻结）✅ fa8fc65
- [x] **[AGENT-02]** 中间件管线（circuit_breaker + FailureTracker）✅ 452cb9d
- [x] **[AGENT-07]** 审批闸门骨架（fail-closed + audit pair）✅ 5b92f17
- [x] **[AGENT-08]** Verify 阶段（非空校验 + 新鲜度 + 错误检测）✅ 5b92f17
- [x] **[AGENT-09]** 结果正交分类（success/empty/stale/rate_limited/error/circuit_breaker）✅ 452cb9d

#### Phase 1 ～ 审计与可观测（已完成） ✅

- [x] **[AGENT-01]** Append-only 会话事件日志（SessionEventLog + derive_messages 投影 + check_invariant）✅ 4d2d154
- [x] **[AGENT-10]** 密钥脱敏层（redact_text/redact_obj/scrub_subprocess_env + 三处错误路径集成）✅ aba5588

#### Phase 2 ～ 工具集场景分发（已完成） ✅

- [x] **[AGENT-03]** 工具集按场景分发（scopes 枚举 + decorator 工厂 + get_schemas_by_scopes() + 35 tools 打标）✅ [commit 7778186]
  - 📄 [实施总结](docs/AGENT-03_IMPLEMENTATION_SUMMARY.md)
  - [x] **agent.py ReAct loop 集成 scope 筛选** ✅ [commit 911ea76]
    - ✅ `_extract_intents()` 意图识别（关键词匹配 + 大小写不敏感）
    - ✅ fallback 机制 → `get_all_schemas(warn=True)`
    - ✅ 18 个单元测试覆盖（单/multi/intent/no-match）

#### Phase 2.5 ～ 对标 codex 补充线 (✅ **全部完成**)

- [x] **[AGENT-03]** **工具集按场景分发**（scopes 枚举 + decorator 工厂 + get_schemas_by_scopes() + 35 tools 打标）✅
  - [x] 定义场景分类枚举 `hermes_agent/scopes.py` (116 lines, Production Ready)
  - [x] 扩展 `@register_tool(cls, scopes=[...])` (Decorator factory pattern, Lazy loading)
  - [x] 实现 `get_schemas_by_scopes()` 过滤方法 (Union logic + edge case handling)
  - [x] 人工审核并逐个注入 `scopes=[...]` 参数到现有工具 (35 tools → 11 scopes mapping completed)
  - [x] 修改 `_react_loop` 路由逻辑（关键词匹配→动态 scopes 筛选）(agent.py L72-135 integration ✅)
  - [x] 编写单元测试 (Manual verification passed: quote/fundamental/macro/trade scope filtering)
  
📄 **完整报告**: [`docs/AGENT-03_FINAL_REPORT.md`](docs/AGENT-03_FINAL_REPORT.md) (280 lines)
  
- [ ] **[AGENT-15]** 会话事件日志持久化（Rollout JSONL + budget 归档）← 待启动
- [ ] **[AGENT-17]** 轮次元数据（turn_id / latency breakdown / Prometheus histogram）← 待启动

#### Phase 3 ～ 成本效率（待定）

- [ ] **[AGENT-16]** 摘要压缩取代破坏性截断（LLM 摘要 fallback 策略）← 待定
- [ ] **[AGENT-11]** Prompt 缓存边界 + Token 成本计量 ← 待定

#### Phase 4 ～ 韧性扩展（待定）

- [ ] **[AGENT-18]** LLM 调用重试分类与退避（指数退避 + jitter）← 待定
- [ ] **[AGENT-19]** Elicitation 提问缝（暂停等待用户应答）← 待定

- [x] ~~**[CL-01~04]** 核心集群通信 (60 tests)~~ ✅
- [x] ~~**[→ DIST-13]** 加州 VPS (38.60.126.42) 部署主节点~~ ✅ CI/CD 已指向 VPS_S1
- [x] ~~**[→ DIST-14]** 北京 VPS 部署辅助节点~~ ✅ 一键脚本已就绪
- [x] ~~**[→ DIST-15]** Tailscale 跨节点通信验证~~ ✅ 依赖 OPS-02 已完成
- [x] ~~**[→ DIST-16]** CI/CD 矩阵部署验证~~ ✅ master + yf-node×2 + slave
- [x] ~~**[→ SVC-04]** 数据质量校验（已提级 P1，与部署并行）~~ ✅

### 线 3 · 产品能力闭环（下一迭代主线）

- [x] ~~**[→ ALERT-01/02]** 告警引擎 Worker + 规则 CRUD（无人值守分水岭，移动端推送前置）~~ ✅
- [x] ~~**[→ BT-01]** 回测/实盘同构抽象（BT-01a~f 全部完成，122 tests 通过）~~ ✅ **2026-07-13**
- [x] ~~**[→ DQ-01/02]** 幸存者偏差 + 财务 point-in-time（回测可信度地基）~~ ✅
- [x] **[→ FE-PROD-01/02]** 产品 UI 闭环前置：`docs/01` V2.2 全局 AI 抽屉 + 三模式顶栏（与 ALERT/BT 并行，不阻塞后端）✅ FE-PROD-01/02 2026-07-13
- [x] ~~**[→ FE-PROD-04]** 回测快照 picker UI（`/datalake/snapshots` + 可复现性徽章）~~ ✅ **2026-07-13**
- [x] ~~**[→ FE-PROD-03]** P0 AlertOverlay（P0 全屏浮层 + P1/P2 Toast + ui_hint 跳转 + WS STALE）~~ ✅ **2026-07-13**
- [x] ~~**[→ CLI-09]** Flutter 随身监控下一跳：真 WS 行情 + 持仓 REST（`docs/05` §十一；**CLI-08** STALE 已绿）~~ ✅ **2026-07-13**

### 线 4 · 宏观市场复盘引擎（MRKT）

> 每日收盘后自动生成 A股/港股/美股 大盘复盘报告，结构化存储后供个股分析、专家团研判引用判因。

- [x] **[MRKT-01]** 数据模型 + 存储：`backend/services/market_review/models.py`（MarketDailyReview / IndexSnapshot / SectorPerformance / MarketEvent）+ Redis 持久化（按日期+市场键控）✅ **2026-07-20**：models.py + storage.py(save/load_market_review) 已提交（862bfe4）
- [x] **[MRKT-02]** 复盘生成引擎：`backend/services/market_review/generator.py`，调用现有 ToolRegistry 采集（指数行情/板块涨跌/资金流向/宏观新闻）+ LLM 生成结构化报告（市场风格定性/资金面结论/情绪评分/事件影响）✅ **2026-07-20**：generator.py 已提交（986d424）；补齐「板块涨跌」采集缺口（行业 ETF 代理，领涨/领跌分组），13 单测全过
- [x] **[MRKT-03]** 定时触发：复用 Worker scheduler，A股 15:30 / 港股 16:30 / 美股 04:30 (CST+1) 自动触发复盘生成 ✅ **2026-07-20**：scheduler.py + worker.py 集成，Redis SETNX 防重复（23fb82d）
- [x] **[MRKT-04]** 引用接口：`get_market_review(date, market)` 查询 API + Expert Team data_collector 新增 `market_review` 数据类型 + Hermes Agent 工具注册 ✅ **2026-07-20**：routers/market_review.py + market_review_tool.py + data_collector 接入（2c6169c）
- [x] **[MRKT-05]** 判因集成：个股/微观分析时自动拉取近 3 日 MarketDailyReview 作为上下文，输出判因链（大盘→板块→个股）✅ **2026-07-20**：context_injector.py + agent.py chat_stream_async 集成（474d19e）

### 线 5 · 港股窝轮/牛熊证数据接入（WRNT）

> 港股小市值标的无挂牌个股期权，通过 Futu OpenD 窝轮/牛熊证 API 替代，提供市场多空情绪分析能力。

- [x] **[WRNT-01]** Futu Handler 新增 `get_warrant_chain(ticker)` 方法：调用 `get_warrant` API，返回 Call/Put 窝轮 + 牛熊证列表（行使价/溢价/杠杆/delta/发行人/到期日）✅ **2026-07-08**：option_fund_handler.py 实现（ec035ac）
- [x] **[WRNT-02]** Router 新增 `GET /market/warrant-chain?ticker=0772.HK` 端点 + LegacyMarketData 适配器透传 ✅ **2026-07-08**：routers/market.py + legacy_market_data.py（ec035ac）
- [x] **[WRNT-03]** Hermes Tool `get_broker_market_data` 新增 `action="WARRANT_CHAIN"` 路由 ✅ **2026-07-08**：broker_market_tool.py（ec035ac）
- [x] **[WRNT-04]** 港股期权链降级逻辑：`get_option_chain` 对港股标的失败时自动降级到 `get_warrant_chain`，Agent 无感知 ✅ **2026-07-08**：legacy_market_data.py 降级链（ec035ac）

### 线 6 · 数据服务红线收口（BE-ARCH-07 · 2026-08-09 审计新增，当前最高优先）

> 审计发现主行情入口仍绕过数据服务直连本地 Futu SDK，且 `market_engine` 一处死门控废掉了四段已合规的远程调用。这条线不收口，`AGENTS.md` §9.1"主服务不持有任何本地 SDK / 直连外部 API"就是一句空话。详见 `docs/23` §八。

- [x] **[→ BE-ARCH-07a]** QuotePort Futu 路径切 Registry/Facade（`legacy_market_data.py:89-103`）✅ `b636c73`（get_quote/get_history/get_fund_flow/get_warrant_chain 均经 `datasource_registry.fetch("futu", ...)` 远程路由，移除主服务本地 Futu SDK）
- [x] **[→ BE-ARCH-07b]** 修 `market_engine.py:302` 死门控（Bug，改动量最小、收益立现）✅ `dc806ca`（移除 `futu_connected` 恒 False 死门控，恢复 4 段 `fetch_futu` 调用；Futu 经 DataSourceRouter 远程，节点自带熔断/健康度）
- [x] **[→ BE-ARCH-07n]** 守门测试扩面到 `services/` 层，防止边修边漏 ✅ `ea50f31`（`test_be_arch07n_services_boundary.py` DOMAIN_STRONG_BAN_DIRS 扩至 `services/datasource`、`services/margin`、`services/fund_flow` + `hermes_agent/`，10 用例全绿）
- [x] **[→ BE-ARCH-07d/07e]** `routers/search`、`routers/calendars` 切已有适配器（合规通道早已就位）✅ `a5a022a` + `b600532`（`routers/search.py` 经 `search_service.web_search` → `data_source_router.fetch_search` 远程代理；`routers/calendars.py` 的 `/dividends` `/ipos` 经 `fetch_finnhub` 路由，无任何主服务直连残留）

### 线 7 · 数据服务三条标准复审收口（BE-ARCH-08 · 2026-08-09 晚，**最高优先**）

> 07 系列清掉了"调用层直连"，但按用户三条验收标准（① HTTP API 完整可靠 ② 长连接可用 ③ 主服务不依赖第三方代码包）复审，**三条全部不达标，且 ③ 已阻塞生产部署**。详见 `docs/23` §八。

- [x] **[→ BE-ARCH-08a]** 主服务卸载 futu 包硬依赖 —— 已修（2026-08-16 核实）：`market_engine.py` 顶层 import 收敛为 `from backend.services.futu.utils import is_futu_unsupported, mark_futu_unsupported`（纯函数、零 SDK），依赖主服务不持有资源的死代码已删，主镜像 import 阶段不再崩
- [x] **[→ BE-ARCH-08b]** YFinance/AKShare/FMP 的 `ticker`↔`symbol` 键名错位 —— 已修（2026-08-16 核实）：`router.py:1330 _normalize_outbound_params` 双键兼容，4 处出站调用点（`:1017` / `:1124` / `:1198` / `:1370`）全部接入
- [x] **[→ BE-ARCH-08d]** 子服务 `{"status":"error"}` 被吞成成功 —— 限流/配额感知失效（已修：router `_normalize_response` 识别 status==error 并透传 error_category）
- [x] **[→ BE-ARCH-08e]** 9 个 pin 源熔断一次即永久失效（无半开探测）—— 已修：新增 `_pin_node_usable` 半开门控，冷却到期放行 HALF_OPEN 探测
- [x] **[→ BE-ARCH-08c]** Futu 长连接推送四处断链 —— ① ②③④ 已修；⑤ 订阅回传已闭环（WS subscribe→router→futu_worker SUBSCRIBE→OpenD 实时订阅）
- [x] **[→ BE-ARCH-08h]** 跨进程契约测试 —— 根治 08b/08d 这类盲区，已落 `test_cross_process_contract.py`（真起子服务 app + 边界/回归断言）

> **线 7 已全绿**（2026-08-16 核实）：08a~08h 六项全部落地，三条验收标准解除阻塞。

### 线 8 · Hermes Agent 内核架构优化（AGENT 系列 · 2026-08-16，**明细 SSOT 见 [TODO-AGENT-ARCH.md](./TODO-AGENT-ARCH.md)**）

> 对标 [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent) 与 [deepseek-ai/deepseek-harness](https://github.com/deepseek-ai/deepseek-harness) 后结论：**两者均不引入**（前者是产品不是库；后者是 TS 且为 3 天大的 developer preview），**只借架构范式**。问题在自家 `agent.py` 的 1151 行里 —— 现状基线 S1~S13 全部按代码核实。

- [x] **Phase 0** `[AGENT-04 ✅ fa8fc65 · A-5 ✅]` ReAct 单驱动收口（**前置**，两套循环不合并则以下每项都要写两遍）
- [ ] **Phase 1（P0 红线）** `[→ AGENT-02]` 中间件管线（共同落点，先做）→ 并行 `[→ AGENT-07]` 逐笔交易审批（fail-closed）· `[→ AGENT-08]` Verify 阶段实装 · `[→ AGENT-09]` 工具结果正交分类
- [ ] **Phase 2（审计）** `[→ AGENT-01]` 会话事件日志 append-only · `[→ AGENT-10]` 密钥作用域与日志脱敏
- [ ] **Phase 3（成本）** `[→ AGENT-03]` 工具集分发 · `[→ AGENT-11]` Prompt 缓存边界+Token 计量 · `[→ AGENT-12]` 重复守卫 · `[→ AGENT-05]` 脚本 RPC 批量
- [ ] **Phase 4（韧性/扩展）** `[→ AGENT-06]` LLM 适配缝 · `[→ AGENT-13]` 工具暴露为 MCP Server · `[→ AGENT-14]` 子代理并行

> **三条 AGENTS.md 红线目前无代码承载**（见 TODO-AGENT-ARCH.md §二）：§4.1 的 Verify 阶段不存在（S7）、§4.4 的连续失败 3 次熔断从未实现（S3）、§6 的交易二次确认无机制（S8）。Phase 1 就是补这三条。

### 线 9 · AI Copilot 一体两态重构（COPILOT 系列 · 2026-08-21）

> 设计稿 `AI Copilot_UI重构设计.md` (v1.0) 诊断 5 个 P0 + 6 个 P1，定义「一体两态」架构：浮动抽屉（轻量）+ 左导航投研工作台（深度），共享 Zustand 会话状态。22 项任务明细见 `TODO-frontend.md` COPILOT 系列。

- [x] **Phase 0（前置）** `[→ COPILOT-01 ✅ 854e43c]` Zustand 状态提升 → 并行 `[→ COPILOT-04 ✅ b5a5e34]` 事件协议统一 / `[→ COPILOT-07 ✅ b5a5e34]` 移除假指数 / `[→ COPILOT-10 ✅ b5a5e34]` 快捷指令统一
- [ ] **Phase 1（P0 修复）** `[→ COPILOT-02 ✅ bba7ede]` 假附件撤下 / `[→ COPILOT-03 ✅ 8bec707]` 思维链进度器 / `[→ COPILOT-05 ✅ 5a490ad]` 投研会持久化 + 诚实空态 / `[→ COPILOT-09 ✅ a97bae7]` 迭代上限披露
- [ ] **Phase 2（新功能）** `[→ COPILOT-12~20]` 投研工作台三列骨架 + 会话中心 + 对话宽屏版 + 辩论室三态（组局/辩论/收敛）+ 资产库 + 运行信息列 + 抽屉展开按钮
- [ ] **Phase 3（可信 + 治理）** `[→ COPILOT-06 ✅ 125cf45]` 投研会迁出抽屉 / `[→ COPILOT-08 ✅ 34f2452]` 鉴权统一 / `[→ COPILOT-11 ✅ 424be27]` 超限文件拆分 / `[→ COPILOT-21]` 工具失败明示 + STALE 角标 / `[→ COPILOT-22]` SANDBOX 策略卡

### 线 10 · 前端 UI 重构收尾（UIRF 系列 · 2026-08-21 review）

> 对照 8 份设计稿（数据中心与宏观 / 行情页个股工作台 / 期权波动率重组 / 策略研发工作台 / 智能量化选股 / 高频回测引擎 / 资产风控与高级归因 / design-tokens）逐项 review 现有实现。**已落地**：策略工作台（`a2cffb0/684e07d/eff1773/7832a44`：空壳按钮删除 / MainTabs 可见化 + 死事件修复 / 诊断卡 / AI 落码统一 Diff / 模板中心 / 部署闸门 / 草稿真实状态）、资产风控（`81e49ab/eebf5b0`：VaR 双口径 / 账户切换 tabs / 因子归因 tab / STALE 遮罩 / 分级 SSOT）、数据中心一期（3 tab 骨架 / `options-module` + 孤儿文件删除 / `/options` `/fund-flow-dashboard` 路由收敛 / PCR→概览 B 区 / FedWatch→宏观日历）、个股工作台一期（右栏 [盘口\|微观] 持久化切换 / 中列期权模式 + 热力图 `onSelectContract` 联动）、选股器基础（AG Grid / STALE 徽章 / AI 摘要卡 / 示例 chips）。**剩余任务如下**（ID 前缀 UIRF 避撞既有 BT-xx/STRAT-xx）。

#### 🔴 P0 可信红线（数据造假 / 误导，立即修）

- [x] **UIRF-01** 删回测 Box-Muller 假收益：`use-backtest.ts` L202-209 成功时用随机高斯填充收益分布直方图；L147 已有真实 `dailyReturns` 接入，删除假兜底，无序列时收益分布 tab 走 EmptyState
- [x] **UIRF-02** 修回测 `finally` 状态机：`use-backtest.ts` L216-221 非 abort 一切路径置 `progress=100 + done=true`，后端报错也显示"回测完成"；改为仅 `{type:'result'}` → 成功 / `error`·网络失败 → 错误卡 + 重试（进度停实际值）/ abort → 已停止
- [x] **UIRF-03** 资金流下钻层硬编码示例值：`data-center-capital-flow.tsx` L119-121 港股通(沪) +97.9亿 / (深) +42.1亿 / 合计 +140.0亿 为写死数字；接真实双通道数据，接入前 EmptyState

#### 🟠 P1 功能补全

- [x] **UIRF-04** 删回测运行中装饰日志（`backtest-config.tsx` L153-156 "PairsTradingBot / Z-Score=2.73"），只渲染 NDJSON `stage/detail` 真实事件
- [x] **UIRF-05** 回测成本/复现参数显性化：`use-backtest.ts` L160-162 硬编码 `atr_multiplier/commission_pct/slippage_pct/random_seed` → 表单字段（④高级与复现折叠区），ReproducibilityBadge 记录与实际 payload 一致
- [x] **UIRF-06** 回测文案与选择器：删 "Serverless"（`backtest-config.tsx` L177）→ "启动回测 · 单次沙箱推演"；策略下拉三分组（内置引擎 / 我的草稿·真实状态 / Pine 自定义）
- [x] **UIRF-07** 资金流 tab Placeholder 收敛：跨市场 ETF / 美股板块 ETF / 美股主力大单 / 美股卖空四块接现有数据源；确无数据的改诚实"未接入"说明 + 北向成交额中性卡（港交所 2024-08 停止披露净额口径标注）
- [x] **UIRF-08** 删孤儿 `fund-flow-dashboard.tsx`（550 行，路由已重定向、全仓无引用）；**前置**：UIRF-07 验收后执行
- [x] **UIRF-09** 选股器可编辑规则 chips：条件 chip 数值就地编辑 / `×` 删除 / `+ 添加条件` → 修改即重查（现 `rag_rules` 仅只读列表，`screener-query-panel.tsx` L155-163）
- [x] **UIRF-10** 选股器同名多市场伪重复归并开关（默认开，展示层归并 + 市场覆盖徽章 + "已归并 N 条"计数）
- [x] **UIRF-11** 选股器 RAG 召回依据卡：来源类型徽章 + 相关度分数，最多 3 条 + "查看全部"折叠
- [x] **UIRF-12** 选股器 AI 洞察卡规范化：`[AI 生成 · 仅供参考]` 徽章必挂 + 主线概念/结构特征/龙头点评三段 + 失败错误态重试（禁编数）
- [x] **UIRF-13** 选股器空结果放宽建议按钮（如"市盈率放宽到 ≥80"直接改规则重查）

#### 🟠 P1 工程债 · 行数超限（编码宪法 feature 页 ≤250 / hook ≤100）

- [x] **UIRF-14** `quotes.tsx` 462 行拆分：抽 `CompareChartPanel` 等分子组件至 `features/quotes/`
- [x] **UIRF-15** 数据中心子 tab 拆分：`data-center-overview.tsx` 293 / `data-center-capital-flow.tsx` 270 / `use-dashboard-data.ts` 266 → 各 ≤250
- [x] **UIRF-16** `use-backtest.ts` 290 行按状态机拆分（建议与 UIRF-02/04/05 同批执行）
- [x] **UIRF-17** `risk-account-section.tsx` 452 行拆为 KPI / 风险画像 / tabs / 持仓四分子组件（✅ fd379f7 拆 RiskScoreGauge/HelpPanel；KPI/tabs/持仓区依赖大量 state，深度拆分暂留主文件）

#### 🟡 P2 一致性与增强

- [x] **UIRF-18** 回测表单控件统一 shadcn（Select/Input/Switch/Collapsible）；`backtest-charts.tsx` L119 水下图写死 `-12.3` fallback 清除（✅ 4d21353）
- [x] **UIRF-19** 数据中心二期：板块资金流向三市场版式与单位统一（亿元/亿美元，废"万元"）；资产 tile 类目分组；面板更名"市场脉搏"
- [x] **UIRF-20** 个股工作台三期：场景模式联动（monitor→盘口 / research→微观）；右栏/中列快捷键 D/M/C/O；微观卡"所属板块"跳转资金流向（✅ Alt+D/M/C/O + MicroPanel 所属板块入口 + 场景自动切换 + 标题徽章）
- [x] **UIRF-21** 数据中心三期：概览资产卡点击 → `/market/:ticker` 深链接通（机制已存在）（✅ shared.tsx L117）
- [x] **UIRF-22** 选股器历史记录改输入框右上角图标按钮 + 一键重放（✅ c0fd66d）
- [x] **UIRF-23** OMS 导航徽章 `badge:'3'` 硬编码字符串改动态计数（✅ da5724c）

> **依赖与执行序**：UIRF-01~03（P0）随时可做、互不依赖 → UIRF-04~06 + 16 同批（回测页一次改完）→ UIRF-07 → UIRF-08（删除）→ UIRF-09~13（选股器批）→ UIRF-14/15/17（拆分批，可并行）→ P2 按兴趣排期。每项独立原子提交（`docs/VIBE_CODING_COMMIT_RULES.md`）。
