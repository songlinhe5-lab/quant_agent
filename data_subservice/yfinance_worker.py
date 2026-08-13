"""YFinance worker — 物理解耦版（import _internal，无 backend 依赖）"""

from typing import Any, Dict

from data_subservice._internal.logger import logger
from data_subservice._internal.yfinance import yfinance_service

# Yahoo 限流类错误的关键词特征（错误文本来自 yfinance 异常 message，非 HTTP 状态码，
# 因 yfinance 内部把 Yahoo 的 429/Too Many Requests 包装成普通 Exception 抛出）。
_RATE_LIMIT_KEYWORDS = (
    "too many requests",
    "rate limit",
    "rate-limited",
    "ratelimit",
    "too many concurrent",
    "throttl",
)


def _annotate_error_category(result: Any) -> Dict[str, Any]:
    """BE-ARCH-08d 补漏：给 yfinance 错误结果补上 error_category。

    yfinance service 层（service.py/quote.py）的限流异常被包装成普通 Exception，
    最终只以 `{"error": "Too Many Requests..."}` 形式返回，缺少 error_category 字段。
    主服务 router 的 _normalize_response 只透传 data.error_category（缺失则落到
    NORMAL），导致限流被误判为普通失败计入熔断器，被限流节点错误触发熔断而非退避。

    此处作为唯一出口统一补标注：结果含 error 且未带 error_category 时，按错误文本
    识别限流类错误，标注 `rate_limit`，使主服务正确走退避而非熔断。
    """
    if not isinstance(result, dict):
        return result

    # 已显式带 error_category，尊重原值，不覆盖
    if result.get("error_category"):
        return result

    err = result.get("error") or result.get("message") or ""
    if not err:
        return result

    err_lower = str(err).lower()
    if any(kw in err_lower for kw in _RATE_LIMIT_KEYWORDS):
        annotated = dict(result)
        annotated["error_category"] = "rate_limit"
        return annotated

    return result


async def handle_yfinance(action: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """处理 yfinance 数据源请求。"""
    try:
        if action == "QUOTE":
            return _annotate_error_category(await yfinance_service.get_quote(params.get("symbol")))
        elif action == "HISTORY":
            return _annotate_error_category(
                await yfinance_service.get_history(
                    params.get("symbol"),
                    period=params.get("period"),
                    start=params.get("start"),
                    end=params.get("end"),
                    interval=params.get("interval", "1d"),
                )
            )
        elif action == "FUND_FLOW":
            return _annotate_error_category(await yfinance_service.get_fund_flow(params.get("symbol")))
        elif action == "OPTION_CHAIN":
            return _annotate_error_category(
                await yfinance_service.get_option_chain(params.get("symbol"), expiration=params.get("expiration"))
            )
        elif action == "FINANCIALS":
            return _annotate_error_category(
                await yfinance_service.get_financials(params.get("symbol"), kind=params.get("kind", "annual"))
            )
        elif action == "SEARCH":
            return _annotate_error_category(
                await yfinance_service.search(params.get("query", ""), limit=params.get("limit", 10))
            )
        elif action == "TECH":
            return _annotate_error_category(
                await yfinance_service.get_tech_indicators(
                    params.get("symbol"), period=params.get("period", "1y"), indicators=params.get("indicators")
                )
            )
        elif action == "BATCH_QUOTE":
            return _annotate_error_category(await yfinance_service.get_batched_quote(params.get("symbols", [])))
        elif action == "NEWS":
            return _annotate_error_category(
                await yfinance_service.get_news(params.get("symbol"), limit=params.get("limit", 15))
            )
        else:
            return {"error": f"未知 yfinance action: {action}"}
    except Exception as e:
        logger.error(f"❌ [YF Worker] {action} 失败: {e}")
        return _annotate_error_category({"error": str(e), "source": "yfinance"})
