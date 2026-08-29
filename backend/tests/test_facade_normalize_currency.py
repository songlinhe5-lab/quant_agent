"""
FAC-09: facade._normalize 币种推断单测
================================================================================
2026-08-29: 旧逻辑只认 ".HK" 后缀与裸 0 开头，Futu 前缀格式 (HK.00772)、
A 股 (SH.600519 / SZ.000001 / 裸代码 600519) 全被误判为 currency=USD。
修复后复用 _detect_market 市场感知推断：HK→HKD, CN→CNY, US→USD。
"""

from backend.services.datasource.business.facade import DataServiceFacade


def _norm(data):
    return DataServiceFacade._normalize(data, "FUNDAMENTAL")


def test_futu_hk_prefix_currency_hkd():
    """Futu 前缀格式 HK.00772 → HKD（旧逻辑误判 USD 的场景）"""
    out = _norm({"ticker": "HK.00772", "trailing_PE": 12.5})
    assert out["currency"] == "HKD"


def test_hk_suffix_currency_hkd():
    """后缀格式 00772.HK → HKD"""
    out = _norm({"ticker": "00772.HK", "trailing_PE": 12.5})
    assert out["currency"] == "HKD"


def test_cn_prefixed_currency_cny():
    """A 股前缀格式 SH./SZ. → CNY（旧逻辑误判 USD）"""
    assert _norm({"ticker": "SH.600519"})["currency"] == "CNY"
    assert _norm({"ticker": "SZ.000001"})["currency"] == "CNY"


def test_cn_naked_code_currency_cny():
    """裸代码 A 股 600519 → CNY（旧逻辑误判 USD）"""
    assert _norm({"ticker": "600519"})["currency"] == "CNY"
    assert _norm({"ticker": "300316"})["currency"] == "CNY"


def test_us_currency_usd():
    """US.AAPL / 裸美股 → USD"""
    assert _norm({"ticker": "US.AAPL"})["currency"] == "USD"
    assert _norm({"ticker": "AAPL"})["currency"] == "USD"


def test_existing_currency_preserved():
    """已有 currency 字段不被覆盖（尊重真实报告货币）"""
    out = _norm({"ticker": "00772.HK", "currency": "CNY", "revenue": 100})
    assert out["currency"] == "CNY"


def test_non_dict_passthrough():
    """非 dict 输入原样返回"""
    assert _norm([1, 2, 3]) == [1, 2, 3]
    assert _norm(None) is None
