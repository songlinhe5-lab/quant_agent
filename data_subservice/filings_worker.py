"""Filings 一手采集 worker（FIN-01，docs/28 §二）。

三地申报索引统一入口（source=filings）：
- 美股 SEC EDGAR：``SUBMISSIONS`` / ``COMPANY_FACTS`` / ``FRAMES`` / ``SYMBOLS``（经 _internal/sec_edgar）
- 港股 HKEXnews 披露易：``HKEX_FILINGS``（titleSearchServlet 页面后端接口）
- A股 巨潮资讯网：``CNINFO_FILINGS``（hisAnnouncement 页面后端接口）

红线（docs/28 §二「采集合规」）：
- 披露易/巨潮是**页面后端接口而非开放 API**，解析必须锁响应结构：
  缺预期键 → 显式返回 ``structure_changed`` 错误，禁止静默拉空。
- 本层只做「获取 + 保障」：不入库、不归一化、不做业务编排（AGENTS §2）。
- SEC 采集节点固定美国节点；能力声明 ``DS_CAPABILITIES=...,filings``。
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

import httpx

from data_subservice._internal.logger import logger
from data_subservice._internal.sec_edgar import sec_edgar_service

_HKEX_URL = "https://www1.hkexnews.hk/search/titleSearchServlet.do"
_CNINFO_URL = "http://www.cninfo.com.cn/new/hisAnnouncement/query"
_CNINFO_STATIC = "http://static.cninfo.com.cn/"

# 浏览器型 UA：披露易/巨潮对空 UA 或脚本 UA 会拒答/返回验证码页
_BROWSER_UA = "Mozilla/5.0 (compatible; quant-agent-data-subservice/1.0; +ops@quant-agent.example.com)"

_SEC_ACTIONS = {"SUBMISSIONS", "COMPANY_FACTS", "FRAMES", "SYMBOLS"}


# ── SEC ──


async def _handle_sec(action: str, params: dict[str, Any]) -> dict[str, Any]:
    if action == "SUBMISSIONS":
        return await sec_edgar_service.get_submissions(params.get("cik") or params.get("entity_id"))
    if action == "COMPANY_FACTS":
        return await sec_edgar_service.get_company_facts(
            params.get("cik") or params.get("entity_id"),
            use_cache=bool(params.get("use_cache", True)),
        )
    if action == "FRAMES":
        return await sec_edgar_service.get_frames(
            params.get("taxonomy", "us-gaap"),
            params.get("concept", ""),
            params.get("measure", "USD"),
            params.get("frame", ""),
        )
    if action == "DOC_TEXT":
        # FIN-08：申报文档全文（YoY diff 文本源）
        return await sec_edgar_service.get_document_text(params.get("doc_url", ""))
    # SYMBOLS：ticker → CIK 对照表（FIN-04 实体解析）
    return await sec_edgar_service.get_symbols(use_cache=bool(params.get("use_cache", True)))


# ── 港股披露易 ──
# 2026-08-31 实测契约（阅文 00772 中报公告验证）：
# 1. titleSearchServlet 必须带 stockId（内部 ID），仅 stockCode 查不到 → 先经 prefix.do 解析；
# 2. 日期参数是 fromDate/toDate，格式 YYYYMMDD（pubFrom/pubTo 会被静默忽略，极危险）；
# 3. result 是「字符串化的 JSON 数组」需二次 loads；无记录时为 "null" 或 "[]" 字符串；
# 4. 字段全大写：TITLE / DATE_TIME(DD/MM/YYYY HH:MM) / FILE_TYPE / FILE_LINK / STOCK_CODE。

_HKEX_PREFIX_URL = "https://www1.hkexnews.hk/search/prefix.do"


def _hkex_num_code(code: str | None) -> str:
    """HK.00772 / 00772 / 772 → '00772'（5 位补零，prefix.do 要求）。"""
    raw = (code or "").replace("HK.", "").replace(".HK", "").strip()
    return raw.zfill(5) if raw.isdigit() else raw


def _hkex_iso_date(dt: str) -> str | None:
    """'11/08/2026 16:30' (DD/MM/YYYY) → '2026-08-11'；解析失败返回 None。"""
    try:
        d = dt.strip().split(" ")[0]
        day, mon, year = d.split("/")
        return f"{year}-{int(mon):02d}-{int(day):02d}"
    except (ValueError, AttributeError):
        return None


def _parse_hkex(payload: Any, limit: int) -> dict[str, Any]:
    """结构锁 + 归一为 {code,title,filed_at,url}。缺 result 键 → structure_changed。"""
    if not isinstance(payload, dict) or "result" not in payload:
        return {
            "status": "error",
            "message": "HKEX 响应结构变化（缺 result 键）",
            "error_category": "structure_changed",
        }
    rows = payload["result"]
    if isinstance(rows, str):
        if rows in ("null", "[]", ""):  # 无记录的两种字符串表示法（实测）
            rows = []
        else:
            try:  # result 是字符串化 JSON 数组（实测）
                rows = json.loads(rows)
            except json.JSONDecodeError:
                return {"status": "error", "message": "HKEX result 无法解析", "error_category": "structure_changed"}
    if rows is None:
        rows = []
    if not isinstance(rows, list):
        return {
            "status": "error",
            "message": "HKEX 响应结构变化（result 非列表）",
            "error_category": "structure_changed",
        }
    items = []
    for row in rows[:limit]:
        if not isinstance(row, dict):
            continue
        link = row.get("FILE_LINK") or ""
        items.append(
            {
                "code": row.get("STOCK_CODE"),
                "title": (row.get("TITLE") or "").replace("\n", " ").strip(),
                "filed_at": _hkex_iso_date(row.get("DATE_TIME") or ""),
                "file_type": row.get("FILE_TYPE") or None,
                "url": f"https://www1.hkexnews.hk{link}" if link.startswith("/") else link or None,
            }
        )
    return {"status": "success", "data": {"items": items, "has_more": bool(payload.get("hasNextRow"))}}


async def _resolve_hkex_stock_id(client: httpx.AsyncClient, code: str) -> str | None:
    """prefix.do 返回 JSONP ``callback({...stockId...})``，解析出内部 stockId。

    网络异常向上抛（由调用方统一报 request failed）；仅「无匹配股票」返回 None → not_found。
    """
    r = await client.get(
        _HKEX_PREFIX_URL,
        params={"callback": "cb", "lang": "ZH", "type": "A", "name": code, "market": "SEHK"},
        headers={"User-Agent": _BROWSER_UA},
    )
    if r.status_code != 200:
        return None
    m = re.search(r"\((\{.*\})\)", r.text, re.DOTALL)  # 剥 JSONP 壳
    if not m:
        return None
    for info in json.loads(m.group(1)).get("stockInfo", []):
        if info.get("code") == code and info.get("stockId"):
            return str(info["stockId"])
    return None


async def _get_hkex_filings(
    code: str | None = None, date_from: str | None = None, date_to: str | None = None, limit: int = 50
) -> dict[str, Any]:
    n_code = _hkex_num_code(code)
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as c:
            stock_id = await _resolve_hkex_stock_id(c, n_code) if n_code else None
            if code and not stock_id:
                return {"status": "error", "message": f"HKEX 无法解析 stockId: {code}", "error_category": "not_found"}
            params = {
                "sortDir": "-1",
                "sortName": "DATE_TIME",
                "sortByOptions": "DateTime",
                "title": "",
                "keyword": "",
                "searchType": "1",
                "stockId": stock_id or "-1",
                "stockCode": n_code,
                "market": "SEHK",
                "Mkt": "1",
                "fromDate": (date_from or "").replace("-", ""),
                "toDate": (date_to or "").replace("-", ""),
                "from": "1",
                "to": str(min(max(int(limit), 1), 100)),
                "count": str(min(max(int(limit), 1), 100)),
                "index": "0",
                "langCode": "E",
                "category": "0",
                "leadMin": "0",
                "leadMax": "0",
                "t1": "40000",
                "t2": "0",
                "board": "",
                "periodOfReport": "0",
                "output": "JSON",
            }
            r = await c.get(_HKEX_URL, params=params, headers={"User-Agent": _BROWSER_UA})
    except Exception as e:  # noqa: BLE001
        logger.warning(f"⚠️ [HKEX] 请求失败: {e}")
        return {"status": "error", "message": f"HKEX request failed: {e}"}
    if r.status_code != 200:
        return {"status": "error", "message": f"HKEX HTTP {r.status_code}"}
    try:
        payload = r.json()
    except Exception:  # noqa: BLE001
        # 页面改版常表现为返回 HTML 而非 JSON —— 必须显式失败
        return {
            "status": "error",
            "message": "HKEX 响应非 JSON（疑似页面改版/反爬）",
            "error_category": "structure_changed",
        }
    return _parse_hkex(payload, min(max(int(limit), 1), 100))


# ── A股巨潮 ──


def _parse_cninfo(payload: Any) -> dict[str, Any]:
    """结构锁 + 归一。缺 announcements 键 → structure_changed（禁止静默拉空）。"""
    if not isinstance(payload, dict) or not isinstance(payload.get("announcements"), list):
        return {
            "status": "error",
            "message": "CNINFO 响应结构变化（缺 announcements 列表）",
            "error_category": "structure_changed",
        }
    items = []
    for row in payload["announcements"]:
        if not isinstance(row, dict):
            continue
        ts_ms = row.get("announcementTime")
        filed_at = (
            datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).date().isoformat()
            if isinstance(ts_ms, (int, float)) and ts_ms > 0
            else None
        )
        adj = row.get("adjunctUrl") or ""
        items.append(
            {
                "id": row.get("announcementId"),
                "code": row.get("secCode"),
                "title": row.get("announcementTitle"),
                "filed_at": filed_at,
                "url": (_CNINFO_STATIC + adj) if adj else None,
            }
        )
    return {
        "status": "success",
        "data": {"items": items, "total": payload.get("totalAnnouncement"), "has_more": bool(payload.get("hasMore"))},
    }


async def _get_cninfo_filings(
    code: str,
    org_id: str | None = None,
    column: str = "szse",
    date_from: str | None = None,
    date_to: str | None = None,
    page: int = 1,
    page_size: int = 30,
    keyword: str = "",
) -> dict[str, Any]:
    if not code:
        return {"status": "error", "message": "CNINFO 需要 code 参数", "error_category": "bad_request"}
    se_date = ""
    if date_from or date_to:
        se_date = f"{date_from or ''}~{date_to or ''}"
    form = {
        "pageNum": str(max(int(page), 1)),
        "pageSize": str(min(max(int(page_size), 1), 100)),
        "column": column,
        "tabName": "fulltext",
        "plate": "",
        "stock": f"{code},{org_id}" if org_id else code,
        "searchkey": keyword or "",
        "secid": "",
        "category": "",
        "trade": "",
        "seDate": se_date,
        "sortName": "",
        "sortType": "",
        "isHLtitle": "true",
    }
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as c:
            r = await c.post(
                _CNINFO_URL,
                data=form,
                headers={
                    "User-Agent": _BROWSER_UA,
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Referer": "http://www.cninfo.com.cn/new/commonUrl/pageOfSearch?url=disclosure/list/search",
                    "X-Requested-With": "XMLHttpRequest",
                },
            )
    except Exception as e:  # noqa: BLE001
        logger.warning(f"⚠️ [CNINFO] 请求失败: {e}")
        return {"status": "error", "message": f"CNINFO request failed: {e}"}
    if r.status_code != 200:
        return {"status": "error", "message": f"CNINFO HTTP {r.status_code}"}
    try:
        payload = r.json()
    except Exception:  # noqa: BLE001
        return {
            "status": "error",
            "message": "CNINFO 响应非 JSON（疑似页面改版/反爬）",
            "error_category": "structure_changed",
        }
    return _parse_cninfo(payload)


# ── 统一分发 ──


async def handle_filings(action: str, params: dict[str, Any]) -> dict[str, Any]:
    """动作分发（main.py 按 handle_<source> 约定调用）。

    SEC 三动作走 _internal/sec_edgar（含 UA/限流/缓存）；港A 索引在本层直连。
    """
    a = (action or "").upper()
    if a in _SEC_ACTIONS:
        return await _handle_sec(a, params)
    if a == "HKEX_FILINGS":
        return await _get_hkex_filings(
            code=params.get("code"),
            date_from=params.get("date_from"),
            date_to=params.get("date_to"),
            limit=int(params.get("limit") or 50),
        )
    if a == "CNINFO_FILINGS":
        return await _get_cninfo_filings(
            code=str(params.get("code") or ""),
            org_id=params.get("org_id"),
            column=str(params.get("column") or "szse"),
            date_from=params.get("date_from"),
            date_to=params.get("date_to"),
            page=int(params.get("page") or 1),
            page_size=int(params.get("page_size") or 30),
            keyword=str(params.get("keyword") or ""),
        )
    logger.warning(f"⚠️ [Filings] 未知动作: {action}")
    return {"status": "error", "message": f"unknown filings action: {action}", "error_category": "bad_request"}


async def startup() -> None:
    logger.info("[Filings-worker] 初始化完成 (SEC EDGAR / HKEXnews / CNINFO 客户端就绪)")
