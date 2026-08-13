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

## 七、asyncio.create_task 必须持有强引用（2026-08-12 实战坑 · PR #294）

**背景**：node-s1 部署新代码后子服务常驻进程 `/futu/status` 偶发 `CONNECTED` 但主服务 `/quote` 仍全部失败。深入核查发现 `futu.status` 偶发 `CONNECTED` 只是 startup 残留快照，**看门狗实际从未运行**（`running=False`、`total_reconnects=0`），一旦初始 `connect()` 因 OpenD 会话抖动未建立即永久 `DISCONNECTED`，无自愈。

**🔴 根因**：`data_subservice/main.py` 原代码
```python
asyncio.create_task(FutuWatchdog(futu_service).start())  # 无强引用持有
```
`asyncio.create_task` 返回的 task 若无任何变量/容器引用，会在下一次 GC 时被回收并取消。看门狗协程因此静默停摆——这不是「没启动」，而是「启动即被 GC 掉」。

**✅ 修复（commit `7e21f27` / PR #294）**：
1. `main.py`：用 `get_watchdog(futu_service)` 单例 + 全局 `_futu_watchdog_task` 持有 task（与既有 `_heartbeat_task` 同模式），`shutdown_event` 优雅 cancel。
2. `watchdog.py`：`start()` 入循环前先主动补连一次（`_do_reconnect`），即便初始建连失败也能立即自愈，不等一个退避周期。
3. `connect()` 本身幂等（双重检查已连则跳过），补连与 startup 建连不冲突。

**🔧 通用规则（固化进 vibe coding）**：凡 `asyncio.create_task(...)` 启动长生命周期后台协程（watchdog / heartbeat / 推送桥接 / 采集循环），**必须**用一个模块级全局变量或对象属性持有 task 引用，绝不能裸 `asyncio.create_task(...)` 丢弃返回值。短生命周期、函数内 await 完成的 task 不受此限。

**观察方式红线补充**：
- ❌ 不要用 `docker exec ... python3 -c "import ...get_watchdog; print(get_watchdog().stats)"` 判断——`exec` 是新进程，单例与常驻进程不同，且新进程未 start 过 watchdog，`running=False` 是假象。
- ✅ 经常驻进程暴露端点或日志判断：`GET /futu/status`（真实 status/connected）+ 启动日志应出现 `🐕 看门狗守护进程启动`；重连行为看 `GET /metrics` 的 `futu_reconnect_total` 计数。

## 八、futu /quote 主服务探针未恢复（2026-08-12 · Issue #289 衍生卡点）

**背景**：Layer 1~5 全部闭环（PR #286~#291），node-s1 已确认部署新代码（`data_subservice/futu_src/service.py` 的 `status` 已改 property 代理 `conn_mgr.status`；经 HTTP `/futu/status` 验证子服务常驻进程 `CONNECTED`，OpenD 11111 TCP ESTABLISHED 通）。但主服务 `/quote?ticker=HK.00700` **仍持续 `No healthy Futu remote node`**，即使主服务 force-recreate 重启后亦然。

**🔴 实测根因（2026-08-12 node-s1 直连核查，已定位）**：**不是代码 bug，是部署网络拓扑错误。**
- 主服务运行时 `FUTU_REMOTE_URL=http://100.102.223.44:8001`（公网 IP，来自 `.env`）。
- `GET /api/v1/market/futu/status` → `{"status":"REMOTE","reachable":false}`：主服务**容器内**访问公网 IP:8001 不可达。
- `GET /api/v1/datasource/futu/health` → `status=stale, connected=false, health_error=error_count=3`：futu 节点已熔断，自愈探针同样走不通公网 → 永不复位。
- 子服务容器内 `/health` → `futu: CONNECTED`（OpenD 正常，TCP 11111 通）。
- **网络核查铁证**：
  - 主服务容器 → 网络 `quant-agent-master_quant-internal`（IP 172.18.0.6）
  - 子服务容器 → 网络 `quant-agent-node-s1_quant-net`（IP 172.19.0.2）
  - **两容器在不同 compose 项目、不同 docker 网络**（master vs node-s1）
  - 子服务 `ports` 仅 `8001/tcp -> 100.102.223.44:8001`（公网），宿主 `127.0.0.1:8001` 为 CLOSED
