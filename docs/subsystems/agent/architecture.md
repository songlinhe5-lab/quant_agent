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

### 3.1 入参规范（parameters JSON Schema）

每个 Tool 的 `parameters` 必须遵循以下 JSON Schema 结构：

```python
parameters = {
    "type": "object",
    "properties": {
        "param_name": {
            "type": "string",              # 类型：string / integer / number / boolean / array / object
            "description": "参数说明",       # 必填：LLM 依赖此说明理解参数含义
            "enum": [...],                  # 可选：枚举值约束
            "default": "default_value",     # 可选：默认值
        },
        # ... 更多参数
    },
    "required": ["param_a", "param_b"],    # 必填：列出所有必填参数名
}
```

**规则**：
- 所有参数必须有 `description`，LLM 依赖此生成正确调用
- 枚举类参数必须用 `enum` 约束，防止 LLM 幻觉
- 可选参数必须标注 `default` 值
- `ticker` 类参数由 `BaseTool.normalize_ticker()` 统一格式化，Tool 内部无需重复处理

### 3.2 出参规范（统一响应协议）

所有 Tool 返回值必须是 `Dict[str, Any]`，遵循以下统一协议：

**成功响应**：
```python
{
    "status": "success",           # 必填："success" | "error" | "rate_limited"
    "data": { ... },               # 成功时必填：业务数据
    "message": "可选提示",          # 可选：给 LLM 的额外上下文
}
```

**失败响应**：
```python
{
    "status": "error",             # "error" | "rate_limited"
    "message": "错误描述",          # 必填：人类可读的错误说明
    "error_code": "ERR_CODE",      # 可选：结构化错误码（见 §3.3）
}
```

**限流响应**（RL-14）：
```python
{
    "status": "rate_limited",
    "message": "数据源限流，已重试 3 次仍未恢复。",
    "retry_after_seconds": 30.0,
    "attempts": 3,
}
```

### 3.3 错误码枚举

| 错误码 | 含义 | 触发场景 |
|:---|:---|:---|
| `MISSING_PARAM` | 缺失必要参数 | `required` 参数未提供 |
| `INVALID_PARAM` | 参数值非法 | 枚举值不匹配 / 类型错误 |
| `DATA_NOT_FOUND` | 数据不存在 | 后端返回空结果 |
| `BACKEND_ERROR` | 后端网关报错 | HTTP 5xx |
| `RATE_LIMITED` | 数据源限流 | HTTP 429/503 |
| `TIMEOUT` | 请求超时 | 网络超时 |
| `UNSUPPORTED_ACTION` | 不支持的操作 | action 枚举值无效 |
| `AUTH_FAILED` | 认证失败 | Token 过期 / 无效 |

### 3.4 Tool 开发骨架模板

```python
# hermes_agent/tools/example_tool.py
import os
from typing import Dict, Any
from .base import BaseTool
from .secure_client import SecureAsyncClient
from hermes_agent.tool_registry import register_tool

@register_tool
class ExampleTool(BaseTool):
    """工具功能说明（LLM 可读的描述）"""
    name = "example_tool"
    description = "一句话说明工具用途，供 LLM 决策调用时机。"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["QUERY", "DETAIL"],
                "description": "操作类型",
            },
            "ticker": {
                "type": "string",
                "description": "股票代码，如 AAPL, 0700.HK",
            },
        },
        "required": ["action", "ticker"],
    }

    async def run(self, action: str, ticker: str) -> Dict[str, Any]:
        backend_url = os.getenv("BACKEND_API_URL", "http://127.0.0.1:8000")
        ticker = self.normalize_ticker(ticker)

        # 1. 参数校验
        if action not in ("QUERY", "DETAIL"):
            return {"status": "error", "message": f"不支持的操作: {action}", "error_code": "UNSUPPORTED_ACTION"}

        # 2. 构建请求
        url = f"{backend_url}/api/v1/example"
        params = {"action": action, "ticker": ticker}

        # 3. 限流感知请求（RL-14）
        async with SecureAsyncClient(timeout=15.0) as client:
            result = await self.rate_limit_aware_request(client, "GET", url, params=params)

        # 4. 结果校验
        if result.get("status") == "error":
            return result
        if not result.get("data"):
            return {"status": "error", "message": f"未找到 {ticker} 的数据", "error_code": "DATA_NOT_FOUND"}

        return {"status": "success", "data": result["data"]}
```

### 3.5 测试模板

```python
# backend/tests/tools/test_example_tool.py
import pytest
from hermes_agent.tools.example_tool import ExampleTool

@pytest.fixture
def tool():
    return ExampleTool()

class TestExampleTool:
    @pytest.mark.asyncio
    async def test_success_path(self, tool):
        """正常调用路径"""
        result = await tool.run(action="QUERY", ticker="AAPL")
        assert result["status"] == "success"
        assert "data" in result

    @pytest.mark.asyncio
    async def test_missing_param(self, tool):
        """缺失必要参数"""
        result = await tool.run(action="QUERY", ticker="")
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_unsupported_action(self, tool):
        """不支持的操作类型"""
        result = await tool.run(action="INVALID", ticker="AAPL")
        assert result["status"] == "error"
        assert result.get("error_code") == "UNSUPPORTED_ACTION"

    @pytest.mark.asyncio
    async def test_data_not_found(self, tool):
        """数据不存在路径"""
        result = await tool.run(action="QUERY", ticker="NONEXISTENT")
        assert result["status"] == "error"
        assert result.get("error_code") == "DATA_NOT_FOUND"
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
| 2026-07-13 | [DOC-01] 补充 §3.1~3.5 Tool 开发模板：入参 JSON Schema 规范 + 出参统一响应协议 + 错误码枚举 + 骨架模板 + 测试模板 |
| 2026-06-27 | 初始版本，14个 Tool 清单、ReAct 循环说明 |
