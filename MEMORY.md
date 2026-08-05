# MEMORY - Quant Agent 架构决策与待办上下文

> 跨会话持久记忆。聚焦于「为何这么做」与「待推进项」，避免后续会话丢失上下文。

## 一、数据源依赖物理隔离（2026-08-06 决策）

**决策**：主服务与数据源子服务依赖树彻底分离。
- `backend/requirements.txt`：**禁止**包含任何第三方数据源 SDK（futu-api / tushare / akshare / yfinance）。仅保留 FastAPI/uvicorn/pydantic/sqlalchemy/httpx/redis/pandas/numpy/requests。
- `data_subservice/requirements.txt`：收口全部数据源 SDK（futu-api / tushare / akshare / yfinance / protobuf）+ 子服务框架。
- `pyproject.toml` 主 `[project.dependencies]` 已移除 yfinance；数据源 SDK 仅留在 `optional-dependencies.datasource` extra（供 `data_subservice/Dockerfile` `uv sync --extra datasource`）。
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
- `backend.main` 导入 OK；`data_subservice` 在 `COLLECTOR_FUTU=true` 下能导入 `app` 与 `futu_src.ConnectionManager`（子服务为唯一 OpenD 宿主）。
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

## 四、相关文件索引

- 架构文档：`docs/03. 后端架构与执行引擎.md`（V5.2，§4.4 依赖收口红线）
- 数据源细规：`docs/14. 分布式数据源服务架构.md`（双模 / HTTP 协议 / Registry）
- 采集器映射：`docs/06`（四节点 Compose）、`AGENTS.md` §9（架构概述）
