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
        elif action == "CREDIT":
            # 供主服务/探活读取 credit 快照，不消耗 credit
            from data_subservice._internal.fmp import credit_snapshot

            return {"status": "success", "data": credit_snapshot()}
        else:
            return {"error": f"未知 fmp action: {action}"}
    except Exception as e:
        logger.error(f"❌ [FMP Worker] {action} 失败: {e}")
        return {"error": str(e), "source": "fmp"}
