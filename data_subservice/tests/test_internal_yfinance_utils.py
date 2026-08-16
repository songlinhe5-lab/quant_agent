"""yfinance utils 单元测试 — 纯函数, 无外部依赖。"""

from data_subservice._internal.yfinance import utils


class TestFormatYfTicker:
    def test_empty(self):
        assert utils.format_yf_ticker("") == ""

    def test_none_like(self):
        # strip 后为空字符串
        assert utils.format_yf_ticker("   ") == ""

    def test_us_prefix(self):
        assert utils.format_yf_ticker("US.AAPL") == "AAPL"

    def test_hk_prefix(self):
        assert utils.format_yf_ticker("HK.00700") == "00700.HK"

    def test_sh_prefix(self):
        assert utils.format_yf_ticker("SH.600519") == "600519.SS"

    def test_sz_prefix(self):
        assert utils.format_yf_ticker("SZ.000001") == "000001.SZ"

    def test_already_suffix_hk(self):
        assert utils.format_yf_ticker("0700.HK") == "0700.HK"

    def test_already_suffix_ss(self):
        assert utils.format_yf_ticker("600519.SS") == "600519.SS"

    def test_already_suffix_t(self):
        assert utils.format_yf_ticker("7203.T") == "7203.T"

    def test_plain_us_adr(self):
        assert utils.format_yf_ticker("aapl") == "AAPL"


class TestResolveDateRange:
    def test_start_end_takes_priority(self):
        assert utils.resolve_date_range(start="2024-01-01", end="2024-02-01") == (None, "2024-01-01", "2024-02-01")

    def test_period_branch(self):
        assert utils.resolve_date_range(period="6mo") == ("6mo", None, None)

    def test_default_fallback(self):
        period, start, end = utils.resolve_date_range()
        assert period is None
        assert start is not None and end is not None
        assert start < end

    def test_custom_range_days(self):
        _, start, end = utils.resolve_date_range(range_days=10)
        assert start is not None and end is not None


class TestGetValidEarningsDates:
    def test_none_input(self):
        assert utils.get_valid_earnings_dates("AAPL", None) == []

    def test_empty_list(self):
        assert utils.get_valid_earnings_dates("AAPL", []) == []

    def test_keeps_past_earnings(self):
        out = utils.get_valid_earnings_dates("AAPL", [{"period": "2020-01-01"}])
        assert out == [{"period": "2020-01-01"}]

    def test_drops_future_earnings(self):
        out = utils.get_valid_earnings_dates("AAPL", [{"period": "2999-01-01"}])
        assert out == []

    def test_skips_malformed(self):
        # 错误日期格式被 except 分支吞掉, 返回空
        out = utils.get_valid_earnings_dates("AAPL", [{"period": "not-a-date"}])
        assert out == []

    def test_mixed(self):
        dates = [
            {"period": "2020-01-01"},
            {"period": "2999-01-01"},
            {"period": "bad"},
        ]
        out = utils.get_valid_earnings_dates("AAPL", dates)
        assert out == [{"period": "2020-01-01"}]
