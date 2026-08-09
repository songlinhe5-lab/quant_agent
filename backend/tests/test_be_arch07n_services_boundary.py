"""
BE-ARCH-07n: 架构守门测试扩面 —— services/ 层禁止第三方数据源 SDK 直连。

背景：BE-ARCH-07f~07p 已将主服务 services/ 业务层（margin/fund_flow/datasource
adapters/business/subscription）的 akshare/yfinance/finnhub/fred 直连下沉到远程
data_subservice（经 data_source_router.fetch_*）。本测试锁死这一成果，防止复发。

门禁分层：
- 【强门禁 · 零容忍】以下目录绝对禁止直连任何第三方 SDK（akshare/yfinance/
  finnhub/fredapi/tushare/futu）：
    * backend/services/datasource/   （统一经 router 远程联邦，adapters 不得再持 SDK）
    * backend/services/margin/       （07f-3 已下沉 fetch_akshare）
    * backend/services/fund_flow/    （07f-3 已下沉 fetch_akshare）
    * backend/routers/              （BE-ARCH-01 既有红线）
- 【弱门禁 · 锁定不扩散】第三方 SDK import 只允许出现在已知 legacy 连接层目录
  （services/futu, services/akshare, services/tushare, services/finnhub,
  services/yfinance, services/fmp, services/adapters/legacy_market_data），
  且 futu SDK 直连**不得越过 services/futu/ 边界**（其余 services 子目录一律禁止）。
"""

from __future__ import annotations

import re
from pathlib import Path

SERVICES = Path(__file__).resolve().parents[1] / "services"
ROUTERS = Path(__file__).resolve().parents[1] / "routers"

# 第三方 SDK 直连 import（顶层 import 语句）
SDK_IMPORT = re.compile(
    r"("
    r"^from\s+(futu|akshare|yfinance|finnhub|fredapi|tushare)\b|"
    r"^import\s+(futu|akshare|yfinance|finnhub|fredapi|tushare)\b"
    r")"
)

# 强门禁目录（相对 services/ 或 routers/ 根的 glob 前缀）
STRONG_BAN_PREFIXES = [
    "datasource",
    "margin",
    "fund_flow",
]

# 已知 legacy 连接层目录（允许 SDK 直连，待 07j 整体下沉）
LEGACY_OK_DIRS = {
    "futu",
    "akshare",
    "tushare",
    "finnhub",
    "yfinance",
    "fmp",
    "adapters",  # legacy_market_data 在此，07c 部分卸载但 akshare 残留仍在
}


