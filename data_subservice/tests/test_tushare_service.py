"""TushareService 单元测试 (纯函数 + 未配置 token 前置分支)。

默认 TUSHARE_TOKEN 为空 → pro=None, 所有需网络方法直接返回
"tushare not configured", 无网络即可覆盖前置校验分支。
"""

import pytest

from data_subservice._internal.tushare import service as ts_svc


@pytest.fixture
def svc():
    # 无 token 时 pro=None, 前置校验分支直接返回
    return ts_svc.TushareService()


class TestPureHelpers:
    @pytest.mark.parametrize("sym,expected", [
        ("HK.00700", True),
        ("00700.HK", True),
        ("000001.SZ", False),
        ("600519", False),
        ("", False),
        ("  ", False),
    ])
    def test_is_hk_symbol(self, sym, expected):
        assert ts_svc._is_hk_symbol(sym) is expected

    def test_today_format(self):
        assert len(ts_svc._today()) == 8
        assert ts_svc._today().isdigit()

    def test_today_minus(self):
        assert len(ts_svc._today_minus(5)) == 8

    def test_empty(self):
        assert ts_svc.TushareService._empty("foo")["action"] == "foo"

    def test_frame_to_records(self):
        import pandas as pd
        df = pd.DataFrame([{"a": 1}])
        out = ts_svc.TushareService._frame_to_records(df)
        assert out["data"] == [{"a": 1}]


class TestNotConfiguredBranches:
    @pytest.mark.asyncio
    async def test_fetch_ts_data_routes(self, svc):
        # not pro 时各路由方法均返回 not configured
        assert "not configured" in (await svc.get_financials("000001.SZ"))["error"]
        assert "not configured" in (await svc.get_holder_number("000001.SZ"))["error"]
        assert "not configured" in (await svc.get_moneyflow("000001.SZ"))["error"]
        assert "not configured" in (await svc.get_daily_history("000001.SZ", "20240101", "20240131"))["error"]
        assert "not configured" in (await svc.get_realtime_quote("000001.SZ"))["error"]

    @pytest.mark.asyncio
    async def test_fetch_ts_data_unknown_endpoint(self, svc):
        res = await svc.fetch_ts_data("bogus", "000001.SZ")
        assert res["error"] == "unknown endpoint: bogus"
