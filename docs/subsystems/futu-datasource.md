# Futu 数据源可切换架构 (V1.0)

> **文档定位**：Futu OpenD 数据源的抽象层设计，支持本地直连与远程 slave 代理两种模式的平行切换。
> **最后更新**：2026-07-06 | **版本**：V1.0
> **关联文档**：`docs/14. 分布式数据源服务架构.md` | `docs/03. 后端架构与执行引擎.md`

---

## 一、背景与动机

### 1.1 部署拓扑

```
┌─────────────────────────────────────────────────────────────┐
│  北京 VPS (Master)                                           │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  FutuService (行情中心)                               │    │
│  │  ┌──────────────────────────────────────────────┐   │    │
│  │  │  SourceRouter (local/remote/auto)             │   │    │
│  │  │  ┌──────────────┐  ┌───────────────────┐    │   │    │
│  │  │  │ LocalDataSource│  │ RemoteDataSource   │    │   │    │
│  │  │  │ (直连 OpenD)   │  │ (ClusterManager    │    │   │    │
│  │  │  │               │  │  → slave HTTP)     │    │   │    │
│  │  │  └──────┬───────┘  └────────┬──────────┘    │   │    │
│  │  └─────────┼───────────────────┼───────────────┘   │    │
│  └────────────┼───────────────────┼───────────────────┘    │
│               │                   │                         │
└───────────────┼───────────────────┼─────────────────────────┘
                │                   │
    ┌───────────┘                   └──────────┐
    │ 模式A: local                             │ 模式B: remote
    │ FUTU_HOST=<HK_VPS_IP>                    │ ClusterManager HTTP
    │ 直连香港 VPS 的 OpenD                     │ → slave /collect/{action}
    │ (跳过 slave HTTP 中转)                    │ → slave 本地 OpenD
    ▼                                          ▼
┌─────────────────────────────────────────────────────────────┐
│  香港 VPS (Slave-1)                                          │
│                                                             │
│  ┌──────────────┐     ┌──────────────────────────────┐     │
│  │ Futu OpenD   │◄────│ slave_app (port 8001)         │     │
│  │ (本地 11111)  │     │ COLLECTOR_FUTU=true           │     │
│  └──────────────┘     └──────────────────────────────┘     │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 1.2 问题

改造前，master 获取 Futu 数据的唯一路径是：

```
Master → ClusterManager HTTP → slave /collect/{action} → slave 本地 OpenD
```

这条链路存在两个问题：

| 问题 | 影响 |
|:---|:---|
| **HTTP 中转开销** | 每次请求都要经过 HTTP 序列化/反序列化，增加延迟 |
| **单点依赖 slave** | slave 进程挂了 = 整个 Futu 数据断供，即使 OpenD 本身正常运行 |

### 1.3 目标

| 目标 | 指标 |
|:---|:---|
| **直连能力** | master 可配置 `FUTU_HOST` 直连香港 VPS 的 OpenD，跳过 slave HTTP 中转 |
| **模式可切换** | 支持 `local` / `remote` / `auto` 三种模式，运行时热切换 |
| **向后兼容** | 默认 `auto` 模式，行为等同于改造前 |
| **零侵入** | 上层调用方 (routers / tools / workers) 接口签名不变 |

---

## 二、架构设计

### 2.1 核心组件

| 组件 | 文件 | 职责 |
|:---|:---|:---|
| `FutuDataSource` Protocol | `services/futu/data_source.py` | 数据源统一接口定义 |
| `LocalDataSource` | 同上 | 直连 OpenD，委托 ConnectionManager + Handler |
| `RemoteDataSource` | 同上 | 通过 ClusterManager HTTP 代理调用 slave |
| `FutuSourceRouter` | `services/futu/source_router.py` | 编排 local/remote 的优先级与降级 |
| `ConnectionManager` | `services/futu/connection_manager.py` | OpenD 连接管理 + `switch_host()` |
| `FutuService` | `services/futu/service.py` | 对外统一接口，`_route()` 委托给 SourceRouter |
| Futu Admin API | `routers/futu_admin.py` | 运行时切换模式/连接目标的 HTTP 端点 |

### 2.2 数据源 Protocol

```python
class FutuDataSource(Protocol):
    @property
    def is_available(self) -> bool: ...

    @property
    def source_type(self) -> str: ...  # 'local' | 'remote'

    async def fetch(self, action: str, params: dict) -> Optional[dict]: ...

    def status(self) -> dict: ...
