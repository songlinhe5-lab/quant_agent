"""
BE-ARCH-03: Collector 真正插件化守门。

- start_collector_daemons 不得硬编码具体服务 import
- 每个 COLLECTORS 条目必须有 factory
- factory 模块位于 workers/collectors/
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "workers" / "collector_registry.py"
FACTORIES_DIR = ROOT / "workers" / "collectors"

FORBIDDEN_IMPORT_SUBSTRINGS = (
    "yfinance_service",
    "futu_service",
    "futu.watchdog",
    "market_daemon",
    "akshare_collector",
    "akshare_service",
    "finnhub_service",
)


def _imports_in_function(tree: ast.AST, func_name: str) -> list[str]:
    hits: list[str] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name:
            for child in ast.walk(node):
                if isinstance(child, ast.Import):
                    for alias in child.names:
                        hits.append(alias.name)
                elif isinstance(child, ast.ImportFrom) and child.module:
                    hits.append(child.module)
    return hits


class TestCollectorPluginBoundary:
    def test_start_daemons_has_no_concrete_service_imports(self):
        tree = ast.parse(REGISTRY.read_text(encoding="utf-8"), filename=str(REGISTRY))
        imports = _imports_in_function(tree, "start_collector_daemons")
        offenders = [mod for mod in imports if any(bad in mod for bad in FORBIDDEN_IMPORT_SUBSTRINGS)]
        assert not offenders, "start_collector_daemons 禁止硬编码数据源 import: " + ", ".join(offenders)

    def test_registry_module_body_has_no_concrete_service_imports(self):
        """模块顶层也不得直接 import yf_service 等（只允许 collectors 包）。"""
        tree = ast.parse(REGISTRY.read_text(encoding="utf-8"), filename=str(REGISTRY))
        offenders: list[str] = []
        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and node.module:
                if any(bad in node.module for bad in FORBIDDEN_IMPORT_SUBSTRINGS):
                    offenders.append(node.module)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if any(bad in alias.name for bad in FORBIDDEN_IMPORT_SUBSTRINGS):
                        offenders.append(alias.name)
        assert not offenders, "collector_registry 顶层污染: " + ", ".join(offenders)

    def test_factory_modules_exist_for_all_collectors(self):
        from backend.workers.collector_registry import COLLECTORS

        for name in COLLECTORS:
            path = FACTORIES_DIR / f"{name}.py"
            assert path.is_file(), f"缺少 factory 模块: {path}"
            assert "async def start" in path.read_text(encoding="utf-8")
