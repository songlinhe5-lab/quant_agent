"""
BE-ARCH-02: Application / Domain 目录落地守门。

- 新用例必须进 backend/app/，禁止新增扁平 services/*.py 编排文件
- app 层不得依赖 FastAPI
- domain 层不得依赖 routers / workers / 具体 *_service
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "app"
DOMAIN_DIR = ROOT / "domain"
SERVICES_DIR = ROOT / "services"

# 冻结：BE-ARCH-02 落地时已存在的顶层 services 文件（允许保留 Legacy）
ALLOWED_FLAT_SERVICES = frozenset(
    {
        "__init__.py",
        "akshare_service.py",
        "algo_analytics.py",
        "algo_engine.py",
        "alert_dispatcher.py",
        "alpha158.py",
        "audit_service.py",
        "backtest_report_service.py",
        "bot_runtime.py",
        "cep_engine.py",
        "cross_sectional.py",
        "data_quality_monitor.py",
        "data_source_router.py",
        "deep_research.py",
        "eval_framework.py",
        "eval_runner.py",
        "factor_miner.py",
        "financial_pit.py",
        "finnhub_service.py",
        "fred_service.py",
        "futu_service.py",
        "indicator_evaluator.py",
        "kline_cache.py",
        "kline_warehouse.py",
        "llm_service.py",
        "market_correctness.py",
        "market_daemon.py",
        "market_engine.py",
        "notification_service.py",
        "oms_service.py",
        "options_engine.py",
        "options_screener.py",
        "paper_ledger_service.py",
        "paper_settlement_daemon.py",
        "performance.py",
        "portfolio_backtest.py",
        "portfolio_optimizer.py",
        "rag_governance.py",
        "risk_attribution.py",
        "risk_cvar.py",
        "risk_engine.py",
        "risk_liquidity.py",
        "risk_sector.py",
        "risk_stress.py",
        "screener_service.py",
        "search_service.py",
        "sentiment_service.py",
        "sentiment_tracker.py",
        "strategy_parser.py",
        "strategy_version_service.py",
        "survivorship_bias.py",
        "system_monitor_service.py",
        "ticker_service.py",
        "yfinance_service.py",
    }
)

REQUIRED_APP_MODULES = frozenset(
    {
        "market_data.py",
        "broker.py",
        "oms_app.py",
        "backtest_app.py",
        "system_app.py",
        "walk_forward_app.py",
        "monte_carlo_app.py",
        "grid_search_app.py",
        "overfit_app.py",
    }
)


def _top_level_py(path: Path) -> set[str]:
    return {p.name for p in path.glob("*.py")}


class TestAppDirectoryLanded:
    def test_required_use_case_modules_exist(self):
        present = _top_level_py(APP_DIR)
        missing = REQUIRED_APP_MODULES - present
        assert not missing, f"缺少 Application 用例模块: {sorted(missing)}"

    def test_app_modules_do_not_import_fastapi(self):
        offenders: list[str] = []
        for path in APP_DIR.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name == "fastapi" or alias.name.startswith("fastapi."):
                            offenders.append(f"{path.name}: import {alias.name}")
                elif isinstance(node, ast.ImportFrom):
                    if node.module and (node.module == "fastapi" or node.module.startswith("fastapi.")):
                        offenders.append(f"{path.name}: from {node.module}")
        assert not offenders, "Application 层禁止依赖 FastAPI:\n" + "\n".join(offenders)


class TestDomainPurity:
    def test_domain_no_router_worker_or_concrete_service(self):
        forbidden = (
            "backend.routers",
            "backend.workers",
            "backend.services.futu_service",
            "backend.services.yfinance_service",
            "backend.services.akshare_service",
            "backend.services.finnhub_service",
            "backend.services.fred_service",
        )
        offenders: list[str] = []
        for path in DOMAIN_DIR.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for bad in forbidden:
                if bad in text:
                    offenders.append(f"{path.relative_to(ROOT)} → {bad}")
        assert not offenders, "Domain 污染:\n" + "\n".join(offenders)


class TestServicesFlatFreeze:
    def test_no_new_flat_service_modules(self):
        """禁止继续向扁平 services/ 堆新编排文件（子包 adapters/datalake 等豁免）。"""
        present = _top_level_py(SERVICES_DIR)
        unexpected = present - ALLOWED_FLAT_SERVICES
        assert not unexpected, (
            f"检测到新增扁平 services/*.py（请放到 backend/app/ 或 services 子包）: {sorted(unexpected)}"
        )

    def test_allowlist_not_silently_shrunk(self):
        """防止误删 allowlist 条目导致假绿。"""
        present = _top_level_py(SERVICES_DIR)
        missing = ALLOWED_FLAT_SERVICES - present
        # 允许个别 Legacy 文件被删除，但需显式从 allowlist 移除；此处只警告式硬失败若大量缺失
        assert len(missing) < 5, f"allowlist 与磁盘严重不一致，缺失: {sorted(missing)}"
