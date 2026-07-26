"""
TRADE-01 · 期权 API 端点

- GET /options/greeks/{ticker} — 计算指定标的期权 Greeks
- POST /options/screen — 期权筛选
- GET /options/vol-smile/{ticker} — 波动率微笑曲线
- GET /options/iv-rank/{ticker} — IV Rank/Percentile
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from backend.app.market_data import market_data
from backend.services.options_engine import compute_option_chain_greeks
from backend.services.options_screener import OptionFilter, options_screener

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/options", tags=["options"])


class ScreenRequest(BaseModel):
    ticker: str
    iv_rank_min: Optional[float] = None
    iv_rank_max: Optional[float] = None
    delta_min: Optional[float] = None
    delta_max: Optional[float] = None
    min_volume: Optional[int] = None
    min_open_interest: Optional[int] = None
    option_type: Optional[str] = None
    expiry: Optional[str] = None


@router.get("/greeks/{ticker}")
async def get_option_greeks(
    ticker: str,
    expiry: Optional[str] = Query(None, description="到期日 (YYYY-MM-DD)"),
):
    """获取指定期权标的 Greeks"""
    try:
        # 获取期权链
        chain_res = await market_data.get_option_chain(ticker, expiry or "")
        if chain_res.get("status") != "success":
            raise HTTPException(
                status_code=404,
                detail=f"期权链获取失败: {chain_res.get('message', '未知错误')}",
            )

        # 获取标的现价
        quote_res = await market_data.get_quote(ticker)
        spot_price = quote_res.get("last_price", 0) if quote_res.get("status") == "success" else 0

        if spot_price <= 0:
            raise HTTPException(status_code=404, detail=f"无法获取 {ticker} 现价")

        # 提取期权数据
        options_data = chain_res.get("options") or chain_res.get("data", {}).get("options", [])
        if not options_data:
            return {"status": "success", "ticker": ticker, "spot_price": spot_price, "options": []}

        # 计算 Greeks
        risk_free_rate = 0.05  # 5% 无风险利率
        enriched = compute_option_chain_greeks(spot_price, risk_free_rate, options_data)

        return {
            "status": "success",
            "ticker": ticker,
            "spot_price": round(spot_price, 2),
            "risk_free_rate": risk_free_rate,
            "options": enriched,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"[Options] Greeks 计算失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/screen")
async def screen_options(req: ScreenRequest):
    """期权高级筛选"""
    try:
        # 获取期权链
        chain_res = await market_data.get_option_chain(req.ticker, "")
        if chain_res.get("status") != "success":
            raise HTTPException(
                status_code=404,
                detail=f"期权链获取失败: {chain_res.get('message', '未知错误')}",
            )

        # 获取标的现价
        quote_res = await market_data.get_quote(req.ticker)
        spot_price = quote_res.get("last_price", 0) if quote_res.get("status") == "success" else 0

        if spot_price <= 0:
            raise HTTPException(status_code=404, detail=f"无法获取 {req.ticker} 现价")

        options_data = chain_res.get("options") or chain_res.get("data", {}).get("options", [])

        # 构建筛选条件
        filters = OptionFilter(
            ticker=req.ticker,
            iv_rank_min=req.iv_rank_min,
            iv_rank_max=req.iv_rank_max,
            delta_min=req.delta_min,
            delta_max=req.delta_max,
            min_volume=req.min_volume,
            min_open_interest=req.min_open_interest,
            option_type=req.option_type,
            expiry=req.expiry,
        )

        result = await options_screener.screen_options(
            ticker=req.ticker,
            filters=filters,
            options_data=options_data,
            spot_price=spot_price,
        )

        return {"status": "success", **result}

    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"[Options] 筛选失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/vol-smile/{ticker}")
async def get_vol_smile(
    ticker: str,
    expiry: Optional[str] = Query(None, description="到期日"),
):
    """波动率微笑曲线分析"""
    try:
        chain_res = await market_data.get_option_chain(ticker, expiry or "")
        if chain_res.get("status") != "success":
            raise HTTPException(status_code=404, detail="期权链获取失败")

        quote_res = await market_data.get_quote(ticker)
        spot_price = quote_res.get("last_price", 0) if quote_res.get("status") == "success" else 0

        if spot_price <= 0:
            raise HTTPException(status_code=404, detail=f"无法获取 {ticker} 现价")

        options_data = chain_res.get("options") or chain_res.get("data", {}).get("options", [])

        result = await options_screener.analyze_vol_smile(
            ticker=ticker,
            options_data=options_data,
            spot_price=spot_price,
        )

        return {"status": "success", **result}

    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"[Options] 微笑分析失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/iv-rank/{ticker}")
async def get_iv_rank(ticker: str):
    """IV Rank 和 IV Percentile 分析"""
    try:
        # 获取当前 IV (从期权链 ATM 期权计算)
        chain_res = await market_data.get_option_chain(ticker, "")
        if chain_res.get("status") != "success":
            raise HTTPException(status_code=404, detail="期权链获取失败")

        quote_res = await market_data.get_quote(ticker)
        spot_price = quote_res.get("last_price", 0) if quote_res.get("status") == "success" else 0

        if spot_price <= 0:
            raise HTTPException(status_code=404, detail=f"无法获取 {ticker} 现价")

        options_data = chain_res.get("options") or chain_res.get("data", {}).get("options", [])

        # 找 ATM 期权的 IV
        enriched = compute_option_chain_greeks(spot_price, 0.05, options_data)
        valid = [o for o in enriched if o.get("iv") and o.get("moneyness")]
        # 优先严格 ATM (moneyness 偏离 <5%)
        atm_options = [o for o in valid if abs(o["moneyness"] - 1.0) < 0.05]
        # 💡 降级：无严格 ATM 时，取最接近平值的若干合约(避免因行权价间隔过大直接 404)
        if not atm_options and valid:
            valid.sort(key=lambda o: abs(o["moneyness"] - 1.0))
            atm_options = valid[: min(3, len(valid))]

        if not atm_options:
            raise HTTPException(status_code=404, detail="期权链无有效 IV 数据可计算")

        # ⚠️ IV Rank 需要历史 IV 序列，须从 Redis/DB 获取真实数据；
        # 当前无真实源，禁止用 random 伪造 (VIBE-CODING)。
        # TODO: 接入真实 IV 历史序列（Redis/DB）后改为读取并调用下方分析
        raise HTTPException(
            status_code=404,
            detail="IV Rank 计算失败：缺少历史 IV 序列（真实数据源不可用，禁止用模拟数据填充）",
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"[Options] IV Rank 计算失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/chain-matrix/{ticker}")
async def get_option_chain_matrix(
    ticker: str,
    max_expiries: int = Query(8, ge=1, le=16),
    max_strikes: int = Query(21, ge=5, le=60),
):
    """跨到期日的 IV 波动率曲面（前端热力图用）。

    返回结构:
    {
      symbol, underlying_price, expirations[], strikes[],
      calls: {iv:[[...]], delta:[[...]]},   # [到期日][行权价]
      puts:  {iv:[[...]], delta:[[...]]},
      legs: [{type, expiry, strike, iv, delta}, ...]
    }
    """
    try:
        res = await market_data.get_option_chain_matrix(ticker, max_expiries, max_strikes)
        if res.get("status") == "error":
            raise HTTPException(status_code=502, detail=res.get("message", "期权矩阵获取失败"))
        return res
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"[Options] 期权矩阵获取失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
