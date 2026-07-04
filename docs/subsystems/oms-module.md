# OMS 订单中枢与算力节点设计文档

## 1. 架构概览

OMS 是系统的交易执行核心，负责订单全生命周期管理、策略运行时调度与全局风控熔断。

```
┌─────────────────────────────────────────────────────────────────────┐
│                        展示层 (Presentation)                         │
│  oms.tsx ─── Bot卡片 / 挂单表 / 成交表 / 算法进度 / KillSwitch       │
│            ↕ WebSocket (Redis PubSub 驱动)                           │
├─────────────────────────────────────────────────────────────────────┤
│                        逻辑层 (Domain)                               │
│  OMS Service ─── 订单状态机 / 算力节点管理 / 算法拆单引擎             │
│                  ↕ Redis PubSub (oms:* 通道)                         │
├─────────────────────────────────────────────────────────────────────┤
│                        数据接口层 (Gateway)                           │
│  trade.py ─── Futu SDK 封装 / ATR 动态风控 / 杠杆校验               │
│               ↕ Futu OpenD (ZeroMQ)                                 │
├─────────────────────────────────────────────────────────────────────┤
│                        持久化层 (Storage)                             │
│  PostgreSQL ─── orders / trade_logs / algo_tasks / audit_logs        │
│  Redis ─── 实时状态缓存 / PubSub 广播 / 幂等性锁                     │
└─────────────────────────────────────────────────────────────────────┘
```

## 2. 数据流设计

### 2.1 真实订单流

```
前端/Agent 发单
    ↓ POST /api/v1/trade/order
trade.py: 杠杆风控校验 → ATR 动态止损测算
    ↓ 校验通过
Futu SDK: ctx.place_order() → 交易所
    ↓ 成交回报
写入 PostgreSQL (orders + trade_logs)
    ↓ Redis PubSub: oms:orders:update / oms:trades:new
WebSocket 广播 → 前端实时更新
```

### 2.2 状态推送流

```
Futu 回调 (成交/撤单/改单)
    ↓
OMS Service 更新 DB + Redis 缓存
    ↓ redis_client.publish("oms:*", payload)
WebSocket Handler (oms.py /ws)
    ↓ 消息路由包装
前端 onmessage → 按 type 分发到对应 state
```

### 2.3 算力节点流

```
策略研发 → 部署至 OMS (POST /strategy/deploy-to-oms)
    ↓
OMS Service: 创建子进程/asyncio.Task 执行策略
    ↓ 注册 Bot 元数据 (id/name/ticker/status)
psutil 采集 CPU/MEM → Redis Hash (quant:oms:bot:{id}:stats)
策略日志 → Redis List (quant:oms:bot:{id}:logs)
    ↓ PubSub 广播
WebSocket → 前端 Bot 卡片实时渲染
```

## 3. 当前能力清单 (v0.2)

### 3.1 已完成 (OMS 面板 + 真实数据接入)

| 能力 | 文件 | 状态 |
|:---|:---|:---|
| **订单持久化** | `oms_service.py` + `models.Order` | ✅ PostgreSQL orders 表，下单/撤单/改单同步写入 |
| **成交记录打通** | `oms_service.py` + `models.TradeLog` | ✅ OMS 面板从 DB 读取真实成交 |
| **真实订单状态同步** | `oms_service.py` + `trade.py` | ✅ Futu 下单后写入 DB + Redis PubSub 广播 |
| **持仓实时同步** | `oms_service.py` + `main.py` daemon | ✅ 30秒定时拉取 Futu 持仓写入 Redis |
| **Bot 算力节点运行时** | `bot_runtime.py` + `oms.py` | ✅ OMS-05~07: asyncio.Task 生命周期 + psutil CPU/MEM + Redis 日志 |
| **算法拆单引擎** | `algo_engine.py` + `oms.py` | ✅ OMS-08~09: TWAP/VWAP/ICEBERG 真实拆单 + Redis 进度持久化 + PubSub 广播 |
| **Kill Switch 安全加固** | `oms.tsx` + `confirm-dialog.tsx` | ✅ OMS-10: ConfirmDialog + CLOSE ALL 文字确认 |
| WebSocket 实时推送 | `oms.py /ws` + Redis PubSub | ✅ 新增 positions:update 通道 |
| 幂等性撤单锁 | `oms.py cancel_order` | ✅ Redis NX 锁 + DB 状态同步 |
| 真实持仓 Tab | `oms.tsx` | ✅ 控制台新增「真实持仓」Tab |

