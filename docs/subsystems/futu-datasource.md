# Futu 数据源架构 (V2.0)

> **文档定位**：Futu OpenD 数据源的接入设计，基于通用数据源框架 (`docs/14`) 的 Futu 特化实现。
> **最后更新**：2026-07-08 | **版本**：V2.0
> **关联文档**：`docs/14. 分布式数据源服务架构.md` | `AGENTS.md §10` | `docs/03. 后端架构与执行引擎.md`

---

## 一、概述

### 1.1 定位

Futu 是系统的核心实时行情数据源，通过 Futu OpenD 网关提供 Level 2 港美股行情。在通用数据源框架中，Futu 作为 `futu` 数据源注册到 `DataSourceRegistry`，支持 internal（直连 OpenD）和 external（HTTP 代理）两种运行模式。

### 1.2 能力声明

| capability | 说明 | 是否支持订阅 |
|:---|:---|:---:|
| `quote` | 实时行情快照（价格、涨跌幅、成交量） | ✅ |
| `history` | 历史 K 线（日/周/月/分钟级） | ❌ |
| `fund_flow` | 主力资金净流入、经纪商买卖盘席位 | ❌ |
| `option_chain` | 期权链及 OCC 合约代码 | ❌ |
| `subscribe_quote` | 实时行情推送（长连接订阅） | ✅ |

### 1.3 底层依赖

- **Futu OpenD 进程**：独立的 TCP 服务，监听 `127.0.0.1:11111`
- **连接管理**：`ConnectionManager` 负责 TCP 连接建立、心跳、断线重连
- **systemd 服务**：OpenD 通过 `futu.service` 管理，支持自动重启

---

## 二、架构设计

### 2.1 在通用框架中的位置

```
DataSourceRegistry
├── futu (本文档)
│   ├── internal 模式 → FutuInternalDataSource (直连 OpenD)
│   └── external 模式 → FutuExternalDataSource (HTTP → 远程节点)
├── yfinance → ...
├── akshare → ...
└── finnhub → ...
```

### 2.2 核心组件

| 组件 | 文件 | 职责 |
|:---|:---|:---|
| `DataSourceInterface` Protocol | `docs/14` §二 | 通用数据源接口定义 |
| `FutuInternalDataSource` | `services/futu/data_source.py` | internal 模式实现，直连 OpenD |
| `FutuExternalDataSource` | (待实现) | external 模式实现，HTTP 调用远程节点 |
| `ConnectionManager` | `services/futu/connection_manager.py` | OpenD TCP 连接管理 + `switch_host()` |
| `FutuService` | `services/futu/service.py` | 对外统一接口，委托 Registry |
| Futu Admin API | `routers/futu_admin.py` | 运行时切换模式/连接目标的 HTTP 端点 |

### 2.3 调用链路

```
上层调用 (routers / tools / workers)
    │
    ▼
FutuService.get_quote(ticker)
    │
    ▼
DataSourceRegistry.get("futu", "quote")
    │
    ├── internal 模式
    │   └── FutuInternalDataSource.fetch("quote", {"ticker": ticker})
    │       └── ConnectionManager → Futu OpenD (TCP 11111)
    │
    ├── external 模式
    │   └── FutuExternalDataSource.fetch("quote", {"ticker": ticker})
    │       └── HTTP POST → 远程节点 /ds/futu/quote → 节点本地 OpenD
    │
    └── hybrid 模式
        └── 先尝试 internal → 失败降级到 external
```

---

## 三、运行模式

### 3.1 模式定义（对齐通用框架）

| 模式 | 标识 | 行为 | 适用场景 |
|:---|:---|:---|:---|
| **内部模式** | `internal` | 主 app 进程内直连 Futu OpenD（TCP） | OpenD 在同一 VPS 或可达网络 |
| **外部模式** | `external` | 主 app 通过 HTTP 调用远程数据源节点，节点本地连接 OpenD | OpenD 在远程 VPS，主 app 无法直连 |
| **混合模式** | `hybrid` | 优先 internal 直连，失败自动降级到 external 节点 | 高可用生产环境 |

> **V1.0 术语映射**：`local` → `internal`，`remote` → `external`，`auto` → `hybrid`

### 3.2 配置项

| 环境变量 | 默认值 | 说明 |
|:---|:---|:---|
| `DATASOURCE_FUTU_ENABLED` | `true` | 是否启用 Futu 数据源 |
| `DATASOURCE_FUTU_MODE` | `internal` | 运行模式: `internal` / `external` / `hybrid` |
| `DATASOURCE_FUTU_NODES` | — | external/hybrid 模式的远程节点地址（逗号分隔） |
| `FUTU_HOST` | `127.0.0.1` | OpenD 主机地址 (internal 模式) |
| `FUTU_PORT` | `11111` | OpenD 端口 |
| `COLLECTOR_FUTU` | `false` | 是否启用 Futu 采集器（后台定时任务） |

