# 🛡️ Quant Agent 限流协议规范 (RATELIMIT-01)

**版本**: v2.0
**更新日期**: 2026-08-03
**状态**: ✅ 已实施 (分层分级)

---

## 📊 一、设计目标

| 层级 | 目标 | 策略 |
|------|------|------|
| **L1 Gateway** | DDoS 防御 + 暴力破解防护 | 统一 IP 限流，豁免敏感路径 |
| **L2 API Specific** | 保护高成本接口 | 按接口配额细分 |
| **L3 Business** | 业务熔断 | 特殊场景独立控制 |

---

## 🎯 二、当前实现 (已部署)

### **架构概览**

```
请求 → rate_limit_middleware
     ↓
  [Step 1] 豁免检查？→ 跳过限流 ✅
     ↓ NO
  [Step 2] 获取客户端 IP
     ↓
  [Step 3] 匹配 API 特定限流？→ 有 → 使用 API 配额
     ↓                      ↓ NO
     ↓                   使用 Gateway 默认配额
     ↓
  [Step 4] Redis incr(key) + expire
     ↓
  [Step 5] > 配额？ → 返回 429 ❌
     ↓ NO
  放行至下游服务
```

---

## 📋 三、豁免路径配置 (SKIP_PATHS)

### **原则**

1. **基础设施端点**: `/health`, `/metrics`, `/monitor` - 必须豁免 (监控/告警依赖)
2. **认证路径**: `/auth/login`, `/auth/refresh` - 必须豁免 (防死锁 + 防暴力破解)
3. **WebSocket/SSE**: `*/ws`, `*/chat/*`, `*/sse/*` - 必须豁免 (长连接特性)
4. **静态资源**: `/assets` - 必须豁免 (前端文件无需限流)

### **当前配置**

```python
SKIP_PATHS = (
    # 基础设施
    "/assets", "/monitor", "/health", "/metrics", "/mcp",
    "/openapi.json", "/docs", "/redoc",

    # 认证路径
    "/api/v1/auth/login", "/api/v1/auth/refresh",

    # WebSocket (实时推送)
    "/api/v1/market/quotes/ws",
    "/api/v1/macro/quotes/ws",
    "/api/v1/oms/quotes/ws",

    # 流式接口
    "/api/v1/chat/",
    "/api/v1/sse/",
)
```

---

## ⚙️ 四、限流配额规则

### **A. Gateway Level (全局兜底)**

```python
GATEWAY_RATE_LIMIT = 200  # 生产环境 200req/min/IP
GATEWAY_RATE_WINDOW = 60   # 1 分钟窗口
```

**适用范围**: 所有未匹配的 API

---

### **B. API Specific (按接口细分)**

| 接口路径 | 配额 | 理由 | 来源 |
|---------|------|------|------|
| `/api/v1/market/quote` | 60req/min | Futu OpenD 限制 (防 429) | 供应商文档 |
| `/api/v1/macro/calendar` | 30req/min | 宏观数据源限流 | FRED/Finnhub |
| `/api/v1/screener/screen` | 20req/min | 复杂 SQL 查询成本高 | 内部优化 |
| `/api/v1/chat/completions` | 10req/min | LLM Token 消耗大 | AI 引擎 |
| `/api/v1/backtest/run` | 5req/min | 回测计算密集 | 资源保护 |

**Python 定义**:
```python
API_SPECIFIC_LIMITS = {
    "/api/v1/market/quote": (60, 60),       # 1req/sec
    "/api/v1/macro/calendar": (30, 60),     # 30req/min
    "/api/v1/screener/screen": (20, 60),    # 20req/min
    "/api/v1/chat/completions": (10, 60),   # 10req/min
    "/api/v1/backtest/run": (5, 60),        # 5req/min
}
```

---

## 🔍 五、限流 Key 生成策略

### **Key 模板**

```python
# API 特定限流
key = f"rate_limit:{path}:{client_ip}"
# 示例: rate_limit:/api/v1/market/quote:192.168.1.100

# 说明:
# - path: 完整 URL 路径 (区分不同接口)
# - client_ip: 客户端真实 IP (request.client.host)
# - separator: : (冒号分隔符)
```

### **TTL 设置**

```python
# API 特定 → 使用该接口的 window (如 60 秒)
# Gateway 默认 → 使用 GATEWAY_RATE_WINDOW (60 秒)
await pipe.expire(key, window, nx=True)
```

---

## 🚨 六、异常处理 (Fail-Safe)

### **Redis 不可用时的行为**

