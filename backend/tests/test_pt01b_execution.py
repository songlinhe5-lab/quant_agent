"""
PT-01b: 执行接线测试
SimBroker paper 差异行为 + fill_callback + 组合 API
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from backend.engine.contracts import Bar, OrderIntent
from backend.engine.drivers.sim_broker import SimBroker, SimBrokerConfig

# ─────────────────────────────────────────
#  SimBroker paper_mode 差异行为
# ─────────────────────────────────────────


class TestSimBrokerPaperMode:
    def _make_bar(self, stale=False, dt=None):
        bar = MagicMock(spec=Bar)
        bar.close = 350.0
        bar.high = 355.0
        bar.low = 345.0
        bar.open = 348.0
        bar.dt = dt or datetime(2026, 7, 14, 10, 0, tzinfo=timezone.utc)
        bar.stale = stale
        bar.volume = 1000000
        return bar

    def _make_intent(self, side="BUY", qty=100):
        intent = MagicMock(spec=OrderIntent)
        intent.symbol = "HK.00700"
        intent.side = side
        intent.qty = qty
        intent.order_type = "MARKET"
        intent.tag = "test"
        return intent

    def test_paper_mode_stale_rejection(self):
        """paper_mode: stale 行情应拒单"""
        config = SimBrokerConfig(paper_mode=True)
        broker = SimBroker(config, initial_cash=100000.0)

        bar = self._make_bar(stale=True)
        intent = self._make_intent()

        result = broker.submit(intent, bar)
        assert result == "REJECTED_STALE"

    @patch("backend.services.market_correctness.MarketSession")
    def test_paper_mode_market_closed_rejection(self, mock_session_cls):
        """paper_mode: 非交易时段应拒单"""
        mock_session_cls.is_trading_hours.return_value = False

        config = SimBrokerConfig(paper_mode=True)
        broker = SimBroker(config, initial_cash=100000.0)

        bar = self._make_bar(stale=False)
        intent = self._make_intent()

        result = broker.submit(intent, bar)
        assert result == "REJECTED_MARKET_CLOSED"

    @patch("backend.services.market_correctness.MarketSession")
    def test_paper_mode_trading_hours_pass(self, mock_session_cls):
        """paper_mode: 交易时段内应正常撮合"""
        mock_session_cls.is_trading_hours.return_value = True

        config = SimBrokerConfig(paper_mode=True)
        broker = SimBroker(config, initial_cash=100000.0)

        bar = self._make_bar(stale=False)
        intent = self._make_intent()

        result = broker.submit(intent, bar)
        assert result.startswith("sim-")  # 正常 order_id

    def test_non_paper_mode_no_rejection(self):
        """非 paper_mode 不做 stale/时段检查"""
        config = SimBrokerConfig(paper_mode=False)
        broker = SimBroker(config, initial_cash=100000.0)

        bar = self._make_bar(stale=True)
        intent = self._make_intent()

        result = broker.submit(intent, bar)
        assert result.startswith("sim-")  # 不拒单


# ─────────────────────────────────────────
#  fill_callback
# ─────────────────────────────────────────


class TestFillCallback:
    def _make_bar(self):
        bar = MagicMock(spec=Bar)
        bar.close = 350.0
        bar.high = 355.0
        bar.low = 345.0
        bar.open = 348.0
        bar.dt = datetime(2026, 7, 14, 10, 0, tzinfo=timezone.utc)
        bar.stale = False
        bar.volume = 1000000
        return bar

    def _make_intent(self, side="BUY", qty=100):
        intent = MagicMock(spec=OrderIntent)
        intent.symbol = "HK.00700"
        intent.side = side
        intent.qty = qty
        intent.order_type = "MARKET"
        intent.tag = "test_tag"
        return intent

    def test_fill_callback_called_on_buy(self):
        """paper_mode 买入成交后 fill_callback 被调用"""
        callback = MagicMock()
        config = SimBrokerConfig(paper_mode=True)
        broker = SimBroker(config, initial_cash=100000.0)
        broker.set_fill_callback(callback)

        bar = self._make_bar()
        intent = self._make_intent("BUY", 100)

        with patch("backend.services.market_correctness.MarketSession") as mock_ms:
            mock_ms.is_trading_hours.return_value = True
            broker.submit(intent, bar)

        callback.assert_called_once()
        fill_data = callback.call_args[0][0]
        assert fill_data["side"] == "BUY"
        assert fill_data["symbol"] == "HK.00700"
        assert fill_data["qty"] == 100
        assert fill_data["intent_tag"] == "test_tag"

    def test_fill_callback_called_on_sell(self):
        """paper_mode 卖出成交后 fill_callback 被调用"""
        callback = MagicMock()
        config = SimBrokerConfig(paper_mode=True)
        broker = SimBroker(config, initial_cash=100000.0)
        broker.set_fill_callback(callback)

        # 先买入
        bar = self._make_bar()
        buy_intent = self._make_intent("BUY", 100)
        with patch("backend.services.market_correctness.MarketSession") as mock_ms:
            mock_ms.is_trading_hours.return_value = True
            broker.submit(buy_intent, bar)

        callback.reset_mock()

        # 再卖出
        sell_intent = self._make_intent("SELL", 50)
        with patch("backend.services.market_correctness.MarketSession") as mock_ms:
            mock_ms.is_trading_hours.return_value = True
            broker.submit(sell_intent, bar)

        callback.assert_called_once()
        fill_data = callback.call_args[0][0]
        assert fill_data["side"] == "SELL"
        assert fill_data["qty"] == 50

    def test_no_callback_in_non_paper_mode(self):
        """非 paper_mode 不调用 fill_callback"""
        callback = MagicMock()
        config = SimBrokerConfig(paper_mode=False)
        broker = SimBroker(config, initial_cash=100000.0)
        broker.set_fill_callback(callback)

        bar = self._make_bar()
        intent = self._make_intent("BUY", 100)
        broker.submit(intent, bar)

        callback.assert_not_called()

    def test_no_callback_when_not_set(self):
        """paper_mode 但未设 callback 不报错"""
        config = SimBrokerConfig(paper_mode=True)
        broker = SimBroker(config, initial_cash=100000.0)

        bar = self._make_bar()
        intent = self._make_intent("BUY", 100)
        with patch("backend.services.market_correctness.MarketSession") as mock_ms:
            mock_ms.is_trading_hours.return_value = True
            result = broker.submit(intent, bar)

        assert result.startswith("sim-")  # 不报错
