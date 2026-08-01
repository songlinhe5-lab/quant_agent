"""
==========================================
Data Source Router - 数据源路由服务
==========================================

实现跨节点数据源路由 (5 节点拓扑):
  - 主节点 VPS_S1 : 本地 finnhub + yfinance，按能力路由至远程 data_subservice 节点
  - 北京 VPS_BJ   : tushare + akshare + yfinance  (tushare/akshare 唯一节点，单点)
  - 美西 VPS_S2   : 纯 yfinance (与 S3/S4 共同负载均衡/容灾)
  - 美西 VPS_S3/S4: 纯 yfinance (负载均衡/容灾)
  - YFinance 主节点限流时自动 failover 至备用/远程 yfinance 节点
  - Tushare/AKShare 流量路由至北京单节点 (无容灾，节点不可用时降级本地适配器)

环境变量控制 (URL 支持逗号分隔多活):
  DATA_SOURCE_ROUTER_ENABLED=true|false    # 是否启用路由
  YF_PRIMARY_NODE_URL=http://localhost:8000  # yfinance 主节点 (主节点本地)
  YF_BACKUP_NODE_URL=http://s3:8000,http://s4:8000,http://s2:8000  # yfinance 备用 (逗号分隔多活)
  TUSHARE_REMOTE_URL=http://bj:8000          # tushare 远程 (北京单节点)
  AKSHARE_REMOTE_URL=http://bj:8000          # akshare 远程 (北京单节点)
  DATA_SOURCE_HMAC_SECRET=...               # 节点间通信签名密钥
"""

import asyncio
import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import httpx

from backend.core.circuit_breaker import get_cooldown_seconds
from backend.core.logger import logger
from backend.services.datasource import (
    ErrorCategory,
    ErrorInfo,
    classify_http_error,
    parse_retry_after,
    rate_limit_registry,
)

# DIST-19: AKShare STALE 缓存配置
_AK_STALE_PREFIX = "quant:akshare:stale"
_AK_STALE_TTL = int(os.getenv("AKSHARE_STALE_TTL", "86400"))  # 默认 24h


@dataclass
class DataSourceNode:
    name: str
    url: str
    enabled: bool = True
    weight: int = 10
    status: str = "healthy"
    last_heartbeat: float = 0.0
    error_count: int = 0
    circuit_breaker_until: float = 0.0
    capabilities: List[str] = field(default_factory=list)
    # RL-13: 限流压力感知
    is_throttled: bool = False
    consecutive_rate_limits: int = 0
    estimated_limit_rpm: Optional[int] = None


