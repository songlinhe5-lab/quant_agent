# AGENT-16-NEXT: Prompt 版本控制与质量检测系统使用指南

## 📋 功能概览

本模块提供完整的 Prompt 生命周期管理，对标 RAG-style versioning + A/B testing + hot reload。

### 核心组件

| 组件 | 功能 | 典型用例 |
|------|------|----------|
| `PromptVersionManager` | 版本管理（semver + checksum + rollback） | 创建新版本、回滚历史版本 |
| `PromptQualityEvaluator` | 质量评估（perplexity/coherence/clarity/relevance/toxicity） | 上线前质量门禁检查 |
| `ABTestOrchestrator` | A/B 测试编排（流量分配 + 变体选择） | 对比 v1/v2 提示词效果 |
| `PromptHotReloader` | 热更新监听器（watchdog 机制） | 修改 .md 文件后自动 reload |

---

## 🚀 快速开始

### 1. 初始化版本管理器

```python
from hermes_agent.prompt_versioning import PromptVersionManager

# 指定 prompts/compact 目录作为存储位置
manager = PromptVersionManager("prompts/compact")

# 加载现有模板
template = manager.load_template("compact_summary_system_prompt")

print(f"当前版本：{template.current_version}")
print(f"历史版本数：{len(template.versions)}")
```

### 2. 创建新版本

```python
# 第一次编辑（默认 minor bump → 1.0.0）
v1 = manager.create_version(
    name="compact_summary_system_prompt",
    new_content="你是一个专业的量化交易记忆压缩助手。请总结以下内容...",
    metadata={"author": "alice", "change": "initial"}
)

# 第二次编辑（minor bump → 1.1.0）
v2 = manager.create_version(
    name="compact_summary_system_prompt",
    new_content="你是一个专业的 AI 研究助手。请优化摘要质量...",
    metadata={"author": "bob", "change": "role_update"}
)

print(f"最新版本号：{v2.version}")
print(f"Checksum: {v2.checksum}")
```

### 3. 回滚到历史版本

```python
# 回滚到 v1.0.0
success = manager.rollback("compact_summary_system_prompt", "1.0.0")

if success:
    template = manager.load_template("compact_summary_system_prompt")
    print(f"已回滚至版本：{template.current_version}")
    
    # 获取该版本内容
    content = manager.get_variant("compact_summary_system_prompt", "1.0.0")
```

### 4. 质量评估

```python
from hermes_agent.prompt_versioning import PromptQualityEvaluator

evaluator = PromptQualityEvaluator()

# 单指标评估
coherence_score = evaluator._compute_coherence("首先分析数据。其次提取关键信息。")
clarity_score = evaluator._compute_clarity("请总结以下内容，不超过 500 字。")

# 综合评估
metrics = evaluator.evaluate(
    prompt="请总结以下对话片段，提取核心事实与决策依据，用专业中文输出（不超过 2000 字）",
    context="用户询问 AAPL 股价走势"
)

print(f"综合评分：{metrics.composite_score:.2f}")
print(f"连贯性：{metrics.coherence:.2f}")
print(f"清晰度：{metrics.clarity:.2f}")
print(f"相关性：{metrics.relevance:.2f}")
print(f"毒性概率：{metrics.toxicity:.2f}")
```

### 5. A/B 测试框架

```python
from hermes_agent.prompt_versioning import ABTestOrchestrator

version_manager = PromptVersionManager("prompts/compact")
orchestrator = ABTestOrchestrator(version_manager)

# 创建 A/B 测试：对比 v1.0.0 vs v1.1.0
orchestrator.create_test(
    name="compact_prompt_v1_vs_v2",
    variants=[("v1", "1.0.0"), ("v2", "1.1.0")],
    metric="token_reduction_rate",  # 评估指标：Token 减少率
    traffic_split={"v1": 0.5, "v2": 0.5},  # 50/50 流量分配
    duration_hours=24,  # 持续 24 小时
)

# 为每个请求选择 Variant（基于 prompt hash 确定性路由）
context = "用户询问AAPL股价走势，需要总结过去 5 轮对话"
variant_id, version = orchestrator.select_variant("compact_prompt_v1_vs_v2", context)

print(f"本次选择 variant: {variant_id} (version: {version})")

# 记录结果
reduction_rate = 0.75  # 假设测得 Token 减少率为 75%
orchestrator.record_metric("compact_prompt_v1_vs_v2", variant_id, reduction_rate)

# 查看获胜者
winner = orchestrator.get_winner("compact_prompt_v1_vs_v2")
print(f"获胜 Variant: {winner}")
```

