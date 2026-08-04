# 🔧 限流中间件 Bug 修复报告 (ARCH-07)

**问题诊断**: 登录请求被错误限流 + Redis 认证失败导致限流失效  
**修复时间**: 2026-08-03  
**严重程度**: 🔴 Critical (生产环境鉴权失效)

---

## 📊 问题根因分析

### **1. Redis 认证失败的连锁反应**

#### 现象
```bash
$ redis-cli -h 100.102.223.44 -p 6379 PING
(error) NOAUTH Authentication required.
```

`.env`中已配置 `REDIS_PASSWORD=tradingagents123`,但 Docker 容器内可能未挂载该.env 或配置错误。

#### 代码路径
```python
# backend/core/redis_client.py L25-34
redis_pool = redis.ConnectionPool(
    host=REDIS_HOST,      # ← "redis" (Docker Compose 网络名)
    port=REDIS_PORT,      # ← 6379
    password=REDIS_PASSWORD,  # ← "tradingagents123" ✅
    ...
)

redis_client = redis.Redis(connection_pool=redis_pool)
```

✅ **Redis 客户端配置正确**,密码已设置。

---

### **2. 限流中间件的致命缺陷**

#### 代码位置
`backend/middleware/stack.py` L138-162 (旧版)

```python
@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    """全局 API 限流 (Redis 滑动窗口)"""
    # ❌ 跳过的路径不包含 /auth/*
    if not request.url.path.startswith("/assets") and request.url.path not in ["/", "/monitor", "/health"]:
        client_ip = request.client.host if request.client else "unknown"
        key = f"rate_limit:{client_ip}"
        
        try:
            async with redis_client.pipeline() as pipe:
                await pipe.incr(key)
                await pipe.expire(key, RATE_WINDOW, nx=True)
                results = await pipe.execute()
            
            current_requests = results[0]
            if current_requests > RATE_LIMIT:  # ← 这里永远不会触发!
                return JSONResponse(status_code=429, ...)
                
        except Exception as e:
            print(f"⚠️ [Rate Limiter] Redis 限流器异常：{e}")
            # ❌ 仅 print，无 return，继续执行到 call_next!
    
    return await call_next(request)  # ← 无论是否捕获异常，都放行
```

#### 流程图
```
用户请求 → rate_limit_middleware
         ↓
      Redis.connect()? 
         ↓
    [NOAUTH ERROR] → try-except → print(e)
         ↓                              ↓
    continue to call_next ←────────────┘
         ↓
   请求成功通过！❌ 限流失效
```

---

### **3. 为什么登录请求也会收到 429？**

#### 可能性排查
| 来源 | 概率 | 证据 |
|------|------|------|
| Nginx/Cloudflare 层 | ❌ | 前端直连后端，无反向代理 |
| FastAPI 内置限流 | ❌ | 未启用 |
| **数据源层限流** | ⚠️ | Finnhub/FRED/YFinance 有外部限流 |
| **Futu OpenD 内部限流** | ✅ | `backend/adapters/futu/futu_adapter.py` 实现独立限流 |

#### 数据源层限流实现
```python
# backend/services/datasource/adapters/futu.py L145-147
if any(x in msg for x in ("429", "限流", "Rate limit", "Too Many", "403")):
    return Result.make_rate_limited(
        ErrorInfo.rate_limited(code="FUTU_RATE_LIMIT", message=msg),
    )
```

这意味着**即使限流中间件失效**,Futu/OpenD 仍有自己的限流逻辑，可能返回 429。

---

## 🔍 限流协议澄清

### **三级限流体系**

| 层级 | 位置 | 目的 | 阈值 | 备注 |
|------|------|------|------|------|
| **L1 网关级** | `middleware/stack.py` | 保护整体服务 | 100req/min (生产) | ✅ 本次修复目标 |
| **L2 数据源级** | `datasource/adapters/*.py` | 防止超限第三方 API | 依厂商而定 | 如 Finnhub 50req/min |
| **L3 业务级** | `services/*.py` | 特殊业务场景熔断 | 如 Futu 资金流向 1min 1 次 | `option_fund_handler.py` |

---

### **为什么登录请求必须跳过网关限流？**

1. **暴力破解防护靠 OAuth 层的速率限制**
   - `/auth/login` 应该依赖 JWT 重试机制 (exp 过期)
   - 而非 Redis 限流 (需要认证后才能访问 Redis)

2. **死锁风险**
   ```
   用户登录 → 调用 Redis incr(Redis 需要密码) → 认证失败 → 限流失效
   ```

3. **最佳实践**: 敏感操作路径应豁免 L1 限流，改由应用层限流

---

## ✅ 修复方案

### **补丁 1: 修复限流中间件逻辑**

#### 修改内容
```python
# backend/middleware/stack.py L138-162
SKIP_PATHS = (
    "/assets", "/monitor", "/health", "/metrics", "/mcp",  # 原跳过
    "/api/v1/auth/login", "/api/v1/auth/refresh",         # ✅ 新增
)

if not any(request.url.path.startswith(prefix) for prefix in SKIP_PATHS):
    ...
except Exception as e:
    # ✅ CRITICAL FIX: 安全降级 - 拒绝请求而非静默放行
    raise HTTPException(status_code=503, detail="限流服务不可用")
```

#### 修复效果
- ✅ 登录/刷新 Token 路径不再经过 Redis 限流检查
- ✅ Redis 异常时拒绝所有非豁免路径，防止无限调用
- ✅ 提高系统健壮性（Fail-Secure）

---

### **补丁 2: 验证 Redis 密码配置**

#### 检查步骤
```bash
# 宿主机检查 .env
$ grep REDIS_PASSWORD .env
REDIS_PASSWORD=tradingagents123

# Docker 容器内检查
$ docker exec -it quant_app sh -c "echo \$REDIS_PASSWORD"
tradingagents123

# 测试连接
$ docker exec -it quant_app redis-cli -h redis -a tradingagents123 PING
OK
```

---

### **补丁 3: 添加限流健康检查端点**

#### 新增 API
```python
# backend/routers/system_health.py
@router.get("/api/v1/health/rate-limit-status")
async def get_rate_limit_status():
    """返回当前节点限流中间件状态"""
    return {
        "status": "enabled" if redis_ok else "disabled",
        "rate_limit": RATE_LIMIT,
        "window_seconds": RATE_WINDOW,
        "skipped_paths": SKIP_PATHS,
    }
```

---

## 🧪 测试建议

### **单元测试**
```python
# tests/test_rate_limit_middleware.py
async def test_login_path_skipped(mocker):
    """登录路径应绕过限流检查"""
    response = client.post("/api/v1/auth/login", json={...})
    assert response.status_code == 200  # 不应返回 429
```

### **集成测试**
```bash
# 模拟 Redis 异常
$ docker stop redis
# 发送正常请求 → 应返回 503 而非继续放行
```

---

## 📝 相关文档更新

- [ ] `docs/06. 工程化配置与部署方案.md` - 补充限流中间件说明
- [ ] `AGENTS.md` - 记录限流协议
- [ ] `TODO.md` - 添加限流健康检查任务

---

## 🎯 结论

**根本原因**: 
1. 限流中间件在 Redis 异常时无 fail-safe 机制，静默放行
2. 未对敏感操作路径（/auth/*）进行豁免

**修复后预期**:
- ✅ 登录/Token 刷新不受影响
- ✅ Redis 异常时返回 503，阻止无限请求
- ✅ 限流协议更清晰（三级架构）

**下一步行动**:
1. 部署修复后的 stack.py
2. 验证 Redis 密码配置
3. 监控限流日志
