---
kind: build_system
name: 构建与部署体系：uv + Docker Compose + GitHub Actions 多节点编排
category: build_system
scope:
    - '**'
source_files:
    - Makefile
    - pyproject.toml
    - uv.lock
    - Dockerfile
    - data_subservice/Dockerfile
    - frontend/Dockerfile
    - docker-compose.master.yml
    - .github/workflows/backend.yml
    - .github/workflows/frontend.yml
    - .github/workflows/compose-hygiene.yml
    - start.sh
    - alembic.ini
    - prometheus.yml
    - registry-config.yml
---

## 1. 使用的系统与工具

- **Python 包管理**：根工程统一使用 `uv`（`pyproject.toml` 中 `[build-system]` 为 hatchling，依赖通过 `uv.lock` 锁定），开发/测试/生产均通过 `uv sync --all-extras` 或 `uv run` 执行。
- **前端包管理**：`frontend/` 使用 `pnpm`（`pnpm-lock.yaml`、`pnpm install --frozen-lockfile`），Node 版本由 `.github/workflows/frontend.yml` 固定为 Node 24。
- **容器化**：后端主服务 `Dockerfile`、数据子服务 `data_subservice/Dockerfile`、前端 `frontend/Dockerfile` 均为多阶段构建；运行时通过 `docker compose`（`docker-compose.master.yml`、`docker-compose.node-{s1,s2,s3,s4,bj}.yml`）编排 Redis、PostgreSQL、quant-agent、quant-worker、Prometheus/Grafana、私有 Registry。
- **CI/CD**：GitHub Actions（`.github/workflows/backend.yml`、`frontend.yml`、`eval.yml`、`security.yml`、`compose-hygiene.yml`），PR/develop 仅本地 buildx `--load` 验证，push main 才真实 `--push` GHCR 并 SSH 部署到 VPS。
- **本地启动**：`Makefile` 提供 `install/format/lint/test/coverage/dev*` 等目标；`start.sh` 是一键脚本，支持开发模式（本地 uvicorn + worker + vite）和 `-d/--docker` 全栈 Docker 模式。

## 2. 关键文件

- 构建入口：`Makefile`、`pyproject.toml`、`uv.lock`
- 镜像定义：`Dockerfile`（后端主服务）、`data_subservice/Dockerfile`、`frontend/Dockerfile`
- 编排配置：`docker-compose.master.yml`、`docker-compose.node-s1/s2/s3/s4/bj.yml`、`registry-config.yml`
- CI 流水线：`.github/workflows/backend.yml`、`.github/workflows/frontend.yml`、`.github/workflows/compose-hygiene.yml`
- 本地一键脚本：`start.sh`
- 数据库迁移：`alembic.ini`、`backend/alembic/versions/`
- 监控：`prometheus.yml`、`grafana/provisioning/`、`tempo/tempo.yaml`

## 3. 架构与约定

### 3.1 多阶段镜像构建
- 后端主服务镜像分 builder（安装 uv、同步依赖）和 runtime（python:3.11-slim，只复制 .venv + backend/hermes_agent 源码），并通过阿里云 Pypi/apt 镜像加速。
- 数据子服务镜像同样双阶段，但额外通过 `ARG DS_EXTRA=datasource-all` 把 tushare/futu/akshare/finnhub/yfinance 全部装进单一镜像，节点能力靠运行时环境变量 `DS_CAPABILITIES` 隔离（未声明的能力返回 503），不再按地域拆分镜像。
- 前端镜像用 node:20-alpine 构建 dist，再拷贝到 nginx:alpine 静态托管。

### 3.2 环境分层
- 运行期依赖集中在 `pyproject.toml` 的 `dependencies`；重型数据源 SDK 放在 `optional-dependencies.datasource`，仅 data-subservice 安装。
- 开发工具链集中在 `[dependency-groups].dev`（ruff、mypy、pre-commit、pytest-*），通过 `uv sync --dev` 安装，避免每次 `uv run` 临时解析开销。
- 测试通过 `pyproject.toml` 的 `[tool.pytest.ini_options]` 集中配置 testpaths、markers、asyncio_mode、NUMBA_CACHE_DIR 等。

