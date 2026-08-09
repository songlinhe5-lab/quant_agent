"""
==========================================
Data Source Router - 数据源路由服务
==========================================

实现跨节点数据源路由 (5 节点拓扑):
  - 主节点 VPS_S1 : finnhub / futu / fmp / 宏观源，全部经 data_subservice 远程调用
  - 北京 VPS_BJ   : tushare + akshare (tushare/akshare 唯一节点，单点)
  - 美西 US-YF-A/B: 纯 yfinance 子服务 (负载均衡/容灾，YF 流量唯一出口)
  - YFinance 流量 100% 外移至 US-YF-A/B 子服务，后端不再本地执行 yfinance
  - YFinance 节点限流时自动 failover 至备用/远程 yfinance 节点
  - Tushare/AKShare/Futu/FMP/Finnhub/宏观源 流量全部远程 (data_subservice)，后端不再本地兜底

设计原则 (2026-08-07): 所有数据源仅远程，移除一切本地 SDK 降级通道。
源失效统一经 get_health_status() 在监控中如实显示，而非静默降级本地。

环境变量控制 (URL 支持逗号分隔多活):
  DATA_SOURCE_ROUTER_ENABLED=true|false    # 是否启用路由
  YF_PRIMARY_NODE_URL=http://localhost:8001  # yfinance 主节点 (data_subservice 端口 8001)
  YF_BACKUP_NODE_URL=http://yf-b:8001       # yfinance 备用 (逗号分隔多活)
  TUSHARE_REMOTE_URL=http://bj:8001          # tushare 远程 (北京单节点)
  AKSHARE_REMOTE_URL=http://bj:8001          # akshare 远程 (北京单节点)
  FUTU_REMOTE_URL=http://localhost:8001      # futu 远程 (主节点 data_subservice, DS_CAPABILITIES=futu)
  FMP_REMOTE_URL=http://localhost:8001       # fmp 远程 (主节点 data_subservice, DS_CAPABILITIES=fmp)
  FINNHUB_REMOTE_URL=http://localhost:8001   # finnhub 远程 (主节点 data_subservice, DS_CAPABILITIES=finnhub)
  FRED_REMOTE_URL=http://localhost:8001      # fred 远程
  DBNOMICS_REMOTE_URL=http://localhost:8001  # dbnomics 远程
  RBI_REMOTE_URL=http://localhost:8001       # rbi 远程
  DATA_SOURCE_HMAC_SECRET=...               # 节点间通信签名密钥
"""

import asyncio
import hashlib
import hmac
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

# 数据子服务统一数据端点 (契约见 data_subservice/main.py::fetch_data)
_DATA_ENDPOINT = "/api/v1/data"

# 主服务内部 fetch_type -> 子服务 action 映射
# 子服务 action 取值见 data_subservice/yfinance_worker.py::handle_yfinance
_YF_ACTION_MAP = {
    "quote": "QUOTE",
    "history": "HISTORY",
    "tech": "TECH",
    "fund_flow": "FUND_FLOW",
    "option_chain": "OPTION_CHAIN",
    "financials": "FINANCIALS",
    "search": "SEARCH",
    "batch_quote": "BATCH_QUOTE",
    "news": "NEWS",
}

# 主服务内部 action -> 子服务 action 映射
# 子服务 tushare worker 已补全 FINANCIALS / HOLDER / MONEYFLOW 之外的全部能力
# (STOCK_HISTORY / STOCK_QUOTE / FUNDAMENTAL / STOCK_LIST / LOWFREQ_HISTORY / MACRO)，
# 对应实现见 data_subservice/_internal/tushare/service.py。
# ⚠️ 仍无法远程实现的 action 不列入本表 (如部分需要本地专属依赖的能力)，
#    会被识别为"远程不支持"并降级本地适配器，避免发出必然失败的远程请求污染熔断计数。
_TS_ACTION_MAP = {
    "financials": "FINANCIALS",
    "holder": "HOLDER",
    "moneyflow": "MONEYFLOW",
    "stock_history": "STOCK_HISTORY",
    "stock_quote": "STOCK_QUOTE",
    "fundamental": "FUNDAMENTAL",
    "stock_list": "STOCK_LIST",
    "lowfreq_history": "LOWFREQ_HISTORY",
    "macro": "MACRO",
}

