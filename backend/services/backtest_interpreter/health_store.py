"""AI-03: 回测健康度持久化层 (Redis + 内存兜底)

设计要点 (对齐 BRD-01 早报存储):
- 正常环境写入 Redis (TTL 30 天)，按 ticker 各存最新一份 Walk-Forward 解读结论。
- 无 Redis 时 (本机单测 / 离线) 自动降级为进程内 dict 兜底，保证引擎可独立运行与测试。
- 供盘前早报 generator 拉取，作为「🔬 回测健康度速览」section 的确定性数据源
  (过拟合预警从被动面板升级为主动播报)。
"""

import logging
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from backend.core.redis_client import redis_client
from backend.services.backtest_interpreter.models import WalkForwardInterpretResult

logger = logging.getLogger(__name__)

# 内存兜底 (Redis 不可用时本地可跑)
_MEMORY: dict[str, "BacktestHealthEntry"] = {}

REDIS_TTL = 30 * 24 * 3600
_KEY_PREFIX = "backtest:health:"
_INDEX_KEY = "backtest:health:index"


class BacktestHealthEntry(BaseModel):
    """单标的回测健康度快照 (最近一次 Walk-Forward 解读结论)。"""

    ticker: str
    is_oos_gap: float = 0.0
    alpha_decay: bool = False
    overfit_risk: bool = False
    robustness_ratio: float = 0.0
    oos_sharpe_mean: float = 0.0
    is_sharpe_mean: float = 0.0
    drift_reasons: List[str] = Field(default_factory=list)
    summary: str = ""
    source: str = "fallback"
    model: Optional[str] = None
    updated_at: datetime = Field(default_factory=datetime.now)
    # 联合研判 (主 /interpret 结论：杠杆/Alpha 判别 + Walk-Forward 漂移)
    interpret_summary: str = ""
    leverage: float = 1.0
    has_joint: bool = False


def _entry_from_result(ticker: str, res: WalkForwardInterpretResult) -> BacktestHealthEntry:
    return BacktestHealthEntry(
        ticker=ticker,
        is_oos_gap=res.is_oos_gap,
        alpha_decay=res.alpha_decay,
        overfit_risk=res.overfit_risk,
        robustness_ratio=res.robustness_ratio,
        oos_sharpe_mean=res.oos_sharpe_mean,
        is_sharpe_mean=res.is_sharpe_mean,
        drift_reasons=res.drift_reasons,
        summary=res.summary,
        source=res.source,
        model=res.model,
    )


# Walk-Forward 漂移结论字段 (save_backtest_health 覆盖这些，保留联合研判字段)
_WF_FIELDS = (
    "is_oos_gap",
    "alpha_decay",
    "overfit_risk",
    "robustness_ratio",
    "oos_sharpe_mean",
    "is_sharpe_mean",
    "drift_reasons",
    "summary",
    "source",
    "model",
)


async def _persist(entry: BacktestHealthEntry) -> None:
    _MEMORY[entry.ticker] = entry
    try:
        await redis_client.set(f"{_KEY_PREFIX}{entry.ticker}", entry.model_dump_json(), ex=REDIS_TTL)
        await redis_client.sadd(_INDEX_KEY, entry.ticker)
        await redis_client.expire(_INDEX_KEY, REDIS_TTL)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[BacktestHealth] Redis 写入失败，使用内存兜底: {e}")


async def save_backtest_health(ticker: str, res: WalkForwardInterpretResult) -> None:
    """持久化某标的 Walk-Forward 漂移结论 (覆盖 WF 字段，保留已存的联合研判字段)。"""
    if not ticker:
        return
    entry = _entry_from_result(ticker, res)
    existing = _MEMORY.get(ticker)
    if existing is not None:
        # 只更新 WF 漂移字段，避免覆盖联合研判 (interpret_summary/leverage/has_joint)
        entry = existing.model_copy(update={k: getattr(entry, k) for k in _WF_FIELDS} | {"updated_at": datetime.now()})
    await _persist(entry)


async def save_backtest_interpret(ticker: str, summary: str, leverage: float = 1.0) -> None:
    """持久化主 /interpret 联合结论 (杠杆/Alpha 判别 + Walk-Forward 漂移)，与 WF 漂移合并到同一条目。"""
    if not ticker:
        return
    existing = _MEMORY.get(ticker)
    if existing is not None:
        entry = existing.model_copy(
            update={
                "interpret_summary": summary,
                "leverage": leverage,
                "has_joint": True,
                "updated_at": datetime.now(),
            }
        )
    else:
        entry = BacktestHealthEntry(
            ticker=ticker,
            interpret_summary=summary,
            leverage=leverage,
            has_joint=True,
        )
    await _persist(entry)


async def get_backtest_health(ticker: str) -> Optional[BacktestHealthEntry]:
    if ticker in _MEMORY:
        return _MEMORY[ticker]
    try:
        raw = await redis_client.get(f"{_KEY_PREFIX}{ticker}")
        if raw:
            return BacktestHealthEntry.model_validate_json(raw)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[BacktestHealth] Redis 读取失败: {e}")
    return None


async def get_all_backtest_health() -> List[BacktestHealthEntry]:
    """返回所有标的的最近回测健康度 (按 updated_at 倒序，最新在前)。"""
    entries: List[BacktestHealthEntry] = list(_MEMORY.values())
    try:
        tickers = await redis_client.smembers(_INDEX_KEY)
        for t in tickers:
            tk = t.decode() if isinstance(t, bytes) else str(t)
            if tk not in _MEMORY:
                raw = await redis_client.get(f"{_KEY_PREFIX}{tk}")
                if raw:
                    entries.append(BacktestHealthEntry.model_validate_json(raw))
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[BacktestHealth] Redis 读取索引失败: {e}")
    entries.sort(key=lambda e: e.updated_at, reverse=True)
    return entries