### 3.3 多节点部署拓扑
- 海外主节点（master）：Redis + PostgreSQL + quant-agent (FastAPI) + quant-worker + 私有 Registry + Prometheus/Grafana（可选 profile monitoring）。
- 数据从节点（bj/s2/s3/s4）：独立 data-subservice 进程，通过 ServiceRegistry 向主节点注册并心跳保活；北京节点经主节点内网 registry（TAILSCALE_IP:5000）拉取镜像，其他节点直拉 GHCR。
- 所有 compose 显式声明顶级 `name:` 字段（如 `quant-agent-master`），避免不同 compose 互相误判 orphan。

### 3.4 CI 门禁策略
- PR/develop push：仅 `docker buildx build --load` 本地编译验证，不 push 镜像、不部署。
- push main：真实 build + push GHCR，打 `:<DEPLOY_SHA>` 与 `:latest`（主服务）或 `:us`（data-subservice）双标签；随后 SSH 到各 VPS 拉取镜像并 `docker compose up -d --remove-orphans`。
- deploy-data-nodes 使用 matrix 并行部署 bj/s2/s3/s4，每个节点注入不同的 `DS_NODE_ID`、`DS_REGION`、`DS_CAPABILITIES`、`NODE_TZ`。
- compose-hygiene reusable workflow 强制校验所有 compose 必须声明 `name:` 且仓库名不得含连字符版（`quant-agent-` → `quant_agent-`）。

### 3.5 版本与发布约定
- 镜像 tag 基于 merge commit 的第二个 parent（`= PR head SHA`），由 `git rev-parse "${HEAD_SHA}^2"` 解析，确保部署镜像可追溯到合并前的 PR 代码。
- 前端产物通过 Cloudflare Pages 部署（`cloudflare/pages-action`），分支映射到 CF Pages 分支。
- 数据库迁移通过 Alembic（`alembic.ini` + `backend/alembic/versions/`）管理。

## 4. 约定与约束

- **依赖锁定**：Python 依赖通过 `uv.lock` 锁定，CI 使用 `uv sync --all-extras`；前端通过 `pnpm-lock.yaml` + `--frozen-lockfile`。
- **数据源 SDK 隔离**：tushare/futu/akshare/finnhub 等重型 SDK 禁止安装在主服务默认环境，仅 data-subservice 镜像安装，主服务通过 DataSourceRouter HTTP 转发。
- **网络暴露规范**：Redis/PostgreSQL/Registry/Prometheus/Grafana 仅绑定 `127.0.0.1` 与 TAILSCALE_IP，不暴露公网端口；仅 quant-agent 8000 端口对公网开放（供 Cloudflare Pages 回调）。
- **健康检查**：所有 compose 服务均声明 healthcheck（redis-cli ping、pg_isready、HTTP /api/v1/health、wget prometheus/grafana 健康端点），服务间通过 `condition: service_healthy` 依赖。
- **资源限制**：每个 compose 服务通过 `deploy.resources.limits/reservations` 设置 CPU/内存上限，防止单容器拖垮宿主。
- **覆盖率门槛**：`[tool.coverage.report] fail_under = 80`，低于 80% 视为失败。
- **Mock 红线**：前端 CI 扫描 `src/` 下含 `MOCK_*` 但未用 `MOCK_ENABLED` 门控的代码，违反即失败（PROD 零 Mock）。
- **预提交钩子**：`make install` 自动执行 `uv run pre-commit install`，结合 `pyproject.toml` 中的 ruff/mypy 规则在提交时拦截。
- **日志与可观测性**：通过 structlog + OpenTelemetry（OTEL_ENABLED 控制），Prometheus metrics 暴露于量化系统内部，Grafana dashboard 通过 provision 目录自动加载。
