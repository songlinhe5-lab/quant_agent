"""
AI-03 · Eval 评估框架单元测试

覆盖:
- EvalMetrics 三个指标函数
- Golden Dataset 加载
- EvalRunner 流程
"""


class TestEvalMetricsNumericAccuracy:
    """数字准确率指标"""

    def test_exact_match(self):
        from backend.services.eval_framework import EvalMetrics

        score = EvalMetrics.numeric_accuracy("价格是150.25美元", "当前价格150.25美元")
        assert score == 1.0

    def test_partial_match(self):
        from backend.services.eval_framework import EvalMetrics

        score = EvalMetrics.numeric_accuracy("价格150.25，涨幅2.3%", "价格150.25，涨幅1.5%")
        assert score == 0.5  # 150.25 匹配，2.3% 不匹配

    def test_no_match(self):
        from backend.services.eval_framework import EvalMetrics

        score = EvalMetrics.numeric_accuracy("价格100", "价格200")
        assert score == 0.0

    def test_no_expected_numbers(self):
        from backend.services.eval_framework import EvalMetrics

        score = EvalMetrics.numeric_accuracy("没有数字", "也没有数字")
        assert score == 1.0

    def test_percentage_match(self):
        from backend.services.eval_framework import EvalMetrics

        score = EvalMetrics.numeric_accuracy("涨幅2.3%", "上涨2.3%")
        assert score == 1.0


class TestEvalMetricsCitationTraceability:
    """引用溯源率指标"""

    def test_all_citations_present(self):
        from backend.services.eval_framework import EvalMetrics

        text = "分析内容[1]和[2]。\n\n📚 参考文献：\n[1] 来源A\n[2] 来源B"
        score = EvalMetrics.citation_traceability(text)
        assert score == 1.0

    def test_missing_citations(self):
        from backend.services.eval_framework import EvalMetrics

        text = "分析内容[1]和[3]。\n\n📚 参考文献：\n[1] 来源A"
        score = EvalMetrics.citation_traceability(text)
        assert score == 0.5  # [1] 有，[3] 缺失

    def test_no_references_section(self):
        from backend.services.eval_framework import EvalMetrics

        text = "分析内容[1]但没有参考文献"
        score = EvalMetrics.citation_traceability(text)
        assert score == 0.0

    def test_no_citations_at_all(self):
        from backend.services.eval_framework import EvalMetrics

        text = "纯文本无引用"
        score = EvalMetrics.citation_traceability(text)
        assert score == 1.0

    def test_no_citations_no_refs(self):
        from backend.services.eval_framework import EvalMetrics

        text = "无引用的纯文本"
        score = EvalMetrics.citation_traceability(text)
        assert score == 1.0


class TestEvalMetricsDSLCompliance:
    """DSL 合规率指标"""

    def test_exact_match(self):
        from backend.services.eval_framework import EvalMetrics

        score = EvalMetrics.dsl_compliance("pe < 15", "pe < 15")
        assert score == 1.0

    def test_case_insensitive(self):
        from backend.services.eval_framework import EvalMetrics

        score = EvalMetrics.dsl_compliance("PE < 15", "pe < 15")
        assert score == 1.0

    def test_partial_match(self):
        from backend.services.eval_framework import EvalMetrics

        score = EvalMetrics.dsl_compliance("pe < 15 AND rsi < 30", "pe < 15")
        assert 0 < score < 1.0

    def test_no_match(self):
        from backend.services.eval_framework import EvalMetrics

        score = EvalMetrics.dsl_compliance("pe < 15", "market_cap > 100")
        assert score == 0.0

    def test_whitespace_normalization(self):
        from backend.services.eval_framework import EvalMetrics

        score = EvalMetrics.dsl_compliance("pe  <  15", "pe < 15")
        assert score == 1.0


class TestEvalMetricsOverallScore:
    """加权综合分"""

    def test_all_perfect(self):
        from backend.services.eval_framework import EvalMetrics

        score = EvalMetrics.overall_score(
            {
                "numeric_accuracy": 1.0,
                "citation_traceability": 1.0,
                "dsl_compliance": 1.0,
            }
        )
        assert score == 1.0

    def test_partial_scores(self):
        from backend.services.eval_framework import EvalMetrics

        score = EvalMetrics.overall_score(
            {
                "numeric_accuracy": 0.5,
                "citation_traceability": 1.0,
                "dsl_compliance": 0.0,
            }
        )
        # 0.5*0.4 + 1.0*0.3 + 0.0*0.3 = 0.2 + 0.3 + 0.0 = 0.5
        assert abs(score - 0.5) < 0.01

    def test_empty_metrics(self):
        from backend.services.eval_framework import EvalMetrics

        score = EvalMetrics.overall_score({})
        assert score == 0.0


class TestGoldenDataset:
    """Golden Dataset 加载"""

    def test_load_dataset(self):
        from backend.services.eval_runner import load_golden_dataset

        cases = load_golden_dataset()
        assert len(cases) >= 50

    def test_dataset_categories(self):
        from backend.services.eval_runner import load_golden_dataset

        cases = load_golden_dataset()
        categories = {c.category for c in cases}
        assert "normal" in categories
        assert "boundary" in categories
        assert "failure" in categories

    def test_dataset_metric_types(self):
        from backend.services.eval_runner import load_golden_dataset

        cases = load_golden_dataset()
        metric_types = {c.metric_type for c in cases}
        assert "numeric_accuracy" in metric_types
        assert "citation_traceability" in metric_types
        assert "dsl_compliance" in metric_types


class TestEvalRunner:
    """EvalRunner 流程"""

    def test_run_all(self):
        from backend.services.eval_runner import EvalRunner

        runner = EvalRunner()
        report = runner.run_all()
        assert report.total_cases >= 50
        report_dict = report.to_dict()
        assert report_dict["average_score"] > 0.0

    def test_run_single(self):
        from backend.services.eval_runner import EvalRunner

        runner = EvalRunner()
        result = runner.run_single("eval-001")
        assert result is not None
        assert result.case_id == "eval-001"
        assert result.score == 1.0

    def test_run_single_not_found(self):
        from backend.services.eval_runner import EvalRunner

        runner = EvalRunner()
        result = runner.run_single("nonexistent")
        assert result is None

    def test_get_dataset_summary(self):
        from backend.services.eval_runner import EvalRunner

        runner = EvalRunner()
        summary = runner.get_dataset_summary()
        assert summary["total_cases"] >= 50
        assert "normal" in summary["categories"]

    def test_get_last_report(self):
        from backend.services.eval_runner import EvalRunner

        runner = EvalRunner()
        assert runner.get_last_report() is None
        runner.run_all()
        report = runner.get_last_report()
        assert report is not None
        assert "total_cases" in report
