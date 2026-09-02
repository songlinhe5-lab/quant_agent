"""TDX worker/service 单元测试 — mock tdxpy（patch _get_api），禁打真实外网。

覆盖：代码归一化 / 市场判定 / 周期映射 / 快照与分钟线 / 空结果如实为空 /
断线重建重试 / worker 分发错误语义化。
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pandas as pd
import pytest

from data_subservice._internal.tdx import client as tdx_client
from data_subservice._internal.tdx import service as tdx_service
from data_subservice.tdx_worker import handle_tdx


@pytest.fixture
def mock_tdx(monkeypatch):
    """注入假 TdxHq_API：patch _get_api 使 with_tdx 不触真实连接。"""
    api = MagicMock()
    api.get_security_quotes.return_value = []
    api.get_security_bars.return_value = []
    api.get_minute_time_data.return_value = []
    api.get_history_minute_time_data.return_value = []
    api.to_df.side_effect = lambda rows: pd.DataFrame(rows) if rows else pd.DataFrame()
    monkeypatch.setattr(tdx_client, "_get_api", lambda: api)
    yield api


# ── 归一化 / 市场判定 / 周期映射 ────────────────────────────────


@pytest.mark.parametrize(
    "raw,expected",
    [("600036", "600036"), ("sh.600000", "600000"), ("SZ.000001", "000001")],
)
def test_normalize_tdx_symbol_ok(raw, expected):
    assert tdx_client.normalize_tdx_symbol(raw) == expected


@pytest.mark.parametrize("bad", ["abc", "60000", "6000001"])
def test_normalize_tdx_symbol_rejects(bad):
    with pytest.raises(ValueError):
        tdx_client.normalize_tdx_symbol(bad)


@pytest.mark.parametrize(
    "code,market",
    [("600036", 1), ("688981", 1), ("000001", 0), ("300750", 0)],
)
def test_to_market(code, market):
    assert tdx_client.to_market(code) == market


@pytest.mark.parametrize("code", ["430047", "832000"])
def test_to_market_rejects_bj(code):
    with pytest.raises(ValueError, match="北交所"):
        tdx_client.to_market(code)


def test_freq_map_aliases():
    assert tdx_client.FREQ_MAP["5m"] == 0 and tdx_client.FREQ_MAP["day"] == 9
    assert tdx_client.FREQ_MAP["week"] == 10 and tdx_client.FREQ_MAP["month"] == 11


# ── service ────────────────────────────────────────────────────


def test_snapshot_empty_result_is_empty_not_error(mock_tdx):
    mock_tdx.get_security_quotes.return_value = []  # 非交易时段/停牌
    out = tdx_service.get_snapshot("600036")
    assert out["status"] == "success" and out["data"] == []


def test_snapshot_returns_records(mock_tdx):
    mock_tdx.get_security_quotes.return_value = [
        {"price": 10.5, "last_close": 10.4, "volume": 12345, "servertime": "20260901:09:30"}
    ]
    out = tdx_service.get_snapshot("sh.600036")
    assert out["data"][0]["price"] == 10.5 and out["source"] == "tdx"
    mock_tdx.get_security_quotes.assert_called_once_with([(1, "600036")])


def test_bars_maps_frequency_and_market(mock_tdx):
    mock_tdx.get_security_bars.return_value = [{"close": 10.0}]
    out = tdx_service.get_bars("600036", frequency="5m", offset=50)
    assert out["frequency"] == "5m" and out["offset"] == 50
    mock_tdx.get_security_bars.assert_called_once_with(0, 1, "600036", 0, 50)


def test_bars_clamps_protocol_limit(mock_tdx):
    mock_tdx.get_security_bars.return_value = [{"close": 1.0}]
    out = tdx_service.get_bars("000001", offset=5000)
    assert out["offset"] == 800  # 协议单次上限
    mock_tdx.get_security_bars.assert_called_once_with(9, 0, "000001", 0, 800)


def test_bars_invalid_frequency(mock_tdx):
    with pytest.raises(ValueError, match="不支持的 K 线周期"):
        tdx_service.get_bars("600036", frequency="3s")


def test_minutes_with_date_uses_history_api(mock_tdx):
    mock_tdx.get_history_minute_time_data.return_value = [{"price": 10.5}]
    out = tdx_service.get_minutes("600036", date="2026-08-29")
    mock_tdx.get_history_minute_time_data.assert_called_once_with(1, "600036", "20260829")
    assert out["data"] == [{"price": 10.5}]


def test_minutes_without_date_uses_intraday_api(mock_tdx):
    mock_tdx.get_minute_time_data.return_value = [{"price": 10.6}]
    out = tdx_service.get_minutes("600036")
    mock_tdx.get_minute_time_data.assert_called_once_with(1, "600036")
    assert out["data"] == [{"price": 10.6}]


def test_none_response_raises_and_worker_semantizes(mock_tdx):
    mock_tdx.get_security_quotes.return_value = None  # 服务器异常
    with pytest.raises(RuntimeError, match="连接或服务器异常"):
        tdx_service.get_snapshot("600036")


# ── 断线重建 ───────────────────────────────────────────────────


def test_with_tdx_rebuilds_on_disconnect(mock_tdx):
    mock_tdx.get_security_bars.side_effect = [OSError("connection reset"), [{"close": 1.0}]]
    out = tdx_service.get_bars("600036")
    assert out["data"] == [{"close": 1.0}]  # 首调断线 → 重建 → 成功
    assert mock_tdx.get_security_bars.call_count == 2


# ── worker 分发 ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_worker_snapshot_ok(mock_tdx):
    mock_tdx.get_security_quotes.return_value = [{"price": 10.5}]
    out = await handle_tdx("QUOTE_CN_SNAPSHOT", {"symbol": "600036"})
    assert out["status"] == "success" and out["data"][0]["price"] == 10.5


@pytest.mark.asyncio
async def test_worker_bad_symbol_is_bad_request():
    out = await handle_tdx("QUOTE_CN_SNAPSHOT", {"symbol": "xyz"})
    assert out["status"] == "error" and out["error_category"] == "bad_request"


@pytest.mark.asyncio
async def test_worker_bj_symbol_is_bad_request():
    out = await handle_tdx("QUOTE_CN_SNAPSHOT", {"symbol": "430047"})
    assert out["status"] == "error" and out["error_category"] == "bad_request"


@pytest.mark.asyncio
async def test_worker_unknown_action():
    out = await handle_tdx("NOPE", {"symbol": "600036"})
    assert out["status"] == "error" and "未知" in out["message"]
