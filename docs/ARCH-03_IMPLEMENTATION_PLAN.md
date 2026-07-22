# ARCH-03: Graceful Shutdown 实施计划

## 🎯 任务目标
在系统关闭时确保所有后台任务正常完成，避免数据丢失或连接泄漏。

## 📊 当前诊断

### 🔴 现有问题清单

| 组件 | 当前实现 | 风险等级 | 问题描述 |
|:-----|:---------|:---------|:---------|
| ThreadPoolExecutor | `executor.shutdown(wait=False)` | 🔴 High | 立即终止，不等待运行中的任务 |
| yfinance._executor | 同步 close()，无 await 包装 | 🟡 Medium | 无法等待异步上下文中的任务完成 |
| Redis 连接池 | `await redis_client.aclose()` | 🟡 Medium | 可能有未刷新的批量写入队列 |
| Futures/Task 取消 | 直接 cancel() + gather | 🟢 Low | 缺少超时保护可能导致挂起 |
| Session 关闭 | `requests.Session.close()` | 🟢 Low | 同步操作，阻塞主线程 |

### 📝 风险评估

1. **高优先级 (High)**:
   - ThreadPoolExecutor 立即关闭可能导致正在执行的行情拉取中断
   - Redis 批量队列未完成刷新导致数据丢失

2. **中优先级 (Medium)**:
   - yfinance Fallback 机制可能导致缓存不一致
   - Futu WebSocket 推送任务中断

3. **低优先级 (Low)**:
   - 数据库连接池释放问题较小

---

## 🛠️ 实施方案

### Phase 1: 核心改进 (Priority: 🔴)

#### 1.1 ThreadPoolExecutor 优雅关闭

**目标**: 等待所有提交的任务完成后再关闭

```python
# backend/core/circuit_breaker.py → new file
import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

class GracefulExecutor(ThreadPoolExecutor):
    """支持异步优雅关闭的线程池"""
    
    def __init__(self, *args, max_wait_s: int = 30, **kwargs):
        super().__init__(*args, **kwargs)
        self.max_wait_s = max_wait_s
    
    async def graceful_shutdown(self):
        """异步优雅关闭：等待所有任务完成"""
        # Python 3.9+ 支持 shutdown(wait=True, timeout=X)
        if hasattr(self, 'shutdown'):
            try:
                loop = asyncio.get_running_loop()
                # 使用 run_in_executor 模拟 timeout
                done, pending = await asyncio.wait(
                    {asyncio.get_event_loop().run_in_executor(None, self.shutdown, True)},
                    timeout=self.max_wait_s
                )
                
                if pending:
                    print(f"⚠️ Executor 关闭超时 ({self.max_wait_s}s)，强制终止")
            except Exception as e:
                print(f"⚠️ Executor 关闭失败：{e}")
```

**应用位置**:
- `backend/services/yfinance/service.py` → `_executor` 替换为 `GracefulExecutor`
- `backend/bootstrap/lifecycle.py` → 添加 `await executor.graceful_shutdown()`

---

#### 1.2 Redis 批量队列完善

**目标**: 确保所有待刷新的数据都写入 Redis 后才关闭连接

**现状分析**:
```python
# backend/core/redis_batch_writer.py (假设存在)
queue = asyncio.Queue()

async def writer():
    while True:
        item = await queue.get()
        await redis_client.setex(...)
```

**改进方案**:
```python
async def graceful_redis_shutdown():
    """等待 Redis 队列清空后关闭"""
    await redis_batch_writer.stop()  # 触发队列刷新
    
    # 额外安全检查：等待队列完全为空
    for _ in range(10):  # 最多等待 10s
        if redis_queue.empty():
            break
        await asyncio.sleep(1)
    
    await redis_client.aclose()
```

---

#### 1.3 Task 取消超时保护

**目标**: 防止 task 无法响应 cancel() 导致系统 hang 住

**改进前**:
```python
nav_snapshot_task.cancel()
tasks_to_await.append(nav_snapshot_task)
await asyncio.gather(*tasks_to_await, return_exceptions=True)
```

**改进后**:
```python
shutdown_tasks = []

for task_name in ['nav_snapshot_task', 'oms_position_task', ...]:
    task = locals()[task_name]
    if not task.done():
        task.cancel()
        shutdown_tasks.append(task)

# 设置 60 秒全局超时
try:
    await asyncio.wait_for(
        asyncio.gather(*shutdown_tasks, return_exceptions=True),
        timeout=60.0
    )
except asyncio.TimeoutError:
    print("⚠️ Shutdown 超时，强制退出")
```

---

### Phase 2: 数据源服务优化 (Priority: 🟡)

#### 2.1 YFinanceService 异步 close()

**目标**: 支持 awaitable 关闭，便于 lifespan 集成

```python
# backend/services/yfinance/service.py

async def async_close(self):
    """异步版本的 close()，支持等待 executor 任务完成"""
    # 1. 停止 Session 复用
    if hasattr(self, "session"):
        self.session.close()
    
    # 2. 优雅关闭线程池
    if hasattr(self, "_executor"):
        if isinstance(self._executor, GracefulExecutor):
            await self._executor.graceful_shutdown()
        else:
            # Fallback: 普通线程池
            self._executor.shutdown(wait=True)
    
    # 3. 关闭路由器 HTTP 客户端
    if self._router is not None:
        await self._router.close()
        self._router = None
    
    print("✅ YFinanceService 已完全关闭")
```

