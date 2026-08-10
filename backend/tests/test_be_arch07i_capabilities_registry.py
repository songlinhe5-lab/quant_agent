"""BE-ARCH-07i 回归测试：capabilities 对齐 + Registry 回退收紧。

验证：
1. adapters 实际声明了 Facade 域方法所用 action（WARRANT_CHAIN/SCREEN_STOCKS/
   FUNDAMENTAL/INFO/FUND_FLOW/OPTION_CHAIN/TECH/FINANCIALS 等）。
2. DataSourceRegistry.get(name, action) 在能力不匹配时返回 None 并告警，
   不再静默回退首实例；DATASOURCE_LOOSE_CAPABILITY=1 时恢复旧行为。
"""

from __future__ import annotations

import importlib
import logging

from backend.services.datasource.source_registry import DataSourceRegistry


def _make_stub(name: str, caps: list[str], available: bool = True):
    class _Stub:
        @property
        def name(self) -> str:
            return name

        @property
        def capabilities(self) -> list[str]:
            return list(caps)

        def is_available(self) -> bool:
            return available

        @property
        def mode(self) -> str:
            return "remote"

    return _Stub()


def test_futu_adapter_declares_facade_actions():
    mod = importlib.import_module("backend.services.datasource.adapters.futu")
    caps = {c.upper() for c in mod.FutuDataSource().capabilities}
    for action in ("QUOTE", "HISTORY", "FUND_FLOW", "OPTION_CHAIN", "FUNDAMENTAL", "WARRANT_CHAIN", "SCREEN_STOCKS"):
        assert action in caps, f"futu adapter 未声明 {action}"


def test_akshare_adapter_declares_hsgt_holders():
    mod = importlib.import_module("backend.services.datasource.adapters.akshare")
    caps = {c.upper() for c in mod.AKShareDataSource().capabilities}
    assert "HSGT_HOLDERS" in caps
    assert "SOUTHBOUND" in caps
    assert "FUND_FLOW" in caps
    assert "HK_CONNECT" in caps


def test_fmp_adapter_declares_fundamental_info():
    mod = importlib.import_module("backend.services.datasource.adapters.fmp")
    caps = {c.upper() for c in mod.FMPDataSource().capabilities}
    assert "FUNDAMENTAL" in caps
    assert "INFO" in caps
    assert "QUOTE" in caps
    assert "PROFILE" in caps
    assert "INCOME_STATEMENT" in caps


def test_yfinance_adapter_declares_mapped_actions():
    mod = importlib.import_module("backend.services.datasource.adapters.legacy_yfinance")
    caps = {c.upper() for c in mod.LegacyYFinanceDataSource().capabilities}
    for action in ("QUOTE", "HISTORY", "FUND_FLOW", "OPTION_CHAIN", "FUNDAMENTAL", "INFO", "TECH", "FINANCIALS"):
        assert action in caps, f"yfinance adapter 未声明 {action}"


def test_registry_strict_no_fallback_on_capability_mismatch():
    reg = DataSourceRegistry()
    reg.register(_make_stub("futu", ["QUOTE", "HISTORY"]))
    # 请求未声明的能力：应返回 None（不再回退首实例）
    assert reg.get("futu", "WARRANT_CHAIN") is None
    assert reg.get("futu", "SCREEN_STOCKS") is None


def test_registry_returns_source_on_capability_match():
    reg = DataSourceRegistry()
    src = _make_stub("futu", ["QUOTE", "WARRANT_CHAIN"])
    reg.register(src)
    assert reg.get("futu", "warrant_chain") is src  # case-insensitive


def test_registry_loose_fallback_when_enabled(monkeypatch):
    monkeypatch.setenv("DATASOURCE_LOOSE_CAPABILITY", "1")
    reg = DataSourceRegistry()
    src = _make_stub("futu", ["QUOTE"])
    reg.register(src)
    # 宽松模式下不匹配也应回退到首实例
    assert reg.get("futu", "WARRANT_CHAIN") is src


def test_registry_warns_on_capability_mismatch(caplog):
    reg = DataSourceRegistry()
    reg.register(_make_stub("futu", ["QUOTE"]))
    with caplog.at_level(logging.WARNING):
        reg.get("futu", "WARRANT_CHAIN")
    assert any("未声明能力" in r.getMessage() for r in caplog.records)


def test_registry_unregistered_source_returns_none():
    reg = DataSourceRegistry()
    assert reg.get("nonexistent", "QUOTE") is None
