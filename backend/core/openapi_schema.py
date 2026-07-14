"""
BE-19: OpenAPI / Swagger 文档增强

- 统一 Info / Tags
- 为缺失 summary 的 operation 补齐（docstring 首行 → 路径人话）
- 为响应注入统一 {code,msg,data,ts} 示例
- 为缺失 example 的 requestBody 注入占位示例
"""

from __future__ import annotations

import os
import re
from typing import Any, Callable, Optional

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

API_VERSION = os.getenv("QUANT_API_VERSION", "1.1.0")

OPENAPI_TITLE = "Quant Agent Data Gateway"
OPENAPI_DESCRIPTION = """
Quant Agent 执行引擎 HTTP/WS/SSE 契约（BE-19）。

## 统一响应

```json
{"code": 0, "msg": "ok", "data": {}, "ts": 1719475200000}
```

- `code=0` 成功；非零见错误码（`docs/10` §1.4）
- 响应头 `X-Trace-Id` 用于全链路追踪（BE-10）

## 机器可读契约

导出产物：`docs/openapi.json`（`python scripts/export_openapi.py`）。
人工互校文档：`docs/10. API接口规范.md`。
"""

OPENAPI_TAGS: list[dict[str, str]] = [
    {"name": "Auth", "description": "登录 / Token / 用户信息"},
    {"name": "Market & Portfolio", "description": "行情快照、K 线、资金流、期权链"},
    {"name": "OMS", "description": "下单与交易执行（含沙箱）"},
    {"name": "OMS & Live Bots", "description": "实盘 Bot / Kill Switch / 持仓状态"},
    {"name": "Screener", "description": "智能选股与条件模板"},
    {"name": "Backtesting Engine", "description": "回测任务提交与查询"},
    {"name": "Backtest Reports", "description": "回测报告持久化与可复现清单"},
    {"name": "Data Lake Snapshots", "description": "Parquet 数据湖快照版本"},
    {"name": "Macro Calendar", "description": "宏观日历与情绪"},
    {"name": "Strategy Dev", "description": "策略实验室"},
    {"name": "Risk", "description": "风控雷达与因子"},
    {"name": "Alert Center", "description": "多通道告警规则"},
    {"name": "Client APM", "description": "客户端心跳与性能上报"},
    {"name": "system", "description": "系统 APM / 数据质量"},
    {"name": "Audit", "description": "审计日志"},
    {"name": "Search", "description": "全局检索"},
    {"name": "Preferences", "description": "用户偏好设置"},
    {"name": "Data Source Proxy", "description": "数据源统一代理"},
    {"name": "DataSource Rate Limit", "description": "限流状态与分析"},
    {"name": "futu-admin", "description": "Futu OpenD 管理"},
    {"name": "Internal", "description": "内网内部接口（HMAC）"},
    {"name": "default", "description": "健康检查 / Chat / Session / MCP"},
]

SUCCESS_EXAMPLE: dict[str, Any] = {
    "code": 0,
    "msg": "ok",
    "data": {},
    "ts": 1719475200000,
}

ERROR_EXAMPLE: dict[str, Any] = {
    "code": 2001,
    "msg": "请求参数校验失败",
    "data": None,
    "ts": 1719475200000,
    "trace_id": "abcdef0123456789abcdef0123456789",
}

AUTH_ERROR_EXAMPLE: dict[str, Any] = {
    "code": 1001,
    "msg": "Token 缺失",
    "data": None,
    "ts": 1719475200000,
}

# 常见路径的精炼 summary（优先于自动生成）
SUMMARY_OVERRIDES: dict[tuple[str, str], str] = {
    ("get", "/api/v1/health"): "健康检查（Redis / DB / Futu）",
    ("get", "/api/v1/cluster"): "集群/节点状态总览",
    ("post", "/api/v1/chat"): "Hermes Agent 对话（SSE 流）",
    ("get", "/api/v1/chat/suggestions"): "Agent 追问建议",
    ("get", "/api/v1/sessions"): "会话列表",
    ("get", "/api/v1/sessions/{session_id}"): "会话详情",
    ("get", "/api/v1/market/quote"): "实时行情快照",
    ("get", "/api/v1/market/history"): "历史 K 线",
    ("post", "/api/v1/market/kline/sync"): "K 线仓库同步",
    ("get", "/api/v1/market/fund-flow"): "主力资金流向",
    ("get", "/api/v1/market/option-chain"): "期权链",
    ("websocket", "/api/v1/market/quotes/ws"): "行情 WebSocket",
    ("post", "/api/v1/auth/login"): "登录获取 Access Token",
    ("post", "/api/v1/auth/refresh"): "刷新 Access Token",
    ("post", "/api/v1/auth/logout"): "登出",
    ("get", "/api/v1/auth/me"): "当前用户信息",
    ("post", "/api/v1/screener/run"): "自然语言选股",
    ("get", "/api/v1/oms/positions"): "当前持仓",
    ("post", "/api/v1/trade/order"): "下单（沙箱/实盘由安全锁控制）",
    ("post", "/api/v1/client/heartbeat"): "客户端 APM 心跳",
    ("get", "/"): "服务根路径",
}


def _first_line(text: Optional[str]) -> str:
    if not text:
        return ""
    for line in text.strip().splitlines():
        cleaned = line.strip().lstrip("#").strip()
        if cleaned:
            return cleaned[:120]
    return ""


