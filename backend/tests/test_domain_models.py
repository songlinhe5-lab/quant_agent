"""schemas/domain.py Pydantic 领域模型单元测试

覆盖: 枚举完整性、alias 接受、必填校验、Optional 字段、嵌套模型、
populate_by_name 双向兼容、from_attributes ORM 模式。
"""

import pytest
from pydantic import ValidationError

from backend.schemas.domain import (
    AccountModel,
    ApiResponseModel,
    ClientHeartbeatModel,
    IndicatorParams,
    IndicatorType,
    KlineModel,
    KlinePeriod,
    KlineSeriesModel,
    Market,
    OrderModel,
    OrderSide,
    OrderStatus,
    OrderTIF,
    OrderType,
    PaginatedResponseModel,
    PositionModel,
    PositionSide,
    PositionStatus,
    QuoteModel,
    ScreenerFilterModel,
    ScreenerResultModel,
    SecurityType,
    StrategyModel,
    StrategyStatus,
    SymbolModel,
    TechIndicatorsModel,
    TickModel,
    WSKlineMessageModel,
    WSQuoteMessageModel,
    WSSubscribeMessageModel,
)


class TestDomainEnums:
    """枚举完整性校验"""

    def test_market_enum_has_seven_members(self):
        assert {m.value for m in Market} == {"US", "HK", "SH", "SZ", "SG", "JP", "CN"}

    def test_security_type_enum_covers_main_types(self):
        assert SecurityType.STOCK.value == "STOCK"
        assert SecurityType.OPTION.value == "OPTION"
        assert SecurityType.CRYPTO.value == "CRYPTO"

    def test_kline_period_enum_includes_intraday_and_daily(self):
        assert KlinePeriod.K_1M.value == "K_1M"
        assert KlinePeriod.K_DAY.value == "K_DAY"
        assert KlinePeriod.K_MONTH.value == "K_MONTH"

    def test_order_side_status_type_tif_enums_complete(self):
        assert {s.value for s in OrderSide} == {"BUY", "SELL"}
        assert OrderStatus.FILLED.value == "FILLED"
        assert OrderType.STOP_LIMIT.value == "STOP_LIMIT"
        assert OrderTIF.GTC.value == "GTC"

    def test_position_side_status_enums(self):
        assert PositionSide.LONG.value == "LONG"
        assert PositionStatus.CLOSED.value == "CLOSED"

    def test_strategy_status_enum_lifecycle(self):
        assert {s.value for s in StrategyStatus} == {"DRAFT", "ACTIVE", "PAUSED", "ARCHIVED"}

    def test_indicator_type_enum_supports_main_indicators(self):
        assert IndicatorType.MACD.value == "MACD"
        assert IndicatorType.VWAP.value == "VWAP"


class TestSymbolModel:
    """SymbolModel: alias + Optional"""

    def test_symbol_model_accepts_camel_alias(self):
        s = SymbolModel(
            code="HK.00700",
            name="Tencent",
            market=Market.HK,
            securityType=SecurityType.STOCK,
            lotSize=100,
        )
        assert s.lot_size == 100
        assert s.security_type == SecurityType.STOCK

    def test_symbol_model_optional_fields_default_none(self):
        s = SymbolModel(code="US.AAPL", name="Apple", market=Market.US, securityType=SecurityType.STOCK)
        assert s.lot_size is None
        assert s.currency is None

    def test_symbol_model_missing_required_field_raises(self):
        with pytest.raises(ValidationError):
            SymbolModel(code="HK.00700", name="Tencent", market=Market.HK)  # 缺 securityType


