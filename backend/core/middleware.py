import time

import httpx
from fastapi import Request
from prometheus_client import Counter, Histogram
from starlette.middleware.base import BaseHTTPMiddleware

from backend.core.logger import logger

# 📊 1. 定义 Prometheus 计数器：记录总请求数与状态码（判断接口存活和 5xx 错误率）
REQUEST_COUNT = Counter(
    "fastapi_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "http_status"]
)

# 📊 2. 定义 Prometheus 直方图：用于计算 P99/P95 耗时
# buckets(桶)的设计至关重要：针对量化高频场景，我们设计得非常精细，从 5ms 到 1s
REQUEST_LATENCY = Histogram(
    "fastapi_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "endpoint"],
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, float("inf")]
)

# 📊 3. 外部 API 监控 (Egress Monitoring)
EXTERNAL_API_COUNT = Counter(
    "external_api_requests_total",
    "Total outgoing HTTP requests to third-party APIs",
    ["service_name", "method", "http_status"]
)

EXTERNAL_API_LATENCY = Histogram(
    "external_api_request_duration_seconds",
    "Outgoing HTTP request latency",
    ["service_name", "method"],
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, float("inf")]
)

# 用于在请求和响应之间传递时间的字典 (协程/线程安全，以请求对象 id 为键)
_request_timers = {}

async def httpx_log_request(request: httpx.Request):
    """记录请求发出的时间 (TTFB 起点)"""
    _request_timers[id(request)] = time.perf_counter()

async def httpx_log_response(response: httpx.Response):
    """统一拦截并收集 httpx 发出的所有外部第三方 API 请求耗时与状态码"""
    request = response.request
    start_time = _request_timers.pop(id(request), None)
    process_time = (time.perf_counter() - start_time) if start_time else 0.0

    host = request.url.host

    service_name = "unknown"
    if "finnhub" in host: service_name = "finnhub"  # noqa: E701
    elif "stlouisfed" in host: service_name = "fred"  # noqa: E701
    elif "tavily" in host: service_name = "tavily"  # noqa: E701
    elif "bochaai" in host: service_name = "bocha"  # noqa: E701
    elif "jina" in host: service_name = "jina_reader"  # noqa: E701
    elif "dingtalk" in host: service_name = "dingtalk"  # noqa: E701
    elif "feishu" in host: service_name = "feishu"  # noqa: E701
    elif "telegram" in host: service_name = "telegram"  # noqa: E701
    elif "openai" in host or "deepseek" in host: service_name = "llm_api"  # noqa: E701
    elif "yahoo" in host: service_name = "yahoo"  # noqa: E701

    EXTERNAL_API_COUNT.labels(service_name=service_name, method=request.method, http_status=response.status_code).inc()  # noqa: E501
    EXTERNAL_API_LATENCY.labels(service_name=service_name, method=request.method).observe(process_time)  # noqa: E501

    if process_time > 3.0:
        logger.warning(f"🐢 [Slow Egress API] {service_name} ({request.method} {host}) 耗时: {process_time:.2f}s")  # noqa: E501

class AccessLogMiddleware(BaseHTTPMiddleware):
    """
    全局请求访问与性能监控中间件 (结合 Prometheus)
    """
    async def dispatch(self, request: Request, call_next):
        start_time = time.perf_counter()
        method = request.method

        try:
            response = await call_next(request)
            process_time = time.perf_counter() - start_time
            status_code = response.status_code

            # 💡 必须在 call_next 之后提取 route！因为 FastAPI 的 Router 是在执行过程中才将匹配到的 route 挂载到 scope 中  # noqa: E501
            route = request.scope.get("route")
            # 🚨 高基数内存泄漏陷阱防范：对于未匹配到的路由，绝对不能使用 request.url.path  # noqa: E501
            endpoint = route.path if route else "UNMATCHED_ROUTE"

            # 收集 Prometheus 监控数据 (纯内存操作，耗时约几百纳秒)
            REQUEST_COUNT.labels(method=method, endpoint=endpoint, http_status=status_code).inc()  # noqa: E501
            REQUEST_LATENCY.labels(method=method, endpoint=endpoint).observe(process_time)  # noqa: E501

            # 根据耗时动态染色：< 100ms 绿色，< 500ms 黄色，> 500ms 红色警报
            color = "green" if process_time < 0.1 else ("yellow" if process_time < 0.5 else "red")  # noqa: E501

            logger.info(
                f"[{color}]{method}[/] {endpoint} "
                f"- Status: {status_code} "
                f"- [cyan]{process_time:.4f}s[/]"
            )
            return response

        except Exception:
            # 即使发生严重异常，也记录耗时并交由 logger 触发携带上下文的 Traceback
            process_time = time.perf_counter() - start_time

            # 发生异常时，也尝试提取已经匹配到的路由
            route = request.scope.get("route")
            endpoint = route.path if route else "UNMATCHED_ROUTE"

            # 保证发生报错时，监控大盘同样能够捕捉到 500 熔断与耗时
            REQUEST_COUNT.labels(method=method, endpoint=endpoint, http_status=500).inc()  # noqa: E501
            REQUEST_LATENCY.labels(method=method, endpoint=endpoint).observe(process_time)  # noqa: E501

            logger.exception(f"[red]🔥 接口异常熔断[/] {method} {endpoint} - [cyan]{process_time:.4f}s[/]")  # noqa: E501
            raise