```python
try:
    async with redis_client.pipeline() as pipe:
        ...
except Exception as e:
    # ✅ 拒绝所有非豁免请求 (而非静默放行)
    raise HTTPException(status_code=503, detail="限流服务不可用")
```

**原因分析**:

| 方案 | 优点 | 缺点 | 推荐度 |
|------|------|------|--------|
| **静默放行** | 服务可用 | 无限攻击风险 | ❌ 禁用 |
| **返回 503** | 主动防御 | 临时影响可用性 | ✅ 推荐 |
| **记录日志后放行** | 可追溯 | 仍有攻击风险 | ⚠️ 次选 |

**决策逻辑**:

```
限流服务故障 → 无法判断请求频率 → FAIL-SAFE (拒绝服务)
```

---

## 🧪 七、测试建议

### **单元测试**

```python
# tests/test_rate_limit.py

async def test_gateway_exemption_paths():
    """豁免路径不应触发限流"""
    for path in SKIP_PATHS:
        response = client.get(path)
        assert response.status_code != 429

async def test_api_specific_limits():
    """特定 API 应有独立配额"""
    # 调用 /market/quote 61 次 → 应返回 429
    for _ in range(61):
        response = client.get("/api/v1/market/quote?symbol=AAPL")
    assert response.status_code == 429

    # 同时调用 /chat/completions 应不受影响
    response = client.post("/api/v1/chat/completions", ...)
    assert response.status_code == 200

async def test_redis_fail_safe():
    """Redis 故障时返回 503"""
    # 停止 Redis
    mocker.patch("backend.core.redis_client.redis_client.pipeline", side_effect=Exception())

    response = client.get("/api/v1/market/quote?symbol=AAPL")
    assert response.status_code == 503
```

---

## 📈 八、监控指标

### **Prometheus 暴露**

```yaml
# metrics/limit_status
rate_limit_hits_total{path="/api/v1/market/quote", ip="x.x.x.x"} 42
rate_limit_denied_total{path="/api/v1/market/quote", ip="x.x.x.x"} 3
```

### **告警规则**

```yaml
groups:
  - name: ratelimit_alerts
    rules:
      - alert: HighRateLimitHits
        expr: rate(rate_limit_hits_total[5m]) > 100
        annotations:
          summary: "高频率限流触发：{{ $labels.path }}"
```

---

## 🔄 九、动态调整机制

### **环境变量配置**

```bash
# .env 或 Docker Compose
QUANT_ENV=production  # production | development
GATEWAY_RATE_LIMIT=200
# 未来可扩展 API 配额动态配置
```

### **运行时更新**

```python
@router.put("/api/v1/system/rate-limit-config")
async def update_rate_limit_config(
    config: RateLimitConfig,
    admin: User = Depends(get_current_admin)
):
    """管理员动态调整限流配额"""
    API_SPECIFIC_LIMITS.update(config.new_limits)
    return {"status": "updated"}
```

---

## 📝 十、最佳实践建议

### **制定配额规则的 Checklist**

- [ ] **查阅官方文档**: 第三方 API (Futu/FRED/Finnhub) 的限流表
- [ ] **评估内部成本**: SQL 复杂度、LLM Token 消耗、CPU 占用
- [ ] **观察历史数据**: 过去 7 天 QPS 分布 (P95/P99)
- [ ] **考虑用户体验**: 是否满足正常业务场景？(如图表加载需多次请求)
- [ ] **预留缓冲空间**: 阈值设置比实测 P99 高 20-30%
- [ ] **添加 Retry-After**: 响应体中告知用户何时重试

### **常见错误**

❌ **一刀切**: 所有 API 使用相同配额 → 高成本接口被拖垮
✅ **分区配额**: 按接口重要性差异化

❌ **IP+User 混合**: 登录用户和访客混同统计 → 付费用户被误杀
✅ **分层限流**: 基于 JWT scope 分配不同配额

❌ **Redis 单点故障无保护**: 限流失效导致无限调用
✅ **Fail-Safe**: Redis 异常时拒绝服务

---

## 📚 十一、相关文件

| 文件 | 说明 |
|------|------|
| `backend/middleware/stack.py` | 限流中间件实现 |
| `backend/services/datasource/adapters/*.py` | 数据源层限流 (二级保护) |
| `backend/workers/market/daemon.py` | 守护进程采集器限流 |
| `backend/adapters/futu/futu_adapter.py` | Futu Adapter 自限流 |

---

**最后更新**: 2026-08-03
**维护者**: @songlinhe5-lab
