"""
Tests for backend/services/screener_service.py

Coverage targets:
- ScreenerFilter model validation and validators
- ScreenerDecision model validation and validators
- _ALIAS_MAP and field validation
- fuzzy_match_field validator
- populate_field_zh validator
- parse_dsl_to_futu_filters
- _normalize_nlp_query
- translate_nlp_to_dsl (with mocked LLM)
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from backend.services.screener_service import (
    _SUPPORTED_PATTERNS,
    _VALID_FIELDS_SET,
    ScreenerDecision,
    ScreenerFilter,
    screener_service,
)


class TestScreenerFilterValidation:
    """Test ScreenerFilter model validation and validators"""

    def test_valid_simple_filter(self):
        """Test creating a valid simple filter"""
        filter_data = {
            "field": "MARKET_CAP",
            "type": "simple",
            "min_value": 1e9,
            "max_value": 1e11,
        }
        f = ScreenerFilter(**filter_data)
        assert f.field == "MARKET_CAP"
        assert f.type == "simple"
        assert f.min_value == 1e9
        assert f.max_value == 1e11

    def test_valid_financial_filter(self):
        """Test creating a valid financial filter"""
        filter_data = {
            "field": "ROE",
            "type": "financial",
            "term": "ANNUAL",
            "min_value": 0.15,
        }
        f = ScreenerFilter(**filter_data)
        assert f.field == "ROE"
        assert f.type == "financial"
        assert f.term == "ANNUAL"
        assert f.min_value == 0.15

    def test_field_alias_mapping(self):
        """Test that field aliases are correctly mapped"""
        # Test PE_PERCENTILE -> HIST_PERCENTILE_PE
        f = ScreenerFilter(field="PE_PERCENTILE", type="featured")
        assert f.field == "HIST_PERCENTILE_PE"

        # Test 毛利率 -> GROSS_PROFIT_RATIO
        f = ScreenerFilter(field="毛利率", type="financial")
        assert f.field == "GROSS_PROFIT_RATIO"

        # Test 资产负债率 -> DEBT_TO_ASSETS
        f = ScreenerFilter(field="资产负债率", type="financial")
        assert f.field == "DEBT_TO_ASSETS"

    def test_fuzzy_match_field(self):
        """Test fuzzy matching of invalid field names"""
        # Test with a field that's close to a valid one
        f = ScreenerFilter(field="MARKET_CAPP", type="simple")  # Close to MARKET_CAP
        assert f.field == "MARKET_CAP"

    def test_fuzzy_match_no_match(self):
        """Test fuzzy matching with no close match"""
        f = ScreenerFilter(field="TOTALLY_INVALID_FIELD", type="simple")
        assert f.field == "TOTALLY_INVALID_FIELD"  # Should remain unchanged

    def test_type_enforcement(self):
        """Test that field types are enforced correctly"""
        # ROE should be financial, not simple
        f = ScreenerFilter(field="ROE", type="simple")
        assert f.type == "financial"

        # MARKET_CAP should be simple, not financial
        f = ScreenerFilter(field="MARKET_CAP", type="financial")
        assert f.type == "simple"

    def test_dividend_ratio_special_case(self):
        """Test special case for DIVIDEND_RATIO with continuous_period"""
        f = ScreenerFilter(field="DIVIDEND_RATIO", type="simple", continuous_period=5)
        assert f.type == "financial"

    def test_term_cleaning_for_non_financial(self):
        """Test that term is removed for non-financial fields"""
        f = ScreenerFilter(
            field="MARKET_CAP",
            type="simple",
            term="ANNUAL",  # Should be removed
            min_value=1e9,
        )
        assert f.term is None

    def test_term_default_for_financial(self):
        """Test that term defaults to ANNUAL for financial fields without term"""
        f = ScreenerFilter(field="ROE", type="financial")
        assert f.term == "ANNUAL"

    def test_populate_field_zh(self):
        """Test that field_zh is populated correctly"""
        f = ScreenerFilter(field="MARKET_CAP", type="simple")
        assert f.field_zh == "市值"

        f = ScreenerFilter(field="PE_TTM", type="simple")
        assert f.field_zh == "市盈率"

    def test_min_max_value_conversion(self):
        """Test that min/max values are converted to float"""
        f = ScreenerFilter(
            field="MARKET_CAP",
            type="simple",
            min_value="1000000000",  # String that can be converted
            max_value=2e10,
        )
        assert f.min_value == 1000000000.0
        assert f.max_value == 2e10

    def test_invalid_min_max_value(self):
        """Test that invalid min/max values raise validation error"""
        with pytest.raises(ValidationError):
            ScreenerFilter(
                field="MARKET_CAP",
                type="simple",
                min_value="not_a_number",
            )


class TestScreenerDecisionValidation:
    """Test ScreenerDecision model validation and validators"""

    def test_valid_decision(self):
        """Test creating a valid ScreenerDecision"""
        decision_data = {
            "dsl_display": "market:us pe:10~20",
            "markets": ["US"],
            "exclude_st": False,
            "filters": [
                {"field": "MARKET_CAP", "type": "simple", "min_value": 1e9},
                {"field": "PE_TTM", "type": "simple", "min_value": 10, "max_value": 20},
            ],
        }
        d = ScreenerDecision(**decision_data)
        assert d.dsl_display == "market:us pe:10~20"
        assert d.markets == ["US"]
        assert d.exclude_st is False
        assert len(d.filters) == 2

    def test_dsl_display_truncation(self):
        """Test that dsl_display is truncated if too long"""
        long_dsl = "a" * 150  # Longer than 100 chars
        decision_data = {
            "dsl_display": long_dsl,
            "markets": ["US"],
            "filters": [],
        }
        d = ScreenerDecision(**decision_data)
        assert len(d.dsl_display) <= 103  # 100 + "..."
        assert d.dsl_display.endswith("...")

    def test_empty_markets_default(self):
        """Test that empty markets are populated with defaults"""
        decision_data = {
            "dsl_display": "test",
            "markets": [],
            "filters": [],
        }
        d = ScreenerDecision(**decision_data)
        assert len(d.markets) > 0  # Should have default markets

    def test_cn_market_expansion(self):
        """Test that CN market is expanded to SH and SZ"""
        decision_data = {
            "dsl_display": "test",
            "markets": ["CN"],
            "filters": [],
        }
        d = ScreenerDecision(**decision_data)
        assert "SH" in d.markets
        assert "SZ" in d.markets
        assert "CN" not in d.markets

    def test_technical_patterns_filtering(self):
        """Test that unsupported technical patterns are filtered out"""
        decision_data = {
            "dsl_display": "test",
            "markets": ["US"],
            "filters": [],
            "technical_patterns": ["macd_gold_cross", "unsupported_pattern", "rsi_oversold"],
        }
        d = ScreenerDecision(**decision_data)
        assert "macd_gold_cross" in d.technical_patterns
        assert "rsi_oversold" in d.technical_patterns
        assert "unsupported_pattern" not in d.technical_patterns

    def test_volume_surge_detection(self):
        """Test detection of volume surge from VOLUME_MULTIPLE with days"""
        decision_data = {
            "dsl_display": "test",
            "markets": ["US"],
            "filters": [{"field": "VOLUME_MULTIPLE", "type": "simple", "min_value": 1.5, "days": 3}],
        }
        d = ScreenerDecision(**decision_data)
        assert "volume_surge_3d" in d.technical_patterns

    def test_plate_filter_removal(self):
        """Test that plate filters are removed"""
        decision_data = {
            "dsl_display": "test",
            "markets": ["US"],
            "filters": [
                {"field": "STOCK_PLATE", "type": "plate", "value": ["银行"]},
                {"field": "MARKET_CAP", "type": "simple", "min_value": 1e9},
            ],
        }
        d = ScreenerDecision(**decision_data)
        assert len(d.filters) == 1
        assert d.filters[0].field == "MARKET_CAP"

    def test_continuous_period_min_value(self):
        """Test that min_value is set for continuous_period filters"""
        decision_data = {
            "dsl_display": "test",
            "markets": ["US"],
            "filters": [
                {
                    "field": "NET_PROFIT",
                    "type": "financial",
                    "term": "ANNUAL",
                    "continuous_period": 3,
                }
            ],
        }
        d = ScreenerDecision(**decision_data)
        assert d.filters[0].min_value == 0.0
        assert d.filters[0].lower_included is False

    def test_conflicting_filters_detection(self):
        """Test detection of conflicting filter conditions"""
        decision_data = {
            "dsl_display": "test",
            "markets": ["US"],
            "filters": [
                {"field": "MARKET_CAP", "type": "simple", "min_value": 1e10, "max_value": 1e9},
            ],
        }
        with pytest.raises(ValueError, match="逻辑互斥"):
            ScreenerDecision(**decision_data)

    def test_technical_patterns_zh_population(self):
        """Test that technical_patterns_zh is populated"""
        decision_data = {
            "dsl_display": "test",
            "markets": ["US"],
            "filters": [],
            "technical_patterns": ["macd_gold_cross", "rsi_oversold"],
        }
        d = ScreenerDecision(**decision_data)
        assert len(d.technical_patterns_zh) == 2
        assert "MACD金叉" in d.technical_patterns_zh

    def test_dsl_display_translation(self):
        """Test that English technical patterns in dsl_display are translated"""
        decision_data = {
            "dsl_display": "US market macd_gold_cross rsi_oversold",
            "markets": ["US"],
            "filters": [],
            "technical_patterns": [],
        }
        d = ScreenerDecision(**decision_data)
        assert "MACD金叉" in d.dsl_display
        assert "RSI超卖" in d.dsl_display


class TestParseDslToFutuFilters:
    """Test parse_dsl_to_futu_filters method"""

    def test_parse_valid_dsl(self):
        """Test parsing valid DSL JSON"""
        json_str = json.dumps(
            {
                "dsl_display": "market:us pe:10~20",
                "markets": ["US"],
                "exclude_st": False,
                "filters": [
                    {"field": "MARKET_CAP", "type": "simple", "min_value": 1e9},
                    {"field": "PE_TTM", "type": "simple", "min_value": 10, "max_value": 20},
                ],
            }
        )
        markets, futu_filters, post_filters = screener_service.parse_dsl_to_futu_filters(json_str)
        assert markets == ["US"]
        assert len(futu_filters) == 2
        assert post_filters["exclude_st"] is False

    def test_parse_with_technical_patterns(self):
        """Test parsing DSL with technical patterns"""
        json_str = json.dumps(
            {
                "dsl_display": "test",
                "markets": ["US"],
                "exclude_st": False,
                "technical_patterns": ["macd_gold_cross"],
                "filters": [],
            }
        )
        markets, futu_filters, post_filters = screener_service.parse_dsl_to_futu_filters(json_str)
        assert "macd_gold_cross" in post_filters["technical_patterns"]

    def test_parse_volume_ratio_conversion(self):
        """Test that VOLUME_MULTIPLE is converted to VOLUME_RATIO"""
        json_str = json.dumps(
            {
                "dsl_display": "test",
                "markets": ["US"],
                "exclude_st": False,
                "filters": [
                    {"field": "VOLUME_MULTIPLE", "type": "simple", "min_value": 1.5},
                ],
            }
        )
        markets, futu_filters, post_filters = screener_service.parse_dsl_to_futu_filters(json_str)
        assert futu_filters[0]["field"] == "VOLUME_RATIO"

    def test_parse_invalid_json(self):
        """Test parsing invalid JSON"""
        with pytest.raises(ValueError):
            screener_service.parse_dsl_to_futu_filters("not valid json")

    def test_parse_invalid_field(self):
        """Test parsing JSON with invalid field - should be handled by fuzzy match"""
        json_str = json.dumps(
            {
                "dsl_display": "test",
                "markets": ["US"],
                "exclude_st": False,
                "filters": [
                    {"field": "INVALID_FIELD", "type": "simple"},
                ],
            }
        )
        # Invalid field should be kept as-is (fuzzy match won't find a match)
        markets, futu_filters, post_filters = screener_service.parse_dsl_to_futu_filters(json_str)
        assert len(futu_filters) == 1
        assert futu_filters[0]["field"] == "INVALID_FIELD"


class TestNormalizeNlpQuery:
    """Test _normalize_nlp_query method"""

    def test_normalize_lowercase(self):
        """Test that query is converted to lowercase"""
        result = screener_service._normalize_nlp_query("Find Stocks With High PE")
        assert result == "find stocks with high pe"

    def test_normalize_remove_punctuation(self):
        """Test that punctuation is removed"""
        result = screener_service._normalize_nlp_query("Find stocks, with high PE!")
        assert "," not in result
        assert "!" not in result

    def test_normalize_chinese(self):
        """Test that Chinese characters are preserved"""
        result = screener_service._normalize_nlp_query("找市盈率<20的股票")
        assert "市盈率" in result
        assert "<" not in result  # Punctuation removed

    def test_normalize_multiple_spaces(self):
        """Test that multiple spaces are collapsed"""
        result = screener_service._normalize_nlp_query("find    stocks   with")
        assert "  " not in result

    def test_normalize_strip(self):
        """Test that leading/trailing spaces are removed"""
        result = screener_service._normalize_nlp_query("  find stocks  ")
        assert not result.startswith(" ")
        assert not result.endswith(" ")


class TestScreenerServiceMethods:
    """Test ScreenerService methods"""

    @pytest.mark.asyncio
    async def test_translate_nlp_to_dsl_with_cache(self):
        """Test translate_nlp_to_dsl with cached result"""
        # Mock redis cache hit
        with patch.object(screener_service, "_normalize_nlp_query", return_value="test query"):
            with patch("backend.services.screener.nlp_translator.redis_client") as mock_redis:
                mock_redis.get = AsyncMock(
                    return_value=json.dumps(
                        {
                            "dsl_display": "cached result",
                            "markets": ["US"],
                            "filters": [],
                        }
                    )
                )

                result = await screener_service.translate_nlp_to_dsl("test query")
                assert "cached result" in result
                mock_redis.get.assert_called_once()

    @pytest.mark.asyncio
    async def test_translate_nlp_to_dsl_no_cache(self):
        """Test translate_nlp_to_dsl without cache (mocked LLM)"""
        with patch("backend.services.screener.nlp_translator.redis_client") as mock_redis:
            mock_redis.get = AsyncMock(return_value=None)
            mock_redis.setex = AsyncMock()

            # Mock the LLM service
            with patch("backend.services.screener.nlp_translator.llm_service") as mock_llm:
                mock_response = MagicMock()
                mock_response.choices = [MagicMock()]
                mock_response.choices[0].message.content = json.dumps(
                    {
                        "dsl_display": "market:us pe:10~20",
                        "markets": ["US"],
                        "exclude_st": False,
                        "filters": [{"field": "PE_TTM", "type": "simple", "min_value": 10, "max_value": 20}],
                    }
                )

                mock_llm.get_client = MagicMock(return_value=MagicMock())
                mock_llm.get_client().chat.completions.create = AsyncMock(return_value=mock_response)
                mock_llm.get_model = MagicMock(return_value="gpt-4")

                result = await screener_service.translate_nlp_to_dsl("find stocks with pe 10 to 20")
                result_dict = json.loads(result)
                assert result_dict["markets"] == ["US"]

    def test_reload_rag_corpus_no_csv(self):
        """Test reload_rag_corpus when CSV doesn't exist"""
        # This should use default corpus
        with patch("os.path.exists", return_value=False):
            result = screener_service.reload_rag_corpus()
            # Should return something (either count or dict)
            assert result is not None


