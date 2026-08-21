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

### Phase 0 · 结构前置

- [ ] **[AGENT-04]** **ReAct 单驱动收口**（前置）
  - **现状**：S1 + S2
  - **改法**：抽唯一 driver（参考 dsh `core/agent-loop`：`Agent` 接口 + 单一默认 driver + `agent/*` 事件），非流式实现降级为流式的消费者；turn/step 生命周期拆分参考 hermes `turn_context.py` / `turn_finalizer.py` / `turn_summary.py`
  - **验收**：全仓 `max_iterations` 字面量只出现一次；`agent.py` 循环本体唯一（不苛求整文件 <300 行——1151 行含 `_heal_memory`/`_compress_memory`/`_save_session` 等非循环逻辑，拆循环不自动缩文件）；`backend/tests/test_agent.py` 全绿
  - **硬约束**（违反即回归，每步验收必查）：
    1. **SSE 事件契约冻结**：`chat_stream_async` 对外 yield 的事件类型（`text_chunk`/`reasoning_chunk`/`tool_start`/`tool_result`/`heartbeat`/`chart_annotation`/`strategy_code`/`error`）与字段名一字不改 —— `backend/routers/chat.py:215` 原样 JSON 化喂前端，改任何事件名=前端崩
    2. **非流式返回值契约不变**：`chat()` 返回最终 `str`；`run()`(CLI) 语义不变
    3. **流式独有逻辑必须保留**：参考文献自愈拦截、策略代码块/图表标注检测、LLM 推理与工具执行两处 heartbeat、`reasoning_content` 提取、chunk 碎片拼接 —— 这些是流式差异化，不得被"收口"误删
    4. **`max_iterations=8` 全仓只出现一次**
  - **子任务（方案 A · 单一 driver）**：
    - **A-1 契约冻结与回归基线**（0.5d，最先做）
      - [ ] A-1.1 枚举 `chat_stream_async` 全部 `yield {"type":...}` 事件（类型+字段）成清单
      - [ ] A-1.2 新建 `backend/tests/test_agent_stream_events.py`：mock LLM 产出「仅文本/含 tool_call/含 reasoning_content/触发参考文献自愈/触发熔断恢复/触发图表标注」六类响应，断言 yield 事件序列与字段符合 A-1.1 —— 作为重构回归锚点，全绿
      - [ ] A-1.3 检查 `routers/chat.py:215` 消费点对事件 dict 有无字段级强依赖，记录"不可动字段"
    - **A-2 抽取无状态 helper**（0.5-1d，低风险先落地，立即消 max_iterations 重复）
      - [ ] A-2.1 抽 `_build_request_kwargs(model, stream)`：合并 `:657-663`/`:829-838` 两处 schema/model/temperature/tools 构造；`max_iterations=8` 保留 `:649`、删 `:819`
      - [ ] A-2.2 抽 `_record_usage(usage)`：合并 `:682-688`/`:946-951` 两处 token 计量埋点
      - [ ] A-2.3 抽 `_safe_execute_tool(name, args_str)`：统一两处 safe_execute（`:704-711`/`:968-975`），内部 `json.loads` + `await execute` + try/except → 这是 **AGENT-02 中间件未来唯一挂点**，标注 `# AGENT-02 middleware seam`
      - [ ] A-2.4 回归：`test_agent.py` + `test_agent_stream_events.py` 全绿；`routers/chat.py` 手测一次流式对话确认 NDJSON 事件流无变化
      - commit: `refactor(agent): 抽取 request_kwargs/usage/tool-exec 三 helper，收敛 max_iterations 至单一常量`
    - **A-3 抽 LLM 调用策略**（1-1.5d）
      - [ ] A-3.1 定义归一化结果 `LLMResult(content, tool_calls, usage, reasoning_content)`
      - [ ] A-3.2 抽 `_call_llm(request_kwargs, stream, heartbeat_cb)`：`stream=False` 直调返回 `LLMResult`；`stream=True` 复用现有 chunk 拼接逻辑（`:890-941`）收口进此函数；LLM 推理期 heartbeat（`:866-877`）经 `heartbeat_cb` 上报
      - [ ] A-3.3 回归：重跑六类用例，重点验证流式 tool_calls 碎片拼接 / reasoning_content 顺序 / usage 落最后 chunk 三处无回归
    - **A-4 合并为单一 `_react_loop`**（1-2d，风险最高）
      - [ ] A-4.1 定义 driver 签名 `async def _react_loop(self, emit) -> str`；内部统一语义事件（think_start/tool_call/tool_result/output/recover_start），由调用方映射成对外事件
      - [ ] A-4.2 流式 wrapper `chat_stream_async`：保留对外签名与 yield 事件，映射回冻结事件全集；参考文献自愈拦截、图表标注/策略代码块检测作为 wrapper post-processing，**不进 driver**（保持 driver 纯）
      - [ ] A-4.3 非流式 wrapper：`chat()` 调 `_react_loop(emit=None)` 取返回 str；`run()`(CLI) 同
      - [ ] A-4.4 熔断恢复唯一化：两处强制总结注入（`:745-773`/`:1097-`）合成 driver 内 `_circuit_break_recover()`
      - [ ] A-4.5 大规模回归：六类 + `test_agent.py` + 全仓 pytest；实连 DeepSeek 真实流式对话，对比收口前后事件流 diff
      - commit: `refactor(agent): 合并 _step_loop 与 chat_stream_async 为单一 _react_loop，事件契约不变`
    - **A-5 收尾与文档**（0.5d）
      - [ ] A-5.1 验收对齐：确认循环本体唯一 + max_iterations 单例
      - [ ] A-5.2 为 AGENT-02 铺路：确认 `_safe_execute_tool`(A-2.3) 为中间件唯一挂点
      - [ ] A-5.3 全仓 `pytest -q -m "not slow"` 通过并提交

