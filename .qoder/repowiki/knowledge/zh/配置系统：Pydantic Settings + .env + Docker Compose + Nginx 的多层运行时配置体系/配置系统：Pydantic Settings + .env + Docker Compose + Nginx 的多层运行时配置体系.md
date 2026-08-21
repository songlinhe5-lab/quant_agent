---
kind: configuration_system
name: 配置系统：Pydantic Settings + .env + Docker Compose + Nginx 的多层运行时配置体系
category: configuration_system
scope:
    - '**'
source_files:
    - backend/core/config.py
    - backend/core/database.py
    - backend/core/otel_config.py
    - backend/core/structlog_config.py
    - .env.example
    - docker-compose.master.yml
    - quant.conf
    - frontend/.env.example
    - frontend/vite.config.ts
    - config/prometheus_rules.yml
    - prometheus.yml
    - registry-config.yml
    - grafana/provisioning/datasources/
    - grafana/provisioning/alerting/
    - alembic.ini
---

## 1. 整体方案

Quant Agent 采用「环境变量优先、文件模板兜底」的纯环境变量驱动配置，核心由 `pydantic-settings` 的 `BaseSettings` 统一建模与校验，Docker Compose 负责注入，Nginx 提供反向代理/HTTPS 配置，前端 Vite 通过 `.env.*` 控制构建期行为。

- **后端**：`backend/core/config.py` 中的 `Settings(BaseSettings)` 是全局唯一配置入口（模块级单例 `settings = Settings()`），所有服务通过 `from backend.core.config import settings` 读取。配置文件来源按优先级：进程环境 → `.env`（UTF-8）→ Pydantic Field 默认值；`extra="ignore"` 允许多余环境变量被静默丢弃。
- **数据库/Redis/LLM/数据源密钥**等全部以 `DATABASE_URL`、`REDIS_*`、`LLM_*`、`*_API_KEY` 等形式通过环境变量注入，缺失必填项在 `Settings` 构造时 fail-fast（如 `database_url`、`embedding_api_key`、`EMBEDDING_BASE_URL` 由 validator 强制非空）。
- **部署编排**：`docker-compose.master.yml` 通过 `env_file: .env` 和 `environment:` 段把 `.env` 变量展开为容器内环境变量（例如 `DATABASE_URL=postgresql://${DB_USER}:${DB_PASSWORD}@postgres:5432/${DB_NAME}`），并显式覆盖 `QUANT_ENV=production`、`OTEL_ENABLED=false` 等运行开关。
- **Nginx**：`quant.conf` 是生产反向代理配置，将 `/api/`、`/ws/`、`/` 转发到 `127.0.0.1:8000`，并配置 WebSocket Upgrade、长超时、SSL 协议与证书路径。
- **前端**：Vite 通过 `frontend/.env.example` 暴露 `VITE_ENABLE_MOCK`，`vite.config.ts` 中 proxy 指向 `http://127.0.0.1:8000`；构建期 `import.meta.env.DEV` 决定 mock 是否注入。
- **可观测性**：`backend/core/otel_config.py` 独立于 `Settings`，直接读 `OTEL_*` 环境变量初始化 OpenTelemetry；`backend/core/structlog_config.py` 根据 `QUANT_ENV` 切换 JSON（生产）/彩色 key=value（开发）输出。

## 2. 关键文件与包

| 文件 | 职责 |
|---|---|
| `backend/core/config.py` | Pydantic Settings 模型，定义所有后端配置字段、validator、枚举 `QuantEnv`、全局单例 `settings` |
| `backend/core/database.py` | 从 `DATABASE_URL` 创建同步/异步 SQLAlchemy engine，PostgreSQL 连接池参数来自 `DB_POOL_SIZE`/`DB_MAX_OVERFLOW`/`DB_POOL_TIMEOUT` |
| `backend/core/otel_config.py` | 基于 `OTEL_*` 环境变量初始化 TracerProvider、FastAPI/Redis/HTTPX/SQLAlchemy 自动埋点 |
| `backend/core/structlog_config.py` | 基于 `QUANT_ENV` 选择 structlog 渲染器，注入 trace_id/symbol/latency_ms 上下文 |
| `.env.example` | 主节点完整环境变量模板，标注 [必填]/[可选]，包含 Redis/PG/LLM/Embedding/数据源/HMAC/告警/OAuth/OTEL/CORS 等全部键 |
| `docker-compose.master.yml` | 容器编排，通过 `env_file` + `environment` 注入运行时配置，声明资源限制与健康检查 |
| `quant.conf` | Nginx HTTPS/WS 反向代理配置 |
| `frontend/.env.example` | 前端构建期开关 `VITE_ENABLE_MOCK` |
| `frontend/vite.config.ts` | 开发服务器 proxy、构建产物目录、别名配置 |
| `config/prometheus_rules.yml` | Prometheus 规则文件 |
| `grafana/provisioning/*` | Grafana 仪表盘/数据源/告警 provision 配置 |
| `prometheus.yml` | Prometheus 抓取目标配置 |
| `registry-config.yml` | 私有镜像 Registry 配置 |
| `alembic.ini` / `backend/alembic/env.py` | 数据库迁移配置 |

