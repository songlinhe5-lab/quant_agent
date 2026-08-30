"""临时冒烟：验证 FMP 下沉子服务 + /metrics 指标暴露（无网络，本地直跑）。"""

import hashlib
import hmac
import json
import os
import time
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import data_subservice.main as _main_mod

# 自包含 HMAC 密钥，避免受其他测试 fixture 对 main.HMAC_SECRET 全局变量的污染
_FMP_HMAC_SECRET = "test-fmp-subservice-secret"


@pytest.fixture
def client():
    """注入测试用 HMAC 密钥，确保服务端校验与测试签名使用同一密钥（自包含）。"""
    with patch.dict(os.environ, {"DATA_SOURCE_HMAC_SECRET": _FMP_HMAC_SECRET}):
        _main_mod.HMAC_SECRET = _FMP_HMAC_SECRET
        yield TestClient(_main_mod.app)


def _signed_post(client, payload: dict):
    """带 HMAC 签名头调用 /api/v1/data（子服务强制鉴权）。

    签名消息必须用与 request.body() 完全一致的原始 JSON 字节（TestClient 用
    json.dumps 默认 separators 序列化），故此处手动 dumps 作为 content 发送。
    """
    raw = json.dumps(payload).encode("utf-8")
    ts = str(int(time.time()))
    msg = f"{ts}:{raw.decode('utf-8')}".encode("utf-8")
    sig = hmac.new(_FMP_HMAC_SECRET.encode(), msg, hashlib.sha256).hexdigest()
    return client.post(
        "/api/v1/data",
        content=raw,
        headers={"X-Timestamp": ts, "X-Signature": sig},
    )


def test_to_fmp_symbol_us_prefix_stripped():
    # 2026-08-30: US.NVDA 带前缀直接透传给 FMP → profile 402 (NVDA 则 200)。
    # 美股前缀应剥离, 与 HK.00772→0772.HK 同属格式适配。
    from data_subservice.fmp_worker import _to_fmp_symbol

    assert _to_fmp_symbol("US.NVDA") == "NVDA"
    assert _to_fmp_symbol("NVDA") == "NVDA"
    assert _to_fmp_symbol("HK.00772") == "772.HK"
    assert _to_fmp_symbol("SH.600000") == "600000.sh"


def test_fmp_smoke(client):
    # 1. /metrics 暴露 fmp_* 指标（14 个中至少命中核心几个）
    r = client.get("/metrics")
    assert r.status_code == 200, r.status_code
    body = r.text
    for must in (
        "fmp_requests_total",
        "fmp_credit_spent_total",
        "fmp_credit_remaining",
        "fmp_credit_limit",
        "fmp_heal_p99_seconds",
        "fmp_up",
    ):
        assert must in body, f"缺失指标 {must}"
    print("[OK] /metrics 暴露 fmp_* 指标")

    # 2. source=fmp CREDIT action 返回快照
    r = _signed_post(client, {"source": "fmp", "action": "CREDIT", "params": {}})
    assert r.status_code == 200, r.status_code
    data = r.json()
    assert data["code"] == 0, data
    assert data["data"]["status"] == "success", data
    snap = data["data"]["data"]
    assert "remaining" in snap and "daily_limit" in snap, snap
    print(f"[OK] fmp CREDIT 快照: {snap}")

    # 3. 未知 action 优雅返回 error（不崩）
    r = _signed_post(client, {"source": "fmp", "action": "NOPE", "params": {}})
    assert r.status_code == 200, r.status_code
    assert "error" in r.json()["data"], r.json()
    print("[OK] 未知 action 优雅降级")

    print("\n=== FMP 下沉冒烟全部通过 ===")


if __name__ == "__main__":
    import os

    os.environ.setdefault("DATA_SOURCE_HMAC_SECRET", _FMP_HMAC_SECRET)
    _main_mod.HMAC_SECRET = _FMP_HMAC_SECRET
    test_fmp_smoke(TestClient(_main_mod.app))
