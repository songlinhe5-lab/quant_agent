# 数据源延迟统计功能实施计划

## 📋 背景

当前系统存在以下问题：
1. ✅ **已解决**: 前端显示 0ms 误导用户 (Phase 1)
2. ⏳ **进行中**: 后端不记录延迟分布 (Phase 2)
3. 📋 **待实施**: 缺乏完整的监控指标体系 (Phase 3)

---

## ✅ Phase 1: 前端显示优化 (已完成)

**提交**: `3195243` - fix(ui): 数据源健康看板延迟显示优化

**改动文件**:
- `frontend/src/features/data-center/datasource-health.tsx`

**关键修改**:
```typescript
// 修复前
{c.latency_ms ? `${c.latency_ms.toFixed(0)} ms` : '—'}

// 修复后
{c.latency_ms != null && c.latency_ms > 0 
  ? `${c.latency_ms.toFixed(0)} ms` 
  : 'N/A'}
```

**效果**:
- 当无延迟数据时显示 "N/A" 而非 "0ms"
- 用户体验更清晰

---

## 🔄 Phase 2: 实现延迟统计功能 (进行中)

### 目标

在后端实现延迟数据的收集和统计，支持：
- 记录每次请求的延迟
- 计算 P50/P95/P99 分位数
- 持久化到 Redis（按自然日分桶）

### 设计方案

#### 1. Redis 键空间设计

```
quant:metrics:{source}:latency:{date}
  type: Redis List
  ttl: 7 days
  max_length: 1000 samples
  
示例:
  quant:metrics:finnhub:latency:2026-08-04
    - 150.5
    - 200.3
    - 180.2
    - ...
```

#### 2. CallMetricsStore 扩展

```python
# backend/services/datasource/call_metrics_store.py

class CallMetricsStore:
    async def record_business(
        self, 
        source: str, 
        outcome: str, 
        category: str = None,
        latency_ms: float = None  # ← 新增参数
    ):
        """记录业务调用时同时记录延迟"""
        date = _local_date_key()
        
        # 原有逻辑
        await self._incr(source, "calls")
        if outcome == "success":
            await self._incr(source, "success")
        # ...
        
        # 新增：记录延迟
        if latency_ms is not None and latency_ms > 0:
            key = f"quant:metrics:{source}:latency:{date}"
            await redis_client.lpush(key, latency_ms)
            await redis_client.ltrim(key, 0, 999)  # 保留最近 1000 个样本
            await redis_client.expire(key, 7 * 86400)  # 7 天过期
    
    async def get_latency_stats(self, source: str) -> Dict[str, float]:
        """获取延迟统计"""
        date = _local_date_key()
        key = f"quant:metrics:{source}:latency:{date}"
        
        samples = await redis_client.lrange(key, 0, -1)
        if not samples:
            return {
                "avg_ms": None,
                "p50_ms": None,
                "p95_ms": None,
                "p99_ms": None,
                "min_ms": None,
                "max_ms": None,
                "samples": 0,
            }
        
        samples = [float(s) for s in samples]
        samples.sort()
        
        return {
            "avg_ms": sum(samples) / len(samples),
            "p50_ms": samples[int(len(samples) * 0.5)],
            "p95_ms": samples[int(len(samples) * 0.95)],
            "p99_ms": samples[int(len(samples) * 0.99)],
            "min_ms": min(samples),
            "max_ms": max(samples),
            "samples": len(samples),
        }
```

#### 3. 数据源调用时传入延迟

```python
# backend/services/datasource/protocol.py

async def fetch(self, action: str, params: Dict[str, Any]) -> Result:
    start_time = time.perf_counter()
    
    try:
        # 原有逻辑
        result = await self._fetch_impl(action, params)
        
        # 记录延迟
        latency_ms = (time.perf_counter() - start_time) * 1000
        await call_metrics.record_business(
            self.source_name, 
            "success",
            latency_ms=latency_ms  # ← 新增
        )
        
        return result
    except Exception as e:
        latency_ms = (time.perf_counter() - start_time) * 1000
        await call_metrics.record_business(
            self.source_name, 
            "error",
            latency_ms=latency_ms  # ← 新增
        )
        raise
```