class DataSourceRouter:
    def __init__(self):
        self._enabled = os.getenv("DATA_SOURCE_ROUTER_ENABLED", "false").lower() == "true"
        self._hmac_secret = os.getenv("DATA_SOURCE_HMAC_SECRET", "")
        self._nodes: Dict[str, DataSourceNode] = {}
        self._lock = asyncio.Lock()
        self._http_client: Optional[httpx.AsyncClient] = None
        self._init_nodes()

    def _init_nodes(self):
        # 支持逗号分隔的多个 URL (多活容灾)。
        # 注意: fetch_akshare/fetch_tushare 按固定单键 'akshare_remote'/'tushare_remote' 取节点，
        #       故 tushare/akshare 远程 URL 仅取首个 (当前拓扑: 北京单节点，无容灾)。
        yf_primary = os.getenv("YF_PRIMARY_NODE_URL", "http://localhost:8000")
        yf_backups = os.getenv("YF_BACKUP_NODE_URL", "")
        akshare_urls = self._split_urls(os.getenv("AKSHARE_REMOTE_URL", ""))
        tushare_urls = self._split_urls(os.getenv("TUSHARE_REMOTE_URL", ""))

        self._nodes["yf_primary"] = DataSourceNode(
            name="yf_primary",
            url=yf_primary,
            weight=10,
            capabilities=["yfinance", "quote", "history", "tech"],
        )

        # YFinance 备用节点 (S2 / S3 / S4 等纯 yfinance 节点)
        for idx, url in enumerate(self._split_urls(yf_backups), start=1):
            self._nodes[f"yf_backup_{idx}"] = DataSourceNode(
                name=f"yf_backup_{idx}",
                url=url,
                weight=5,
                capabilities=["yfinance", "quote", "history", "tech"],
            )

        # AKShare 远程节点 (北京单节点，单键)
        if akshare_urls:
            self._nodes["akshare_remote"] = DataSourceNode(
                name="akshare_remote",
                url=akshare_urls[0],
                weight=10,
                capabilities=["akshare", "southbound", "northbound", "hsgt"],
            )

        # Tushare 远程节点 (北京单节点，单键)
        if tushare_urls:
            self._nodes["tushare_remote"] = DataSourceNode(
                name="tushare_remote",
                url=tushare_urls[0],
                weight=10,
                capabilities=[
                    "tushare",
                    "stock_history",
                    "stock_quote",
                    "fundamental",
                    "fund_flow",
                    "stock_list",
                    "lowfreq_history",
                    "macro",
                ],
            )

        logger.info(f"[Router] 初始化完成: enabled={self._enabled}, nodes={list(self._nodes.keys())}")

    @staticmethod
    def _split_urls(raw: str) -> List[str]:
        """将逗号分隔的 URL 字符串拆分为列表 (去除空白/空项)。"""
        return [u.strip() for u in (raw or "").split(",") if u.strip()]

    def _sign_request(self, payload: dict, timestamp: str) -> str:
        if not self._hmac_secret:
            return ""
        payload_with_ts = payload.copy()
        payload_with_ts["__timestamp"] = timestamp
        data_str = json.dumps(payload_with_ts, sort_keys=True).encode("utf-8")
        return hashlib.sha256(self._hmac_secret.encode("utf-8") + data_str).hexdigest()

    def _ensure_http_client(self):
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(15.0, connect=5.0),
                limits=httpx.Limits(max_connections=20),
            )

    async def _send_request(self, node: DataSourceNode, endpoint: str, payload: dict) -> Dict[str, Any]:

        self._ensure_http_client()
        url = f"{node.url}/api/v1/data-source/proxy/{endpoint}"
        headers = {"Content-Type": "application/json"}

        if self._hmac_secret:
            timestamp = str(int(time.time()))
            signature = self._sign_request(payload, timestamp)
            headers["X-Data-Source-Signature"] = signature
            headers["X-Data-Source-Timestamp"] = timestamp

        if self._http_client is None:
            return {}

        try:
            resp = await self._http_client.post(url, json=payload, headers=headers, timeout=15.0)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            status_code = e.response.status_code
            resp_headers = dict(e.response.headers)

            # 根据 HTTP 状态码推断错误分类
            category = classify_http_error(status_code, resp_headers)
            retry_after = parse_retry_after(resp_headers)

            # 构建错误信息，填充 category
            error_info = self._build_error_info_from_http(
                status_code=status_code,
                category=category,
                retry_after=retry_after,
                response_headers=resp_headers,
                message=str(e),
            )

            logger.error(
                f"[Router] 请求错误: node={node.name}, endpoint={endpoint}, "
                f"status={status_code}, category={category.value}, error={str(e)}"
            )

            # 将错误分类信息附加到返回值中，供上层使用
            return {
                "status": "error",
                "error_info": error_info.to_dict(),
                "error_category": category.value,
                "message": str(e),
            }
        except Exception as e:
            logger.error(f"[Router] 请求失败: node={node.name}, endpoint={endpoint}, error={str(e)}")
            raise

    def _build_error_info_from_http(
        self,
        status_code: int,
        category: ErrorCategory,
        retry_after: Optional[float],
        response_headers: Optional[dict],
        message: str,
    ) -> ErrorInfo:
        """根据 HTTP 响应构建 ErrorInfo，正确填充 category"""

        if category == ErrorCategory.RATE_LIMIT:
            return ErrorInfo.rate_limited(
                code=f"HTTP_{status_code}",
                message=message,
                retry_after=retry_after,
                source_header=response_headers.get("X-RateLimit-Remaining") if response_headers else None,
            )
        elif category == ErrorCategory.QUOTA_EXHAUSTED:
            return ErrorInfo.quota_exhausted(
                code=f"HTTP_{status_code}",
                message=message,
                estimated_reset=retry_after,
            )
        elif category == ErrorCategory.IP_BLOCKED:
            return ErrorInfo.ip_blocked(
                code=f"HTTP_{status_code}",
                message=message,
                estimated_reset=retry_after,
            )
        else:
            return ErrorInfo.normal(
                code=f"HTTP_{status_code}",
                message=message,
                retryable=status_code >= 500,  # 5xx 可重试，4xx 不可重试
            )

    def _get_healthy_nodes(self, capability: str) -> List[DataSourceNode]:
        """
        获取健康节点列表。

        RL-13: 限流压力感知 — 节点被限流时降低优先级，优先选择限流压力低的节点。
        """
        now = time.time()
        healthy = [
            node
            for node in self._nodes.values()
            if node.enabled
            and capability in node.capabilities
            and node.status == "healthy"
            and now >= node.circuit_breaker_until
        ]
        # 同步限流状态到节点（从本地 registry 获取）
        for node in healthy:
            throttler = rate_limit_registry.get_throttler(node.name)
            status = throttler.get_status()
            node.is_throttled = status.is_throttled
            node.consecutive_rate_limits = status.consecutive_rate_limits
            node.estimated_limit_rpm = status.estimated_limit_rpm
        return healthy

    async def _update_node_status(
        self,
        node_name: str,
        success: bool,
        error: str = "",
        error_category: ErrorCategory = ErrorCategory.NORMAL,
    ):
        """
        更新节点状态。

        关键区分：限流类错误不计入熔断器失败计数，触发独立退避机制。
        普通错误才走标准熔断器 CLOSED → OPEN 状态机。
        """
        async with self._lock:
            node = self._nodes.get(node_name)
            if not node:
                return

            node.last_heartbeat = time.time()

            if success:
                node.error_count = 0
                node.status = "healthy"
            else:
                # 限流类错误不计入熔断器失败计数
                if error_category == ErrorCategory.NORMAL:
                    node.error_count += 1
                    if node.error_count >= 3:
                        node.status = "unhealthy"
                        node.circuit_breaker_until = time.time() + get_cooldown_seconds()
                        logger.warning(f"[CircuitBreaker] 节点 {node_name} 触发熔断: {error}")
                else:
                    # 限流类错误：记录日志但不触发熔断
                    logger.info(
                        f"[RateLimit] 节点 {node_name} 限流 ({error_category.value}): {error} "
                        f"— 不计入熔断器，触发独立退避"
                    )

    async def _select_node(self, capability: str) -> Optional[DataSourceNode]:
        """
        选择最优节点。

        RL-13: 优先选择限流压力低的节点。
        排序规则:
        1. 未被限流的节点优先 (is_throttled=False 在前)
        2. 同状态下按 weight 降序
        3. 同 weight 下按连续限流次数升序
        """
        healthy = self._get_healthy_nodes(capability)
        if not healthy:
            return None

        healthy.sort(key=lambda n: (n.is_throttled, -n.weight, n.consecutive_rate_limits))
        return healthy[0]

    async def fetch_yfinance(self, ticker: str, fetch_type: str, **kwargs) -> Dict[str, Any]:
        if not self._enabled:
            from backend.services.yfinance import yf_service

            if fetch_type == "quote":
                return await yf_service.get_batched_quote(ticker, req_type="quote")
            elif fetch_type == "tech":
                return await yf_service.get_tech_indicators(ticker, **kwargs)
            elif fetch_type == "history":
                success, data, msg = await yf_service.fetch_yf_data(ticker, "history", ttl=3600, **kwargs)
                return {"success": success, "data": data, "message": msg}
            return {"success": False, "message": f"Unknown fetch_type: {fetch_type}"}

        nodes = self._get_healthy_nodes("yfinance")
        if not nodes:
            logger.warning("[YFinance] 无健康节点可用，降级本地数据源")
            return await self.fetch_yfinance_local(ticker, fetch_type, **kwargs)

        for node in nodes:
            try:
                payload = {
                    "ticker": ticker,
                    "fetch_type": fetch_type,
                    "kwargs": kwargs,
                }
                result = await self._send_request(node, "yfinance", payload)

                # 检查返回结果中是否包含错误分类信息
                error_category = ErrorCategory(result.get("error_category", "normal"))

                if result.get("status") == "success" or result.get("success"):
                    await self._update_node_status(node.name, success=True)
                    return result

                # 限流类错误：不计入熔断器，触发 failover 到下一节点
                if error_category != ErrorCategory.NORMAL:
                    logger.warning(f"[YFinance] 节点 {node.name} 限流 ({error_category.value}): {ticker}")
                    await self._update_node_status(
                        node.name,
                        success=False,
                        error="rate_limit",
                        error_category=error_category,
                    )
                    continue

                await self._update_node_status(
                    node.name,
                    success=False,
                    error=str(result.get("message")),
                    error_category=ErrorCategory.NORMAL,
                )

            except Exception as e:
                logger.warning(f"[YFinance] 节点 {node.name} 失败: {ticker}, {str(e)}")
                await self._update_node_status(
                    node.name,
                    success=False,
                    error=str(e),
                    error_category=ErrorCategory.NORMAL,
                )

        logger.warning("[YFinance] 所有节点失败，降级本地数据源")
        return await self.fetch_yfinance_local(ticker, fetch_type, **kwargs)

    async def fetch_yfinance_local(self, ticker: str, fetch_type: str, **kwargs) -> Dict[str, Any]:
        from backend.services.yfinance import yf_service

        try:
            if fetch_type == "quote":
                return await yf_service.get_batched_quote(ticker, req_type="quote")
            elif fetch_type == "tech":
                return await yf_service.get_tech_indicators(ticker, **kwargs)
            elif fetch_type == "history":
                success, data, msg = await yf_service.fetch_yf_data(ticker, "history", ttl=3600, **kwargs)
                return {"success": success, "data": data, "message": msg}
            return {"success": False, "message": f"Unknown fetch_type: {fetch_type}"}
        except Exception as e:
            return {"success": False, "message": f"Local yfinance failed: {str(e)}"}

    async def fetch_akshare(self, action: str, **kwargs) -> Dict[str, Any]:
        from backend.services.akshare import akshare_service

        remote_node = self._nodes.get("akshare_remote")
        if not self._enabled or not remote_node or remote_node.status != "healthy":
            result = await self._call_local_akshare(action, akshare_service, **kwargs)
            # DIST-19: 本地也失败时，尝试 STALE 缓存降级
            if result.get("status") == "error":
                stale = await self._get_akshare_stale(action, kwargs)
                if stale:
                    return stale
            else:
                # 成功时存档 STALE 缓存
                await self._save_akshare_stale(action, kwargs, result)
            return result

        try:
            payload = {"action": action, "kwargs": kwargs}
            result = await self._send_request(remote_node, "akshare", payload)

            if result.get("status") == "success":
                await self._update_node_status(remote_node.name, success=True)
                # DIST-19: 成功响应存档，供 CN 断连时降级
                await self._save_akshare_stale(action, kwargs, result)
                return result

            await self._update_node_status(remote_node.name, success=False, error=str(result.get("message")))

        except Exception as e:
            logger.warning(f"[AKShare] 远程节点失败: {remote_node.name}, {action}, {str(e)}")
            await self._update_node_status(remote_node.name, success=False, error=str(e))

        # DIST-19: 远程节点不可用，先尝试本地，再 STALE
        logger.warning("[AKShare] 远程节点不可用，降级本地数据源")
        result = await self._call_local_akshare(action, akshare_service, **kwargs)
        if result.get("status") == "error":
            stale = await self._get_akshare_stale(action, kwargs)
            if stale:
                return stale
        else:
            await self._save_akshare_stale(action, kwargs, result)
        return result

    async def fetch_tushare(self, action: str, **params) -> Dict[str, Any]:
        """Tushare 远程节点代理 (北京从节点 DS_CAPABILITIES=tushare,akshare)。

        启用 DATA_SOURCE_ROUTER 且 tushare_remote 节点健康时，优先走远程；
        否则回退本地 Tushare 适配器 (A股主源)。
        """
        remote_node = self._nodes.get("tushare_remote")
        if not self._enabled or not remote_node or remote_node.status != "healthy":
            return await self._call_local_tushare(action, **params)

        try:
            payload = {"action": action, "params": params}
            result = await self._send_request(remote_node, "tushare", payload)
            if result.get("success"):
                await self._update_node_status(remote_node.name, success=True)
                return result
            await self._update_node_status(remote_node.name, success=False, error=str(result.get("message")))
        except Exception as e:
            logger.warning(f"[Tushare] 远程节点失败: {remote_node.name}, {action}, {str(e)}")
            await self._update_node_status(remote_node.name, success=False, error=str(e))

        logger.warning("[Tushare] 远程节点不可用，降级本地 Tushare 适配器")
        return await self._call_local_tushare(action, **params)

    async def _call_local_tushare(self, action: str, **params) -> Dict[str, Any]:
        from backend.services.tushare import tushare_service

        try:
            if action == "stock_history":
                return tushare_service.get_daily_history(
                    ticker=params.get("ticker", ""), **{k: v for k, v in params.items() if k != "ticker"}
                )
            elif action == "stock_quote":
                return tushare_service.get_realtime_quote(ticker=params.get("ticker", ""))
            elif action == "fundamental":
                return tushare_service.get_daily_basic(
                    ticker=params.get("ticker", ""), trade_date=params.get("trade_date")
                )
            elif action == "fund_flow":
                return tushare_service.get_moneyflow_hsgt(
                    start_date=params.get("start_date"), end_date=params.get("end_date")
                )
            elif action == "stock_list":
                return tushare_service.get_stock_basic(
                    list_status=params.get("list_status", "L"),
                    exchange=params.get("exchange"),
                    fields=params.get("fields"),
                )
            elif action == "lowfreq_history":
                return tushare_service.get_lowfreq_history(
                    ticker=params.get("ticker", ""), **{k: v for k, v in params.items() if k != "ticker"}
                )
            elif action == "macro":
                return tushare_service.get_macro(
                    params.get("api_name", ""), **{k: v for k, v in params.items() if k != "api_name"}
                )
            return {"success": False, "message": f"unsupported tushare action: {action}"}
        except Exception as e:  # noqa: BLE001
            return {"success": False, "message": str(e)}

    # ─────────────────────────────────────────
    #  DIST-19: AKShare STALE 缓存降级
    # ─────────────────────────────────────────

    async def _save_akshare_stale(self, action: str, kwargs: dict, data: Dict[str, Any]) -> None:
        """将 AKShare 成功响应存档到 Redis，供 CN 断连时降级"""
        try:
            from backend.core.redis_client import redis_client

            cache_key = f"{_AK_STALE_PREFIX}:{action}:{json.dumps(kwargs, sort_keys=True)}"
            await redis_client.set(cache_key, json.dumps(data, ensure_ascii=False), ex=_AK_STALE_TTL)
        except Exception as e:
            logger.debug(f"[AKShare] STALE 缓存存档失败: {e}")

    async def _get_akshare_stale(self, action: str, kwargs: dict) -> Optional[Dict[str, Any]]:
        """从 Redis 获取 AKShare STALE 缓存，CN 断连时返回降级数据"""
        try:
            from backend.core.redis_client import redis_client

            cache_key = f"{_AK_STALE_PREFIX}:{action}:{json.dumps(kwargs, sort_keys=True)}"
            cached = await redis_client.get(cache_key)
            if cached:
                data = json.loads(cached)
                data["degraded"] = True
                data["stale_source"] = True
                # DIST-20: 记录 AKShare STALE 降级指标
                try:
                    from backend.core.metrics import DIST_AK_STALE_TOTAL

                    DIST_AK_STALE_TOTAL.labels(action=action).inc()
                except Exception:
                    pass
                logger.warning(f"[AKShare] CN 断连，降级返回 STALE 缓存: {action}")
                return data
        except Exception as e:
            logger.debug(f"[AKShare] STALE 缓存读取失败: {e}")
        return None

    async def _call_local_akshare(self, action: str, akshare_service, **kwargs) -> Dict[str, Any]:
        try:
            if action == "southbound":
                return await akshare_service.get_southbound_flow()
            elif action == "northbound":
                return await akshare_service.get_northbound_flow()
            elif action == "hsgt_holders":
                return await akshare_service.get_hsgt_top_holders(symbol=kwargs.get("symbol", "00700"))
            elif action == "company_news":
                return await akshare_service.get_company_news(ticker=kwargs.get("ticker", ""))
            elif action == "stock_quote":
                return await akshare_service.get_stock_quote(ticker=kwargs.get("ticker", ""))
            elif action == "stock_history":
                return await akshare_service.get_stock_history(
                    ticker=kwargs.get("ticker", ""), num=kwargs.get("num", 60)
                )
            elif action == "economic_calendar":
                return await akshare_service.get_economic_calendar(days_ahead=kwargs.get("days_ahead", 7))
            return {"status": "error", "message": f"Unknown akshare action: {action}"}
        except Exception as e:
            return {"status": "error", "message": f"Local akshare failed: {str(e)}"}

    async def get_health_status(self) -> Dict[str, Any]:
        status = {"router_enabled": self._enabled, "nodes": {}}
        now = time.time()

        for name, node in self._nodes.items():
            # RL-13: 从 registry 获取实时限流状态
            throttler = rate_limit_registry.get_throttler(name)
            throttle_status = throttler.get_status()

            status["nodes"][name] = {
                "name": node.name,
                "url": node.url,
                "enabled": node.enabled,
                "weight": node.weight,
                "status": node.status,
                "capabilities": node.capabilities,
                "error_count": node.error_count,
                "cooldown_remaining": max(0, int(node.circuit_breaker_until - now)),
                # RL-13: 限流压力信息
                "is_throttled": throttle_status.is_throttled,
                "consecutive_rate_limits": throttle_status.consecutive_rate_limits,
                "total_rate_limits_1h": throttle_status.total_rate_limits_1h,
                "estimated_limit_rpm": throttle_status.estimated_limit_rpm,
                "backoff_strategy": throttle_status.backoff_strategy,
            }

        return status

    async def close(self):
        if self._http_client is not None:
            await self._http_client.aclose()


data_source_router = DataSourceRouter()
