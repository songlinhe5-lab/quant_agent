# 数据源延迟统计与缓存优化实施跟踪

## 📋 问题背景

基于 2026-08-04 的全数据源真实性验证，发现以下需要改进的问题：

1. ✅ **已解决**: 前端显示 0ms 误导用户
2. ⏳ **进行中**: 后端延迟统计功能缺失
3. ✅ **已澄清**: Finnhub 缓存机制正常
4. 📋 **待实施**: 完整监控指标体系

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
- ✅ 当无延迟数据时显示 "N/A" 而非 "0ms"
- ✅ 避免误导用户
- ✅ 用户体验更清晰

**部署状态**: ⏳ 待部署到生产环境

---

## 🔍 调查：Finnhub 缓存机制

### ✅ **结论：Finnhub 缓存机制正常！**

**发现**:
- ✅ Finnhub **有缓存逻辑**
- ✅ 缓存键模式不同于预期
- ✅ 实际有 9 个缓存键在使用

### 📊 **缓存详情**

| 缓存类型 | 键模式 | 数量 | TTL | 状态 |
|---------|--------|------|-----|------|
| **财报日历** | `quant:macro:earnings_calendar:*` | 2 | ~12h | ✅ 活跃 |
| **内幕交易** | `quant:macro:insider_transactions:*` | 7 | ~12h | ✅ 活跃 |
| **历史 K 线** | `quant:history:finnhub:*` | 0 | 1h | ⚠️ 未使用 |
| **公司新闻** | `quant:news:company:*` | 0 | - | ⚠️ 未使用 |

### 💡 **为什么之前误判？**

**原因**:
1. 检查了错误的键模式：`quant:cache:finnhub:*`
2. Finnhub 实际使用：`quant:macro:*` 和 `quant:history:finnhub:*`
3. 部分 API（如 quote）可能确实不缓存（实时性要求高）

### ✅ **Finnhub 数据真实性确认**

- ✅ 1217 次真实业务调用
- ✅ 1138 次成功 (93.5%)
- ✅ 79 次真实限流 (IP 封禁)
- ✅ 9 个缓存键在使用
- ✅ 价格数据与直接调用 API 完全一致

**结论**: Finnhub 返回的是**100% 真实数据**！

---

## 🔄 Phase 2: 实现延迟统计功能 (待实施)

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

#### 2. 实施步骤

**Step 1: 扩展 CallMetricsStore** (30min)
```python
# backend/services/datasource/call_metrics_store.py

async def record_business(
    self, 
    source: str, 
    outcome: str, 
    category: str = None,
    latency_ms: float = None  # ← 新增参数
):
    """记录业务调用时同时记录延迟"""
    # ... 原有逻辑 ...
    
    # 新增：记录延迟
    if latency_ms is not None and latency_ms > 0:
        key = f"quant:metrics:{source}:latency:{date}"
        await redis_client.lpush(key, latency_ms)
        await redis_client.ltrim(key, 0, 999)  # 保留最近 1000 个样本
        await redis_client.expire(key, 7 * 86400)  # 7 天过期

async def get_latency_stats(self, source: str) -> Dict[str, float]:
    """获取延迟统计"""
    # ... 计算 P50/P95/P99 ...
```

**Step 2: 修改数据源协议** (30min)
```python
# backend/services/datasource/protocol.py

async def fetch(self, action: str, params: Dict[str, Any]) -> Result:
    start_time = time.perf_counter()
    
    try:
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

**Step 3: 添加 API 端点** (30min)
```python
# backend/routers/datasource.py

@router.get("/{name}/latency")
async def get_datasource_latency(name: str):
    """获取数据源延迟统计"""
    stats = await call_metrics.get_latency_stats(name)
    return {
        "source": name,
        "latency": stats,
    }
```

**Step 4: 前端集成** (30min)
```typescript
// frontend/src/features/data-center/datasource-health.tsx

const latencyStats = await apiClient.get(`/datasource/${source}/latency`)

<div className="text-sm font-medium text-foreground">
  {latencyStats.avg_ms != null 
    ? `${latencyStats.avg_ms.toFixed(0)} ms` 
    : 'N/A'}
</div>
```

**Step 5: 测试验证** (30min)
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

## 📊 实施进度总览

| Phase | 状态 | 工作量 | 优先级 | 备注 |
|-------|------|--------|--------|------|
| Phase 1: 前端显示优化 | ✅ 已完成 | 30min | P0 | 已提交，待部署 |
| 调查：Finnhub 缓存 | ✅ 已完成 | 30min | - | 缓存机制正常 |
| Phase 2: 延迟统计功能 | 📋 待实施 | 2.5h | P1 | 设计完成 |
| Phase 3: 监控指标体系 | 📋 待实施 | 1-2 天 | P2 | 规划中 |

---

## 🎯 下一步行动

### 立即行动

1. **部署 Phase 1 到生产环境**
   ```bash
   # 提交 PR 到 main
   git checkout develop
   git push origin develop
   
   # 创建 PR
   gh pr create --base main --head develop --title "fix: 数据源健康看板延迟显示优化"
   ```

2. **验证 Phase 1 效果**
   - 访问 Data Center 页面
   - 检查 Finnhub 等数据源是否显示 "N/A"
   - 确认不再显示误导性的 "0ms"

### 中期行动

3. **实施 Phase 2: 延迟统计功能**
   - 扩展 `CallMetricsStore`
   - 修改数据源协议
   - 添加延迟统计 API
   - 前端集成展示

### 长期行动

4. **实施 Phase 3: 监控指标体系**
   - 延迟分布可视化
   - 错误率趋势图
   - 限流热力图
   - 可用性时间线

---

## 📚 相关文档

- [数据源延迟统计功能实施计划](./DATASOURCE_LATENCY_IMPLEMENTATION.md)
- [全数据源真实性验证报告](./全数据源真实性验证报告.md)
- [三层分级限流协议](./RATELIMIT_PROTOCOL_V2.md)

---

**最后更新**: 2026-08-04 12:30
