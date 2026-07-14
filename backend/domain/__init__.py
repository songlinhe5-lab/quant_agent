"""
Domain 包（BE-ARCH-01 / BE-ARCH-02）

跨模块稳定 Port 定义于此。策略运行时 Port/合约归属 `backend/engine/`（BT-01）。
DTO 继续用 `backend/schemas/`，避免过早复制。
"""

from backend.domain.ports import BrokerPort, QuotePort

__all__ = ["QuotePort", "BrokerPort"]
