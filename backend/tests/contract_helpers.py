"""
SVC-01: 三方数据源契约测试基础设施
=================================

提供:
1. ``ContractMockSubservice`` — 线程内 HTTP 子服务, 模拟 data_subservice 的
   ``POST /api/v1/data`` 契约响应, 无需任何真实第三方 Key。
2. ``get_vcr`` — 统一 vcrpy 配置。录制点为主服务 ``DataSourceRouter._send_request``
   发出的 httpx 调用 (到子服务 ``/api/v1/data``)。默认 ``record_mode='none'``
   (CI 离线回放); 设 ``QUANT_RECORD=1`` 且子服务可达时 ``record_mode='new_episodes'``
   实时补录。

契约载体: 子服务响应 ``{"code":0,"data":...}`` -> router ``_normalize_response``
-> ``{"status":"success","data":...}``。三方改字段时, 适配器解析层断言会变红。

match_on 仅取 method+path (忽略 host/port), 使录制端口无关, 回放在任意端口可重放。
"""

from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Optional

import vcr

CASSETTE_DIR = os.path.join(os.path.dirname(__file__), "cassettes")
os.makedirs(CASSETTE_DIR, exist_ok=True)

DEFAULT_PORT = 18199


# ---------------------------------------------------------------------------
# 契约响应模板: 模拟子服务对不同 source/action 的返回
# 这些字段即为"三方契约"。任一方 (Yahoo/Finnhub/FMP/Futu/FRED) 改字段,
# 此处或 adapter 解析层需同步; 否则契约测试变红。
# ---------------------------------------------------------------------------
CONTRACT_RESPONSES: Dict[str, Dict[str, Any]] = {
    # Finnhub /quote 契约 (FinnhubDataSource.fetch 解析 c/pc/o/h/l/t/v)
    "finnhub|QUOTE": {
        "code": 0,
        "data": {
            "c": 189.71,
            "d": 1.23,
            "dp": 0.65,
            "h": 190.5,
            "l": 188.1,
            "o": 188.4,
            "pc": 188.48,
            "t": 1723819200,
            "v": 48213900,
            "symbol": "AAPL",
        },
        "meta": {"source": "finnhub", "action": "QUOTE", "latency_ms": 42},
    },
    # FMP /quote 契约
    "fmp|QUOTE": {
        "code": 0,
        "data": {
            "symbol": "AAPL",
            "price": 189.71,
            "changesPercentage": 0.65,
            "change": 1.23,
            "dayLow": 188.1,
            "dayHigh": 190.5,
            "open": 188.4,
            "previousClose": 188.48,
            "volume": 48213900,
        },
        "meta": {"source": "fmp", "action": "QUOTE", "latency_ms": 51},
    },
    # Futu /quote 契约 (透传子服务信封)
    "futu|QUOTE": {
        "code": 0,
        "data": {
            "code": 0,
            "stock_code": "AAPL",
            "curt_price": 189.71,
            "price_change": 1.23,
            "change_rate": 0.65,
            "open_price": 188.4,
            "high_price": 190.5,
            "low_price": 188.1,
            "last_close": 188.48,
            "volume": 48213900,
        },
        "meta": {"source": "futu", "action": "QUOTE", "latency_ms": 38},
    },
    # Yahoo /quote 契约 (yfinance 经子服务)
    "yfinance|QUOTE": {
        "code": 0,
        "data": {
            "ticker": "AAPL",
            "price": 189.71,
            "change": 1.23,
            "change_percent": 0.65,
            "open": 188.4,
            "day_high": 190.5,
            "day_low": 188.1,
            "previous_close": 188.48,
            "volume": 48213900,
        },
        "meta": {"source": "yfinance", "action": "QUOTE", "latency_ms": 67},
    },
    # FRED /macro_series 契约
    "fred|MACRO_SERIES": {
        "code": 0,
        "data": {
            "series_id": "DGS10",
            "observations": [
                {"date": "2026-08-01", "value": 4.21},
                {"date": "2026-08-02", "value": 4.18},
            ],
        },
        "meta": {"source": "fred", "action": "MACRO_SERIES", "latency_ms": 55},
    },
}


def _select_contract(body: Dict[str, Any]) -> Dict[str, Any]:
    source = body.get("source", "")
    action = body.get("action", "")
    key = f"{source}|{action}"
    if key in CONTRACT_RESPONSES:
        return CONTRACT_RESPONSES[key]
    # 兜底失败信封 (契约未覆盖的 source/action 不应被调用)
    return {"code": 1, "data": None, "message": f"contract not defined: {key}"}


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args, **kwargs):  # 静默
        pass

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            body = {}
        resp = _select_contract(body)
        payload = json.dumps(resp).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


class ContractMockSubservice:
    """线程内模拟 data_subservice, 供 QUANT_RECORD=1 时首次录制 cassette 使用。"""

    def __init__(self, host: str = "127.0.0.1", port: int = DEFAULT_PORT):
        self.host = host
        self.port = port
        self._server: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def start(self):
        self._server = ThreadingHTTPServer((self.host, self.port), _Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self):
        if self._server:
            self._server.shutdown()
            self._server.server_close()
        if self._thread:
            self._thread.join(timeout=2)


def get_vcr() -> vcr.VCR:
    """返回统一 vcr 配置。record_mode 受 QUANT_RECORD 控制。"""
    if os.getenv("QUANT_RECORD") == "1":
        record_mode = "new_episodes"
    else:
        record_mode = "none"
    return vcr.VCR(
        cassette_library_dir=CASSETTE_DIR,
        record_mode=record_mode,
        match_on=["method", "path"],
        filter_post_data_parameters=[],
        decode_compressed_response=True,
    )


def cassette_path(name: str) -> str:
    return os.path.join(CASSETTE_DIR, f"{name}.yaml")
