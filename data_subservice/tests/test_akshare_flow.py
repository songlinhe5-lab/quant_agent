"""AKShare 资金流向单元测试 — 覆盖纯函数与各 get_* 成功/异常分支 (mock akshare)。"""

import pandas as pd
import pytest

import data_subservice._internal.akshare.flow as flow_mod


# ─── 纯函数 ──────────────────────────────────────────────────────────
class TestPureHelpers:
    def test_to_float(self):
        assert flow_mod._to_float(None) == 0.0
        assert flow_mod._to_float("") == 0.0
        assert flow_mod._to_float("None") == 0.0
        assert flow_mod._to_float("1,234.5") == 1234.5
        assert flow_mod._to_float("bad") == 0.0

    def test_to_int(self):
        assert flow_mod._to_int(None) == 0
        assert flow_mod._to_int("1,234") == 1234
        assert flow_mod._to_int("x") == 0

    @pytest.mark.parametrize("sym,exp", [
        ("HK.00700", True), ("00700.HK", True), ("00700", False), ("US.AAPL", False),
    ])
    def test_is_hk_symbol(self, sym, exp):
        assert flow_mod._is_hk_symbol(sym) is exp

    @pytest.mark.parametrize("code,exp", [("600000", "sh"), ("688001", "sh"), ("000001", "sz"), ("300750", "sz")])
    def test_a_share_market(self, code, exp):
        assert flow_mod._a_share_market(code) == exp


# ─── get_northbound_flow (无 retry) ──────────────────────────────────
class TestNorthboundFlow:
    def _fake_summary(self):
        # 源码取 df.iloc[-1]（最后一行）作为 latest
        return pd.DataFrame([
            {"日期": "2024-01-01", "资金方向": "南向", "北向资金": 200.0},
            {"日期": "2024-01-01", "资金方向": "北向", "北向资金": 100.0},
        ])

    def test_success(self, monkeypatch):
        monkeypatch.setattr(flow_mod.ak, "stock_hsgt_fund_flow_summary_em", self._fake_summary)
        out = flow_mod.get_northbound_flow()
        assert out is not None
        assert out["northbound_net_inflow"] == 100.0
        assert out["source"] == "akshare"

    def test_empty_df(self, monkeypatch):
        monkeypatch.setattr(flow_mod.ak, "stock_hsgt_fund_flow_summary_em", lambda: pd.DataFrame())
        assert flow_mod.get_northbound_flow() is None

    def test_exception(self, monkeypatch):
        monkeypatch.setattr(flow_mod.ak, "stock_hsgt_fund_flow_summary_em",
                            lambda: (_ for _ in ()).throw(RuntimeError("x")))
        assert flow_mod.get_northbound_flow() is None


# ─── get_southbound_flow (retry) ─────────────────────────────────────
class TestSouthboundFlow:
    def _summary(self):
        return pd.DataFrame([
            {"交易日": "2024-01-01", "资金方向": "南向", "资金净流入": 50.0, "交易状态": 1},
        ])

    def test_success(self, monkeypatch):
        monkeypatch.setattr(flow_mod.ak, "stock_hsgt_fund_flow_summary_em", self._summary)
        monkeypatch.setattr(flow_mod.ak, "stock_hsgt_hist_em", lambda **k: pd.DataFrame())
        out = flow_mod.get_southbound_flow()
        assert out["status"] == "success"
        assert out["data"]["net_inflow"] == 50.0
        assert out["is_closed"] is False

    def test_empty_summary_warning(self, monkeypatch):
        monkeypatch.setattr(flow_mod.ak, "stock_hsgt_fund_flow_summary_em", lambda: pd.DataFrame())
        out = flow_mod.get_southbound_flow()
        assert out["status"] == "warning"
        assert out["data"] is None

    def test_net_inflow_above_threshold_raises(self, monkeypatch):
        def big():
            return pd.DataFrame([
                {"交易日": "2024-01-01", "资金方向": "南向", "资金净流入": 999.0, "交易状态": 1},
            ])
        monkeypatch.setattr(flow_mod.ak, "stock_hsgt_fund_flow_summary_em", big)
        monkeypatch.setattr(flow_mod.ak, "stock_hsgt_hist_em", lambda **k: pd.DataFrame())
        out = flow_mod.get_southbound_flow()
        assert out["status"] == "warning"


