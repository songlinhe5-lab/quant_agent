"""
沙箱基础设施测试：SandboxTimeoutTracer, BaseStrategySandbox
"""

import time

import pytest

from backend.core.backtest import (
    BaseStrategySandbox,
    SandboxTimeoutException,
    SandboxTimeoutTracer,
)


# ─── SandboxTimeoutTracer ───────────────────────────────────────────
class TestSandboxTimeoutTracer:
    def test_timeout_triggered(self):
        # 💡 直接测试 _trace_calls 的超时逻辑，不依赖 sys.settrace，
        # 避免 coverage.py 运行时被沙箱 trace 覆盖导致覆盖率统计异常。
        tracer = SandboxTimeoutTracer(timeout_seconds=0.1)
        tracer.start_time = time.perf_counter()
        time.sleep(0.2)
        with pytest.raises(SandboxTimeoutException, match="超时"):
            tracer._trace_calls(None, "call", None)

    def test_context_manager_enter_exit(self):
        tracer = SandboxTimeoutTracer(timeout_seconds=5.0)
        with tracer:
            assert tracer.start_time > 0
            time.sleep(0.05)

    def test_memory_check(self):
        tracer = SandboxTimeoutTracer(timeout_seconds=5.0, max_memory_mb=500.0)
        with tracer:
            for _ in range(10000):
                pass


# ─── BaseStrategySandbox ────────────────────────────────────────────
class TestBaseStrategySandbox:
    def test_init(self):
        strategy = BaseStrategySandbox()
        assert strategy._position_size == 0
        assert strategy._position_data == {}

    def test_has_position_false(self):
        strategy = BaseStrategySandbox()
        assert strategy.has_position() is False

    def test_has_position_true(self):
        strategy = BaseStrategySandbox()
        strategy._position_size = 100
        assert strategy.has_position() is True

    def test_get_position(self):
        strategy = BaseStrategySandbox()
        strategy._position_size = 100
        strategy._position_data = {"size": 100, "entry_price": 100.0}
        position = strategy.get_position()
        assert position["size"] == 100
        assert position["entry_price"] == 100.0
