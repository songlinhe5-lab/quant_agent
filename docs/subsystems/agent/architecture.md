# Hermes Agent 子系统架构文档

> 最后更新：2026-06-27 | 版本：V1.0

## 一、目录结构

```
hermes_agent/
├── agent.py              ReAct 推理引擎主类（Plan/Tool/Verify/Output 循环）
├── tool_registry.py      Tool 动态注册与调用分发
├── tools/                量化工具集（14个标准工具）
│   ├── base.py           BaseTool 基类（统一接口规范）
│   ├── decorators.py     @tool 装饰器（自动注册 + 异常包装）
│   ├── broker_market_tool.py    行情感知（QUOTE/HISTORY/FUND_FLOW/OPTION_CHAIN）
│   ├── fundamental_data_tool.py 基本面数据（PE/PB/ROE + FRED 路由）
│   ├── screener_tool.py         智能选股
│   ├── macro_news_tool.py       宏观新闻
│   ├── company_news_tool.py     个股新闻
│   ├── macro_calendar_tool.py   经济日历
│   ├── fred_macro_tool.py       FRED 宏观序列
│   ├── financial_report_tool.py 财报深度解析
│   ├── knowledge_base_tool.py   RAG 全局知识库检索
│   ├── delete_knowledge_tool.py 知识库清理
│   ├── research_tool.py         网页正文提取
│   ├── optimize_strategy_tool.py 策略优化建议
│   ├── insider_tool.py          内幕交易数据
│   ├── broker_trade_tool.py     模拟交易执行
│   └── notification_tool.py     消息推送
├── actions/              复合动作（多 Tool 编排）
├── plugins/              可选插件（按需加载）
└── skills/               技能记忆（SKILL.md 格式）
```

## 二、ReAct 推理循环

```
用户指令（自然语言）
    ↓
[Plan] 分析意图 → 制定工具调用计划
    ↓
[Tool] 执行工具调用（可并行多个）
    ↓
[Verify] 校验返回数据（非空？时间戳新鲜？数值合理？）
    ↓
[Output] 生成回答（SSE 逐 token 推送至前端）
    ↑
如需继续，回到 [Tool] 步骤（最多 10 轮）
```

**Verify 步骤必须检查**：
- Tool 返回值非空（非 `None` / `{}` / `[]`）
- 时间戳新鲜度（金融数据超过 24h 应警告）
- 数值范围合理性（价格不为负，涨跌幅不超过 ±50%）

## 三、Tool 接口规范

```python
# hermes_agent/tools/base.py
from abc import ABC, abstractmethod
from typing import Any

class BaseTool(ABC):
    name: str                # 工具名（与 AGENTS.md §2 对应）
    description: str         # LLM 调用时的工具说明
    parameters: dict         # JSON Schema 参数定义

    @abstractmethod
    async def execute(self, **kwargs) -> dict[str, Any]:
        """统一执行接口，失败抛 ToolExecutionError"""
        ...

class ToolExecutionError(Exception):
    def __init__(self, tool_name: str, error_code: str, message: str):
        self.tool_name = tool_name
        self.error_code = error_code
        super().__init__(message)
```

## 四、新增 Tool 标准流程

```
1. 在 hermes_agent/tools/ 下创建 {name}_tool.py
2. 继承 BaseTool，实现 execute() 方法
3. 在 tool_registry.py 的 TOOL_REGISTRY 列表中注册
4. 在 AGENTS.md §2 工具矩阵中添加说明
5. 创建 tests/tools/test_{name}_tool.py
   - 正常调用路径测试
   - 数据源失败降级测试
   - 参数边界测试
6. 更新本文档的 Tool 列表
```

## 五、当前 Tool 清单

| Tool 名称 | 文件 | 用途 | 测试状态 |
|:---|:---|:---|:---:|
| `get_broker_market_data` | broker_market_tool.py | 行情/历史/资金流/期权链 | 需补充 |
| `get_fundamental_data` | fundamental_data_tool.py | 基本面/FRED 路由 | 需补充 |
| `screen_stocks` | screener_tool.py | 智能选股 | 需补充 |
| `get_macro_news` | macro_news_tool.py | 宏观新闻 | 需补充 |
| `get_company_news` | company_news_tool.py | 个股新闻 | 需补充 |
| `get_macro_calendar` | macro_calendar_tool.py | 经济日历 | 需补充 |
| `get_fred_macro_data` | fred_macro_tool.py | FRED 时序数据 | 需补充 |
| `analyze_financial_report` | financial_report_tool.py | 财报解析 | 需补充 |
| `search_global_knowledge` | knowledge_base_tool.py | RAG 知识库检索 | 需补充 |
| `delete_global_knowledge` | delete_knowledge_tool.py | 知识库清理 | 需补充 |
| `fetch_webpage` | research_tool.py | 网页正文提取 | 需补充 |
| `optimize_strategy` | optimize_strategy_tool.py | 策略优化建议 | 需补充 |
| `get_insider_trading` | insider_tool.py | 内幕交易数据 | 需补充 |
| `send_notification` | notification_tool.py | 消息推送 | 需补充 |

## 六、性能基准

| 指标 | 目标 | 说明 |
|:---|:---:|:---|
| 单 Tool 调用 P50 | ≤ 2s | 包含网络 IO |
| 单 Tool 调用 P99 | ≤ 8s | 含外部 API 限速等待 |
| ReAct 循环最大轮次 | 10 轮 | 超出强制终止并告警 |
| SSE 首 token 延迟 | ≤ 1s | 用户感知流畅度 |

## 七、变更记录

| 日期 | 变更 |
|:---|:---|
| 2026-06-27 | 初始版本，14个 Tool 清单、ReAct 循环说明 |
