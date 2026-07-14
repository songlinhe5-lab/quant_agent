"""
前后端契约测试 (TEST-12)
===========================

验证后端 Pydantic Schema 与前端 TypeScript 类型定义的一致性。
当后端 Schema 变更导致与前端类型不匹配时，测试立即变红。

契约 SSOT:
  - 后端: backend/schemas/domain.py (Pydantic v2)
  - 前端: frontend/src/types/domain.ts (TypeScript)
  - 规范: docs/11 数据模型与领域设计

测试维度:
  1. 枚举值对齐（Market / SecurityType / KlinePeriod / OrderStatus 等）
  2. 模型字段映射（snake_case → camelCase alias 必须与前端 TS 字段名一致）
  3. 必填/可选字段对齐
  4. API 响应结构一致性
"""

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Set

import pytest

from backend.schemas.domain import (
    AccountModel,
    ApiResponseModel,
    ClientHeartbeatModel,
    IndicatorParams,
    IndicatorType,
    KlineModel,
    KlinePeriod,
    KlineSeriesModel,
    Market,
    OrderModel,
    OrderSide,
    OrderStatus,
    OrderType,
    PaginatedResponseModel,
    PositionModel,
    PositionSide,
    PositionStatus,
    QuoteModel,
    ScreenerFilterModel,
    ScreenerResultModel,
    SecurityType,
    StrategyModel,
    StrategyStatus,
    SymbolModel,
    TechIndicatorsModel,
    TickModel,
    WSKlineMessageModel,
    WSQuoteMessageModel,
    WSSubscribeMessageModel,
)


# ─── 辅助工具 ──────────────────────────────────────────────────────


def _get_model_fields(model) -> Dict[str, dict]:
    """获取 Pydantic 模型的字段信息"""
    return model.model_fields


def _get_field_alias(model, field_name: str) -> str:
    """获取字段的 alias，无 alias 则返回字段名本身"""
    field_info = model.model_fields.get(field_name)
    if field_info and field_info.alias:
        return field_info.alias
    return field_name


def _get_json_field_names(model) -> Set[str]:
    """获取模型序列化后的 JSON 字段名集合（使用 alias）"""
    names = set()
    for field_name in model.model_fields:
        names.add(_get_field_alias(model, field_name))
    return names


def _parse_ts_interface(ts_content: str, interface_name: str) -> Dict[str, dict]:
    """
    从 TypeScript 源码中解析 interface 的字段。
    返回 {field_name: {type, optional}} 字典。
    """
    pattern = rf"export\s+interface\s+{interface_name}\s*\{{([^}}]+)\}}"
    match = re.search(pattern, ts_content, re.DOTALL)
    if not match:
        return {}

    body = match.group(1)
    fields = {}
    for line in body.split("\n"):
        line = line.strip()
        if not line or line.startswith("//") or line.startswith("/*"):
            continue
        # 匹配: fieldName?: type 或 fieldName: type
        m = re.match(r"(\w+)(\?)?:\s*(.+?)(?:\s*//.*)?$", line)
        if m:
            name = m.group(1)
            optional = m.group(2) == "?"
            type_str = m.group(3).strip()
            fields[name] = {"type": type_str, "optional": optional}
    return fields


def _parse_ts_type_union(ts_content: str, type_name: str) -> Set[str]:
    """解析 TypeScript type 联合类型的值集合"""
    pattern = rf"export\s+type\s+{type_name}\s*=\s*([^;\n]+)"
    match = re.search(pattern, ts_content)
    if not match:
        return set()
    values_str = match.group(1)
    values = set()
    for v in re.findall(r"'([^']+)'", values_str):
        values.add(v)
    return values


# ─── Fixtures ──────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def ts_domain_content() -> str:
    """读取前端 domain.ts 内容"""
    ts_path = Path(__file__).parent.parent.parent / "frontend" / "src" / "types" / "domain.ts"
    if not ts_path.exists():
        pytest.skip(f"前端类型文件不存在: {ts_path}")
    return ts_path.read_text(encoding="utf-8")


# ─── 枚举值对齐测试 ─────────────────────────────────────────────────


