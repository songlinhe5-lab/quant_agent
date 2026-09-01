"""SEC EDGAR 一手申报数据客户端（FIN-01，docs/28 §二）。

三端点封装：
- ``submissions``    公司申报索引（含全部近期 filing 元数据）
- ``companyfacts``   XBRL 全量事实（单公司可达数 MB，必须落盘缓存）
- ``frames``         市场截面（一次请求拿全市场某 tag 某期取值，FIN-06 同业分位用）
- ``symbols``        ticker → CIK 对照表（FIN-04 实体解析；周更，长 TTL 缓存）

合规红线（docs/28 §二「采集合规」）：
- SEC 要求描述性 ``User-Agent``（含联系邮箱），缺失即 403；
- 请求频率 ≤ 10 req/s，超限封 IP → 本模块内置令牌桶限流（默认 8/s 留余量）；
- 429/限流命中返回 ``error_category=rate_limit``，主服务侧不计入熔断失败计数。

本层只做「获取 + 保障」，不做任何业务归一化（AGENTS §2）；
XBRL tag → 标准科目的映射在 backend/domain/financials（FIN-02）。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import time
from collections import deque
from html import unescape as html_unescape
from pathlib import Path
from typing import Any, Callable

import httpx

from data_subservice._internal.logger import logger

_BASE = "https://data.sec.gov"
_WWW_BASE = "https://www.sec.gov"

_TAG_RE = re.compile(r"<[^>]+>")
_BLOCK_RE = re.compile(r"</(p|div|tr|table|h[1-6]|li)>", re.IGNORECASE)


def _html_to_text(html: str) -> str:
    """确定性 HTML → 纯文本：去 script/style、块级标签换行、剥其余标签、折叠空白。"""
    s = re.sub(r"<(script|style)[\s\S]*?</\1>", " ", html, flags=re.IGNORECASE)
    s = _BLOCK_RE.sub("\n", s)
    s = _TAG_RE.sub(" ", s)
    s = html_unescape(s)
    lines = (re.sub(r"\s+", " ", ln).strip() for ln in s.split("\n"))  # Unicode \s 含 unescape 后的 \xa0
    return "\n".join(ln for ln in lines if ln)


# 默认 UA：描述性 + 联系邮箱（SEC fair access 政策要求）。
# 生产必须经 SEC_EDGAR_USER_AGENT 覆盖为真实可达邮箱，否则可能被 SEC 封禁。
_DEFAULT_UA = "quant-agent-data-subservice/1.0 (quantitative research; contact: ops@quant-agent.example.com)"


def _user_agent() -> str:
    ua = os.getenv("SEC_EDGAR_USER_AGENT", "").strip()
    if not ua:
        logger.warning("⚠️ [SEC] SEC_EDGAR_USER_AGENT 未配置，使用默认占位 UA（生产环境必须配置真实联系邮箱）")
        return _DEFAULT_UA
    return ua


def normalize_cik(cik: Any) -> str | dict[str, Any]:
    """归一化 CIK 为 10 位零填充字符串。

    接受 int / 纯数字 str / ``US:CIK0000320193`` / ``CIK123`` 形式；失败返回 error dict。
    """
    s = str(cik).strip().upper()
    if ":" in s:
        s = s.split(":")[-1]
    if s.startswith("CIK"):
        s = s[3:]
    s = "".join(ch for ch in s if ch.isdigit())
    if not s or int(s) <= 0:
        return {"status": "error", "message": f"无效 CIK: {cik!r}", "error_category": "bad_request"}
    return s.zfill(10)


class TokenBucketLimiter:
    """滑动窗口限流器：任意 1 秒窗口内最多 ``max_per_sec`` 次。

    clock/sleep 可注入以便单测（禁打真实外网、禁真实等待）。
    """

    def __init__(
        self,
        max_per_sec: float,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Any] = asyncio.sleep,
    ):
        self.max_per_sec = max(1.0, float(max_per_sec))
        self._clock = clock
        self._sleep = sleep
        self._hits: deque[float] = deque()

    async def acquire(self) -> None:
        while True:
            now = self._clock()
            while self._hits and now - self._hits[0] >= 1.0:
                self._hits.popleft()
            if len(self._hits) < self.max_per_sec:
                self._hits.append(now)
                return
            wait = 1.0 - (now - self._hits[0])
            await self._sleep(max(wait, 0.01))


class SecEdgarService:
    """SEC EDGAR REST 客户端（子服务叶子节点，仅本层触 data.sec.gov）。"""

    def __init__(self) -> None:
        self._limiter = TokenBucketLimiter(float(os.getenv("SEC_EDGAR_MAX_RPS", "8")))

    # ── 内部 HTTP ──

    async def _get_json(self, url: str, timeout: float = 30.0, host: str = "data.sec.gov") -> dict[str, Any]:
        """带 UA + 限流的 GET JSON。错误统一 {status:error}，429 标 rate_limit。"""
        await self._limiter.acquire()
        headers = {
            "User-Agent": _user_agent(),
            "Accept-Encoding": "gzip, deflate",
            "Host": host,
        }
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as c:
                r = await c.get(url, headers=headers)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"⚠️ [SEC] 请求失败 {url}: {e}")
            return {"status": "error", "message": f"SEC request failed: {e}"}
        if r.status_code == 200:
            try:
                return {"status": "success", "data": r.json()}
            except Exception as e:  # noqa: BLE001
                return {"status": "error", "message": f"SEC 响应非 JSON: {e}", "error_category": "bad_response"}
        if r.status_code == 429:
            return {"status": "error", "message": "SEC 429 rate limited", "error_category": "rate_limit"}
        if r.status_code == 403:
            return {"status": "error", "message": "SEC 403（UA 缺失/不合规或 IP 被封）", "error_category": "ip_blocked"}
        if r.status_code == 404:
            return {"status": "error", "message": f"SEC 404 not found: {url}", "error_category": "not_found"}
        return {"status": "error", "message": f"SEC HTTP {r.status_code}"}

    # ── 落盘缓存（companyfacts 单票数 MB，禁止每次全量拉） ──

    def _cache_dir(self) -> Path:
        return Path(os.getenv("SEC_CACHE_DIR", "data/cache/sec_edgar"))

    def _cache_read(self, key: str, ttl_sec: float) -> dict[str, Any] | None:
        f = self._cache_dir() / f"{key}.json"
        if not f.is_file():
            return None
        try:
            obj = json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return None
        if time.time() - float(obj.get("cached_at", 0)) > ttl_sec:
            return None
        return obj.get("payload")

    def _cache_write(self, key: str, payload: dict[str, Any]) -> None:
        try:
            d = self._cache_dir()
            d.mkdir(parents=True, exist_ok=True)
            (d / f"{key}.json").write_text(json.dumps({"cached_at": time.time(), "payload": payload}), encoding="utf-8")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"⚠️ [SEC] 缓存写入失败 {key}: {e}")

    # ── 三端点 ──

    async def get_submissions(self, cik: Any) -> dict[str, Any]:
        """公司申报索引（近期全部 filing 元数据 + older 文件指针）。"""
        norm = normalize_cik(cik)
        if isinstance(norm, dict):
            return norm
        resp = await self._get_json(f"{_BASE}/submissions/CIK{norm}.json")
        if resp.get("status") == "success":
            data = resp["data"]
            # 结构锁：SEC 改版必须显式失败而非静默拉空（docs/28 §二）
            if not isinstance(data, dict) or "filings" not in data:
                return {
                    "status": "error",
                    "message": "SEC submissions 结构变化（缺 filings 键）",
                    "error_category": "structure_changed",
                }
        return resp

    async def get_company_facts(self, cik: Any, use_cache: bool = True) -> dict[str, Any]:
        """XBRL 全量事实。默认落盘缓存（TTL 可配），冷取才打 SEC。

        增量按 ``filed`` 去重/合并属 FIN-02/03 归一化层职责，本层只缓存原始响应。
        """
        norm = normalize_cik(cik)
        if isinstance(norm, dict):
            return norm
        ttl = float(os.getenv("SEC_COMPANYFACTS_TTL_SEC", "21600"))  # 默认 6h
        key = f"companyfacts_CIK{norm}"
        if use_cache:
            cached = self._cache_read(key, ttl)
            if cached is not None:
                return {"status": "success", "data": cached, "cached": True}
        resp = await self._get_json(f"{_BASE}/api/xbrl/companyfacts/CIK{norm}.json", timeout=60.0)
        if resp.get("status") == "success":
            data = resp["data"]
            if not isinstance(data, dict) or "facts" not in data:
                return {
                    "status": "error",
                    "message": "SEC companyfacts 结构变化（缺 facts 键）",
                    "error_category": "structure_changed",
                }
            self._cache_write(key, data)
        return resp

    async def get_frames(self, taxonomy: str, concept: str, measure: str, frame: str) -> dict[str, Any]:
        """截面帧：全市场某概念在某期的取值（如 us-gaap/Assets/USD/CY2024Q3I）。

        ⚠️ 时点科目（Assets/StockholdersEquity）必须用 ``I`` 后缀帧（CY2024Q3I），
        流量科目用 ``CY2024`` / ``CY2024Q3``，用错后缀 SEC 返回 404（docs/28 §3.3）。
        """
        if not concept or not frame:
            return {"status": "error", "message": "frames 需要 concept 与 frame 参数", "error_category": "bad_request"}
        url = f"{_BASE}/api/xbrl/frames/{taxonomy.strip().lower()}/{concept.strip()}/{measure.strip().upper()}/{frame.strip()}.json"
        resp = await self._get_json(url)
        if resp.get("status") == "success":
            data = resp["data"]
            if not isinstance(data, dict) or "frame" not in data:
                return {
                    "status": "error",
                    "message": "SEC frames 结构变化（缺 frame 键）",
                    "error_category": "structure_changed",
                }
        return resp

    async def get_document_text(self, doc_url: str, max_chars: int = 2_000_000) -> dict[str, Any]:
        """FIN-08 · 申报文档全文（FIN-08 文本层 YoY diff 的文本源）。

        EDGAR 文档在 www.sec.gov/Archives（HTML/iXBRL，非 JSON），拉回后剥标签成纯文本。
        只做确定性清洗（去 script/style/tag、折叠空白），**不做任何 LLM/摘要**；
        文档可达数 MB，超过 max_chars 截断并标记 truncated（章节切分由主服务做）。

        FIN-09 性能：已申报文档 immutable → 落盘永久缓存（缓存清洗后全文，
        命中后再按 max_chars 截断；验收「缓存命中 < 1s」的关键）。
        """
        url = (doc_url or "").strip()
        if not url.startswith(("http://", "https://")):
            return {"status": "error", "message": "doc_url 非法", "error_category": "bad_request"}
        key = f"doc_text_{hashlib.md5(url.encode('utf-8')).hexdigest()}"
        cached = self._cache_read(key, float("inf"))  # immutable 文档永不过期
        if cached is not None and isinstance(cached, dict) and cached.get("text") is not None:
            return self._doc_text_payload(url, str(cached["text"]), max_chars, cached=True)

        host = "www.sec.gov" if "sec.gov" in url else url.split("//", 1)[-1].split("/", 1)[0]
        await self._limiter.acquire()
        headers = {"User-Agent": _user_agent(), "Host": host}
        try:
            async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as c:
                r = await c.get(url, headers=headers)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"⚠️ [SEC] 文档拉取失败 {url}: {e}")
            return {"status": "error", "message": f"document request failed: {e}"}
        if r.status_code == 429:
            return {"status": "error", "message": "SEC 429 rate limited", "error_category": "rate_limit"}
        if r.status_code == 404:
            return {"status": "error", "message": f"document 404: {url}", "error_category": "not_found"}
        if r.status_code != 200:
            return {"status": "error", "message": f"document HTTP {r.status_code}"}
        text = _html_to_text(r.text)
        self._cache_write(key, {"text": text})
        return self._doc_text_payload(url, text, max_chars, cached=False)

    @staticmethod
    def _doc_text_payload(url: str, full_text: str, max_chars: int, *, cached: bool) -> dict[str, Any]:
        """统一组装响应：缓存的是清洗后全文，截断随调用参数走。"""
        return {
            "status": "success",
            "data": {"url": url, "text": full_text[:max_chars], "truncated": len(full_text) > max_chars},
            "cached": cached,
        }

    async def get_symbols(self, use_cache: bool = True) -> dict[str, Any]:
        """ticker → CIK 对照表（FIN-04 实体解析用）。

        在 ``www.sec.gov/files``（非 data 子域），周更即可 → 默认 7 天缓存，
        禁止每次请求都拉全表。响应结构变化必须显式失败（缺键 → structure_changed）。
        """
        ttl = float(os.getenv("SEC_SYMBOLS_TTL_SEC", "604800"))  # 默认 7d
        key = "symbols_company_tickers"
        if use_cache:
            cached = self._cache_read(key, ttl)
            if cached is not None:
                return {"status": "success", "data": cached, "cached": True}
        resp = await self._get_json(f"{_WWW_BASE}/files/company_tickers.json", host="www.sec.gov")
        if resp.get("status") == "success":
            data = resp["data"]
            # 官方形状：{"0": {"cik_str":..,"ticker":..,"title":..}, ...}
            if not isinstance(data, dict) or not all(isinstance(v, dict) for v in data.values()):
                return {
                    "status": "error",
                    "message": "SEC company_tickers 结构变化",
                    "error_category": "structure_changed",
                }
            self._cache_write(key, data)
        return resp


sec_edgar_service = SecEdgarService()