class TestQuoteModel:
    """QuoteModel: 别名字段 + populate_by_name"""

    def test_quote_model_accepts_camel_alias(self):
        q = QuoteModel(
            symbol="US.AAPL",
            lastPrice=185.5,
            open=184.0,
            high=186.0,
            low=183.5,
            prevClose=184.0,
            volume=1000000,
            turnover=1.8e8,
            change=1.5,
            changePercent=0.81,
            timestamp=1719500000000,
        )
        assert q.last_price == 185.5
        assert q.change_percent == 0.81
        assert q.prev_close == 184.0

    def test_quote_model_accepts_snake_name_when_populate_by_name(self):
        q = QuoteModel(
            symbol="US.AAPL",
            last_price=185.5,  # snake
            open=184.0,
            high=186.0,
            low=183.5,
            prev_close=184.0,  # snake
            volume=1000,
            turnover=1e6,
            change=1.0,
            change_percent=0.5,  # snake
            timestamp=1719500000000,
        )
        assert q.last_price == 185.5

    def test_quote_model_optional_bid_ask_default_none(self):
        q = QuoteModel(
            symbol="X",
            last_price=1,
            open=1,
            high=1,
            low=1,
            prev_close=1,
            volume=1,
            turnover=1,
            change=0,
            change_percent=0,
            timestamp=0,
        )
        assert q.bid_price is None and q.ask_volume is None


class TestKlineModels:
    """KlineModel + KlineSeriesModel: 嵌套"""

    def test_kline_model_optional_turnover(self):
        k = KlineModel(timestamp=0, open=1, high=2, low=0, close=1, volume=100)
        assert k.turnover is None

    def test_kline_series_model_nests_kline_list(self):
        k1 = KlineModel(timestamp=1, open=1, high=2, low=0, close=1, volume=100)
        k2 = KlineModel(timestamp=2, open=1, high=3, low=1, close=2, volume=200)
        series = KlineSeriesModel(symbol="HK.00700", period=KlinePeriod.K_DAY, klines=[k1, k2])
        assert len(series.klines) == 2
        assert series.klines[1].close == 2


class TestTickModel:
    def test_tick_model_accepts_alias(self):
        t = TickModel(timestamp=0, price=100.0, volume=10, bidSize=5, askSize=8)
        assert t.bid_size == 5 and t.ask_size == 8


class TestPositionAndOrderModels:
    """PositionModel + OrderModel: alias + 必填"""

    def test_position_model_accepts_all_aliases(self):
        p = PositionModel(
            id="pos-1",
            symbol="US.AAPL",
            side=PositionSide.LONG,
            quantity=100,
            avgCost=150.0,
            currentPrice=160.0,
            marketValue=16000.0,
            unrealizedPnL=1000.0,
            realizedPnL=0.0,
            unrealizedPnLPercent=6.67,
            status=PositionStatus.OPEN,
            openedAt=0,
            updatedAt=0,
        )
        assert p.avg_cost == 150.0
        assert p.unrealized_pnl_percent == 6.67

    def test_order_model_optional_price_defaults_none(self):
        o = OrderModel(
            id="ord-1",
            symbol="X",
            side=OrderSide.BUY,
            type=OrderType.MARKET,
            quantity=100,
            filledQuantity=100,
            status=OrderStatus.FILLED,
            createdAt=0,
            updatedAt=0,
            isPaper=True,
        )
        assert o.price is None and o.stop_price is None
        assert o.is_paper is True

    def test_order_model_strategy_id_optional(self):
        o = OrderModel(
            id="ord-2",
            symbol="X",
            side=OrderSide.SELL,
            type=OrderType.LIMIT,
            quantity=10,
            price=100.0,
            filledQuantity=0,
            status=OrderStatus.PENDING,
            createdAt=0,
            updatedAt=0,
            isPaper=False,
            strategyId="strat-1",
        )
        assert o.strategy_id == "strat-1"


class TestAccountModel:
    def test_account_model_all_aliases(self):
        a = AccountModel(
            accountId="A1",
            totalAssets=1e6,
            cash=5e5,
            marketValue=5e5,
            buyingPower=5e5,
            unrealizedPnL=0,
            realizedPnL=0,
            dailyPnL=100,
            dailyPnLPercent=0.01,
            currency="USD",
            updatedAt=0,
        )
        assert a.account_id == "A1"
        assert a.total_assets == 1e6
        assert a.daily_pnl_percent == 0.01