### 3.3 典型配置

**主 app 与 OpenD 在同一 VPS (推荐)**:
```bash
DATASOURCE_FUTU_MODE=internal
FUTU_HOST=127.0.0.1
FUTU_PORT=11111
```

**主 app 与 OpenD 在不同 VPS (external 模式)**:
```bash
DATASOURCE_FUTU_MODE=external
DATASOURCE_FUTU_NODES=http://<OpenD_VPS_IP>:8000
```

**高可用混合模式**:
```bash
DATASOURCE_FUTU_MODE=hybrid
FUTU_HOST=127.0.0.1              # 先尝试直连
DATASOURCE_FUTU_NODES=http://<backup_VPS>:8000  # 直连失败降级
```

---

## 四、External 模式 HTTP 协议

当 Futu 以 external 模式运行时，远程数据源节点暴露以下 HTTP 接口：

### 4.1 数据获取

```
POST /ds/futu/{action}
Headers: X-DS-Sig, X-DS-Timestamp
Body: { "params": { "ticker": "00700.HK" } }

Response:
{
  "status": "success",
  "data": { "price": 388.2, "change": +2.1, ... },
  "source": "futu-node-hk-01",
  "latency_ms": 12.5,
  "cached": false
}
```

支持的 `{action}`：`quote`, `history`, `fund_flow`, `option_chain`

### 4.2 节点健康

```
GET /ds/futu/health

Response:
{
  "healthy": true,
  "mode": "internal",
  "connected": true,
  "uptime_seconds": 86400,
  "stats": {
    "total_requests": 15234,
    "total_errors": 23,
    "current_subscriptions": 50
  }
}
```

---

## 五、运行时 API

### 5.1 查询数据源状态

```
GET /api/v1/futu/source
```

响应示例:
```json
{
  "code": 0,
  "data": {
    "mode": "internal",
    "available": true,
    "instance": {
      "type": "internal",
      "connected": true,
      "host": "127.0.0.1",
      "port": 11111,
      "uptime_seconds": 86400
    }
  }
}
```

### 5.2 切换运行模式

```
PUT /api/v1/futu/source
Content-Type: application/json

{"mode": "external", "nodes": ["http://hk-vps:8000"]}
```

### 5.3 切换 OpenD 连接目标

```
PUT /api/v1/futu/host
Content-Type: application/json

{"host": "1.2.3.4", "port": 11111}
```

切换会断开现有连接并尝试重新连接到新目标。

---

## 六、OpenD 部署与运维

### 6.1 systemd 管理

Futu OpenD 通过 systemd 服务管理：

```ini
[Unit]
Description=Futu OpenD Gateway
After=network.target

[Service]
Type=simple
ExecStart=/opt/futu/opend -cfg /opt/futu/FutuOpenD.xml
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### 6.2 Docker 容器访问 OpenD

当主 app 运行在 Docker 容器中，通过 `extra_hosts` 映射访问宿主机的 OpenD：

```yaml
# docker-compose.yml
services:
  quant-agent:
    extra_hosts:
      - "host.docker.internal:host-gateway"
    environment:
      FUTU_HOST: host.docker.internal
      FUTU_PORT: 11111
```

> **注意**：`host.docker.internal` 在 Linux 上需要显式配置 `host-gateway`，否则无法解析。

### 6.3 网络拓扑

```
Docker 容器 (quant-agent)
    │
    │ FUTU_HOST=host.docker.internal
    │ FUTU_PORT=11111
    ▼
宿主机 (VPS)
    │
    ├── Futu OpenD (127.0.0.1:11111)
    │       ↑
    │       │ TCP 连接
    │       │
    └── host.docker.internal → 宿主机网关 IP
```

---

## 七、文件清单

| 文件 | 说明 |
|:---|:---|
| `backend/services/futu/data_source.py` | FutuDataSource Protocol + Internal 实现 |
| `backend/services/futu/source_router.py` | 数据源路由器（internal/external 编排） |
| `backend/services/futu/service.py` | 对外统一接口，`_route()` 委托 Registry |
| `backend/services/futu/connection_manager.py` | OpenD TCP 连接管理 |
| `backend/routers/futu_admin.py` | 运行时切换 API |
| `backend/main.py` | 注册 futu_admin 路由 |

---

## 附录：变更记录

| 日期 | 版本 | 变更内容 |
|:---|:---|:---|
| 2026-07-08 | V2.0 | 对齐通用数据源框架 V2.0：模式术语 local/remote/auto → internal/external/hybrid；统一 Result 返回结构；纳入 DataSourceRegistry 管理 |
| 2026-07-06 | V1.0 | 初版：Futu 数据源 local/remote/auto 三种模式设计 |
