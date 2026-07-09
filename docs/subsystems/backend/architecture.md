# 后端子系统架构文档

> 最后更新：2026-07-07 | 版本：V3.0  
> **架构变更**：升级为三节点高可用架构（海外主节点 + 海外备用节点 + 国内 AKShare 节点），支持 YFinance 多源切换和 AKShare 远程获取。

## 一、架构图（三节点高可用方案）

```
┌──────────────────────────────────────────────────────────────────────────┐
│                        三节点高可用架构                                  │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  海外主节点 (Master)                      海外备用节点 (YFinance Backup) │
│  ┌─────────────────────────────────────┐  ┌───────────────────────────┐ │
│  │  backend/main.py  ← FastAPI 入口     │  │  backend/main.py          │ │
│  ├─────────────────────────────────────┤  ├───────────────────────────┤ │
│  │  routers/                           │  │  routers/                 │ │
│  │  ├── auth.py / market.py / oms.py   │  │  └── data_source.py       │ │
│  │  ├── screener.py / backtest.py      │  │      (代理接口)           │ │
│  │  ├── chat.py                        │  ├───────────────────────────┤ │
│  │  └── data_source.py                 │  │  services/                │ │
│  ├─────────────────────────────────────┤  │  └── yfinance_service.py  │ │
│  │  services/                          │  ├───────────────────────────┤ │
│  │  ├── futu/                          │  │  COLLECTOR_YFINANCE=true  │ │
│  │  ├── screener_service.py            │  │  DATA_SOURCE_ROUTER=off   │ │
│  │  ├── llm_service.py                 │  └───────────────────────────┘ │
│  │  ├── data_source_router.py ←核心    │                                  │
│  │  │   (多源切换 + 远程调用)           │  国内 AKShare 节点 (CN Node)     │
│  │  ├── yfinance_service.py            │  ┌───────────────────────────┐ │
│  │  └── akshare_service.py             │  │  backend/main.py          │ │
│  ├─────────────────────────────────────┤  ├───────────────────────────┤ │
│  │  workers/                           │  │  routers/                 │ │
│  │  ├── quote_publisher.py             │  │  └── data_source.py       │ │
│  │  └── collector_registry.py          │  │      (代理接口)           │ │
│  ├─────────────────────────────────────┤  ├───────────────────────────┤ │
│  │  core/                              │  │  services/                │ │
│  │  ├── redis_client.py                │  │  └── akshare_service.py   │ │
│  │  ├── database.py                    │  ├───────────────────────────┤ │
│  │  └── logger.py                      │  │  COLLECTOR_AKSHARE=true   │ │
│  ├─────────────────────────────────────┤  │  DATA_SOURCE_ROUTER=off   │ │
│  │  Redis / PostgreSQL / Futu OpenD    │  └───────────────────────────┘ │
│  └─────────────────────┬───────────────┘                                  │
│                        │                                                  │
│                        │ Tailscale 内网通信 (HMAC 签名验证)                 │
│                        │                                                  │
│                        └──────────────────────────────────────────────────┘
│                                                                          │
│  数据流:                                                                  │
│  ├── YFinance请求 → data_source_router → 主节点本地 → 失败/限流 → 备用节点  │
│  └── AKShare请求 → data_source_router → 国内节点 → 失败 → 本地降级         │
└──────────────────────────────────────────────────────────────────────────┘
```

### 1.1 节点职责矩阵

| 节点 | 定位 | 核心服务 | 数据源 |
|:---|:---|:---|:---|
| **海外主节点** | 核心业务 | Redis, PostgreSQL, quant-agent, quant-worker | Futu OpenD(本地), YFinance(本地+远程), AKShare(远程) |
| **海外备用节点** | YFinance 备用 | 仅 quant-agent | YFinance(本地) |
| **国内 AKShare 节点** | 国内数据源 | 仅 quant-agent | AKShare(本地) |

### 1.2 数据源路由核心流程

```python
# data_source_router.py — 核心路由逻辑

async def fetch_yfinance(self, ticker, fetch_type, **kwargs):
    # 1. 遍历健康节点（按权重排序）
    for node in self._get_healthy_nodes("yfinance"):
        try:
            result = await self._send_request(node, "yfinance", payload)
            if result.get("success"):
                return result
            # 2. 限流检测：429/rate limit 时标记节点并尝试下一个
            if "429" in str(result.get("message", "")):
                await self._update_node_status(node.name, False, "rate_limit")
                continue
        except Exception:
            await self._update_node_status(node.name, False)
    # 3. 全部失败时降级到本地
    return await self._fetch_local(ticker, fetch_type, **kwargs)

async def fetch_akshare(self, action, **kwargs):
    # 1. 优先调用远程 AKShare 节点
    remote_node = self._nodes.get("akshare_remote")
    if remote_node and remote_node.status == "healthy":
        try:
            result = await self._send_request(remote_node, "akshare", payload)
            if result.get("status") == "success":
                return result
            await self._update_node_status(remote_node.name, False)
        except Exception:
            await self._update_node_status(remote_node.name, False)
    # 2. 远程失败时降级到本地
    return await self._call_local_akshare(action, **kwargs)
```

