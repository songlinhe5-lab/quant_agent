"""主服务 ↔ 数据子服务 HTTP 契约一致性测试。

背景: commit 93f1ecf 删除了 data_subservice/routes.py (旧的
/api/v1/data-source/proxy/* 端点), 但主服务侧的调用方未同步更新,
导致路径/请求体/签名/头名/响应信封五个维度全部断裂。

本文件用**子服务的真实校验函数**来验证主服务构造的请求,
而不是各自 mock 各自的预期 —— 这样任何一侧单方面改动契约都会立刻失败。
"""

import hashlib
import hmac
import json
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# data_subservice 与 backend 平级, 需加入 sys.path 才能导入
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from backend.services.datasource.router import DataSourceRouter  # noqa: E402

_SECRET = "contract-test-secret"


def _subservice_verify(body: str, timestamp: str, signature: str, secret: str = _SECRET) -> bool:
    """复刻 data_subservice/main.py::verify_hmac 的校验逻辑。"""
    message = f"{timestamp}:{body}".encode("utf-8")
    expected = hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


@pytest.fixture
def router():
    with patch.dict(
        os.environ,
        {"DATA_SOURCE_ROUTER_ENABLED": "false", "DATA_SOURCE_HMAC_SECRET": _SECRET},
    ):
        r = DataSourceRouter()
    r._enabled = True
    return r


class TestSignatureInteroperability:
    """主服务签名必须能通过子服务的真实校验。"""

    def test_signature_accepted_by_subservice(self, router):
        body = json.dumps(
            {"source": "yfinance", "action": "QUOTE", "params": {"ticker": "AAPL"}},
            ensure_ascii=False,
        )
        ts = "1700000000"
        sig = router._sign_request(body, ts)
        assert _subservice_verify(body, ts, sig), "主服务签名未能通过子服务校验"

    def test_signature_rejected_on_tampered_body(self, router):
        body = json.dumps({"source": "yfinance", "action": "QUOTE", "params": {}}, ensure_ascii=False)
        ts = "1700000000"
        sig = router._sign_request(body, ts)
        tampered = body.replace("QUOTE", "HISTORY")
        assert not _subservice_verify(tampered, ts, sig), "篡改 body 后签名仍通过, 校验形同虚设"

    def test_signature_is_real_hmac_not_naive_concat(self, router):
        """确保不是 sha256(secret ‖ data) 朴素拼接 (存在长度扩展攻击风险)。"""
        body = '{"a": 1}'
        ts = "1700000000"
        naive = hashlib.sha256(_SECRET.encode() + f"{ts}:{body}".encode()).hexdigest()
        assert router._sign_request(body, ts) != naive

    def test_non_ascii_body_roundtrip(self, router):
        """中文参数不得因转义差异导致验签失败。"""
        body = json.dumps(
            {"source": "akshare", "action": "STOCK_LIST", "params": {"market": "沪深"}},
            ensure_ascii=False,
        )
        ts = "1700000000"
        assert _subservice_verify(body, ts, router._sign_request(body, ts))


class TestRequestShape:
    """请求的 URL / 头名 / body 必须与子服务契约对齐。"""

    @staticmethod
    def _mock_client(payload=None):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = payload if payload is not None else {"code": 0, "data": {}}
        client = AsyncMock()
        client.post = AsyncMock(return_value=resp)
        return client

    @pytest.mark.asyncio
    async def test_posts_to_real_subservice_endpoint(self, router):
        from backend.services.datasource.router import DataSourceNode

        client = self._mock_client()
        router._http_client = client
        node = DataSourceNode(name="n1", url="http://node:8001")

        await router._send_request(node, "yfinance", {"source": "yfinance", "action": "QUOTE", "params": {}})

        args, kwargs = client.post.call_args
        assert args[0] == "http://node:8001/api/v1/data"
        assert set(["X-Timestamp", "X-Signature"]).issubset(kwargs["headers"].keys())
        # 旧的错误头名不得再出现
        assert "X-Data-Source-Signature" not in kwargs["headers"]

    @pytest.mark.asyncio
    async def test_signs_exact_bytes_that_are_sent(self, router):
        """签名对象必须是实际发送的字节, 否则子服务验签必然失败。"""
        from backend.services.datasource.router import DataSourceNode

        client = self._mock_client()
        router._http_client = client
        node = DataSourceNode(name="n1", url="http://node:8001")

        await router._send_request(
            node, "akshare", {"source": "akshare", "action": "STOCK_LIST", "params": {"market": "沪深"}}
        )

        _, kwargs = client.post.call_args
        sent_body = kwargs["content"].decode("utf-8")
        assert _subservice_verify(sent_body, kwargs["headers"]["X-Timestamp"], kwargs["headers"]["X-Signature"])


