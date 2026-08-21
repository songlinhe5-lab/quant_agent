---
kind: logging_system
name: 后端结构化日志系统（structlog + Rich + QueueListener）
category: logging_system
scope:
    - '**'
source_files:
    - backend/core/logger.py
    - backend/core/structlog_config.py
    - docs/08. 日志与可观测性规范.md
    - backend/main.py
    - backend/core/middleware.py
    - backend/middleware/stack.py
---

## 1. 使用的框架与工具

- **标准库 logging**：作为底层输出管道，通过 `QueueHandler` + `QueueListener` 实现无阻塞异步落盘。
- **Rich**：终端彩色渲染（`RichHandler`、`Console`、`Theme`），并通过自定义 `PlainFileFormatter`/`ConsoleColorFormatter` 剥离/注入 markup。
- **structlog**：结构化日志门面，绑定到标准 logging 体系；生产环境 JSON 输出，开发环境彩色 key=value 控制台输出。
- **TimedRotatingFileHandler**：按天切割日志文件，保留最近 30 份。
- **WebhookAlertHandler**：可选的严重错误 webhook 告警（钉钉/企微/Telegram），由 `ALERT_WEBHOOK_URL` 环境变量激活。
- **OpenTelemetry**：通过 `backend/core/otel_config.py` 初始化，将 trace_id 注入日志并上报至 Grafana Tempo。
- **Prometheus/Grafana**：`backend/core/middleware.py` 暴露 `fastapi_requests_total`、`fastapi_request_duration_seconds`、`external_api_*` 指标。

## 2. 核心文件

| 文件 | 作用 |
|---|---|
| `backend/core/logger.py` | 统一日志初始化入口：配置 Rich 控制台、分级文件 handler、QueueListener、webhook 告警、接管 uvicorn/fastapi/sqlalchemy 日志 |
| `backend/core/structlog_config.py` | structlog 结构化日志配置：contextvars 注入 trace_id/symbol/latency_ms、JSON formatter、dev/prod 渲染器切换、`bind_context()` 便捷 API |
| `docs/08. 日志与可观测性规范.md` | 日志与可观测性规范文档，定义字段命名约定、关键事件清单、前端日志、监控看板、OTEL→Tempo 契约 |
| `backend/main.py` | FastAPI 应用工厂中调用 `configure_structlog()`，并以 `structlog.get_logger("quant_agent")` 获取 logger |
| `backend/core/middleware.py` | AccessLogMiddleware 记录 HTTP 请求耗时、状态码，并触发 Prometheus 指标；httpx 拦截器记录外部 API 延迟 |
| `backend/middleware/stack.py` | 中间件栈注册，同时使用 structlog 的 `bind_context` 注入 trace_id/symbol |

## 3. 架构与工作流程

### 3.1 启动链路

1. `main.py` → `create_app()` → `configure_structlog()`（在 `init_otel(application)` 之后）。
2. `logger.py` 中的 `configure_logging()` 被模块导入时自动执行（模块级 `logger = configure_logging()`），建立 Root Logger。
3. `structlog_config.configure_structlog()` 遍历 root logger 的 `QueueHandler` → `QueueListener` 下的 `TimedRotatingFileHandler`，替换为 `StructlogJsonFormatter`，使文件输出变为 JSON 行。
4. structlog 处理器链：`add_log_level` → `add_logger_name` → `TimeStamper` → `inject_context_vars` → `StackInfoRenderer` → `UnicodeDecoder` → `ProcessorFormatter.wrap_for_formatter`。
5. 终端输出：`ConsoleRenderer`（dev）或 `JSONRenderer`（prod）；文件输出：`StructlogJsonFormatter`。

### 3.2 上下文传播

- 使用 `contextvars.ContextVar` 存储 `trace_id`、`symbol`、`latency_ms`。
- `bind_context(**kwargs)` 设置这些变量，所有后续 structlog 调用自动携带。
- `middleware/stack.py` 在请求进入时通过 `bind_context(trace_id=...)` 注入 trace_id。

### 3.3 输出路由

```
logging.getLogger("quant_agent").info(...) 
  → QueueHandler → QueueListener
    ├─ RichHandler (终端, 彩色)
    ├─ TimedRotatingFileHandler: logs/debug.log (DEBUG)
    ├─ TimedRotatingFileHandler: logs/info.log (INFO)
    ├─ TimedRotatingFileHandler: logs/warning.log (WARNING)
    ├─ TimedRotatingFileHandler: logs/error.log (ERROR+CRITICAL)
    └─ WebhookAlertHandler (仅 ERROR+, 可选)
```

### 3.4 第三方日志接管

- `uvicorn`、`uvicorn.error`、`uvicorn.access`、`fastapi` 的 handlers 被清空，`propagate=True` 使其冒泡到 quant_agent 的队列。
- `sqlalchemy.engine` 级别被设为 WARNING，避免 INFO 刷屏。

## 4. 约定与约束

### 4.1 日志字段约定（来自 docs/08）

- event 名采用动词_名词格式（如 `order_submitted`、`service_started`）。
- 数值字段用原始类型而非字符串化对象。
- 后缀约定：`_ms`（毫秒）、`_count`（计数）、`_bytes`（字节数）、`_url`（URL）、`_id`（ID）。
- 必须记录的关键事件：服务启停、外部连接状态、订单提交、策略信号、性能关键路径、降级事件、安全事件。

### 4.2 强制约束

- **禁止**直接使用 `print()` 或自行配置 logging；所有后端模块统一从 `backend/core/logger.py` 获取 logger（docs/08 明确声明）。
- 文件输出在生产环境必须是 JSON 格式（便于 ELK/Loki 采集）。
- 每条日志必须携带 `trace_id`、`symbol`、`latency_ms` 字段（由 `inject_context_vars` 自动注入）。
- 日志文件按天切割，保留最近 30 份（`backupCount=30`）。
- 严重错误（ERROR+）可通过 `ALERT_WEBHOOK_URL` 触发 webhook 告警，且告警失败不会导致日志线程崩溃（try/except 兜底）。
- 请求级 trace_id 通过 `X-Trace-ID` 头透传，关闭 OTEL 时回退短 hex。

### 4.3 运行时行为

- QueueListener 在独立守护线程中消费队列，网络 I/O（webhook）不阻塞主进程。
- `atexit.register(listener.stop)` 保证进程退出前队列日志刷盘。
- 开发环境（`QUANT_ENV=development`）使用彩色 ConsoleRenderer；生产环境使用 JSONRenderer。
- 异常堆栈通过 `rich_tracebacks=True`、`tracebacks_show_locals=True` 在终端高亮显示。

### 4.4 监控集成

- `AccessLogMiddleware` 记录每个 HTTP 请求的 method、endpoint、status_code、耗时，并写入 Prometheus 指标。
- httpx 拦截器记录外部 API（finnhub/fred/tavily/jina/dingtalk/feishu/telegram/openai/yahoo 等）的延迟和状态码。
- 慢外部 API（>3s）以 warning 级别记录。
- OpenTelemetry 通过 `init_otel(application)` 启用，支持 `OTEL_ENABLED`、`OTEL_EXPORTER_OTLP_ENDPOINT`、`OTEL_SAMPLING_RATE` 配置。