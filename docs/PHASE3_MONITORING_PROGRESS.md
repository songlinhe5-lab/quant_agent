# Phase 3: 监控指标体系实施进度报告

**实施日期**: 2026-08-04  
**当前状态**: 🚧 进行中  
**最后更新**: Module 1 & Module 2 后端完成

---

## 📊 实施进度总览

| Module | 状态 | 工作量 | 提交哈希 | 备注 |
|--------|------|--------|---------|------|
| Module 1: Prometheus 指标导出 | ✅ 已完成 | 2h | `9db2d65` | 4 个新指标 + 集成 |
| Module 2: 延迟分布直方图 (后端) | ✅ 已完成 | 1.5h | `e8d33e9` | API 端点实现 |
| Module 2: 延迟分布直方图 (前端) | 📋 待实施 | 1.5h | - | ECharts 组件 |
| Module 3: 错误率趋势图 | 📋 待实施 | 3h | - | 后端 + 前端 |
| Module 4: 限流热力图 | 📋 待实施 | 3h | - | 后端 + 前端 |
| Module 5: 可用性时间线 | 📋 待实施 | 4h | - | 后端 + 前端 |
| Module 6: Grafana 仪表板 | 📋 待实施 | 2h | - | 配置 4 个面板 |

**已完成工作量**: 3.5h / 20h (17.5%)

---

## ✅ 已完成内容

### Module 1: Prometheus 指标导出增强

**提交**: `9db2d65` - feat(metrics): Phase 3 Module 1 - Prometheus 数据源监控指标导出

**文件改动**:
- `backend/core/metrics.py` (+33 行)
- `backend/services/datasource/source_registry.py` (+21 行)

**新增指标**:
```python
# 1. 延迟分布直方图
DATASOURCE_LATENCY = Histogram(
    "quant_datasource_latency_milliseconds",
    "数据源请求延迟分布（毫秒）",
    ["source", "action"],
    buckets=[50, 100, 150, 200, 250, 300, 500, 1000, 2000, float("inf")],
)

# 2. 错误率计数器
DATASOURCE_ERRORS = Counter(
    "quant_datasource_errors_total",
    "数据源错误总数",
    ["source", "error_type"],
)

# 3. 限流计数器
DATASOURCE_RATE_LIMITS = Counter(
    "quant_datasource_rate_limits_total",
    "数据源限流次数",
    ["source", "category"],
)

# 4. 可用性状态
DATASOURCE_AVAILABILITY = Gauge(
    "quant_datasource_availability",
    "数据源可用性状态 (1=可用，0=不可用)",
    ["source"],
)
```

**集成逻辑**:
- 成功时：记录延迟 + 标记可用 (`availability=1`)
- 限流时：记录延迟 + 错误计数 + 限流计数
- 错误时：记录延迟 + 错误计数 + 标记不可用 (`availability=0`)

**Prometheus 查询示例**:
```promql
# P95 延迟（按数据源）
histogram_quantile(0.95, rate(quant_datasource_latency_milliseconds_bucket[5m]))

# 错误率（每秒）
rate(quant_datasource_errors_total[5m])

# 限流次数（过去 1 小时）
increase(quant_datasource_rate_limits_total[1h])

# 当前可用性状态
quant_datasource_availability
```

---

### Module 2: 延迟分布直方图（后端）

**提交**: `e8d33e9` - feat(datasource): Phase 3 Module 2 - 延迟分布直方图后端 API

**文件改动**:
- `backend/routers/datasource.py` (+66 行，-25 行)

**新增 API**:
```python
GET /api/v1/datasource/{name}/latency-distribution?hours=24
```

**响应格式**:
```json
{
  "source": "finnhub",
  "buckets": [
    {"range": "0-50ms", "count": 120},
    {"range": "50-100ms", "count": 340},
    {"range": "100-150ms", "count": 280},
    {"range": "150-200ms", "count": 195},
    {"range": "200-250ms", "count": 110},
    {"range": "250-300ms", "count": 75},
    {"range": "300-500ms", "count": 62},
    {"range": "500-1000ms", "count": 28},
    {"range": "1000-2000ms", "count": 5},
    {"range": "2000ms+", "count": 2}
  ],
  "total_samples": 1217,
  "avg_ms": 180.5,
  "p50_ms": 165.3,
  "p95_ms": 245.8
}
```