# ─── get_northbound_flow_full (retry) ───────────────────────────────
class TestNorthboundFlowFull:
    def test_success(self, monkeypatch):
        def summary():
            return pd.DataFrame([
                {"交易日": "2024-01-01", "资金方向": "北向", "资金净流入": 80.0, "交易状态": 1},
            ])
        monkeypatch.setattr(flow_mod.ak, "stock_hsgt_fund_flow_summary_em", summary)
        monkeypatch.setattr(flow_mod.ak, "stock_hsgt_hist_em", lambda **k: pd.DataFrame())
        out = flow_mod.get_northbound_flow_full()
        assert out["status"] == "success"
        assert out["data"]["net_inflow"] == 80.0

    def test_empty_north_warning(self, monkeypatch):
        def summary():
            return pd.DataFrame([
                {"交易日": "2024-01-01", "资金方向": "南向", "资金净流入": 80.0},
            ])
        monkeypatch.setattr(flow_mod.ak, "stock_hsgt_fund_flow_summary_em", summary)
        out = flow_mod.get_northbound_flow_full()
        assert out["status"] == "warning"


# ─── get_hk_connect_flow (retry) ────────────────────────────────────
class TestHkConnectFlow:
    def test_success(self, monkeypatch):
        def summary():
            return pd.DataFrame([
                {"交易日": "2024-01-01", "资金方向": "南向", "板块": "沪股通", "成交净买额": "10.5",
                 "资金净流入": "20.0", "上涨数": "100", "下跌数": "50", "持平数": "10",
                 "相关指数": "HSI", "指数涨跌幅": "1.2"},
            ])
        monkeypatch.setattr(flow_mod.ak, "stock_hsgt_fund_flow_summary_em", summary)
        out = flow_mod.get_hk_connect_flow()
        assert out["status"] == "success"
        ch = out["data"]["channels"][0]
        assert ch["board"] == "沪股通"
        assert ch["net_buy"] == 10.5
        assert ch["net_inflow"] == 20.0
        assert ch["up"] == 100

    def test_empty_warning(self, monkeypatch):
        monkeypatch.setattr(flow_mod.ak, "stock_hsgt_fund_flow_summary_em", lambda: pd.DataFrame())
        out = flow_mod.get_hk_connect_flow()
        assert out["status"] == "warning"


# ─── get_hsgt_top_holders (retry) ───────────────────────────────────
class TestHsgtTopHolders:
    def _df(self, **kwargs):
        return pd.DataFrame([
            {"持股日期": "2024-01-02", "机构名称": "A", "持股数量": 100.0, "持股数量占A股百分比": 5.0},
            {"持股日期": "2024-01-01", "机构名称": "A", "持股数量": 80.0, "持股数量占A股百分比": 4.0},
        ])

    def test_success(self, monkeypatch):
        monkeypatch.setattr(flow_mod.ak, "stock_hsgt_individual_detail_em", self._df)
        out = flow_mod.get_hsgt_top_holders("00700")
        assert out["status"] == "success"
        assert out["data"]["southbound_total_shares"] == 100.0
        assert out["data"]["southbound_net_change"] == 20.0

    def test_empty_raises(self, monkeypatch):
        monkeypatch.setattr(flow_mod.ak, "stock_hsgt_individual_detail_em", lambda **k: pd.DataFrame())
        out = flow_mod.get_hsgt_top_holders("00700")
        assert out["status"] == "warning"

    def test_exception_is_error(self, monkeypatch):
        monkeypatch.setattr(flow_mod.ak, "stock_hsgt_individual_detail_em",
                            lambda **k: (_ for _ in ()).throw(KeyError("x")))
        out = flow_mod.get_hsgt_top_holders("00700")
        assert out["status"] == "error"


