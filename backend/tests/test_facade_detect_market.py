"""
FAC-08: facade._detect_market 裸代码 A 股识别单测
================================================================================
2026-08-14: 前端/外部订阅可能以裸代码形式存 A 股（无 SH./SZ. 前缀），
此前被 _detect_market 判为 US，导致 FUND_FLOW/QUOTE 走 futu(无 A 股权限) 失败。
本测试覆盖裸代码 A 股按代码段识别为 CN 的逻辑，以及非 A 股不被误判。
"""

from backend.services.datasource.business.facade import _detect_market, _is_naked_cn_code


def test_naked_cn_codes_detected():
    """6 位纯数字 + 上交所/深交所代码段 → CN"""
    assert _detect_market("688777") == "CN"  # 科创板
    assert _detect_market("300316") == "CN"  # 创业板
    assert _detect_market("600667") == "CN"  # 沪市主板
    assert _detect_market("002195") == "CN"  # 深市主板
    assert _detect_market("601162") == "CN"  # 沪市主板
    assert _detect_market("000001") == "CN"  # 深市主板


def test_naked_cn_code_helper():
    """_is_naked_cn_code 代码段判断"""
    assert _is_naked_cn_code("688777") is True
    assert _is_naked_cn_code("300316") is True
    assert _is_naked_cn_code("600667") is True
    assert _is_naked_cn_code("002195") is True
    assert _is_naked_cn_code("900901") is True  # 沪 B股
    assert _is_naked_cn_code("200001") is True  # 深 B股
    assert _is_naked_cn_code("123456") is False  # 非 A 股段
    assert _is_naked_cn_code("1") is False  # 非 6 位
    assert _is_naked_cn_code("") is False


def test_existing_market_rules_preserved():
    """原有市场判定规则不被破坏"""
    assert _detect_market("US.AAPL") == "US"
    assert _detect_market("AAPL") == "US"
    assert _detect_market("HK.00700") == "HK"
    assert _detect_market("00700.HK") == "HK"
    assert _detect_market("SH.600000") == "CN"
    assert _detect_market("SZ.000001") == "CN"
    assert _detect_market("") == "US"


def test_non_cn_not_misclassified():
    """非 A 股代码不被误判为 CN"""
    assert _detect_market("00700") == "US"  # 5 位数字港股，非 6 位，仍 US
    assert _detect_market("GOOG") == "US"
    assert _detect_market("BABA") == "US"
    assert _detect_market("AAPL") == "US"