### Phase 1 · 安全与正确性红线（P0）

- [ ] **[AGENT-02]** **工具执行中间件管线**（Phase 1 共同落点，先做）
  - **现状**：S3 + S4
  - **改法**：`tool_registry.py:94 execute()` 改为 `pre_execute → execute → post_execute` 责任链（dsh waterfall 语义：listener 必须调 `next()` 委托，不调即终止）。中间件顺序：审批闸门（AGENT-07）→ 失败熔断 → 结果分类（AGENT-09）→ 脱敏（AGENT-10）→ 缓存（现有）→ 限流（现有）
  - **验收**：同一工具连续 3 次 error 后本轮中止，熔断报告含 AGENTS.md §4.4 三要素（失败 Tool 名 / 错误原因 / 建议检查配置项）；**连带回填 S13 虚标的 TEST-11 四项断言**
- [ ] **[AGENT-07]** **逐笔交易审批闸门（fail-closed）**
  - **现状**：S8 —— `engine/gateway.py` 的三级锁是**配置态开关**，不是**逐笔确认**。AGENTS.md §6 要求的"二次确认"目前无机制承载
  - **改法**（参考 dsh `subsystems/approval.md`）：
    1. **闭集结果 + fail-closed**：`allowed-once | rejected | cancelled | unavailable`；应答方缺失 / 抛异常 / 返回不合规**一律 `unavailable` 并拒绝**，绝不因异常而放行
    2. **一次授权只授一次**：`allowed-once` 仅对被问的那一笔生效，禁止推广到后续订单
    3. **会话级策略** `ask` / `never`，策略变更本身作为会话事件落日志，重放可重建
    4. **审计对**：`approval/asked` + `approval/decided` 配对留痕，带独立的 approval id（不与 tool-call id 混用）
    5. **防漂移**：审批提示**不重新渲染一份订单参数**，而是引用已流式输出的那次 tool call（dsh 原话：避免"second copy that could drift"）—— 否则确认框里的价格与真正下单的价格可能不是同一份
  - **验收**：`REAL_TRADE_EXECUTE=true` 且策略 `ask` 时，每笔 BUY/SELL 均需一次显式放行；应答方异常时订单被拒而非放行；`never` 策略下确定性拒绝且不弹窗
- [ ] **[AGENT-08]** **Verify 阶段实装（零幻觉的结构保证）**
  - **现状**：S7 —— AGENTS.md §4.1 强制四段式，代码里 Verify 是空的，等于红线靠自觉
  - **改法**（参考 hermes `verify/` + `verification_evidence.py` + `verification_stop.py`）：工具返回后进入校验环节，按 AGENTS.md §4.1 校验非空 / 数值区间 / 时间戳新鲜度；校验产出**证据对象**并与结论绑定；未通过校验时**阻止进入 Output**（stop 而非降级编数）
  - **验收**：构造过期时间戳 / 空结果 / 越界数值三类桩数据，Agent 均不得输出结论数字；扩 `backend/routers/eval.py` 的 golden dataset 加入这三类反例