### 6. 热更新监听器

```python
from hermes_agent.prompt_versioning import PromptHotReloader

def on_template_changed(name: str, template):
    """回调函数：当 Prompt 文件被修改时触发"""
    print(f"✅ [HotReload] {name} 已更新到版本 {template.current_version}")
    # 重新加载 LLM 客户端或刷新缓存
    
reloader = PromptHotReloader(
    version_manager=version_manager,
    callback=on_template_changed
)

# 启动监听（后台线程）
print("👂 Prompt 热更新监听器已启动...")

# 停止监听
# reloader.stop()
```

---

## 📁 文件格式规范

### Prompt 版本文件结构

所有 Prompt 版本保存在 `prompts/compact/{name}.md` 文件中，采用 YAML frontmatter 分隔符：

```markdown
---
version: 1.0.0
created_at: 1692585600.0
author: alice
description: 初始版本
---
你是一个专业的量化交易记忆压缩助手。请高度凝练地总结以下对话中的关键事实、决策依据和结论，用简洁专业的中文输出（不超过 2000 字）。

---
version: 1.1.0
created_at: 1692672000.0
author: bob
change: role_update
---
你是一个专业的 AI 研究助手。请优化摘要质量，重点关注事实准确性和逻辑连贯性（不超过 2000 字）。

---
version: 1.2.0
created_at: 1692758400.0
author: charlie
change: length_optimization
---
你是量化交易记忆压缩专家。请按以下结构输出：
1. 核心事实（最多 3 点）
2. 决策依据（关键理由）
3. 下一步行动建议
用专业中文输出（不超过 1500 字）。
```

---

## 🔧 环境变量配置

在 `.env` 中配置 Prompt 相关参数：

```bash
# AGENT-16 · 摘要压缩配置
HERMES_COMPACT_SUMMARY_SYSTEM_PROMPT=  # 留空则使用默认值
HERMES_COMPACT_SYSTEM_PROMPT=
HERMES_COMPACT_MAX_SUMMARY_TOKENS=
```

---

## 🧪 运行单元测试

```bash
# 运行完整测试套件
pytest hermes_agent/tests/test_agent_16_next.py -v

# 单独运行某个测试
pytest hermes_agent/tests/test_agent_16_next.py::test_parse_yaml_frontmatter_basic -v
```

预期输出：

```
test_agent_16_next.py::test_parse_yaml_frontmatter_basic PASSED
test_agent_16_next.py::test_parse_yaml_frontmatter_numeric_types PASSED
test_agent_16_next.py::test_prompt_version_manager_create_version PASSED
test_agent_16_next.py::test_prompt_version_manager_rollback PASSED
test_agent_16_next.py::test_prompt_quality_evaluator_coherence PASSED
test_agent_16_next.py::test_prompt_quality_evaluator_clarity PASSED
test_agent_16_next.py::test_ab_test_orchestrator_select_variant PASSED
test_agent_16_next.py::test_prompt_quality_evaluator_composite_score PASSED

8 passed in 0.15s
```

---

## ⚠️ 注意事项

1. **依赖安装**：`watchdog` 需单独安装 (`pip install watchdog`)
2. **权限问题**：确保有 `prompts/compact/` 目录的读写权限
3. **并发安全**：多个进程同时编辑同一文件可能导致冲突，建议使用 Git 锁定
4. **性能考量**：质量评估器每调用一次会计算多个指标，建议在非实时场景下使用
5. **A/B 测试流量**：确定性感知的 hash-based routing 保证同一 context 始终分配到相同 variant

---

## 📈 未来扩展方向

1. **LLM 驱动的 Perplexity 计算**：使用真实语言模型计算困惑度而非启发式估算
2. **人工反馈集成**：支持用户对 Prompt 评分（thumbs up/down）
3. **自动化回归测试**：每次创建新版本自动跑 Golden Dataset
4. **Dashboard 可视化**：监控各版本的质量趋势和 A/B 测试结果
5. **Prompt 知识库**：将高质量 Prompt 沉淀到向量数据库供检索复用

---

**状态**: ✅ Production Ready  
**影响范围**: 新增模块，不影响现有代码