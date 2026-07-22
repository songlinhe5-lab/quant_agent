---
name: 📋 Task - OPT 子任务分解
about: 单个工程任务的详细跟踪 Issue (隶属于某个 Epic)
title: '[OPT-XXX-TASK] 具体任务描述'
labels: ['task', 'opt', 'phase-X']
assignees: []
---

# ✅ 任务概览

**所属 Epic**: #XXXXX (OPT-XXX: [Phase X] XXX 目标)  
**任务类型**: Refactoring / Feature / Test / Documentation  
**优先级**: P0 / P1 / P2  
**工作量估算**: Xh  
**预计耗时**: X 工作日  

---

## 🎯 任务目标

<!-- 用 1-2 句话说明这个任务要做什么 -->
例如：
> 实现 `DataSourceInterface` Protocol 定义，并创建 FutuImpl 初始版本。

---

## 🔍 背景信息

### 相关文档
- 输入材料：[`docs/OPT-001-004_Architecture_Review_Materials.md`](../OPT-001-004_Architecture_Review_Materials.md#议题一-router-层解耦)
- 决策记录：[`docs/VARB-2026-0708-001_Decision_Report.md`](待生成)
- 技术参考：[`backend/routers/market.py`](../../backend/routers/market.py#L156-L162)

### 当前状态
```python
# 示例：展示当前的反模式或待改进点
❌ 当前代码存在的问题...
```

---

## ✅ 验收标准 (Acceptance Criteria)

### 必须完成项
- [ ] 代码实现符合 Clean Architecture 规范
- [ ] 新增单元测试覆盖率 ≥ 80%
- [ ] CI/CD流水线验证通过
- [ ] 更新相关技术文档

### 可选增强项
- [ ] 添加性能基准测试对比
- [ ] 编写开发者指南注释
- [ ] 生成 API 图表文档

---

## 🛠️ 实施步骤

### Step 1: 准备工作
```bash
# 示例命令
git checkout -b feature/opt-xxx-task-description
pip install pytest-asyncio hypothesis
```

### Step 2: 核心实现
```python
# 伪代码示例
class DataSourceInterface(Protocol):
    name: str
    version: str
    
    def fetch(self, action: str, params: dict) -> Result:
        ...
```

### Step 3: 测试编写
```python
# tests/adapters/test_futu_impl.py
async def test_futu_quote_returns_success():
    adapter = FutuAdapter(...)
    result = await adapter.fetch("quote", {"ticker": "AAPL"})
    
    assert result.status == "success"
    assert "price" in result.data
```

### Step 4: 静态验证
```bash
# 运行脚本验证无旧模式残留
grep -r 'from.*data_source_router' backend/routers/*.py
# 期望输出：(空)
```

---

## 🚨 已知风险与阻塞因素

| 风险 ID | 描述 | 缓解策略 | 依赖项 |
|:-------|:-----|:---------|:-------|
| RISK-001 | SEC EDGAR API 限流 | 实现指数退避重试 | OPT-002 前置 |
| BLOCK-001 | 真人资源未到位 | PM 协调 Time Slot | 真人确认签字 |

---

## 📎 参考资源

### 代码链接
- [DataSourceInterface 协议定义](../../backend/adapters/ports/data_source_port.py#L10-L40)
- [FutuAdapter 初始实现](../../backend/adapters/futu/quote_adapter.py)
- [BacktestEngine PIT 过滤器](../../backend/domain/entities/backtest_engine.py)

### 外部文档
- SEC EDGAR API: https://www.sec.gov/edgar/sec-api-documentation
- Python Protocol ABC: https://peps.python.org/pep-0544/

### 工具脚本
- `scripts/check_protocol_implementations.py` - Protocol 完整性检查
- `scripts/run_pit_validation.sh` - PIT 测试验证

---

## 📝 变更历史

| 日期 | 操作人 | 变更内容 |
|:-----|:-------|:---------|
| 2026-07-08 | AI Agent | 初始化 Issue，基于 VARB 会议决议 |
| TBD | TBD | 真人工程师认领并补充实施细节 |

---

## ✍️ 责任人承诺

- [ ] **认领人**: _________________ 日期：______
- [ ] **代码审查**: _________________ 日期：______

**认领即表示承诺在上述时间窗口内完成交付**.
