"""AKShare 宏观日历单元测试 — mock 网络与 akshare, 覆盖三级容灾与解析逻辑。"""

import pandas as pd
import pytest

import data_subservice._internal.akshare.calendar as cal_mod


class TestFetchDateThreeTier:
    """_fetch_date 三级容灾（百度/新浪/金十）分支。"""

    def test_tier1_akshare_returns_records(self, monkeypatch):
        """第一级 akshare 命中即返回。"""
        fake_df = pd.DataFrame([{"地区": "美国", "事件": "FOMC", "公布时间": "02:00", "重要性": "高"}])
        monkeypatch.setattr(cal_mod.ak, "news_economic_baidu", lambda **k: fake_df)
        out = cal_mod._fetch_date("2024-01-01", "20240101")
        assert isinstance(out, list) and len(out) == 1

    def test_tier1_missing_attr_falls_through(self, monkeypatch):
        """ak 无该属性时跳过第一级。"""
        monkeypatch.delattr(cal_mod.ak, "news_economic_baidu", raising=False)
        monkeypatch.setattr(cal_mod.httpx, "Client", lambda **k: _FakeSinaClient([]))
        out = cal_mod._fetch_date("2024-01-01", "20240101")
        assert out == []

    def test_tier2_sina_returns_list(self, monkeypatch):
        monkeypatch.delattr(cal_mod.ak, "news_economic_baidu", raising=False)
        monkeypatch.setattr(cal_mod.httpx, "Client", lambda **k: _FakeSinaClient([{"country": "US", "event": "X"}]))
        out = cal_mod._fetch_date("2024-01-01", "20240101")
        assert out == [{"country": "US", "event": "X"}]

    def test_tier3_jin10_returns_list(self, monkeypatch):
        monkeypatch.delattr(cal_mod.ak, "news_economic_baidu", raising=False)
        # 新浪返回非 200, 金十返回数据
        monkeypatch.setattr(
            cal_mod.httpx, "Client", lambda **k: _FakeSinaClient(None, jin10=[{"country": "CN", "event": "Y"}])
        )
        out = cal_mod._fetch_date("2024-01-01", "20240101")
        assert out == [{"country": "CN", "event": "Y"}]

    def test_all_tiers_fail_returns_empty(self, monkeypatch):
        monkeypatch.delattr(cal_mod.ak, "news_economic_baidu", raising=False)
        monkeypatch.setattr(cal_mod.httpx, "Client", lambda **k: _FakeSinaClient(None, jin10_fail=True))
        assert cal_mod._fetch_date("2024-01-01", "20240101") == []


class _FakeResp:
    def __init__(self, status_code=200, payload=None, jin10=False, fail=False):
        self.status_code = status_code
        self._payload = payload
        self._jin10 = jin10
        self._fail = fail

    def json(self):
        if self._fail:
            raise ValueError("bad json")
        if self._jin10:
            return {"data": self._payload}
        return self._payload


class _FakeSinaClient:
    """模拟 httpx.Client，第一次 get 为新浪(返回空/非200)，第二次为金十。"""

    def __init__(self, sina_payload, jin10=None, jin10_fail=False):
        self._sina = sina_payload
        self._jin10 = jin10
        self._jin10_fail = jin10_fail
        self._call = 0

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, url, headers=None):
        self._call += 1
        if "jin10" in url:
            if self._jin10_fail:
                return _FakeResp(200, fail=True)
            return _FakeResp(200, self._jin10, jin10=True)
        # 新浪分支: 返回空/非 200 以触发容灾
        return _FakeResp(503 if self._sina is None else 200, self._sina)


class TestGetEconomicCalendar:
    def test_builds_events_and_sorts(self, monkeypatch):
        """mock _fetch_date 返回多条, 验证解析 + 排序 + impact 映射。"""
        recs = [
            {"地区": "美国", "事件": "FOMC", "公布时间": "02:00", "重要性": "高", "前值": "5.0", "预测值": "5.1", "公布值": "5.2"},
            {"country": "CN", "event": "PM I", "time": "09:30", "importance": "2", "previous": "50", "consensus": "51", "actual": "52"},
        ]
        monkeypatch.setattr(cal_mod, "_fetch_date", lambda *a: recs)
        out = cal_mod.get_economic_calendar(days_ahead=0, days_back=0)
        assert out["status"] == "success"
        assert out["source"] == "akshare_universal"
        assert len(out["data"]) == 2
        # impact 映射
        assert out["data"][0]["impact"] == "high"
        assert out["data"][1]["impact"] == "medium"
        # 时间补齐
        assert out["data"][0]["time"].endswith("02:00")
        assert out["data"][0]["previous"] == "5.0"

    def test_empty_event_name_skipped(self, monkeypatch):
        monkeypatch.setattr(cal_mod, "_fetch_date", lambda *a: [{"地区": "US", "事件": "", "重要性": "1"}])
        out = cal_mod.get_economic_calendar(days_ahead=0, days_back=0)
        assert out["data"] == []

    def test_missing_pub_time_defaults(self, monkeypatch):
        monkeypatch.setattr(cal_mod, "_fetch_date", lambda *a: [{"地区": "US", "event": "X"}])
        out = cal_mod.get_economic_calendar(days_ahead=0, days_back=0)
        assert out["data"][0]["time"].endswith("08:30:00")

    def test_exception_returns_error(self, monkeypatch):
        def boom(*a):
            raise RuntimeError("boom")
        monkeypatch.setattr(cal_mod, "_fetch_date", boom)
        out = cal_mod.get_economic_calendar(days_ahead=0, days_back=0)
        assert out["status"] == "error"


class TestGetFutureCalendar:
    def test_returns_head_30(self, monkeypatch):
        df = pd.DataFrame([{"a": 1}] * 50)
        monkeypatch.setattr(cal_mod.ak, "futures_rule", lambda: df)
        out = cal_mod.get_future_calendar()
        assert len(out) == 30

    def test_empty_df_returns_empty(self, monkeypatch):
        monkeypatch.setattr(cal_mod.ak, "futures_rule", lambda: pd.DataFrame())
        assert cal_mod.get_future_calendar() == []

    def test_exception_returns_empty(self, monkeypatch):
        monkeypatch.setattr(cal_mod.ak, "futures_rule", lambda: (_ for _ in ()).throw(RuntimeError("x")))
        assert cal_mod.get_future_calendar() == []
