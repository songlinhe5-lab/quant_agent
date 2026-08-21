"""
AGENT-16-NEXT · Prompt 版本控制与质量检测系统

对标 RAG-style versioning + A/B testing + hot reload。

核心功能：
1. Prompt 版本管理（versioning + rollback）
2. 质量检测指标（perplexity, coherence, relevance）
3. A/B 测试框架（多变体并行测试）
4. 热更新支持（watchdog 机制）
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer


@dataclass
class PromptVersion:
    """单个 Prompt 版本记录"""

    version: str  # semver (e.g., "1.0.0")
    checksum: str  # SHA256 checksum
    content: str  # 实际文本内容
    created_at: float  # Unix timestamp
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Optional A/B test metrics
    ab_test_results: Optional[Dict[str, float]] = None  # {metric_name: score}


@dataclass
class PromptTemplate:
    """Prompt 模板（含版本历史）"""

    name: str  # 模板名称（如 "compact_summary_system_prompt"）
    current_version: str  # 当前活跃版本
    path: Path  # 文件路径

    # 版本历史（按时间排序）
    versions: List[PromptVersion] = field(default_factory=list)

    # Metadata
    description: str = ""
    tags: List[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


@dataclass
class PromptQualityMetrics:
    """Prompt 质量评估指标"""

    perplexity: Optional[float] = None  # 越低越好（语言模型困惑度）
    coherence: Optional[float] = None  # 0-1（连贯性）
    clarity: Optional[float] = None  # 0-1（清晰度）
    relevance: Optional[float] = None  # 0-1（相关性）
    toxicity: Optional[float] = None  # 0-1（毒性/不当内容概率）

    # Composite score (weighted average)
    composite_score: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "perplexity": self.perplexity,
            "coherence": self.coherence,
            "clarity": self.clarity,
            "relevance": self.relevance,
            "toxicity": self.toxicity,
            "composite_score": self.composite_score,
        }


@dataclass
class ABTestConfig:
    """A/B 测试配置"""

    name: str  # 测试名称（如 "compact_prompt_v2_vs_v1"）
    variants: List[Tuple[str, PromptTemplate]]  # [(variant_id, template)]
    metric: str  # 评估指标（如 "token_reduction_rate"）
    traffic_split: Dict[str, float]  # {"v1": 0.5, "v2": 0.5}
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None
    status: str = "running"  # running | completed | cancelled

    def is_active(self) -> bool:
        if self.end_time and time.time() > self.end_time:
            self.status = "completed"
            return False
        return self.status == "running"


class PromptVersionManager:
    """Prompt 版本管理器（RAG-style versioning）"""

    def __init__(self, prompt_dir: str = "prompts/compact"):
        self.prompt_dir = Path(prompt_dir)
        self.prompt_dir.mkdir(parents=True, exist_ok=True)

        # In-memory cache of templates
        self.templates: Dict[str, PromptTemplate] = {}

        # Version history index (for quick lookup)
        self.version_index: Dict[str, List[PromptVersion]] = {}

    def load_template(self, name: str) -> PromptTemplate:
        """从文件加载 Prompt 模板（含所有历史版本）"""
        template_path = self.prompt_dir / f"{name}.md"

        if not template_path.exists():
            return PromptTemplate(name=name, current_version="initial", path=template_path)

        # Load all versions from file (format: ---\nversion: X.Y.Z\n---\ncontent)
        with open(template_path, "r", encoding="utf-8") as f:
            content = f.read()

        versions = self._parse_versions(content)

        if not versions:
            # Create initial version if none found
            initial_version = PromptVersion(
                version="1.0.0",
                checksum=self._compute_checksum(content),
                content=content,
                created_at=time.time(),
            )
            versions = [initial_version]

        # Find latest version (sorted by created_at)
        latest_version = max(versions, key=lambda v: v.created_at)

        template = PromptTemplate(
            name=name,
            current_version=latest_version.version,
            path=template_path,
            versions=versions,
            created_at=versions[0].created_at if versions else time.time(),
            updated_at=latest_version.created_at,
        )

        self.templates[name] = template
        return template

    def _parse_versions(self, content: str) -> List[PromptVersion]:
        """解析文件中的多个版本（YAML frontmatter separator）"""
        versions = []
        parts = content.split("---\n")[1::2]  # Split by YAML frontmatter

        for part in parts:
            lines = part.strip().split("\n", 1)
            if len(lines) < 2:
                continue

            # Parse metadata
            metadata_str = lines[0]
            content_body = lines[1]

            try:
                metadata = yaml.safe_load(metadata_str) or {}
                version = metadata.get("version", "unknown")
                created_at = metadata.get("created_at", time.time())

                versions.append(
                    PromptVersion(
                        version=version,
                        checksum=self._compute_checksum(content_body),
                        content=content_body.strip(),
                        created_at=float(created_at) if isinstance(created_at, (int, float)) else time.time(),
                        metadata=metadata,
                    )
                )
            except Exception:
                continue

        return sorted(versions, key=lambda v: v.created_at)

    def create_version(self, name: str, new_content: str, metadata: Optional[Dict] = None) -> PromptVersion:
        """创建新版本（semver bump）"""
        template = self.templates.get(name) or self.load_template(name)

        # Bump version (major/minor/patch)
        if not template.versions:
            new_version = "1.0.0"
        else:
            latest = template.versions[-1]
            parts = latest.version.split(".")
            minor = int(parts[1]) if len(parts) > 1 else 0
            new_version = f"{parts[0]}.{minor + 1}.0"  # Minor bump by default

        version = PromptVersion(
            version=new_version,
            checksum=self._compute_checksum(new_content),
            content=new_content,
            created_at=time.time(),
            metadata=metadata or {},
        )

        # Append to template
        template.versions.append(version)
        template.current_version = new_version
        template.updated_at = time.time()

        # Save to file
        self._save_template(template)

        return version

    def rollback(self, name: str, target_version: str) -> bool:
        """回滚到指定版本"""
        template = self.templates.get(name)
        if not template:
            return False

        # Find target version
        target = next((v for v in template.versions if v.version == target_version), None)
        if not target:
            return False

        # Update current version
        template.current_version = target_version

        # Rewrite file with only target version
        with open(template.path, "w", encoding="utf-8") as f:
            f.write(f"---\nversion: {target_version}\n---\n{target.content}")

        return True

    def get_variant(self, name: str, version: str) -> Optional[str]:
        """获取特定版本的 Prompt 内容"""
        template = self.templates.get(name)
        if not template:
            return None

        version_obj = next((v for v in template.versions if v.version == version), None)
        return version_obj.content if version_obj else None

    def _save_template(self, template: PromptTemplate):
        """保存模板到文件（追加模式保留历史）"""
        # Build full content with all versions
        parts = []
        for v in template.versions:
            parts.append(f"---\nversion: {v.version}\ncreated_at: {v.created_at}\n---\n{v.content}")

        with open(template.path, "w", encoding="utf-8") as f:
            f.write("\n\n".join(parts))

    def _compute_checksum(self, content: str) -> str:
        """计算 SHA256 checksum"""
        return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


class PromptQualityEvaluator:
    """Prompt 质量评估器（模拟指标计算）"""

    def __init__(self, llm_client: Optional[Any] = None):
        self.llm_client = llm_client

    def evaluate(self, prompt: str, context: Optional[str] = None) -> PromptQualityMetrics:
        """评估 Prompt 质量（多指标综合）"""
        metrics = PromptQualityMetrics()

        # 1. Perplexity (通过 LLM 计算)
        if self.llm_client:
            metrics.perplexity = self._estimate_perplexity(prompt)

        # 2. Coherence (语言连贯性)
        metrics.coherence = self._compute_coherence(prompt)

        # 3. Clarity (清晰度和指令明确性)
        metrics.clarity = self._compute_clarity(prompt)

        # 4. Relevance (与任务的相关性)
        if context:
            metrics.relevance = self._compute_relevance(prompt, context)
        else:
            metrics.relevance = 0.8  # 默认值

        # 5. Toxicity (内容安全性)
        metrics.toxicity = self._estimate_toxicity(prompt)

        # 6. Composite score (加权平均)
        scores = [s for s in [metrics.coherence, metrics.clarity, metrics.relevance] if s is not None]
        if scores:
            metrics.composite_score = sum(scores) / len(scores)

        return metrics

    def _estimate_perplexity(self, prompt: str) -> float:
        """估算困惑度（基于 token 多样性和复杂度）"""
        tokens = prompt.split()
        unique_ratio = len(set(tokens.lower().split())) / len(tokens) if tokens else 1
        return 1.0 - unique_ratio  # 简化版：越多样越低

    def _compute_coherence(self, prompt: str) -> float:
        """计算连贯性（基于句子结构和逻辑连接词）"""
        sentences = prompt.split(".")
        connector_words = ["因此", "所以", "然而", "同时", "此外", "首先", "其次"]

        has_connectors = any(word in prompt for word in connector_words)
        sentence_length_variance = len(set(len(s.split()) for s in sentences)) / len(sentences) if sentences else 0

        score = 0.7 + (0.3 if has_connectors else 0) + min(0.2, sentence_length_variance * 0.05)
        return min(1.0, max(0.0, score))

    def _compute_clarity(self, prompt: str) -> float:
        """计算清晰度（指令明确性 + 无歧义）"""
        has_action_verbs = any(verb in prompt for verb in ["总结", "提取", "分析", "生成", "计算"])
        has_specific_constraints = any(constraint in prompt for constraint in ["不超过", "限制", "≤", "最多"])

        score = 0.6 + (0.2 if has_action_verbs else 0) + (0.2 if has_specific_constraints else 0)
        return min(1.0, max(0.0, score))

    def _compute_relevance(self, prompt: str, context: str) -> float:
        """计算相关性（prompt 与上下文的语义相似度）"""
        # 简化版：基于关键词重叠率
        prompt_words = set(prompt.lower().split())
        context_words = set(context.lower().split())

        if not prompt_words or not context_words:
            return 0.0

        overlap = len(prompt_words & context_words) / len(prompt_words | context_words)
        return overlap

    def _estimate_toxicity(self, prompt: str) -> float:
        """估算毒性（基于敏感词检测）"""
        toxic_patterns = ["垃圾", "愚蠢", "废物", "错误", "失败"]
        toxic_count = sum(1 for pattern in toxic_patterns if pattern in prompt)

        # 1 - (toxic_count / total_words)，但最低不低于 0.9
        words = prompt.split()
        if not words:
            return 0.0

        return max(0.9, 1.0 - (toxic_count / len(words)))


class ABTestOrchestrator:
    """A/B 测试编排器（多 Prompt 变体并行测试）"""

    def __init__(self, version_manager: PromptVersionManager):
        self.version_manager = version_manager
        self.active_tests: Dict[str, ABTestConfig] = {}

    def create_test(
        self,
        name: str,
        variants: List[Tuple[str, str]],  # [(variant_id, version)]
        metric: str,
        traffic_split: Optional[Dict[str, float]] = None,
        duration_hours: Optional[float] = None,
    ) -> ABTestConfig:
        """创建新的 A/B 测试"""
        # Default 50/50 split
        if traffic_split is None:
            traffic_split = {vid: 1.0 / len(variants) for vid, _ in variants}

        # Calculate end time
        end_time = None
        if duration_hours:
            end_time = time.time() + (duration_hours * 3600)

        # Load variant templates
        variant_templates = []
        for variant_id, version in variants:
            template = self.version_manager.load_template("compact_summary_system_prompt")
            content = self.version_manager.get_variant("compact_summary_system_prompt", version)
            if content:
                # Create temporary template
                temp_template = PromptTemplate(
                    name=f"{template.name}_{variant_id}",
                    current_version=version,
                    path=template.path,
                    versions=[PromptVersion(version=version, checksum="", content=content, created_at=time.time())],
                )
                variant_templates.append((variant_id, temp_template))

        config = ABTestConfig(
            name=name,
            variants=variant_templates,
            metric=metric,
            traffic_split=traffic_split,
            end_time=end_time,
        )

        self.active_tests[name] = config
        return config

    def select_variant(self, test_name: str, prompt_context: str) -> Tuple[str, str]:
        """根据流量分配选择 Variant（确定性路由）"""
        test = self.active_tests.get(test_name)
        if not test or not test.is_active():
            # Fallback to first variant
            if test and test.variants:
                return test.variants[0]
            raise ValueError(f"No active A/B test: {test_name}")

        # Deterministic routing based on prompt hash
        hash_value = int(hashlib.md5(prompt_context.encode()).hexdigest(), 16)
        cumulative = 0.0

        for variant_id, _ in test.variants:
            cumulative += test.traffic_split.get(variant_id, 0)
            if hash_value % 1000 < cumulative * 1000:
                return variant_id, test.variants[0][1].current_version

        # Fallback to last variant
        return test.variants[-1][0], test.variants[-1][1].current_version

    def record_metric(self, test_name: str, variant_id: str, metric_value: float):
        """记录测试结果"""
        test = self.active_tests.get(test_name)
        if not test:
            return

        # Update variant results
        for vid, template in test.variants:
            if vid == variant_id:
                if template.versions:
                    version = template.versions[0]
                    if not version.ab_test_results:
                        version.ab_test_results = {}
                    version.ab_test_results[test.metric] = metric_value
                    break

    def get_winner(self, test_name: str) -> Optional[str]:
        """确定获胜 Variant（基于最优指标）"""
        test = self.active_tests.get(test_name)
        if not test or not test.is_active():
            return None

        best_variant = None
        best_score = float("-inf")

        for variant_id, template in test.variants:
            if template.versions and template.versions[0].ab_test_results:
                score = template.versions[0].ab_test_results.get(test.metric, 0)
                if score > best_score:
                    best_score = score
                    best_variant = variant_id

        return best_variant


class PromptHotReloader:
    """Prompt 热更新监听器（watchdog 机制）"""

    def __init__(self, version_manager: PromptVersionManager, callback: callable):
        self.version_manager = version_manager
        self.callback = callback  # 当文件变更时触发的回调函数

        # Setup watchdog observer
        self.observer = Observer()
        self.handler = PromptFileHandler(version_manager, callback)

        # Start watching
        self.observer.schedule(self.handler, str(version_manager.prompt_dir), recursive=False)
        self.observer.start()

    def stop(self):
        """停止监听"""
        self.observer.stop()
        self.observer.join()


class PromptFileHandler(FileSystemEventHandler):
    """Prompt 文件变化事件处理器"""

    def __init__(self, version_manager: PromptVersionManager, callback: callable):
        self.version_manager = version_manager
        self.callback = callback
        self.last_modified: Dict[str, float] = {}  # Rate limiting
        self.MODIFICATION_DELAY = 1.0  # 至少间隔 1 秒才触发

    def on_modified(self, event):
        """文件修改事件"""
        if event.is_directory:
            return

        filepath = Path(event.src_path)
        if filepath.suffix != ".md":
            return

        template_name = filepath.stem

        # Rate limiting
        current_time = time.time()
        last_time = self.last_modified.get(template_name, 0)
        if current_time - last_time < self.MODIFICATION_DELAY:
            return

        self.last_modified[template_name] = current_time

        # Reload template
        try:
            template = self.version_manager.load_template(template_name)
            print(f"✅ [PromptHotReload] {template_name} loaded (version: {template.current_version})")

            # Trigger callback
            self.callback(template_name, template)
        except Exception as e:
            print(f"❌ [PromptHotReload] Failed to reload {template_name}: {e}")


# Try import yaml, fallback to simple parser
try:
    import yaml
except ImportError:
    yaml = None


def parse_yaml_frontmatter(text: str) -> Tuple[Dict[str, Any], str]:
    """简单解析 YAML frontmatter（不依赖 pyyaml）"""
    lines = text.split("\n")
    metadata = {}
    content_start = 0

    for i, line in enumerate(lines[1:], 1):  # Skip first "---"
        if line.startswith("---"):
            content_start = i + 1
            break

        if ":" in line:
            key, value = line.split(":", 1)
            key = key.strip()
            value = value.strip()

            # Simple type conversion
            if value.isdigit():
                value = int(value)
            elif value.replace(".", "").isdigit():
                value = float(value)
            elif value.lower() == "true":
                value = True
            elif value.lower() == "false":
                value = False

            metadata[key] = value

    content = "\n".join(lines[content_start:])
    return metadata, content
