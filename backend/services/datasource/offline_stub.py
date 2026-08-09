"""
==========================================================
三方数据源离线 Stub (SVC-06)
==========================================================

量化主脑的数据源（YFinance / Futu / FMP / Finnhub / AKShare / Tushare /
FRED / DBnomics / RBI / Search）均已远程化，由 data_subservice 子节点代理，
主服务不再本地 SDK 直连外部 API。

但在 CI / 本地离线开发时，连子服务节点也不应触网。本模块提供**确定性离线
stub 数据**：当 QUANT_ENV ∈ {offline, testing, dev} 或显式 OFFLINE_MODE=1 时，
DataSourceRouter.fetch_* 直接返回本模块的假数据，保证零网络、可重复、不烧钱。

stub 数据特征：
- 确定性（无随机），便于测试断言；
- 字段结构与真实响应兼容（含 success/status/results 等），调用方降级逻辑可正常解析；
- 仅用于开发/测试，绝不进入生产流量（生产环境 OFFLINE_MODE 必须为 0）。
"""

from __future__ import annotations

import os
from typing import Any, Dict


def is_offline_mode_enabled() -> bool:
    """是否启用数据源离线 stub（DataSourceRouter.fetch_* 短路）。

    触发条件（任一满足）：
    - OFFLINE_MODE=1（显式开关，CI / 本地离线开发推荐）
    - QUANT_ENV=offline（显式离线环境）

    ⚠️ 设计取舍：不把 testing/dev 自动纳入，否则会破坏既有的 router 集成测试
    （它们在 QUANT_ENV=testing 下依赖 conftest 的远程节点 mock 走真实路径）。
    LLM 离线 stub 的触发条件更宽松（testing 即启用），因其既有测试已默认离线。
    """
    env = os.getenv("QUANT_ENV", "").lower()
    if env == "offline":
        return True
    return os.getenv("OFFLINE_MODE", "0").lower() in ("1", "true", "yes", "on")


def _ok(payload: Dict[str, Any]) -> Dict[str, Any]:
    """包装成功响应。"""
    return {"success": True, "status": "ok", "offline_stub": True, **payload}


def _stub_yfinance(ticker: str, fetch_type: str = "history", **kwargs) -> Dict[str, Any]:
    return _ok(
        {
            "ticker": ticker,
            "fetch_type": fetch_type,
            "data": [
                {"date": "2026-08-07", "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 1000000},
                {"date": "2026-08-08", "open": 100.5, "high": 102.0, "low": 100.0, "close": 101.5, "volume": 1200000},
            ],
        }
    )


def _stub_akshare(action: str, **kwargs) -> Dict[str, Any]:
    return _ok({"action": action, "data": [{"code": "000001", "name": "平安银行", "price": 11.5}]})


def _stub_tushare(action: str, **params) -> Dict[str, Any]:
    return _ok({"action": action, "data": [{"ts_code": "000001.SZ", "close": 11.5}]})


def _stub_futu(action: str, **params) -> Dict[str, Any]:
    return _ok({"action": action, "symbol": params.get("symbol", "HK.00700"), "last_price": 380.0})


def _stub_fmp(action: str, **params) -> Dict[str, Any]:
    return _ok({"action": action, "data": [{"symbol": "AAPL", "price": 228.0}]})


def _stub_finnhub(action: str, **params) -> Dict[str, Any]:
    return _ok({"action": action, "symbol": params.get("symbol", "AAPL"), "c": 228.0, "dp": 1.2})


def _stub_fred(action: str, **params) -> Dict[str, Any]:
    return _ok({"action": action, "series_id": params.get("series_id", "DGS10"), "value": 4.2})


def _stub_dbnomics(action: str, **params) -> Dict[str, Any]:
    return _ok({"action": action, "data": [{"value": 100.0}]})


def _stub_rbi(action: str, **params) -> Dict[str, Any]:
    return _ok({"action": action, "data": [{"indicator": "repo_rate", "value": 6.5}]})


def _stub_search(source: str, **params) -> Dict[str, Any]:
    return _ok({"source": source, "results": [{"title": "[离线stub] 搜索结果", "url": "https://example.com"}]})


# source → stub 构造器
_STUB_BUILDERS = {
    "yfinance": _stub_yfinance,
    "akshare": _stub_akshare,
    "tushare": _stub_tushare,
    "futu": _stub_futu,
    "fmp": _stub_fmp,
    "finnhub": _stub_finnhub,
    "fred": _stub_fred,
    "dbnomics": _stub_dbnomics,
    "rbi": _stub_rbi,
    "search": _stub_search,
}


def build_offline_response(source: str, action: str = "", **params) -> Dict[str, Any]:
    """根据 source 构造确定性离线 stub 响应。未知 source 返回通用空成功。"""
    builder = _STUB_BUILDERS.get(source)
    if builder is None:
        return _ok({"source": source, "action": action, "data": []})
    if source == "yfinance":
        # builder 自行从 params 解包 ticker / fetch_type，避免重复传参冲突
        return builder(**params)
    if source == "search":
        return builder(action or "tavily", **params)
    return builder(action, **params)