## 3. 架构与设计约定

- **单一配置源**：后端所有配置集中到 `backend/core/config.py` 的 `Settings` 类，新增配置必须在此添加字段 + alias，禁止散落 `os.getenv` 调用。
- **fail-fast 启动**：`@field_validator` 对 `DATABASE_URL`、`EMBEDDING_API_KEY`、`REAL_TRADE_EXECUTE` 等关键字段做强校验，缺失或非法直接抛异常阻止启动。
- **环境隔离**：`QuantEnv` 枚举 (`development`/`production`/`testing`) 由 `QUANT_ENV` 注入，`is_production`/`is_development` 属性供业务分支；structlog 据此切换 JSON/彩色输出。
- **敏感字段分离**：API Key、密码、HMAC Secret 仅通过环境变量注入，`.env` 已加入 `.gitignore`；`ENCRYPTION_MASTER_KEY` 用于敏感字段加密。
- **多节点能力声明**：`data_subservice` 通过 `DS_CAPABILITIES` 声明自身能力集，未声明能力返回 503；主节点通过 `DATA_SOURCE_ROUTER_ENABLED` + `DATA_SOURCE_HMAC_SECRET` 路由到远程子节点。
- **离线/Stub 模式**：`OFFLINE_MODE`、`LLM_STUB`、`QUANT_RECORD` 等开关支持 CI/本地离线开发与契约录制。
- **容器网络命名**：容器间通信使用 Docker 服务名（`redis`、`postgres`）而非 `localhost`，通过 `TAILSCALE_IP` 绑定 Tailscale 内网 IP，避免公网暴露。

## 4. 约定与约束

- **严禁提交密钥**：`.env.example` 顶部注释明确“严禁将 .env 提交到 Git”，CI 在 `.env` 不存在时复制模板并补入 `TAILSCALE_IP`。
- **数据库 URL 格式约束**：必须以 `sqlite://` 或 `postgresql://` 开头，否则启动失败。
- **实盘交易安全锁**：`REAL_TRADE_EXECUTE=true` 时必须同时配置 `FUTU_PWD_UNLOCK`，否则抛出异常。
- **Embedding 维度一致性**：`EMBEDGING_DIM` 必须与 `EMBEDDING_MODEL` 输出维度对齐（bge-large-zh-v1.5=1024），否则 pgvector 建表/查询报错。
- **Redis 密码一致**：Compose 中 `--requirepass ${REDIS_PASSWORD}` 与后端 `REDIS_PASSWORD` 必须一致，否则连接被拒。
- **端口绑定安全**：Redis/PostgreSQL/Registry/Prometheus/Grafana 仅绑定 `127.0.0.1` 与 `${TAILSCALE_IP:-127.0.0.1}`，不暴露公网。
- **前端 Mock 零注入**：生产构建下 `VITE_ENABLE_MOCK` 被忽略，mock 数据绝不注入。
- **OTEL 可插拔**：`OTEL_ENABLED=false` 时跳过初始化；依赖缺失时降级为 NoOp，不影响主流程。
- **日志结构化**：所有日志必须携带 `trace_id`、`symbol`、`latency_ms` 字段，生产输出 JSON 行便于 ELK/Loki 采集。

## 5. 相关测试

- `tests/test_config.py`：验证 `Settings` 加载与校验逻辑。
- `tests/test_structlog_config.py`：验证 structlog JSON/彩色输出与上下文注入。
- `tests/test_otel_be10.py`：验证 OTEL 初始化与 trace_id 传播。
- `tests/test_database.py`：验证数据库引擎与连接池配置。
- `tests/test_redis_client.py`：验证 Redis 客户端配置加载。

该配置体系以 pydantic-settings 为核心，配合 docker-compose 的环境变量注入、nginx 的反向代理配置以及前端的构建期环境变量，形成从开发到生产的完整配置链路。