# 🎯 AGENT-17 最终完成报告：轮次身份与计时元数据

## ✅ 验收标准

**原始定义（TODO-AGENT-ARCH.md §9.3）**：
> `_react_loop` 每轮生成 `turn_id`（uuid），turn/start|end 事件携带：iteration / model / prompt_tokens / completion_tokens / latency 分解（inference_ms / tool_ms / save_ms）；预留 parent_turn_id / root_turn_id 字段（AGENT-14 血缘）；Prometheus `agent_turn_duration_seconds` histogram

**实际完成情况**：

### 1. ✅ turn_id 生成与跟踪
- **每轮唯一 ID**: `str(uuid.uuid4())[:8]` → 8 字符短 ID 便于日志阅读（如 `"a3f7b2c1"`）
- **全链路传播**: 
  - `record_turn_start`: 携带 `turn_id`, `model`
  - `record_tool_result`: 携带 `turn_id`（便于按轮归组）
  - `record_turn_end`: 携带 `turn_id` + 所有延迟指标
- **事件一致性**: 单轮内所有事件 share 同一 `turn_id`（已通过单元测试验证）

### 2. ✅ 延迟分解（latency breakdown）
三阶段精确计时：
- **`inference_ms`**: LLM 推理时间（从 `asyncio.create_task` 到流式接收结束）
- **`tool_ms`**: Tool 执行时间（仅当有工具调用时）
- **`save_ms`**: 会话保存到 Redis/PG 时间（所有路径均记录）

**示例 Payload**：
```python
{
    "iteration": 3,
    "turn_id": "xyz789",
    "prompt_tokens": 1024,
    "completion_tokens": 512,
    "latency": {
        "inference_ms": 2500.5,   # ~2.5s LLM
        "tool_ms": 150.25,        # ~150ms Tool
        "save_ms": 35.125         # ~35ms Save
    }
}
```

### 3. ✅ Token 计量集成
- **`prompt_tokens`**: 从 `_last_usage` 提取（若存在）
- **`completion_tokens`**: 同上
- **Fallback**: 若 `_last_usage` 为空则保持为 0

### 4. ✅ 血缘字段预留（AGENT-14）
- **`parent_turn_id`**: 当前轮次的父轮次 ID（用于子 Agent 调用链）
- **`root_turn_id`**: 根轮次 ID（用于追踪完整对话树）
- **现状**: 当前均为空字符串，预留字段供未来扩展

### 5. ✅ Prometheus 指标 (`agent_turn_duration_seconds`)
- **Histogram 配置**:
  ```python
  Histogram(
      "agent_turn_duration_seconds",
      "ReAct 轮次延迟分布（按阶段分解）",
      ["phase", "model"],  # 维度：阶段 + 模型
      buckets=(0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0)
  )
  ```
- **Phase 标签**:
  - `start_inference`: 正常轮次（inference + save）
  - `early_exit`: 无内容直接退出（仅 save）
  - `recovery_fallback`: 熔断恢复路径（inference + save）
- **延迟初始化**: 避免 `prometheus_client` 未安装时崩溃

## 🔧 核心实现

### 文件清单

#### 1. `hermes_agent/event_log.py` (+55/-8)
**变更**:
```python
# record_turn_start: 新增 turn_id/model/血缘字段
def record_turn_start(
    self,
    iteration: int,
    turn_id: str = "",          # ← 新增
    model: str = "",             # ← 新增
    parent_turn_id: str = "",    # ← AGENT-14 预留
    root_turn_id: str = "",      # ← AGENT-14 预留
) -> SessionEvent:

# record_turn_end: 新增完整延迟分解
def record_turn_end(
    self,
    iteration: int,
    content_len: int = 0,
    turn_id: str = "",                  # ← 新增
    prompt_tokens: int = 0,              # ← 新增
    completion_tokens: int = 0,          # ← 新增
    inference_ms: float = 0.0,           # ← 新增
    tool_ms: float = 0.0,                # ← 新增
    save_ms: float = 0.0,                # ← 新增
) -> SessionEvent:

# record_tool_result: 新增 turn_id 便于归组
def record_tool_result(
    self, call_id: str, name: str, content: str, turn_id: str = ""
) -> SessionEvent:
```

