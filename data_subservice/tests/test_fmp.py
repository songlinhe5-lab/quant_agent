"""FMPService 单元测试 (credit 配额 / 响应解析 / 耗尽分支)。

底层 httpx.AsyncClient 经 mock 替换, 不触真实 FMP REST。
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from data_subservice._internal import fmp as fmp_mod


@pytest.fixture(autouse=True)
def _reset_credit():
    fmp_mod._credit_spent = 0
    fmp_mod._request_count = 0
    fmp_mod._rate_limit_hits = 0
    yield
    fmp_mod._credit_spent = 0


class TestCreditBudget:
    def test_remaining(self):
        assert fmp_mod._credit_remaining() == fmp_mod._FMP_DAILY_CREDIT

    def test_consume_ok(self):
        assert fmp_mod._consume_credit(1) is True
        assert fmp_mod._credit_spent == 1

    def test_consume_exhausted(self, monkeypatch):
        monkeypatch.setattr(fmp_mod, "_FMP_DAILY_CREDIT", 2)
        assert fmp_mod._consume_credit(1) is True
        # 只剩 1, 再要 2 不足
        assert fmp_mod._consume_credit(2) is False

    def test_maybe_reset_daily_credit(self, monkeypatch):
        fmp_mod._credit_spent = 50
        monkeypatch.setattr("time.strftime", lambda fmt: "2099-01-01")
        fmp_mod._maybe_reset_daily_credit()
        assert fmp_mod._credit_spent == 0


class TestParse:
    def test_200(self):
        resp = MagicMock(status_code=200)
        resp.json.return_value = {"x": 1}
        out = fmp_mod.FMPService()._parse(resp, credit=1)
        assert out["status"] == "success"
        assert out["data"] == {"x": 1}

    def test_429(self):
        resp = MagicMock(status_code=429)
        out = fmp_mod.FMPService()._parse(resp, credit=1)
        assert out["error_category"] == "rate_limit"
        assert fmp_mod._rate_limit_hits == 1

    def test_other_status(self):
        resp = MagicMock(status_code=500)
        out = fmp_mod.FMPService()._parse(resp, credit=1)
        assert out["status"] == "error"
        assert "500" in out["message"]


class TestCreditSnapshot:
    def test_snapshot_keys(self):
        snap = fmp_mod.credit_snapshot()
        assert "daily_limit" in snap
        assert "remaining" in snap
        assert "request_count" in snap


class TestMethodsExhausted:
    @pytest.mark.asyncio
    async def test_get_quote_exhausted(self, monkeypatch):
        monkeypatch.setattr(fmp_mod, "_FMP_DAILY_CREDIT", 0)
        out = await fmp_mod.FMPService().get_quote("AAPL")
        assert out["error_category"] == "quota"

    @pytest.mark.asyncio
    async def test_get_income_exhausted(self, monkeypatch):
        monkeypatch.setattr(fmp_mod, "_FMP_DAILY_CREDIT", 0)
        out = await fmp_mod.FMPService().get_income_statement("AAPL")
        assert out["error_category"] == "quota"


class TestMethodsSuccess:
    @pytest.mark.asyncio
    async def test_get_quote_success(self):
        svc = fmp_mod.FMPService()
        fake_resp = MagicMock(status_code=200)
        fake_resp.json.return_value = [{"price": 1}]
        fake_client = AsyncMock()
        fake_client.__aenter__.return_value.get = AsyncMock(return_value=fake_resp)
        with patch.object(fmp_mod.httpx, "AsyncClient", return_value=fake_client):
            out = await svc.get_quote("AAPL")
        assert out["status"] == "success"
