"""TDX worker/service 单元测试 — mock mootdx（sys.modules 注入），禁打真实外网。

覆盖：代码归一化 / 周期映射 / 快照与分钟线 / 空 DataFrame 如实为空 /
断线重建重试 / worker 分发错误语义化。
"""

from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import MagicMock

import pandas as pd
import pytest

from data_subservice._internal.tdx import client as tdx_client
from data_subservice._internal.tdx import service as tdx_service
from data_subservice.tdx_worker import handle_tdx


@pytest.fixture
def mock_mootdx(monkeypatch):
    """注入假 mootdx.quotes.Quotes：factory 返回可逐测试覆写的 client。"""
    client = MagicMock()
    client.quotes = MagicMock(return_value=pd.DataFrame())
    client.bars = MagicMock(return_value=pd.DataFrame())
    client.minutes = MagicMock(return_value=pd.DataFrame())
    quotes_mod = ModuleType("mootdx.quotes")
    quotes_mod.Quotes = MagicMock(factory=MagicMock(return_value=client))
    mootdx_mod = ModuleType("mootdx")
    mootdx_mod.quotes = quotes_mod
    monkeypatch.setitem(sys.modules, "mootdx", mootdx_mod)
    monkeypatch.setitem(sys.modules, "mootdx.quotes", quotes_mod)
    tdx_client.reset_client()
    yield client
    tdx_client.reset_client()


# ── 归一化 / 周期映射 ───────────────────────────────────────────


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


def test_freq_map_aliases():
    assert tdx_client.FREQ_MAP["5m"] == 0 and tdx_client.FREQ_MAP["day"] == 9
    assert tdx_client.FREQ_MAP["week"] == 10 and tdx_client.FREQ_MAP["month"] == 11


# ── service ────────────────────────────────────────────────────


def test_snapshot_empty_frame_is_empty_not_error(mock_mootdx):
    mock_mootdx.quotes.return_value = pd.DataFrame()  # 非交易时段/停牌
    out = tdx_service.get_snapshot("600036")
    assert out["status"] == "success" and out["data"] == []


def test_snapshot_returns_records(mock_mootdx):
    mock_mootdx.quotes.return_value = pd.DataFrame(
        [{"price": 10.5, "last_close": 10.4, "volume": 12345, "servertime": "20260901:09:30"}]
    )
    out = tdx_service.get_snapshot("sh.600036")
    assert out["data"][0]["price"] == 10.5 and out["source"] == "tdx"


def test_bars_maps_frequency(mock_mootdx):
    mock_mootdx.bars.return_value = pd.DataFrame([{"close": 10.0}])
    out = tdx_service.get_bars("600036", frequency="5m", offset=50)
    assert out["frequency"] == "5m" and out["offset"] == 50
    mock_mootdx.bars.assert_called_once_with(symbol="600036", frequency=0, offset=50)


def test_bars_invalid_frequency(mock_mootdx):
    with pytest.raises(ValueError, match="不支持的 K 线周期"):
        tdx_service.get_bars("600036", frequency="3s")


def test_minutes_with_date(mock_mootdx):
    mock_mootdx.minutes.return_value = pd.DataFrame([{"price": 10.5}])
    out = tdx_service.get_minutes("600036", date="2026-08-29")
    mock_mootdx.minutes.assert_called_once_with(symbol="600036", date="2026-08-29")
    assert out["data"] == [{"price": 10.5}]


def test_none_response_raises_and_worker_semantizes(mock_mootdx):
    mock_mootdx.quotes.return_value = None  # 服务器异常
    with pytest.raises(RuntimeError, match="连接或服务器异常"):
        tdx_service.get_snapshot("600036")


# ── 断线重建 ───────────────────────────────────────────────────


def test_call_client_rebuilds_on_disconnect(mock_mootdx, monkeypatch):
    mock_mootdx.bars.side_effect = [OSError("connection reset"), pd.DataFrame([{"close": 1.0}])]
    out = tdx_service.get_bars("600036")
    assert out["data"] == [{"close": 1.0}]  # 首调断线 → 重建 → 成功
    assert mock_mootdx.bars.call_count == 2


# ── worker 分发 ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_worker_snapshot_ok(mock_mootdx):
    mock_mootdx.quotes.return_value = pd.DataFrame([{"price": 10.5}])
    out = await handle_tdx("QUOTE_CN_SNAPSHOT", {"symbol": "600036"})
    assert out["status"] == "success" and out["data"][0]["price"] == 10.5


@pytest.mark.asyncio
async def test_worker_bad_symbol_is_bad_request():
    out = await handle_tdx("QUOTE_CN_SNAPSHOT", {"symbol": "xyz"})
    assert out["status"] == "error" and out["error_category"] == "bad_request"


@pytest.mark.asyncio
async def test_worker_unknown_action():
    out = await handle_tdx("NOPE", {"symbol": "600036"})
    assert out["status"] == "error" and "未知" in out["message"]
