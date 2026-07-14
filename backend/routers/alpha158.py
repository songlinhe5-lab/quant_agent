"""
AI-03 (能力) · Alpha158 因子 API 端点

- POST /alpha158/compute — 计算指定因子
- GET /alpha158/factors — 列出可用因子
"""

from typing import List

from fastapi import APIRouter
from pydantic import BaseModel

from backend.services.alpha158 import compute_all_factors, compute_factor, list_factors

router = APIRouter(prefix="/alpha158", tags=["alpha158"])


class ComputeRequest(BaseModel):
    factor_names: List[str]
    # 实际应从 DataServer 获取 K 线，此处简化为直接传入
    # 前端/调用方应先通过 screener 获取 K 线数据


@router.get("/factors")
async def get_factors():
    """列出所有可用因子"""
    return {"factors": list_factors()}


@router.post("/compute")
async def compute_factors(request: dict):
    """
    计算指定因子。

    Body:
    ```json
    {
        "factor_names": ["rsi_14", "macd_dif", "sma_20"],
        "kline_data": {"open": [...], "high": [...], "low": [...], "close": [...], "volume": [...]}
    }
    ```
    """
    import pandas as pd

    factor_names = request.get("factor_names", [])
    kline_data = request.get("kline_data", {})

    if not kline_data:
        return {"error": "kline_data is required"}

    df = pd.DataFrame(kline_data)

    if not factor_names:
        # 计算全部因子
        result = compute_all_factors(df)
        return {
            "factors": {col: result[col].tolist() for col in result.columns},
            "index": [str(i) for i in result.index],
        }

    results = {}
    for name in factor_names:
        series = compute_factor(df, name)
        if series is not None:
            results[name] = series.tolist()
        else:
            results[name] = None

    return {
        "factors": results,
        "index": [str(i) for i in df.index],
    }
