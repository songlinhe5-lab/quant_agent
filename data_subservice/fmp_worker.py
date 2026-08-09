"""FMP worker — 物理解耦版（import _internal，无 backend 依赖）"""

from typing import Any, Dict

from data_subservice._internal.fmp import fmp_service
from data_subservice._internal.logger import logger


async def handle_fmp(action: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """处理 FMP 数据源请求（纯数据源连接，无业务编排）。"""
    try:
        if action == "QUOTE":
            return await fmp_service.get_quote(params.get("symbol"))
        elif action == "PROFILE":
            return await fmp_service.get_profile(params.get("symbol"))
        elif action == "INCOME_STATEMENT":
            return await fmp_service.get_income_statement(params.get("symbol"), limit=int(params.get("limit", 4)))
        # BE-ARCH-08g: Facade 的 get_fundamental / get_fundamental_info 经 router 以
        # action=FUNDAMENTAL / INFO 抵达本 worker, 此前无对应分支 → 必走 else 返回
        # "未知 fmp action"。补齐两分支 (仅复用已存在的 get_profile / get_income_statement,
        # 不臆测 fmp_service 是否另有 get_fundamental 方法)。
        elif action == "INFO":
            # 公司头条信息 = 公司档案 (profile)
            return await fmp_service.get_profile(params.get("symbol"))
        elif action == "FUNDAMENTAL":
            # 基本面 = 公司档案 + 利润表 (按 Facade 既有语义组合)
            symbol = params.get("symbol")
            profile = await fmp_service.get_profile(symbol)
            income = await fmp_service.get_income_statement(symbol, limit=int(params.get("limit", 4)))
            return {
                "status": "success",
                "data": {
                    "symbol": symbol,
                    "profile": profile.get("data") if isinstance(profile, dict) else profile,
                    "income_statement": income.get("data") if isinstance(income, dict) else income,
                },
                "source": "fmp",
            }
        elif action == "CREDIT":
            # 供主服务/探活读取 credit 快照，不消耗 credit
            from data_subservice._internal.fmp import credit_snapshot

            return {"status": "success", "data": credit_snapshot()}
        else:
            return {"error": f"未知 fmp action: {action}"}
    except Exception as e:
        logger.error(f"❌ [FMP Worker] {action} 失败: {e}")
        return {"error": str(e), "source": "fmp"}