- **结论**：主服务只能用公网 IP 访问子服务，但容器访问公网 IP 回环路径在 VPS 不通 → 持续 `reachable:false` → 熔断 → 探针失败 → 永不恢复。
- **端点路径备忘**：主服务 API 全局前缀 `/api/v1`（health-overview 真实路径 `/api/v1/datasource/health-overview`，非 `/health-overview`）。

**已排除（代码层全部闭环，问题在部署层）**：
- 子服务 futu 会话未初始化（PR #290 后 `/futu/status` 已 CONNECTED）。
- compose `environment:` 覆盖 `.env`（PR #287 已删）。
- node-s1 复用旧 `:us` 镜像（PR #291 已修，`status is property: True` 已确认）。
- 探针逻辑 bug / `/health-overview` 接口异常（实测接口正常返回 JSON，前缀 `/api/v1`）。

**修复方向（方案待用户拍板，Issue #292 已记）**：
- **方案 A（推荐）**：主服务 + 子服务并入同一 compose 网络；子服务 `ports` 改 `127.0.0.1:8001:8001`；`FUTU_REMOTE_URL=http://data-subservice:8001`（服务名互联），彻底不依赖公网 IP。
- **方案 B（最小改动）**：子服务端口补映射 `127.0.0.1:8001` + 两容器建共享网络，主服务改走宿主网关/服务名。

**待办**：
- [x] 创建 Issue #292 + 同步实测根因。
- [x] 经 HTTP 取 `futu` 节点真实状态（status=stale/error_count=3）。
- [x] 主服务容器内确认 `FUTU_REMOTE_URL=http://100.102.223.44:8001`。
- [x] **方案 A 已实施**：node-s1 子服务 `ports` 改 `127.0.0.1:8001:8001`，主服务 `FUTU_REMOTE_URL=http://data-subservice:8001`（服务名互联）；并修掉 VPS 上被救急改坏的中转镜像地址（见第八章）。详见 2026-08-12 后续会话。
- [x] **watchdog 自愈已修复（PR #294 / commit `7e21f27`，独立于网络拓扑）**：`main.py` 用全局 `_futu_watchdog_task` 持有 task 强引用 + `watchdog.start()` 入循环前主动补连。`/futu/status` 偶发 `CONNECTED` 实为 startup 残留快照、看门狗此前从未运行的根因已闭环。重启 `data-subservice` 容器后生效。

## 九、子服务 HMAC 403 排查踩坑（2026-08-13 实战 · node-bj）

**现象**：主服务 `DataSourceRouter` 调 BJ 子服务 `POST /api/v1/data` 持续返回 **403**，但 `/health` 正常 200。日志里 200 与 403 交替（200 来自其他健康节点，403 全是 BJ）。

**`verify_hmac`（`data_subservice/main.py:71-87`）三道 403 关卡**：
1. 缺 `X-Timestamp` / `X-Signature` 头 → `缺少 HMAC 请求头`
2. `abs(time.time() - int(x_timestamp)) > 300` → `请求时间戳过期`（**先于签名比对执行**）
3. `hmac.compare_digest` 失败 → `HMAC 签名校验失败`

**本次真因（两连击）**：
- **根因 1 · example 占位符未替换**：BJ 的 `.env.data-node` 第 56 行把模板里的占位符 `<与主节点一致的 HMAC 密钥>` **原样照搬**，没换成真实哈希。致容器 `DATA_SOURCE_HMAC_SECRET` 字面量 = 那段中文占位符，与主服务 `b6fb201e...` 不符 → 签名校验失败 → 403。
  - ⚠️ `docker exec ... printenv` 回显的 `<与主节点一致的 HMAC 密钥>` 不是打码，是**配置里真实的字面量**——第一眼极易误判为"密钥一致"。
