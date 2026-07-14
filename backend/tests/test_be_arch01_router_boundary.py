"""
BE-ARCH-01: Router 层禁止直连具体数据源 / 券商 SDK。

验收：backend/routers/*.py 不得 import futu_service / yf_service /
akshare_service / finnhub_service / fred_service / futu SDK / yfinance。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROUTERS_DIR = Path(__file__).resolve().parents[1] / "routers"

FORBIDDEN_IMPORT = re.compile(
    r"("
    r"from\s+backend\.services\.futu_service\b|"
    r"from\s+backend\.services\.yfinance_service\b|"
    r"from\s+backend\.services\.akshare_service\b|"
    r"from\s+backend\.services\.finnhub_service\b|"
    r"from\s+backend\.services\.fred_service\b|"
    r"from\s+backend\.services\.futu\b|"
    r"from\s+futu\s+import\b|"
    r"import\s+futu\b|"
    r"import\s+yfinance\b"
    r")"
)


def _router_files() -> list[Path]:
    return sorted(p for p in ROUTERS_DIR.glob("*.py") if p.name != "__init__.py")


class TestRouterNoDatasourceDirectImport:
    def test_all_routers_clean(self):
        dirty: list[str] = []
        for path in _router_files():
            for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if FORBIDDEN_IMPORT.search(stripped):
                    dirty.append(f"{path.name}:{i}: {stripped}")
        assert not dirty, "Router 仍直连数据源:\n" + "\n".join(dirty[:30])

    def test_clean_ratio_at_least_70_percent(self):
        total = len(_router_files())
        dirty_files = set()
        for path in _router_files():
            for line in path.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if FORBIDDEN_IMPORT.search(stripped):
                    dirty_files.add(path.name)
                    break
        clean = total - len(dirty_files)
        ratio = clean / total if total else 0.0
        assert ratio >= 0.70, f"clean ratio {ratio:.0%} < 70% ({clean}/{total})"

    def test_app_market_data_exports_gateway(self):
        from backend.app.market_data import market_data
        from backend.domain.ports import QuotePort

        assert hasattr(market_data, "get_quote")
        assert hasattr(market_data, "get_history")
        assert isinstance(market_data, QuotePort)

    def test_app_broker_exports_gateway(self):
        from backend.app.broker import broker
        from backend.domain.ports import BrokerPort

        assert hasattr(broker, "place_order")
        assert isinstance(broker, BrokerPort)

    def test_ticker_format_pure(self):
        from backend.core.ticker_format import format_ticker, format_yf_ticker

        assert format_ticker("00700.HK") == "HK.00700"
        assert format_yf_ticker("HK.00700") == "0700.HK"
