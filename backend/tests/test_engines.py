"""
引擎层单元测试
覆盖: market_engine (protobuf, utils)
"""

import os
import sys

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("EMBEDDING_API_KEY", "test-key")
os.environ.setdefault("EMBEDDING_BASE_URL", "https://api.test.com")
os.environ.setdefault("EMBEDDING_MODEL", "BAAI/bge-large-zh-v1.5")
os.environ.setdefault("INTERNAL_API_SECRET", "test-secret-key")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))


# ─── market_engine: Protobuf ────────────────────────────────────────
class TestMarketEngineProtobuf:
    def test_quote_data_proto(self):
        from backend.core.proto.market_pb2 import QuoteData

        quote = QuoteData(
            status="success",
            ticker="US.AAPL",
            last_price=150.0,
            change_pct="+1.5%",
            volume_str="50M",
            source="yfinance",
        )
        assert quote.ticker == "US.AAPL"
        assert quote.last_price == 150.0
        serialized = quote.SerializeToString()
        assert len(serialized) > 0

        # Deserialize
        quote2 = QuoteData()
        quote2.ParseFromString(serialized)
        assert quote2.ticker == "US.AAPL"
        assert quote2.last_price == 150.0

    def test_order_proto(self):
        from backend.core.proto.market_pb2 import Order

        order = Order(price=100.5, size=200.0)
        assert order.price == 100.5
        assert order.size == 200.0

    def test_quote_with_bids_asks(self):
        from backend.core.proto.market_pb2 import Order, QuoteData

        quote = QuoteData(status="success", ticker="HK.00700", last_price=400.0)
        quote.bids.append(Order(price=399.5, size=1000))
        quote.asks.append(Order(price=400.5, size=500))
        assert len(quote.bids) == 1
        assert len(quote.asks) == 1
        assert quote.bids[0].price == 399.5


# ─── market_engine: Helper Functions ────────────────────────────────
class TestMarketEngineHelpers:
    def test_safe_float_in_market_context(self):
        from backend.core.utils import safe_float

        assert safe_float("150.5") == 150.5
        assert safe_float(None) == 0.0

    def test_safe_divide_in_market_context(self):
        from backend.core.utils import safe_divide

        assert safe_divide(100, 0) == 0.0
        assert safe_divide(100, 200) == 0.5