- **根因 2 · `.env` 末尾缺换行导致 `echo >>` 拼接污染**：修复时 `echo '...' >> .env.data-node`，但文件末行 `TZ=<时区>` 后无换行，追加内容被拼到同一条 → 生成坏行 `TZ=<时区>DATA_SOURCE_HMAC_SECRET=b6fb...`。dotenv 把整串解析成 `TZ` 的值，`DATA_SOURCE_HMAC_SECRET` 反未被定义 → 容器回退代码默认 `change-me-in-prod` → 403 依旧。
  - 此坑隐蔽：肉眼 `grep` 能看到 `b6fb...` 字符串，但它在 `TZ=` 行里，变量根本没生效。

**排查顺序固化（别再空推）**：
1. `docker exec <容器> printenv DATA_SOURCE_HMAC_SECRET` —— 看**真实哈希**还是占位符/默认 `change-me-in-prod`。
2. `grep -n "DATA_SOURCE_HMAC_SECRET" .env.data-node` —— 确认是否独立成行、无拼接污染（警惕与上一行粘连的坏行）。
3. 主从节点分别 `date +%s` 互比，差须 < 300s（时差也会 403，且早于签名比对）。
4. 密钥一致、时差正常、IP 白名单（`DATA_SOURCE_ALLOWED_IPS` 在代码里**无引用**，不影响）仍 403 → 抓子服务 403 的 `detail` 文案定性。

**修复铁律**：
- slave 节点 `.env.data-node` 必须含 `DATA_SOURCE_HMAC_SECRET=<真实哈希>`，且与主节点 `.env` 的 `DATA_SOURCE_HMAC_SECRET` **逐字符一致**。
- `echo 'KEY=val' >> file` 前先 `tail -c1 file | read -r _ || echo >> file` 补换行，或干脆用 `printf 'KEY=val\n' >> file` 避免拼接污染。
- 改完 `docker compose -f docker-compose.node-<节点>.yml --env-file .env.data-node up -d` 重启，再 `printenv` 复核。

**已沉淀文档**：`DEPLOYMENT_CHECKLIST.md` 故障排查「问题 4」、`.env.data-node.example` HMAC/TZ 注释（commit `f3a6ccd`）。

## 八、容器隔离下的网络访问模型（2026-08-12 固化）

**核心原则**：主服务与子服务保持 Docker bridge 隔离（**不用 `network_mode: host`**），同机走 Docker 服务名 DNS，跨机走 Tailscale + HMAC。host 化虽能让子服务用 `127.0.0.1` 连 OpenD，但牺牲隔离、暴露端口、且破坏服务名互联，得不偿失——当前 `:us` 镜像 + `host.docker.internal` 网关映射已稳定 `CONNECTED`。

### 8.1 同 VPS 内访问（容器 ↔ 容器）

- **机制**：两个容器连到**同一用户自定义 bridge 网络**，Docker 内置 DNS 把对方**服务名/容器名**解析成容器 IP，直接互通，无需出宿主、无需知道 IP。
- **当前 s1 实现**：
  - `quant-internal` 网络（`172.18.0.0/16`）由 master 项目创建，node-s1 用 `external: true` + `name: quant-agent-master_quant-internal` 外部引用，实现**跨 compose 项目同网**。
  - 主服务 → 子服务：`http://data-subservice:8001` ✅
  - 子服务 → 主服务（回调）：`http://quant-agent:8000` ✅
- **容器内访问宿主进程（OpenD/Redis）**：
  - 容器内 `127.0.0.1` 是容器自身，**不能**连宿主 OpenD。
  - 须用 `host.docker.internal`（compose `extra_hosts: host.docker.internal:host-gateway` 映射到宿主网关 `172.17.0.1`；s1 实测用 `172.19.0.1`）。
  - **前置条件**：宿主进程必须监听 `0.0.0.0` 或对应网关 IP，不能只绑 `127.0.0.1`（否则网关来的连接 `Connection refused`）。OpenD 当前监听 `0.0.0.0:11111` ✅。

### 8.2 跨 VPS 访问（VPS_A 容器 ↔ VPS_B 服务）

