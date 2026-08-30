"""Filings worker 单测（FIN-01）— mock httpx，禁打真实外网。

覆盖：五动作分发 / SEC 委托 / HKEX·CNINFO fixture 结构锁解析 /
页面改版（HTML/缺键）显式失败 / 未知动作。
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import data_subservice.filings_worker as fw

_FIXTURES = Path(__file__).parent / "fixtures" / "filings"


def _load(name: str):
    return json.loads((_FIXTURES / name).read_text(encoding="utf-8"))


class _Resp:
    def __init__(self, status_code=200, payload=None, text=None):
        self.status_code = status_code
        self._payload = payload
        self.text = text if text is not None else (json.dumps(payload) if payload is not None else "")

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


def _client(resp=None, raise_exc=None):
    client = MagicMock()
    captured = {}

    async def get(url, params=None, headers=None):
        captured["url"] = url
        captured["params"] = params
        captured["headers"] = headers
        if raise_exc:
            raise raise_exc
        return resp

    async def post(url, data=None, headers=None):
        captured["url"] = url
        captured["data"] = data
        captured["headers"] = headers
        if raise_exc:
            raise raise_exc
        return resp

    client.get = get
    client.post = post
    client.captured = captured
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


# ─── 动作分发 ───────────────────────────────────────────────────
class TestDispatch:
    async def test_unknown_action(self):
        out = await fw.handle_filings("NOPE", {})
        assert out["status"] == "error"
        assert "unknown filings action" in out["message"]

    async def test_sec_delegates(self, monkeypatch):
        calls = {}

        async def fake_sub(cik):
            calls["cik"] = cik
            return {"status": "success", "data": {}}

        monkeypatch.setattr(fw.sec_edgar_service, "get_submissions", fake_sub)
        out = await fw.handle_filings("SUBMISSIONS", {"cik": 320193})
        assert out["status"] == "success"
        assert calls["cik"] == 320193

    async def test_frames_delegates(self, monkeypatch):
        seen = {}

        async def fake_frames(tax, concept, measure, frame):
            seen.update(tax=tax, concept=concept, measure=measure, frame=frame)
            return {"status": "success", "data": {}}

        monkeypatch.setattr(fw.sec_edgar_service, "get_frames", fake_frames)
        await fw.handle_filings(
            "FRAMES", {"taxonomy": "us-gaap", "concept": "Assets", "measure": "USD", "frame": "CY2024Q3I"}
        )
        assert seen == {"tax": "us-gaap", "concept": "Assets", "measure": "USD", "frame": "CY2024Q3I"}


# ─── HKEX ───────────────────────────────────────────────────────
# 2026-08-31 实测契约：两步请求（prefix.do JSONP 解析 stockId → titleSearchServlet），
# result 为字符串化 JSON 数组、字段全大写、DATE_TIME 为 DD/MM/YYYY HH:MM。


def _hkex_client(prefix_text=None, servlet_payload=None, servlet_resp=None):
    """按 URL 路由的双响应 mock client。"""
    client = MagicMock()
    captured = {}

    async def get(url, params=None, headers=None):
        captured.setdefault("urls", []).append(url)
        if "prefix.do" in url:
            captured["prefix_params"] = params
            text = (
                prefix_text
                if prefix_text is not None
                else (_FIXTURES / "hkex_prefix.jsonp").read_text(encoding="utf-8")
            )
            return _Resp(200, None, text=text)
        captured["params"] = params
        if servlet_resp is not None:
            return servlet_resp
        return _Resp(200, servlet_payload if servlet_payload is not None else _load("hkex_filings.json"))

    client.get = get
    client.captured = captured
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


class TestHkex:
    async def test_parse_fixture(self):
        client = _hkex_client()
        with patch.object(fw.httpx, "AsyncClient", return_value=client):
            out = await fw.handle_filings("HKEX_FILINGS", {"code": "HK.00772", "limit": 10})
        assert out["status"] == "success"
        items = out["data"]["items"]
        assert len(items) == 2
        assert items[0]["code"] == "00772"
        assert items[0]["filed_at"] == "2026-08-11"  # DD/MM/YYYY → ISO
        assert "INTERIM RESULTS" in items[0]["title"]
        assert items[0]["url"].startswith("https://www1.hkexnews.hk/listedco/")
        assert out["data"]["has_more"] is False
        # 两步流程：prefix 解析出 stockId 后带入 servlet
        assert client.captured["params"]["stockId"] == "165872"
        assert client.captured["params"]["stockCode"] == "00772"

    async def test_date_params_yyyymmdd(self):
        client = _hkex_client()
        with patch.object(fw.httpx, "AsyncClient", return_value=client):
            await fw.handle_filings(
                "HKEX_FILINGS", {"code": "00772", "date_from": "2026-07-15", "date_to": "2026-08-31"}
            )
        # 实测：fromDate/toDate 必须 YYYYMMDD，否则被静默忽略（返回全量旧数据）
        assert client.captured["params"]["fromDate"] == "20260715"
        assert client.captured["params"]["toDate"] == "20260831"

    async def test_stock_id_resolution_failure(self):
        client = _hkex_client(prefix_text='cb({"stockInfo":[]});')
        with patch.object(fw.httpx, "AsyncClient", return_value=client):
            out = await fw.handle_filings("HKEX_FILINGS", {"code": "99999"})
        assert out["status"] == "error"
        assert out["error_category"] == "not_found"

    async def test_null_result_means_empty_not_revamp(self):
        # 实测：无记录时 result 为 "null" 或 "[]" 字符串 → 空结果而非结构改版
        for empty in ("null", "[]"):
            client = _hkex_client(servlet_payload={"result": empty, "hasNextRow": False, "recordCnt": 0})
            with patch.object(fw.httpx, "AsyncClient", return_value=client):
                out = await fw.handle_filings("HKEX_FILINGS", {"code": "00772"})
            assert out["status"] == "success"
            assert out["data"]["items"] == []
            assert out["data"]["has_more"] is False

    async def test_result_non_list_still_fails(self):
        # result 键存在但既非列表也非空表示法 → 真结构改版，显式失败
        client = _hkex_client(servlet_payload={"result": {"unexpected": 1}})
        with patch.object(fw.httpx, "AsyncClient", return_value=client):
            out = await fw.handle_filings("HKEX_FILINGS", {"code": "00772"})
        assert out["error_category"] == "structure_changed"

    async def test_structure_changed_missing_result(self):
        client = _hkex_client(servlet_payload={"foo": 1})
        with patch.object(fw.httpx, "AsyncClient", return_value=client):
            out = await fw.handle_filings("HKEX_FILINGS", {"code": "00772"})
        assert out["error_category"] == "structure_changed"

    async def test_html_page_means_revamp(self):
        # 页面改版/反爬常返回 HTML：json() 抛错 → 必须显式失败，禁止静默拉空
        client = _hkex_client(servlet_resp=_Resp(200, None))
        with patch.object(fw.httpx, "AsyncClient", return_value=client):
            out = await fw.handle_filings("HKEX_FILINGS", {"code": "00772"})
        assert out["error_category"] == "structure_changed"

    async def test_http_error(self):
        client = _hkex_client(servlet_resp=_Resp(500))
        with patch.object(fw.httpx, "AsyncClient", return_value=client):
            out = await fw.handle_filings("HKEX_FILINGS", {"code": "00772"})
        assert out["status"] == "error"
        assert "500" in out["message"]

    async def test_network_exception(self):
        client = _hkex_client()

        async def boom(url, params=None, headers=None):
            raise ConnectionError("timeout")

        client.get = boom
        with patch.object(fw.httpx, "AsyncClient", return_value=client):
            out = await fw.handle_filings("HKEX_FILINGS", {"code": "00772"})
        assert out["status"] == "error"
        assert "timeout" in out["message"]


# ─── CNINFO ─────────────────────────────────────────────────────
class TestCninfo:
    async def test_parse_fixture(self):
        client = _client(_Resp(200, _load("cninfo_filings.json")))
        with patch.object(fw.httpx, "AsyncClient", return_value=client):
            out = await fw.handle_filings(
                "CNINFO_FILINGS", {"code": "600519", "org_id": "gssh0600519", "column": "sse"}
            )
        assert out["status"] == "success"
        items = out["data"]["items"]
        assert len(items) == 2
        assert items[0]["title"] == "贵州茅台2023年年度报告"
        assert items[0]["filed_at"] == "2024-04-03"  # ms epoch → UTC 日期
        assert items[0]["url"].startswith("http://static.cninfo.com.cn/finalpage/")
        assert out["data"]["total"] == 2
        form = client.captured["data"]
        assert form["stock"] == "600519,gssh0600519"
        assert form["column"] == "sse"

    async def test_requires_code(self):
        out = await fw.handle_filings("CNINFO_FILINGS", {})
        assert out["error_category"] == "bad_request"

    async def test_structure_changed(self):
        client = _client(_Resp(200, {"announcements": None}))
        with patch.object(fw.httpx, "AsyncClient", return_value=client):
            out = await fw.handle_filings("CNINFO_FILINGS", {"code": "600519"})
        assert out["error_category"] == "structure_changed"

    async def test_date_range_param(self):
        client = _client(_Resp(200, _load("cninfo_filings.json")))
        with patch.object(fw.httpx, "AsyncClient", return_value=client):
            await fw.handle_filings(
                "CNINFO_FILINGS", {"code": "600519", "date_from": "2024-01-01", "date_to": "2024-12-31"}
            )
        assert client.captured["data"]["seDate"] == "2024-01-01~2024-12-31"

    async def test_network_exception(self):
        client = _client(None, raise_exc=OSError("refused"))
        with patch.object(fw.httpx, "AsyncClient", return_value=client):
            out = await fw.handle_filings("CNINFO_FILINGS", {"code": "600519"})
        assert out["status"] == "error"
        assert "refused" in out["message"]
