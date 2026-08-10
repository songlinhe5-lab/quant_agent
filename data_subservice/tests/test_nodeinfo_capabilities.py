"""BE-ARCH-07l①：get_node_info 能力解析须正确按逗号切分，而非按字符迭代。"""

import os
from unittest import mock

from data_subservice.nodeinfo import get_node_info


def test_ds_capabilities_split_by_comma():
    """DS_CAPABILITIES 字符串须正确按逗号切分为能力列表。"""
    with mock.patch.dict(os.environ, {"DS_CAPABILITIES": "yfinance,akshare,tushare,fmp,futu"}, clear=False):
        info = get_node_info()
    assert info.capabilities == ["yfinance", "akshare", "tushare", "fmp", "futu"]


def test_ds_capabilities_no_split_bug():
    """回归：早期实现未 split，导致 'yfinance' 被拆成 ['y','f','i',...]，必须杜绝。"""
    with mock.patch.dict(os.environ, {"DS_CAPABILITIES": "yfinance,futu"}, clear=False):
        info = get_node_info()
    caps = info.capabilities
    assert "yfinance" in caps
    assert "futu" in caps
    assert not any(len(c) == 1 for c in caps), "能力被按字符拆分，DS_CAPABILITIES.split 未生效"


def test_default_fallback_when_unset():
    """未声明 DS_CAPABILITIES 时回退到默认集（含 futu/fmp，不含 finnhub/fred 等）。"""
    env = {k: v for k, v in os.environ.items() if k not in ("DS_CAPABILITIES", "NODE_CAPABILITIES")}
    with mock.patch.dict(os.environ, env, clear=True):
        info = get_node_info()
    assert "yfinance" in info.capabilities
    assert "futu" in info.capabilities
    assert "fmp" in info.capabilities


def test_explicit_capabilities_param_takes_precedence():
    """显式入参优先于环境变量。"""
    with mock.patch.dict(os.environ, {"DS_CAPABILITIES": "yfinance"}, clear=False):
        info = get_node_info(capabilities=["futu", "fmp"])
    assert info.capabilities == ["futu", "fmp"]


def test_capabilities_stripped_and_lowercased():
    """能力名应去除空格并统一小写。"""
    with mock.patch.dict(os.environ, {"DS_CAPABILITIES": "YFinance , Futu"}, clear=False):
        info = get_node_info()
    assert info.capabilities == ["yfinance", "futu"]