def _iter_py(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.py") if p.name != "__init__.py")


def _first_party_rel(path: Path) -> str:
    """返回相对 services/ 或 routers/ 的第一层目录名（用于判断归属）。"""
    try:
        rel = path.relative_to(SERVICES)
    except ValueError:
        rel = path.relative_to(ROUTERS)
    parts = rel.parts
    return parts[0] if parts else ""


def _match_sdk_import(path: Path) -> list[str]:
    hits: list[str] = []
    for i, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if line.startswith("#"):
            continue
        if SDK_IMPORT.search(line):
            hits.append(f"{path.name}:{i}: {line}")
    return hits


class TestServicesNoSDKDirectImport:
    def test_datasource_layer_zero_sdk(self):
        dirty: list[str] = []
        for p in _iter_py(SERVICES / "datasource"):
            dirty.extend(_match_sdk_import(p))
        assert not dirty, "services/datasource 仍直连第三方 SDK（应经 router 远程联邦）:\n" + "\n".join(dirty[:20])

    def test_margin_layer_zero_sdk(self):
        dirty = [str(p) for p in _match_all("margin")]
        assert not dirty, "services/margin 仍直连第三方 SDK:\n" + "\n".join(dirty[:20])

    def test_fund_flow_layer_zero_sdk(self):
        dirty = [str(p) for p in _match_all("fund_flow")]
        assert not dirty, "services/fund_flow 仍直连第三方 SDK:\n" + "\n".join(dirty[:20])

    def test_routers_layer_zero_sdk(self):
        dirty: list[str] = []
        for p in _iter_py(ROUTERS):
            dirty.extend(_match_sdk_import(p))
        assert not dirty, "routers 仍直连第三方 SDK:\n" + "\n".join(dirty[:20])

    def test_futu_sdk_confined_to_services_futu(self):
        """futu SDK 直连不得越过 services/futu/ 边界，防止新扩散。"""
        violations: list[str] = []
        for p in _iter_py(SERVICES):
            if _first_party_rel(p) == "futu":
                continue  # legacy 连接层目录，允许
            hits = _match_sdk_import(p)
            # 仅 futu 越界算违规；其他 SDK 由 legacy 白名单处理
            for h in hits:
                if re.search(r"\bfutu\b", h):
                    violations.append(f"{p}: {h}")
        assert not violations, "futu SDK 直连越出 services/futu/ 边界:\n" + "\n".join(violations[:20])

    def test_sdk_only_in_legacy_dirs(self):
        """第三方 SDK import 只应出现在已知 legacy 连接层目录。"""
        violations: list[str] = []
        for p in _iter_py(SERVICES):
            top = _first_party_rel(p)
            if top in LEGACY_OK_DIRS:
                continue
            for h in _match_sdk_import(p):
                violations.append(f"{p}: {h}")
        assert not violations, "第三方 SDK 直连出现在非 legacy 目录:\n" + "\n".join(violations[:20])


# ── hermes_agent 层 + 外部域名字面量强门禁 ──────────────────────────────────

HERMES = Path(__file__).resolve().parents[1].parent / "hermes_agent"

# 外部数据源域名字面量（强门禁区不得出现直连 URL）。
# 仅匹配 http(s):// 后的真实 URL（排除 "Tavily 搜索" 等纯 label 配置字符串）。
EXTERNAL_DOMAIN = re.compile(
    r"https?://[^\s\"']*("
    r"finnhub\.io|stlouisfed|db\.nomics|tavily\.com|bochaai\.com|r\.jina\.ai|"
    r"finance\.yahoo\.com|query1?\.finance\.yahoo|tushare\.pro|finra\.org|"
    r"api\.fred|fred\.stlouis|api\.finnhub"
    r")"
)

# 强门禁区（外部域名字面量不得出现）：仅覆盖本轮已 100% 远程化的红线目录
DOMAIN_STRONG_BAN_DIRS = [
    (ROUTERS, None),  # routers/ 全层
    (HERMES, None),  # hermes_agent/ 全层
    (SERVICES / "datasource" / "business", None),  # datasource/business/ 全层
]


def _match_external_domain(path: Path) -> list[str]:
    hits: list[str] = []
    for i, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if line.startswith("#"):
            continue
        if EXTERNAL_DOMAIN.search(line):
            hits.append(f"{path.name}:{i}: {line}")
    return hits


class TestExternalDomainNoDirectLink:
    def test_hermes_zero_sdk_import(self):
        if not HERMES.exists():
            return
        dirty: list[str] = []
        for p in _iter_py(HERMES):
            dirty.extend(_match_sdk_import(p))
        assert not dirty, "hermes_agent 仍直连第三方 SDK:\n" + "\n".join(dirty[:20])

    def test_routers_no_external_domain(self):
        dirty: list[str] = []
        for p in _iter_py(ROUTERS):
            dirty.extend(_match_external_domain(p))
        assert not dirty, "routers 出现外部数据源域名字面量（应经 router 远程）:\n" + "\n".join(dirty[:20])

    def test_hermes_no_external_domain(self):
        """hermes_agent 不得直连外部数据源；已知 jina 直连为 07m 待治理项，锁定不扩散。"""
        if not HERMES.exists():
            return
        known_violations = {
            "web_scrape_tool.py",  # 07m: 直连 r.jina.ai，应经 data_subservice Jina 代理
        }
        violations: list[str] = []
        for p in _iter_py(HERMES):
            hits = _match_external_domain(p)
            if p.name in known_violations:
                continue  # 登记已知遗留，待 07m 收口
            violations.extend(hits)
        assert not violations, "hermes_agent 出现新增外部数据源直连（超出已知 07m 清单）:\n" + "\n".join(
            violations[:20]
        )

    def test_datasource_business_no_external_domain(self):
        dirty: list[str] = []
        for p in _iter_py(SERVICES / "datasource" / "business"):
            dirty.extend(_match_external_domain(p))
        assert not dirty, "services/datasource/business 出现外部数据源域名字面量:\n" + "\n".join(dirty[:20])


def _match_all(subdir: str):
    res = []
    for p in _iter_py(SERVICES / subdir):
        res.extend(_match_sdk_import(p))
    return res
