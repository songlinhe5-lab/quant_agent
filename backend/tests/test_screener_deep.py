"""
Screener 模块深度覆盖测试
目标: 覆盖 screener/dsl_parser.py, screener/nlp_translator.py, screener/service.py 的未覆盖分支
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ─────────────────────────────────────────────
# DslParserMixin 测试
# ─────────────────────────────────────────────


class TestDslParser:
    """DslParserMixin 测试"""

    @pytest.fixture
    def parser(self):
        from backend.services.screener.dsl_parser import DslParserMixin

        return DslParserMixin()

    def test_parse_dsl_valid(self, parser):
        """parse_dsl_to_futu_filters: 有效 DSL"""
        dsl = json.dumps(
            {
                "dsl_display": "HK PE<20",
                "markets": ["HK"],
                "exclude_st": False,
                "filters": [{"field": "PE_TTM", "type": "simple", "min_value": None, "max_value": 20.0}],
            }
        )
        markets, futu_filters, post_filters = parser.parse_dsl_to_futu_filters(dsl)
        assert markets == ["HK"]
        assert len(futu_filters) == 1
        assert futu_filters[0]["field"] == "PE_TTM"
        assert post_filters["exclude_st"] is False

    def test_parse_dsl_volume_multiple_rename(self, parser):
        """parse_dsl_to_futu_filters: VOLUME_MULTIPLE 重命名为 VOLUME_RATIO"""
        dsl = json.dumps(
            {
                "dsl_display": "放量",
                "markets": ["US"],
                "exclude_st": False,
                "filters": [{"field": "VOLUME_MULTIPLE", "type": "simple", "min_value": 1.5}],
            }
        )
        markets, futu_filters, post_filters = parser.parse_dsl_to_futu_filters(dsl)
        assert futu_filters[0]["field"] == "VOLUME_RATIO"

    def test_parse_dsl_financial_with_term(self, parser):
        """parse_dsl_to_futu_filters: financial 类型保留 term"""
        dsl = json.dumps(
            {
                "dsl_display": "ROE>15%",
                "markets": ["HK"],
                "exclude_st": False,
                "filters": [{"field": "ROE", "type": "financial", "term": "ANNUAL", "min_value": 0.15}],
            }
        )
        markets, futu_filters, post_filters = parser.parse_dsl_to_futu_filters(dsl)
        assert futu_filters[0].get("term") == "ANNUAL"

    def test_parse_dsl_non_financial_removes_term(self, parser):
        """parse_dsl_to_futu_filters: 非 financial 类型移除 term"""
        dsl = json.dumps(
            {
                "dsl_display": "PE<20",
                "markets": ["HK"],
                "exclude_st": False,
                "filters": [{"field": "PE_TTM", "type": "simple", "term": "ANNUAL", "max_value": 20.0}],
            }
        )
        markets, futu_filters, post_filters = parser.parse_dsl_to_futu_filters(dsl)
        assert "term" not in futu_filters[0]

    def test_parse_dsl_validation_error(self, parser):
        """parse_dsl_to_futu_filters: 验证错误"""
        invalid_dsl = json.dumps({"invalid": "structure"})
        with pytest.raises(ValueError) as exc_info:
            parser.parse_dsl_to_futu_filters(invalid_dsl)
        assert "AI 生成的筛选条件越界" in str(exc_info.value) or "大模型输出结构异常" in str(exc_info.value)

    def test_parse_dsl_invalid_json(self, parser):
        """parse_dsl_to_futu_filters: 无效 JSON"""
        with pytest.raises(ValueError) as exc_info:
            parser.parse_dsl_to_futu_filters("not valid json {{{")
        # 无效 JSON 会被 Pydantic 捕获并转换为 ValueError
        assert "筛选条件越界" in str(exc_info.value) or "结构异常" in str(exc_info.value)

    def test_parse_dsl_field_zh_removed(self, parser):
        """parse_dsl_to_futu_filters: field_zh 被移除"""
        dsl = json.dumps(
            {
                "dsl_display": "PE<20",
                "markets": ["HK"],
                "exclude_st": False,
                "filters": [{"field": "PE_TTM", "type": "simple", "max_value": 20.0, "field_zh": "市盈率"}],
            }
        )
        markets, futu_filters, post_filters = parser.parse_dsl_to_futu_filters(dsl)
        assert "field_zh" not in futu_filters[0]

    @pytest.mark.asyncio
    async def test_apply_technical_pattern_filtering_empty(self, parser):
        """apply_technical_pattern_filtering: 空数据"""
        result = await parser.apply_technical_pattern_filtering([], ["macd_gold_cross"])
        assert result == []

    @pytest.mark.asyncio
    async def test_apply_technical_pattern_filtering_no_patterns(self, parser):
        """apply_technical_pattern_filtering: 无技术形态要求"""
        data = [{"symbol": "AAPL"}, {"symbol": "TSLA"}]
        with patch("backend.services.screener.dsl_parser.redis_client") as mock_redis:
            mock_pipe = MagicMock()
            mock_pipe.execute = AsyncMock(return_value=[None, None])
            mock_redis.pipeline = MagicMock(return_value=mock_pipe)

            result = await parser.apply_technical_pattern_filtering(data, [])
            assert len(result) == 2

    @pytest.mark.asyncio
    async def test_apply_technical_pattern_filtering_cache_hit(self, parser):
        """apply_technical_pattern_filtering: 缓存命中"""
        data = [{"symbol": "AAPL"}]
        cached_data = json.dumps({"patterns": ["macd_gold_cross"], "values": {"rsi": 30}})
        with patch("backend.services.screener.dsl_parser.redis_client") as mock_redis:
            mock_pipe = MagicMock()
            mock_pipe.execute = AsyncMock(return_value=[cached_data])
            mock_redis.pipeline = MagicMock(return_value=mock_pipe)

            result = await parser.apply_technical_pattern_filtering(data, ["macd_gold_cross"])
            assert len(result) == 1
            assert result[0].get("matched_patterns") == "MACD金叉"
            assert result[0].get("rsi") == 30


# ─────────────────────────────────────────────
# NlpTranslatorMixin 测试
# ─────────────────────────────────────────────


class TestNlpTranslator:
    """NlpTranslatorMixin 测试"""

    @pytest.fixture
    def translator(self):
        from backend.services.screener.nlp_translator import NlpTranslatorMixin

        class TestTranslator(NlpTranslatorMixin):
            def __init__(self):
                self._rag_corpus = [{"desc": "test", "rule": "test rule"}]
                self._pg_enabled = False
                self._embed_func = None

        return TestTranslator()

    def test_normalize_nlp_query_basic(self, translator):
        """_normalize_nlp_query: 基本标准化"""
        result = translator._normalize_nlp_query("PE < 20 AND ROE > 15%")
        assert result == "pe 20 and roe 15"

    def test_normalize_nlp_query_chinese(self, translator):
        """_normalize_nlp_query: 中文查询"""
        result = translator._normalize_nlp_query("市盈率小于20，ROE大于15%")
        assert "市盈率" in result
        assert "20" in result

    def test_normalize_nlp_query_extra_spaces(self, translator):
        """_normalize_nlp_query: 多余空格"""
        result = translator._normalize_nlp_query("PE    <    20")
        assert result == "pe 20"

    @pytest.mark.asyncio
    async def test_retrieve_relevant_fields_no_pg(self, translator):
        """_retrieve_relevant_fields: 无 PostgreSQL 降级"""
        result = await translator._retrieve_relevant_fields("PE < 20")
        assert "test rule" in result

    @pytest.mark.asyncio
    async def test_translate_nlp_to_dsl_cache_hit(self, translator):
        """translate_nlp_to_dsl: 缓存命中"""
        cached_dsl = json.dumps({"markets": ["HK"], "filters": []})
        with patch("backend.services.screener.nlp_translator.redis_client") as mock_redis:
            mock_redis.get = AsyncMock(return_value=cached_dsl)
            result = await translator.translate_nlp_to_dsl("PE < 20")
            assert result == cached_dsl

    @pytest.mark.asyncio
    async def test_translate_nlp_to_dsl_cache_hit_bytes(self, translator):
        """translate_nlp_to_dsl: 缓存命中 (bytes)"""
        cached_dsl = json.dumps({"markets": ["HK"], "filters": []})
        with patch("backend.services.screener.nlp_translator.redis_client") as mock_redis:
            mock_redis.get = AsyncMock(return_value=cached_dsl.encode("utf-8"))
            result = await translator.translate_nlp_to_dsl("PE < 20")
            assert result == cached_dsl


# ─────────────────────────────────────────────
# ScreenerService 测试
# ─────────────────────────────────────────────


class TestScreenerService:
    """ScreenerService 测试"""

    @pytest.fixture
    def service(self):
        from backend.services.screener.service import ScreenerService

        # 创建一个简化的测试实例
        svc = object.__new__(ScreenerService)
        svc._rag_corpus = []
        svc._pg_enabled = False
        svc._embed_func = None
        return svc

    @pytest.mark.asyncio
    async def test_get_custom_rules_no_pg(self, service):
        """get_custom_rules: 无 PostgreSQL"""
        result = await service.get_custom_rules(user_id=1)
        assert result == []

    @pytest.mark.asyncio
    async def test_delete_custom_rule_no_pg(self, service):
        """delete_custom_rule: 无 PostgreSQL"""
        result = await service.delete_custom_rule(rule_id="1", user_id=1)
        assert result is False

    @pytest.mark.asyncio
    async def test_summarize_results_empty(self, service):
        """summarize_results: 空结果"""
        result = await service.summarize_results([])
        assert "暂无选股结果" in result

    @pytest.mark.asyncio
    async def test_summarize_results_with_stocks(self, service):
        """summarize_results: 有股票数据"""
        stocks = [
            {"symbol": "AAPL", "name": "苹果", "chg": 2.5},
            {"symbol": "TSLA", "name": "特斯拉", "chg": -1.2},
        ]
        # Mock LLM 服务
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "## AI 选股洞察\n这是一份测试报告"

        with patch("backend.services.screener.service.llm_service") as mock_llm:
            mock_client = MagicMock()
            mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
            mock_llm.get_client = MagicMock(return_value=mock_client)
            mock_llm.get_model = MagicMock(return_value="gpt-4")

            # Mock 新闻获取 - finnhub_service 是在函数内部导入的
            with patch("backend.services.finnhub_service.finnhub_service") as mock_finnhub:
                mock_finnhub.get_company_news = AsyncMock(return_value={"status": "success", "data": []})

                result = await service.summarize_results(stocks)
                assert "AI 选股洞察" in result or "测试报告" in result

    @pytest.mark.asyncio
    async def test_summarize_results_llm_error(self, service):
        """summarize_results: LLM 调用失败"""
        stocks = [{"symbol": "AAPL", "name": "苹果", "chg": 2.5}]

        with patch("backend.services.screener.service.llm_service") as mock_llm:
            mock_client = MagicMock()
            mock_client.chat.completions.create = AsyncMock(side_effect=Exception("LLM error"))
            mock_llm.get_client = MagicMock(return_value=mock_client)
            mock_llm.get_model = MagicMock(return_value="gpt-4")

            # Mock 新闻获取 - finnhub_service 是在函数内部导入的
            with patch("backend.services.finnhub_service.finnhub_service") as mock_finnhub:
                mock_finnhub.get_company_news = AsyncMock(return_value={"status": "error"})

                result = await service.summarize_results(stocks)
                assert "失败" in result


# ─────────────────────────────────────────────
# Screener Models 测试
# ─────────────────────────────────────────────


class TestScreenerModels:
    """Screener Models 测试"""

    def test_screener_decision_valid(self):
        """ScreenerDecision: 有效模型"""
        from backend.services.screener.models import ScreenerDecision

        data = {
            "dsl_display": "HK PE<20",
            "markets": ["HK"],
            "exclude_st": False,
            "filters": [],
        }
        decision = ScreenerDecision.model_validate(data)
        assert decision.markets == ["HK"]

    def test_screener_filter_valid(self):
        """ScreenerFilter: 有效过滤器"""
        from backend.services.screener.models import ScreenerFilter

        filter_data = {
            "field": "PE_TTM",
            "type": "simple",
            "min_value": 0,
            "max_value": 20.0,
        }
        f = ScreenerFilter.model_validate(filter_data)
        assert f.field == "PE_TTM"

    def test_screener_filter_with_alias(self):
        """ScreenerFilter: 别名序列化"""
        from backend.services.screener.models import ScreenerFilter

        f = ScreenerFilter(field="PE_TTM", type="simple", min_value=0, max_value=20.0)
        dumped = f.model_dump(by_alias=True, exclude_none=True)
        assert "min" in dumped or "min_value" in dumped