#### 4. 前端展示

```typescript
// frontend/src/features/data-center/datasource-health.tsx

// 从后端获取延迟统计
const latencyStats = await apiClient.get(`/datasource/${source}/latency`)

// 展示
<div className="text-sm font-medium text-foreground">
  {latencyStats.avg_ms != null 
    ? `${latencyStats.avg_ms.toFixed(0)} ms` 
    : 'N/A'}
</div>
<div className="text-[10px] text-muted-foreground">
  P50: {latencyStats.p50_ms?.toFixed(0) ?? '—'} · 
  P95: {latencyStats.p95_ms?.toFixed(0) ?? '—'} · 
  n={latencyStats.samples}
</div>
```

### 实施步骤

1. **扩展 CallMetricsStore** (30min)
   - 添加 `record_business(latency_ms=...)` 参数
   - 实现 Redis List 存储延迟样本
   - 实现 `get_latency_stats()` 方法

2. **修改数据源协议** (30min)
   - 在 `DataSourceInterface.fetch()` 中测量延迟
   - 调用 `record_business()` 时传入延迟

3. **添加 API 端点** (30min)
   - `GET /api/v1/datasource/{name}/latency` - 获取延迟统计
   - 在 `backend/routers/datasource.py` 中实现

4. **前端集成** (30min)
   - 调用新 API 获取延迟统计
   - 更新健康看板展示

5. **测试验证** (30min)
   - 单元测试
   - 集成测试
   - 手动验证

**总预计时间**: 2.5 小时

---

## 📋 Phase 3: 完善监控指标体系 (待实施)

### 目标

建立完整的数据源监控体系，支持：
- 延迟分布可视化
- 错误率趋势图
- 限流热力图
- 数据源可用性时间线

### 功能模块

#### 1. 延迟分布直方图

```
[延迟分布] Finnhub
  ┌─────────────────────────────┐
10│         █                   │
20│       █ █ █                 │
30│     █ █ █ █ █               │
40│   █ █ █ █ █ █ █             │
50│ █ █ █ █ █ █ █ █ █           │
  └─────────────────────────────┘
    0  50 100 150 200 250 300+ (ms)
```

#### 2. 错误率趋势图

```
[错误率趋势] 过去 24 小时
  ┌─────────────────────────────┐
10│                             │
 5│         ▲                   │
 1│   ▲   ▲ ▲     ▲             │
 0│───┴───┴──┴─────┴───────────│
  └─────────────────────────────┘
    00 04 08 12 16 20 24 (小时)
```

#### 3. 限流热力图

```
[限流热力图] 过去 7 天
        Mon Tue Wed Thu Fri Sat Sun
Finnhub  ██  ██  █   ░   ░   ░   ░
YFinance ░   ░   ░   ░   ░   ░   ░
Futu     ░   ░   ░   ░   ░   ░   ░
```

#### 4. 可用性时间线

```
[可用性] Finnhub
00:00 ───────────────●─────────────●────── 24:00
     正常 1h ▲ 异常 2h ▲ 正常 21h
```

### 技术方案

1. **数据存储**
   - Redis Time Series (延迟样本)
   - PostgreSQL (聚合统计)
   - Prometheus (实时监控)

2. **可视化**
   - ECharts (前端图表)
   - Grafana (运维看板)

3. **告警**
   - 延迟超过阈值 → 飞书/钉钉通知
   - 错误率飙升 → 自动降级
   - 限流频繁 → 自动扩容

**预计工作量**: 1-2 天

---

## 📝 总结

| Phase | 状态 | 工作量 | 优先级 |
|-------|------|--------|--------|
| Phase 1: 前端显示优化 | ✅ 已完成 | 30min | P0 |
| Phase 2: 延迟统计功能 | 🔄 进行中 | 2.5h | P1 |
| Phase 3: 监控指标体系 | 📋 待实施 | 1-2 天 | P2 |

**下一步**: 立即实施 Phase 2，实现后端延迟统计功能。
