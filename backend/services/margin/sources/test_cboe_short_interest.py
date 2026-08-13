"""CboeShortInterestSource 单元测试（免费做空持仓 CSV 兜底源）"""

import sys
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from backend.services.margin.sources.cboe import CboeShortInterestSource

# 真实字段结构的精简样本（BATS/BATS-Symbol header）
SAMPLE_CSV = """Cycle Settlement Date,BATS-Symbol,Security Name,# Shares Net Short Current Cycle,# Shares Net Short Previous Cycle,Cycle Avg Daily Trade Vol,Min # of Trade Days To Cover Shorts,Percent Change in Short Position,Change in Short Position From Previous
20260731,AAPL,APPLE INC,1000000,900000,200000,5.00,11.11,100000
20260731,MSFT,MICROSOFT CORP,2000000,1900000,500000,4.00,5.26,100000
20260731,TSLA,TESLA INC,500000,600000,250000,2.00,-16.67,-100000
20260731,ZZZNONETICKER,,0,0,0,0.00,0.00,0
"""


@pytest.mark.asyncio
async def test_cboe_aggregate_market_level():
    """聚合应产出全市场做空总股数 + 回补天数，并标记 cboe 源"""
    src = CboeShortInterestSource()
    with patch.object(src, "_http_get_text", new=AsyncMock(return_value=SAMPLE_CSV)):
        snap = await src.fetch(date(2026, 8, 13))
    assert snap is not None
    # 总做空股数 = 1M + 2M + 0.5M = 3.5M（ZZZ 行无效被跳过）
    assert snap.short_interest_shares == 3_500_000
    # 市场级回补天数 = 总做空 / 总日均量 = 3.5M / (0.2M+0.5M+0.25M=0.95M) ≈ 3.6842
    assert snap.short_interest_ratio is not None
    assert abs(snap.short_interest_ratio - (3_500_000 / 950_000)) < 1e-3
    assert "cboe_short_interest" in snap.sources
    assert "AAPL" not in snap.note  # note 是市场级汇总，不列个股


@pytest.mark.asyncio
async def test_cboe_lookback_finds_latest():
    """当天无文件时应向前探测命中最近有效 CSV"""
    src = CboeShortInterestSource()

    async def fake_get(url: str) -> str:
        # 仅当日期为 20260801 时返回有效 CSV，模拟"当天(0813)未发布，向前命中0812/0801)"
        if "Bats_Listed_Short_Interest-finra-20260801.csv" in url:
            return SAMPLE_CSV
        return ""  # 其它日期无文件

    with patch.object(src, "_http_get_text", new=fake_get):
        snap = await src.fetch(date(2026, 8, 13))
    assert snap is not None
    assert snap.short_interest_shares == 3_500_000


@pytest.mark.asyncio
async def test_cboe_all_fail_returns_none():
    """全部探测失败应返回 None（零幻觉，不写假数据）"""
    src = CboeShortInterestSource()
    with patch.object(src, "_http_get_text", new=AsyncMock(return_value="")):
        snap = await src.fetch(date(2026, 8, 13))
    assert snap is None
