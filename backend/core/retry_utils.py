import httpx
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_random_exponential,
)


def is_retryable_http_error(exception: BaseException) -> bool:
    """定义哪些异常情况需要触发自动重试"""
    err_msg = str(exception).lower()

    # 0. 外部接口限流与封禁异常 (429, 403, Rate Limit, Too Many Requests, Forbidden)
    if any(
        kw in err_msg
        for kw in [
            "rate limit",
            "too many requests",
            "429",
            "403",
            "forbidden",
            "finnhub",
        ]
    ):  # noqa: E501
        return True

    # 1. Futu 频率限制与底层连接异常
    if "频繁" in err_msg or "frequency" in err_msg or "10041" in err_msg or "timeout" in err_msg:  # noqa: E501
        return True

    # 2. 网络请求本身的底层异常 (如连接超时、断网等)
    if isinstance(exception, httpx.RequestError):
        return True
    # 3. 服务端返回的异常 HTTP 状态码
    if isinstance(exception, httpx.HTTPStatusError):
        status = exception.response.status_code
        # 仅对封禁/限流(403, 429)和服务端崩溃(500,502,503,504)进行重试
        return status in (403, 429, 500, 502, 503, 504)
    return False


def log_retry_attempt(retry_state):
    """重试钩子：支持同步与异步函数，防止 tenacity 混用报错"""
    exception_name = type(retry_state.outcome.exception()).__name__
    attempt_num = retry_state.attempt_number
    print(f"⏳ [Global Service Retry] 接口请求异常 ({exception_name})，正在进行第 {attempt_num} 次退避重试...")


# 导出的核心装饰器：支持指数退避 + 随机抖动
with_global_retry = retry(
    retry=retry_if_exception(is_retryable_http_error),
    wait=wait_random_exponential(multiplier=1, min=1, max=10),
    stop=stop_after_attempt(3),
    reraise=True,
    before_sleep=log_retry_attempt,
)
