"""BRD-01: 早报刊物一键生成器服务包"""

from backend.services.morning_briefing.generator import (
    CORE_TICKERS,
    MorningBriefingGenerator,
    generate_morning_briefing,
)
from backend.services.morning_briefing.models import BriefingResult
from backend.services.morning_briefing.storage import (
    get_briefing,
    get_latest_briefing,
    save_briefing,
)

__all__ = [
    "MorningBriefingGenerator",
    "generate_morning_briefing",
    "BriefingResult",
    "save_briefing",
    "get_briefing",
    "get_latest_briefing",
    "CORE_TICKERS",
]
