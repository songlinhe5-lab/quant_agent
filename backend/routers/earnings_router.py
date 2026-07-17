"""
财报预期对比 API - 存储和管理财报预期基准值
"""

import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from backend.core.database import redis_client

router = APIRouter(prefix="/earnings", tags=["earnings"])


class EarningsExpectation(BaseModel):
    """财报预期基准值"""

    metric: str = Field(..., description="指标名称")
    expected_low: Optional[float] = Field(None, description="预期下限")
    expected_high: Optional[float] = Field(None, description="预期上限")
    expected_value: Optional[float] = Field(None, description="预期值")
    unit: str = Field(default="亿", description="单位")
    scenario: str = Field(default="中性", description="情景")
    notes: str = Field(default="", description="关键假设")


class SetExpectationsRequest(BaseModel):
    """设置预期值请求"""

    ticker: str = Field(..., description="股票代码")
    period: str = Field(..., description="财报周期，如 2026H1")
    expectations: List[EarningsExpectation] = Field(..., description="预期值列表")


@router.get("/expectations")
async def get_expectations(
    ticker: str = Query(..., description="股票代码"),
    period: str = Query(..., description="财报周期"),
) -> Dict[str, Any]:
    """获取财报预期基准值"""
    cache_key = f"quant:earnings:expectations:{ticker}:{period}"

    try:
        cached = await redis_client.get(cache_key)
        if cached:
            return {"status": "success", "data": json.loads(cached)}
        return {"status": "success", "data": []}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.post("/expectations")
async def set_expectations(req: SetExpectationsRequest) -> Dict[str, Any]:
    """设置财报预期基准值"""
    cache_key = f"quant:earnings:expectations:{req.ticker}:{req.period}"

    # 转换为字典列表
    data = [exp.model_dump() for exp in req.expectations]

    try:
        # 存储到 Redis，设置 1 年过期（财报周期较长）
        await redis_client.setex(cache_key, 365 * 24 * 3600, json.dumps(data))
        return {
            "status": "success",
            "message": f"已存储 {req.ticker} {req.period} 的 {len(data)} 条预期值",
            "data": data,
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.delete("/expectations")
async def delete_expectations(
    ticker: str = Query(..., description="股票代码"),
    period: str = Query(..., description="财报周期"),
) -> Dict[str, Any]:
    """删除财报预期基准值"""
    cache_key = f"quant:earnings:expectations:{ticker}:{period}"

    try:
        await redis_client.delete(cache_key)
        return {"status": "success", "message": f"已删除 {ticker} {period} 的预期值"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/expectations/list")
async def list_expectations(
    ticker: Optional[str] = Query(None, description="股票代码（可选）"),
) -> Dict[str, Any]:
    """列出所有已存储的预期值"""
    try:
        if ticker:
            pattern = f"quant:earnings:expectations:{ticker}:*"
        else:
            pattern = "quant:earnings:expectations:*"

        keys = await redis_client.keys(pattern)
        result = []

        for key in keys:
            # 解析 key: quant:earnings:expectations:{ticker}:{period}
            parts = key.split(":")
            if len(parts) >= 5:
                t, p = parts[3], parts[4]
                cached = await redis_client.get(key)
                if cached:
                    result.append(
                        {
                            "ticker": t,
                            "period": p,
                            "count": len(json.loads(cached)),
                            "expectations": json.loads(cached),
                        }
                    )

        return {"status": "success", "data": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}
