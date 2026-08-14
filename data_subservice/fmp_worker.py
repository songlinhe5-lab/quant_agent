"""FMP worker — 物理解耦版（import _internal，无 backend 依赖）"""

from typing import Any, Dict

from data_subservice._internal.fmp import fmp_service
from data_subservice._internal.logger import logger


def _to_fmp_symbol(symbol: str) -> str:
    """将业务侧（Futu 前缀）代码转为 FMP API 期望格式。

    DIST-SEC-05(2026-08-14): get_fundamental_data(0772.HK) 经 Facade 归一化为
    HK.00772 (Futu 约定) 后路由到 FMP，但 FMP REST 对港股期望 '0772.HK' 写法，
    直接传 'HK.00772' 会查不到 → profile/income_statement 全 null。这里在数据源层
    做格式适配，港股 HK.00772→0772.HK、A股 SH.600000→600000.SH，美股原样透传。
    """
    if not symbol:
        return symbol
    s = symbol.strip().upper()
    if s.startswith("HK."):
        code = s[3:].lstrip("0") or "0"
        return f"{code}.HK"
    if s.startswith(("SH.", "SZ.", "BJ.")):
        market = s[:2].lower()
        return f"{s[3:]}.{market}"
    return symbol


async def handle_fmp(action: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """处理 FMP 数据源请求（纯数据源连接，无业务编排）。"""
    try:
        symbol = _to_fmp_symbol(params.get("symbol"))
        if action == "QUOTE":
            return await fmp_service.get_quote(symbol)
        elif action == "PROFILE":
            return await fmp_service.get_profile(symbol)
        elif action == "INCOME_STATEMENT":
            return await fmp_service.get_income_statement(symbol, limit=int(params.get("limit", 4)))
        # BE-ARCH-08g: Facade 的 get_fundamental / get_fundamental_info 经 router 以
        # action=FUNDAMENTAL / INFO 抵达本 worker, 此前无对应分支 → 必走 else 返回
        # "未知 fmp action"。补齐两分支 (仅复用已存在的 get_profile / get_income_statement,
        # 不臆测 fmp_service 是否另有 get_fundamental 方法)。
        elif action == "INFO":
            # 公司头条信息 = 公司档案 (profile)
            return await fmp_service.get_profile(symbol)
        elif action == "FUNDAMENTAL":
            # 基本面 = 公司档案 + 利润表 (按 Facade 既有语义组合)
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
