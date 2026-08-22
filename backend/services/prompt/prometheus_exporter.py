"""
Prompt Governance Prometheus Metrics Exporter

将质量指标和 A/B 测试结果导出为监控指标，支持 Grafana 可视化。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Dict, Optional

from prometheus_client import (
    CONTENT_TYPE_LATEST_TEXT_FORMAT,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    Summary,
    generate_latest,
)


@dataclass
class PromptMetricsCollector:
    """自定义 Prometheus Collector for Prompt Governance"""

    # Quality Score Gauges (0-1 scale)
    quality_score_gauge = Gauge(
        "prompt_quality_score",
        "Current quality score for a prompt version (0-1)",
        ["prompt_name", "version"],
    )

    coherence_gauge = Gauge(
        "prompt_coherence_score",
        "Coherence score component (0-1)",
        ["prompt_name", "version"],
    )

    clarity_gauge = Gauge(
        "prompt_clarity_score",
        "Clarity score component (0-1)",
        ["prompt_name", "version"],
    )

    relevance_gauge = Gauge(
        "prompt_relevance_score",
        "Relevance score component (0-1)",
        ["prompt_name", "version"],
    )

    # Feedback Stats Counters
    feedback_up_count = Counter(
        "prompt_feedback_up_total",
        "Total count of thumbs up feedback",
        ["prompt_name", "version"],
    )

    feedback_down_count = Counter(
        "prompt_feedback_down_total",
        "Total count of thumbs down feedback",
        ["prompt_name", "version"],
    )

    feedback_avg_rating = Gauge(
        "prompt_feedback_avg_rating",
        "Average rating score (-1 to 1)",
        ["prompt_name", "version"],
    )

    # A/B Test Result Gauges
    ab_test_improvement = Gauge(
        "ab_test_improvement_rate",
        "A/B test improvement rate",
        ["test_name", "winner_variant"],
    )

    ab_test_traffic_split = Gauge(
        "ab_test_traffic_split",
        "Traffic split percentage for A/B test variant",
        ["test_name", "variant_id"],
    )

    # Version History Counter
    version_history_counter = Counter(
        "prompt_version_created_total",
        "Total number of prompt versions created",
        ["prompt_name", "version"],
    )

    # Timing Metrics
    golden_dataset_runtime_histogram = Histogram(
        "golden_dataset_regression_seconds",
        "Time spent running Golden Dataset regression test",
        ["prompt_name"],
        buckets=[0.1, 0.5, 1.0, 2.5, 5.0, 10.0],
    )

    llm_evaluation_latency_summary = Summary(
        "llm_evaluation_latency_seconds",
        "Latency of LLM-driven evaluation",
        ["prompt_name"],
        buckets=[0.5, 1.0, 2.5, 5.0, 10.0, 30.0],
    )

    vector_search_time = Histogram(
        "vector_search_similarity_seconds",
        "Time spent searching similar prompts",
        ["top_k"],
        buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0],
    )

    # Alert Thresholds
    quality_threshold_warning = 0.6
    quality_threshold_critical = 0.5

    def __post_init__(self):
        """Register collector with Prometheus registry"""
        from prometheus_client import REGISTRY

        try:
            REGISTRY.unregister(self)
        except KeyError:
            pass  # Not registered yet

        REGISTRY.register(self)


class PrometheusExporter:
    """导出所有 Prompt Governance 指标"""

    def __init__(self):
        self.collector = PromptMetricsCollector()
        self.registry = CollectorRegistry()

    def export_quality_metrics(
        self,
        prompt_name: str,
        version: str,
        quality_score: float,
        coherence: float,
        clarity: float,
        relevance: float,
    ):
        """导出单个 Prompt 的质量指标"""
        self.collector.quality_score_gauge.labels(prompt_name=prompt_name, version=version).set(quality_score)

        self.collector.coherence_gauge.labels(prompt_name=prompt_name, version=version).set(coherence)

        self.collector.clarity_gauge.labels(prompt_name=prompt_name, version=version).set(clarity)

        self.collector.relevance_gauge.labels(prompt_name=prompt_name, version=version).set(relevance)

    def export_feedback_stats(
        self,
        prompt_name: str,
        version: str,
        up_count: int,
        down_count: int,
        avg_rating: float,
    ):
        """导出反馈统计指标"""
        self.collector.feedback_up_count.labels(prompt_name=prompt_name, version=version).inc(up_count)

        self.collector.feedback_down_count.labels(prompt_name=prompt_name, version=version).inc(down_count)

        self.collector.feedback_avg_rating.labels(prompt_name=prompt_name, version=version).set(avg_rating)

    def export_ab_test_results(
        self,
        test_name: str,
        winner_variant: str,
        improvement: float,
        traffic_splits: Dict[str, float],
    ):
        """导出 A/B 测试结果"""
        self.collector.ab_test_improvement.labels(test_name=test_name, winner_variant=winner_variant).set(improvement)

        for variant_id, split in traffic_splits.items():
            self.collector.ab_test_traffic_split.labels(test_name=test_name, variant_id=variant_id).set(split)

    def record_version_creation(
        self,
        prompt_name: str,
        version: str,
    ):
        """记录版本创建事件"""
        self.collector.version_history_counter.labels(prompt_name=prompt_name, version=version).inc()

    def measure_golden_dataset_runtime(
        self,
        prompt_name: str,
    ):
        """装饰器：测量 Golden Dataset 回归测试耗时"""

        def decorator(func):
            async def wrapper(*args, **kwargs):
                start_time = time.time()
                try:
                    result = await func(*args, **kwargs)
                    return result
                finally:
                    elapsed = time.time() - start_time
                    self.collector.golden_dataset_runtime_histogram.labels(prompt_name=prompt_name).observe(elapsed)

            return wrapper

        return decorator

    def measure_llm_evaluation_latency(
        self,
        prompt_name: str,
    ):
        """装饰器：测量 LLM 评估耗时"""

        def decorator(func):
            async def wrapper(*args, **kwargs):
                start_time = time.time()
                try:
                    result = await func(*args, **kwargs)
                    return result
                finally:
                    elapsed = time.time() - start_time
                    self.collector.llm_evaluation_latency_summary.labels(prompt_name=prompt_name).observe(elapsed)

            return wrapper

        return decorator

    def get_metrics_text(self) -> str:
        """获取 Prometheus 格式的所有指标文本"""
        return generate_latest(self.registry).decode("utf-8")

    def get_metrics_json(self) -> Dict[str, any]:
        """获取指标 JSON 格式（用于 API 响应）"""
        text = self.get_metrics_text()
        lines = text.split("\n")

        metrics_dict = {}

        for line in lines:
            if not line or line.startswith("#"):
                continue

            parts = line.split("{")
            metric_name = parts[0].strip()

            if "{" in line:
                labels_part = parts[1].rstrip("}").split("}")
                labels = {}
                for label_pair in labels_part:
                    if "=" in label_pair:
                        key, value = label_pair.split("=", 1)
                        labels[key.strip()] = value.strip().replace('"', "")

                value = parts[-1].strip()

                if metric_name not in metrics_dict:
                    metrics_dict[metric_name] = []

                metrics_dict[metric_name].append(
                    {
                        "labels": labels,
                        "value": float(value),
                    }
                )

        return metrics_dict


# Global singleton instance
_exporter_instance: Optional[PrometheusExporter] = None


def get_prometheus_exporter() -> PrometheusExporter:
    """获取全局 Prometheus Exporter 单例"""
    global _exporter_instance
    if _exporter_instance is None:
        _exporter_instance = PrometheusExporter()
    return _exporter_instance


async def initialize_prometheus_metrics(llm_client=None):
    """初始化 Prometheus 指标系统"""
    global _exporter_instance

    from backend.services.prompt.governance_service import (
        get_prompt_governance_service,
    )

    service = get_prompt_governance_service()

    # Index all existing prompts as metrics
    manager = service.version_manager
    exporter = get_prometheus_exporter()

    for name in manager.templates.keys():
        template = manager.load_template(name)

        if template.versions:
            latest_version = template.versions[-1]

            # Evaluate quality
            evaluator = service._evaluate_quality(latest_version.content)

            exporter.export_quality_metrics(
                prompt_name=name,
                version=latest_version.version,
                quality_score=evaluator.composite_score or 0.0,
                coherence=evaluator.coherence or 0.0,
                clarity=evaluator.clarity or 0.0,
                relevance=evaluator.relevance or 0.0,
            )

            # Record version creation
            exporter.record_version_creation(name, latest_version.version)

    print(f"✅ [PrometheusMetrics] Initialized {len(manager.templates)} prompt metrics")


# FastAPI endpoint for metrics export
def create_metrics_endpoint(app=None):
    """创建 /metrics HTTP endpoint（供 Prometheus scrape）"""
    if app is None:
        from fastapi import FastAPI

        app = FastAPI()

    @app.get("/metrics")
    async def metrics():
        """Prometheus metrics endpoint"""
        from fastapi.responses import PlainTextResponse

        exporter = get_prometheus_exporter()
        return PlainTextResponse(
            content=exporter.get_metrics_text(),
            media_type=CONTENT_TYPE_LATEST_TEXT_FORMAT,
        )

    return app