- **机制**：无 Docker 内部 DNS，走 **Tailscale 虚拟组网 + HMAC 签名鉴权**。
- **拓扑**：各 VPS 有 `tailscale0` 接口（如 S1=`100.102.223.44`、BJ=`100.124.178.96`），流量经 Tailscale 加密隧道，不经公网裸奔。
- **寻址**：用 Tailscale IP，不能用服务名（服务名只在本机有效）。
  - S1 主服务 → BJ 子服务（A股）：`TUSHARE_REMOTE_URL=http://100.124.178.96:8001` / `AKSHARE_REMOTE_URL=...`
  - S1 主服务 → S2/S3/S4 辅助 YF：`YF_BACKUP_NODE_URL=http://100.x.x.x:8001`
  - 每个请求带 `DATA_SOURCE_HMAC_SECRET` 签名，远端校验，防伪造。
- **北京节点中转 registry（镜像分发通道，非运行时流量）**：
  - BJ 境内直拉 GHCR 不稳，S1 部署私有 `registry:2`（监听 `127.0.0.1:5000` + Tailscale IP:5000）。
  - CI 推送 `:cn` 镜像到 S1 registry；BJ compose 写 `127.0.0.1:5000/...:cn`，经 **Tailscale 内网**拉取。
  - **铁律**：中转 registry **只缓存 `:cn`**（BJ 用）；主服务 (`quant_agent:latest`) 与 S1 子服务 (`:us`)、S2/S3/S4 (`:us-aux`) 均走 GHCR 直连，不进中转。

### 8.3 对比速查

| 维度 | 同 VPS 内 | 跨 VPS |
|---|---|---|
| 寻址 | Docker 服务名 DNS (`data-subservice:8001`) | Tailscale IP (`100.x.x.x:8001`) |
| 网络层 | 宿主 bridge (172.18/172.19) | Tailscale 加密隧道 |
| 是否出宿主 | 否（容器间直连） | 是（出 tailscale0） |
| 鉴权 | 同网默认可信（HMAC 仍校验） | HMAC 签名必须 |
| 配置来源 | compose `networks` + 共享外部网络 | `.env` 的 `*_REMOTE_URL` |

### 8.4 `network_mode: host` 弊端备忘（已否决方案）

- 两容器都 host 后 `127.0.0.1` 即宿主，localhost 全通；
- 但：① 失去网络隔离（端口直接绑宿主所有网卡，SEC-16 红线倒退）② 端口冲突风险（无 NAT 隔离）③ Docker 服务名 DNS 失效（所有 `*_REMOTE_URL` 改 `127.0.0.1`）④ compose `networks`/`extra_hosts`/`ports` 映射全失效 ⑤ 仅解决同机，跨机仍要 Tailscale ⑥ 与 CI 模板（curl 仓库 compose 覆盖）冲突。
- 仅当子服务用 `127.0.0.1` 连 OpenD 的单点诉求成立，但该诉求已由 `:us` 镜像 + `host.docker.internal` 网关达成，**无需 host 化**。

## 十、「测试连接」失联认知修正（2026-08-13 · 熔断假象根因）

**🔴 纠正一个误导：futu 与 finnhub 的 `health()` 实现几乎一字不差，都是被动探测，不是「finnhub 被动 / futu 靠 WS」的区别。**

- 两者 `health()` 均：`connected = node.status == "healthy"`，只看 `DataSourceRouter` 节点注册表的 `node.status`，**都不消耗真实配额、都不依赖 WS 连接状态**（Finnhub WS tick 层已弃用，quote 走 REST 快照；futu 同样经 router HTTP 代理）。
- 适配器代码对照：`backend/services/datasource/adapters/futu.py:87` 与 `backend/services/datasource/adapters/finnhub.py:67` 逻辑一致。

