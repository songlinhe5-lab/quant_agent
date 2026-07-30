"""单测：app/eval/runner.EvalRunner + load_golden_dataset

覆盖：Golden Dataset 加载（正常 / 文件缺失）、单例评估、三类指标评分
（numeric_accuracy / citation_traceability / dsl_compliance）、未知指标类型归零、
run_all 报告统计与摘要。
"""

import json

import pytest

from backend.app.eval import runner as runner_mod
from backend.app.eval.runner import EvalRunner, load_golden_dataset
from backend.domain.eval_framework import EvalCase

_SAMPLE = [
    {
        "id": "t-1",
        "category": "normal",
        "input": "AAPL 股价",
        "expected_output": "AAPL 当前价格为 150.25 美元",
        "metric_type": "numeric_accuracy",
        "tolerance": 0.05,
    },
    {
        "id": "t-2",
        "category": "normal",
        "input": "分析苹果",
        "expected_output": "苹果分析[1]。\n\n📚 参考文献：\n[1] 苹果基本面",
        "metric_type": "citation_traceability",
        "tolerance": 0.1,
    },
    {
        "id": "t-3",
        "category": "normal",
        "input": "筛选 PE",
        "expected_output": "pe < 15",
        "metric_type": "dsl_compliance",
    },
    {
        "id": "t-4",
        "category": "normal",
        "input": "未知指标",
        "expected_output": "whatever",
        "metric_type": "unknown_metric",
    },
]


@pytest.fixture
def dataset_path(tmp_path, monkeypatch):
    p = tmp_path / "golden_dataset.json"
    p.write_text(json.dumps(_SAMPLE), encoding="utf-8")
    monkeypatch.setattr(runner_mod, "GOLDEN_DATASET_PATH", p)
    return p


def _new_runner(dataset_path):
    return EvalRunner()


def test_load_golden_dataset_parses(dataset_path):
    cases = load_golden_dataset()
    assert len(cases) == 4
    assert all(isinstance(c, EvalCase) for c in cases)
    assert cases[0].case_id == "t-1"
    assert cases[0].tolerance == 0.05
    # 缺省 tolerance 回退 0.05
    assert cases[2].tolerance == 0.05


def test_load_golden_dataset_missing_file_returns_empty(monkeypatch):
    monkeypatch.setattr(runner_mod, "GOLDEN_DATASET_PATH", __import__("pathlib").Path("/nope/missing.json"))
    assert load_golden_dataset() == []


def test_run_single_existing_and_missing(dataset_path):
    runner = EvalRunner()
    res = runner.run_single("t-1")
    assert res is not None
    assert res.case_id == "t-1"
    assert res.metric_type == "numeric_accuracy"
    assert res.score == 1.0  # expected 与 actual 相同
    assert runner.run_single("no-such-id") is None


def test_evaluate_case_numeric_accuracy(dataset_path):
    runner = EvalRunner()
    case = runner.cases[0]
    res = runner._evaluate_case(case)
    assert res.metric_type == "numeric_accuracy"
    assert res.score == 1.0


def test_evaluate_case_citation_traceability(dataset_path):
    runner = EvalRunner()
    case = runner.cases[1]
    res = runner._evaluate_case(case)
    assert res.metric_type == "citation_traceability"
    assert res.score == 1.0


def test_evaluate_case_dsl_compliance(dataset_path):
    runner = EvalRunner()
    case = runner.cases[2]
    res = runner._evaluate_case(case)
    assert res.metric_type == "dsl_compliance"
    assert res.score == 1.0


def test_evaluate_case_unknown_metric_zero(dataset_path):
    runner = EvalRunner()
    case = runner.cases[3]
    res = runner._evaluate_case(case)
    assert res.metric_type == "unknown_metric"
    assert res.score == 0.0
    assert "Unknown metric type" in res.details


def test_run_all_report_counts(dataset_path):
    runner = EvalRunner()
    report = runner.run_all()
    assert report.total_cases == 4
    assert report.passed_cases == 3  # t-1/2/3 满分通过
    assert report.failed_cases == 1  # t-4 未知指标 0 分不通过
    assert runner.get_last_report() is not None
    assert runner.get_last_report()["average_score"] == 0.75


def test_get_dataset_summary(dataset_path):
    runner = EvalRunner()
    summary = runner.get_dataset_summary()
    assert summary["total_cases"] == 4
    assert summary["categories"] == {"normal": 4}
    assert summary["metric_types"]["numeric_accuracy"] == 1
    assert summary["metric_types"]["citation_traceability"] == 1
    assert summary["metric_types"]["dsl_compliance"] == 1
    assert summary["metric_types"]["unknown_metric"] == 1


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
