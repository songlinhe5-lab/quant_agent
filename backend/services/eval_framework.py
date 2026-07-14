"""
AI-03 · Agent Eval 评估框架

- 幻觉检测指标: 数字准确率 / 引用溯源率 / DSL 合规率
- 加权综合评分
"""

import re
from typing import Dict, List, Set, Tuple


class EvalMetrics:
    """LLM 输出质量评估指标集"""

    @staticmethod
    def numeric_accuracy(expected: str, actual: str) -> float:
        """
        数字准确率: 提取文本中所有数字，计算 expected 中的数字在 actual 中出现的比例。

        支持: 整数、小数、百分比、负数
        """
        expected_numbers = EvalMetrics._extract_numbers(expected)
        actual_numbers = EvalMetrics._extract_numbers(actual)

        if not expected_numbers:
            return 1.0  # 无数字期望则满分

        matched = 0
        for num in expected_numbers:
            if num in actual_numbers:
                matched += 1

        return matched / len(expected_numbers)

    @staticmethod
    def citation_traceability(text: str) -> float:
        """
        引用溯源率: 检查正文中的 [X] 引用是否都在文末参考文献列表中出现。

        Returns:
            1.0: 所有引用都有对应参考文献
            0.0: 所有引用都缺失参考文献
        """
        # 分割正文和参考文献
        parts = re.split(r"📚\s*(?:\*\*|\*)?参考文献(?:\*\*|\*)?[:：]?", text)
        if len(parts) < 2:
            # 没有参考文献部分，检查是否有正文引用
            citations = set(re.findall(r"\[(\d+)\]", text))
            return 0.0 if citations else 1.0  # 有引用但无参考文献 → 0分

        main_text = parts[0]
        ref_text = parts[-1]

        # 提取正文引用序号
        citations: Set[str] = set(re.findall(r"\[(\d+)\]", main_text))
        # 提取参考文献序号
        references: Set[str] = set(re.findall(r"\[(\d+)\]", ref_text))

        if not citations:
            return 1.0  # 无引用则满分

        matched = citations & references
        return len(matched) / len(citations)

    @staticmethod
    def dsl_compliance(expected_dsl: str, actual_dsl: str) -> float:
        """
        DSL 合规率: 比较两个 DSL 表达式的语义等价性。

        简化实现: 规范化后比较字符串相等性。
        """
        norm_expected = EvalMetrics._normalize_dsl(expected_dsl)
        norm_actual = EvalMetrics._normalize_dsl(actual_dsl)

        if norm_expected == norm_actual:
            return 1.0

        # 部分匹配: 检查关键 token 的重叠率
        expected_tokens = set(norm_expected.split())
        actual_tokens = set(norm_actual.split())

        if not expected_tokens:
            return 1.0

        overlap = expected_tokens & actual_tokens
        return len(overlap) / len(expected_tokens)

    @staticmethod
    def overall_score(metrics: Dict[str, float]) -> float:
        """
        加权综合分。

        权重:
        - numeric_accuracy: 0.4
        - citation_traceability: 0.3
        - dsl_compliance: 0.3
        """
        weights = {
            "numeric_accuracy": 0.4,
            "citation_traceability": 0.3,
            "dsl_compliance": 0.3,
        }

        total_weight = 0.0
        weighted_sum = 0.0

        for metric_name, weight in weights.items():
            if metric_name in metrics:
                weighted_sum += metrics[metric_name] * weight
                total_weight += weight

        return weighted_sum / total_weight if total_weight > 0 else 0.0

    @staticmethod
    def _extract_numbers(text: str) -> Set[str]:
        """提取文本中的所有数字 (包括小数、百分比、负数)"""
        # 匹配: -123, 12.34, 12.3%, -0.5 等
        pattern = r"-?\d+\.?\d*%?"
        return set(re.findall(pattern, text))

    @staticmethod
    def _normalize_dsl(dsl: str) -> str:
        """规范化 DSL 表达式: 去除空白、统一大小写"""
        return re.sub(r"\s+", " ", dsl.strip().lower())


class EvalCase:
    """单条评估用例"""

    def __init__(
        self,
        case_id: str,
        category: str,
        input_text: str,
        expected_output: str,
        metric_type: str,
        tolerance: float = 0.05,
    ):
        self.case_id = case_id
        self.category = category  # normal / boundary / failure
        self.input_text = input_text
        self.expected_output = expected_output
        self.metric_type = metric_type
        self.tolerance = tolerance


class EvalResult:
    """单条评估结果"""

    def __init__(self, case_id: str, metric_type: str, score: float, details: str = ""):
        self.case_id = case_id
        self.metric_type = metric_type
        self.score = score
        self.details = details


class EvalReport:
    """全量评估报告"""

    def __init__(self):
        self.results: List[EvalResult] = []
        self.total_cases: int = 0
        self.passed_cases: int = 0
        self.failed_cases: int = 0

    def add_result(self, result: EvalResult, passed: bool = True):
        self.results.append(result)
        self.total_cases += 1
        if passed:
            self.passed_cases += 1
        else:
            self.failed_cases += 1

    def to_dict(self) -> Dict:
        avg_score = (
            sum(r.score for r in self.results) / len(self.results)
            if self.results
            else 0.0
        )
        return {
            "total_cases": self.total_cases,
            "passed_cases": self.passed_cases,
            "failed_cases": self.failed_cases,
            "average_score": round(avg_score, 4),
            "results": [
                {
                    "case_id": r.case_id,
                    "metric_type": r.metric_type,
                    "score": round(r.score, 4),
                    "details": r.details,
                }
                for r in self.results
            ],
        }