**实测「点全部测试连接后 futu 失联、finnhub 一直通」的真正原因 = 节点稳定性差异，而非探测方式：**
- finnhub：`DS_CAPABILITIES` 在主节点本地 data_subservice 跑，节点 `finnhub_master` 由本地子服务心跳注册，主服务常驻稳定 → `node.status` 几乎恒 `healthy`。
- futu：`futu_master` 节点依赖**主宿主机 Futu OpenD（TCP 11111）+ 经 router HTTP 代理的子服务**。`test-link` 的真实主动探测 `source.fetch("QUOTE", ...)` 打到 futu 上游，一旦风暴/抖动把 `futu_master` 节点的 `error_count` 打高或心跳失败 → `node.status=unhealthy` → 连带 `health()` 返回 `connected=False` → 看板集体失联。
- 即：两者被动探测逻辑相同；失联差异来自**节点承载的上游稳定性**，finnhub 上游额度宽松且本地稳定，futu 上游（OpenD/子服务）易在探测风暴下被拖垮。

**修复（commit 见 git log · 本次会话）**：
- 后端 `backend/routers/datasource.py` `test_datasource_link`：加全局最小触发间隔（`TEST_LINK_MIN_INTERVAL_S` 默认 1.5s）+ per-source 串行锁（`asyncio.Lock`），抑制「全部测试连接」并发风暴；并**尊重 throttler 退避**，退避期内直接返回冷却状态、不发起真实请求（避免雪上加霜）。
- 前端 `frontend/src/features/data-center/datasource-health.tsx`：新增 `testingAll` 全局锁，全部测试连接过程显示「全部测试中…」并禁用所有按钮，且改为**串行触发**，全局进行中禁止单独点「测试连接」。

**勿再犯**：不要把 finnhub 当「被动探测豁免」特例去改 `test-link` 的 futu 分支——问题在「主动探测风暴拖垮节点」，应在 router/限流层统一防护（已做），而非给某源开例外。

## 十一、前端 Cloudflare Pages 部署变量铁律（2026-08-14 实战 · token 频繁踢人 + 大盘空白同根因）

**🔴 现象闭环**：用户访问 `quant.stephenhe.com`（Cloudflare Pages 前端），API 在 `quant-api.stephenhe.com`（独立子域）。两子域在 cookie 语境下是 **cross-site**。

**构建环境变量 `VITE_API_BASE_URL` 必须等于**：
```
https://quant-api.stephenhe.com/api/v1
```
**绝不能**写成 `https://quant.stephenhe.com/api/v1`（漏 `api-` 子域）。

**为什么这是「被踢回登录 + 大盘面板空白」的同一个根因**：
- 前端 `api-client.ts` 的 `API_BASE_URL` = `VITE_API_BASE_URL`，所有 REST 与 `/auth/refresh` 都拼这个地址。
- 若配成 `quant.stephenhe.com`，则：
  - REST 业务请求 → 打到被 Cloudflare 拦截的域名（返回 845 字节 HTML 拦截页）→ dashboard 空白。
  - `doRefreshToken` 的 `/auth/refresh` → 打到被拦域名 → 续期失败 → 旧代码 `clearTokens()` + 跳 `/login` → **超 10 分钟必被踢回登录页**（access token TTL=15min，过期后任意请求触发续期，撞上错域 → 清 token）。
- 注意：本仓库 **没有 `.env.production` 文件**，该变量只在 Cloudflare Pages 的「构建环境变量」里配置，仓库外不可见，必须人工核对。

**已落地的代码层防御（commit `903b35f`，PR #305）**：
- `api-client.ts`：① 新增 `startTokenKeepAlive()`——按 access token exp 提前 120s 主动续期 + 页面可见时兜底续期，化被动续期为保活；② `refreshToken` 仅在刷新接口**真 401** 才清 token 跳登录，网络/跨域瞬时异常保留会话允许重试，避免误踢。
- `auth-context.tsx`：登录成功 / 初始化已登录态启动 keep-alive，登出停止。

**部署铁律**：
- 改 `VITE_API_BASE_URL` 后必须重新 `wrangler pages deploy`（走 main/master push 的 CI 才触发），develop push 只 build 不部署。
- 发布前在 Cloudflare Pages 控制台核对构建变量值 = `https://quant-api.stephenhe.com/api/v1`。
- WS 连接已统一用 `getWsBaseUrl()`（从 `API_BASE_URL` 推导 origin），跟随 REST 子域，不再裸用 `window.location.host`，避免同样被 `quant.stephenhe.com` 拦截。
