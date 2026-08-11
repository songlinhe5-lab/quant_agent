# MEMORY - Quant Agent 架构决策与待办上下文

> 跨会话持久记忆。聚焦于「为何这么做」与「待推进项」，避免后续会话丢失上下文。

## 一、数据源依赖物理隔离（2026-08-06 决策）

**决策**：主服务与数据源子服务依赖树彻底分离。
- `backend/requirements.txt`：**禁止**包含任何第三方数据源 SDK（futu-api / tushare / akshare / yfinance）。仅保留 FastAPI/uvicorn/pydantic/sqlalchemy/httpx/redis/pandas/numpy/requests。
- `data_subservice/requirements.txt`：收口全部数据源 SDK（futu-api / tushare / akshare / yfinance / protobuf）+ 子服务框架。
- `pyproject.toml` 主 `[project.dependencies]` 已移除 yfinance；数据源 SDK 仅留在 `optional-dependencies` 的地域 extra：`datasource-cn`(Tushare+AKShare+YF) / `datasource-us`(YF+Futu+Finnhub) / `datasource-us-aux`(纯 YF)，供 `data_subservice/Dockerfile` `uv sync --extra ${DS_EXTRA}`（默认 `datasource-cn`）。
- **架构红线**：主服务运行时只经 `DataSourceRouter` 走 HTTP 调 `data_subservice`；禁止主服务 `import futu_api / tushare / akshare / yfinance`。

**验证**：两文件 install 均 satisfied；`backend.main` 导入显示「数据源不可用，走 HTTP 路由」；`data_subservice` 四 worker + app 全部 import ok。

**提交**：commit `67ee7f6`（backend/requirements.txt + data_subservice/requirements.txt + pyproject.toml）。

## 二、Phase 2.5 / 2.6 状态（已提交）

- Phase 2.5（整洁边界收口 BE-ARCH-01~04）：✅ 完成，文档 V5.2。
- Phase 2.6（数据源依赖抽离 + external 双模）：✅ 依赖抽离完成；⏸ **子服务部署运行** 待基础设施就绪。

## 三、Phase 3 已完成（2026-08-06）

**目标**：删主服务第二份 OpenD 实例 + 确认 data_subservice 已运行 + 迁移数据源单测到 data_subservice/tests。

**已落地改动**：
1. `backend/bootstrap/lifecycle.py`：移除启动期连接 Futu OpenD 的代码块（主服务不再启动 OpenD）。
2. `backend/workers/collectors/futu.py`：**删除**（它从 worker 进程启动第二份 OpenD）。
3. `backend/workers/collectors/__init__.py` + `collector_registry.py`：从采集器表移除 `futu` 定义与导入。
4. `backend/services/datasource/adapters/futu.py`：`DATASOURCE_FUTU_MODE` 默认 `internal` → **`external`**（主服务仅经 Router 走 HTTP 调子服务）。
5. **Futu 数据源单测迁移**：11 个 `backend/tests/test_futu_*.py` 移至 `data_subservice/tests/`，import 由 `backend.services.futu` 改写为 `data_subservice.futu_src`；其中 `test_futu_trade_handler.py` 2 处断言按子服务 `query_order` 实际（仅日志通知、不 spawn 任务）对齐。
6. `backend/tests/test_collector_registry.py`：移除 futu collector 相关断言（期望集、启停矩阵、任务数 4→3）。

**验证**：
- `backend.main` 导入 OK；`data_subservice` 在 `DS_CAPABILITIES=futu` 下能导入 `app` 与 `futu_src.ConnectionManager`（子服务为唯一 OpenD 宿主）。
- `data_subservice/tests/test_futu_*.py`：**242 passed**。
- `backend/tests/test_collector_registry.py`：17 passed。
- 主服务 `test_market_engine.py` / `test_kline_warehouse.py` 等回归无新增失败。

**预存失败（非本次引入，已 git stash 确认）**：
- `backend/tests/test_data_source_router_futu.py::test_remote_success_maps_action`（`KeyError: last_price`，envelope 归一化断言偏差）。
- `backend/tests/test_kline_warehouse.py` 5 例（`kline_warehouse.data_source_router` 属性缺失 + 信封处理）。
- `backend/tests/test_futu_adapter.py::test_fetch_option_chain_not_connected_returns_error_no_mock`（adapter 行为偏差）。
- 以上为存量技术债，Phase 3 未触碰，后续单独修。

