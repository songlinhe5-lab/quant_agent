# 全数据源真实性验证指南

## 🎯 验证目标

验证主服务器 (38.60.126.42) 上所有已注册数据源是否都在返回**真实数据**，而非缓存数据。

---

## 🚀 快速执行

### 方法 1: SSH 远程执行 (推荐)

```bash
# 1. SSH 到主服务器
ssh root@38.60.126.42

# 2. 进入容器执行验证脚本
docker exec quant_app python3 /opt/quant-agent/scripts/verify_on_master.py

# 3. 查看完整输出
```

### 方法 2: 本地执行 (需要依赖)

```bash
# 在本地虚拟环境中执行
cd /Users/stephenhe/Development/workspace/quant_agent
source .venv/bin/activate
python3 scripts/verify_on_master.py
```

---

## 📊 验证内容

### 1. 检查的数据源

脚本会自动检查所有已注册的数据源，包括但不限于：

- **YFinance** (Yahoo Finance 美股/港股)
- **Futu** (富途 OpenD 港股实时行情)
- **AKShare** (A 股/期货/基金)
- **Finnhub** (美股基本面)
- **FRED** (宏观经济数据)

### 2. 验证维度

| 维度 | 说明 | 判断标准 |
|------|------|----------|
| **缓存状态** | 检查 L1/YF/Futu 缓存 | 空缓存 = 真实数据 |
| **调用计数** | Redis 中的业务调用次数 | >0 = 有真实请求 |
| **成功率** | 业务调用成功比例 | >90% = 健康 |
| **限流统计** | 触发数据源限流的次数 | 0 = 正常，>0 = 需关注 |
| **最近请求** | 最后一次请求时间 | 越近越真实 |

### 3. 真实性判断逻辑

```python
if 无调用记录:
    状态 = "no_data"  # 无法判断
elif 命中缓存:
    状态 = "cache_hit"  # 可能不真实
elif 成功率 > 0:
    状态 = "healthy"  # ✅ 真实数据
    if 限流次数 > 0:
        状态 = "throttled"  # 真实但被限流
else:
    状态 = "error"  # ❌ 异常
```

---

## 📋 预期输出示例

### ✅ 健康状态

```
================================================================================
📡 数据源：YFINANCE
================================================================================

【基本信息】
  类型：YFinanceService
  模式：internal
  能力：QUOTE, HISTORY, FUND_FLOW, OPTION_CHAIN

【缓存状态】
  L1 Cache 条目：0
  YFinance 内存缓存：0 条目
    ✅ 无内存缓存

【调用计数 (今日)】
  日期：2026-08-04
  Redis Key: quant:metrics:yfinance:calls:2026-08-04
  ✅ 有调用记录:
    业务调用：15
    业务成功：15
    业务错误：0
    成功率：100.0%
    探针调用：20
    探针成功：20
    探针成功率：100.0%
    限流次数：0

【真实性判断】
  ✅ 数据源正常工作
     成功率：100.0%
     业务调用：15 次
     探针调用：20 次
     ✅ 无限流触发
```

### ⚠️ 限流状态

```
【真实性判断】
  ✅ 数据源正常工作
     成功率：85.0%
     业务调用：50 次
     探针调用：30 次
     ⚠️  已触发限流 5 次
```

### ❌ 异常状态

```
【真实性判断】
  ❌ 数据源异常 (成功率 0%)
```

---

## 🔍 结果解读

### 关键指标说明

| 指标 | 含义 | 正常范围 |
|------|------|----------|
| **业务调用 (calls)** | 真实业务请求次数 | >0 |
| **探针调用 (probe_calls)** | test-link 测试次数 | 任意 |
| **成功率** | 业务成功/业务总数 | >90% |
| **限流次数** | 被数据源限流的次数 | 0 (最佳) |
| **缓存命中** | 是否命中本地缓存 | 否 (最佳) |

### 常见场景分析

#### 场景 1: 所有数据源都健康

