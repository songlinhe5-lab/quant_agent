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

## 三、Phase 3 待推进（依赖基础设施，当前挂起）

**目标**：删主服务第二份 OpenD 实例 + 确认 data_subservice 已实际运行。

**前置条件（基础设施就绪后）**：
1. 主节点仅保留 `127.0.0.1:11111` 一份 Futu OpenD（US-MASTER 宿主）；移除主服务侧重复/冗余 OpenD 启动逻辑。
2. `data_subservice` 在 US-YF-A/B、CN-AKSHARE 等节点以 external 模式部署并启动；心跳写主 Redis Registry。
3. 主服务 `DATASOURCE_*` 模式切 `external`，`DataSourceRouter` 经 HMAC + Tailscale 调子服务 `/ds/{source}/{action}`。
4. 验证 `DataSourceRouter.fetch_futu` 远程透传信封（data_subservice 返回的子服务信封需与主服务 kline_warehouse 兼容 - 已在 Phase 2 修一处 envelope 不一致 bug）。

**风险点**：
- legacy_market_data 循环导入（预存环境债，非本次引入，待修）。
- Redis 未运行时 router 测试 503（环境性，非代码 bug）。
- 子服务 remote 返回信封与主服务 local 降级返回结构需保持一致（已在 router.py + kline_warehouse.py 处理）。

## 四、相关文件索引

- 架构文档：`docs/03. 后端架构与执行引擎.md`（V5.2，§4.4 依赖收口红线）
- 数据源细规：`docs/14. 分布式数据源服务架构.md`（双模 / HTTP 协议 / Registry）
- 采集器映射：`docs/06`（四节点 Compose）、`AGENTS.md` §9（架构概述）
