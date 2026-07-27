"""AI-01: 市场指挥中心·异动解说员"""

from backend.services.ai_narrator.models import NarrativeRequest, NarrativeResult
from backend.services.ai_narrator.service import AiNarratorService

__all__ = ["NarrativeRequest", "NarrativeResult", "AiNarratorService"]
