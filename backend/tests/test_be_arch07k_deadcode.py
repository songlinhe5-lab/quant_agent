"""BE-ARCH-07k: 连接层死代码清理验证。

背景：主服务 backend/services/yfinance/ 的 search.py / technical.py 是直连
query2.finance.yahoo.com 的死 mixin（backend 生产代码无任何 import，无 __init__.py，
非合法包），已于 07k 删除。主服务 yahoo_news 改走 router.fetch_yfinance 远程代理
（US-YF-A/B 子服务），backend 不应再保留任何 yfinance 本地直连实现。

本测试锁死：
1. backend 全仓不得再 import backend.services.yfinance（死目录已删）；
2. 07n 弱门禁白名单已移除 yfinance（见 test_be_arch07n_services_boundary.py）；
3. backend 生产代码不得再直连 query2.finance.yahoo.com（由 07j 收口为 router 代理）。
"""

from __future__ import annotations

import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
YFINANCE_DIR = BACKEND / "services" / "yfinance"

# yfinance 库 import（本地直连 SDK）
YF_IMPORT = re.compile(r"(^from\s+yfinance\b|^import\s+yfinance\b)")
# Yahoo 直连域名
YAHOO_DOMAIN = re.compile(r"https?://[^\s\"']*query[12]?\.finance\.yahoo\.com")

# 已知 legacy 连接层目录（07n 弱门禁白名单，允许直连，待 07c 末段统一下沉）。
# 这些目录内的 Yahoo 直连属已登记遗留，不计入本轮 07k 强门禁。
LEGACY_OK_DIRS = {
    "services/futu",
    "services/akshare",
    "services/tushare",
    "services/finnhub",
    "services/fmp",
    "services/adapters",
}


def _iter_py(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.py") if p.name != "__init__.py")


def _rel(p: Path) -> str:
    return p.relative_to(BACKEND).as_posix()


def test_yfinance_dead_mixins_gone():
    """backend/services/yfinance 死 mixin 应已删除（07k 清理目标）。

    目录可能仍保留（空目录），但其中不得再含直连 Yahoo 的 search.py / technical.py。
    """
    dead_files = ("search.py", "technical.py")
    if not YFINANCE_DIR.exists():
        return
    for p in YFINANCE_DIR.rglob("*.py"):
        assert p.name not in dead_files, (
            f"backend/services/yfinance/{p.name} 死 mixin 仍残留（应已删除，主服务 yahoo_news 已改走 router 代理）"
        )
        assert not YAHOO_DOMAIN.search(p.read_text(encoding="utf-8")), (
            f"backend/services/yfinance/{p.name} 仍直连 Yahoo Finance（应已删除）"
        )


def test_backend_no_import_dead_yfinance():
    """backend 生产代码不得 import backend.services.yfinance（死包引用）。"""
    offenders: list[str] = []
    for p in _iter_py(BACKEND):
        rel = _rel(p)
        if rel.startswith("tests/") or rel.startswith("scripts/"):
            continue  # 测试/脚本不计入
        text = p.read_text(encoding="utf-8")
        for bad in ("backend.services.yfinance", "services.yfinance"):
            if bad in text:
                offenders.append(f"{rel} → {bad}")
    assert not offenders, "backend 生产代码仍引用已删除的 yfinance 死目录:\n" + "\n".join(offenders[:20])


def test_backend_non_legacy_no_yahoo_direct():
    """backend 非 legacy 生产代码不得直连 query2.finance.yahoo.com（07j 收口为 router 代理）。

    已知 legacy 连接层目录（services/finnhub 等）的 Yahoo fallback 属 07k 登记遗留，
    不计入本轮强门禁。
    """
    offenders: list[str] = []
    for p in _iter_py(BACKEND):
        rel = _rel(p)
        if rel.startswith("tests/") or rel.startswith("scripts/"):
            continue
        if any(rel.startswith(d + "/") or rel == d for d in LEGACY_OK_DIRS):
            continue  # 已知 legacy 目录，待 07c 下沉
        if YAHOO_DOMAIN.search(p.read_text(encoding="utf-8")):
            offenders.append(rel)
    assert not offenders, "backend 非 legacy 生产代码仍直连 Yahoo Finance:\n" + "\n".join(offenders[:20])