# ─── get_individual_flow ────────────────────────────────────────────
class TestIndividualFlow:
    def test_hk_symbol_returns_none(self, monkeypatch):
        out = flow_mod.get_individual_flow("HK.00700")
        assert out is None

    def test_success(self, monkeypatch):
        def fake(stock, market):
            return pd.DataFrame([{"日期": "2024-01-01", "主力净流入-净额": 500.0}])
        monkeypatch.setattr(flow_mod.ak, "stock_individual_fund_flow", fake)
        out = flow_mod.get_individual_flow("600000")
        assert out is not None
        assert out["main_net_inflow"] == 500.0

    def test_empty_returns_none(self, monkeypatch):
        monkeypatch.setattr(flow_mod.ak, "stock_individual_fund_flow", lambda **k: pd.DataFrame())
        assert flow_mod.get_individual_flow("600000") is None

    def test_exception_returns_none(self, monkeypatch):
        monkeypatch.setattr(flow_mod.ak, "stock_individual_fund_flow",
                            lambda **k: (_ for _ in ()).throw(RuntimeError("x")))
        assert flow_mod.get_individual_flow("600000") is None


# ─── get_a_share_margin (retry) ─────────────────────────────────────
class TestAShareMargin:
    def test_success(self, monkeypatch):
        sse = pd.DataFrame([{"融资余额": 1e8, "融券余额": 2e8}])
        szse = pd.DataFrame([{"融资余额": 3e8, "融券余额": 4e8}])
        monkeypatch.setattr(flow_mod.ak, "stock_margin_sse", lambda: sse)
        monkeypatch.setattr(flow_mod.ak, "stock_margin_szse", lambda: szse)
        out = flow_mod.get_a_share_margin()
        assert out["status"] == "success"
        # (1+3)=4 亿元
        assert out["data"]["financing_balance"] == 4.0

    def test_empty_sse_raises(self, monkeypatch):
        monkeypatch.setattr(flow_mod.ak, "stock_margin_sse", lambda: pd.DataFrame())
        monkeypatch.setattr(flow_mod.ak, "stock_margin_szse", lambda: pd.DataFrame())
        out = flow_mod.get_a_share_margin()
        assert out["status"] == "error"


# ─── get_a_share_sector_flow (retry) ────────────────────────────────
class TestAShareSectorFlow:
    def test_success(self, monkeypatch):
        df = pd.DataFrame([
            {"名称": "银行", "今日涨跌幅": 1.0, "今日主力净流入-净额": 100.0, "今日主力净流入-净占比": 5.0},
            {"名称": "半导体", "今日涨跌幅": -2.0, "今日主力净流入-净额": -50.0, "今日主力净流入-净占比": -3.0},
        ])
        monkeypatch.setattr(flow_mod.ak, "stock_sector_fund_flow_rank", lambda **k: df)
        out = flow_mod.get_a_share_sector_flow()
        assert out["status"] == "success"
        assert len(out["data"]["inflow_top"]) == 2

    def test_empty_raises(self, monkeypatch):
        monkeypatch.setattr(flow_mod.ak, "stock_sector_fund_flow_rank", lambda **k: pd.DataFrame())
        out = flow_mod.get_a_share_sector_flow()
        assert out["status"] == "error"


# ─── get_hk_sector_flow (retry) ─────────────────────────────────────
class TestHkSectorFlow:
    def test_success(self, monkeypatch):
        df = pd.DataFrame([
            {"行业": "金融", "净买入": 100.0},
            {"行业": "科技", "净买入": -30.0},
        ])
        monkeypatch.setattr(flow_mod.ak, "stock_hsgt_fund_flow_summary_em", lambda: df)
        out = flow_mod.get_hk_sector_flow()
        assert out["status"] == "success"
        assert out["data"]["sectors"][0]["name"] == "金融"
        assert out["data"]["sectors"][0]["net_inflow"] == 100.0 / 1e4

    def test_unparseable_raises(self, monkeypatch):
        # 单列非数值, 无法解析 flow_col
        df = pd.DataFrame([{"行业": "X"}])
        monkeypatch.setattr(flow_mod.ak, "stock_hsgt_fund_flow_summary_em", lambda: df)
        out = flow_mod.get_hk_sector_flow()
        assert out["status"] == "error"
