"""
Option IV Summary 聚合逻辑单元测试（TEST-14 补充）
验证 get_option_iv_summary 的派生逻辑：
  - ATM IV（行权价最贴近最新价的 IV 均值）
  - IV 分位（ATM IV 在跨到期日 IV 序列中的分位数）
  - 30日已实现波动率（近 30 根日 K 收益率 std × sqrt(252)）
  - Skew（OTM put IV 均值 − OTM call IV 均值）
全程 mock facade，不触碰真实 Redis/PG/Futu/外网。
"""

from unittest.mock import AsyncMock, MagicMock

from backend.services.datasource.business.market import MarketDataService


def _result(data, is_error=False):
    r = MagicMock()
    r.is_error = is_error
    r.data = data
    r.source = "mock"
    r.status = "SUCCESS"
    return r


def _make_chain(last_price, strikes_ivs):
    """构造某到期日的 strikes 列表：[(strike, iv, kind)]"""
    items = [{"strike": s, "iv": iv, "kind": k} for (s, iv, k) in strikes_ivs]
    return {"expiry": "2026-09-18", "strikes": items}


async def test_atm_iv_and_skew():
    last_price = 100.0
    # 近月到期：含 ATM(100) + OTM put(90) + OTM call(110)
    chain = _make_chain(
        last_price,
        [
            (100, 0.40, "call"),
            (100, 0.40, "put"),
            (90, 0.50, "put"),  # OTM put → skew 正
            (110, 0.30, "call"),  # OTM call → skew 负向
        ],
    )
    chain["iv"] = 0.38  # 近月到期整体 IV，用于跨期分位序列
    chain_data = {
        "snapshot": {"last_price": last_price},
        "chains": [chain, {"expiry": "2026-10-16", "iv": 0.45, "strikes": []}],
    }
    hist_bars = [{"close": 100 + i} for i in range(1, 31)]

    svc = MarketDataService(facade=MagicMock())
    svc._facade.get_option_chain = AsyncMock(return_value=_result(chain_data))
    svc._facade.get_history = AsyncMock(return_value=_result(hist_bars))

    out = await svc.get_option_iv_summary("US.AAPL")

    # ATM IV 应接近 0.40（100 行权价最贴近 100 最新价）
    assert out["atm_iv"] is not None
    assert abs(out["atm_iv"] - 0.40) < 1e-6
    # Skew = mean(OTM put 0.50) - mean(OTM call 0.30) = 0.20
    assert abs(out["skew"] - 0.20) < 1e-6
    # RV30d 应 > 0（此处 close 线性递增，波动非零）
    assert out["rv30d"] is not None and out["rv30d"] > 0
    # IV 分位：跨期 IV 序列 [0.38, 0.45]，atm_iv=0.40 → 1/2 = 0.5
    assert out["iv_percentile"] is not None
    assert abs(out["iv_percentile"] - 0.5) < 1e-6


async def test_unavailable_returns_none_fields():
    svc = MarketDataService(facade=MagicMock())
    svc._facade.get_option_chain = AsyncMock(return_value=_result(None, is_error=True))
    svc._facade.get_history = AsyncMock(return_value=_result(None, is_error=True))

    out = await svc.get_option_iv_summary("US.AAPL")

    assert out["atm_iv"] is None
    assert out["iv_percentile"] is None
    assert out["rv30d"] is None
    assert out["skew"] is None
    assert out["available"] is False