# 主服务内部 fetch_type -> 子服务 action 映射 (Futu)
# 子服务 futu worker 已补全全部能力, 对应实现见 data_subservice/futu_worker.py::handle_futu。
# ⚠️ Futu OpenD 仅部署在主节点 (DATASOURCE_FUTU_MODE=external 时本路由 pin 主节点),
#    不进入多活/容灾候选, 故 _FUTU_ACTION_MAP 仅作内部 fetch_type 归一化用。
_FUTU_ACTION_MAP = {
    "quote": "QUOTE",
    "history": "HISTORY",
    "fund_flow": "FUND_FLOW",
    "option_chain": "OPTION_CHAIN",
    "fundamental": "FUNDAMENTAL",
    "order_book": "ORDER_BOOK",
    "warrant_chain": "WARRANT_CHAIN",
    "market_snapshots": "SNAPSHOT",
    "stock_basicinfo": "STOCK_BASICINFO",
    "account_info": "ACCOUNT_INFO",
    "place_order": "PLACE_ORDER",
    "emergency_liquidation": "EMERGENCY_LIQUIDATION",
}

# 主服务内部 fetch_type -> 子服务 action 映射 (Finnhub)
# Finnhub 连接层已下沉 data_subservice (_internal/finnhub + finnhub_worker.py)。
_FINNHUB_ACTION_MAP = {
    "quote": "QUOTE",
    "company_news": "COMPANY_NEWS",
    "market_news": "MARKET_NEWS",
    "earnings": "EARNINGS",
    "economic_calendar": "ECONOMIC_CALENDAR",
    "insider_trading": "INSIDER_TRADING",
    "stock_history": "STOCK_HISTORY",
    "dividend_calendar": "DIVIDEND_CALENDAR",
    "ipo_calendar": "IPO_CALENDAR",
}

# DIST-19: AKShare STALE 缓存配置
_AK_STALE_PREFIX = "quant:akshare:stale"
_AK_STALE_TTL = int(os.getenv("AKSHARE_STALE_TTL", "86400"))  # 默认 24h

