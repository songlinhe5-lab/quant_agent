"""FIN-04 · filings 源薄适配器（远程子服务模式，对齐 sentiment.py）。

主服务不装 SEC SDK，全部经 DataSourceRouter HTTP+HMAC 调子服务 `filings` 能力。
对齐 docs/14 §10 零侵入扩展规范：业务代码经 Registry.fetch，禁止直连 sec_edgar。
"""

from __future__ import annotations

import time
from typing import Any, Optional

from backend.services.datasource import (
    ErrorCategory,
    ErrorInfo,
    HealthInfo,
    RateLimitStatus,
    Result,
)


class FilingsDataSource:
    """SEC EDGAR filings 远程适配器：经 data_source_router.fetch_filings() 调用 data_subservice。"""

    def __init__(self) -> None:
        self._started_at = time.monotonic()

    @property
    def name(self) -> str:
        return "filings"

    @property
    def version(self) -> str:
        return "0.1.0"

    @property
    def capabilities(self) -> list[str]:
        # 与子服务 filings_worker 实际 action 对齐（大小写全声明，使 upper 比对均可命中）。
        return [
            "submissions",
            "SUBMISSIONS",
            "company_facts",
            "COMPANY_FACTS",
            "frames",
            "FRAMES",
            "doc_text",
            "DOC_TEXT",
            "symbols",
            "SYMBOLS",
            "HKEX_FILINGS",
            "CNINFO_FILINGS",
        ]

    @property
    def mode(self) -> str:
        return "remote"

    def _get_filings_node(self) -> Any:
        from backend.services.datasource.router import data_source_router

        return data_source_router._nodes.get("filings_master")

    def is_available(self) -> bool:
        return self._get_filings_node() is not None

    async def health(self) -> HealthInfo:
        node = self._get_filings_node()
        if node is None:
            return HealthInfo(
                healthy=False,
                mode="remote",
                connected=False,
                uptime_seconds=time.monotonic() - self._started_at,
                last_error="filings_master 节点未配置（SEC 采集固定美国节点，docs/28 §二）",
                stats={"capabilities": self.capabilities},
                rate_limit_status=RateLimitStatus(),
            )
        connected = node.status == "healthy"
        return HealthInfo(
            healthy=connected,
            mode="remote",
            connected=connected,
            uptime_seconds=time.monotonic() - self._started_at,
            last_error=f"error_count={node.error_count}" if node.error_count else None,
            stats={
                "capabilities": self.capabilities,
                "node_url": node.url,
                "node_status": node.status,
                "error_count": node.error_count,
            },
            rate_limit_status=RateLimitStatus(),
        )

    async def fetch(self, action: str, params: dict[str, Any]) -> Result:
        _action = action.lower()
        if _action not in [c.lower() for c in self.capabilities]:
            return Result.make_error(
                ErrorInfo.normal(
                    "UNSUPPORTED_ACTION",
                    f"Filings 不支持 action: {action}",
                    retryable=False,
                ),
                source=self.name,
            )

        from backend.services.datasource.router import data_source_router

        try:
            resp = await data_source_router.fetch_filings(_action, **params)
        except Exception as e:  # noqa: BLE001
            return Result.make_error(
                ErrorInfo.normal("FILINGS_ROUTER_ERROR", str(e), retryable=True),
                source=self.name,
            )

        if isinstance(resp, dict) and resp.get("status") == "success":
            result = Result.make_success(resp.get("data"), source=self.name)
            result.self_recorded = True  # router 已记录 throttler(on_success)
            return result

        # 错误/降级：router 已记录 throttler，此处仅做语义化转换
        raw_data = resp if isinstance(resp, dict) else {}
        msg = raw_data.get("message") or "filings fetch failed"
        raw_cat = raw_data.get("error_category")
        is_rl = True
        if raw_cat == ErrorCategory.IP_BLOCKED.value:
            err = ErrorInfo.ip_blocked(message=msg)
        elif raw_cat == ErrorCategory.QUOTA_EXHAUSTED.value:
            err = ErrorInfo.quota_exhausted(message=msg)
        elif any(x in msg for x in ("429", "限流", "Rate limit", "Too Many")):
            err = ErrorInfo.rate_limited(message=msg)
        else:
            err = ErrorInfo.normal("FILINGS_FETCH_FAILED", msg, retryable=True)
            is_rl = False

        if is_rl:
            result = Result.make_rate_limited(err, source=self.name)
            result.self_recorded = True
        else:
            result = Result.make_error(err, source=self.name)
        return result


def ensure_filings_registered(service: Optional[Any] = None) -> str:
    """幂等注册 Filings 适配器到 DataSourceRegistry（对齐 ensure_sentiment_registered）。"""
    from backend.services.datasource.source_registry import datasource_registry

    if datasource_registry.has("filings"):
        return "filings-default"
    return datasource_registry.register(FilingsDataSource())
