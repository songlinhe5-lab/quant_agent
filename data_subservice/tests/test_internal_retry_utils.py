"""retry_utils 单元测试 (tenacity 重试装饰器)"""

import pytest

from data_subservice._internal.retry_utils import WithGlobalRetry, with_global_retry


class TestWithGlobalRetry:
    def test_sync_retry_eventually_succeeds(self):
        calls = {"n": 0}

        @WithGlobalRetry(max_attempts=3, initial_wait=0.01, max_wait=0.05)
        def flaky():
            calls["n"] += 1
            if calls["n"] < 3:
                raise ValueError("fail")
            return "ok"

        assert flaky() == "ok"
        assert calls["n"] == 3

    def test_sync_retry_exhausted_raises(self):
        calls = {"n": 0}

        @WithGlobalRetry(max_attempts=2, initial_wait=0.01, max_wait=0.05)
        def always_fail():
            calls["n"] += 1
            raise RuntimeError("nope")

        with pytest.raises(RuntimeError):
            always_fail()
        assert calls["n"] == 2

    @pytest.mark.asyncio
    async def test_async_retry_eventually_succeeds(self):
        calls = {"n": 0}

        @with_global_retry
        async def flaky():
            calls["n"] += 1
            if calls["n"] < 2:
                raise KeyError("x")
            return "done"

        assert await flaky() == "done"
        assert calls["n"] == 2

    @pytest.mark.asyncio
    async def test_async_retry_exhausted_raises(self):
        calls = {"n": 0}

        @WithGlobalRetry(max_attempts=3, initial_wait=0.01, max_wait=0.05)
        async def boom():
            calls["n"] += 1
            raise IOError("io")

        with pytest.raises(IOError):
            await boom()
        assert calls["n"] == 3

    def test_factory_returns_sync_wrapper_for_sync_func(self):
        @WithGlobalRetry(max_attempts=1)
        def f():
            return 42

        assert f() == 42

    @pytest.mark.asyncio
    async def test_factory_returns_async_wrapper_for_async_func(self):
        @WithGlobalRetry(max_attempts=1)
        async def f():
            return 43

        assert await f() == 43
