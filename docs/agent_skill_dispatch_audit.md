# quant_agent 系统 Agents / Skill 调度逻辑 & codex harness 合入核查

> 核查时间：2026-08-21 | 视角：代码库架构调研（非工作台搭建）
> 核查方式：Grep + Read 全仓代码/文档，逐项按证据定位

---

## 一、核心结论（先说结果）

| 问题 | 结论 | 一句话 |
|---|---|---|
| 系统 agents 调度逻辑在哪 | 已交付 | 专家团多智能体引擎 `backend/services/expert_team/`，三轮辩论协议，Phase 1 完成（38/38 测试通过） |
| skill 调度逻辑是否独立存在 | **不存在独立实体** | 全仓无 skill 引擎；Hermes 用的是 **tool 注册表**模式（37 个工具），"skill" 仅是文档泛指 |
| codex 是否合入系统 | **未合入** | "codex" 仅作「外部写码 Agent」统称出现，无任何 codex 运行时/SDK |
| deepseek-harness 是否合入系统 | **未合入（且明确不引入）** | SSOT 结论：两者均不引入，只借架构范式；"harness" 在全仓仅 2 处，皆非 deepseek-harness |

---

## 二、系统 Agents 调度逻辑（已落地）

### 2.1 两套并行的 Agent 体系

| 体系 | 模式 | 代码位置 | 状态 |
|---|---|---|---|
| **Hermes Agent** | 1 Agent × N Tools × 1 结论（单 Agent ReAct） | `hermes_agent/agent.py`（1151 行）、`tool_registry.py`、`tools/`（37 工具） | 运行中 |
| **Expert Team（专家团）** | N Experts × 共享数据 × 辩论 × 1 首席收敛 | `backend/services/expert_team/` | Phase 1 已交付 |

> 结论（来自 `docs/21` §一、§九）：两者**不复用**。Hermes 是单 Agent ReAct；Expert Team 是多 Agent 辩论。Hermes 在「复杂问题」时可**升级**到专家团（`docs/21` §十一："Hermes Agent 复杂问题自动升级至专家团"），但代码链路未在 `hermes_agent/agent.py` 中直接发现引用（grep "expert_team" 无匹配），升级接口应走后端 `backend/routers/expert_team.py` 由前端/上层触发。

### 2.2 专家团调度细节（`docs/21`）

- **三轮混合协议**：
  - Round 1 独立研判（Parallel，互不可见防锚定）
  - Round 2 交叉辩论（Adversarial，自己全文 + 他人摘要）
  - Round 3 首席收敛（Synthesis，FLAGSHIP 模型）
- **17 位专家**：分析师团队 7 / 研究员 2 / 交易员 1 / 风控 2 / 管理层 1 / 代码域 4
- **4 个场景模板**：`financial_research`(5) / `full_investment`(11) / `trading_decision`(5) / `code_review`(4)
- **核心文件**：
  - `orchestrator.py` —— 三轮协议编排引擎（核心）
  - `expert_registry.py` —— 专家注册表 + 场景模板 + 团队分组
  - `data_collector.py` —— 共享数据包采集（复用 ToolRegistry，一次采集全员复用）
  - `expert_team_service.py` —— 对外入口 + 会话管理
  - `models.py` —— 7 个 Pydantic 核心类
- **API**：`backend/routers/expert_team.py`，4 端点（SSE 流式 analyze / scenarios / sessions / sessions/{id}）
- **复用**：LLMRouter（专家 STANDARD / 首席 FLAGSHIP）、ToolRegistry、Redis（Phase 2 迁会话存储）

---

## 三、Skill 调度逻辑核查

### 3.1 全仓无任何独立 "skill" 引擎

- `docs/02. Vibe Coding与AI工程规范.md` 全文搜 `skill|技能` → **0 匹配**（该规范完全不涉及 skill 调度）。
- `backend/` 搜 `skill` 仅命中 2 个文件，且均为**误匹配**：
  - `test_services_akshare_quote_coverage.py` 里的 `_QuoteHarness` 类（pytest 测试夹具，非 skill）
  - `test_router_oms.py`（上下文无关命中）
- `hermes_agent/agent.py` 搜 `skill|dispatch|subagent|专家团` → **0 匹配**（Hermes 主循环里没有 skill 路由、没有子代理、没有直接调专家团）。
- Hermes 的「能力扩展」机制是 **Tool 注册表**：`tool_registry.py` 的 `get_all_schemas()` 每步全量注入 37 个工具 schema 给 LLM（`docs/TODO-AGENT-ARCH.md` S5 短板），**没有按场景分发的 skill/tools 子集机制**（AGENT-03 待做）。

### 3.2 结论

