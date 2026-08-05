"""补充 services/adapters/legacy_market_data.py 遗漏分支的覆盖率测试。

覆盖 CI 报告中的缺失行 (57-67, 70-92, 94-134, 144-214, 219-239, 306-362, 366-378):
- 各 QuotePort / Futu 扩展委托方法 (get_quote/get_history/get_fund_flow/
  get_warrant_chain/get_fundamental/screen_stocks 等 + status/error_msg 属性)
- _is_hk_ticker / _option_chain_lacks_pricing 纯函数
- _enrich_option_chain: 无 spot 仅拆分 / 有 spot 计算 Greeks
- get_option_chain: 正常含定价 / Futu 报错降级 YF / 港股降级窝轮
- get_option_chain_matrix: Futu 未连接报错 / 已连接组装曲面
"""

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.adapters.legacy_market_data import MarketDataGateway


def _make_gateway():
    # 绕过 __init__ 的注册副作用, 直接注入 mock 子服务
    gw = MarketDataGateway.__new__(MarketDataGateway)
    gw._futu = MagicMock()
    gw._yf = MagicMock()
    gw._ak = MagicMock()
    gw._fh = MagicMock()
    gw._fred = MagicMock()
    gw._dbnomics = MagicMock()
    gw._rbi = MagicMock()
    # 默认把降级用的真实 yfinance 方法替换掉, 避免 fork+xdist 子进程里
    # 真实 import yfinance / numpy 计算触发 segfault 把 worker 跑崩
    gw._option_chain_yfinance = AsyncMock(return_value=None)
    return gw


# ── 简单委托方法 (57-67, 306-362, 366-378) ─────────────────────────────────────
@pytest.mark.asyncio
async def test_delegation_methods():
    gw = _make_gateway()
    gw._futu.get_quote = AsyncMock(return_value={"last_price": 1})
    gw._futu.get_history = AsyncMock(return_value={"data": []})
    gw._futu.get_fund_flow = AsyncMock(return_value={"status": "success"})
    gw._futu.get_warrant_chain = AsyncMock(return_value={"status": "success"})
    gw._futu.get_fundamental = AsyncMock(return_value={"pe": 10})
    gw._futu.screen_stocks = MagicMock(return_value=[{"symbol": "AAPL"}])
    gw._futu.status = "CONNECTED"
    gw._futu.error_msg = "boom"
    gw._futu.quote_ctx = "ctx"
    gw._futu.conn_mgr = MagicMock()
    gw._futu.conn_mgr.status = "CONNECTED"
    gw._futu.conn_mgr._is_opend_reachable = MagicMock(return_value=True)
    gw._futu.conn_mgr.switch_host = MagicMock(return_value={"ok": True})
    gw._yf.get_tech_indicators = AsyncMock(return_value={"rsi": 50})

    assert (await gw.get_quote("US.AAPL"))["last_price"] == 1
    assert (await gw.get_history("US.AAPL")).get("data") == []
    assert (await gw.get_fund_flow("US.AAPL"))["status"] == "success"
    assert (await gw.get_warrant_chain("HK.00700"))["status"] == "success"
    assert (await gw.get_fundamental("US.AAPL"))["pe"] == 10
    assert await gw.screen_stocks("US", {"pe": "<15"}) == [{"symbol": "AAPL"}]
    assert await gw.get_tech_indicators("US.AAPL") == {"rsi": 50}

    # 属性 / setter
    assert gw.status == "CONNECTED"
    gw.status = "DISCONNECTED"
    assert gw._futu.status == "DISCONNECTED"
    assert gw.error_msg == "boom"
    gw.error_msg = "fixed"
    assert gw._futu.error_msg == "fixed"
    assert gw.quote_ctx == "ctx"
    gw.quote_ctx = "ctx2"
    assert gw._futu.quote_ctx == "ctx2"
    assert gw.conn_mgr is gw._futu.conn_mgr
    assert gw.source_router is gw._futu.source_router
    assert gw.connect() is gw._futu.connect()
    assert gw.is_opend_reachable() is True
    assert gw.switch_opend_host("1.2.3.4") == {"ok": True}
    health = gw.futu_health_status()
    assert health["status"] == "CONNECTED"  # switch_opend_host 已将 status 同步为 CONNECTED


# ── 纯函数 (219-239) ───────────────────────────────────────────────────────────
def test_is_hk_ticker():
    assert MarketDataGateway._is_hk_ticker("00700.HK") is True
    assert MarketDataGateway._is_hk_ticker("00700") is True
    assert MarketDataGateway._is_hk_ticker("US.AAPL") is False


def test_option_chain_lacks_pricing():
    # 无 options -> False
    assert MarketDataGateway._option_chain_lacks_pricing({"options": []}) is False
    # 含定价字段 -> False
    assert MarketDataGateway._option_chain_lacks_pricing({"options": [{"bid": 1}]}) is False
    # 全缺定价字段 -> True
    assert MarketDataGateway._option_chain_lacks_pricing({"options": [{"foo": 1}]}) is True


# ── _enrich_option_chain (94-134) ───────────────────────────────────────────────
def test_enrich_option_chain_no_spot():
    gw = _make_gateway()
    res = {"options": [{"option_type": "CALL"}, {"option_type": "PUT"}]}
    out = gw._enrich_option_chain(res, None)
    assert out["calls"] and out["puts"]
    assert "greeks" not in out["calls"][0]


