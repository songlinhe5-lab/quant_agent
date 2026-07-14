"""
AI-01 (能力) · Multi-Agent 深度研报流水线

三段流水线:
1. ClusterDiscoveryAgent — 聚类发现: 收集新闻 + 基本面 → 识别关键主题
2. DataDeepDiveAgent — 数据深挖: 深入阅读研报 + 知识库检索
3. ChartDeliveryAgent — 图表交付: 生成最终 Markdown 研报 + ECharts 配置
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List

from backend.services.llm_service import ModelTier, llm_service

logger = logging.getLogger(__name__)


@dataclass
class ResearchFinding:
    """单条研究发现"""
    theme: str
    summary: str
    source: str = ""
    relevance: float = 0.0


@dataclass
class ResearchReport:
    """深度研报"""
    topic: str
    symbols: List[str]
    executive_summary: str = ""
    findings: List[ResearchFinding] = field(default_factory=list)
    deep_analysis: str = ""
    chart_configs: List[Dict[str, Any]] = field(default_factory=list)
    references: List[str] = field(default_factory=list)
    markdown_content: str = ""


class ClusterDiscoveryAgent:
    """
    阶段 1: 聚类发现 Agent

    输入: topic + symbols
    调用: 新闻/基本面数据收集
    输出: 关键发现列表 (主题聚类 + 异常信号)
    """

    async def run(self, topic: str, symbols: List[str]) -> List[ResearchFinding]:
        """执行聚类发现"""
        findings: List[ResearchFinding] = []

        # 1. 构建数据收集 prompt
        symbols_str = ", ".join(symbols) if symbols else "N/A"
        prompt = f"""作为华尔街顶级量化分析师，请针对以下主题和标的进行聚类分析：

主题: {topic}
监控标的: {symbols_str}

请识别以下维度的关键发现：
1. 行业趋势与竞争格局变化
2. 财务数据异常信号 (营收/利润/现金流)
3. 市场情绪与资金流向
4. 宏观政策影响

请以 JSON 格式输出：
{{"findings": [{{"theme": "主题", "summary": "摘要", "relevance": 0.8}}]}}"""

        try:
            from pydantic import BaseModel

            class FindingsResponse(BaseModel):
                findings: List[Dict[str, Any]]

            result = await llm_service.generate_pydantic(
                prompt=prompt,
                response_model=FindingsResponse,
                system_prompt="你是华尔街顶级量化分析师，擅长从数据中发现投资主题。",
                tier=ModelTier.FLAGSHIP,
            )

            for f in result.findings:
                findings.append(
                    ResearchFinding(
                        theme=f.get("theme", ""),
                        summary=f.get("summary", ""),
                        relevance=f.get("relevance", 0.5),
                    )
                )
        except Exception as e:
            logger.warning(f"[ClusterDiscovery] LLM 调用失败: {e}")
            # 降级: 返回基础发现
            findings.append(
                ResearchFinding(
                    theme="数据收集异常",
                    summary=f"LLM 调用失败，请稍后重试: {str(e)[:100]}",
                    relevance=0.0,
                )
            )

        return findings


class DataDeepDiveAgent:
    """
    阶段 2: 数据深挖 Agent

    输入: 阶段 1 的关键发现
    调用: 知识库检索 + 深入分析
    输出: 深度分析段落
    """

    async def run(self, topic: str, findings: List[ResearchFinding]) -> str:
        """执行数据深挖"""
        findings_text = "\n".join(
            f"- [{f.theme}] {f.summary}" for f in findings
        )

        prompt = f"""基于以下聚类发现，请进行深入分析：

主题: {topic}

关键发现:
{findings_text}

请从以下角度进行深入分析：
1. 驱动因素分析 (为什么会出现这些现象)
2. 历史对比 (与历史类似情况对比)
3. 风险评估 (潜在的下行风险)
4. 投资建议 (基于分析的操作建议)

请用专业的金融语言输出分析结果，控制在 800 字以内。"""

        try:
            client = llm_service.get_client(ModelTier.FLAGSHIP)
            response = await client.chat.completions.create(
                model=llm_service.get_model(ModelTier.FLAGSHIP),
                messages=[
                    {"role": "system", "content": "你是华尔街资深研究分析师，擅长深度研报撰写。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
            )
            llm_service.router.record_success(ModelTier.FLAGSHIP)
            return response.choices[0].message.content or ""
        except Exception as e:
            llm_service.router.record_failure(ModelTier.FLAGSHIP)
            logger.warning(f"[DataDeepDive] LLM 调用失败: {e}")
            return f"深度分析暂时不可用: {str(e)[:100]}"


class ChartDeliveryAgent:
    """
    阶段 3: 图表交付 Agent

    输入: 深度分析结果
    输出: 最终 Markdown 研报 + ECharts 配置
    """

    async def run(
        self,
        topic: str,
        symbols: List[str],
        findings: List[ResearchFinding],
        deep_analysis: str,
    ) -> ResearchReport:
        """组装最终研报"""
        # 构建 Markdown 研报
        sections = [
            f"# {topic} 深度研报\n",
            f"**监控标的**: {', '.join(symbols)}\n",
            "## 核心发现\n",
        ]

        for i, f in enumerate(findings, 1):
            sections.append(f"{i}. **{f.theme}**: {f.summary}\n")

        sections.append("\n## 深度分析\n")
        sections.append(deep_analysis)
        sections.append("\n## 风险提示\n")
        sections.append("- 以上分析仅供参考，不构成投资建议\n")
        sections.append("- 市场有风险，投资需谨慎\n")

        markdown_content = "\n".join(sections)

        return ResearchReport(
            topic=topic,
            symbols=symbols,
            executive_summary=findings[0].summary if findings else "",
            findings=findings,
            deep_analysis=deep_analysis,
            chart_configs=[],
            references=[],
            markdown_content=markdown_content,
        )


class DeepResearchPipeline:
    """深度研报三段流水线"""

    def __init__(self):
        self.cluster_agent = ClusterDiscoveryAgent()
        self.deepdive_agent = DataDeepDiveAgent()
        self.delivery_agent = ChartDeliveryAgent()

    async def run(self, topic: str, symbols: List[str]) -> ResearchReport:
        """
        执行完整流水线:
        1. 聚类发现 → 2. 数据深挖 → 3. 图表交付
        """
        logger.info(f"[DeepResearch] 开始生成研报: {topic}, symbols={symbols}")

        # Stage 1: 聚类发现
        findings = await self.cluster_agent.run(topic, symbols)
        logger.info(f"[DeepResearch] Stage 1 完成: {len(findings)} 条发现")

        # Stage 2: 数据深挖
        deep_analysis = await self.deepdive_agent.run(topic, findings)
        logger.info(f"[DeepResearch] Stage 2 完成: {len(deep_analysis)} 字分析")

        # Stage 3: 图表交付
        report = await self.delivery_agent.run(topic, symbols, findings, deep_analysis)
        logger.info("[DeepResearch] Stage 3 完成: 研报生成")

        return report


# 全局单例
deep_research_pipeline = DeepResearchPipeline()