**保留项（未删）**：
- `backend/services/futu/` 包仍保留作 `DATASOURCE_FUTU_MODE=internal` 兜底（被 legacy_market_data.futu / legacy_broker / market_engine._get_futu_service / adapters/futu 引用）。
- `backend/tests/test_futu_adapter.py` + `test_futu_adapter_dispatch.py` 仍测试 `backend.adapters.futu.futu_adapter`（主服务 DataSourceInterface 适配器层，属集成适配非源 SDK），未迁移。

## 四、Phase 4 启动（2026-08-06 决策 · V5.4）

**🔴 子服务职责红线（用户拍板，须固化进 vibe coding 规则）**：
- `data_subservice` **只负责**：① 数据源连接（SDK/WS/OpenD）② 连接与采集保障监控（限流/熔断/健康/自愈/credit 对账）③ 对外 HTTP API（`/ds/{source}/{action}` + `/metrics` Prometheus）。
- **禁止**在子服务写任何业务逻辑/业务编排（LLM 秒评、通知、分片、宏观聚合、财报解读、信号生成）——这些依赖 backend 内部模块，违反子服务「禁 import backend」红线。
- 判定准则：**「数据获取 + 保障监控」属子服务；「数据消费后的业务加工」属主服务**。

**用户拍板结论**：
1. finnhub：数据源获取/保障/监控逻辑下沉 data_subservice；LLM 秒评+通知+分片+宏观保留主服务。
2. fmp：**整体下沉**（含 800 行 daemon + system.py credit 观测改经 HTTP 拉子服务 /metrics）。
3. akshare/yfinance：先核查再动手（yfinance collector 为路由空壳可删；akshare 北京 VPS 市场级资金流 daemon 需子服务补采集）。

**已落地（本次 commit）**：
- `backend/workers/macro/alert_daemon.py`：从 `workers/market/daemon.py` 抽出 `_macro_alert_daemon`（实际用 AKShare+FRED，与 Finnhub 无关），独立化后关闭 COLLECTOR_FINNHUB 不影响宏观告警。
- `backend/bootstrap/lifecycle.py`：删 FMP 主服务守护启动块（fmp 整体下沉）。
- `docs/03` §4.4 + 变更日志 V5.4：固化子服务职责红线。
- 相关测试 2 件（`test_finnhub_service_daemon.py` / `test_services_market_daemon_coverage.py`）改引用 `alert_daemon.macro_alert_daemon`。

**已落地（2026-08-07 全远程重构）**：
- 所有数据源仅远程：`Futu/FMP/Finnhub/FRED/DBnomics/RBI/Tavily/Bocha/Jina` 连接层全部下沉 data_subservice（`_internal/*` + 各 `*_worker.py`），主服务经 `DataSourceRouter` HTTP 代理，**不再持有本地 SDK / WS 订阅 / 直连外部 API**。
- `backend/services/datasource/router.py`：移除 `_call_local_*` 本地降级通道；`fetch_*` 全部 remote-only；新增 `fetch_finnhub/fred/dbnomics/rbi/search`。
- 适配器 `futu/fmp/finnhub/macro/search/akshare` 改为经 router 调用（mode=remote）。Finnhub WS tick 层已弃用，quote 走 REST 快照。
- 子服务 `main.fetch_data` 新增 finnhub/fred/dbnomics/rbi/search 源路由；`DS_CAPABILITIES` 声明能力（主节点可声明 `futu,fmp,finnhub,fred,dbnomics,rbi,tavily,bocha,jina`）。
- 外部搜索/抓取 API Key 由承载对应能力的子服务节点持有，主服务不再直连 api.tavily.com / api.bochaai.com / r.jina.ai。

**待办（后续优化，非阻断）**：
- akshare 市场级资金流（南向/北向/港股通）定时采集补进 data_subservice/akshare_worker.py（当前已支持 FUND_FLOW/ECONOMIC_CALENDAR）。
- FMP `/metrics` 暴露 Prometheus 指标 + credit 看板经 HTTP（子服务已下沉，指标待补齐）。

## 四、相关文件索引

- 架构文档：`docs/03. 后端架构与执行引擎.md`（V5.2，§4.4 依赖收口红线）
- 数据源细规：`docs/14. 分布式数据源服务架构.md`（双模 / HTTP 协议 / Registry）
- 采集器映射：`docs/06`（四节点 Compose）、`AGENTS.md` §9（架构概述）

