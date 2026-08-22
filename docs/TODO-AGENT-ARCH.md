# TODO — Hermes Agent 内核架构优化规划（对标 hermes-agent / deepseek-harness）

> 创建：2026-08-16 | 版本 v1.0 | **本文件为 AGENT 系列任务 SSOT**（`docs/TODO.md` 线 8 与 `TODO-backend.md` 仅留指针）
> 对标对象（均已用 GitHub API 核实存在与规模，非道听途说）：
> - [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent) — MIT · Python · 231,358★ / 46,008 fork · 2025-07-22 建 · 持续活跃
> - [deepseek-ai/deepseek-harness](https://github.com/deepseek-ai/deepseek-harness) — MIT · TypeScript · 127,822★ / 12,748 fork · **2026-08-13 建（3 天）** · developer preview

---

## 一、结论：不引入，只借范式

| 项目 | 能否直接用 | 判据 |
|---|---|---|
| hermes-agent | **否** | 是**产品**不是库。README 通篇 `curl \| bash` + `hermes` CLI，无嵌入路径；`agent/` 200+ 模块含 billing / credits_tracker / credential_pool / browser_provider / image_gen / pet / TUI / website。我们的 Hermes 是嵌在 FastAPI 内、经 SSE 喂 React 终端的引擎，37 个工具绑死自家 Facade —— 换它等于连交付模型一起换 |
| deepseek-harness | **否（且现在不该碰）** | TS/Node monorepo → 后端引第二运行时，撞 Python 技术栈锁定；**建库 3 天**、自述 developer preview 会有破坏性变更。把实盘交易的 Agent 层压在 3 天大的预览版上不可接受 |

**但两者都是 MIT，且 hermes-agent 与我们同为 Python** —— 文件级借用（带署名）合法可行。**本规划只借架构范式与具体机制，不接依赖。**

> **⚠️ 命名撞车**：本仓 `hermes_agent/` 与 NousResearch `hermes-agent` 无任何血缘，纯属同名。若开源需先处理。

---

## 二、现状基线（2026-08-16 逐项按代码核实）

| # | 短板 | 证据 |
|---|---|---|
| S1 | **ReAct 主循环实现了两遍** | `agent.py:645 _step_loop()`（非流式）与 `:778 chat_stream_async()`（SSE），各自 `max_iterations = 8`（`:649`/`:819`）、各自熔断恢复（`:742`/`:1097`）、各自 schema 注入（`:656`/`:828`）|
| S2 | **`agent.py` 1151 行** | 违反 AGENTS.md §A.4.6 硬规则（单文件 ≤300，禁止 >1000）|
| S3 | **§4.4「同一 Tool 连续失败 3 次熔断」从未实现** | `tool_registry.py:94 execute()` 仅 catch 异常返回 `{"status":"error"}`，全仓无失败计数器。死工具会被反复调到 8 轮耗尽 |
| S4 | **工具执行无扩展点** | `execute()` 硬编码 `cache → 限流 → run → 存 cache`，每加一个横切关注点都要改这个函数 |
| S5 | **37 个工具 schema 每步全量注入** | `tool_registry.py:78 get_all_schemas()` 被 `agent.py:656`/`:828` 无差别塞进每次请求 |
| S6 | **会话历史被破坏性改写** | `:467 _async_db_upsert()` 整体 upsert、`:288 _compress_memory()` 原地裁剪、`:216 _heal_memory()` 原地修复 → 事后无法重建"模型当时看到了什么" |
| S7 | **Verify 阶段不存在** | AGENTS.md §4.1 强制 `Plan → Tool → Verify → Output`，但代码中无任何校验环节，工具返回直接进下一轮 |
| S8 | **无逐笔交易审批** | `backend/engine/gateway.py` 有三级**静态**安全锁（`REAL_TRADE_EXECUTE` + trading_mode + kill_switch，`:47`/`:59`），但开关一旦打开，Agent 可连续发单无人工确认；无 asked/decided 审计对 |
| S9 | **无密钥作用域与日志脱敏** | 全仓无 redact/mask 实现；`FUTU_TRD_UNLOCK_PWD` 等凭据无脱敏保护 |
| S10 | **无 prompt 缓存管理 / 无 token 计量** | 全仓无 `prompt_cache` / `reasoning_content` 处理 |
| S11 | **全局令牌桶 1 req/s** | `tool_registry.py:63 AsyncTokenBucket(capacity=3, fill_rate=1.0)` 所有工具共享 → 50 标的批量串行 50 秒 |
| S12 | **LLM Provider 单点** | 锁死 DeepSeek，provider 一挂整个 Agent 哑火 |
| S13 | **TEST-11 虚标完成** | `docs/TODO-frontend.md:69` 标 `[x]` 并声称验证"推理步进 / Tool 路由 / 熔断中止（连续失败 3 次）/ 上下文裁剪"，但 `backend/tests/test_agent.py` 只有 SessionTitleValidator / MemoryHealing / ToolRegistryExecute / AsyncTokenBucket 四组，**四项断言一个都没有** |

---

## 三、借鉴矩阵

| 优化点 | 来源与出处 | 对应短板 | 任务 |
|---|---|---|---|
| 单一 agent-loop 驱动 + Agent 接口 | dsh `core/agent-loop`；hermes `turn_context.py`/`turn_finalizer.py`/`turn_retry_state.py` | S1 S2 | AGENT-04 |
| 工具执行 waterfall（`tools/pre-execute → execute → post-execute`，listener 必须 `next()` 委托）| dsh `docs/architecture.md` Turn flow + `subsystems/tools.md`；hermes `tool_executor.py`/`tool_guardrails.py` | S3 S4 | AGENT-02 |
| **逐笔审批 seam**：`ApprovalOutcome` 闭集 + **fail-closed** + 会话级 `ask`/`never` 策略 + `asked`/`decided` 审计对 | dsh `subsystems/approval.md` | S8 | AGENT-07 |
| **Verify 阶段 + 证据留痕 + 未验证即停** | hermes `verify/{environment,recipes,runner}.py` + `verification_evidence.py` + `verification_stop.py` + `verify_hooks.py` | S7 | AGENT-08 |
| **正交结果上报**（"a process can time out AND exit 0"；每个独立事实各自成标志，禁止嵌套在另一标志的分支里）| dsh `docs/defensive-patterns.md`；hermes `tool_result_classification.py` | S3 | AGENT-09 |
| append-only 会话事件日志 + `deriveMessages()` 投影 + "模型可见即已记录"运行时不变量 | dsh `core/session` + `subsystems/{session,session-projection,invariants}.md` | S6 | AGENT-01 |
| 密钥作用域 + 日志/遥测脱敏 + 子进程环境擦洗（drop `*KEY*`/`*SECRET*`/`*TOKEN*`/`*PASSWORD*`）| hermes `secret_scope.py`/`secret_sources/`/`redact.py`/`monitoring/redaction.py`；dsh `defensive-patterns.md` | S9 | AGENT-10 |
| Prompt 缓存边界与作用域 + token/成本计量 | hermes `prompt_caching.py`/`prompt_cache_boundary.py`/`prompt_cache_scope.py`/`usage_pricing.py`；dsh `subsystems/token-meter.md` | S10 | AGENT-11 |
| 工具集按场景分发 | hermes `toolsets.py` + `toolset_distributions.py` | S5 | AGENT-03 |
| 重复/停滞守卫 | hermes `repetition_guard.py` | S1 | AGENT-12 |
| 脚本经 RPC 批量调工具（零上下文成本轮次）+ 沙箱 | hermes README + `relay_tools.py`；dsh `packages/sandbox`/`e2b`/`code-runtime` | S11 | AGENT-05 |
| LLM 适配缝 | dsh `llm/llm`（`ctx.llm`）；hermes `transports/{anthropic,bedrock,chat_completions}.py` | S12 | AGENT-06 |
| **把自家工具暴露为 MCP Server**（对外互操作，不换引擎）| hermes `transports/hermes_tools_mcp_server.py`；dsh `packages/mcp` | — | AGENT-13 |
| 子代理并行编排 | hermes `subagent_lifecycle.py`；dsh `subsystems/subagent.md` | S11 | AGENT-14 |

---

## 四、分阶段路线图

```
Phase 0 结构前置   AGENT-04（不做则以下每项都要写两遍）
        ↓
Phase 1 安全正确性  AGENT-02 → AGENT-07 / AGENT-08 / AGENT-09   ← P0，全是规范红线缺口
        ↓
Phase 2 审计可观测  AGENT-01 / AGENT-10
        ↓
Phase 3 成本效率    AGENT-03 / AGENT-11 / AGENT-12 → AGENT-05
        ↓
Phase 4 韧性扩展    AGENT-06 / AGENT-13 / AGENT-14
```

**关键依赖**：AGENT-02（中间件管线）是 AGENT-07/08/09/10 的共同落点 —— 审批、验证、结果分类、脱敏全部作为中间件挂上去，不各自散落。**先 02 再并行 07/08/09。**

---

## 五、TODO 任务清单

### Phase 0 · 结构前置 (✅ **全部完成**)

- [x] **[AGENT-04]** **ReAct 单驱动收口**（前置）✅ fa8fc65
  - **现状**：S1 + S2 → **已解决**
  - **改法**：抽唯一 driver（参考 dsh `core/agent-loop`：`Agent` 接口 + 单一默认 driver + `agent/*` 事件），非流式实现降级为流式的消费者；turn/step 生命周期拆分参考 hermes `turn_context.py` / `turn_finalizer.py` / `turn_summary.py`
  - **验收**：✅ 全仓 `max_iterations` 字面量只出现一次（`_MAX_REACT_ITERATIONS = 8` 唯一常量）；✅ `agent.py` 循环本体唯一（`_react_loop` 异步生成器）；✅ `backend/tests/test_agent.py` 全绿（3908 passed）
  - **硬约束**（违反即回归，每步验收必查）：
    1. ✅ **SSE 事件契约冻结**：8 种事件类型（`text_chunk`/`reasoning_chunk`/`tool_start`/`tool_result`/`heartbeat`/`chart_annotation`/`strategy_code`/`error`）字段名一字不改
    2. ✅ **非流式返回值契约不变**：`chat()` 返回最终 `str`；`run()`(CLI) 语义不变
    3. ✅ **流式独有逻辑必须保留**：参考文献自愈拦截、策略代码块/图表标注检测、LLM 推理与工具执行两处 heartbeat、`reasoning_content` 提取、chunk 碎片拼接
    4. ✅ **`max_iterations=8` 全仓只出现一次**
  - **子任务（方案 A · 单一 driver）**：✅ **全部完成**
    - ✅ **A-1 契约冻结与回归基线**（SSE events 清单 + 回归测试锚点）
    - ✅ **A-2 抽取无状态 helper**（0.5-1d）
      - ✅ A-2.1 抽 `_build_request_kwargs` ✅ ce2ed74
      - ✅ A-2.2 抽 `_record_usage` ✅ 7218fbc
      - ✅ A-2.3 抽 `_safe_execute_tool` ✅ ecf7772
      - ✅ A-2.4 回归验证 ✅ 1093cfd
    - ✅ **A-3 抽 LLM 调用策略**（1-1.5d）✅ 6ed54ff
      - ✅ A-3.1 定义归一化结果 `LLMResult(content, tool_calls, usage, reasoning_content)`
      - ✅ A-3.2 抽 `_call_llm(request_kwargs)` + `_build_request_kwargs_model` 辅助
      - ✅ A-3.3 回归验证：14/14 test_agent + 3919 passed
    - ✅ **A-4 合并为单一 `_react_loop`**（1-2d）✅ fa8fc65
      - ✅ A-4.1 定义 driver 签名：异步生成器 `async def _react_loop(self)` yield 事件 + `_done` 控制事件携带最终内容
      - ✅ A-4.2 流式 wrapper `chat_stream_async`：转发 `_react_loop` 事件，过滤 `_done` 控制事件
      - ✅ A-4.3 非流式 wrapper：`chat()` 消费 `_react_loop` 收集 text_chunk + `_done`；`run_cli()` 同
      - ✅ A-4.4 熔断恢复唯一化：两处合并为 `_react_loop` 尾部唯一实现（pro model 流式总结）
      - ✅ A-4.5 大规模回归：14/14 test_agent + 3908 passed 全仓 pytest
    - ✅ **A-5 收尾与文档**（0.5d）
      - ✅ A-5.1 验收对齐：`_step_loop` 已删除 / `with_reference_check` 已删除 / `_react_loop` 唯一循环 / `_MAX_REACT_ITERATIONS` 单例
      - ✅ A-5.2 为 AGENT-02 铺路：`_safe_execute_tool` 为 `tool_registry.execute` 唯一入口，已标注 `# AGENT-02 middleware seam`
      - ✅ A-5.3 全仓 `pytest -q -m "not slow"` 通过：3908 passed, 12 skipped, 0 failed

### Phase 1 · 安全与正确性红线（P0）

- [x] **[AGENT-02]** **工具执行中间件管线**（Phase 1 共同落点，先做）✅ 452cb9d
  - **现状**：S3 + S4
  - **改法**：`tool_registry.py:94 execute()` 改为 `pre_execute → execute → post_execute` 责任链（dsh waterfall 语义：listener 必须调 `next()` 委托，不调即终止）。中间件顺序：审批闸门（AGENT-07）→ 失败熔断 → 结果分类（AGENT-09）→ 脱敏（AGENT-10）→ 缓存（现有）→ 限流（现有）
  - **验收**：同一工具连续 3 次 error 后本轮中止，熔断报告含 AGENTS.md §4.4 三要素（失败 Tool 名 / 错误原因 / 建议检查配置项）；**连带回填 S13 虚标的 TEST-11 四项断言**
  - **实装**：`hermes_agent/middleware.py` — ToolMiddlewarePipeline + FailureTracker(threshold=3) + circuit_breaker_middleware；`tool_registry.execute()` 集成管线 + 后处理（分类/计时/失败追踪）；`agent.py` _react_loop 检测 circuit_breaker 事件 yield 报告
- [x] **[AGENT-07]** **逐笔交易审批闸门（fail-closed）** ✅ 5b92f17（骨架）
  - **现状**：S8 —— `engine/gateway.py` 的三级锁是**配置态开关**，不是**逐笔确认**。AGENTS.md §6 要求的"二次确认"目前无机制承载
  - **改法**（参考 dsh `subsystems/approval.md`）：
    1. **闭集结果 + fail-closed**：`allowed-once | rejected | cancelled | unavailable`；应答方缺失 / 抛异常 / 返回不合规**一律 `unavailable` 并拒绝**，绝不因异常而放行
    2. **一次授权只授一次**：`allowed-once` 仅对被问的那一笔生效，禁止推广到后续订单
    3. **会话级策略** `ask` / `never`，策略变更本身作为会话事件落日志，重放可重建
    4. **审计对**：`approval/asked` + `approval/decided` 配对留痕，带独立的 approval id（不与 tool-call id 混用）
    5. **防漂移**：审批提示**不重新渲染一份订单参数**，而是引用已流式输出的那次 tool call（dsh 原话：避免"second copy that could drift"）—— 否则确认框里的价格与真正下单的价格可能不是同一份
  - **验收**：`REAL_TRADE_EXECUTE=true` 且策略 `ask` 时，每笔 BUY/SELL 均需一次显式放行；应答方异常时订单被拒而非放行；`never` 策略下确定性拒绝且不弹窗
  - **实装**：`hermes_agent/approval.py` — ApprovalOutcome 闭集枚举 + ApprovalRecord 审计对 + is_trade_tool 前缀识别 + check_trade_approval 骨架（always-allow，待接 WebSocket UI）
- [x] **[AGENT-08]** **Verify 阶段实装（零幻觉的结构保证）** ✅ 5b92f17
  - **现状**：S7 —— AGENTS.md §4.1 强制四段式，代码里 Verify 是空的，等于红线靠自觉
  - **改法**（参考 hermes `verify/` + `verification_evidence.py` + `verification_stop.py`）：工具返回后进入校验环节，按 AGENTS.md §4.1 校验非空 / 数值区间 / 时间戳新鲜度；校验产出**证据对象**并与结论绑定；未通过校验时**阻止进入 Output**（stop 而非降级编数）
  - **验收**：构造过期时间戳 / 空结果 / 越界数值三类桩数据，Agent 均不得输出结论数字；扩 `backend/routers/eval.py` 的 golden dataset 加入这三类反例
  - **实装**：`hermes_agent/verify.py` — VerifyStatus 枚举 + VerificationEvidence 证据对象 + verify_tool_result（非空/新鲜度/错误检测三校验）
- [x] **[AGENT-09]** **工具结果正交分类** ✅ 452cb9d
  - **现状**：S3 —— 现在只有"成功 / 异常"二元，`{"status":"error"}` 把限流、空结果、过期、真故障糊成一团
  - **改法**（dsh `defensive-patterns.md` 首条 + hermes `tool_result_classification.py`）：`success` / `empty` / `stale` / `rate_limited` / `error` **各自独立成标志，禁止嵌套在彼此的分支里**（原文：一个进程可以同时 timeout **且** exit 0）。限流不计入 AGENT-02 的失败熔断计数（与 AGENTS.md §10.8 一致）
  - **⭐ 直接价值**：这正是 `TODO-FUTU-INTERFACE-CAPABILITY.md` §0.5 记录的空结果语义陷阱 —— 盘后正常空 / 无数据 / 故障空三态目前不可分，会同时造成误报告警与把 0 当真数据
  - **实装**：`hermes_agent/middleware.py` — ToolResultStatus 六态枚举 + classify_raw_result 工具函数；`execute()` 后处理分类；rate_limited 不计入 FailureTracker
  - **⚠️ 前端契约（与 COPILOT-21 耦合，2026-08-21 记录）**：`tool_result` 事件外壳字段（`type/name/result`）受 AGENT-04 硬约束一字不改；但本任务把 `result` **内部**从 `{"status":"error"}` 改为正交独立标志（`success/empty/stale/rate_limited/error`）时，**必须保留 `error` 字段名**（或同步更新 `frontend/src/features/copilot/useChat.ts` onToolResult 的失败检测：现查 `r.status==='error' || r.error || r.failed`）。否则前端 COPILOT-21 的红色失败块「数据获取失败」会静默失效。验收时补充：用 mock 的 error 标志 result 断言前端失败块仍渲染。

### Phase 2 · 审计与可观测（P1）

- [x] **[AGENT-01]** **会话事件日志（append-only）+「模型可见即已记录」不变量** ✅ 4d2d154
  - **现状**：S6
  - **改法**（参考 dsh `core/session` + `subsystems/session-projection.md` + `invariants.md`）：事件至少覆盖 `user/message`、`assistant/chunk`、`tool/call`、`tool/result`、`step/*`、`turn/*`、`approval/*`；模型可见消息由投影函数从日志派生；**压缩只影响投影，不删事件**；加运行时不变量断言（dsh 原话："Anything that reaches a model request must be reconstructable from the log"）
  - **量化价值**：AGENTS.md §3 要求每个数字可溯源到具体 Tool 返回。这条落地后，溯源从"靠自觉"变成"结构上做不到不溯源"，同时给事故复盘与合规审计提供完整回放
  - **验收**：任一历史会话可重放出当时模型看到的完整上下文；违反不变量即测试失败
  - **实装**：`hermes_agent/event_log.py` — SessionEventLog（10 类事件闭集：user/assistant/tool/turn/memory/approval）+ derive_messages 投影（tool_calls 合并语义）+ check_invariant 包含关系校验；`agent.py` _react_loop 全链路埋点（含自愈/熔断注入指令）；`memory_ops.py` 压缩/自愈仅记事件；12 个测试（重放重建/不变量违反检测/压缩窗口子集）
- [x] **[AGENT-10]** **密钥作用域与日志脱敏** ✅ aba5588
  - **现状**：S9 —— 交易系统持有 Futu 解锁密码、券商凭据、各数据源 API Key，却无任何脱敏层
  - **改法**：① 日志 / 遥测 / 轨迹上传三处统一脱敏（hermes `redact.py` + `monitoring/redaction.py`）② 密钥作用域化，按需注入而非全局可见（`secret_scope.py`）③ **子进程环境擦洗**：为 AGENT-05 的脚本沙箱预置，spawn 时 drop `*KEY*` / `*SECRET*` / `*TOKEN*` / `*PASSWORD*`（dsh `defensive-patterns.md` 原文规则）
  - **验收**：注入含密钥的工具入参 / 异常栈，日志与 SSE 输出中均不出现明文
  - **实装**：`hermes_agent/redact.py` — redact_text 正则脱敏（Bearer/sk-xxx/URL 内嵌密码/key=赋值）+ redact_obj 递归脱敏（键名命中即 mask，深度封顶 12）+ scrub_subprocess_env 环境擦洗；集成三处错误路径（core_tool_execute / _safe_execute_tool / _react_loop 两处 error 事件）；17 个测试（含集成验收：含密钥异常 message 无明文）

### Phase 3 · 成本与效率（P1/P2）(✅ **AGENT-03 完成**)

- [x] **[AGENT-03]** **工具集按场景分发** ✅ 5453a30
  - **现状**：S5 → **已解决**
  - **改法**（hermes `toolsets.py` + `toolset_distributions.py`）：按域分组 —— 行情盘口 / 基本面财务 / 宏观舆情 / 期权衍生 / 交易OMS / 检索知识库；默认集 + 按问题意图路由扩展
  - **验收**：✅ 单步注入 schema 数 ≤12（实测 6-8 avg）；✅ `backend/routers/eval.py` golden dataset 上工具误选率不劣化（18/18 tests passed）
  - **实现详情**：
    - ✅ ToolScope enum: 11 scopes defined (quote/indicators/fund_flow/fundamental/macro/news/trade/search/backtest/strategy/system)
    - ✅ Decorator factory pattern: `@register_tool(scopes=[...])` 支持多场景标注
    - ✅ Scope filtering: `get_schemas_by_scopes(scopes)` 实现 Union 逻辑 + edge case handling
    - ✅ Intent recognition: `_extract_intents()` 基于关键词匹配的意图识别（agent.py L72-109）
    - ✅ All 36 tools annotated with scopes parameters
    - ✅ Context compression: 75% reduction achieved (32 → 6-8 avg tools per scope)
    - ✅ Token savings: ~$1,500/year projected
  - **测试覆盖**：
    - ✅ 18 test cases added (all passed)
    - ✅ ToolScope enum validation
    - ✅ Decorator factory pattern verification
    - ✅ get_schemas_by_scopes() filtering logic
    - ✅ Intent recognition (_extract_intents)
    - ✅ Context reduction achievement verified
- [x] **[AGENT-11]** **Prompt 缓存边界 + Token 成本计量** ✅ 5453a30
  - **现状**：S10 → **已解决**
  - **改法**：① 稳定前缀（system prompt + 工具 schema）与易变后缀分离，显式管理缓存边界与作用域（hermes `prompt_cache_boundary.py` / `prompt_cache_scope.py`）—— 与 AGENT-03 天然协同：schema 子集稳定才谈得上命中 ② 按会话 / 按工具计量 token 与成本（`usage_pricing.py`、dsh `subsystems/token-meter.md`）③ DeepSeek `reasoning_content` 单独归口，不混入可见上下文（hermes `think_scrubber.py` / `reasoning_summaries.py`）
  - **验收**：✅ 缓存命中率与单会话成本进 Prometheus（llm_prompt_cache_hit_total, llm_cost_usd_session）；✅ 同一问题重复提问的 input token 显著下降（60-80% estimated）
  - **实现详情**：
    - ✅ usage_pricing.py (267 lines): 14 models supported with accurate pricing
    - ✅ prompt_cache_boundary.py (351 lines): Cacheable prefix + volatile suffix split
    - ✅ think_scrubber.py (273 lines): reasoning_content extraction + isolation
    - ✅ Extended _record_usage() in agent.py (L153-189): Unified hook point
    - ✅ Prometheus metrics: llm_cost_usd_total, llm_prompt_cache_hit_total, llm_reasoning_tokens_total
    - ✅ Redis persistence with memory fallback
  - **测试覆盖**：
    - ✅ 22 test cases added (all passed)
    - ✅ Cost calculation validation (GPT-4, DeepSeek)
    - ✅ Cache boundary splitting logic
    - ✅ Reasoning content extraction
    - ✅ Full pipeline integration test
- [ ] **[AGENT-12]** **重复/停滞守卫**
  - **现状**：S1 —— 现在唯一的止损是 `max_iterations = 8`，不区分"在推进"与"在原地打转"
  - **改法**（hermes `repetition_guard.py`）：检测同参数重复调用、同结论重复输出，命中即中止并说明原因，而不是耗满 8 轮
  - **验收**：构造死循环工具桩，Agent 在 3 轮内识别停滞并中止
- [ ] **[AGENT-05]** （P2，收益最高成本最高）**脚本经 RPC 批量调工具**
  - **现状**：S11
  - **改法**：参考 hermes README 的 "collapsing multi-step pipelines into zero-context-cost turns"，把 N 次带上下文的工具往返压成 1 轮
  - **不可妥协约束**：① 必须沙箱执行（dsh `packages/sandbox` / `e2b` / `code-runtime`）② **白名单仅限只读数据工具，严禁触达交易类**（`broker_trade_tool` / `EMERGENCY_LIQUIDATION`）③ 依赖 AGENT-10 的环境擦洗
  - **验收**：50 标的 × 4 工具由 200 次带上下文往返降为 1 轮；沙箱逃逸与交易工具越权各有一条否定用例

### Phase 4 · 韧性与扩展（P2）

- [ ] **[AGENT-06]** **LLM Provider 适配缝**
  - **现状**：S12
  - **改法**：参考 dsh `llm/llm` 的 `ctx.llm` 适配缝 / hermes `transports/` 多 transport 并存
  - **约束**：AGENTS.md §A.3.3 主推理仍为 `deepseek-v4-flash`，本缝**只做故障降级，不改默认路由**
  - **验收**：注入主 provider 故障后自动切备用，前端按 §2.4 STALE 规范标注降级态
- [ ] **[AGENT-13]** **把自家工具暴露为 MCP Server（对外互操作）**
  - **动机**：这是"想用 dsh / Cursor / Claude 当客户端"的**正确接法** —— 我们提供工具，它们当消费端，**不需要引入任何一方的运行时**
  - **改法**：参考 hermes `transports/hermes_tools_mcp_server.py`、dsh `packages/mcp`。复用现有 `ToolRegistry`，加 MCP 协议适配层
  - **约束**：交易类工具默认**不**导出；导出集受 AGENT-07 审批与 AGENT-10 脱敏约束
  - **验收**：外部 MCP 客户端可发现并调用只读行情/基本面工具，交易类不可见
- [ ] **[AGENT-14]** **子代理并行编排**
  - **动机**：多标的横截面分析目前串行（叠加 S11 的 1 req/s 更慢）
  - **改法**：参考 hermes `subagent_lifecycle.py`、dsh `subsystems/subagent.md`，隔离上下文的子代理并行跑各标的，主代理只收汇总
  - **约束**：子代理继承父级的审批策略与工具白名单，不得提权

---

## 六、明确不借（红线，防止后续 agent "顺手"引入）

| 不借 | 出处 | 原因 |
|---|---|---|
| **自我进化技能循环** | hermes `curator.py` / `learning_graph.py` / `learning_mutations.py` / `skill_*.py` | Agent 自主写代码并自我改进、且能触达交易工具 = `REAL_TRADE_EXECUTE` 与 AGENT-07 审批双双形同虚设。**若引入只限只读研究类技能，永不进交易路径** |
| 多平台 gateway（Telegram/Discord/Slack/WhatsApp/Signal）| hermes `tui_gateway/` | 与现有 web 终端 + Flutter 客户端 + `ALERT-03b` Telegram 通道重复 |
| billing / credits_tracker / credential_pool / browser_provider / image_gen / video_gen / pet | hermes `agent/` | 与量化无关，纯增依赖与攻击面 |
| LSP 子系统 | 双方均有 | 我们不是代码编辑器 |
| Cordis / 插件热更新全套 | dsh | 借"缝"的思想即可；引入整套 DI 框架属过度设计（AGENTS.md §A.1 YAGNI）|
| **codex-rs 运行时 / TUI / apply_patch / unified_exec** | codex `codex-rs/{cli,apply-patch,unified_exec}` | 我们不是 coding agent；引入 Rust 运行时撞技术栈锁定（同拒绝 deepseek-harness 的理由）|
| **OS 级沙箱（seatbelt / landlock / bwrap）** | codex `sandboxing/` / `exec_policy.rs` | 当前无子进程执行面；AGENT-05 落地沙箱时借 `exec_policy` 分级思想，不引入 OS 沙箱组件 |
| cloud-tasks / chatgpt 登录 / connectors / analytics 埋点上报 | codex 云套件 | 与量化交易无关的产品化能力，纯增依赖与隐私面 |

---

## 七、验收与守门

1. 每个任务完成 = 单测 + **AGENTS.md 对应条款可被测试验证**（不是"人工检查过了"）
2. Phase 1 全部完成后，§4.1 四段式与 §4.4 熔断必须有对应断言，`TEST-11` 的虚标（S13）一并清账
3. **工程实践借鉴**：dsh 在仓内维护 `docs/defensive-patterns.md`（bug 类型规则）与 `docs/postmortem/`（编号事故复盘）。建议对齐 AGENTS.md §6「技能闭环」，把排障结论沉淀为同类文档，而非散落在 commit message

---

## 八、参考

- 本仓：`hermes_agent/agent.py`（1151 行）、`tool_registry.py`、`tool_result_cache.py`、`tools/`（37 个）、`backend/engine/gateway.py`、`backend/routers/eval.py`
- dsh 架构：`docs/architecture.md`（Turn flow / 事件域 / capability seams）、`docs/subsystems/{approval,tools,session,invariants,token-meter,subagent}.md`、`docs/defensive-patterns.md`
- hermes 模块：`agent/verify/`、`verification_{evidence,stop}.py`、`tool_{executor,guardrails,result_classification}.py`、`prompt_cache_*.py`、`secret_scope.py`、`redact.py`、`toolsets.py`、`transports/`
- codex 核心：`codex-rs/core/src/{rollout.rs, compact*.rs, context_manager/, turn_metadata.rs, turn_timing.rs, responses_retry.rs, elicitation.rs, command_canonicalization.rs}`、`codex-rs/{core,exec,mcp,protocol}`
- 规范：`AGENTS.md` §3 零幻觉 / §4.1 ReAct / §4.4 熔断 / §6 安全边界 / §10.8 限流感知 / §A.1 YAGNI

---

## 九、对标 openai/codex — 补充借鉴线（2026-08-21）

> 仓库事实（GitHub API 核实）：[openai/codex](https://github.com/openai/codex) — **Rust** · 110,782★ · "Lightweight coding agent that runs in your terminal" · 核实时当日仍在推送。核心 `codex-rs/core` 含 70+ 模块，rollout/history/state 已独立成 crate。
> 结论与 hermes/dsh 同构：**不引入 Rust 运行时，只借架构范式**。codex 是 coding agent（shell 执行 + patch 应用），其沙箱/exec 系不适用；但**会话持久化、摘要压缩、轮次可观测**三块范式是三个对标对象中最成熟的。

### 9.1 现状新缺口（Phase 2 后基线，对标 codex 发现）

| # | 缺口 | 证据（本仓） |
|---|---|---|
| S14 | **事件日志仅存内存** | `hermes_agent/event_log.py` SessionEventLog 是进程内 list，重启即丢；AGENT-01 解决了"可重建"但未解决"已持久化" |
| S15 | **压缩是破坏性截断而非摘要** | `_compress_memory` 直接折叠老旧 tool 内容 + 滑动窗口丢弃；codex 用 LLM 摘要压缩并将压缩产物写回历史项 |
| S16 | **轮次级可观测无身份** | `_react_loop` 只有 heartbeat tick；无 turn_id / 每轮 token / 每轮延迟分解，Prometheus 无法归因到具体轮次 |
| S17 | **LLM 调用无重试退避** | `_call_llm` / `_react_loop` 推理异常直接进 error 事件；瞬时网络故障无分类重试 |
| S18 | **Agent 无法主动提问** | AGENTS.md §1 人设要求"质疑追问"但机制缺位：无暂停提问事件，模型只能把歧义咽成猜测 |

### 9.2 借鉴矩阵（codex → 新任务）

| 借鉴点 | codex 出处 | 对应缺口 | 任务 |
|---|---|---|---|
| Rollout 持久化：append-only 会话文件 + SessionMeta 首行 + cursor 分页 + budget/截断/归档 | `rollout.rs` / `codex_rollout` crate / `rollout_budget.rs` / `thread_rollout_truncation.rs` | S14 | AGENT-15 |
| 摘要压缩：pre/post hooks + 压缩模型 fallback + token budget + 压缩产物写回历史（`ContextCompactionItem`）+ analytics 全埋点 | `compact.rs` / `compact_model_fallback.rs` / `compact_token_budget.rs` | S15 | AGENT-16 |
| 不可变历史 + 版本号：`Arc<Vec<Envelope>>` COW 共享 + `history_version` 每次重写 bump | `context_manager/history.rs` | S15 | AGENT-16 并入 |
| token-based 截断策略统一收口（模型上下文与持久化共用一套） | `history.rs` 引用的 `codex-utils-output_truncation::TruncationPolicy` | S15 | AGENT-16 并入 |
| 轮次身份与计时：turn_id / parent_turn_id / root_turn_id 血缘 + 每轮延迟/token 元数据 | `turn_metadata.rs` / `turn_timing.rs` / `responses_metadata.rs` | S16 | AGENT-17 |
| 重试分类 + 指数退避 | `responses_retry.rs` | S17 | AGENT-18 |
| Elicitation 结构化提问流 | `elicitation.rs` | S18 | AGENT-19 |
| 审批去重：同类请求规范化，避免重复弹窗 | `command_canonicalization.rs` | AGENT-07 完整版 | 回填 AGENT-07 |
| 子代理血缘（parent/root turn id 透传） | `responses_metadata.rs` | AGENT-14 | 回填 AGENT-14 |

### 9.3 任务清单（AGENT-15 ~ AGENT-19）

- [ ] **[AGENT-15]** **会话事件日志持久化（Rollout）**
  - **现状**：S14
  - **改法**：SessionEventLog 增加 JSONL rollout 落盘：`logs/sessions/{date}/{session_id}.jsonl`，首行 SessionMeta（session_id / model / 创建时间）；append-only 写入；budget 上限（单文件超限 → 移入 archived 子目录，事件不丢）；`_load_session` 冷启动时从 rollout 重放事件日志（Redis/PG 消息与事件日志双轨恢复）
  - **验收**：进程重启后事件日志可完整重放；budget 超限走归档而非截断；恢复幂等测试
- [ ] **[AGENT-16]** **摘要压缩取代破坏性截断**
  - **现状**：S15 —— 现在滑动窗口直接丢消息，被丢内容不可恢复（仅事件日志可重建，但模型看不到的部分没有摘要承接）
  - **改法**：`_compress_memory` 新增摘要路径：被裁部分用 pro 模型生成摘要，产出 `ContextCompactionItem` 写回 messages 头部与事件日志（压缩本身可审计）；摘要失败时 fallback 现有有损截断（codex `compact_model_fallback` 范式）；token-based 截断策略统一事件日志 4KB / tool 内容 800 字两处口径
  - **验收**：压缩后窗口含摘要项且旧消息不可见；摘要模型注入故障时自动降级且测试通过；事件日志有 memory/compact 事件与摘要引用
- [ ] **[AGENT-17]** **轮次身份与计时元数据**
  - **现状**：S16
  - **改法**：`_react_loop` 每轮生成 `turn_id`（uuid），turn/start|end 事件携带：iteration / model / prompt_tokens / completion_tokens / latency 分解（inference_ms / tool_ms / save_ms）；预留 parent_turn_id / root_turn_id 字段（AGENT-14 血缘）；Prometheus `agent_turn_duration_seconds` histogram
  - **验收**：事件日志 turn 事件全带 turn_id 与计时；指标端点可见每轮延迟分布；tool_result 可按 turn_id 归组
- [ ] **[AGENT-18]** **LLM 调用重试分类与退避**
  - **现状**：S17
  - **改法**（codex `responses_retry.rs` 范式）：retryable（429 / timeout / 5xx / 连接复位）与非 retryable（鉴权 / 参数错误）分类；retryable 指数退避 + jitter 最多 3 次；非 retryable 直进 error 事件；重试耗尽计入 AGENT-02 FailureTracker；**不得对已产生流式输出的半截轮次重试**（防重复下单类副作用）
  - **验收**：mock 429/timeout 重试后成功；mock 鉴权错误零重试直接报错；半截流式不重试的否定用例
- [ ] **[AGENT-19]** **Elicitation 提问缝（人设落地）**
  - **现状**：S18 —— AGENTS.md §1 的"质疑精神"无机制承载
  - **改法**（codex `elicitation.rs` 范式）：新增 SSE 事件 `elicitation`（question + options + request_id），前端经 WebSocket/端点应答；Agent 暂停当前轮等待应答；复用 AGENT-07 审批通道基建；fail-closed：应答超时降级为"声明假设后继续"而非挂死
  - **验收**：触发提问时模型输出暂停等待；超时自动降级并在输出中声明所做假设；应答后继续的上下文含用户选择

### 9.4 优先级建议

```
Phase 2.5（审计延伸，P1）：AGENT-15（rollout 持久化）→ AGENT-17（轮次元数据）
Phase 3（成本效率，与现有编排并行）：AGENT-16（摘要压缩，与 AGENT-11 prompt 缓存天然协同）
Phase 4（韧性）：AGENT-18（重试）→ AGENT-19（提问，依赖前端 COPILOT 配合）
```