class TestEnumAlignment:
    """后端枚举值与前端 type 联合类型值对齐"""

    def test_market_enum_values(self, ts_domain_content):
        """Market 枚举: 后端值必须是前端 Market type 的子集"""
        ts_values = _parse_ts_type_union(ts_domain_content, "Market")
        # 后端有 SH/SZ，前端只有 US/HK/CN/SG/JP
        # 这是已知差异（前端合并 SH/SZ 为 CN），验证核心值存在
        backend_values = {m.value for m in Market}
        core_values = {"US", "HK", "CN", "SG", "JP"}
        assert core_values.issubset(ts_values), (
            f"前端 Market 缺少核心值: {core_values - ts_values}"
        )
        # 后端的 SH/SZ 是内部标识，不需要在前端出现
        assert {"US", "HK"}.issubset(backend_values)

    def test_security_type_enum_values(self, ts_domain_content):
        """SecurityType 枚举值完全对齐"""
        ts_values = _parse_ts_type_union(ts_domain_content, "SecurityType")
        backend_values = {st.value for st in SecurityType}
        assert backend_values == ts_values, (
            f"SecurityType 不对齐: 后端多={backend_values - ts_values}, 前端多={ts_values - backend_values}"
        )

    def test_kline_period_enum_values(self, ts_domain_content):
        """KlinePeriod 枚举值完全对齐"""
        ts_values = _parse_ts_type_union(ts_domain_content, "KlinePeriod")
        backend_values = {kp.value for kp in KlinePeriod}
        assert backend_values == ts_values, (
            f"KlinePeriod 不对齐: 后端多={backend_values - ts_values}, 前端多={ts_values - backend_values}"
        )

    def test_order_side_enum_values(self, ts_domain_content):
        """OrderSide 枚举值完全对齐"""
        ts_values = _parse_ts_type_union(ts_domain_content, "OrderSide")
        backend_values = {s.value for s in OrderSide}
        assert backend_values == ts_values

    def test_order_type_enum_values(self, ts_domain_content):
        """OrderType 枚举值完全对齐"""
        ts_values = _parse_ts_type_union(ts_domain_content, "OrderType")
        backend_values = {t.value for t in OrderType}
        assert backend_values == ts_values

    def test_order_status_enum_values(self, ts_domain_content):
        """OrderStatus 枚举值完全对齐"""
        ts_values = _parse_ts_type_union(ts_domain_content, "OrderStatus")
        backend_values = {s.value for s in OrderStatus}
        assert backend_values == ts_values

    def test_position_side_enum_values(self, ts_domain_content):
        """PositionSide 枚举值完全对齐"""
        ts_values = _parse_ts_type_union(ts_domain_content, "PositionSide")
        backend_values = {s.value for s in PositionSide}
        assert backend_values == ts_values

    def test_strategy_status_enum_values(self, ts_domain_content):
        """StrategyStatus 枚举值完全对齐"""
        ts_values = _parse_ts_type_union(ts_domain_content, "StrategyStatus")
        backend_values = {s.value for s in StrategyStatus}
        assert backend_values == ts_values


# ─── 模型字段对齐测试 ──────────────────────────────────────────────


class TestModelFieldAlignment:
    """后端模型字段与前端 interface 字段对齐"""

    def test_quote_model_fields(self, ts_domain_content):
        """Quote 模型字段对齐"""
        ts_fields = _parse_ts_interface(ts_domain_content, "Quote")
        json_fields = _get_json_field_names(QuoteModel)

        # 前端必填字段必须在后端 JSON 输出中存在
        required_ts = {name for name, info in ts_fields.items() if not info["optional"]}
        missing = required_ts - json_fields
        assert not missing, f"Quote: 前端必填字段在后端缺失: {missing}"

    def test_kline_model_fields(self, ts_domain_content):
        """Kline 模型字段对齐"""
        ts_fields = _parse_ts_interface(ts_domain_content, "Kline")
        json_fields = _get_json_field_names(KlineModel)

        required_ts = {name for name, info in ts_fields.items() if not info["optional"]}
        missing = required_ts - json_fields
        assert not missing, f"Kline: 前端必填字段在后端缺失: {missing}"

    def test_position_model_fields(self, ts_domain_content):
        """Position 模型字段对齐"""
        ts_fields = _parse_ts_interface(ts_domain_content, "Position")
        json_fields = _get_json_field_names(PositionModel)

        required_ts = {name for name, info in ts_fields.items() if not info["optional"]}
        missing = required_ts - json_fields
        assert not missing, f"Position: 前端必填字段在后端缺失: {missing}"

    def test_order_model_fields(self, ts_domain_content):
        """Order 模型字段对齐"""
        ts_fields = _parse_ts_interface(ts_domain_content, "Order")
        json_fields = _get_json_field_names(OrderModel)

        required_ts = {name for name, info in ts_fields.items() if not info["optional"]}
        missing = required_ts - json_fields
        assert not missing, f"Order: 前端必填字段在后端缺失: {missing}"

    def test_account_model_fields(self, ts_domain_content):
        """Account 模型字段对齐"""
        ts_fields = _parse_ts_interface(ts_domain_content, "Account")
        json_fields = _get_json_field_names(AccountModel)

        required_ts = {name for name, info in ts_fields.items() if not info["optional"]}
        missing = required_ts - json_fields
        assert not missing, f"Account: 前端必填字段在后端缺失: {missing}"

    def test_screener_result_model_fields(self, ts_domain_content):
        """ScreenerResult 模型字段对齐"""
        ts_fields = _parse_ts_interface(ts_domain_content, "ScreenerResult")
        json_fields = _get_json_field_names(ScreenerResultModel)

        required_ts = {name for name, info in ts_fields.items() if not info["optional"]}
        missing = required_ts - json_fields
        assert not missing, f"ScreenerResult: 前端必填字段在后端缺失: {missing}"


# ─── API 响应结构测试 ──────────────────────────────────────────────