## 五、代码经济性准则（Ponytail · Lazy Senior Dev Mode，2026-08-09）

**来源**：`AGENTS.md` §10（V2.6）。所有 agent 在动笔前必读，硬规则下沉如下：

**决策阶梯（动手前逐层自问）**：
1. 真需要造吗？(YAGNI) → 2. 仓库里是否已有？复用别重写 → 3. 标准库能否做？→ 4. 平台能力覆盖？→ 5. 已装依赖能解？→ 6. 能一行吗？→ 7. 才写最小代码。
**理解问题优先于爬梯**：先读题、端到端 trace 真实调用流，再选阶梯。看不懂的小 diff = 披着效率外衣的懒。

**Bug 修复 = 根因**：Grep 你 touched 函数的每一个调用方，在共享函数修一次（一处 guard 比每调用方各加一处更小）；只修 ticket 点名路径会留兄弟调用方仍坏。

**硬规则**：不造未要求抽象 / 能避免不引新依赖 / 不写没人要的样板 / **删多于加·无聊优于花哨·文件越少越好** / 最短可工作 diff 但须位置正确 / 复杂需求先质疑「真需要 X 还是 Y 已覆盖」/ 同体积 stdlib 选边界正确那个 / 主动砍角落的简化用 `ponytail:` 注释标天花板+升级路径。

**绝不含糊**：信任边界输入校验、防数据丢失的错误处理、安全/无障碍、真实硬件校准（时钟漂移·传感器读偏）、显式要求的事。

**留下一个可运行检查**：非平凡逻辑留一个 assert 自检 demo 或一个小测试文件（无框架、无 fixture）；纯一行 trivial 无需测试。

## 六、data-subservice 镜像重建部署铁律（2026-08-11 实战踩坑固化）

**背景**：node-s1 排障 17 分钟，根因全在部署链路，不在应用代码（常驻进程 futu 从头到尾 CONNECTED）。

**重建 `:us` 镜像（主节点含 futu）的唯一正确命令**：
```bash
docker build -f data_subservice/Dockerfile --build-arg DS_EXTRA=datasource-us \
  -t ghcr.io/songlinhe5-lab/quant_agent-data-subservice:us .
```
对应地域 extra：`datasource-us`(主节点 YF+Futu+Finnhub) / `datasource-us-aux`(纯 YF) / `datasource-cn`(Tushare+AKShare+YF)。Dockerfile 默认 `DS_EXTRA=datasource-cn`，**漏传 build-arg 即缺 futu 模块** → `No module named 'futu'`。

**三个必踩易错点（一次性记死）**：
1. **extra 错胎**：必须 `--build-arg DS_EXTRA=datasource-us`，否则默认 cn 缺 futu。
2. **镜像 tag 错位**：compose 引用 `ghcr.io/songlinhe5-lab/quant_agent-data-subservice:us`（CI 会 sed 成私有 registry）。本地 build 必须打**同名 tag**，打 `127.0.0.1:5000/...` 无效——`up` 仍拉 ghcr 旧镜像。
3. **env 漏传**：`up` 必须 `--env-file .env.data-node`（放 `up` 前，是 compose global flag），否则 `DS_CAPABILITIES`/`FUTU_HOST` 缺失 → futu 分支不拉起。

**观察方式红线（防虚假 DISCONNECTED 误判）**：
- ❌ 禁止 `docker exec ... python3 -c "import ...futu_service; print(futu_service.quote_ctx)"` 判断状态——`exec` 是全新进程，读到的是未 connect 的全新单例（quote_ctx=None），与常驻进程无关。
- ✅ 直查常驻进程暴露的端点：`GET /futu/status`（返回真实 status/connected/target/error_msg）或 `GET /health`（含 `futu` 字段）。PR #282 已实装。

**验证连通性最终命令**：
```bash
docker exec quant-agent-node-s1-data-subservice-1 sh -c 'python3 -c "import urllib.request; print(urllib.request.urlopen(\"http://127.0.0.1:8001/futu/status\").read().decode())"'
# 预期: {"status":"CONNECTED","connected":true,"target":"100.102.223.44:11111","error_msg":""}
```不带校验的懒代码是半成品。