def _humanize_path(method: str, path: str) -> str:
    """从 METHOD + path 生成可读 summary。"""
    # /api/v1/market/quote → Market Quote
    trimmed = re.sub(r"^/api/v1", "", path)
    trimmed = re.sub(r"\{[^}]+\}", "", trimmed)
    parts = [p for p in trimmed.split("/") if p]
    if not parts:
        label = "Root"
    else:
        label = " ".join(p.replace("-", " ").replace("_", " ").title() for p in parts[-2:])
    return f"{method.upper()} {label}"


def _ensure_response_examples(operation: dict[str, Any]) -> None:
    responses = operation.setdefault("responses", {})
    for code, example in (
        ("200", SUCCESS_EXAMPLE),
        ("201", SUCCESS_EXAMPLE),
        ("400", ERROR_EXAMPLE),
        ("401", AUTH_ERROR_EXAMPLE),
        ("422", ERROR_EXAMPLE),
        ("500", ERROR_EXAMPLE),
    ):
        if code not in responses:
            continue
        resp = responses[code]
        if not isinstance(resp, dict):
            continue
        content = resp.setdefault("content", {})
        app_json = content.setdefault("application/json", {})
        if "example" not in app_json and "examples" not in app_json:
            app_json["example"] = example

    # 保证至少有一个带统一 envelope 示例的成功响应
    if "200" not in responses and "201" not in responses:
        responses["200"] = {
            "description": "Success",
            "content": {"application/json": {"example": SUCCESS_EXAMPLE}},
        }
    elif "200" in responses and isinstance(responses["200"], dict):
        content = responses["200"].setdefault("content", {})
        if not content:
            content["application/json"] = {"example": SUCCESS_EXAMPLE}


def _ensure_request_example(operation: dict[str, Any]) -> None:
    body = operation.get("requestBody")
    if not isinstance(body, dict):
        return
    content = body.get("content")
    if not isinstance(content, dict):
        return
    for media in content.values():
        if not isinstance(media, dict):
            continue
        if media.get("example") or media.get("examples"):
            continue
        schema = media.get("schema") or {}
        # 有 $ref 时给通用 object 示例，避免 Swagger 空白
        media["example"] = {"_note": "见 Schema 字段说明；统一响应见 {code,msg,data,ts}"}
        if isinstance(schema, dict) and schema.get("type") == "object":
            props = schema.get("properties") or {}
            if props:
                media["example"] = {
                    k: (v.get("default") if isinstance(v, dict) else None)
                    for k, v in list(props.items())[:8]
                }


def enrich_openapi_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """就地增强 OpenAPI schema，返回同一对象。"""
    info = schema.setdefault("info", {})
    info.setdefault("title", OPENAPI_TITLE)
    info["version"] = API_VERSION
    info["description"] = OPENAPI_DESCRIPTION.strip()

    if "tags" not in schema or not schema["tags"]:
        schema["tags"] = OPENAPI_TAGS

    components = schema.setdefault("components", {})
    schemas = components.setdefault("schemas", {})
    schemas.setdefault(
        "ApiResponse",
        {
            "type": "object",
            "description": "统一响应信封（docs/10 §1.2）",
            "required": ["code", "msg", "data", "ts"],
            "properties": {
                "code": {"type": "integer", "example": 0},
                "msg": {"type": "string", "example": "ok"},
                "data": {"description": "业务负载"},
                "ts": {"type": "integer", "example": 1719475200000},
                "trace_id": {
                    "type": "string",
                    "description": "可选；错误时附带",
                    "example": "abcdef0123456789abcdef0123456789",
                },
            },
            "example": SUCCESS_EXAMPLE,
        },
    )

    paths = schema.get("paths") or {}
    for path, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            if method in ("parameters", "summary", "description", "servers"):
                continue
            if not isinstance(operation, dict):
                continue
            key = (method.lower(), path)
            override = SUMMARY_OVERRIDES.get(key)
            if override:
                operation["summary"] = override
            elif not operation.get("summary"):
                from_doc = _first_line(operation.get("description"))
                operation["summary"] = from_doc or _humanize_path(method, path)

            if not operation.get("description"):
                operation["description"] = (
                    f"{operation['summary']}\n\n"
                    "响应遵循统一信封 `{code, msg, data, ts}`；"
                    "失败时参见错误码表（docs/10）。"
                )

            _ensure_response_examples(operation)
            _ensure_request_example(operation)

    return schema


def build_openapi_schema(app: FastAPI) -> dict[str, Any]:
    """生成并增强 OpenAPI schema（不写缓存）。"""
    raw = get_openapi(
        title=OPENAPI_TITLE,
        version=API_VERSION,
        description=OPENAPI_DESCRIPTION.strip(),
        routes=app.routes,
        tags=OPENAPI_TAGS,
    )
    return enrich_openapi_schema(raw)


def install_custom_openapi(app: FastAPI) -> Callable[[], dict[str, Any]]:
    """挂载自定义 openapi() 到 FastAPI app。"""

    def custom_openapi() -> dict[str, Any]:
        if app.openapi_schema is not None:
            return app.openapi_schema
        app.openapi_schema = build_openapi_schema(app)
        return app.openapi_schema

    app.openapi = custom_openapi  # type: ignore[method-assign]
    return custom_openapi


def iter_operations(schema: dict[str, Any]):
    """Yield (method, path, operation)."""
    for path, path_item in (schema.get("paths") or {}).items():
        if not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            if method in ("parameters", "summary", "description", "servers"):
                continue
            if isinstance(operation, dict):
                yield method.lower(), path, operation