- [ ] **[AGENT-09]** **工具结果正交分类**
  - **现状**：S3 —— 现在只有"成功 / 异常"二元，`{"status":"error"}` 把限流、空结果、过期、真故障糊成一团
  - **改法**（dsh `defensive-patterns.md` 首条 + hermes `tool_result_classification.py`）：`success` / `empty` / `stale` / `rate_limited` / `error` **各自独立成标志，禁止嵌套在彼此的分支里**（原文：一个进程可以同时 timeout **且** exit 0）。限流不计入 AGENT-02 的失败熔断计数（与 AGENTS.md §10.8 一致）
  - **⭐ 直接价值**：这正是 `TODO-FUTU-INTERFACE-CAPABILITY.md` §0.5 记录的空结果语义陷阱 —— 盘后正常空 / 无数据 / 故障空三态目前不可分，会同时造成误报告警与把 0 当真数据
  - **⚠️ 前端契约（与 COPILOT-21 耦合，2026-08-21 记录）**：`tool_result` 事件外壳字段（`type/name/result`）受 AGENT-04 硬约束一字不改；但本任务把 `result` **内部**从 `{"status":"error"}` 改为正交独立标志（`success/empty/stale/rate_limited/error`）时，**必须保留 `error` 字段名**（或同步更新 `frontend/src/features/copilot/useChat.ts` onToolResult 的失败检测：现查 `r.status==='error' || r.error || r.failed`）。否则前端 COPILOT-21 的红色失败块「数据获取失败」会静默失效。验收时补充：用 mock 的 error 标志 result 断言前端失败块仍渲染。

### Phase 2 · 审计与可观测（P1）

- [ ] **[AGENT-01]** **会话事件日志（append-only）+「模型可见即已记录」不变量**
  - **现状**：S6
  - **改法**（参考 dsh `core/session` + `subsystems/session-projection.md` + `invariants.md`）：事件至少覆盖 `user/message`、`assistant/chunk`、`tool/call`、`tool/result`、`step/*`、`turn/*`、`approval/*`；模型可见消息由投影函数从日志派生；**压缩只影响投影，不删事件**；加运行时不变量断言（dsh 原话："Anything that reaches a model request must be reconstructable from the log"）
  - **量化价值**：AGENTS.md §3 要求每个数字可溯源到具体 Tool 返回。这条落地后，溯源从"靠自觉"变成"结构上做不到不溯源"，同时给事故复盘与合规审计提供完整回放
  - **验收**：任一历史会话可重放出当时模型看到的完整上下文；违反不变量即测试失败
- [ ] **[AGENT-10]** **密钥作用域与日志脱敏**
  - **现状**：S9 —— 交易系统持有 Futu 解锁密码、券商凭据、各数据源 API Key，却无任何脱敏层
  - **改法**：① 日志 / 遥测 / 轨迹上传三处统一脱敏（hermes `redact.py` + `monitoring/redaction.py`）② 密钥作用域化，按需注入而非全局可见（`secret_scope.py`）③ **子进程环境擦洗**：为 AGENT-05 的脚本沙箱预置，spawn 时 drop `*KEY*` / `*SECRET*` / `*TOKEN*` / `*PASSWORD*`（dsh `defensive-patterns.md` 原文规则）
  - **验收**：注入含密钥的工具入参 / 异常栈，日志与 SSE 输出中均不出现明文

### Phase 3 · 成本与效率（P1/P2）

- [ ] **[AGENT-03]** **工具集按场景分发**
  - **现状**：S5
  - **改法**（hermes `toolsets.py` + `toolset_distributions.py`）：按域分组 —— 行情盘口 / 基本面财务 / 宏观舆情 / 期权衍生 / 交易OMS / 检索知识库；默认集 + 按问题意图路由扩展
  - **验收**：单步注入 schema 数 ≤12；`backend/routers/eval.py` golden dataset 上工具误选率不劣化
- [ ] **[AGENT-11]** **Prompt 缓存边界 + Token 成本计量**
  - **现状**：S10
  - **改法**：① 稳定前缀（system prompt + 工具 schema）与易变后缀分离，显式管理缓存边界与作用域（hermes `prompt_cache_boundary.py` / `prompt_cache_scope.py`）—— 与 AGENT-03 天然协同：schema 子集稳定才谈得上命中 ② 按会话 / 按工具计量 token 与成本（`usage_pricing.py`、dsh `subsystems/token-meter.md`）③ DeepSeek `reasoning_content` 单独归口，不混入可见上下文（hermes `think_scrubber.py` / `reasoning_summaries.py`）
  - **验收**：缓存命中率与单会话成本进 Prometheus；同一问题重复提问的 input token 显著下降
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
- 规范：`AGENTS.md` §3 零幻觉 / §4.1 ReAct / §4.4 熔断 / §6 安全边界 / §10.8 限流感知 / §A.1 YAGNI
