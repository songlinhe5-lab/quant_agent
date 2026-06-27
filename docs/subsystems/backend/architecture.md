# 后端子系统架构文档

> 最后更新：2026-06-27 | 版本：V1.0

## 一、架构图

```
┌─────────────────────────────────────────────────────────────────┐
│  backend/main.py  ← FastAPI 唯一入口，路由注册 + 中间件挂载        │
├─────────────────────────────────────────────────────────────────┤
│  routers/         ← HTTP 路由层，只做参数校验与 Service 调用       │
│  ├── auth.py       /api/v1/auth/*                               │
│  ├── market.py     /api/v1/market/*  /ws/v1/quotes              │
│  ├── screener.py   /api/v1/screener                             │
│  ├── oms.py        /api/v1/oms/*     /ws/v1/oms-stream          │
│  ├── backtest.py   /api/v1/backtest                             │
│  ├── chat.py       /sse/v1/agent                                │
│  └── ...                                                        │
├─────────────────────────────────────────────────────────────────┤
│  services/        ← 业务逻辑层，编排 Worker/外部数据              │
│  ├── futu/         Futu OpenD SDK 封装（行情 + 交易）             │
│  ├── screener_service.py   选股逻辑（Filter Engine）             │
│  ├── llm_service.py        LLM 调用封装                          │
│  ├── kline_warehouse.py    K线历史本地缓存                        │
│  └── ...                                                        │
├─────────────────────────────────────────────────────────────────┤
│  workers/         ← 长驻后台任务（独立生命周期）                   │
│  ├── quote_publisher.py   Futu → Redis Pub/Sub 数据桥接          │
│  └── daemon.py            Worker 守护进程管理                    │
├─────────────────────────────────────────────────────────────────┤
│  core/            ← 基础设施（无业务逻辑）                         │
│  ├── config.py         环境变量 + Pydantic Settings              │
│  ├── database.py       SQLAlchemy 异步引擎 + Session 工厂        │
│  ├── redis_client.py   Redis 连接池单例                          │
│  ├── logger.py         structlog 统一日志配置                    │
│  ├── backtest_engine.py VectorBT 向量化回测引擎                  │
│  ├── market_engine.py  行情处理核心                              │
│  ├── middleware.py      FastAPI 中间件（Trace ID / CORS / 限流） │
│  ├── models.py         SQLAlchemy ORM 模型                      │
│  └── retry_utils.py    tenacity 重试装饰器                      │
└─────────────────────────────────────────────────────────────────┘
```

## 二、数据流示意

### 行情订阅流（高频路径）

```
Futu OpenD
  ↓ TCP 长连接（futu-api SDK）
workers/quote_publisher.py
  ↓ Redis PUBLISH "tick:{symbol}"
Redis Pub/Sub（内存总线）
  ↓ SUBSCRIBE（WebSocket Handler）
routers/market.py → WebSocket Handler
  ↓ JSON 序列化
前端 WebSocket 客户端
```

### AI 研报生成流（低频路径）

```
前端 SSE 请求 POST /sse/v1/agent
  ↓
routers/chat.py → Hermes Agent
  ↓ ReAct 循环：Plan → Tool
hermes_agent/tools/*.py
  ↓ 内网 HTTP 调用
services/*.py（查 Redis 缓存 / PostgreSQL / 外部 API）
  ↓ Tool 结果返回
Hermes Agent → Verify → Output
  ↓ SSE Token 逐字流
前端 EventSource
```

## 三、关键接口契约

### API 统一响应格式

```python
# backend/schemas/base_schema.py
class ApiResponse(BaseModel, Generic[T]):
    status: Literal["success", "error"]
    message: str
    data: Optional[T] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    error_code: Optional[str] = None   # 仅 error 时存在
```

### WebSocket 消息格式

```python
class WsMessage(BaseModel, Generic[T]):
    event: str         # e.g. "tick.update", "order.filled"
    data: T
    ts: int            # Unix ms
    seq: int           # 单调递增序列号（用于客户端乱序检测）
```

## 四、性能基准（见 docs/09.）

| 接口 | P95 目标 | 当前基准 |
|:---|:---:|:---:|
| GET /api/v1/market/quote | 100ms | 待测 |
| POST /api/v1/screener | 1000ms | 待测 |
| GET /api/v1/market/kline | 200ms | 待测 |

## 五、核心安全设计（快速参考）

详细设计见 `docs/03. 后端架构与执行引擎.md §七`

| 安全点 | 实现方式 |
|:---|:---|
| 用户鉴权 | JWT 双 Token（access 1h + refresh 7d HttpOnly Cookie） |
| Hermes Tool 鉴权 | HMAC-SHA256 请求签名（内部通道 `/internal/v1/`） |
| 凭证管理 | 环境变量，不落 Git，不写日志 |
| 交易数据脱敏 | 非实盘模式下资金字段返回 `***` |
| 审计追踪 | 所有交易操作写入 `audit_logs` 表（append-only） |
| CORS | 精确配置 ALLOWED_ORIGINS，禁用通配符 `*` |

## 六、测试覆盖情况

| 模块 | 目标覆盖率 | 当前状态 |
|:---|:---:|:---:|
| services/ | 80% | 部分有测试（test_screener_service.py） |
| routers/ | 70% | 部分有测试（test_api_preferences.py） |
| workers/ | 60% | 需补充 |
| core/ | 60% | 需补充 |

## 七、变更记录

| 日期 | 变更 |
|:---|:---|
| 2026-06-27 | 初始版本 |