### 3.2 已完成 (真实交易链路)

| 能力 | 文件 | 状态 |
|:---|:---|:---|
| Futu 真实下单 | `trade.py place_order` | 已对接 Futu SDK |
| ATR 动态风控止损 | `trade.py` | 2x ATR 止损价测算 |
| 杠杆风控校验 | `trade.py` | 实时账户总资产 × 最大杠杆 |
| 高波动率资产降杠杆 | `trade.py` | 日均振幅 >5% 强制 1.0x |
| 真实账户/持仓查询 | `trade.py /account /portfolio` | Futu 直连 |
| 交易日志持久化 | `models.TradeLog` + `trade.py /trades` | PostgreSQL |
| Hermes Agent 交易 Tool | `broker_trade_tool.py` | Agent 可通过 Tool 发单 |

### 3.2 核心问题 (已部分解决)

- ~~**OMS 面板与真实交易完全脱节**~~: ✅ OMS-01~03 已桥接，下单/撤单/改单同步写入 DB + PubSub
- ~~**无订单状态机**~~: ✅ `models.Order` 表已存在，状态追踪 SUBMITTED → FILLED/CANCELLED
- ~~**Bot 算力节点纯 Mock**~~: ✅ OMS-05~07 已完成: `bot_runtime.py` 真实 asyncio.Task + psutil + Redis 日志
- ~~**算法拆单空壳**~~: ✅ OMS-08~09 已完成: `algo_engine.py` TWAP/VWAP/ICEBERG 真实拆单 + Redis 进度持久化
- ~~**Kill Switch 安全薄弱**~~: ✅ OMS-10 已完成: ConfirmDialog + CLOSE ALL 文字确认替代 window.confirm

## 4. 进阶能力 TODO List (v0.2+)

### 4.1 ~~P1 - 核心闭环 (真实数据接入)~~ ✅ 已完成

- [x] ~~**[OMS-01]** 订单持久化~~：✅ `oms_service.create_order()` + `models.Order` 表
- [x] ~~**[OMS-02]** 成交记录打通~~：✅ `oms_service.get_historical_trades()` 从 `trade_logs` 读取
- [x] ~~**[OMS-03]** 真实订单状态同步~~：✅ `trade.py` 下单后写入 DB + PubSub + 撤单/改单同步
- [x] ~~**[OMS-04]** 持仓实时同步~~：✅ `_oms_position_sync_daemon` 每 30 秒拉取 Futu 持仓

### 4.2 ~~P2 - 算力节点 (策略运行时)~~ ✅ 已完成

- [x] ~~**[OMS-05]** 策略运行时引擎~~：✅ `bot_runtime.py` BotRuntimeManager + asyncio.Task 生命周期管理
- [x] ~~**[OMS-06]** Bot 真实资源监控~~：✅ `psutil.Process` 采集真实 CPU/MEM
- [x] ~~**[OMS-07]** Bot 日志持久化~~：✅ Redis List + PubSub 广播 + WebSocket 实时推送

### 4.3 ~~P2 - 算法拆单引擎~~ ✅ 已完成

- [x] ~~**[OMS-08]** TWAP/VWAP 真实执行引擎~~：✅ `algo_engine.py` asyncio.Task 拆单 + 行情模拟成交 + PubSub 广播
- [x] ~~**[OMS-09]** 算法执行进度持久化~~：✅ Redis Hash 活动进度 + List 归档已完成任务 (7天 TTL)

### 4.4 ~~P2 - 安全与体验~~ ✅ 已完成