#### 2. `hermes_agent/agent.py` (+85 net)
**变更**:
```python
# 1. 导入增加
import uuid
import time

# 2. Prometheus 指标（~30 行）
_TURN_DURATION_HISTOGRAM: Any = None

def _init_prometheus_metrics():
    """延迟初始化 Prometheus 指标"""
    global _TURN_DURATION_HISTOGRAM
    if _TURN_DURATION_HISTOGRAM is not None:
        return
    try:
        from prometheus_client import Histogram
        _TURN_DURATION_HISTOGRAM = Histogram(...)
    except Exception:
        pass

def _observe_turn_duration(phase: str, model: str, duration_seconds: float):
    """观测轮次延迟（秒）"""
    _init_prometheus_metrics()
    if _TURN_DURATION_HISTOGRAM is not None:
        _TURN_DURATION_HISTOGRAM.labels(phase=phase, model=model).observe(duration_seconds)

# 3. _react_loop 修改（+55 行净增量）
for i in range(max_iterations):
    # 3.1 生成 turn_id（循环开始时）
    turn_id = str(uuid.uuid4())[:8]
    current_model = self.provider_router.get_active_model()

    # 3.2 record_turn_start 调用（带参数）
    self.event_log.record_turn_start(
        iteration=i + 1,
        turn_id=turn_id,
        model=current_model,
        parent_turn_id="",  # 未来填充
        root_turn_id="",    # 未来填充
    )

    # 3.3 初始化计时变量
    inference_ms = tool_ms = save_ms = 0.0
    prompt_tokens = completion_tokens = 0

    # 3.4 LLM 推理计时（inference_start → inference_ms）
    inference_start = time.monotonic()
    ...  # LLM call
    inference_ms = (time.monotonic() - inference_start) * 1000

    # 3.5 Token 提取
    if _last_usage:
        prompt_tokens = getattr(_last_usage, "prompt_tokens", 0) or 0
        completion_tokens = getattr(_last_usage, "completion_tokens", 0) or 0

    # 3.6 工具执行计时（tool_start → tool_ms）
    tool_start = time.monotonic()
    ...  # Tool execution
    tool_ms = (time.monotonic() - tool_start) * 1000

    # 3.7 保存会话计时（save_start → save_ms）
    save_start = time.monotonic()
    await self._save_session()
    save_ms = (time.monotonic() - save_start) * 1000

    # 3.8 record_tool_result 携带 turn_id
    self.event_log.record_tool_result(tc["id"], tc["name"], content, turn_id=turn_id)

    # 3.9 record_turn_end 携带所有指标
    self.event_log.record_turn_end(
        i + 1,
        content_len=...,
        turn_id=turn_id,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        inference_ms=inference_ms,
        tool_ms=tool_ms,
        save_ms=save_ms,
    )

    # 3.10 观测 Prometheus
    _observe_turn_duration("start_inference", current_model, (inference_ms + save_ms) / 1000)
```

### 测试覆盖

**文件**: `hermes_agent/tests/test_agent_17_turn_metadata.py`（11 个单元测试）

| Test Class | Test Count | Coverage |
|------------|-----------|----------|
| `TestTurnStartEventWithTurnId` | 3 | turn_id/model/血缘字段正确性 |
| `TestTurnEndEventWithTiming` | 3 | latency 分解、舍入、缺失值处理 |
| `TestToolResultWithTurnId` | 2 | tool/result 携带 turn_id |
| `TestTurnIdConsistencyAcrossEvents` | 1 | 单轮事件 share turn_id |
| `TestPrometheusMetricsInitialization` | 1 | metrics 初始化不崩溃 |
| `TestRealisticTimingValues` | 1 | 典型场景延迟范围校验 |

**通过率**: ✅ 11/11

## 📊 预期效果

### 前端/监控端点可见性

一旦集成到 Prometheus/Grafana，可查询：
```promql
# 查看某模型的平均推理延迟
avg(agent_turn_duration_seconds_bucket{phase="start_inference", model="deepseek-chat"}) by (le)

# 查看 TurnID 分组的所有事件
# （需 EventLog API 支持按 turn_id 过滤）

# 对比不同阶段的延迟分布
histogram_quantile(0.95, agent_turn_duration_seconds_bucket{phase="tool_execution"})
```

### 事件日志示例

```json
{
  "seq": 12,
  "ts": 1753123456.789,
  "type": "turn/end",
  "payload": {
    "iteration": 3,
    "content_len": 2048,
    "turn_id": "abc123de",
    "model": "deepseek-chat",
    "prompt_tokens": 1024,
    "completion_tokens": 512,
    "latency": {
      "inference_ms": 2500.5,
      "tool_ms": 150.25,
      "save_ms": 35.125
    }
  }
}
```

## ⚠️ 已知限制与注意事项

1. **Token 计数可能为空**
   - 原因：部分模型响应不包含 `usage` 字段
   - 影响：`prompt_tokens`/`completion_tokens` 保持为 0
   - 缓解：已添加 fallback 逻辑，不会导致错误

2. **Early-exit 路径无 inference**
   - 场景：`if not iter_content` 直接返回
   - 状态：仅 `save_ms` 非零，`inference_ms=0`
   - 度量：单独 phase=`early_exit` 区分

3. **熔断恢复路径独立 timing**
   - Phase 标签：`recovery_fallback`
   - 仅含 inference + save（no tool，因已跳过工具调用）

4. **Prometheus 依赖可选**
   - 未安装 `prometheus_client` 时静默跳过
   - 不影响功能，仅无可视化指标

## 🔄 向后兼容性

- **Optional fields**: `turn_id`/`model`/`parent_turn_id` 等均为可选，旧代码仍可工作
- **Latency 结构**: 若无延迟数据，`"latency"` key 不出现
- **Event log API**: `record_*` 方法新增参数均设默认值 `""`/`0`/`0.0`

## 📈 下一步优化建议

1. **事件聚合 API**: 提供 `/api/v1/sessions/{session_id}/events?turn_id=xxx` 接口
2. **实时 dashboard**: Grafana 面板展示各 turn 的延迟直方图
3. **Trace 系统整合**: 将 turn_id 作为 correlation ID 传入分布式追踪系统
4. **Parent/Root 血缘**: 实现 AGENT-14 子 Agent 调用的转递逻辑

---

**Commit**: c0e1d8a (core), [docs commit]  
**Tests**: 11 passed (hermes_agent/tests/test_agent_17_turn_metadata.py)  
**Status**: ✅ 全部验收标准达成