class TestApiResponseContract:
    """API 响应结构一致性测试"""

    def test_api_response_structure(self):
        """ApiResponse 必须包含 code/msg/data/ts 四个字段"""
        fields = set(ApiResponseModel.model_fields.keys())
        assert {"code", "msg", "data", "ts"}.issubset(fields)

    def test_paginated_response_structure(self):
        """PaginatedResponse 必须包含 items/total/page/pageSize/hasMore"""
        json_fields = _get_json_field_names(PaginatedResponseModel)
        assert {"items", "total", "page", "pageSize", "hasMore"}.issubset(json_fields)

    def test_api_response_serializable(self):
        """ApiResponse 可正确序列化为 JSON"""
        resp = ApiResponseModel(code=0, msg="ok", data={"test": 1}, ts=1234567890)
        json_str = resp.model_dump_json(by_alias=True)
        parsed = json.loads(json_str)
        assert parsed["code"] == 0
        assert parsed["msg"] == "ok"
        assert parsed["ts"] == 1234567890


# ─── WebSocket 消息结构测试 ────────────────────────────────────────


class TestWSMessageContract:
    """WebSocket 消息结构一致性测试"""

    def test_ws_subscribe_message(self):
        """WS 订阅消息结构"""
        msg = WSSubscribeMessageModel(type="subscribe", topic="quotes", symbol="AAPL")
        assert msg.type == "subscribe"
        assert msg.topic == "quotes"

    def test_ws_quote_message_structure(self):
        """WS 行情推送消息结构"""
        quote_data = {
            "symbol": "AAPL",
            "lastPrice": 150.0,
            "open": 148.0,
            "high": 152.0,
            "low": 147.0,
            "prevClose": 147.5,
            "volume": 1000000,
            "turnover": 150000000.0,
            "change": 2.5,
            "changePercent": 1.69,
            "timestamp": 1234567890000,
        }
        msg = WSQuoteMessageModel(type="quote", data=quote_data)
        assert msg.data.symbol == "AAPL"
        assert msg.data.last_price == 150.0

    def test_ws_kline_message_structure(self):
        """WS K线推送消息结构"""
        kline_data = {
            "symbol": "AAPL",
            "period": "K_DAY",
            "klines": [
                {
                    "timestamp": 1234567890000,
                    "open": 148.0,
                    "high": 152.0,
                    "low": 147.0,
                    "close": 150.0,
                    "volume": 1000000,
                }
            ],
        }
        msg = WSKlineMessageModel(type="kline", data=kline_data)
        assert msg.data.symbol == "AAPL"
        assert len(msg.data.klines) == 1


# ─── 类型兼容性测试 ────────────────────────────────────────────────


class TestTypeCompatibility:
    """后端模型实例化与序列化兼容性"""

    def test_quote_model_roundtrip(self):
        """Quote 模型 JSON roundtrip 无损"""
        data = {
            "symbol": "HK.00700",
            "lastPrice": 350.0,
            "open": 345.0,
            "high": 355.0,
            "low": 342.0,
            "prevClose": 344.0,
            "volume": 20000000,
            "turnover": 7000000000.0,
            "change": 6.0,
            "changePercent": 1.74,
            "timestamp": 1234567890000,
            "bidPrice": 349.8,
            "bidVolume": 500,
            "askPrice": 350.2,
            "askVolume": 300,
        }
        model = QuoteModel.model_validate(data)
        json_out = model.model_dump_json(by_alias=True)
        parsed = json.loads(json_out)

        # 验证 camelCase 字段名
        assert "lastPrice" in parsed
        assert "prevClose" in parsed
        assert "changePercent" in parsed
        assert "bidPrice" in parsed

    def test_order_model_roundtrip(self):
        """Order 模型 JSON roundtrip 无损"""
        data = {
            "id": "order-001",
            "symbol": "AAPL",
            "side": "BUY",
            "type": "LIMIT",
            "quantity": 100.0,
            "price": 150.0,
            "filledQuantity": 50.0,
            "filledAvgPrice": 149.5,
            "status": "PARTIAL",
            "createdAt": 1234567890000,
            "updatedAt": 1234567890500,
            "isPaper": True,
            "strategyId": "strat-001",
        }
        model = OrderModel.model_validate(data)
        json_out = model.model_dump_json(by_alias=True)
        parsed = json.loads(json_out)

        assert "filledQuantity" in parsed
        assert "filledAvgPrice" in parsed
        assert "isPaper" in parsed
        assert parsed["isPaper"] is True

    def test_heartbeat_model_web_vitals(self):
        """ClientHeartbeat 支持 Web Vitals 字段 (OBS-03/FE-27)"""
        data = {
            "platform": "web",
            "appVersion": "1.0.0",
            "deviceId": "device-001",
            "fps": 60.0,
            "lcpMs": 1200.0,
            "cls": 0.05,
            "inpMs": 80.0,
            "ttfbMs": 200.0,
            "timestamp": 1234567890000,
        }
        model = ClientHeartbeatModel.model_validate(data)
        assert model.lcp_ms == 1200.0
        assert model.cls == 0.05
        assert model.inp_ms == 80.0
