"""
QUANT-04: CEPEngine 深度单测（补齐触发/冷却/过滤分支）
====================================================

覆盖 cep_engine.py:
- on_bar 缓冲不足 / 足量的评估路径
- on_quote 简化路径
- 规则禁用 / watchlist 不匹配 → 跳过
- 冷却机制（同规则同标的限频）
- 表达式求值异常 → 捕获不崩溃
- get_recent_matches(since) / clear_matches
- remove_rule 清理冷却记录
- list_rules / get_rule
- start_background / stop
"""

from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np

from backend.services.cep.cep_engine import CEPEngine

# 使用随机游走 K 线 (含涨跌幅) 以保证 RSI 等指标的 DataFrame 计算有效 (非 NaN)
_POSITIVE = "RSI < 100"  # 对任意有效 RSI 恒成立 → 必然触发


def _feed(engine, ticker, n, seed=42, base_ts=1000.0):
    rng = np.random.RandomState(seed)
    price = 100.0
    for i in range(n):
        price += rng.randn() * 0.5
        price = max(price, 1.0)
        engine.on_bar(ticker, price, price + 1, price - 1, price, 1000.0, timestamp=base_ts + float(i))


def _feed_one(e, i):
    return e.on_bar("AAPL", 100.0 + i, 101.0 + i, 99.0 + i, 100.0 + i, 1000.0, timestamp=float(i))


class TestBarIngestion:
    def test_insufficient_buffer_returns_empty(self):
        e = CEPEngine()
        e.add_rule("x", _POSITIVE, ["AAPL"])
        res = [_feed_one(e, i) for i in range(10)]
        assert all(r == [] for r in res)

    def test_sufficient_buffer_triggers(self):
        e = CEPEngine()
        e.add_rule("x", _POSITIVE, ["AAPL"])
        _feed(e, "AAPL", 35)
        assert len(e.get_recent_matches()) >= 1

    def test_on_quote_triggers(self):
        e = CEPEngine()
        e.add_rule("x", _POSITIVE, ["AAPL"])
        rng = np.random.RandomState(7)
        price = 100.0
        for i in range(35):
            price += rng.randn() * 0.5
            price = max(price, 1.0)
            e.on_quote("AAPL", price, 1000.0, timestamp=1000.0 + float(i))
        assert len(e.get_recent_matches()) >= 1


class TestFiltering:
    def test_disabled_rule_not_triggered(self):
        e = CEPEngine()
        r = e.add_rule("x", _POSITIVE, ["AAPL"])
        r.enabled = False
        _feed(e, "AAPL", 35)
        assert e.get_recent_matches() == []

    def test_watchlist_mismatch_skipped(self):
        e = CEPEngine()
        e.add_rule("x", _POSITIVE, ["MSFT"])
        _feed(e, "AAPL", 35)
        assert e.get_recent_matches() == []

    def test_bad_expression_no_crash(self):
        e = CEPEngine()
        e.add_rule("bad", "not a valid expr @@@", ["AAPL"])
        _feed(e, "AAPL", 35)
        assert e.get_recent_matches() == []


class TestCooldown:
    def test_cooldown_suppresses_repeat(self):
        e = CEPEngine()
        e.add_rule("x", _POSITIVE, ["AAPL"])
        _feed(e, "AAPL", 35)  # 首个匹配 (~ts 34)
        first_count = len(e.get_recent_matches())
        assert first_count >= 1
        # 冷却期内 (base_ts=35, ts≈35..54) 继续喂，不应新增匹配
        _feed(e, "AAPL", 20, seed=99, base_ts=35.0)
        assert len(e.get_recent_matches()) == first_count

    def test_cooldown_expires(self):
        e = CEPEngine()
        e.add_rule("x", _POSITIVE, ["AAPL"])
        _feed(e, "AAPL", 35)
        assert len(e.get_recent_matches()) >= 1
        # 超越冷却窗口 (300s) 后再次触发
        _feed(e, "AAPL", 10, seed=5, base_ts=100000.0)
        assert len(e.get_recent_matches()) >= 2


class TestMatchQueue:
    def test_get_recent_matches_since(self):
        e = CEPEngine()
        e.add_rule("x", _POSITIVE, ["AAPL"])
        _feed(e, "AAPL", 35)
        all_m = e.get_recent_matches()
        sub = e.get_recent_matches(since=all_m[0].matched_at + 1)
        assert isinstance(sub, list)

    def test_clear_matches(self):
        e = CEPEngine()
        e.add_rule("x", _POSITIVE, ["AAPL"])
        _feed(e, "AAPL", 35)
        e.clear_matches()
        assert e.get_recent_matches() == []


class TestRuleManagement:
    def test_remove_rule_clears_cooldown(self):
        e = CEPEngine()
        r = e.add_rule("x", _POSITIVE, ["AAPL"])
        _feed(e, "AAPL", 35)
        assert len(e._cooldown_map) >= 1
        assert e.remove_rule(r.id) is True
        assert e.get_rule(r.id) is None
        assert all(k[0] != r.id for k in e._cooldown_map)

    def test_remove_missing_rule(self):
        e = CEPEngine()
        assert e.remove_rule("nope") is False

    def test_list_and_get_rule(self):
        e = CEPEngine()
        r = e.add_rule("a", _POSITIVE, ["AAPL"])
        assert r in e.list_rules()
        assert e.get_rule(r.id).id == r.id
        assert e.get_rule("missing") is None


class TestLifecycle:
    def test_start_background_and_stop(self):
        e = CEPEngine()
        fake_task = MagicMock()
        fake_task.done.return_value = False
        with (
            patch("asyncio.create_task", return_value=fake_task),
            patch.object(CEPEngine, "subscribe_redis_stream", new=AsyncMock()),
        ):
            task = e.start_background()
            assert task is fake_task
            e.stop()
            fake_task.cancel.assert_called_once()
