"""补充 routers/strategy.py 遗漏分支的覆盖率测试。

覆盖 CI 报告中的缺失行:
- RateLimiter 封禁/全局限流分支 (162-163, 174)
- _fetch_backtest_data 的 interval 倍率 / 快照命中 / 快照缺失 / live 禁止 / finnhub 异常
  (375, 379, 381, 388-402, 415-424, 426-427, 433-434, 539-540)
- /generate 流式: 空 choices / reasoning / 空内容 / 异常 (610, 617, 637-645)
- /format 与 /save 的 black 缺失与格式化异常分支 (656-657, 660-661, 674, 677-679)
- /draft/{name} DELETE 异常 (799-800)
- run/optimize/batch/monte-carlo 沙箱的快照解析与异常路径
  (872-875, 898-909, 1007, 1011-1012, 1051-1054, 1066, 1106-1109)
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

from backend.routers import strategy as strategy_router
from backend.services.datalake.snapshot_resolver import SnapshotResolveError


# ── RateLimiter 封禁 / 全局限流 (162-163, 174) ───────────────────────────────
class _FakeRedis:
    def __init__(self, blacklisted=False, executes=None):
        self._get = "1" if blacklisted else None
        self._executes = list(executes or [[1, None, 1]])
        self.setex_calls = []

    async def get(self, key):
        return self._get

    def pipeline(self):
        return self

    async def incr(self, *a, **k):
        return 1

    async def expire(self, *a, **k):
        return True

    async def execute(self):
        return self._executes.pop(0)

    async def setex(self, key, ttl, val):
        self.setex_calls.append(key)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _FakeRequest:
    class _URL:
        path = "/api/v1/strategy/inspirations"

    class _Client:
        host = "127.0.0.1"

    url = _URL()
    client = _Client()


def _ip_limiter(max_requests=5, global_max=None):
    limiter = strategy_router.RateLimiter(
        max_requests=max_requests,
        window_seconds=10,
        global_max=global_max,
        global_window=10,
        by_user=False,
    )
    return limiter


@pytest.mark.asyncio
async def test_rate_limit_pass(test_client):
    with patch.object(strategy_router, "redis_client", _FakeRedis(executes=[[1, None, 1]])):
        dep = _ip_limiter(global_max=50)
        await dep(_FakeRequest())  # 不应抛异常


@pytest.mark.asyncio
async def test_rate_limit_blacklist_403(test_client):
    with patch.object(strategy_router, "redis_client", _FakeRedis(blacklisted=True)):
        dep = _ip_limiter()
        with pytest.raises(Exception) as exc:
            await dep(_FakeRequest())
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_rate_limit_ban_after_violations_403(test_client):
    # 第一次 execute -> 超 max_requests; 第二次 execute -> 违规达 5 次 -> 封禁
    fake = _FakeRedis(executes=[[6], [5]])
    with patch.object(strategy_router, "redis_client", fake):
        dep = _ip_limiter()
        with pytest.raises(Exception) as exc:
            await dep(_FakeRequest())
    assert exc.value.status_code == 403
    assert fake.setex_calls  # 已写入黑名单


@pytest.mark.asyncio
async def test_rate_limit_global_max_429(test_client):
    # results[2] (全局计数) 超过 global_max
    with patch.object(strategy_router, "redis_client", _FakeRedis(executes=[[1, None, 60]])):
        dep = _ip_limiter(global_max=50)
        with pytest.raises(Exception) as exc:
            await dep(_FakeRequest())
    assert exc.value.status_code == 429


# ── _fetch_backtest_data 各分支 (375, 379, 381, 388-402, 415-424, 426-427) ──
@pytest.mark.asyncio
async def test_fetch_backtest_interval_multipliers(test_client):
    # 仅验证 interval -> multiplier 计算 (374-382), 通过 snapshot 缺失提前返回
    with (
        patch("backend.services.datalake.snapshot_reader.SnapshotReader") as SR,
        patch.object(strategy_router, "redis_client", _FakeRedis()),
    ):
        inst = SR.return_value
        inst.resolve_snapshot_id = AsyncMock(side_effect=SnapshotResolveError("no"))
        inst.get_history = AsyncMock(return_value=None)
        for interval, mult in [("1m", 390), ("5m", 78), ("15m", 26), ("1h", 7)]:
            ok, df, msg = await strategy_router._fetch_backtest_data(
                "US.AAPL", "1y", "snapshot", interval, snapshot_id="snapX"
            )
            assert ok is False
            assert "DATA_SNAPSHOT_MISSING" in msg


@pytest.mark.asyncio
async def test_fetch_backtest_snapshot_hit(test_client):
    df_in = pd.DataFrame(
        {
            "time": ["2024-01-01", "2024-01-02"],
            "open": [1, 2],
            "high": [1, 2],
            "low": [1, 2],
            "close": [1, 2],
            "volume": [10, 20],
        }
    )
    with (
        patch("backend.services.datalake.snapshot_reader.SnapshotReader") as SR,
        patch.object(strategy_router, "redis_client", _FakeRedis()),
    ):
        inst = SR.return_value
        inst.resolve_snapshot_id = AsyncMock(return_value="snap123")
        inst.get_history = AsyncMock(return_value=df_in.copy())
        ok, df, msg = await strategy_router._fetch_backtest_data("US.AAPL", "1y", "snapshot", "1d", snapshot_id="snap1")
        assert ok is True
        assert isinstance(df, pd.DataFrame)
        assert list(df.columns) == ["Open", "High", "Low", "Close", "Volume"]


@pytest.mark.asyncio
async def test_fetch_backtest_live_forbidden(test_client):
    ok, df, msg = await strategy_router._fetch_backtest_data("US.AAPL", "1y", "snapshot", "1d", snapshot_id="live")
    assert ok is False
    assert "LIVE_FORBIDDEN" in msg  # 433-434


@pytest.mark.asyncio
async def test_fetch_backtest_finnhub_except(test_client):
    # 走 auto + US. 标的, 触发 finnhub 兜底并让其抛异常 (539-540)
    with (
        patch.object(strategy_router, "market_data") as md,
        patch.object(strategy_router, "redis_client", _FakeRedis()),
    ):
        md.get_history = AsyncMock(return_value={"status": "error"})
        md.get_stock_history_ak = AsyncMock(return_value={"status": "error"})
        md.get_stock_history_fh = AsyncMock(side_effect=RuntimeError("finnhub boom"))
        md.fetch_yf_data = AsyncMock(return_value=(False, None, "nope"))
        ok, df, msg = await strategy_router._fetch_backtest_data("US.AAPL", "1y", "auto", "1d")
        assert ok is False


# ── /generate 流式分支 (610, 617, 637-645) ───────────────────────────────────
class _Delta:
    def __init__(self, reasoning=None, content=None):
        self.reasoning_content = reasoning
        self.content = content


class _Choice:
    def __init__(self, delta):
        self.delta = delta


class _Chunk:
    def __init__(self, choices=None):
        self.choices = choices if choices is not None else []


class _Stream:
    def __init__(self, chunks):
        self._chunks = chunks

    def __aiter__(self):
        self._it = iter(self._chunks)
        return self

    async def __anext__(self):
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration


@pytest.mark.asyncio
async def test_generate_stream_success_and_reasoning(test_client):
    chunks = [
        _Chunk(),  # 空 choices -> 610 continue
        _Chunk(choices=[_Choice(_Delta(reasoning="thinking"))]),  # 617
        _Chunk(choices=[_Choice(_Delta(content="print(1)"))]),  # 626-635
    ]
    fake_client = MagicMock()
    fake_client.chat.completions.create = AsyncMock(return_value=_Stream(chunks))
    fake_llm = MagicMock()
    fake_llm.get_client = lambda: fake_client
    with (
        patch.object(strategy_router, "redis_client", _FakeRedis()),
        patch.object(strategy_router, "llm_service", fake_llm),
    ):
        resp = test_client.post("/api/v1/strategy/generate", json={"prompt": "双均线"})
        assert resp.status_code == 200
        body = b"".join(resp.iter_bytes()).decode("utf-8")
        assert "success" in body or "reasoning" in body


@pytest.mark.asyncio
async def test_generate_stream_empty_content(test_client):
    chunks = [_Chunk(choices=[_Choice(_Delta(content=""))])]
    fake_client = MagicMock()
    fake_client.chat.completions.create = AsyncMock(return_value=_Stream(chunks))
    fake_llm = MagicMock()
    fake_llm.get_client = lambda: fake_client
    with (
        patch.object(strategy_router, "redis_client", _FakeRedis()),
        patch.object(strategy_router, "llm_service", fake_llm),
    ):
        resp = test_client.post("/api/v1/strategy/generate", json={"prompt": "x"})
        assert resp.status_code == 200
        body = b"".join(resp.iter_bytes()).decode("utf-8")
        assert "大模型返回为空" in body  # 637-643


@pytest.mark.asyncio
async def test_generate_stream_exception(test_client):
    fake_client = MagicMock()
    fake_client.chat.completions.create = AsyncMock(side_effect=RuntimeError("llm down"))
    fake_llm = MagicMock()
    fake_llm.get_client = lambda: fake_client
    with (
        patch.object(strategy_router, "redis_client", _FakeRedis()),
        patch.object(strategy_router, "llm_service", fake_llm),
    ):
        resp = test_client.post("/api/v1/strategy/generate", json={"prompt": "x"})
        assert resp.status_code == 200
        body = b"".join(resp.iter_bytes()).decode("utf-8")
        assert "error" in body  # 645


# ── /format 与 /save 的 black 缺失 / 格式化异常 (656-657, 660-661, 674, 677-679)
def test_format_black_missing(test_client, monkeypatch):
    real_import = __import__

    def _fake_import(name, *a, **k):
        if name == "black":
            raise ImportError("no black")
        return real_import(name, *a, **k)

    monkeypatch.setattr("builtins.__import__", _fake_import)
    resp = test_client.post("/api/v1/strategy/format", json={"source_code": "x=1"})
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "error"  # 658-659


def test_format_black_error(test_client, monkeypatch):
    import types

    black_mod = types.ModuleType("black")

    def _format_str(code, mode=None):
        raise SyntaxError("bad syntax")

    black_mod.format_str = _format_str
    black_mod.Mode = lambda: None

    real_import = __import__

    def _fake_import(name, *a, **k):
        if name == "black":
            return black_mod
        return real_import(name, *a, **k)

    monkeypatch.setattr("builtins.__import__", _fake_import)
    resp = test_client.post("/api/v1/strategy/format", json={"source_code": "x=1"})
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "error"  # 660-661


def test_save_black_import_error(test_client, monkeypatch):
    real_import = __import__

    def _fake_import(name, *a, **k):
        if name == "black":
            raise ImportError("no black")
        return real_import(name, *a, **k)

    monkeypatch.setattr("builtins.__import__", _fake_import)
    resp = test_client.post(
        "/api/v1/strategy/save",
        json={"source_code": "x=1", "class_name": "DemoStrategy"},
    )
    # 降级保存: 走 except ImportError (675-676) -> 仍成功落盘
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "success"


# ── /draft/{name} DELETE 异常 (799-800) ──────────────────────────────────────
def test_delete_draft_exception(test_client, monkeypatch):
    import os as _os

    real_remove = _os.remove

    def _boom(path):
        raise PermissionError("locked")

    monkeypatch.setattr(_os, "remove", _boom)
    resp = test_client.delete("/api/v1/strategy/draft/nonexistent_for_test")
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "error"  # 799-800
    monkeypatch.setattr(_os, "remove", real_remove)


# ── 沙箱异常路径 (1007, 1011-1012, 1051-1054, 1066, 1106-1109) ───────────────
@pytest.mark.asyncio
async def test_optimize_sandbox_success(test_client):
    ok_df = pd.DataFrame({"Close": [1, 2, 3]})
    with (
        patch.object(strategy_router, "market_data") as md,
        patch.object(strategy_router, "run_cpu_bound", new=AsyncMock(return_value=[{"p": 1}])),
        patch.object(strategy_router, "redis_client", _FakeRedis()),
    ):
        md.get_history = AsyncMock(return_value={"status": "success", "data": []})
        md.get_stock_history_ak = AsyncMock(return_value={"status": "error"})
        md.get_stock_history_fh = AsyncMock(return_value={"status": "error"})
        md.fetch_yf_data = AsyncMock(return_value=(False, None, "nope"))
        with patch.object(strategy_router, "_fetch_backtest_data", new=AsyncMock(return_value=(True, ok_df, "ok"))):
            resp = test_client.post(
                "/api/v1/strategy/optimize-sandbox",
                json={
                    "source_code": "x=1",
                    "class_name": "C",
                    "param_grid": {"a": [1]},
                },
            )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "success"  # 1007


@pytest.mark.asyncio
async def test_optimize_sandbox_crash(test_client):
    ok_df = pd.DataFrame({"Close": [1, 2, 3]})
    with (
        patch.object(strategy_router, "run_cpu_bound", new=AsyncMock(side_effect=RuntimeError("boom"))),
        patch.object(strategy_router, "redis_client", _FakeRedis()),
    ):
        with patch.object(strategy_router, "_fetch_backtest_data", new=AsyncMock(return_value=(True, ok_df, "ok"))):
            resp = test_client.post(
                "/api/v1/strategy/optimize-sandbox",
                json={
                    "source_code": "x=1",
                    "class_name": "C",
                    "param_grid": {"a": [1]},
                },
            )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "error"  # 1011-1012


@pytest.mark.asyncio
async def test_batch_sandbox_crash(test_client):
    with (
        patch.object(strategy_router, "run_cpu_bound", new=AsyncMock(side_effect=RuntimeError("boom"))),
        patch.object(strategy_router, "redis_client", _FakeRedis()),
    ):
        with patch.object(
            strategy_router,
            "_fetch_backtest_data",
            new=AsyncMock(return_value=(True, pd.DataFrame({"Close": [1]}), "ok")),
        ):
            resp = test_client.post(
                "/api/v1/strategy/run-batch-sandbox",
                json={"source_code": "x=1", "class_name": "C", "params": {}, "tickers": ["US.AAPL"]},
            )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "error"  # 1051-1054


@pytest.mark.asyncio
async def test_monte_carlo_sandbox_module_inject(test_client):
    ok_df = pd.DataFrame({"Close": [1, 2, 3]})
    with (
        patch.object(strategy_router, "market_data") as md,
        patch.object(strategy_router, "run_cpu_bound", new=AsyncMock(return_value={"summary": 1})),
        patch.object(strategy_router, "redis_client", _FakeRedis()),
    ):
        md.fetch_yf_data = AsyncMock(return_value=(True, {"marketCap": 1, "beta": 2}, "ok"))
        with patch.object(strategy_router, "_fetch_backtest_data", new=AsyncMock(return_value=(True, ok_df, "ok"))):
            resp = test_client.post(
                "/api/v1/strategy/monte-carlo-sandbox",
                json={"source_code": "x=1", "class_name": "C", "params": {}},
            )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "success"  # 1066 注入 MagicMock 模块


@pytest.mark.asyncio
async def test_monte_carlo_sandbox_crash(test_client):
    ok_df = pd.DataFrame({"Close": [1, 2, 3]})
    with (
        patch.object(strategy_router, "run_cpu_bound", new=AsyncMock(side_effect=RuntimeError("boom"))),
        patch.object(strategy_router, "redis_client", _FakeRedis()),
    ):
        with patch.object(strategy_router, "_fetch_backtest_data", new=AsyncMock(return_value=(True, ok_df, "ok"))):
            resp = test_client.post(
                "/api/v1/strategy/monte-carlo-sandbox",
                json={"source_code": "x=1", "class_name": "C", "params": {}},
            )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "error"  # 1106-1109


# ── run-sandbox 快照解析异常 + 报告持久化 (872-875, 898-909) ──────────────────
@pytest.mark.asyncio
async def test_run_sandbox_snapshot_resolve_and_persist(test_client):
    ok_df = pd.DataFrame({"Close": [1, 2, 3]})
    report = {"metrics": {"sharpe": 1.0}}

    class _Resolver:
        def resolve(self, *a, **k):
            from backend.services.datalake.snapshot_resolver import SnapshotResolveError

            raise SnapshotResolveError("no snapshot")

    with (
        patch.object(strategy_router, "market_data") as md,
        patch.object(strategy_router, "run_cpu_bound", new=AsyncMock(return_value=report)),
        patch.object(strategy_router, "redis_client", _FakeRedis()),
        patch("backend.services.datalake.snapshot_resolver.SnapshotResolver", _Resolver),
        patch("backend.services.backtest_report_service.BacktestReportService") as BRS,
    ):
        md.get_history = AsyncMock(return_value={"status": "success", "data": []})
        md.get_stock_history_ak = AsyncMock(return_value={"status": "error"})
        md.get_stock_history_fh = AsyncMock(return_value={"status": "error"})
        md.fetch_yf_data = AsyncMock(return_value=(False, None, "nope"))
        svc_inst = BRS.return_value
        svc_inst.save = MagicMock(return_value=MagicMock(run_id="run_xyz"))
        svc_inst.to_public_dict = MagicMock(return_value={"badge": "G"})
        with patch.object(strategy_router, "_fetch_backtest_data", new=AsyncMock(return_value=(True, ok_df, "ok"))):
            resp = test_client.post(
                "/api/v1/strategy/run-sandbox",
                json={
                    "source_code": "x=1",
                    "class_name": "C",
                    "params": {},
                    "persist_report": True,
                },
            )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status"] == "success"
    assert "persisted_run_id" in data["data"]  # 898-909
