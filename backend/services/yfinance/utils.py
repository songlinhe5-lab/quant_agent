"""YFinance 工具函数与限流 Session"""

import threading
import time
from collections import deque

import requests

try:
    # yfinance >= ~0.2.50 将 session 基类切换为 curl_cffi.requests.Session，
    # 自定义限流 session 必须继承它，否则触发
    # "Yahoo API requires curl_cffi session" 导致全量抓取失败（影响 macro daemon / on-demand）。
    from curl_cffi import requests as _cffi_requests

    _SessionBase = _cffi_requests.Session
except Exception:  # pragma: no cover - 旧版 yfinance 仍用标准库 requests.Session
    _SessionBase = requests.Session


def format_yf_ticker(ticker: str) -> str:
    yf_ticker = ticker.upper().replace("US.", "")
    index_map = {
        "HSI": "^HSI",
        "HK.800000": "^HSI",
        "HK.HSI": "^HSI",
        "HSTECH": "HSTECH.HK",  # 💡 恒生科技指数 Yahoo 代码
        "HK.800700": "HSTECH.HK",  # 💡 恒生科技指数 Yahoo 代码
        "HK.800100": "^HSCE",  # 💡 恒生国企指数 Yahoo 代码
        "SPX": "^GSPC",
        "IXIC": "^IXIC",
        "DJI": "^DJI",
        "VIX": "^VIX",
        "SSEC": "000001.SS",
        "000001.SH": "000001.SS",
        "CSI300": "000300.SS",
        "399300.SZ": "399300.SZ",
        "399001.SZ": "399001.SZ",
        "TSMC": "TSM",
        "N225": "^N225",
        "DX-Y": "DX-Y.NYB",
        "TNX": "^TNX",
        "GC=F": "GC=F",
        "JGB10Y": "^JN09T",
        "USDCNH": "USDCNH=X",
        "CNH=X": "USDCNH=X",  # 💡 兼容旧代码
        "BTC": "BTC-USD",
        "CL=F": "CL=F",
    }
    if yf_ticker in index_map:
        return index_map[yf_ticker]

    if yf_ticker.endswith(".HK") or yf_ticker.startswith("HK."):
        code = yf_ticker.replace(".HK", "").replace("HK.", "")
        yf_ticker = f"{code.lstrip('0').zfill(4)}.HK" if code.isdigit() else f"{code}.HK"  # noqa: E501
    elif yf_ticker.startswith("SH."):
        yf_ticker = yf_ticker.replace("SH.", "") + ".SS"
    elif yf_ticker.endswith(".SH"):
        yf_ticker = yf_ticker.replace(".SH", ".SS")
    elif yf_ticker.startswith("SZ."):
        yf_ticker = yf_ticker.replace("SZ.", "") + ".SZ"
    elif yf_ticker.startswith("JP."):
        yf_ticker = yf_ticker.replace("JP.", "") + ".T"  # 东京交易所后缀
    elif yf_ticker.startswith("SG."):
        yf_ticker = yf_ticker.replace("SG.", "") + ".SI"  # 新加坡交易所后缀
    elif yf_ticker.startswith("UK.") or yf_ticker.startswith("LSE."):
        yf_ticker = yf_ticker.replace("UK.", "").replace("LSE.", "") + ".L"  # 伦敦交易所后缀  # noqa: E501

    return yf_ticker


class RateLimitedSession(_SessionBase):
    """
    带有线程安全限流器的 requests.Session。
    防止 yfinance 在开启并发下载或大批量请求时被 Yahoo 封锁 (429)。
    """

    def __init__(self, max_requests: int = 1, per_seconds: float = 2.0):
        super().__init__()
        self.max_requests = max_requests  # 1 request
        self.per_seconds = per_seconds
        self._request_times = deque()
        self._rl_lock = threading.Lock()

    def request(self, method, url, *args, **kwargs):
        # 🚨 致命遗漏修复：强制注入请求超时限制。
        # yfinance 内部大量网络请求未显式配置 timeout。若雅虎服务器假死，
        # 请求会永久挂起，从而耗尽 FastAPI 默认的 asyncio.to_thread 线程池导致整个网关死锁！  # noqa: E501
        kwargs.setdefault("timeout", 15.0)

        sleep_time = 0.0
        with self._rl_lock:
            now = time.time()
            while self._request_times and now > self._request_times[0] + self.per_seconds:  # noqa: E501
                self._request_times.popleft()

            if len(self._request_times) >= self.max_requests:
                # 严格按照先进先出漏桶控制，保障每 per_seconds 内最多执行 max_requests 次  # noqa: E501
                earliest_allowed = self._request_times[-self.max_requests] + self.per_seconds  # noqa: E501
                sleep_time = earliest_allowed - now
                if sleep_time < 0:
                    sleep_time = 0

            self._request_times.append(now + sleep_time)

        if sleep_time > 0:
            time.sleep(sleep_time)

        from backend.core.logger import logger
        from backend.core.middleware import EXTERNAL_API_COUNT, EXTERNAL_API_LATENCY

        start_t = time.perf_counter()
        try:
            res = super().request(method, url, *args, **kwargs)
            process_time = time.perf_counter() - start_t
            EXTERNAL_API_COUNT.labels(service_name="yfinance", method=method, http_status=res.status_code).inc()  # noqa: E501
            EXTERNAL_API_LATENCY.labels(service_name="yfinance", method=method).observe(process_time)  # noqa: E501
            if process_time > 3.0:
                logger.warning(f"🐢 [Slow Egress API] yfinance ({method} {url}) 耗时: {process_time:.2f}s")  # noqa: E501
            return res
        except Exception as e:
            process_time = time.perf_counter() - start_t
            EXTERNAL_API_COUNT.labels(service_name="yfinance", method=method, http_status=500).inc()  # noqa: E501
            EXTERNAL_API_LATENCY.labels(service_name="yfinance", method=method).observe(process_time)  # noqa: E501
            raise e
