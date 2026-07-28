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

# 渐进迁移白名单：services 顶层仅允许保留尚未迁移的 Legacy 文件。
# 每完成一批迁移，对应条目从此集合移除（子集策略，允许逐步收缩，禁止新增）。
# 最终目标态：services 顶层仅保留 D 类核心聚合（audit/market_engine/oms/paper_ledger/strategy_version）。
ALLOWED_FLAT_SERVICES = frozenset(
    {
        "__init__.py",
        "akshare_service.py",
        "dbnomics_service.py",
        "rbi_service.py",
        "algo_engine.py",
        "alert_dispatcher.py",
        "audit_service.py",
        "backtest_report_service.py",
        "bot_runtime.py",
        "cep_engine.py",
        "data_quality_monitor.py",
        "data_source_router.py",
        "deep_research.py",
        "eval_runner.py",
        "factor_miner.py",
        "financial_pit.py",
        "finnhub_service.py",
        "futu_service.py",
        "kline_cache.py",
        "kline_warehouse.py",
        "llm_service.py",
        "market_correctness.py",
        "market_daemon.py",
        "market_engine.py",
        "notification_service.py",
        "oms_service.py",
        "options_screener.py",
        "paper_ledger_service.py",
        "paper_settlement_daemon.py",
        "portfolio_backtest.py",
        "rag_governance.py",
        "screener_service.py",
        "search_service.py",
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
            "backend.services.macro.fred_service",
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
        """services 顶层禁止新增扁平编排文件（子集策略：仅允许白名单内、且正逐步收缩）。

        迁移进行中，已迁出的文件不再出现在磁盘，present 为白名单子集即通过；
        任何白名单之外的「新增」扁平文件都会使 present - ALLOWED 非空而失败。
        """
        present = _top_level_py(SERVICES_DIR)
        unexpected = present - ALLOWED_FLAT_SERVICES
        assert not unexpected, (
            f"检测到新增扁平 services/*.py（请放到 backend/app/ 或 services 子包）: {sorted(unexpected)}"
        )

    def test_no_orphan_flat_service(self):
        """services 顶层不得残留已被显式移除白名单的孤立文件（每批迁移须同步更新白名单）。"""
        present = _top_level_py(SERVICES_DIR)
        # 反向：白名单中不存在于磁盘的条目不应是「误删白名单」造成，
        # 这里仅做信息性校验——真正约束由 test_no_new_flat_service_modules 的子集语义保证。
        assert present <= ALLOWED_FLAT_SERVICES
