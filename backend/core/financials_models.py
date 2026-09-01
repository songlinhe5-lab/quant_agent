"""
FIN-03 · 财报事实层 ORM（双时间轴）
===================================

financial_facts: 一行 = 一个科目在一个期间的一个「键」，列上带两条时间轴
  - 业务时间（valid time）: period_start / period_end —— 会计期间本身
  - 系统时间（knowability）: filed_as_reported / filed_latest —— 何时可被市场知晓

去重与取值规则（docs/28 §3.2，踩过的坑写死在这）:
  1. 唯一键 = (entity_id, concept, period_start, period_end, unit)，**禁按 fy 去重**
     （比较期与本期共用 fy 标签，按 fy 去重会静默丢数）
  2. value_as_reported = 首次披露值（冻结不改，回测/因子只读这条）
  3. value_latest = 最新值（含重述，「真实走势」看这条）
  4. 两者不等 → restated=True，进重述 diff 面板
  5. PIT 查询一律 filed_as_reported <= as_of

⚠️ period_start 可为 NULL（时点科目），但 PG 的 NULL 互不相等，唯一约束会失效；
   故额外维护非空列 period_start_key（时点值写 ""）承载唯一键。
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from .database import Base

STATEMENTS = ("income", "balance", "cash")


class FinancialFact(Base):
    """标准化财务事实（双时间轴）"""

    __tablename__ = "financial_facts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # 实体与科目
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False)  # US:CIK0000320193 / HK:00700 / CN:600519
    concept: Mapped[str] = mapped_column(String(64), nullable=False)  # concept_map 的 key
    statement: Mapped[str] = mapped_column(String(16), nullable=False)  # income / balance / cash

    # 业务时间轴（valid time）
    period_start: Mapped[Optional[date]] = mapped_column(Date, nullable=True)  # 时点科目为 NULL
    period_start_key: Mapped[str] = mapped_column(String(10), nullable=False, default="")  # 唯一键用，时点值写 ""
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    fiscal_year: Mapped[int] = mapped_column(Integer, nullable=False)
    fiscal_period: Mapped[str] = mapped_column(String(8), nullable=False)  # Q1..Q4 / FY / H1 / 9M
    unit: Mapped[str] = mapped_column(String(16), nullable=False, default="")

    # 取值（双轨）
    value_as_reported: Mapped[float] = mapped_column(Float, nullable=False)
    value_latest: Mapped[float] = mapped_column(Float, nullable=False)
    restated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    derived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)  # Q4 / 累计拆分推导值

    # 系统时间轴（knowability）
    filed_as_reported: Mapped[date] = mapped_column(Date, nullable=False)  # 首次披露日，PIT 过滤用
    filed_latest: Mapped[date] = mapped_column(Date, nullable=False)  # 最近一次涉及该键的申报日

    # 溯源
    accession_no: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)  # EDGAR accn / 公告 id
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="sec")  # sec / futu / tushare
    source_tag: Mapped[str] = mapped_column(String(128), nullable=False, default="")  # 原始标签，便于回溯映射错误
    check_failed: Mapped[Optional[List[str]]] = mapped_column(JSON, nullable=True)  # 勾稽失败项（失败只标注不丢数）

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "entity_id",
            "concept",
            "period_start_key",
            "period_end",
            "unit",
            name="uq_financial_fact",
        ),
        Index("idx_fin_fact_pit", "entity_id", "filed_as_reported"),  # PIT 主查询路径
        Index("idx_fin_fact_period", "entity_id", "concept", "period_end"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "concept": self.concept,
            "statement": self.statement,
            "period_start": self.period_start.isoformat() if self.period_start else None,
            "period_end": self.period_end.isoformat(),
            "fiscal_year": self.fiscal_year,
            "fiscal_period": self.fiscal_period,
            "unit": self.unit,
            "value_as_reported": self.value_as_reported,
            "value_latest": self.value_latest,
            "restated": self.restated,
            "derived": self.derived,
            "filed_as_reported": self.filed_as_reported.isoformat() if self.filed_as_reported else None,
            "filed_latest": self.filed_latest.isoformat() if self.filed_latest else None,
            "accession_no": self.accession_no,
            "source": self.source,
            "source_tag": self.source_tag,
            "check_failed": self.check_failed or [],
        }


class FilingRecord(Base):
    """申报归档索引（原文地址 + RAG 索引状态）"""

    __tablename__ = "filings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False)
    form_type: Mapped[str] = mapped_column(String(16), nullable=False)  # 10-K / 10-Q / 8-K / 年報 / 年度报告
    fiscal_year: Mapped[int] = mapped_column(Integer, nullable=False)
    filed_at: Mapped[date] = mapped_column(Date, nullable=False)
    accession_no: Mapped[str] = mapped_column(String(64), nullable=False)  # EDGAR accn；港A为公告 id
    doc_url: Mapped[str] = mapped_column(Text, nullable=False)
    lang: Mapped[str] = mapped_column(String(4), nullable=False, default="en")
    rag_indexed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        UniqueConstraint("entity_id", "accession_no", name="uq_filings_accn"),
        Index("idx_filings_entity", "entity_id", "filed_at"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "form_type": self.form_type,
            "fiscal_year": self.fiscal_year,
            "filed_at": self.filed_at.isoformat() if self.filed_at else None,
            "accession_no": self.accession_no,
            "doc_url": self.doc_url,
            "lang": self.lang,
            "rag_indexed": self.rag_indexed,
        }


class FinancialsJob(Base):
    """回填任务登记簿（FIN-10 可靠性）：内存 jobs 的 PG 快照。

    写侧是 best-effort 双写（持久化失败不影响内存任务推进，回填本身幂等重放）；
    读侧内存优先、miss 落库——进程重启后任务状态不再凭空消失。
    """

    __tablename__ = "financial_jobs"

    job_id: Mapped[str] = mapped_column(String(32), primary_key=True)  # finbf_{uuid12}
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="sec")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    result: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # ISO 字符串，与内存 job dict 的 created_at/updated_at 同形（快照直灌）
    created_at: Mapped[str] = mapped_column(String(32), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(32), nullable=False)