def test_enrich_option_chain_with_spot():
    gw = _make_gateway()
    res = {
        "options": [
            {
                "option_type": "CALL",
                "strike_price": 100,
                "bid": 1,
                "ask": 2,
                "implied_volatility": 0.2,
                "days_to_expiry": 30,
            }
        ]
    }
    out = gw._enrich_option_chain(res, 105.0)
    assert out["underlying_price"] == 105.0
    assert "greeks" in out["calls"][0]


# ── get_option_chain 三种路径 (69-92) ───────────────────────────────────────────
@pytest.mark.asyncio
async def test_get_option_chain_normal():
    gw = _make_gateway()
    # 含定价字段(且带 underlying_price) -> 不走 yfinance 降级, 直接 enrich Greeks
    gw._futu.get_option_chain = AsyncMock(
        return_value={
            "status": "success",
            "underlying_price": 100.0,
            "options": [
                {
                    "option_type": "CALL",
                    "strike_price": 100,
                    "bid": 1,
                    "ask": 2,
                    "implied_volatility": 0.2,
                    "days_to_expiry": 30,
                }
            ],
        }
    )
    out = await gw.get_option_chain("US.AAPL")
    assert out["status"] == "success"
    assert "calls" in out


@pytest.mark.asyncio
async def test_get_option_chain_yfinance_fallback():
    gw = _make_gateway()
    gw._futu.get_option_chain = AsyncMock(return_value={"status": "error"})
    gw._option_chain_yfinance = AsyncMock(return_value={"status": "success", "options": [{"option_type": "CALL"}]})
    out = await gw.get_option_chain("US.AAPL")
    assert out["status"] == "success"


@pytest.mark.asyncio
async def test_get_option_chain_hk_warrant_fallback():
    gw = _make_gateway()
    gw._futu.get_option_chain = AsyncMock(return_value={"status": "error"})
    gw._option_chain_yfinance = AsyncMock(return_value={"status": "error"})
    gw._futu.get_warrant_chain = AsyncMock(return_value={"status": "success"})
    out = await gw.get_option_chain("00700.HK")
    assert out.get("_fallback") == "warrant_chain"


# ── get_option_chain_matrix (144-217) ───────────────────────────────────────────
@pytest.mark.asyncio
async def test_option_chain_matrix_not_connected():
    gw = _make_gateway()
    # Futu 未连接且无任何真实数据源可用 -> 应返回 error。
    # 直接 mock _get_option_expiration_dates 返回空, 避免 fork+xdist 子进程里
    # _get_option_expiration_dates 真实 import yfinance 触发 segfault 把 worker 跑崩
    # (见 _make_gateway 注释; _option_chain_yfinance 已被 mock, 但该方法内部仍会真 import)。
    gw._get_option_expiration_dates = AsyncMock(return_value=([], "none"))
    out = await gw.get_option_chain_matrix("US.AAPL")
    assert out["status"] == "error"


@pytest.mark.asyncio
async def test_option_chain_matrix_connected():
    gw = _make_gateway()
    gw._futu.conn_mgr = MagicMock()
    gw._futu.conn_mgr.status = "CONNECTED"
    gw._futu.get_option_expiration_date_list = AsyncMock(return_value=["2024-01-19"])
    gw.get_option_chain = AsyncMock(
        return_value={
            "status": "success",
            "options": [{"option_type": "CALL", "strike_price": 100, "greeks": {"delta": 0.5}, "iv": 0.2}],
        }
    )
    gw._futu.get_quote = AsyncMock(return_value={"last_price": 105})
    out = await gw.get_option_chain_matrix("US.AAPL")
    assert out["status"] == "success"
    assert out["expirations"] == ["2024-01-19"]


@pytest.mark.asyncio
async def test_get_option_expiration_dates_yf_fallback():
    """Futu 未连接时降级到 YFinance 真实期权到期日 (OPTION-01 修复路径)"""
    gw = _make_gateway()
    gw._futu.conn_mgr = None  # 跳过 Futu 分支
    fake_ticker = MagicMock()
    fake_ticker.options = ["2024-01-19", "2024-02-16"]
    fake_yf = MagicMock()
    fake_yf.Ticker.return_value = fake_ticker
    with patch.dict(sys.modules, {"yfinance": fake_yf}):
        dates, src = await gw._get_option_expiration_dates("US.AAPL")
    assert dates == ["2024-01-19", "2024-02-16"]
    assert src == "yfinance"


@pytest.mark.asyncio
async def test_get_option_expiration_dates_no_source():
    """Futu 与 YFinance 均无真实数据时返回空列表 + 'none' 源标识 (不伪造)"""
    gw = _make_gateway()
    gw._futu.conn_mgr = None
    fake_ticker = MagicMock()
    fake_ticker.options = []
    fake_yf = MagicMock()
    fake_yf.Ticker.return_value = fake_ticker
    with patch.dict(sys.modules, {"yfinance": fake_yf}):
        dates, src = await gw._get_option_expiration_dates("US.AAPL")
    assert dates == []
    assert src == "none"
