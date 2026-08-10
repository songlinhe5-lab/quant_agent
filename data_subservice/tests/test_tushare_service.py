"""子服务 tushare 数据服务单元测试。

数据服务能力 (stock_history / stock_quote / fundamental / stock_list /
lowfreq_history / macro) 现已迁移到数据子服务
(data_subservice/_internal/tushare/service.py)，本文件对齐该实现，
验证 6 个新增能力方法调用正确的 tushare 接口并规整返回结构。
即从原主服务本地 tushare 适配逻辑迁移到子服务后的单测归属。

sys.path 注入由 tests/conftest.py 统一处理, 本文件无需再 hack。
"""

import pytest

# tushare 为重型 SDK，按架构禁止装在 backend 环境；缺依赖时优雅跳过而非 collection error。
pytest.importorskip("tushare")

from _internal.tushare import service as tushare_service


class _FakeDF:
    """极简 DataFrame 替身，仅实现 to_dict(orient='records')。"""

    def __init__(self, rows):
        self._rows = rows

    def to_dict(self, orient="records"):
        assert orient == "records"
        return list(self._rows)

    @property
    def empty(self):
        return not self._rows

    def head(self, n=1):
        return _FakeDF(self._rows[:n])


class _ProStub:
    """tushare pro 接口桩，记录调用并返回可控 DataFrame。"""

    def __init__(self, returns):
        self._returns = returns
        self.calls = {}

    def _record(self, name, **kwargs):
        self.calls[name] = kwargs

    def daily(self, **kw):
        self._record("daily", **kw)
        return self._returns.get("daily", _FakeDF([]))

    def index_daily(self, **kw):
        self._record("index_daily", **kw)
        return self._returns.get("index_daily", _FakeDF([]))

    def rt(self, **kw):
        self._record("rt", **kw)
        return self._returns.get("rt", _FakeDF([]))

    def daily_basic(self, **kw):
        self._record("daily_basic", **kw)
        return self._returns.get("daily_basic", _FakeDF([]))

    def stock_basic(self, **kw):
        self._record("stock_basic", **kw)
        return self._returns.get("stock_basic", _FakeDF([]))

    def wk_mn(self, **kw):
        self._record("wk_mn", **kw)
        return self._returns.get("wk_mn", _FakeDF([]))

    def macro(self, **kw):
        self._record("macro", **kw)
        return self._returns.get("macro", _FakeDF([]))


@pytest.fixture
def patch_cb():
    """circuit_breaker.call 直接执行函数体，便于断言底层 tushare 调用。"""

    async def _call(_key, fn, *a, **k):
        return fn(*a, **k)

    orig = tushare_service.circuit_breaker.call
    tushare_service.circuit_breaker.call = _call
    yield
    tushare_service.circuit_breaker.call = orig


@pytest.fixture
def svc(patch_cb):
    s = tushare_service.TushareService()
    s.pro = _ProStub({})
    return s


@pytest.mark.asyncio
async def test_daily_history_equity_calls_daily(svc):
    svc.pro._returns = {"daily": _FakeDF([{"ts_code": "000001.SZ", "close": 10.0}])}
    out = await svc.get_daily_history("000001.SZ", "20240101", "20240131", asset="E")
    assert out["source"] == "tushare"
    assert out["data"][0]["close"] == 10.0
    assert svc.pro.calls["daily"]["ts_code"] == "000001.SZ"
    assert "index_daily" not in svc.pro.calls


@pytest.mark.asyncio
async def test_daily_history_index_calls_index_daily(svc):
    svc.pro._returns = {"index_daily": _FakeDF([{"ts_code": "000001.SH"}])}
    out = await svc.get_daily_history("000001.SH", "20240101", "20240131", asset="I")
    assert out["data"][0]["ts_code"] == "000001.SH"
    assert "daily" not in svc.pro.calls
    assert svc.pro.calls["index_daily"]["ts_code"] == "000001.SH"