# 新增：AKShare 热点数据缓存配置（主节点统一缓存）
_AK_CACHE_PREFIX = "quant:cache:akshare"
_AK_CACHE_TTL = int(os.getenv("AKSHARE_CACHE_TTL", "1800"))  # 默认 30 分钟


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
    # 子服务健康检查端点（用于监控数据源失效），无则跳过主动探测
    health_check_url: Optional[str] = None
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

        # Fail-fast: 子服务无条件校验 HMAC, 主服务若缺密钥则所有远程请求必 403。
        # 与其在运行时以"签名失败"的形式暴露 (极难排查), 不如启动即报错。
        # 仅在启用路由时校验, 不影响本地开发与单测。
        if self._enabled and not self._hmac_secret:
            raise RuntimeError(
                "DATA_SOURCE_ROUTER_ENABLED=true 但未配置 DATA_SOURCE_HMAC_SECRET。"
                "数据子服务会拒绝所有未签名请求 (403)，请先配置该密钥 (需与子服务侧一致)。"
            )

        self._init_nodes()

    def _init_nodes(self):
        # 支持逗号分隔的多个 URL (多活容灾)。
        # 注意: fetch_akshare/fetch_tushare 按固定单键 'akshare_remote'/'tushare_remote' 取节点，
        #       故 tushare/akshare 远程 URL 仅取首个 (当前拓扑: 北京单节点，无容灾)。
        yf_primary = os.getenv("YF_PRIMARY_NODE_URL", "http://localhost:8001")
        yf_backups = os.getenv("YF_BACKUP_NODE_URL", "")
        akshare_urls = self._split_urls(os.getenv("AKSHARE_REMOTE_URL", ""))
        tushare_urls = self._split_urls(os.getenv("TUSHARE_REMOTE_URL", ""))

        self._nodes["yf_primary"] = DataSourceNode(
            name="yf_primary",
            url=yf_primary,
            health_check_url=f"{yf_primary}/api/v1/health",
            weight=10,
            capabilities=["yfinance", "quote", "history", "tech"],
        )

        # YFinance 备用节点 (S2 / S3 / S4 等纯 yfinance 节点)
        for idx, url in enumerate(self._split_urls(yf_backups), start=1):
            self._nodes[f"yf_backup_{idx}"] = DataSourceNode(
                name=f"yf_backup_{idx}",
                url=url,
                health_check_url=f"{url}/api/v1/health",
                weight=5,
                capabilities=["yfinance", "quote", "history", "tech"],
            )

        # AKShare 远程节点 (北京单节点，单键)
        if akshare_urls:
            self._nodes["akshare_remote"] = DataSourceNode(
                name="akshare_remote",
                url=akshare_urls[0],
                health_check_url=f"{akshare_urls[0]}/api/v1/health",
                weight=10,
                capabilities=["akshare", "southbound", "northbound", "hsgt"],
            )

        # Tushare 远程节点 (北京单节点，单键)
        if tushare_urls:
            self._nodes["tushare_remote"] = DataSourceNode(
                name="tushare_remote",
                url=tushare_urls[0],
                health_check_url=f"{tushare_urls[0]}/api/v1/health",
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

        # Futu 主节点节点 (pin 主节点, 单键)
        # Futu OpenD 仅部署在 US-MASTER 主节点 (127.0.0.1:11111), 由主节点 data_subservice
        # 经 DS_CAPABILITIES=futu 持有 OpenD 长连接。主服务经 HTTP 调 source=futu 获取数据,
        # 不持有 SDK。URL 默认 http://localhost:8001 (与主节点 data_subservice 同机)。
        futu_url = os.getenv("FUTU_REMOTE_URL", "http://localhost:8001")
        self._nodes["futu_master"] = DataSourceNode(
            name="futu_master",
            url=futu_url,
            health_check_url=f"{futu_url}/api/v1/health",
            weight=10,
            capabilities=["futu"],
        )

        # FMP 主节点节点 (pin 主节点, 单键)
        # FMP 数据源连接层 (REST + credit 配额/指标) 已下沉 data_subservice
        # (_internal/fmp + fmp_worker.py)。主服务经 HTTP 调 source=fmp 获取数据,
        # 不持有 FMP REST 客户端。URL 默认 http://localhost:8001 (与主节点 data_subservice 同机)。
        fmp_url = os.getenv("FMP_REMOTE_URL", "http://localhost:8001")
        self._nodes["fmp_master"] = DataSourceNode(
            name="fmp_master",
            url=fmp_url,
            health_check_url=f"{fmp_url}/api/v1/health",
            weight=10,
            capabilities=["fmp"],
        )

        # Finnhub 远程节点 (pin 主节点, 单键)
        # Finnhub 连接层 (REST + WS tick 订阅) 已下沉 data_subservice (_internal/finnhub + finnhub_worker.py)。
        # 主服务经 HTTP 调 source=finnhub 获取数据，不持有 FinnhubService / WS 订阅。
        # URL 默认 http://localhost:8001 (与主节点 data_subservice 同机)。
        finnhub_url = os.getenv("FINNHUB_REMOTE_URL", "http://localhost:8001")
        self._nodes["finnhub_master"] = DataSourceNode(
            name="finnhub_master",
            url=finnhub_url,
            health_check_url=f"{finnhub_url}/api/v1/health",
            weight=10,
            capabilities=[
                "finnhub",
                "quote",
                "company_news",
                "market_news",
                "earnings",
                "economic_calendar",
                "insider_trading",
                "stock_history",
            ],
        )

        # 宏观源远程节点 (FRED / DBnomics / RBI)
        # 宏观连接层 (FRED REST / DBnomics REST / RBI 爬虫) 已下沉 data_subservice
        # (_internal/fred|dbnomics|rbi + 对应 worker)。主服务经 HTTP 调 source=fred|dbnomics|rbi 获取数据，
        # 不再本地调用 fred_service / dbnomics_service / rbi_service。
        fred_url = os.getenv("FRED_REMOTE_URL", "http://localhost:8001")
        self._nodes["fred_master"] = DataSourceNode(
            name="fred_master",
            url=fred_url,
            health_check_url=f"{fred_url}/api/v1/health",
            weight=10,
            capabilities=["fred", "macro_series", "economic_calendar"],
        )
        dbnomics_url = os.getenv("DBNOMICS_REMOTE_URL", "http://localhost:8001")
        self._nodes["dbnomics_master"] = DataSourceNode(
            name="dbnomics_master",
            url=dbnomics_url,
            health_check_url=f"{dbnomics_url}/api/v1/health",
            weight=10,
            capabilities=["dbnomics", "economic_calendar"],
        )
        rbi_url = os.getenv("RBI_REMOTE_URL", "http://localhost:8001")
        self._nodes["rbi_master"] = DataSourceNode(
            name="rbi_master",
            url=rbi_url,
            health_check_url=f"{rbi_url}/api/v1/health",
            weight=10,
            capabilities=["rbi", "economic_calendar"],
        )

        # 搜索/抓取源远程节点 (Tavily / Bocha / Jina)
        # 外部搜索/抓取经 data_subservice 统一代理 (search_worker.py)，主服务不再直接 httpx 外部 API。
        search_url = os.getenv("SEARCH_REMOTE_URL", "http://localhost:8001")
        self._nodes["search_master"] = DataSourceNode(
            name="search_master",
            url=search_url,
            health_check_url=f"{search_url}/api/v1/health",
            weight=10,
            capabilities=["tavily", "bocha", "jina"],
        )

        logger.info(f"[Router] 初始化完成: enabled={self._enabled}, nodes={list(self._nodes.keys())}")

    @staticmethod
    def _split_urls(raw: str) -> List[str]:
        """将逗号分隔的 URL 字符串拆分为列表 (去除空白/空项)。"""
        return [u.strip() for u in (raw or "").split(",") if u.strip()]

    def _sign_request(self, body: str, timestamp: str) -> str:
        """对**实际发送的 body 字符串**做标准 HMAC-SHA256 签名。

        契约与 data_subservice/main.py::verify_hmac 严格一致:
            message   = f"{timestamp}:{body}"
            signature = hmac_sha256(HMAC_SECRET, message).hexdigest()

        注意: 必须对最终发送的字节签名, 不能重新序列化 payload,
        否则空格/键序/Unicode 转义的差异会导致子服务验签失败 (403)。
        """
        return hmac.new(
            self._hmac_secret.encode("utf-8"),
            f"{timestamp}:{body}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    @staticmethod
    def _normalize_response(raw: Dict[str, Any]) -> Dict[str, Any]:
        """将子服务的 {"code":0,"data":...} 响应归一化为主服务内部约定。

        主服务各调用方统一以 status/success 判定结果, 子服务返回的是
        code/data 信封, 此处做一次转换, 避免污染上层业务逻辑。
        """
        if not isinstance(raw, dict):
            return {"status": "error", "success": False, "message": f"非法响应类型: {type(raw).__name__}"}

        # 已是主服务内部格式 (如 _send_request 构造的错误体), 原样返回
        if "code" not in raw:
            return raw

        if raw.get("code") != 0:
            return {
                "status": "error",
                "success": False,
                "message": str(raw.get("message") or raw.get("detail") or f"子服务返回 code={raw.get('code')}"),
            }

        data = raw.get("data")

        # worker 内部错误以 {"error": "..."} 形式返回, 需识别为失败
        if isinstance(data, dict) and data.get("error"):
            return {"status": "error", "success": False, "message": str(data["error"]), "data": data}

        result: Dict[str, Any] = {"status": "success", "success": True, "data": data}
        # 透传 worker 已带的业务字段, 但不覆盖上面的状态字段
        if isinstance(data, dict):
            for k, v in data.items():
                result.setdefault(k, v)
        return result

    def _ensure_http_client(self):
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(15.0, connect=5.0),
                limits=httpx.Limits(max_connections=20),
            )

    async def _send_request(self, node: DataSourceNode, source: str, payload: dict) -> Dict[str, Any]:
        """向数据子服务发起统一数据请求。

        契约 (data_subservice/main.py):
            POST {node.url}/api/v1/data
            body    = {"source": ..., "action": ..., "params": {...}}
            headers = X-Timestamp / X-Signature (HMAC-SHA256)
            resp    = {"code": 0, "data": ...}
        """
        self._ensure_http_client()
        url = f"{node.url}{_DATA_ENDPOINT}"

        # 子服务对原始 body 字节验签, 故此处固定序列化一次并以 content= 发送,
        # 不能用 json=payload (httpx 会重新序列化, 字节可能不一致导致 403)。
        body = json.dumps(payload, ensure_ascii=False)
        timestamp = str(int(time.time()))

        headers = {
            "Content-Type": "application/json",
            "X-Timestamp": timestamp,
            "X-Signature": self._sign_request(body, timestamp),
        }

        if self._http_client is None:
            return {}

        try:
            resp = await self._http_client.post(url, content=body.encode("utf-8"), headers=headers, timeout=15.0)
            resp.raise_for_status()
            return self._normalize_response(resp.json())
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
                f"[Router] 请求错误: node={node.name}, source={source}, "
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
            logger.error(f"[Router] 请求失败: node={node.name}, source={source}, error={str(e)}")
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
        """联邦 YF 流量到 US-YF-A/B 子服务节点。

        后端进程不再本地执行 yfinance。若路由未启用或所有子服务节点不可用，
        直接返回失败（不再降级本地 yfinance）。
        """
        if not self._enabled:
            return {
                "success": False,
                "message": "DataSourceRouter 未启用，无法路由 YFinance 子服务流量",
            }

        nodes = self._get_healthy_nodes("yfinance")
        if not nodes:
            logger.warning("[YFinance] 无健康子服务节点可用（后端已移除本地兜底）")
            return {
                "success": False,
                "message": "No healthy YFinance subservice node (local yfinance disabled)",
            }

        for node in nodes:
            try:
                payload = {
                    "source": "yfinance",
                    "action": _YF_ACTION_MAP.get(fetch_type.lower(), fetch_type.upper()),
                    "params": {"ticker": ticker, **kwargs},
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

        logger.warning("[YFinance] 所有子服务节点失败（后端已移除本地兜底）")
        return {
            "success": False,
            "message": "All YFinance subservice nodes failed (local yfinance disabled)",
        }

    async def fetch_akshare(self, action: str, **kwargs) -> Dict[str, Any]:
        """AKShare 远程节点代理 (北京单节点 DS_CAPABILITIES=akshare)。

        设计原则 (2026-08-07): 仅远程，移除本地 SDK 降级。router 未启用或远程节点
        不可用时直接返回失败（源失效在监控中如实显示）。成功响应仍存档 STALE/热点
        缓存，供 CN 断连时监控侧识别降级，但不自动回退本地。
        """
        remote_node = self._nodes.get("akshare_remote")
        if not self._enabled or not remote_node or remote_node.status != "healthy":
            logger.warning("[AKShare] 远程节点不可用（后端已移除本地兜底）")
            return {"status": "error", "message": "No healthy AKShare remote node (local SDK disabled)"}

        try:
            payload = {
                "source": "akshare",
                "action": action.upper(),
                "params": dict(kwargs),
            }
            result = await self._send_request(remote_node, "akshare", payload)

            if result.get("status") == "success":
                await self._update_node_status(remote_node.name, success=True)
                # 成功响应存档，供监控侧识别降级（不再回退本地）
                await self._save_akshare_stale(action, kwargs, result)
                await self._save_akshare_cache(action, kwargs, result)
                return result

            await self._update_node_status(remote_node.name, success=False, error=str(result.get("message")))

        except Exception as e:
            logger.warning(f"[AKShare] 远程节点失败：{remote_node.name}, {action}, {str(e)}")
            await self._update_node_status(remote_node.name, success=False, error=str(e))

        logger.warning("[AKShare] 远程节点失败（后端已移除本地兜底）")
        return {"status": "error", "message": "AKShare remote node failed (local SDK disabled)"}

    async def fetch_tushare(self, action: str, **params) -> Dict[str, Any]:
        """Tushare 远程节点代理 (北京从节点 DS_CAPABILITIES=tushare,akshare)。

        设计原则 (2026-08-07): 仅远程，移除本地适配器降级。所有 tushare action
        经 _TS_ACTION_MAP 归一化后走远程；子服务不支持的 action 直接返回失败，
        不再回退本地 TushareService。
        """
        remote_node = self._nodes.get("tushare_remote")
        if not self._enabled or not remote_node or remote_node.status != "healthy":
            logger.warning("[Tushare] 远程节点不可用（后端已移除本地兜底）")
            return {"success": False, "message": "No healthy Tushare remote node (local adapter disabled)"}

        remote_action = _TS_ACTION_MAP.get(action.lower())
        if remote_action is None:
            logger.warning(f"[Tushare] action={action} 远程子服务不支持，本地兜底已移除")
            return {"success": False, "message": f"unsupported tushare action (remote-only): {action}"}

        try:
            payload = {
                "source": "tushare",
                "action": remote_action,
                "params": dict(params),
            }
            result = await self._send_request(remote_node, "tushare", payload)
            if result.get("success"):
                await self._update_node_status(remote_node.name, success=True)
                return result
            await self._update_node_status(remote_node.name, success=False, error=str(result.get("message")))
        except Exception as e:
            logger.warning(f"[Tushare] 远程节点失败: {remote_node.name}, {action}, {str(e)}")
            await self._update_node_status(remote_node.name, success=False, error=str(e))

        logger.warning("[Tushare] 远程节点失败（后端已移除本地兜底）")
        return {"success": False, "message": "Tushare remote node failed (local adapter disabled)"}

    async def fetch_futu(self, action: str, **params) -> Dict[str, Any]:
        """Futu 主节点 HTTP 代理 (source="futu", pin 主节点)。

        Futu OpenD 仅部署在 US-MASTER 主节点 (127.0.0.1:11111), 由主节点
        data_subservice (DS_CAPABILITIES=futu) 持有长连接并对外提供 source=futu。
        主服务不持有 SDK, 所有 futu 访问经本路由 pin 到 futu_master 节点。

        设计原则 (2026-08-07): 仅远程，移除本地 futu_service 降级通道。
        """
        remote_action = _FUTU_ACTION_MAP.get(action.lower(), action.upper())

        # 业务侧统一用 ticker/tickers, 子服务 worker 契约用 symbol/symbols, 此处对齐
        norm_params = self._futu_normalize_params(remote_action, params)

        remote_node = self._nodes.get("futu_master")
        if not self._enabled or not remote_node or remote_node.status != "healthy":
            logger.warning("[Futu] 远程节点不可用（后端已移除本地兜底）")
            return {"status": "error", "message": "No healthy Futu remote node (local SDK disabled)"}

        try:
            payload = {
                "source": "futu",
                "action": remote_action,
                "params": norm_params,
            }
            result = await self._send_request(remote_node, "futu", payload)
            if result.get("status") == "success":
                await self._update_node_status(remote_node.name, success=True)
                # 直接透传子服务信封 (含 status/data 字段)
                return result
            await self._update_node_status(remote_node.name, success=False, error=str(result.get("message")))
        except Exception as e:
            logger.warning(f"[Futu] 远程节点失败: {remote_node.name}, {remote_action}, {str(e)}")
            await self._update_node_status(remote_node.name, success=False, error=str(e))

        logger.warning("[Futu] 远程节点失败（后端已移除本地兜底）")
        return {"status": "error", "message": "Futu remote node failed (local SDK disabled)"}

    @staticmethod
    def _futu_normalize_params(action: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """对齐业务侧键名与子服务 worker 契约。

        业务侧统一: ticker / tickers / market / sec_type / ktype / num / ...
        子服务 worker: symbol / symbols (其余同)
        """
        out = dict(params)
        if "ticker" in out:
            out["symbol"] = out.pop("ticker")
        if "tickers" in out:
            out["symbols"] = out.pop("tickers")
        return out

    async def fetch_fmp(self, action: str, **params) -> Dict[str, Any]:
        """FMP 主节点 HTTP 代理 (source="fmp", pin 主节点)。

        FMP 数据源连接层 (REST + credit 配额/指标) 已下沉 data_subservice
        (_internal/fmp + fmp_worker.py::handle_fmp)。主服务不持有 REST 客户端,
        所有 fmp 访问经本路由 pin 到 fmp_master 节点。

        设计原则 (2026-08-07): 仅远程，移除本地 _local_get 直连兜底。
        """
        _FMP_ACTION_MAP = {
            "quote": "QUOTE",
            "profile": "PROFILE",
            "income_statement": "INCOME_STATEMENT",
        }
        remote_action = _FMP_ACTION_MAP.get(action.lower(), action.upper())

        norm_params = dict(params)

        remote_node = self._nodes.get("fmp_master")
        if not self._enabled or not remote_node or remote_node.status != "healthy":
            logger.warning("[FMP] 远程节点不可用（后端已移除本地兜底）")
            return {"status": "error", "message": "No healthy FMP remote node (local fallback disabled)"}

        try:
            payload = {
                "source": "fmp",
                "action": remote_action,
                "params": norm_params,
            }
            result = await self._send_request(remote_node, "fmp", payload)
            if result.get("status") == "success":
                await self._update_node_status(remote_node.name, success=True)
                # 配额耗尽错误已带 error_category=quota, 透传给业务侧
                if result.get("error_category") == "quota":
                    await self._update_node_status(
                        remote_node.name, success=False, error="quota", error_category=ErrorCategory.QUOTA_EXHAUSTED
                    )
                    return result
                return result
            await self._update_node_status(remote_node.name, success=False, error=str(result.get("message")))
        except Exception as e:
            logger.warning(f"[FMP] 远程节点失败: {remote_node.name}, {remote_action}, {str(e)}")
            await self._update_node_status(remote_node.name, success=False, error=str(e))

        logger.warning("[FMP] 远程节点失败（后端已移除本地兜底）")
        return {"status": "error", "message": "FMP remote node failed (local fallback disabled)"}

    async def fetch_finnhub(self, action: str, **params) -> Dict[str, Any]:
        """Finnhub 远程节点代理 (主节点 DS_CAPABILITIES=finnhub)。

        Finnhub 连接层 (REST + WS tick 订阅) 已下沉 data_subservice
        (_internal/finnhub + finnhub_worker.py)。主服务不持有 FinnhubService / WS 订阅，
        quote 走 REST 快照。仅远程，无本地 SDK 兜底。
        """
        remote_action = _FINNHUB_ACTION_MAP.get(action.lower(), action.upper())
        remote_node = self._nodes.get("finnhub_master")
        if not self._enabled or not remote_node or remote_node.status != "healthy":
            logger.warning("[Finnhub] 远程节点不可用（后端已移除本地兜底）")
            return {"status": "error", "message": "No healthy Finnhub remote node (local SDK disabled)"}

        try:
            payload = {
                "source": "finnhub",
                "action": remote_action,
                "params": dict(params),
            }
            result = await self._send_request(remote_node, "finnhub", payload)
            if result.get("status") == "success":
                await self._update_node_status(remote_node.name, success=True)
                return result
            await self._update_node_status(remote_node.name, success=False, error=str(result.get("message")))
        except Exception as e:
            logger.warning(f"[Finnhub] 远程节点失败: {remote_node.name}, {remote_action}, {str(e)}")
            await self._update_node_status(remote_node.name, success=False, error=str(e))

        logger.warning("[Finnhub] 远程节点失败（后端已移除本地兜底）")
        return {"status": "error", "message": "Finnhub remote node failed (local SDK disabled)"}

    async def fetch_fred(self, action: str, **params) -> Dict[str, Any]:
        """FRED 远程节点代理 (主节点 DS_CAPABILITIES=fred)。

        宏观连接层 (FRED REST) 已下沉 data_subservice (_internal/fred + fred_worker.py)。
        主服务不再本地调用 fred_service。仅远程。
        """
        remote_node = self._nodes.get("fred_master")
        if not self._enabled or not remote_node or remote_node.status != "healthy":
            logger.warning("[FRED] 远程节点不可用（后端已移除本地兜底）")
            return {"status": "error", "message": "No healthy FRED remote node (local service disabled)"}

        try:
            payload = {
                "source": "fred",
                "action": action.upper(),
                "params": dict(params),
            }
            result = await self._send_request(remote_node, "fred", payload)
            if result.get("status") == "success":
                await self._update_node_status(remote_node.name, success=True)
                return result
            await self._update_node_status(remote_node.name, success=False, error=str(result.get("message")))
        except Exception as e:
            logger.warning(f"[FRED] 远程节点失败: {remote_node.name}, {action}, {str(e)}")
            await self._update_node_status(remote_node.name, success=False, error=str(e))

        logger.warning("[FRED] 远程节点失败（后端已移除本地兜底）")
        return {"status": "error", "message": "FRED remote node failed (local service disabled)"}

    async def fetch_dbnomics(self, action: str, **params) -> Dict[str, Any]:
        """DBnomics 远程节点代理 (主节点 DS_CAPABILITIES=dbnomics)。

        宏观连接层 (DBnomics REST) 已下沉 data_subservice (_internal/dbnomics + dbnomics_worker.py)。
        仅远程。
        """
        remote_node = self._nodes.get("dbnomics_master")
        if not self._enabled or not remote_node or remote_node.status != "healthy":
            logger.warning("[DBnomics] 远程节点不可用（后端已移除本地兜底）")
            return {"status": "error", "message": "No healthy DBnomics remote node (local service disabled)"}

        try:
            payload = {
                "source": "dbnomics",
                "action": action.upper(),
                "params": dict(params),
            }
            result = await self._send_request(remote_node, "dbnomics", payload)
            if result.get("status") == "success":
                await self._update_node_status(remote_node.name, success=True)
                return result
            await self._update_node_status(remote_node.name, success=False, error=str(result.get("message")))
        except Exception as e:
            logger.warning(f"[DBnomics] 远程节点失败: {remote_node.name}, {action}, {str(e)}")
            await self._update_node_status(remote_node.name, success=False, error=str(e))

        logger.warning("[DBnomics] 远程节点失败（后端已移除本地兜底）")
        return {"status": "error", "message": "DBnomics remote node failed (local service disabled)"}

    async def fetch_rbi(self, action: str, **params) -> Dict[str, Any]:
        """RBI 远程节点代理 (主节点 DS_CAPABILITIES=rbi)。

        宏观连接层 (RBI 爬虫) 已下沉 data_subservice (_internal/rbi + rbi_worker.py)。
        仅远程。
        """
        remote_node = self._nodes.get("rbi_master")
        if not self._enabled or not remote_node or remote_node.status != "healthy":
            logger.warning("[RBI] 远程节点不可用（后端已移除本地兜底）")
            return {"status": "error", "message": "No healthy RBI remote node (local service disabled)"}

        try:
            payload = {
                "source": "rbi",
                "action": action.upper(),
                "params": dict(params),
            }
            result = await self._send_request(remote_node, "rbi", payload)
            if result.get("status") == "success":
                await self._update_node_status(remote_node.name, success=True)
                return result
            await self._update_node_status(remote_node.name, success=False, error=str(result.get("message")))
        except Exception as e:
            logger.warning(f"[RBI] 远程节点失败: {remote_node.name}, {action}, {str(e)}")
            await self._update_node_status(remote_node.name, success=False, error=str(e))

        logger.warning("[RBI] 远程节点失败（后端已移除本地兜底）")
        return {"status": "error", "message": "RBI remote node failed (local service disabled)"}

    async def fetch_search(self, source: str, **params) -> Dict[str, Any]:
        """搜索/抓取源远程代理 (Tavily / Bocha / Jina)。

        外部搜索/抓取经 data_subservice 统一代理 (search_worker.py)，主服务不再直接
        httpx 外部 API。source ∈ {tavily, bocha, jina}。仅远程。
        """
        remote_node = self._nodes.get("search_master")
        if not self._enabled or not remote_node or remote_node.status != "healthy":
            logger.warning(f"[Search/{source}] 远程节点不可用（后端已移除直连）")
            return {
                "status": "error",
                "message": f"No healthy Search remote node (direct API disabled) source={source}",
            }

        try:
            payload = {
                "source": source,
                "action": "SEARCH",
                "params": dict(params),
            }
            result = await self._send_request(remote_node, source, payload)
            if result.get("status") == "success":
                await self._update_node_status(remote_node.name, success=True)
                return result
            await self._update_node_status(remote_node.name, success=False, error=str(result.get("message")))
        except Exception as e:
            logger.warning(f"[Search/{source}] 远程节点失败: {remote_node.name}, {str(e)}")
            await self._update_node_status(remote_node.name, success=False, error=str(e))

        logger.warning(f"[Search/{source}] 远程节点失败（后端已移除直连）")
        return {"status": "error", "message": f"Search remote node failed (direct API disabled) source={source}"}

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
                logger.warning(f"[AKShare] CN 断连，降级返回 STALE 缓存：{action}")
                return data
        except Exception as e:
            logger.debug(f"[AKShare] STALE 缓存读取失败：{e}")
        return None

    # ─────────────────────────────────────────
    #  新增：AKShare 热点数据缓存（主节点统一管理）
    # ─────────────────────────────────────────

    async def _save_akshare_cache(self, action: str, kwargs: dict, data: Dict[str, Any]) -> None:
        """将 AKShare 成功响应写入 Redis 热点缓存（TTL=30 分钟）"""
        try:
            from backend.core.redis_client import redis_client

            cache_key = f"{_AK_CACHE_PREFIX}:{action}:{hashlib.md5(json.dumps(kwargs, sort_keys=True).encode()).hexdigest()[:8]}"
            await redis_client.set(cache_key, json.dumps(data, ensure_ascii=False), ex=_AK_CACHE_TTL)
            logger.debug(f"[AKShare] 写入热点缓存：{cache_key}, TTL={_AK_CACHE_TTL}s")
        except Exception as e:
            logger.warning(f"[AKShare] 热点缓存写入失败：{e}")

    async def _get_akshare_cache(self, action: str, kwargs: dict) -> Optional[Dict[str, Any]]:
        """从 Redis 读取 AKShare 热点缓存，命中则直接返回（< 10ms）"""
        try:
            from backend.core.redis_client import redis_client

            cache_key = f"{_AK_CACHE_PREFIX}:{action}:{hashlib.md5(json.dumps(kwargs, sort_keys=True).encode()).hexdigest()[:8]}"
            cached = await redis_client.get(cache_key)
            if cached:
                data = json.loads(cached)
                data["source"] = "cache"
                data["cached"] = True
                logger.info(f"[AKShare] 热点缓存命中：{cache_key}")
                return data
        except Exception as e:
            logger.debug(f"[AKShare] 热点缓存读取失败：{e}")
        return None

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