## 一之一、跨节点数据源路由架构

当需要多源切换（YFinance 限流）或远程数据源（AKShare 国内 VPS）时，启用跨节点路由模式：

```
┌──────────────────────────────────────────────────────────────────────────┐
│                        数据源路由架构（多节点模式）                        │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  海外主节点                          海外备用节点                        国内节点
│  ┌──────────────┐                   ┌──────────────┐                   ┌──────────────┐
│  │ quant-agent  │                   │ quant-agent  │                   │ quant-agent  │
│  │ 主服务       │                   │ 备用服务     │                   │ AKShare服务  │
│  └──────┬───────┘                   └──────┬───────┘                   └──────┬───────┘
│         │                                  │                                  │
│         │  HTTP请求 (HMAC签名)             │                                  │
│         │  YF_PRIMARY_NODE_URL            │                                  │
│         ├────────────────────────────────→│                                  │
│         │                                  │  YFinance本地调用                  │
│         │←────────────────────────────────┤                                  │
│         │                                  │                                  │
│         │  限流/失败                        │                                  │
│         ├────────────────────────────────────────────────────────────────→│
│         │                                  │                                  │  AKShare本地调用
│         │←────────────────────────────────────────────────────────────────┤
│         │                                  │                                  │
│         │  AKSHARE_REMOTE_URL              │                                  │
│         ├────────────────────────────────────────────────────────────────→│
│         │                                  │                                  │
│         │←────────────────────────────────────────────────────────────────┤
│         │                                  │                                  │
│         │  fallback to local              │                                  │
│         └──────────────────────────────────────────────────────────────────┘
│                                                                          │
│  核心组件:                                                               │
│  ├── data_source_router.py  ← 路由服务，管理节点状态与切换逻辑            │
│  ├── data_source.py (router) ← 代理接口，接收跨节点请求                  │
│  ├── HMAC签名                ← 节点间通信安全验证                        │
│  └── 熔断器机制               ← 节点失败自动标记，防止雪崩                │
└──────────────────────────────────────────────────────────────────────────┘
```

### 1.1 数据源路由服务（data_source_router.py）

| 组件 | 职责 | 关键特性 |
|:---|:---|:---|
| DataSourceNode | 节点定义 | name, url, weight, capabilities, status, circuit_breaker_until |
| fetch_yfinance() | YFinance 多源获取 | 按权重遍历健康节点，限流时切换，全部失败则降级本地 |
| fetch_akshare() | AKShare 远程获取 | 优先调用远程节点，失败则降级本地 |
| get_health_status() | 健康状态查询 | 返回所有节点状态与冷却剩余时间 |
| _update_node_status() | 节点状态更新 | 成功清零错误计数，失败累计，连续3次触发熔断 |

### 1.2 节点间通信安全

```python
# HMAC 签名验证流程

# 请求方（主节点）
payload = {"ticker": "AAPL", "fetch_type": "quote"}
signature = sha256(HMAC_SECRET + json.dumps(payload, sort_keys=True))
headers["X-Data-Source-Signature"] = signature

# 接收方（代理节点）
received_signature = request.headers.get("X-Data-Source-Signature")
expected_signature = sha256(HMAC_SECRET + json.dumps(body, sort_keys=True))
if received_signature != expected_signature:
    raise HTTPException(status_code=401, detail="Invalid signature")
```

### 1.3 熔断与切换机制

```
节点状态机:
  healthy ←──────┐
    │            │ 成功请求
    │ 失败       │
    ↓            │
  unhealthy      │
    │            │
    │ 冷却结束    │
    ↓            │
  circuit_breaker_until 到期
    │
    ↓
  自动恢复为 healthy
```

**熔断规则**：
- 连续失败 3 次 → 标记为 unhealthy
- unhealthy 节点进入 60 秒冷却期（circuit_breaker_until）
- 冷却期内跳过该节点，尝试其他健康节点
- 冷却期结束后自动恢复为 healthy

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
| 2026-07-06 | V2.0 架构重构：移除主从集群，改为单一 VPS 本地采集模式；更新架构图、workers 层描述、外部数据源访问方式 |
| 2026-06-27 | V1.0 初始版本 |
