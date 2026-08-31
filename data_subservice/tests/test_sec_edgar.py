"""SEC EDGAR 客户端单测（FIN-01）— mock httpx，禁打真实外网。

覆盖：CIK 归一化 / UA 合规 / 令牌桶限流 / 三端点 200·429·403·404·异常分支 /
结构锁（structure_changed）/ companyfacts 落盘缓存命中与 TTL 过期。
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import data_subservice._internal.sec_edgar as sec_mod
from data_subservice._internal.sec_edgar import SecEdgarService, TokenBucketLimiter, normalize_cik

_FIXTURES = Path(__file__).parent / "fixtures" / "filings"


def _load(name: str):
    return json.loads((_FIXTURES / name).read_text(encoding="utf-8"))


class _Resp:
    def __init__(self, status_code=200, payload=None, json_exc=None):
        self.status_code = status_code
        self._payload = payload
        self._json_exc = json_exc

    def json(self):
        if self._json_exc:
            raise self._json_exc
        return self._payload


def _client(resp=None, raise_exc=None):
    client = MagicMock()
    captured = {}

    async def get(url, headers=None, params=None):
        captured["url"] = url
        captured["headers"] = headers
        if raise_exc is not None:
            raise raise_exc
        return resp or _Resp(200, {})

    client.get = get
    client.captured = captured
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


@pytest.fixture
def svc():
    s = SecEdgarService()
    # 单测禁真实等待：限流器置为直通
    s._limiter.acquire = AsyncMock()
    return s


# ─── normalize_cik ──────────────────────────────────────────────
class TestNormalizeCik:
    def test_int(self):
        assert normalize_cik(320193) == "0000320193"

    def test_padded_str(self):
        assert normalize_cik("0000320193") == "0000320193"

    def test_entity_id_form(self):
        assert normalize_cik("US:CIK0000320193") == "0000320193"

    def test_cik_prefix_form(self):
        assert normalize_cik("CIK106581") == "0000106581"

    def test_invalid(self):
        out = normalize_cik("abc")
        assert out["status"] == "error"
        assert out["error_category"] == "bad_request"

    def test_zero_invalid(self):
        assert normalize_cik(0)["status"] == "error"


# ─── TokenBucketLimiter ─────────────────────────────────────────
class TestTokenBucketLimiter:
    async def test_allows_burst_up_to_max(self):
        now = [0.0]
        slept = []

        async def fake_sleep(t):
            slept.append(t)
            now[0] += t

        lim = TokenBucketLimiter(3, clock=lambda: now[0], sleep=fake_sleep)
        for _ in range(3):
            await lim.acquire()
        assert slept == []  # 前 3 次直通

    async def test_waits_when_full(self):
        now = [0.0]
        slept = []

        async def fake_sleep(t):
            slept.append(t)
            now[0] += t

        lim = TokenBucketLimiter(2, clock=lambda: now[0], sleep=fake_sleep)
        await lim.acquire()
        now[0] += 0.1
        await lim.acquire()
        now[0] += 0.1  # t=0.2, 窗口内已有 2 次 → 必须等待
        await lim.acquire()
        assert slept and slept[0] > 0.7  # 等 oldest(0.0) 滑出 1s 窗口

    async def test_window_slides(self):
        now = [0.0]

        async def fake_sleep(t):
            now[0] += t

        lim = TokenBucketLimiter(1, clock=lambda: now[0], sleep=fake_sleep)
        await lim.acquire()
        now[0] += 1.5  # 窗口整体滑出
        await lim.acquire()  # 不应触发 sleep


# ─── UA 合规 ────────────────────────────────────────────────────
class TestUserAgent:
    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("SEC_EDGAR_USER_AGENT", "Research Corp research@example.com")
        assert sec_mod._user_agent() == "Research Corp research@example.com"

    def test_default_when_missing(self, monkeypatch):
        monkeypatch.delenv("SEC_EDGAR_USER_AGENT", raising=False)
        ua = sec_mod._user_agent()
        assert "@" in ua  # SEC 要求含联系邮箱


# ─── submissions ────────────────────────────────────────────────
class TestSubmissions:
    async def test_success(self, svc):
        client = _client(_Resp(200, _load("sec_submissions.json")))
        with patch.object(sec_mod.httpx, "AsyncClient", return_value=client):
            out = await svc.get_submissions("320193")
        assert out["status"] == "success"
        assert client.captured["url"].endswith("/submissions/CIK0000320193.json")
        assert "@" in client.captured["headers"]["User-Agent"]

    async def test_bad_cik_no_network(self, svc):
        with patch.object(sec_mod.httpx, "AsyncClient") as ac:
            out = await svc.get_submissions("not-a-cik")
        assert out["status"] == "error"
        ac.assert_not_called()

    async def test_structure_changed(self, svc):
        client = _client(_Resp(200, {"name": "X"}))  # 缺 filings 键
        with patch.object(sec_mod.httpx, "AsyncClient", return_value=client):
            out = await svc.get_submissions(320193)
        assert out["error_category"] == "structure_changed"

    async def test_429_rate_limit_category(self, svc):
        client = _client(_Resp(429))
        with patch.object(sec_mod.httpx, "AsyncClient", return_value=client):
            out = await svc.get_submissions(320193)
        assert out["error_category"] == "rate_limit"

    async def test_403_ip_blocked(self, svc):
        client = _client(_Resp(403))
        with patch.object(sec_mod.httpx, "AsyncClient", return_value=client):
            out = await svc.get_submissions(320193)
        assert out["error_category"] == "ip_blocked"

    async def test_exception(self, svc):
        client = _client(raise_exc=ConnectionError("net down"))
        with patch.object(sec_mod.httpx, "AsyncClient", return_value=client):
            out = await svc.get_submissions(320193)
        assert out["status"] == "error"
        assert "net down" in out["message"]


# ─── companyfacts + 缓存 ────────────────────────────────────────
class TestCompanyFacts:
    async def test_cold_fetch_writes_cache(self, svc, tmp_path, monkeypatch):
        monkeypatch.setenv("SEC_CACHE_DIR", str(tmp_path))
        client = _client(_Resp(200, _load("sec_companyfacts.json")))
        with patch.object(sec_mod.httpx, "AsyncClient", return_value=client):
            out = await svc.get_company_facts(320193)
        assert out["status"] == "success"
        assert not out.get("cached")
        assert (tmp_path / "companyfacts_CIK0000320193.json").is_file()

    async def test_cache_hit_skips_network(self, svc, tmp_path, monkeypatch):
        monkeypatch.setenv("SEC_CACHE_DIR", str(tmp_path))
        client = _client(_Resp(200, _load("sec_companyfacts.json")))
        with patch.object(sec_mod.httpx, "AsyncClient", return_value=client):
            await svc.get_company_facts(320193)
        # 第二次：新 client 若被调用即失败
        boom = _client(raise_exc=AssertionError("不应再打网络"))
        with patch.object(sec_mod.httpx, "AsyncClient", return_value=boom):
            out = await svc.get_company_facts(320193)
        assert out["cached"] is True
        assert "facts" in out["data"]

    async def test_cache_ttl_expiry(self, svc, tmp_path, monkeypatch):
        monkeypatch.setenv("SEC_CACHE_DIR", str(tmp_path))
        monkeypatch.setenv("SEC_COMPANYFACTS_TTL_SEC", "0")  # 立即过期
        client = _client(_Resp(200, _load("sec_companyfacts.json")))
        with patch.object(sec_mod.httpx, "AsyncClient", return_value=client):
            await svc.get_company_facts(320193)
            out = await svc.get_company_facts(320193)
        assert not out.get("cached")  # TTL=0 → 缓存永不命中

    async def test_structure_changed(self, svc, tmp_path, monkeypatch):
        monkeypatch.setenv("SEC_CACHE_DIR", str(tmp_path))
        client = _client(_Resp(200, {"cik": 1}))  # 缺 facts 键
        with patch.object(sec_mod.httpx, "AsyncClient", return_value=client):
            out = await svc.get_company_facts(320193)
        assert out["error_category"] == "structure_changed"

    async def test_use_cache_false_bypasses(self, svc, tmp_path, monkeypatch):
        monkeypatch.setenv("SEC_CACHE_DIR", str(tmp_path))
        client = _client(_Resp(200, _load("sec_companyfacts.json")))
        with patch.object(sec_mod.httpx, "AsyncClient", return_value=client):
            await svc.get_company_facts(320193)
            out = await svc.get_company_facts(320193, use_cache=False)
        assert not out.get("cached")


# ─── frames ─────────────────────────────────────────────────────
class TestFrames:
    async def test_success_instant_frame(self, svc):
        client = _client(_Resp(200, _load("sec_frames.json")))
        with patch.object(sec_mod.httpx, "AsyncClient", return_value=client):
            out = await svc.get_frames("us-gaap", "Assets", "USD", "CY2024Q3I")
        assert out["status"] == "success"
        assert client.captured["url"].endswith("/api/xbrl/frames/us-gaap/Assets/USD/CY2024Q3I.json")

    async def test_missing_params(self, svc):
        out = await svc.get_frames("us-gaap", "", "USD", "")
        assert out["error_category"] == "bad_request"

    async def test_404_not_found(self, svc):
        # 时点科目用错后缀（缺 I）→ SEC 404，必须显式 not_found 而非空数据
        client = _client(_Resp(404))
        with patch.object(sec_mod.httpx, "AsyncClient", return_value=client):
            out = await svc.get_frames("us-gaap", "Assets", "USD", "CY2024Q3")
        assert out["error_category"] == "not_found"

    async def test_structure_changed(self, svc):
        client = _client(_Resp(200, {"data": []}))  # 缺 frame 键
        with patch.object(sec_mod.httpx, "AsyncClient", return_value=client):
            out = await svc.get_frames("us-gaap", "Assets", "USD", "CY2024Q3I")
        assert out["error_category"] == "structure_changed"

    async def test_non_json(self, svc):
        client = _client(_Resp(200, None, json_exc=ValueError("not json")))
        with patch.object(sec_mod.httpx, "AsyncClient", return_value=client):
            out = await svc.get_frames("us-gaap", "Assets", "USD", "CY2024Q3I")
        assert out["error_category"] == "bad_response"
