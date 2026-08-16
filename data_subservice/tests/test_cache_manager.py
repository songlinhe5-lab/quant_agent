"""CacheManager 单元测试 — 覆盖 LRU 订阅池、缓存增删、压缩工具纯逻辑。"""

import pandas as pd

from data_subservice.futu_src.cache_manager import CacheManager, _iv_to_pct


class TestIvToPct:
    def test_none(self):
        assert _iv_to_pct(None) is None

    def test_decimal_to_pct(self):
        assert _iv_to_pct(0.25) == 25.0

    def test_already_pct_kept(self):
        assert _iv_to_pct(25.0) == 25.0

    def test_rounding(self):
        assert _iv_to_pct(0.3333) == 33.33


class TestLRUSubPool:
    def test_touch_new_and_existing(self):
        cm = CacheManager()
        cm.touch_topic("HK.00700", "QUOTE")
        assert cm.has_topic("HK.00700", "QUOTE") is True
        cm.touch_topic("HK.00700", "QUOTE")  # LRU 提升
        assert ("HK.00700", "QUOTE") in cm.subscribed_topics

    def test_has_topic_refreshes(self):
        cm = CacheManager()
        cm.touch_topic("A", "Q")
        cm.touch_topic("B", "Q")
        # 访问 A 提升, B 成为最久
        assert cm.has_topic("A", "Q") is True
        evicted = cm.evict_lru(1)
        assert evicted == [("B", "Q")]
        assert cm.has_topic("B", "Q") is False

    def test_remove_topic(self):
        cm = CacheManager()
        cm.touch_topic("A", "Q")
        cm.remove_topic("A", "Q")
        assert cm.subscription_count == 0

    def test_ensure_capacity_evicts(self, monkeypatch):
        cm = CacheManager()
        monkeypatch.setattr(cm, "max_subscriptions", 2)
        cm.touch_topic("A", "Q")
        cm.touch_topic("B", "Q")
        evicted = cm.ensure_capacity(needed=1)
        assert evicted == [("A", "Q")]
        # 待退订队列已记录
        assert ("A", "Q") in cm.drain_pending_unsub()

    def test_drain_pending_unsub(self):
        cm = CacheManager()
        cm._pending_unsub.add(("X", "Y"))
        out = cm.drain_pending_unsub()
        assert out == {("X", "Y")}
        assert cm.drain_pending_unsub() == set()

    def test_clear_all_subscriptions(self):
        cm = CacheManager()
        cm.touch_topic("A", "Q")
        cm._pending_unsub.add(("A", "Q"))
        cm.clear_all_subscriptions()
        assert cm.subscription_count == 0
        assert cm.drain_pending_unsub() == set()


class TestEvictStaleCache:
    def test_removes_stale(self, monkeypatch):
        import time

        cm = CacheManager()
        now = time.time()
        cm._quote_cache["old"] = (now - 9999, {"x": 1})
        cm._quote_cache["fresh"] = (now, {"x": 2})
        cm.evict_stale_cache()
        assert "old" not in cm._quote_cache
        assert "fresh" in cm._quote_cache

    def test_capacity_halving(self, monkeypatch):
        import time

        cm = CacheManager()
        now = time.time()
        # 超过 _MAX_CACHE_SIZE (200)，触发清空最旧一半
        for i in range(210):
            cm._fundamental_cache[f"k{i}"] = (now - i, {"v": i})
        cm.evict_stale_cache()
        # 210 -> 一半应被删 (最近 105 留)
        assert len(cm._fundamental_cache) == 105