**实现逻辑**:
1. 从 Redis 读取延迟样本 List
2. 定义 10 个延迟桶边界
3. 遍历样本按桶分组统计
4. 返回直方图数据 + P50/P95 统计

**前端集成示例** (待实施):
```typescript
// 使用 ECharts 绘制直方图
const response = await apiClient.get(`/datasource/${source}/latency-distribution`);
const { buckets, total_samples, avg_ms, p95_ms } = response.data;

<ECharts option={{
  title: { text: `延迟分布 (n=${total_samples}, avg=${avg_ms}ms, P95=${p95_ms}ms)` },
  xAxis: { type: 'category', data: buckets.map(b => b.range) },
  yAxis: { type: 'value' },
  series: [{
    type: 'bar',
    data: buckets.map(b => b.count),
    itemStyle: { color: '#8b5cf6' }
  }]
}} />
```

---

## 📋 待实施内容

### Module 2: 延迟分布直方图（前端）

**文件**: `frontend/src/features/data-center/latency-distribution-chart.tsx`

**预计工作量**: 1.5 小时

**任务**:
- [ ] 创建 ECharts 直方图组件
- [ ] 集成到数据源健康看板
- [ ] 支持按数据源切换
- [ ] 显示统计信息（avg/P50/P95）

---

### Module 3: 错误率趋势图

**后端 API**: `backend/routers/datasource.py`

```python
@router.get("/error-trend")
async def get_error_trend(hours: int = 24):
    """获取错误率趋势（过去 N 小时）"""
    # 从 Redis 读取每小时的错误统计
    # 计算错误率 = errors / total_calls
    return {
        "timeline": [
            {"time": "2026-08-04T00:00", "error_rate": 0.05},
            {"time": "2026-08-04T01:00", "error_rate": 0.08},
            # ...
        ],
        "sources": ["finnhub", "yfinance", "futu"],
    }
```

**前端组件**: `frontend/src/features/data-center/error-trend-chart.tsx`

**预计工作量**: 3 小时

**任务**:
- [ ] 后端 API 实现 (1.5h)
- [ ] 前端 ECharts 折线图组件 (1.5h)

---

### Module 4: 限流热力图

**后端 API**: `backend/routers/datasource.py`

```python
@router.get("/rate-limit-heatmap")
async def get_rate_limit_heatmap(days: int = 7):
    """获取限流热力图数据（过去 N 天）"""
    # 从 Redis 读取每天的限流统计
    # 按数据源 x 日期组织
    return {
        "matrix": [
            {"source": "finnhub", "date": "2026-08-01", "count": 45},
            {"source": "finnhub", "date": "2026-08-02", "count": 32},
            # ...
        ],
        "sources": ["finnhub", "yfinance", "futu"],
        "dates": ["2026-08-01", "2026-08-02", ...],
    }
```

**前端组件**: `frontend/src/features/data-center/rate-limit-heatmap.tsx`

**预计工作量**: 3 小时

**任务**:
- [ ] 后端 API 实现 (1.5h)
- [ ] 前端 ECharts 热力图组件 (1.5h)

---

### Module 5: 可用性时间线

**后端 API**: `backend/routers/datasource.py`

```python
@router.get("/{name}/availability-timeline")
async def get_availability_timeline(name: str, hours: int = 24):
    """获取可用性时间线（状态转换历史）"""
    # 从 Redis 读取状态转换事件
    # 或从 Prometheus 查询 availability gauge
    return {
        "source": name,
        "events": [
            {"time": "2026-08-04T00:00", "status": "healthy"},
            {"time": "2026-08-04T02:30", "status": "throttled"},
            {"time": "2026-08-04T03:15", "status": "healthy"},
            # ...
        ],
        "availability_pct": 95.8,  # 可用率百分比
    }
```