- [x] ~~**[OMS-10]** Kill Switch 安全加固~~：✅ `confirm-dialog.tsx` 新增 `requireInputConfirm` + CLOSE ALL 文字确认
- [x] ~~**[OMS-11]** 沙箱/实盘模式切换~~：✅ `/oms/mode` + `/oms/mode/switch` + 前端 SANDBOX/LIVE 横幅
- [x] ~~**[OMS-12]** 订单审计日志~~：✅ 所有 OMS 端点 (撤单/改单/熔断/算法/模式切换) 接入 `audit_service.log_audit()`

## 5. Redis 键空间约定

| 键模式 | 类型 | 用途 | TTL |
|:---|:---|:---|:---|
| `quant:oms:status` | String | 全局状态 (NORMAL/KILLED) | 3600s |
| `quant:oms:active_orders` | String (JSON) | 活动挂单缓存列表 | 300s |
| `quant:oms:positions:{market}` | String (JSON) | 真实持仓缓存 | 30s |
| `quant:oms:bot:{bot_id}:stats` | Hash | Bot 资源占用 (cpu/mem/status) | 15s |
| `quant:oms:bot:{bot_id}:logs` | List | Bot 运行日志 (最近 200 条) | 86400s |
| `quant:oms:algo:{algo_id}` | Hash | 算法拆单进度 (target/filled/avg_price/status) | 86400s |
| `quant:oms:cancel_lock:{idempotency_key}` | String | 撤单幂等性锁 (NX) | 60s |

### PubSub 通道

| 通道 | 消息格式 | 用途 |
|:---|:---|:---|
| `oms:bots:update` | `Bot[]` JSON | 广播 Bot 列表变更 |
| `oms:orders:update` | `Order[]` JSON | 广播活动挂单变更 |
| `oms:trades:new` | `Trade` JSON | 广播新成交 |
| `oms:bot_log:stream` | `{bot_id, log}` JSON | 广播 Bot 日志 |
| `oms:algo_executions:update` | `AlgoExecution[]` JSON | 广播算法进度 |
| `oms:kill_switch` | `"ENGAGE"` | 全局熔断信号 |
| `oms:positions:update` | `{market, positions[]}` JSON | 广播持仓变更 |

## 6. 安全规范

| 场景 | Web 前端 | 移动端 (Flutter) |
|:---|:---|:---|
| 沙箱下单 | 直接执行，显示 SANDBOX 标识 | 直接执行，显示 SANDBOX 标识 |
| 实盘下单 | ConfirmDialog 二次确认 | 生物识别 + 二次确认 |
| 全部平仓 (Kill Switch) | 输入 "CLOSE ALL" + ConfirmDialog | 输入 "CLOSE ALL" + 生物识别 |
| 模式切换 (SANDBOX/LIVE) | 顶部横幅颜色变化 + 二次确认 | ModeBanner 颜色变化 + 震动 |
| 撤单/改单 | 行内按钮 + 幂等性锁 | 滑动确认 |

## 7. 文件映射

| 文件 | 职责 |
|:---|:---|
| `backend/services/oms_service.py` | **OMS 核心服务层** (OMS-01~04): 订单持久化 + 持仓同步 + PubSub 广播 |
| `backend/services/bot_runtime.py` | **算力节点运行时** (OMS-05~07): Bot 生命周期 + psutil 监控 + Redis 日志 |
| `backend/routers/oms.py` | OMS API 路由 + WebSocket 推送 + Bot 控制接口 |
| `backend/routers/trade.py` | 真实交易下单 + 风控校验 + 订单持久化 |
| `backend/routers/strategy.py` | `/deploy-to-oms` 策略部署 + Bot 启动 |
| `backend/services/algo_engine.py` | **算法拆单引擎** (OMS-08~09): TWAP/VWAP/ICEBERG 拆单 + Redis 进度持久化 |
| `backend/core/models.py` | Order / TradeLog / AuditLog 数据模型 |
| `backend/services/audit_service.py` | 审计日志写入 (OMS-12 对接) |
| `frontend/src/features/trading/oms.tsx` | OMS 前端面板 (Bot 卡片 + 挂单/成交/算法/持仓 Tab) |
| `hermes_agent/tools/broker_trade_tool.py` | Agent 交易 Tool (调用 `/trade/order`) |