class TestTechIndicators:
    def test_tech_indicators_model_with_alias_params(self):
        ind = TechIndicatorsModel(
            type=IndicatorType.MACD,
            params=IndicatorParams(fastPeriod=12, slowPeriod=26, signalPeriod=9),
            values=[{"dif": 0.5, "dea": 0.3, "macd": 0.2}],
            signal="BUY",
        )
        assert ind.params.fast_period == 12
        assert ind.signal == "BUY"


class TestScreenerModels:
    def test_screener_filter_all_optional(self):
        f = ScreenerFilterModel()
        assert f.market is None and f.max_pe is None

    def test_screener_filter_accepts_aliases(self):
        f = ScreenerFilterModel(minPE=10, maxPE=30, minMarketCap=1e9)
        assert f.min_pe == 10 and f.max_pe == 30
        assert f.min_market_cap == 1e9

    def test_screener_result_model_alias(self):
        r = ScreenerResultModel(
            symbol="US.AAPL",
            name="Apple",
            market=Market.US,
            lastPrice=185.0,
            changePercent=0.5,
            volume=1e6,
        )
        assert r.last_price == 185.0
        assert r.pe is None


class TestStrategyModel:
    def test_strategy_model_accepts_aliases(self):
        s = StrategyModel(
            id="s1",
            name="DualMA",
            status=StrategyStatus.ACTIVE,
            code="...",
            createdAt=0,
            updatedAt=0,
        )
        assert s.created_at == 0


class TestWSMessageModels:
    def test_ws_subscribe_message(self):
        m = WSSubscribeMessageModel(type="subscribe", topic="quote", symbol="US.AAPL")
        assert m.symbol == "US.AAPL"

    def test_ws_quote_message_nests_quote(self):
        q = QuoteModel(
            symbol="X",
            last_price=1,
            open=1,
            high=1,
            low=1,
            prev_close=1,
            volume=1,
            turnover=1,
            change=0,
            change_percent=0,
            timestamp=0,
        )
        m = WSQuoteMessageModel(type="tick", data=q)
        assert m.data.last_price == 1

    def test_ws_kline_message_nests_series(self):
        series = KlineSeriesModel(
            symbol="X",
            period=KlinePeriod.K_1M,
            klines=[KlineModel(timestamp=0, open=1, high=1, low=1, close=1, volume=1)],
        )
        m = WSKlineMessageModel(type="kline", data=series)
        assert m.data.klines[0].close == 1


class TestApiResponseModels:
    def test_api_response_model_basic(self):
        r = ApiResponseModel(code=0, msg="ok", data={"k": "v"}, ts=0)
        assert r.code == 0 and r.data == {"k": "v"}

    def test_paginated_response_accepts_alias(self):
        r = PaginatedResponseModel(items=[1, 2], total=10, page=1, pageSize=2, hasMore=True)
        assert r.page_size == 2 and r.has_more is True


class TestClientHeartbeatModel:
    def test_heartbeat_required_fields(self):
        h = ClientHeartbeatModel(
            platform="web",
            appVersion="1.0",
            deviceId="dev-1",
            timestamp=0,
        )
        assert h.fps is None and h.memory_mb is None
        assert h.app_version == "1.0"

    def test_heartbeat_optional_metrics(self):
        h = ClientHeartbeatModel(
            platform="desktop",
            appVersion="2.0",
            deviceId="d",
            fps=59.5,
            memoryMb=512.0,
            wsLatencyMs=12,
            timestamp=0,
        )
        assert h.fps == 59.5
        assert h.ws_latency_ms == 12

    def test_heartbeat_web_vitals_optional(self):
        h = ClientHeartbeatModel(
            platform="web",
            appVersion="0.1.0",
            deviceId="browser-1",
            lcpMs=1450.0,
            cls=0.04,
            inpMs=120.0,
            ttfbMs=90.0,
            timestamp=1719500000000,
        )
        assert h.lcp_ms == 1450.0
        assert h.cls == 0.04
        assert h.inp_ms == 120.0
        assert h.ttfb_ms == 90.0