**集成到 lifespan**:
```python
# lifecycle.py
try:
    from backend.services.yfinance.service import yf_service
    await yf_service.async_close()
except Exception as e:
    logger.warning(f"YFinance shutdown failed: {e}")
```

---

#### 2.2 FutuService WebSocket 优雅断开

**目标**: 确保推送任务正常结束，避免僵尸进程

```python
# backend/services/futu/service.py

async def async_close(self):
    """优雅关闭 Futu 连接"""
    if hasattr(self, "_ws") and self._ws and not self._ws.closed:
        await self._ws.close()
    
    # 通知 push_handler 停止推送
    futu_push_handler.stop_pushing()
    
    time.sleep(0.5)  # 等待推送任务自然退出
```

---

### Phase 3: 监控与日志增强 (Priority: 🟢)

#### 3.1 Shutdown 时间线追踪

**实现**:
```python
import time
from contextlib import asynccontextmanager

shutdown_timer = {"start": None, "steps": []}

def log_step(name):
    elapsed = time.time() - shutdown_timer["start"]
    shutdown_timer["steps"].append(f"{name}: {elapsed:.2f}s")

@asynccontextmanager
async def app_lifespan(app):
    # ... startup ...
    
    yield
    
    # === Shutdown ===
    shutdown_timer["start"] = time.time()
    log_step("Shutdown started")
    
    # ... 各组件关闭逻辑 ...
    
    total_time = time.time() - shutdown_timer["start"]
    log_step(f"Total shutdown time: {total_time:.2f}s")
    
    for step in shutdown_timer["steps"]:
        logger.info(f"[Shutdown Timeline] {step}")
```

---

#### 3.2 Prometheus Metrics（可选）

```python
from prometheus_client import Counter, Gauge

SHUTDOWN_DURATION_SECONDS = Counter(
    'system_shutdown_duration_seconds',
    '总关闭耗时'
)

SHUTDOWN_STEPS_GAUGE = Gauge(
    'shutdown_step_complete',
    '已完成关闭的步骤',
    ['component']
)
```

---

## ✅ 验收标准

### 必须满足 (P0)

- [ ] ThreadPoolExecutor 关闭时所有任务完成（≤30s）
- [ ] Redis 批量队列清空后才断开连接
- [ ] 系统关闭时间 ≤90s（含所有组件）
- [ ] 无未处理的异常导致进程崩溃

### 建议满足 (P1)

- [ ] 每个组件都有清晰的 shutdown 日志
- [ ] 提供 shutdown 时间线追踪
- [ ] Prometheus 指标集成

---

## 🧪 测试方案

### Unit Tests

```python
# backend/tests/unit/test_graceful_shutdown.py

@pytest.mark.asyncio
async def test_executor_waits_for_tasks():
    """验证 Executor 等待所有任务完成"""
    executor = GracefulExecutor(max_workers=2, max_wait_s=10)
    
    def slow_task():
        time.sleep(5)
        return "done"
    
    # 提交慢任务
    future = executor.submit(slow_task)
    
    # 立即关闭
    await executor.graceful_shutdown()
    
    assert future.result() == "done"

@pytest.mark.asyncio
async def test_redis_queue_flushed_before_close():
    """验证 Redis 队列清空后连接才断开"""
    await redis_batch_writer.push("key", "value")
    await redis_batch_writer.stop()  # Should flush queue
    
    # Verify queue empty
    assert redis_queue.empty()
```

### Integration Tests

```python
async def test_full_system_shutdown():
    """完整系统关闭测试"""
    async with lifespan(app):
        # Simulate active requests
        pass
    
    # Should complete within 90s
    assert total_shutdown_time <= 90.0
    
    # All components properly closed
    assert yf_service._executor is None
    assert redis_client.connection_pool is None
```

---

## 📅 实施时间表

| 阶段 | 任务 | 预估时间 | 状态 |
|:-----|:-----|:---------|:-----|
| **Phase 1** | ThreadPoolExecutor 改进 | 1h | ⏸️ Pending |
| **Phase 1** | Redis 批量队列完善 | 1h | ⏸️ Pending |
| **Phase 1** | Task 取消超时保护 | 30min | ⏸️ Pending |
| **Phase 2** | YFinanceService async_close | 1h | ⏸️ Pending |
| **Phase 2** | FutuService WebSocket 关闭 | 1h | ⏸️ Pending |
| **Phase 3** | 监控与日志增强 | 1h | ⏸️ Pending |
| **Total** | | **6h** | |

---

## 🎓 参考资料

- FastAPI Lifespan Docs: https://fastapi.tiangolo.com/advanced/events/
- Python ThreadPoolExecutor: https://docs.python.org/3/library/concurrent.futures.html
- Redis Connection Pool: https://redis.readthedocs.io/en/stable/connections.html
- Graceful Shutdown Best Practices: https://aws.amazon.com/blogs/architecture/graceful-shutdowns-in-microservices/