@pytest.mark.asyncio
async def test_realtime_quote_uses_rt(svc):
    svc.pro._returns = {"rt": _FakeDF([{"ts_code": "000001.SZ", "price": 12.3}])}
    out = await svc.get_realtime_quote("000001.SZ")
    assert out["data"][0]["price"] == 12.3
    assert "rt" in svc.pro.calls


@pytest.mark.asyncio
async def test_realtime_quote_fallback_to_daily(svc):
    # rt 返回空 -> 降级 daily 取最新一行
    svc.pro._returns = {
        "rt": _FakeDF([]),
        "daily": _FakeDF(
            [
                {"trade_date": "20240130", "close": 9.0},
                {"trade_date": "20240131", "close": 9.5},
            ]
        ),
    }
    out = await svc.get_realtime_quote("000001.SZ")
    # rt 为空降级 daily：tushare daily 默认按日期升序，head(1) 取最早一行
    assert out["data"][0]["trade_date"] == "20240130"
    assert "rt" in svc.pro.calls and "daily" in svc.pro.calls


@pytest.mark.asyncio
async def test_daily_basic_by_trade_date(svc):
    svc.pro._returns = {"daily_basic": _FakeDF([{"pe": 8.1, "pb": 1.2}])}
    out = await svc.get_daily_basic("000001.SZ", trade_date="20240131")
    assert out["data"][0]["pe"] == 8.1
    assert svc.pro.calls["daily_basic"]["trade_date"] == "20240131"
    assert "start_date" not in svc.pro.calls["daily_basic"]


@pytest.mark.asyncio
async def test_daily_basic_by_range(svc):
    svc.pro._returns = {"daily_basic": _FakeDF([{"pe": 8.1}])}
    await svc.get_daily_basic("000001.SZ", start_date="20240101", end_date="20240131")
    assert svc.pro.calls["daily_basic"]["start_date"] == "20240101"
    assert "trade_date" not in svc.pro.calls["daily_basic"]


@pytest.mark.asyncio
async def test_stock_basic_calls_stock_basic(svc):
    svc.pro._returns = {"stock_basic": _FakeDF([{"ts_code": "000001.SZ", "name": "平安银行"}])}
    out = await svc.get_stock_basic(list_status="L", exchange="", fields="ts_code,symbol,name")
    assert out["data"][0]["name"] == "平安银行"
    assert svc.pro.calls["stock_basic"]["list_status"] == "L"


@pytest.mark.asyncio
async def test_lowfreq_history_calls_wk_mn(svc):
    svc.pro._returns = {"wk_mn": _FakeDF([{"ts_code": "000001.SZ", "freq": "W"}])}
    out = await svc.get_lowfreq_history("000001.SZ", "W", "20240101", "20240131")
    assert out["data"][0]["freq"] == "W"
    assert svc.pro.calls["wk_mn"]["freq"] == "W"
    assert svc.pro.calls["wk_mn"]["ts_code"] == "000001.SZ"


@pytest.mark.asyncio
async def test_macro_calls_macro(svc):
    svc.pro._returns = {"macro": _FakeDF([{"ts_code": "M0000001", "value": 3.2}])}
    out = await svc.get_macro("M0000001", "20240101", "20240131")
    assert out["data"][0]["value"] == 3.2
    assert svc.pro.calls["macro"]["ts_code"] == "M0000001"


@pytest.mark.asyncio
async def test_empty_result_shapes_data_list(svc):
    svc.pro._returns = {"daily": _FakeDF([])}
    out = await svc.get_daily_history("000001.SZ", "20240101", "20240131")
    assert out["data"] == []


@pytest.mark.asyncio
async def test_not_configured_returns_error(svc):
    svc.pro = None
    out = await svc.get_daily_history("000001.SZ", "20240101", "20240131")
    assert "error" in out
    assert out["source"] == "tushare"