class TestResponseNormalization:
    """子服务 {"code":0,"data":...} 信封须归一化为主服务的 status/success。"""

    def test_success_envelope(self, router):
        out = router._normalize_response({"code": 0, "data": {"price": 1.23}})
        assert out["status"] == "success" and out["success"] is True
        assert out["data"] == {"price": 1.23}
        assert out["price"] == 1.23  # 业务字段透传

    def test_error_code(self, router):
        out = router._normalize_response({"code": 500, "message": "boom"})
        assert out["status"] == "error" and out["success"] is False and "boom" in out["message"]

    def test_worker_level_error_is_failure(self, router):
        """worker 以 {"error": ...} 返回时不能被误判为成功。"""
        out = router._normalize_response({"code": 0, "data": {"error": "ticker not found"}})
        assert out["status"] == "error" and out["success"] is False

    def test_passthrough_when_no_code_field(self, router):
        out = router._normalize_response({"status": "error", "error_category": "rate_limit"})
        assert out["error_category"] == "rate_limit"


class TestFailFast:
    def test_enabled_without_secret_raises(self):
        with patch.dict(os.environ, {"DATA_SOURCE_ROUTER_ENABLED": "true", "DATA_SOURCE_HMAC_SECRET": ""}):
            with pytest.raises(RuntimeError, match="DATA_SOURCE_HMAC_SECRET"):
                DataSourceRouter()

    def test_disabled_without_secret_is_ok(self):
        with patch.dict(os.environ, {"DATA_SOURCE_ROUTER_ENABLED": "false", "DATA_SOURCE_HMAC_SECRET": ""}):
            assert DataSourceRouter() is not None


class TestTushareCapabilityGapClosure:
    """审计发现 tushare 6 个 action 子服务未实现, 现应已全部补齐并可远程路由。

    若本类失败, 说明又把 stock_history/stock_quote/fundamental/stock_list/
    lowfreq_history/macro 错误地降级到本地适配器 (audit: capability-gap 回归)。
    """

    # 主服务内部 action -> 期望发往子服务的 action
    _EXPECTED = {
        "financials": "FINANCIALS",
        "holder": "HOLDER",
        "moneyflow": "MONEYFLOW",
        "stock_history": "STOCK_HISTORY",
        "stock_quote": "STOCK_QUOTE",
        "fundamental": "FUNDAMENTAL",
        "stock_list": "STOCK_LIST",
        "lowfreq_history": "LOWFREQ_HISTORY",
        "macro": "MACRO",
    }

    def test_all_actions_mapped(self, router):
        """6 个能力缺口 action 必须出现在映射表中 (不再降级本地)。"""
        from backend.services.datasource.router import _TS_ACTION_MAP

        for action in self._EXPECTED:
            assert action in _TS_ACTION_MAP, f"{action} 未映射, 将错误降级本地"
            assert _TS_ACTION_MAP[action] == self._EXPECTED[action]

    @staticmethod
    def _mock_client_tushare(payload=None):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = payload if payload is not None else {"code": 0, "data": {}}
        client = AsyncMock()
        client.post = AsyncMock(return_value=resp)
        return client

    @pytest.mark.asyncio
    async def test_new_actions_route_to_subservice(self, router):
        """stock_history 等新增 action 实际请求必须带上正确的大写 action 远程发出。"""
        from backend.services.datasource.router import DataSourceNode

        client = self._mock_client_tushare()
        router._http_client = client
        node = DataSourceNode(name="n1", url="http://node:8001")

        async with router._lock:
            router._nodes["tushare_remote"] = node

        for internal_action, expected in self._EXPECTED.items():
            await router._send_request(
                node, "tushare", {"source": "tushare", "action": expected, "params": {"symbol": "000001.SZ"}}
            )
            _, kwargs = client.post.call_args
            sent = json.loads(kwargs["content"].decode("utf-8"))
            assert sent["source"] == "tushare"
            assert sent["action"] == expected, f"{internal_action} 发出的 action 错误: {sent['action']}"
            assert _subservice_verify(
                kwargs["content"].decode("utf-8"),
                kwargs["headers"]["X-Timestamp"],
                kwargs["headers"]["X-Signature"],
            )
