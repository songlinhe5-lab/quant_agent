"""BaoStock worker/service 单元测试 — mock SDK（sys.modules 注入），禁打真实外网。

覆盖：代码归一化 / 结构锁（error_code 非 0 显式失败）/ K 线与季频财务 /
复权因子 / worker 分发（to_thread 语义化错误、bad_request 不静默）。
"""

from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock

import pytest

from data_subservice._internal.baostock import client as bs_client
from data_subservice._internal.baostock import service as bs_service
from data_subservice.baostock_worker import handle_baostock

# ── SDK mock 基建 ────────────────────────────────────────────────


class _FakeRS:
    """模拟 baostock ResultData：error_code/fields/逐行迭代。"""

    def __init__(self, fields, rows, error_code="0", error_msg=""):
        self.fields = fields
        self._rows = list(rows)
        self.error_code = error_code
        self.error_msg = error_msg
        self._i = 0

    def next(self):
        return self._i < len(self._rows)

    def get_row_data(self):
        row = self._rows[self._i]
        self._i += 1
        return row


@pytest.fixture
def mock_bs(monkeypatch):
    """注入假 baostock 模块：login 幂等成功、查询函数可逐测试覆写。"""
    bs = ModuleType("baostock")
    bs.login = MagicMock(return_value=SimpleNamespace(error_code="0", error_msg=""))
    bs.query_history_k_data_plus = MagicMock(return_value=_FakeRS([], []))
    bs.query_profit_data = MagicMock(return_value=_FakeRS([], []))
    bs.query_growth_data = MagicMock(return_value=_FakeRS([], []))
    bs.query_balance_data = MagicMock(return_value=_FakeRS([], []))
    bs.query_cashflow_data = MagicMock(return_value=_FakeRS([], []))
    bs.query_adjust_factor = MagicMock(return_value=_FakeRS([], []))
    bs.query_stock_basic = MagicMock(return_value=_FakeRS([], []))
    monkeypatch.setitem(sys.modules, "baostock", bs)
    bs_client.reset_login()
    yield bs
    bs_client.reset_login()


# ── 代码归一化 ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("600000", "sh.600000"),
        ("688981", "sh.688981"),
        ("000001", "sz.000001"),
        ("300750", "sz.300750"),
        ("SH.600000", "sh.600000"),
        ("sz.000001", "sz.000001"),
    ],
)
def test_normalize_bs_code_ok(raw, expected):
    assert bs_client.normalize_bs_code(raw) == expected


@pytest.mark.parametrize("bad", ["830001", "430047", "abc", "60000", "6000001"])
def test_normalize_bs_code_rejects_out_of_coverage(bad):
    with pytest.raises(ValueError):
        bs_client.normalize_bs_code(bad)


# ── 结构锁：错误码非 0 显式失败 ────────────────────────────────


def test_query_rows_explicit_error(mock_bs):
    rs = _FakeRS(["date"], [], error_code="10001", error_msg="network down")
    with pytest.raises(RuntimeError, match="10001"):
        bs_client.query_rows(mock_bs, rs)


def test_kline_success(mock_bs):
    mock_bs.query_history_k_data_plus.return_value = _FakeRS(
        ["date", "close"], [["2026-08-31", "10.50"], ["2026-09-01", "10.60"]]
    )
    out = bs_service.get_kline("600000", start_date="2026-08-31", end_date="2026-09-01")
    assert out["status"] == "success" and out["source"] == "baostock"
    assert len(out["data"]) == 2 and out["data"][0]["close"] == "10.50"
    # 协议参数：前复权 flag=2，代码归一化带前缀
    args, kwargs = mock_bs.query_history_k_data_plus.call_args
    assert args[0] == "sh.600000" and kwargs["adjustflag"] == "2"


def test_kline_invalid_frequency_is_value_error(mock_bs):
    with pytest.raises(ValueError, match="不支持的 K 线周期"):
        bs_service.get_kline("600000", frequency="3s")


def test_quarter_fundamental_merges_four_tables(mock_bs):
    mock_bs.query_profit_data.return_value = _FakeRS(
        ["code", "pubDate", "statDate", "roeAvg"], [["sz.000001", "2026-04-20", "2026-03-31", "0.11"]]
    )
    out = bs_service.get_quarter_fundamental("000001", 2026, 1)
    assert out["status"] == "success" and out["quarter"] == 1
    assert out["data"]["profit"]["roeAvg"] == "0.11"
    assert out["data"]["pub_date"] == "2026-04-20"  # 日期外提，不进指标 dict
    assert "code" not in out["data"]["profit"]
    # 四表都查过
    mock_bs.query_growth_data.assert_called_once()
    mock_bs.query_cashflow_data.assert_called_once()


def test_quarter_fundamental_missing_quarter_stays_empty(mock_bs):
    """该季未披露 → 如实留空 dict，不补零不报错。"""
    out = bs_service.get_quarter_fundamental("600000", 2026, 4)
    assert out["data"]["profit"] == {} and out["data"]["growth"] == {}


def test_quarter_fundamental_bad_quarter(mock_bs):
    with pytest.raises(ValueError, match="1~4"):
        bs_service.get_quarter_fundamental("600000", 2026, 5)


# ── worker 分发 ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_worker_kline_forwards_params(mock_bs):
    mock_bs.query_history_k_data_plus.return_value = _FakeRS(["date", "close"], [["2026-08-31", "10.5"]])
    out = await handle_baostock(
        "KLINE_CN", {"symbol": "600000", "start_date": "2026-08-01", "frequency": "w", "adjust": "back"}
    )
    assert out["status"] == "success"
    kwargs = mock_bs.query_history_k_data_plus.call_args.kwargs
    assert kwargs["frequency"] == "w" and kwargs["adjustflag"] == "1"  # back → 1


@pytest.mark.asyncio
async def test_worker_fundamentals_requires_year_quarter():
    out = await handle_baostock("FUNDAMENTALS_CN", {"symbol": "600000"})
    assert out["error_category"] == "bad_request"


@pytest.mark.asyncio
async def test_worker_semantizes_value_error():
    out = await handle_baostock("KLINE_CN", {"symbol": "830001"})  # 北交所不覆盖
    assert out["status"] == "error" and out["error_category"] == "bad_request"
    assert "不覆盖" in out["message"]


@pytest.mark.asyncio
async def test_worker_unknown_action():
    out = await handle_baostock("NOPE", {})
    assert out["status"] == "error" and "未知" in out["message"]


@pytest.mark.asyncio
async def test_worker_network_error_is_error_not_raise(mock_bs, monkeypatch):
    def boom(*a, **k):
        raise OSError("connection reset")

    monkeypatch.setattr(bs_service, "safe_query", boom)
    out = await handle_baostock("STOCK_BASIC_CN", {"symbol": "600000"})
    assert out["status"] == "error" and "connection reset" in out["message"]
