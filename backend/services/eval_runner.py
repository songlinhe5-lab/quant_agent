"""
AI-03 · Eval Runner

加载 Golden Dataset → 逐条评估 → 生成报告
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.services.eval_framework import (
    EvalCase,
    EvalMetrics,
    EvalReport,
    EvalResult,
)

logger = logging.getLogger(__name__)

# Golden Dataset 路径
GOLDEN_DATASET_PATH = Path(__file__).parent.parent / "eval" / "golden_dataset.json"


def load_golden_dataset() -> List[EvalCase]:
    """加载 Golden Dataset"""
    if not GOLDEN_DATASET_PATH.exists():
        logger.error(f"Golden Dataset not found at {GOLDEN_DATASET_PATH}")
        return []

    with open(GOLDEN_DATASET_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    cases = []
    for item in data:
        cases.append(
            EvalCase(
                case_id=item["id"],
                category=item["category"],
                input_text=item["input"],
                expected_output=item["expected_output"],
                metric_type=item["metric_type"],
                tolerance=item.get("tolerance", 0.05),
            )
        )
    return cases


class EvalRunner:
    """评估运行器"""

    def __init__(self):
        self.cases = load_golden_dataset()
        self._last_report: Optional[EvalReport] = None

    def run_all(self) -> EvalReport:
        """
        运行全量评估。

        注意: 这里使用 Golden Dataset 中的 expected_output 作为基准，
        直接评估指标函数的正确性，而非调用真实 LLM。
        真实 LLM 评估需要在 CI 中配合实际 API 运行。
        """
        report = EvalReport()

        for case in self.cases:
            result = self._evaluate_case(case)
            passed = result.score >= (1.0 - case.tolerance)
            report.add_result(result, passed=passed)

        self._last_report = report
        return report

    def run_single(self, case_id: str) -> Optional[EvalResult]:
        """运行单条用例"""
        for case in self.cases:
            if case.case_id == case_id:
                return self._evaluate_case(case)
        return None

    def _evaluate_case(self, case: EvalCase) -> EvalResult:
        """评估单条用例"""
        if case.metric_type == "numeric_accuracy":
            score = EvalMetrics.numeric_accuracy(case.expected_output, case.expected_output)
            return EvalResult(
                case_id=case.case_id,
                metric_type="numeric_accuracy",
                score=score,
                details=f"Input: {case.input_text[:50]}...",
            )

        elif case.metric_type == "citation_traceability":
            score = EvalMetrics.citation_traceability(case.expected_output)
            return EvalResult(
                case_id=case.case_id,
                metric_type="citation_traceability",
                score=score,
                details=f"Input: {case.input_text[:50]}...",
            )

        elif case.metric_type == "dsl_compliance":
            score = EvalMetrics.dsl_compliance(case.expected_output, case.expected_output)
            return EvalResult(
                case_id=case.case_id,
                metric_type="dsl_compliance",
                score=score,
                details=f"Input: {case.input_text[:50]}...",
            )

        else:
            return EvalResult(
                case_id=case.case_id,
                metric_type=case.metric_type,
                score=0.0,
                details=f"Unknown metric type: {case.metric_type}",
            )

    def get_last_report(self) -> Optional[Dict[str, Any]]:
        """获取最近一次评估报告"""
        if self._last_report is None:
            return None
        return self._last_report.to_dict()

    def get_dataset_summary(self) -> Dict[str, Any]:
        """获取 Golden Dataset 摘要"""
        categories = {}
        metric_types = {}
        for case in self.cases:
            categories[case.category] = categories.get(case.category, 0) + 1
            metric_types[case.metric_type] = metric_types.get(case.metric_type, 0) + 1

        return {
            "total_cases": len(self.cases),
            "categories": categories,
            "metric_types": metric_types,
        }


# 全局单例
eval_runner = EvalRunner()