class TestDataCaches:
    def test_quote_roundtrip(self):
        cm = CacheManager()
        cm.set_quote_cache("HK.00700", 123.0, {"price": 1})
        assert cm.get_quote_cache("HK.00700") == (123.0, {"price": 1})
        assert cm.get_quote_cache("NOPE") is None

    def test_history_roundtrip(self):
        cm = CacheManager()
        cm.set_history_cache("k", 1.0, {"c": 1})
        assert cm.get_history_cache("k")[1]["c"] == 1

    def test_option_chain_roundtrip(self):
        cm = CacheManager()
        cm.set_option_chain_cache("o", 1.0, {"x": 1})
        assert cm.get_option_chain_cache("o") is not None

    def test_fund_flow_roundtrip(self):
        cm = CacheManager()
        cm.set_fund_flow_cache("f", 1.0, {"x": 1})
        assert cm.get_fund_flow_cache("f") is not None

    def test_order_book_roundtrip(self):
        cm = CacheManager()
        cm.set_order_book_cache("b", 1.0, {"x": 1})
        assert cm.get_order_book_cache("b") is not None

    def test_fundamental_roundtrip(self):
        cm = CacheManager()
        cm.set_fundamental_cache("fa", 1.0, {"x": 1})
        assert cm.get_fundamental_cache("fa") is not None


class TestCompressChainData:
    def _df(self):
        return pd.DataFrame(
            [
                {
                    "code": "AAPL2601C100",
                    "option_type": "CALL",
                    "strike_price": 100.0,
                    "option_implied_volatility": 0.25,
                    "option_delta": 0.6,
                    "option_gamma": 0.05,
                    "option_vega": 0.1,
                    "option_theta": -0.02,
                    "bid_price": 1.5,
                    "ask_price": 2.0,
                    "volume": 1000,
                    "open_interest": 500,
                    "expiry_date": "2026-01-15",
                },
                {
                    "code": "AAPL2601P100",
                    "type": "PUT",
                    "strike_price": 100.0,
                    "implied_volatility": 0.30,
                    "delta": 0.4,
                    "gamma": 0.04,
                    "vega": 0.09,
                    "theta": -0.03,
                    "bid": 1.0,
                    "ask": 1.8,
                    "volume": 800,
                    "open_int": 300,
                },
            ]
        )

    def test_calls_and_puts_split(self):
        out = CacheManager.compress_chain_data(self._df(), "2026-01-15")
        assert out["status"] == "success"
        assert out["count"] == 2
        assert len(out["calls"]) == 1
        assert len(out["puts"]) == 1
        assert out["calls"][0]["implied_volatility"] == 25.0  # 0.25 -> 25.0
        assert out["calls"][0]["expiration_date"] == "2026-01-15"
        assert out["puts"][0]["option_type"] == "PUT"

    def test_empty_df(self):
        out = CacheManager.compress_chain_data(pd.DataFrame(), "2026-01-15")
        assert out["count"] == 0
        assert out["options"] == []


class TestCompressQuoteData:
    def test_basic(self):
        row = {
            "code": "HK.00700",
            "last_price": 380.0,
            "prev_close_price": 375.0,
            "volume": 1_500_000,
            "turnover_rate": 0.5,
            "lot_size": 100,
        }
        out = CacheManager.compress_quote_data(row)
        assert out["status"] == "success"
        assert out["ticker"] == "HK.00700"
        assert out["last_price"] == 380.0
        assert out["change_pct"].startswith("+")  # (380-375)/375 > 0
        assert out["volume_str"] == "1.50M"
        assert out["lot_size"] == 100

    def test_zero_prev_close_no_division_error(self):
        row = {"code": "X", "last_price": 10, "prev_close_price": 0, "volume": 0}
        out = CacheManager.compress_quote_data(row)
        assert out["change_pct"] == "+0.00%"  # safe_divide 兜底 0

    def test_option_fields_extracted(self):
        row = {
            "code": "O",
            "last_price": 1,
            "prev_close_price": 1,
            "volume": 0,
            "strike_price": 50.0,
            "option_implied_volatility": 0.2,
            "option_delta": 0.5,
            "option_gamma": 0.01,
            "option_vega": 0.02,
            "option_theta": -0.01,
        }
        out = CacheManager.compress_quote_data(row)
        assert out["implied_volatility"] == 0.2
        assert out["delta"] == 0.5
        assert out["strike_price"] == 50.0