**前端组件**: `frontend/src/features/data-center/availability-timeline.tsx`

**预计工作量**: 4 小时

**任务**:
- [ ] 后端 API 实现 (2h)
- [ ] 前端自定义时间线组件 (2h)

---

### Module 6: Grafana 仪表板配置

**文件**: `grafana/provisioning/dashboards/datasource-monitoring.json`

**面板配置**:
1. **延迟分布直方图** - Panel 1
   - 查询: `histogram_quantile(0.95, rate(quant_datasource_latency_milliseconds_bucket[5m]))`
   
2. **错误率趋势图** - Panel 2
   - 查询: `rate(quant_datasource_errors_total[5m])`
   
3. **限流热力图** - Panel 3
   - 查询: `increase(quant_datasource_rate_limits_total[1d])`
   
4. **可用性时间线** - Panel 4
   - 查询: `quant_datasource_availability`

**预计工作量**: 2 小时

**任务**:
- [ ] 创建仪表板 JSON 配置
- [ ] 配置 4 个面板
- [ ] 设置告警规则
- [ ] 端到端测试验证

---

## 🎯 下一步行动

### 立即行动

1. **实施 Module 2 前端组件** (1.5h)
   - 创建 `latency-distribution-chart.tsx`
   - 集成到健康看板
   - 测试交互效果

2. **实施 Module 3 错误率趋势图** (3h)
   - 后端 API 实现
   - 前端折线图组件
   - 支持多数据源对比

### 后续行动

3. **实施 Module 4-6** (9h)
   - 限流热力图
   - 可用性时间线
   - Grafana 集成

---

## 📈 技术指标

### Prometheus 指标命名规范

- **Counter**: `quant_datasource_*_total` (累计计数)
- **Gauge**: `quant_datasource_*` (瞬时值)
- **Histogram**: `quant_datasource_*_milliseconds` (分布统计)

### 标签设计规范

- `source`: 数据源名称 (finnhub, yfinance, futu)
- `action`: API 动作 (quote, history, fundamental)
- `error_type`: 错误类型 (rate_limit, timeout, network, circuit_open)
- `category`: 限流类别 (429, 403, 402)

### Redis 键空间

```
quant:metrics:{source}:latency:{date}
  - 类型：List
  - 容量：1000 样本/天
  - TTL: 7 天
  - 用途：延迟分布统计

quant:metrics:{source}:calls:{date}
  - 类型：Hash
  - 字段：calls, success, errors, rl_*
  - TTL: 35 天
  - 用途：调用计数统计
```

---

## 🧪 测试验证

### 单元测试

```python
# tests/test_datasource_latency.py
async def test_latency_distribution():
    """测试延迟分布 API"""
    # 1. 准备测试数据
    await call_metrics.record_business("test_source", "success", latency_ms=150.5)
    await call_metrics.record_business("test_source", "success", latency_ms=200.3)
    
    # 2. 调用 API
    response = await client.get("/datasource/test_source/latency-distribution")
    
    # 3. 验证结果
    assert response.status_code == 200
    data = response.json()
    assert data["source"] == "test_source"
    assert data["total_samples"] == 2
    assert len(data["buckets"]) == 10
```

### 集成测试

```bash
# 在 VPS 上测试
curl -X GET "http://localhost:8000/api/v1/datasource/finnhub/latency-distribution" | jq

# 预期输出
{
  "source": "finnhub",
  "buckets": [...],
  "total_samples": 1217,
  "avg_ms": 180.5,
  "p50_ms": 165.3,
  "p95_ms": 245.8
}
```

---

## 📚 参考文档

- [Phase 2 延迟统计功能实施报告](./PHASE2_LATENCY_STATS_COMPLETION.md)
- [数据源改进跟踪](./DATASOURCE_IMPROVEMENT_TRACKING.md)
- [Prometheus Histogram 文档](https://prometheus.io/docs/practices/histograms/)
- [ECharts 官方文档](https://echarts.apache.org/)

---

**实施进度**: 17.5% (3.5h / 20h)  
**下次更新**: Module 2 前端完成后