class TestEdgeCases:
    """Test edge cases and error handling"""

    def test_screener_filter_all_fields(self):
        """Test ScreenerFilter with all possible fields"""
        # Test that valid fields are accepted
        # Note: Some fields may be corrected by fuzzy match or type enforcement
        test_fields = [
            "MARKET_CAP",
            "PE_TTM",
            "PB",
            "PRICE",
            "ROE",
            "ROA_TTM",
            "DIVIDEND_RATIO",
            "GROSS_PROFIT_RATIO",
            "DEBT_TO_ASSETS",
            "CURRENT_RATIO",
        ]
        for field in test_fields:
            filter_data = {"field": field, "type": "simple"}
            f = ScreenerFilter(**filter_data)
            assert f.field in _VALID_FIELDS_SET  # Field should be valid

    def test_screener_decision_with_all_technical_patterns(self):
        """Test ScreenerDecision with all supported technical patterns"""
        decision_data = {
            "dsl_display": "test",
            "markets": ["US"],
            "filters": [],
            "technical_patterns": list(_SUPPORTED_PATTERNS),
        }
        d = ScreenerDecision(**decision_data)
        assert len(d.technical_patterns) == len(_SUPPORTED_PATTERNS)

    def test_filter_with_intervals(self):
        """Test ScreenerFilter with intervals"""
        filter_data = {
            "field": "MACD_GOLD_CROSS",
            "type": "indicator_pattern",
            "period": "K_DAY",
            "intervals": [{"min": 0, "max": 100}],
        }
        f = ScreenerFilter(**filter_data)
        assert f.intervals == [{"min": 0, "max": 100}]

    @pytest.mark.asyncio
    async def test_add_custom_rule_not_enabled(self):
        """Test add_custom_rule when pg is not enabled"""
        # Ensure _pg_enabled is False
        screener_service._pg_enabled = False

        result = await screener_service.add_custom_rule(
            desc_text="Test rule",
            rule_text="Test rule text",
            user_id=1,
        )
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_get_custom_rules_not_enabled(self):
        """Test get_custom_rules when pg is not enabled"""
        screener_service._pg_enabled = False

        result = await screener_service.get_custom_rules(user_id=1)
        assert result == []

    @pytest.mark.asyncio
    async def test_delete_custom_rule_not_enabled(self):
        """Test delete_custom_rule when pg is not enabled"""
        screener_service._pg_enabled = False

        result = await screener_service.delete_custom_rule(rule_id="test_id", user_id=1)
        assert result is False
