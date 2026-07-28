"""CacheManager 单元测试 (Futu LRU 订阅池 + 数据压缩工具)"""

import time

import pandas as pd

from backend.services.futu.cache_manager import CacheManager, _iv_to_pct


class TestCacheManagerLRU:
    def test_touch_and_has_topic(self):
        cm = CacheManager()
        assert cm.has_topic("HK.00700", "QUOTE") is False
        cm.touch_topic("HK.00700", "QUOTE")
        assert cm.has_topic("HK.00700", "QUOTE") is True

    def test_remove_topic(self):
        cm = CacheManager()
        cm.touch_topic("HK.00700", "QUOTE")
        cm.remove_topic("HK.00700", "QUOTE")
        assert cm.has_topic("HK.00700", "QUOTE") is False

    def test_evict_lru_order(self):
        cm = CacheManager()
        cm.touch_topic("A", "QUOTE")
        cm.touch_topic("B", "QUOTE")
        cm.touch_topic("C", "QUOTE")
        # 再次 touch A, 使其成为最近访问
        cm.touch_topic("A", "QUOTE")
        evicted = cm.evict_lru(2)
        # 最久未用的是 B, C
        assert set(evicted) == {("B", "QUOTE"), ("C", "QUOTE")}

    def test_ensure_capacity_evicts_when_full(self):
        cm = CacheManager()
        cm.max_subscriptions = 2
        cm.touch_topic("A", "QUOTE")
        cm.touch_topic("B", "QUOTE")
        # 需要再 +1 空间, 超出容量 -> 淘汰最久的 A
        evicted = cm.ensure_capacity(needed=1)
        assert evicted == [("A", "QUOTE")]
        assert ("A", "QUOTE") in cm.drain_pending_unsub()

    def test_subscription_count_and_clear(self):
        cm = CacheManager()
        cm.touch_topic("A", "QUOTE")
        cm.touch_topic("B", "QUOTE")
        assert cm.subscription_count == 2
        cm.clear_all_subscriptions()
        assert cm.subscription_count == 0

    def test_drain_pending_unsub(self):
        cm = CacheManager()
        cm._pending_unsub.add(("A", "QUOTE"))
        drained = cm.drain_pending_unsub()
        assert ("A", "QUOTE") in drained
        assert cm.drain_pending_unsub() == set()


class TestCacheManagerStaleEviction:
    def test_evict_stale_cache_removes_expired(self):
        cm = CacheManager()
        now = time.time()
        cm.set_quote_cache("HK.00700", now - 999, {"status": "success", "old": True})
        cm.set_quote_cache("HK.00701", now, {"status": "success", "fresh": True})
        cm.evict_stale_cache()
        assert cm.get_quote_cache("HK.00700") is None
        assert cm.get_quote_cache("HK.00701") is not None


class TestCompressChainData:
    def test_compress_chain_data_maps_columns(self):
        df = pd.DataFrame(
            {
                "code": ["OPT1"],
                "option_type": ["CALL"],
                "strike_price": [100.0],
                "option_implied_volatility": [0.25],
                "option_delta": [0.5],
                "bid_price": [1.0],
                "ask_price": [1.2],
                "volume": [1000],
                "open_interest": [500],
            }
        )
        res = CacheManager.compress_chain_data(df, "2026-01-01")
        assert res["status"] == "success"
        assert res["count"] == 1
        leg = res["calls"][0]
        assert leg["implied_volatility"] == 25.0  # _iv_to_pct: 0.25 -> 25.0
        assert leg["delta"] == 0.5
        assert leg["bid"] == 1.0
        assert leg["ask"] == 1.2

    def test_compress_chain_data_splits_calls_puts(self):
        df = pd.DataFrame(
            {
                "code": ["C1", "P1"],
                "option_type": ["CALL", "PUT"],
                "strike_price": [100.0, 90.0],
            }
        )
        res = CacheManager.compress_chain_data(df, "2026-01-01")
        assert res["count"] == 2
        assert len(res["calls"]) == 1
        assert len(res["puts"]) == 1


class TestCompressQuoteData:
    def test_compress_quote_data_formats(self):
        row = {
            "code": "HK.00700",
            "last_price": 350.0,
            "prev_close_price": 345.0,
            "volume": 1_500_000,
        }
        res = CacheManager.compress_quote_data(row)
        assert res["status"] == "success"
        assert res["last_price"] == 350.0
        assert res["volume_str"] == "1.50M"
        assert res["change_pct"].endswith("%")


class TestIvToPct:
    def test_iv_to_pct_decimal_to_percent(self):
        assert _iv_to_pct(0.25) == 25.0
        assert _iv_to_pct(None) is None

    def test_iv_to_pct_already_percent_kept(self):
        # 超过 3 视为已为百分数
        assert _iv_to_pct(35.0) == 35.0
