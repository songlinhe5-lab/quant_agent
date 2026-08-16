"""_compat 纯函数单测 (safe_float / safe_divide / no-op 指标桩)。"""

import pytest

from data_subservice.futu_src import _compat


class TestSafeFloat:
    @pytest.mark.parametrize(
        "val,default,expected",
        [
            (None, 0.0, 0.0),
            ("3.5", 0.0, 3.5),
            (10, 0.0, 10.0),
            ("abc", 0.0, 0.0),
            (None, -1.0, -1.0),
            ([], 0.0, 0.0),
        ],
    )
    def test_cases(self, val, default, expected):
        assert _compat.safe_float(val, default) == expected


class TestSafeDivide:
    @pytest.mark.parametrize(
        "num,den,default,expected",
        [
            (10, 2, 0.0, 5.0),
            (10, 0, 0.0, 0.0),
            (10, "x", 0.0, 0.0),
            (10, None, 0.0, 0.0),
            ("notnum", 2, 0.0, 0.0),
            (1, 4, -1.0, 0.25),
        ],
    )
    def test_cases(self, num, den, default, expected):
        assert _compat.safe_divide(num, den, default) == expected


class TestNoopMetrics:
    def test_gauge_set(self):
        _compat.FUTU_CONNECTION_STATUS.set(1)  # 不应抛

    def test_counter_inc(self):
        _compat.FUTU_RECONNECT_FAILURES.inc()
        _compat.FUTU_RECONNECT_TOTAL.inc()