仓库里 **"skill" 一词只作为文档泛指**（如 AGENTS.md 提到"技能闭环"），**没有可运行的 skill 调度子系统**。能力分发靠 tool 注册表 + LLM 自主选工具，而非显式 skill dispatch。

---

## 四、codex / harness 是否合入系统

### 4.1 "codex" 全仓出现位置（全部为非运行时泛指）

| 位置 | 内容 | 性质 |
|---|---|---|
| `AGENTS.md:3` | "受众：Cursor / Claude Code / **Codex** / Copilot 等**写仓库代码**的 Agent" | 把 codex 列为外部编码 Agent 之一，**非依赖** |
| `docs/02:26` | "多 IDE（Claude Code / **Codex** / Copilot）只保证读取根目录 AGENTS.md" | 同上，泛指 |

→ **无任何 `codex` SDK / 运行时 / 配置文件 / import**。codex 未被合入。

### 4.2 "harness" 全仓出现位置（仅 2 处，皆非 deepseek-harness）

| 位置 | 内容 | 性质 |
|---|---|---|
| `docs/TODO-AGENT-ARCH.md` / `docs/TODO.md` / `docs/TODO-backend.md` | 对标 `deepseek-ai/deepseek-harness` | **架构参考对象，明确不引入** |
| `backend/tests/test_services_akshare_quote_coverage.py` | 类 `_QuoteHarness(QuoteMixin)` | pytest 测试夹具，与 deepseek 无关 |

### 4.3 决策依据（SSOT = `docs/TODO-AGENT-ARCH.md`）

> 结论：**不引入，只借范式**。

| 项目 | 能否直接用 | 判据（原文） |
|---|---|---|
| hermes-agent | 否 | 是**产品**不是库；`agent/` 200+ 模块含 billing/browser/image_gen 等，与量化无关；换它等于连交付模型一起换 |
| deepseek-harness | 否（且现在不该碰） | TS/Node monorepo → 后端引第二运行时，撞 Python 技术栈锁定；**建库 3 天**、developer preview 会有破坏性变更 |

**且 §六红线显式「明确不借」**：
- 自我进化技能循环（`skill_*.py` / `learning_graph.py`）—— Agent 自主写代码并触达交易工具 = `REAL_TRADE_EXECUTE` 与逐笔审批形同虚设 → **永不进交易路径**
- 多平台 gateway、billing、browser_provider、image_gen、LSP、Cordis 插件热更新全套

### 4.4 目前借用了哪些范式（规划中，尚未全部落地）

`docs/TODO-AGENT-ARCH.md` 的 AGENT-01~14 任务，对标 hermes-agent / deepseek-harness 的**具体机制**（非依赖）：
- AGENT-02 工具执行 waterfall 中间件（pre→execute→post）
- AGENT-07 逐笔审批 seam（fail-closed）
- AGENT-08 Verify 阶段 + 证据留痕
- AGENT-09 工具结果正交分类
- AGENT-01 append-only 会话事件日志
- AGENT-10 密钥脱敏 + 环境擦洗
- AGENT-11 Prompt 缓存边界 + token 计量
- AGENT-03 工具集按场景分发（= skill 分发思想的平替）
- AGENT-13 把自家工具暴露为 MCP Server
- AGENT-14 子代理并行编排

→ 即：**借鉴机制，不引运行时**。codex / deepseek-harness 的代码从未进仓库。

---

## 五、给你的下一步建议

1. **若想做"skill 分发"**：无需引入外部 skill 框架，直接在 Hermes 的 `tool_registry.py` 上做 AGENT-03（工具集按场景分发）即可，与范式借用路线一致。
2. **若担心"codex 是否已偷偷合入"**：可放心，全仓无任何 codex 依赖；如需硬保证，可加一条 CI 检查（grep `codex` import / `deepseek-harness` 依赖）防回归。
3. **专家团升级链路待补**：`docs/21` 声称 Hermes 可自动升级到专家团，但 `hermes_agent/agent.py` 未直接引用 `expert_team`，建议核实升级是在前端/上层 router 触发还是确有缺口。

---

## 附：证据文件清单

- `docs/21. 专家团多智能体协作系统.md`（专家团架构 SSOT）
- `docs/TODO-AGENT-ARCH.md`（AGENT 系列 SSOT，含 harness 决策）
- `docs/TODO.md` / `docs/TODO-backend.md`（指针）
- `AGENTS.md` / `docs/02. Vibe Coding与AI工程规范.md`（codex 泛指出处）
- `hermes_agent/agent.py` / `hermes_agent/tool_registry.py` / `hermes_agent/tools/`（Hermes 工具模式）
- `backend/services/expert_team/`（专家团代码）
- `backend/tests/test_services_akshare_quote_coverage.py`（_QuoteHarness 测试夹具）
