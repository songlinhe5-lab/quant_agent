"""全局重试装饰器（复制自 backend.core.retry_utils，物理解耦，零 backend 依赖）

子服务仅需 tenacity 重试能力，去除 backend 监控/proxy 绑定逻辑。
"""

from functools import wraps

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)


class WithGlobalRetry:
    """
    全局重试装饰器工厂。

    用法:
        @with_global_retry
        async def my_fetch(): ...
    """

    def __init__(
        self,
        max_attempts: int = 3,
        initial_wait: float = 1.0,
        max_wait: float = 10.0,
        retry_on: tuple = (Exception,),
    ):
        self.max_attempts = max_attempts
        self.initial_wait = initial_wait
        self.max_wait = max_wait
        self.retry_on = retry_on

    def __call__(self, func):
        @wraps(func)
        @retry(
            stop=stop_after_attempt(self.max_attempts),
            wait=wait_exponential(multiplier=self.initial_wait, max=self.max_wait),
            retry=retry_if_exception_type(self.retry_on),
            reraise=True,
        )
        async def async_wrapper(*args, **kwargs):
            return await func(*args, **kwargs)

        @wraps(func)
        @retry(
            stop=stop_after_attempt(self.max_attempts),
            wait=wait_exponential(multiplier=self.initial_wait, max=self.max_wait),
            retry=retry_if_exception_type(self.retry_on),
            reraise=True,
        )
        def sync_wrapper(*args, **kwargs):
            return func(*args, **kwargs)

        import asyncio

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper


with_global_retry = WithGlobalRetry()
