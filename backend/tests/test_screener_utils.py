"""
选股器工具函数单元测试
覆盖: backend/routers/screener.py 中的 _parse_human_number 和 _clean_json_dsl
"""

import os
import sys

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))


class TestParseHumanNumber:
    """人类可读数字解析测试"""

    def test_parse_plain_integer(self):
        from backend.routers.screener import _parse_human_number

        assert _parse_human_number(1000) == 1000.0

    def test_parse_plain_float(self):
        from backend.routers.screener import _parse_human_number

        assert _parse_human_number(123.45) == 123.45

    def test_parse_trillion_Chinese(self):
        from backend.routers.screener import _parse_human_number

        assert _parse_human_number("3.1万亿") == 3.1e12

    def test_parse_billion_Chinese(self):
        from backend.routers.screener import _parse_human_number

        assert _parse_human_number("850亿") == 850e8

    def test_parse_million_Chinese(self):
        from backend.routers.screener import _parse_human_number

        assert _parse_human_number("500万") == 500e4

    def test_parse_trillion_english(self):
        from backend.routers.screener import _parse_human_number

        assert _parse_human_number("3.1T") == 3.1e12

    def test_parse_billion_english(self):
        from backend.routers.screener import _parse_human_number

        assert _parse_human_number("1.2B") == 1.2e8

    def test_parse_million_english(self):
        from backend.routers.screener import _parse_human_number

        assert _parse_human_number("850M") == 850e6

    def test_parse_thousand_english(self):
        from backend.routers.screener import _parse_human_number

        assert _parse_human_number("5K") == 5000.0

    def test_parse_with_percent(self):
        from backend.routers.screener import _parse_human_number

        assert _parse_human_number("+25.4%") == 25.4

    def test_parse_with_commas(self):
        from backend.routers.screener import _parse_human_number

        assert _parse_human_number("1,234,567") == 1234567.0

    def test_parse_none_returns_zero(self):
        from backend.routers.screener import _parse_human_number

        assert _parse_human_number(None) == 0.0

    def test_parse_invalid_string_returns_zero(self):
        from backend.routers.screener import _parse_human_number

        assert _parse_human_number("invalid") == 0.0


class TestCleanJsonDsl:
    """DSL JSON 清理测试"""

    def test_clean_removes_markdown_code_blocks(self):
        from backend.routers.screener import _clean_json_dsl

        dsl = """```json
{"markets": ["US"]}
```"""
        result = _clean_json_dsl(dsl)
        assert result == '{"markets": ["US"]}'

    def test_clean_removes_code_blocks_without_language(self):
        from backend.routers.screener import _clean_json_dsl

        dsl = """```
{"markets": ["US"]}
```"""
        result = _clean_json_dsl(dsl)
        assert result == '{"markets": ["US"]}'

    def test_clean_removes_single_line_comments(self):
        from backend.routers.screener import _clean_json_dsl

        dsl = '{"markets": ["US"]} // this is a comment'
        result = _clean_json_dsl(dsl)
        assert result == '{"markets": ["US"]}'

    def test_clean_removes_multi_line_comments(self):
        from backend.routers.screener import _clean_json_dsl

        dsl = '{"markets": /* comment */ ["US"]}'
        result = _clean_json_dsl(dsl)
        assert result == '{"markets":  ["US"]}'

    def test_clean_preserves_string_content(self):
        from backend.routers.screener import _clean_json_dsl

        dsl = '{"name": "// not a comment"}'
        result = _clean_json_dsl(dsl)
        assert result == '{"name": "// not a comment"}'

    def test_clean_empty_string(self):
        from backend.routers.screener import _clean_json_dsl

        assert _clean_json_dsl("") == ""

    def test_clean_already_clean(self):
        from backend.routers.screener import _clean_json_dsl

        dsl = '{"markets": ["US"], "filters": []}'
        result = _clean_json_dsl(dsl)
        assert result == dsl
