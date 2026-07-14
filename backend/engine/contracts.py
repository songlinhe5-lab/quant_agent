"""
BT-01a · 同构引擎核心契约（Pydantic 先行）

定义策略与引擎之间的所有数据契约：
- Bar / QuoteSnapshot：行情数据单元
- OrderIntent / OrderUpdate：订单意图与回报
- Position：持仓快照
- RunManifest：一次运行的可复现性指纹

设计文档：docs/15. 回测实盘同构引擎设计.md §三
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from backend.schemas.domain import OrderStatus


# ─────────────────────────────────────────────
# 行情数据契约
# ─────────────────────────────────────────────


class Bar(BaseModel):
    """单根 K 线（bar 收盘时间语义）"""

    symbol: str
    dt: datetime = Field(description="bar 收盘时间（时区感知，UTC）")
    open: float
    high: float
    low: float
    close: float
    volume: float
    ktype: str = Field(default="K_DAY", description="K线周期：K_DAY / K_60M / ...")

    @field_validator("dt")
    @classmethod
    def _dt_must_be_utc(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("Bar.dt must be timezone-aware (UTC)")
        return v


class QuoteSnapshot(BaseModel):
    """实时行情快照"""

    symbol: str
    dt: datetime
    price: float
    bid: Optional[float] = None
    ask: Optional[float] = None
    stale: bool = Field(default=False, description="数据降级标识（STALE 规范）")

    @field_validator("dt")
    @classmethod
    def _dt_must_be_utc(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("QuoteSnapshot.dt must be timezone-aware (UTC)")
        return v


# ─────────────────────────────────────────────
# 订单契约
# ─────────────────────────────────────────────


class OrderIntent(BaseModel):
    """策略产出的下单意图——唯一的执行入口契约"""

    symbol: str
    side: Literal["BUY", "SELL"]
    qty: int = Field(gt=0, description="下单数量（整数股）")
    order_type: Literal["MARKET", "LIMIT"] = "MARKET"
    limit_price: Optional[float] = Field(default=None, description="限价单价格")
    stop_loss: Optional[float] = Field(default=None, description="止损价")
    tag: Optional[str] = Field(default=None, description="策略自定义标签，贯穿至成交回报")

    @model_validator(mode="after")
    def _limit_price_required_for_limit(self) -> "OrderIntent":
        if self.order_type == "LIMIT" and self.limit_price is None:
            raise ValueError("LIMIT order requires limit_price")
        return self


class OrderUpdate(BaseModel):
    """订单回报（状态统一后的规范化枚举）"""

    order_id: str
    intent_tag: Optional[str] = None
    status: OrderStatus
    filled_qty: int = Field(default=0, ge=0)
    avg_fill_price: Optional[float] = None


# ─────────────────────────────────────────────
# 持仓契约
# ─────────────────────────────────────────────


class Position(BaseModel):
    """策略视角的持仓快照"""

    symbol: str
    qty: int = Field(default=0, ge=0, description="持仓数量")
    avg_cost: float = Field(default=0.0, description="持仓均价")
    market_value: float = Field(default=0.0, description="当前市值")
    unrealized_pnl: float = Field(default=0.0, description="未实现盈亏")

    @property
    def is_flat(self) -> bool:
        return self.qty == 0


# ─────────────────────────────────────────────
# 运行指纹（BT-02 插座）
# ─────────────────────────────────────────────


class RunManifest(BaseModel):
    """一次运行的可复现性指纹（BT-02）

    绑定：code_hash + data_snapshot_id/manifest_hash + params + random_seed。
    """

    run_id: str = Field(description="uuid")
    mode: Literal["backtest", "paper", "live"]
    code_hash: str = Field(description="策略源码 sha256")
    params: Dict[str, Any] = Field(default_factory=dict)
    data_snapshot_id: Optional[str] = Field(default=None, description="snap_YYYYMMDD | latest_published")
    manifest_hash: Optional[str] = Field(default=None, description="数据湖 manifest 指纹")
    random_seed: Optional[int] = None
    engine_version: str = Field(default="1.0.0")
    data_mode: Literal["snapshot", "live", "unbound"] = Field(default="unbound")
    reproducible: bool = Field(default=False, description="是否满足正式可复现条件")

    @staticmethod
    def compute_code_hash(source_code: str) -> str:
        """计算策略源码的 sha256 hash"""
        return hashlib.sha256(source_code.encode("utf-8")).hexdigest()

    def to_summary(self) -> Dict[str, Any]:
        """API / 报告页徽章用摘要（FE-PROD-04）。"""
        return {
            "run_id": self.run_id,
            "code_hash": self.code_hash,
            "data_snapshot_id": self.data_snapshot_id,
            "manifest_hash": self.manifest_hash,
            "random_seed": self.random_seed,
            "data_mode": self.data_mode,
            "reproducible": self.reproducible,
            "engine_version": self.engine_version,
        }

    def to_json(self) -> str:
        """序列化为确定性 JSON（用于持久化/比对）"""
        return json.dumps(self.model_dump(), sort_keys=True, default=str)