```

使用 Python Protocol (structural typing) 而非 ABC，避免强制继承。

### 2.3 路由模式

| 模式 | 行为 | 适用场景 |
|:---|:---|:---|
| `local` | 仅走本地直连 OpenD | master 已配置 `FUTU_HOST` 指向远程 OpenD |
| `remote` | 仅走 ClusterManager → slave HTTP | slave 有 OpenD 但 master 无法直连 |
| `auto` (默认) | 本地优先 → 本地失败降级到 remote | 通用场景，向后兼容 |

---

## 三、配置项

| 环境变量 | 默认值 | 说明 |
|:---|:---|:---|
| `FUTU_SOURCE_MODE` | `auto` | 数据源模式: `local` / `remote` / `auto` |
| `FUTU_HOST` | `127.0.0.1` | OpenD 主机地址 (local 模式下使用) |
| `FUTU_PORT` | `11111` | OpenD 端口 |
| `COLLECTOR_FUTU` | `false` | 是否启用 Futu 采集器 |

### 3.1 典型配置

**Master 直连香港 VPS (推荐)**:
```bash
# master .env
FUTU_SOURCE_MODE=local
FUTU_HOST=<香港VPS公网IP>
FUTU_PORT=11111
COLLECTOR_FUTU=true
```

**Master 通过 slave 代理**:
```bash
# master .env
FUTU_SOURCE_MODE=remote
SLAVE_NODES=http://<香港VPS_IP>:8001
```

**自动降级 (默认)**:
```bash
# master .env
FUTU_SOURCE_MODE=auto
FUTU_HOST=<香港VPS公网IP>    # 尝试直连
FUTU_PORT=11111
SLAVE_NODES=http://<香港VPS_IP>:8001  # 直连失败时降级
```

---

## 四、运行时 API

### 4.1 查询数据源状态

```
GET /api/v1/futu/source
```

响应示例:
```json
{
  "code": 0,
  "data": {
    "mode": "auto",
    "local": {
      "type": "local",
      "connected": true,
      "host": "1.2.3.4",
      "port": 11111,
      "status": "CONNECTED",
      "error_msg": ""
    },
    "remote": {
      "type": "remote",
      "available_nodes": 1,
      "total_nodes": 1,
      "nodes": [{"node_id": "slave-1", "host": "1.2.3.4", "status": "healthy"}]
    }
  }
}
```

### 4.2 切换数据源模式

```
PUT /api/v1/futu/source
Content-Type: application/json

{"mode": "local"}
```

### 4.3 切换 OpenD 连接目标

```
PUT /api/v1/futu/host
Content-Type: application/json

{"host": "1.2.3.4", "port": 11111}
```

切换会断开现有连接并尝试重新连接到新目标。

---

## 五、与 ClusterManager 的协作

```
FutuService._route()
    │
    ▼
FutuSourceRouter.route()
    │
    ├── mode=local  → LocalDataSource.fetch()
    │                   └── ConnectionManager → OpenD (FUTU_HOST:FUTU_PORT)
    │
    ├── mode=remote → RemoteDataSource.fetch()
    │                   └── ClusterManager.call_collector("futu", ...)
    │                       └── slave HTTP → slave 本地 OpenD
    │
    └── mode=auto   → 先 LocalDataSource
                       ├── 成功 → 返回
                       └── 失败 → RemoteDataSource (降级)
```

关键点:
- `LocalDataSource` 和 `RemoteDataSource` 是**平行**的两个数据源实现
- `FutuSourceRouter` 负责编排优先级，不涉及具体数据采集逻辑
- `RemoteDataSource` 内部复用现有的 `ClusterManager.call_collector()` 带 failover
- 防递归重入逻辑收口在 `RemoteDataSource._in_dispatch` 中

---

## 六、文件清单

| 文件 | 变更类型 | 说明 |
|:---|:---|:---|
| `backend/services/futu/data_source.py` | 新增 | Protocol + Local/Remote 实现 |
| `backend/services/futu/source_router.py` | 新增 | 数据源路由器 |
| `backend/services/futu/service.py` | 修改 | `_route()` 委托给 SourceRouter |
| `backend/services/futu/connection_manager.py` | 修改 | 新增 `switch_host()` |
| `backend/routers/futu_admin.py` | 新增 | 运行时切换 API |
| `backend/main.py` | 修改 | 注册 futu_admin 路由 |
