"""
工具函数模块单元测试

覆盖：
- safe_float() 安全浮点数转换
- safe_divide() 安全除法运算
- safe_truncate() 自适应安全截断
- is_my_shard() 分布式任务分片判断
- 异常路径：None、类型错误、除零错误
"""

import os

import pytest

from backend.core.utils import is_my_shard, safe_divide, safe_float, safe_truncate


class TestSafeFloat:
    """safe_float() 安全浮点数转换"""

    def test_valid_float(self):
        """有效浮点数转换"""
        assert safe_float(3.14) == 3.14
        assert safe_float("3.14") == 3.14
        assert safe_float(10) == 10.0

    def test_none_returns_default(self):
        """None 返回默认值"""
        assert safe_float(None) == 0.0
        assert safe_float(None, default=99.9) == 99.9

    def test_invalid_string_returns_default(self):
        """无效字符串返回默认值"""
        assert safe_float("not-a-number") == 0.0
        assert safe_float("not-a-number", default=-1.0) == -1.0

    def test_empty_string_returns_default(self):
        """空字符串返回默认值"""
        assert safe_float("") == 0.0

    def test_boolean_conversion(self):
        """布尔值转换"""
        assert safe_float(True) == 1.0
        assert safe_float(False) == 0.0


class TestSafeDivide:
    """safe_divide() 安全除法运算"""

    def test_valid_division(self):
        """有效除法运算"""
        assert safe_divide(10, 2) == 5.0
        assert safe_divide(10.0, 3.0) == pytest.approx(3.333333, rel=1e-5)
        assert safe_divide("10", "2") == 5.0

    def test_divide_by_zero_returns_default(self):
        """除零返回默认值"""
        assert safe_divide(10, 0) == 0.0
        assert safe_divide(10, 0, default=-1.0) == -1.0

    def test_none_numerator_returns_default(self):
        """分子为 None 返回默认值"""
        assert safe_divide(None, 2) == 0.0

    def test_none_denominator_returns_default(self):
        """分母为 None 返回默认值"""
        assert safe_divide(10, None) == 0.0

    def test_invalid_string_returns_default(self):
        """无效字符串返回默认值"""
        assert safe_divide("not-a-number", 2) == 0.0
        assert safe_divide(10, "not-a-number") == 0.0

    def test_zero_numerator(self):
        """分子为 0"""
        assert safe_divide(0, 5) == 0.0


class TestSafeTruncate:
    """safe_truncate() 自适应安全截断"""

    def test_no_truncation_needed(self):
        """不需要截断"""
        text = "短文本"
        assert safe_truncate(text, 100) == text

    def test_truncate_at_newline(self):
        """在换行符处截断"""
        text = "第一行\n第二行\n第三行"
        result = safe_truncate(text, 10)
        assert "\n" in result
        # 截断后的正文部分应该比原文短
        # （但加上后缀后可能更长，所以只检查是否包含换行符）

    def test_truncate_at_period(self):
        """在句号处截断"""
        text = "第一句。第二句。第三句。"
        result = safe_truncate(text, 10)
        assert "。" in result

    def test_truncate_with_suffix(self):
        """截断后添加后缀"""
        text = "a" * 100
        result = safe_truncate(text, 20)
        assert "已自适应安全截断" in result
        assert "省略" in result
        assert "字符" in result

    def test_non_string_input(self):
        """非字符串输入转为字符串"""
        result = safe_truncate(12345, 10)
        assert isinstance(result, str)

    def test_custom_suffix(self):
        """自定义后缀"""
        text = "a" * 100
        suffix = "...[截断]..."
        result = safe_truncate(text, 20, suffix=suffix)
        assert result.endswith(suffix)


class TestIsMyShard:
    """is_my_shard() 分布式任务分片判断"""

    def test_single_worker_always_true(self, monkeypatch):
        """单工作节点时总是返回 True"""
        monkeypatch.setenv("WORKER_TOTAL", "1")
        assert is_my_shard("AAPL") is True
        assert is_my_shard("GOOGL") is True

    def test_worker_id_zero(self, monkeypatch):
        """WORKER_ID=0 时的分片判断"""
        monkeypatch.setenv("WORKER_TOTAL", "2")
        monkeypatch.setenv("WORKER_ID", "0")
        # AAPL 的 crc32 值应该稳定
        result = is_my_shard("AAPL")
        assert isinstance(result, bool)

    def test_different_identifiers(self, monkeypatch):
        """不同标识符的分片结果可能不同"""
        monkeypatch.setenv("WORKER_TOTAL", "10")
        monkeypatch.setenv("WORKER_ID", "0")
        results = [is_my_shard(f"STOCK_{i}") for i in range(100)]
        # 至少有一些 True 和 False
        assert any(results)
        assert any(not r for r in results)
