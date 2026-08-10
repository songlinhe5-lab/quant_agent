"""
BE-ARCH-07o：scripts/ 探针脚本归口审计。

确保直接对接外部数据源 SDK / API 的诊断脚本统一归口到 scripts/probes/，
不得散落在 scripts/ 根目录（scripts/archive/ 为已知弃用归档，豁免）。

注意：本测试不是 07n 强门禁的一部分（07n 只扫描 backend/services|routers|core|hermes），
而是对 07o 归口成果的独立锁死——防止诊断脚本回潮到 scripts/ 根目录污染生产脚本区。
"""

from __future__ import annotations

import re
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1].parent / "scripts"

# 直接对接第三方数据源 SDK / 外部 API 的 import 或裸调用特征
EXTERNAL_SDK = re.compile(
    r"("
    r"^from\s+(futu|akshare|yfinance|finnhub|fredapi|tushare)\b|"
    r"^import\s+(futu|akshare|yfinance|finnhub|fredapi|tushare)\b|"
    r"^\s*import\s+(futu|akshare|yfinance|finnhub|fredapi|tushare)\b|"
    r"(requests|httpx)\.(get|post|AsyncClient).*(verify\s*=\s*False|params=)|"
    r"yf\.Ticker|tushare\.pro_api|akshare\.|query1?\.finance\.yahoo|api\.finnhub|fred\.stlouisfed"
    r")"
)

EXCLUDE_DIRS = {"probes", "archive", "__pycache__"}


def _iter_root_py() -> list[Path]:
    out: list[Path] = []
    for p in SCRIPTS.rglob("*.py"):
        rel = p.relative_to(SCRIPTS)
        if rel.parts and rel.parts[0] in EXCLUDE_DIRS:
            continue
        if p.name == "__init__.py":
            continue
        out.append(p)
    return sorted(out)


def _match_external(path: Path) -> list[str]:
    hits: list[str] = []
    for i, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if line.startswith("#"):
            continue
        if EXTERNAL_SDK.search(line):
            hits.append(f"{path.name}:{i}: {line}")
    return hits


def test_scripts_root_no_external_source_direct():
    """scripts/ 根目录（不含 probes/、archive/）不得出现直连外部数据源 SDK/API 的代码。"""
    violations: list[str] = []
    for p in _iter_root_py():
        for h in _match_external(p):
            violations.append(f"{p}: {h}")
    assert not violations, "scripts/ 根目录发现直连外部数据源的脚本（应移入 scripts/probes/）:\n" + "\n".join(
        violations[:20]
    )