```
✅ 健康数据源：5
   - YFINANCE: 成功率 100.0%, 业务 15 次，探针 20 次
   - FUTU: 成功率 98.5%, 业务 67 次，探针 10 次
   - AKSHARE: 成功率 100.0%, 业务 8 次，探针 5 次
   - FINNHUB: 成功率 100.0%, 业务 12 次，探针 8 次
   - FRED: 成功率 100.0%, 业务 3 次，探针 2 次
```

**结论**: ✅ 所有数据源都在返回真实数据

---

#### 场景 2: 部分数据源无调用记录

```
✅ 健康数据源：3
   - YFINANCE: 成功率 100.0%, 业务 15 次
   - FUTU: 成功率 98.5%, 业务 67 次
   - FINNHUB: 成功率 100.0%, 业务 12 次

ℹ️  无调用记录：2
   - AKSHARE
   - FRED
```

**结论**: ⚠️ AKShare 和 FRED 可能未启用或未使用，但不影响其他数据源

---

#### 场景 3: 数据源被限流

```
⚠️  已限流数据源：1
   - YFINANCE: 限流 5 次

✅ 健康数据源：4
   - FUTU: 成功率 98.5%, 业务 67 次
   ...
```

**结论**: ⚠️ YFinance 调用过于频繁，触发了 Yahoo Finance 的限流机制 (~200 RPM)

**建议**: 降低 YFinance 调用频率，增加缓存 TTL

---

#### 场景 4: 命中缓存

```
⚠️  命中缓存：1
   - YFINANCE: 可能命中本地缓存
```

**结论**: ⚠️ YFinance 的 test-link 探针可能命中了内存缓存，延迟数据不准确

**建议**: 检查 `skip_cache=True` 是否正确绕过所有缓存层

---

## 💡 验证建议

### 1. 定期验证

建议每天验证一次，确保数据源持续提供真实数据：

```bash
# 添加到 crontab
0 9 * * * docker exec quant_app python3 /opt/quant-agent/scripts/verify_on_master.py >> /var/log/datasource_verify.log 2>&1
```

### 2. 对比验证

在不同时间点验证，观察调用计数变化：

```bash
# 上午 9 点
docker exec quant_app python3 /opt/quant-agent/scripts/verify_on_master.py | tee /tmp/am_verify.txt

# 下午 3 点
docker exec quant_app python3 /opt/quant-agent/scripts/verify_on_master.py | tee /tmp/pm_verify.txt

# 对比差异
diff /tmp/am_verify.txt /tmp/pm_verify.txt
```

### 3. 压力测试

验证限流阈值：

```bash
# 快速连续查询 300 次 (测试 YFinance 限流)
for i in {1..300}; do
  curl -s http://localhost:8000/api/v1/market/quote?symbol=AAPL &
done
wait

# 再次验证
docker exec quant_app python3 /opt/quant-agent/scripts/verify_on_master.py
```

---

## 📝 检查清单

执行验证后，确认以下项目：

- [ ] 所有数据源都有调用记录 (或明确知道哪些未启用)
- [ ] 成功率 > 90% (或知道失败原因)
- [ ] 限流次数 = 0 (或在可接受范围内)
- [ ] 缓存未命中 (test-link 返回真实延迟)
- [ ] 最近请求时间在合理范围内 (< 1 小时)

---

## 🎉 成功标准

满足以下条件即可确认**所有数据源都在返回真实数据**:

1. ✅ 至少 1 个数据源状态为 `healthy` 或 `throttled`
2. ✅ 无数据源状态为 `error`
3. ✅ 业务调用成功率 > 90%
4. ✅ 缓存未命中 (或明确知道缓存策略)

---

## 📚 相关文档

- [数据源探针与业务调用指标隔离规范](../docs/DEVELOPMENT_PRACTICE_SPECIFICATION_数据源探针与业务调用指标隔离规范.md)
- [三层分级限流协议](../docs/RATELIMIT_PROTOCOL_V2.md)
- [分布式数据源服务架构](../docs/14.%20分布式数据源服务架构.md)
