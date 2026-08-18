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
import math
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
from backend.services.datasource.offline_stub import (
    build_offline_response,
    is_offline_mode_enabled,
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
    # BE-ARCH-08c⑤: 前端 WS 订阅回传 — subscribe/unsubscribe 通知 OpenD 实时订阅
    "subscribe": "SUBSCRIBE",
    "unsubscribe": "UNSUBSCRIBE",
    # F2: 三大财务报表 + 估值明细（G1 真基本面基座）
    "financials": "FINANCIALS",
    "valuation": "VALUATION",
    # F1: 卖空数据分析（港股/美股卖空榜 + 每日卖空量）
    "short_selling": "SHORT_SELLING",
    # F3: 期权策略 + 期权波动率（G4 支撑）
    "option_strategy": "OPTION_STRATEGY",
    "option_volatility": "OPTION_VOLATILITY",
    # F4: P1 资金分布 / FedWatch / 热力图 / 分析师共识（支撑 G3/G5/G6/G7）
    "capital_distribution": "CAPITAL_DISTRIBUTION",
    "analyst_consensus": "ANALYST_CONSENSUS",
    "fed_watch": "FED_WATCH",
    "heat_map": "HEAT_MAP",
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

# BE-ARCH-08i: action 级熔断隔离配置
# action 连续普通失败达到该阈值 → 仅熔断该 action（不影响同节点其它 action）
_ACTION_MAX_FAILURES = int(os.getenv("DATASOURCE_ACTION_MAX_FAILURES", "3"))
# 节点级兜底阈值下限：任何节点至少需要这么多 action 同时熔断才判进程级故障。
# 这保证小节点（如 search_master 仅 3 个 action）不会因 2 个 action 熔断就被整节点误杀。
_ACTION_BREAKER_NODE_MIN_THRESHOLD = int(os.getenv("DATASOURCE_ACTION_NODE_MIN_THRESHOLD", "3"))
# 节点级兜底阈值比例：熔断态 action 数 ≥ ceil(节点 capabilities 规模 × 该比例) 才整节点熔断。
# capabilities 长度作为节点承载能力的规模代理（search_master=3 → 全熔断才兜底；
# finnhub_master=9 → 6 个熔断兜底），避免写死单一阈值对小/大节点均不适配。
_ACTION_BREAKER_NODE_RATIO = float(os.getenv("DATASOURCE_ACTION_NODE_RATIO", "0.6"))


def _node_breaker_threshold(node: "DataSourceNode") -> int:
    """节点级兜底动态阈值：max(下限, ceil(capabilities 规模 × 比例))。

    - search_master (capabilities=3: tavily/bocha/jina) → max(3, 2) = 3，
      须全部 action 熔断才整节点熔断，避免 bocha/tavily 双挂误伤 jina
      （BE-ARCH-08i 修复：单节点 pin 源整源误杀）。
    - finnhub_master (capabilities=9) → max(3, 6) = 6，进程级故障仍能通过
      多数 action 同时熔断被兜底捕获。
    """
    total = len(node.capabilities) if node.capabilities else 0
    if total <= 0:
        return _ACTION_BREAKER_NODE_MIN_THRESHOLD
    return max(_ACTION_BREAKER_NODE_MIN_THRESHOLD, math.ceil(total * _ACTION_BREAKER_NODE_RATIO))


# Yahoo/子服务限流类错误的文本特征（BE-ARCH-08d 补漏：某些子服务——如 yfinance——
# 未在响应 body 里携带 error_category，仅返回 "Too Many Requests" 文本，需在主服务侧兜底识别，
# 避免限流被误判为普通失败计入熔断器）。
_RATE_LIMIT_MESSAGE_KEYWORDS = (
    "too many requests",
    "rate limit",
    "rate-limited",
    "ratelimit",
    "too many concurrent",
    "throttl",
)


def _infer_error_category(result: Dict[str, Any]) -> ErrorCategory:
    """从子服务响应推断 error_category，带文本兜底（BE-ARCH-08d 补漏）。

    优先级：
    1. 响应已显式带 error_category → 直接采用。
    2. 响应 message/error 文本命中限流关键词 → 推断为 RATE_LIMIT。
    3. 否则 → NORMAL。

    这是修法 2（主服务侧兜底），与修法 1（子服务 yfinance_worker 补 error_category）
    互为双保险：即使子服务未修复/旧版本未部署，主服务仍能正确识别限流。
    """
    raw = result.get("error_category")
    if raw:
        try:
            return ErrorCategory(raw)
        except ValueError:
            pass

    msg = str(result.get("message") or result.get("error") or "").lower()
    if any(kw in msg for kw in _RATE_LIMIT_MESSAGE_KEYWORDS):
        return ErrorCategory.RATE_LIMIT

    # DIST-SEC-04(2026-08-14): 子服务 yfinance 对『该标的 Yahoo 无数据』会返回
    # error_category="data_unavailable"。文本兜底：识别 "no data"/"yahoo error" 等特征，
    # 避免这类标的层面问题被误判为普通失败计入熔断，误杀整节点。
    _DATA_UNAVAIL_KEYWORDS = ("no data", "yahoo error", "delisted", "not found")
    if any(kw in msg for kw in _DATA_UNAVAIL_KEYWORDS):
        return ErrorCategory.DATA_UNAVAILABLE

    return ErrorCategory.NORMAL


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
    # RL-13: 限流压力感知
    is_throttled: bool = False
    consecutive_rate_limits: int = 0
    estimated_limit_rpm: Optional[int] = None
    # 半开自愈探针状态（RL-14: 熔断后自动探活恢复，避免单节点源永久失效）
    last_probe_at: float = 0.0
    probe_consecutive_failures: int = 0
    # ── action 级熔断隔离（BE-ARCH-08i）──────────────────────────
    # 单节点 pin 源承载多个 action，某 action 连续失败不应整节点熔断（误杀其它 action）。
    # action_errors: 每个 action 的连续普通失败计数（限流类不计入）
    # action_breaker_until: 每个 action 的熔断冷却截止时间戳
    action_errors: Dict[str, int] = field(default_factory=dict)
    action_breaker_until: Dict[str, float] = field(default_factory=dict)


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

        # [DIAG-SEC] 启动期诊断：打印实际生效的 HMAC 密钥前几位，定位密钥注入时序问题
        # （若运行时 env 未注入导致用默认值，则与子服务侧密钥不一致 → 全部请求 403/熔断）。
        # 仅打印前缀，绝不泄露完整密钥。
        _secret_preview = (self._hmac_secret[:6] + "…") if self._hmac_secret else "<EMPTY>"
        logger.warning(
            "[DIAG-SEC] DataSourceRouter init: _enabled=%s, _hmac_secret[:6]=%s, len=%d",
            self._enabled,
            _secret_preview,
            len(self._hmac_secret),
        )

        self._init_nodes()
        # 💡 FIX-275: 启动期自检, 捕获 REMOTE_URL 端口配错指向主服务自身的典型故障
        # (如 akshare/fred 误配成 :8000 而非子服务 :8001, 导致静默 404 / connection refused)。
        self._validate_node_urls()
        # RL-14: 每次重新部署 (进程启动) 清空所有节点的熔断残留, 防止上一次运行的
        # unhealthy/error_count 污染新进程 (实战: 改 FUTU_REMOTE_URL 重启后老进程熔断态
        # 未清, 导致 QUOTE 端点持续 所有候选源失败)。
        self.reset_circuit_breakers()
        # 启动半开自愈探针 (后台任务, 独立于业务流量持续探查节点健康, 熔断后自动恢复)
        self._probe_task: Optional[asyncio.Task] = None
        self._shutdown_event = asyncio.Event()
        self.start_probing()

    # ------------------------------------------------------------------
    # RL-14: 熔断自愈 (半开探针) + 部署重置
    # ------------------------------------------------------------------
    def reset_circuit_breakers(self) -> None:
        """清空所有节点的熔断残留 (error_count / circuit_breaker_until / unhealthy)。

        每次进程启动 (即重新部署) 调用一次, 保证新进程从干净状态开始,
        不会被上一次运行累积的熔断态污染 (否则单节点 pin 源一旦熔断便永久
        "所有候选源失败", 必须 force-recreate 才能恢复)。
        """
        for node in self._nodes.values():
            node.error_count = 0
            node.circuit_breaker_until = 0.0
            node.status = "healthy"
            node.probe_consecutive_failures = 0
            node.last_probe_at = 0.0
            node.action_errors.clear()
            node.action_breaker_until.clear()
        logger.info(f"[Router] 熔断状态已重置 (部署重置): nodes={list(self._nodes.keys())}")

    def start_probing(self) -> None:
        """启动后台半开探针任务 (幂等, 仅当路由启用且无进行中任务时)。

        供两处调用:
        - __init__ 末尾 (模块导入期若已有 running loop 则直接拉起);
        - lifespan startup (此时必然有 running loop, 兜底确保探针一定运行)。
        """
        if not self._enabled:
            return
        if self._probe_task is not None and not self._probe_task.done():
            return
        try:
            # 仅当存在 running 的事件循环时才创建后台任务;
            # 模块导入期 / 单测 setup (无 running loop) 下 get_running_loop 会抛
            # RuntimeError, 此时静默跳过, 探针由运行时 (lifespan) 实际启动。
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._shutdown_event.clear()
        self._probe_task = loop.create_task(self._probe_loop())
        logger.info("[Router] 半开自愈探针已启动")

    async def stop_probing(self) -> None:
        """优雅关闭探针任务 (供 lifespan shutdown 调用)。"""
        if self._probe_task is None:
            return
        self._shutdown_event.set()
        try:
            await asyncio.wait_for(self._probe_task, timeout=5.0)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            self._probe_task.cancel()
        self._probe_task = None

    async def _probe_loop(self) -> None:
        """周期性对熔断/异常节点发起轻量探活, 成功则复位为 healthy。

        仅探查处于 unhealthy 或熔断冷却中的节点 (healthy 节点无需打扰),
        避免对正常节点造成额外请求压力。探活使用子服务 /health 端点。
        """
        probe_interval = float(os.getenv("DATASOURCE_PROBE_INTERVAL", "30"))
        while not self._shutdown_event.is_set():
            try:
                await asyncio.sleep(probe_interval)
                if self._shutdown_event.is_set():
                    break
                await self._probe_once()
            except asyncio.CancelledError:
                break
            except Exception as e:  # 探针自身异常绝不应影响主服务
                logger.warning(f"[Router] 探针循环异常 (已忽略): {e}")

    async def _probe_once(self) -> None:
        now = time.time()
        candidates = [
            n for n in self._nodes.values() if n.enabled and (n.status != "healthy" or now < n.circuit_breaker_until)
        ]
        if not candidates:
            return
        for node in candidates:
            try:
                ok = await self._probe_node(node)
            except Exception as e:
                logger.debug(f"[Router] 探针 {node.name} 异常: {e}")
                ok = False
            async with self._lock:
                node.last_probe_at = now
                if ok:
                    node.error_count = 0
                    node.circuit_breaker_until = 0.0
                    node.status = "healthy"
                    node.probe_consecutive_failures = 0
                    logger.info(f"[Router] 探针恢复节点 {node.name} -> healthy")
                else:
                    node.probe_consecutive_failures += 1
                    # 探针持续失败: 维持 unhealthy, 但让熔断冷却随时间自然到期,
                    # 不在此续期冷却 (由真实业务请求失败触发续期),
                    # 保证 once-healthy-after-cooldown 后 _pin_node_usable 放行重试。

    async def _probe_node(self, node: "DataSourceNode") -> bool:
        """对单个节点发起 /health 探活, 返回是否健康。"""
        self._ensure_http_client()
        if self._http_client is None:
            return False
        # 优先用节点 URL 的 /health, 失败回退到 /api/v1/data 的 OPTIONS 不可用,
        # 故直接 POST 一个轻量 PING action (子服务需支持 source=ping 或忽略)。
        url = f"{node.url}/health"
        try:
            resp = await self._http_client.get(url, timeout=httpx.Timeout(5.0, connect=3.0))
            if resp.status_code == 200:
                try:
                    body = resp.json()
                    # 子服务健康体含 status 字段, 仅当显式 unhealthy 才判失败
                    if isinstance(body, dict) and body.get("status") == "unhealthy":
                        return False
                except Exception:
                    pass
                return True
            return False
        except Exception:
            return False

    def _validate_node_urls(self):
        """启动期校验各远程数据源节点的 URL 端口, 防止误指向主服务自身。

        典型事故: AKSHARE_REMOTE_URL / FRED_REMOTE_URL 等被配成主服务端口
        (默认 8000) 而非 data_subservice 的 8001, 导致请求打到主服务自身 →
        404 或 connection refused, 且只在首次调用时才暴露, 排查成本高。

        此处于初始化阶段主动报错, 把故障前移到启动日志, 一目了然。
        """
        import urllib.parse

        main_port = str(os.getenv("QUANT_PORT", "8000"))
        for name, node in self._nodes.items():
            try:
                parsed = urllib.parse.urlparse(node.url)
            except Exception:
                logger.error(f"[DataSourceRouter] 节点 {name} 的 URL 无法解析: {node.url}")
                continue
            port = parsed.port or (80 if parsed.scheme == "http" else 443)
            host = (parsed.hostname or "").lower()
            # 端口等于主服务端口 => 高度疑似指向主服务自身而非子服务(8001)
            if str(port) == main_port:
                logger.error(
                    f"[DataSourceRouter] ⚠️ 节点 {name} 的 URL 端口({port}) 疑似指向主服务自身 "
                    f"(QUANT_PORT={main_port}), 而非 data_subservice 子服务的 8001: {node.url}。"
                    f"请检查对应的 *_REMOTE_URL 环境变量(如 AKSHARE_REMOTE_URL / FRED_REMOTE_URL / "
                    f"YF_PRIMARY_NODE_URL 等), 子服务应运行在 *:8001。"
                )
            # 显式指向 localhost/127.0.0.1 但端口非 8001(非子服务)也给出弱告警
            elif host in ("localhost", "127.0.0.1") and str(port) != "8001":
                logger.warning(
                    f"[DataSourceRouter] 节点 {name} 指向本地非子服务端口 {port}: {node.url}。"
                    f"data_subservice 默认运行在 8001, 若非刻意请修正。"
                )

    def _init_nodes(self):
        # 支持逗号分隔的多个 URL (多活容灾)。
        # 注意: fetch_akshare/fetch_tushare 按固定单键 'akshare_remote'/'tushare_remote' 取节点，
        #       故 tushare/akshare 远程 URL 仅取首个 (当前拓扑: 北京单节点，无容灾)。
        yf_primary = os.getenv("YF_PRIMARY_NODE_URL", "http://localhost:8001").strip()
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

        # Futu 主节点节点 (pin 主节点, 单键)
        # Futu OpenD 仅部署在 US-MASTER 主节点 (127.0.0.1:11111), 由主节点 data_subservice
        # 经 DS_CAPABILITIES=futu 持有 OpenD 长连接。主服务经 HTTP 调 source=futu 获取数据,
        # 不持有 SDK。URL 默认 http://localhost:8001 (与主节点 data_subservice 同机)。
        futu_url = os.getenv("FUTU_REMOTE_URL", "http://localhost:8001").strip()
        self._nodes["futu_master"] = DataSourceNode(
            name="futu_master",
            url=futu_url,
            weight=10,
            capabilities=["futu"],
        )

        # FMP 主节点节点 (pin 主节点, 单键)
        # FMP 数据源连接层 (REST + credit 配额/指标) 已下沉 data_subservice
        # (_internal/fmp + fmp_worker.py)。主服务经 HTTP 调 source=fmp 获取数据,
        # 不持有 FMP REST 客户端。URL 默认 http://localhost:8001 (与主节点 data_subservice 同机)。
        fmp_url = os.getenv("FMP_REMOTE_URL", "http://localhost:8001").strip()
        self._nodes["fmp_master"] = DataSourceNode(
            name="fmp_master",
            url=fmp_url,
            weight=10,
            capabilities=["fmp"],
        )

        # Finnhub 远程节点 (pin 主节点, 单键)
        # Finnhub 连接层 (REST + WS tick 订阅) 已下沉 data_subservice (_internal/finnhub + finnhub_worker.py)。
        # 主服务经 HTTP 调 source=finnhub 获取数据，不持有 FinnhubService / WS 订阅。
        # URL 默认 http://localhost:8001 (与主节点 data_subservice 同机)。
        finnhub_url = os.getenv("FINNHUB_REMOTE_URL", "http://localhost:8001").strip()
        self._nodes["finnhub_master"] = DataSourceNode(
            name="finnhub_master",
            url=finnhub_url,
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
            weight=10,
            capabilities=["fred", "macro_series", "economic_calendar"],
        )
        dbnomics_url = os.getenv("DBNOMICS_REMOTE_URL", "http://localhost:8001")
        self._nodes["dbnomics_master"] = DataSourceNode(
            name="dbnomics_master",
            url=dbnomics_url,
            weight=10,
            capabilities=["dbnomics", "economic_calendar"],
        )
        rbi_url = os.getenv("RBI_REMOTE_URL", "http://localhost:8001")
        self._nodes["rbi_master"] = DataSourceNode(
            name="rbi_master",
            url=rbi_url,
            weight=10,
            capabilities=["rbi", "economic_calendar"],
        )

        # 搜索/抓取源远程节点 (Tavily / Bocha / Jina)
        # 外部搜索/抓取经 data_subservice 统一代理 (search_worker.py)，主服务不再直接 httpx 外部 API。
        search_url = os.getenv("SEARCH_REMOTE_URL", "http://localhost:8001")
        self._nodes["search_master"] = DataSourceNode(
            name="search_master",
            url=search_url,
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

        # worker 内部错误以 {"error": "..."} 或 {"status": "error", "error_category": ...}
        # 两种形式返回 (FMP/Finnhub 走后者且不带 error 键)。无论哪种都必须识别为失败,
        # 否则配额耗尽 / 429 会被吞成"有数据返回", 限流退避 (RateLimitThrottler) 与
        # error_category 判定在这两源上完全失效 (BE-ARCH-08d)。
        if isinstance(data, dict) and (data.get("error") or data.get("status") == "error"):
            result: Dict[str, Any] = {
                "status": "error",
                "success": False,
                "message": str(data.get("error") or data.get("message") or "子服务返回错误状态"),
            }
            # 透传 error_category (限流/配额类), 供上层 throttler 与熔断分流
            if data.get("error_category"):
                result["error_category"] = data["error_category"]
            return result

        # 剥内层信封：REST 型子服务 (fred/finnhub/fmp/dbnomics/rbi/search) 的 service 层
        # 已返回 {"status":"success","data":{...}} 主服务风格信封，又被子服务 main.py 包成
        # {"code":0,"data":{那个信封}}。此处若 data 仍是 {"status":"success","data":{...}}
        # 双重包装，则剥掉内层，取真实业务数据，避免主服务业务层拿到嵌套信封解析失败
        # (如 fred_service payload.get("observations") 拿到 None → 空数据)。
        # 判断条件：data 含 "data" 键且 "status" 为 success（区别于 futu 等平级返回的
        # {"status":"success","symbol":...} 无 "data" 键的情况，不误剥）。
        inner_data = None
        if isinstance(data, dict) and data.get("status") == "success" and "data" in data:
            inner_data = data.get("data")
            # 仅当内层 data 是 dict/list（真实业务数据）才剥；内层为 None/标量时不剥，
            # 避免把空结果错误拍平。
            if inner_data is not None and isinstance(inner_data, (dict, list)):
                data = inner_data

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

        # 🚨 [DIAG-REQ] 采样定位请求风暴来源 (2026-08-14)：S1 子服务线程持续增长 (275 req/min)，
        # 但主服务日志 action 记录极少，无法定位高频请求源。此处每 300 个请求采样一次完整调用栈，
        # 定位是哪个调用方（market_engine 循环 / 前端端点 / WS 推送）在持续发起子服务请求。
        # 仅采样不刷屏，定位后移除。
        diag_n = getattr(self, "_diag_req_count", 0)
        self._diag_req_count = diag_n + 1
        if diag_n % 300 == 0:
            import traceback

            _tb = "".join(traceback.format_stack(limit=8)[:-1])
            logger.warning(
                "[DIAG-REQ] source=%s action=%s ticker=%s caller_stack:\n%s",
                source,
                payload.get("action"),
                (payload.get("params") or {}).get("ticker"),
                _tb,
            )

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
        action: Optional[str] = None,
        record_breaker: bool = True,
    ):
        """
        更新节点状态（BE-ARCH-08i: action 级熔断隔离 + 节点级兜底）。

        关键区分：
        - record_breaker=False（探针/链接测试等非业务流量）：仅刷新 heartbeat，
          不写入任何熔断/退避计数，避免探测失败污染业务熔断器（COMM-01 test-link 探针）。
        - 限流类错误不计入任何熔断计数，触发独立退避机制。
        - 普通错误按 action 维度计数：
          * 单 action 连续失败 ≥ _ACTION_MAX_FAILURES → 仅熔断该 action
            （不影响同节点其它 action，避免单节点 pin 源一处失败误杀全部能力）。
          * 同时处于熔断态的不同 action 数 ≥ _node_breaker_threshold(node)
            （动态阈值，按节点 capabilities 规模缩放）→ 判定为进程级故障
            （子服务崩/HMAC 错/网络断），整节点熔断兜底。
        - 成功：重置对应 action 计数；若整节点成功，重置全部。
        """
        async with self._lock:
            node = self._nodes.get(node_name)
            if not node:
                return

            node.last_heartbeat = time.time()

            # 探针/链接测试等非业务流量：不污染熔断器，仅记录心跳后直接返回
            if not record_breaker:
                return

            if success:
                node.error_count = 0
                node.status = "healthy"
                if action is not None:
                    node.action_errors.pop(action, None)
                    node.action_breaker_until.pop(action, None)
                else:
                    node.action_errors.clear()
                    node.action_breaker_until.clear()
                return

            # 限流类错误不计入熔断器失败计数
            if error_category != ErrorCategory.NORMAL:
                logger.info(
                    f"[RateLimit] 节点 {node_name} 限流 ({error_category.value}): {error} — 不计入熔断器，触发独立退避"
                )
                return

            # 普通错误：action 级计数
            action_key = action or "__node__"
            node.error_count += 1
            if action is not None:
                cnt = node.action_errors.get(action_key, 0) + 1
                node.action_errors[action_key] = cnt
                if cnt >= _ACTION_MAX_FAILURES:
                    node.action_breaker_until[action_key] = time.time() + get_cooldown_seconds()
                    logger.warning(
                        f"[CircuitBreaker] 节点 {node_name} action={action} 连续失败 {cnt} 次，"
                        f"触发 action 级熔断 (冷却 {get_cooldown_seconds():.0f}s)"
                    )
                    # 节点级兜底：统计当前处于熔断态的不同 action 数，用动态阈值判定
                    now = time.time()
                    broken_actions = {k for k, until in node.action_breaker_until.items() if now < until}
                    threshold = _node_breaker_threshold(node)
                    if len(broken_actions) >= threshold:
                        node.status = "unhealthy"
                        node.circuit_breaker_until = time.time() + get_cooldown_seconds()
                        logger.warning(
                            f"[CircuitBreaker] 节点 {node_name} 多个 action 同时熔断 "
                            f"({sorted(broken_actions)})，达到动态阈值 {threshold}，"
                            f"判定进程级故障，整节点熔断兜底"
                        )
            else:
                # 无 action 信息（旧调用点）：退化为节点级熔断，保持原行为
                if node.error_count >= 3:
                    node.status = "unhealthy"
                    node.circuit_breaker_until = time.time() + get_cooldown_seconds()
                    logger.warning(f"[CircuitBreaker] 节点 {node_name} 触发熔断: {error}")

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

    @staticmethod
    def _pin_node_usable(node: "DataSourceNode") -> bool:
        """BE-ARCH-08e: 单节点 pin 源半开探测门控。

        单节点 pin 源 (akshare/tushare/futu/fmp/finnhub/fred/dbnomics/rbi/search)
        熔断后若仅用 `status != "healthy"` 门控，则永远不会再发请求 → 永不恢复
        （不请求就不可能成功，不成功就永远 unhealthy）。

        此处允许：节点 healthy **或** 已熔断且冷却已到期的半开探测 (HALF_OPEN)，
        对齐子服务侧已有的 HALF_OPEN 语义。探测成功由 `_update_node_status` 翻回
        healthy；失败则续冷却。限流类错误不计入熔断计数，本身不会触发 permanent 失效。
        """
        if node.status == "healthy":
            return True
        return time.time() >= node.circuit_breaker_until

    @staticmethod
    def _action_usable(node: "DataSourceNode", action: str) -> bool:
        """BE-ARCH-08i: action 级熔断门控。

        单节点 pin 源某 action 被单独熔断后，仅该 action 的请求被拦截，
        同节点其它 action 照常放行。action 冷却到期后允许半开探测（重试成功即恢复）。

        节点级熔断（status != healthy）仍由 `_pin_node_usable` 统一门控，
        本函数只负责 action 维度，需与 `_pin_node_usable` 联合使用：
            if not (_pin_node_usable(node) and _action_usable(node, action)): ...
        """
        if action is None:
            return True
        until = node.action_breaker_until.get(action, 0.0)
        return time.time() >= until

    def _maybe_offline(self, source: str, action: str = "", **params) -> Optional[Dict[str, Any]]:
        """SVC-06: 离线 stub 拦截。

        当 OFFLINE_MODE=1 或 QUANT_ENV∈{offline,testing,dev} 时，直接返回确定性 stub，
        连子服务节点都不触网。生产环境（OFFLINE_MODE=0）返回 None 走真实远程。
        """
        if not is_offline_mode_enabled():
            return None
        return build_offline_response(source, action, **params)

    async def fetch_yfinance(self, ticker: str, fetch_type: str, **kwargs) -> Dict[str, Any]:
        """联邦 YF 流量到 US-YF-A/B 子服务节点。

        后端进程不再本地执行 yfinance。若路由未启用或所有子服务节点不可用，
        直接返回失败（不再降级本地 yfinance）。
        """
        record_breaker = bool(kwargs.pop("_record_breaker", True))
        offline = self._maybe_offline("yfinance", fetch_type, ticker=ticker, **kwargs)
        if offline is not None:
            return offline

        if not self._enabled:
            return {
                "success": False,
                "message": "DataSourceRouter 未启用，无法路由 YFinance 子服务流量",
            }

        nodes = self._get_healthy_nodes("yfinance")
        if not nodes:
            # DIST-SEC-03(2026-08-14): 修复「无健康节点即永久失败」的恢复不对称性。
            # yfinance 是单节点（yf_primary），_get_healthy_nodes 仅返回 status=="healthy"
            # 的节点，一旦节点进入熔断冷却或被标 unhealthy 便永远进不来，而业务流量又
            # 不会触发半开探测 → 直到后台探针轮询才偶发恢复，期间 HISTORY 等请求全失败。
            # 这里兜底：冷却期已过的 unhealthy 节点以「半开」身份参与探测，失败则继续熔断，
            # 成功则让 _update_node_status 翻回 healthy。与 futu/fmp 等单节点源行为对齐。
            half_open = [
                n
                for key, n in self._nodes.items()
                if key.startswith("yf_") and n.status != "healthy" and n.circuit_breaker_until <= time.time()
            ]
            if not half_open:
                logger.warning("[YFinance] 无健康/可探测子服务节点（熔断冷却中或全 offline）")
                return {
                    "success": False,
                    "message": "No healthy YFinance subservice node (local yfinance disabled)",
                }
            logger.info(f"[YFinance] 健康节点空，启用半开探测节点: {[n.name for n in half_open]}")
            nodes = half_open

        # DIST-SEC-05(2026-08-14): 雅虎服务熔断（表现为 possibly delisted / 连接失败 / 限流）时的
        # 自愈策略 —— 切备份节点 + 退避 + 冷却后恢复。
        #  1. 每个 YF 节点持有独立 RateLimitThrottler，节点级失败进入指数退避，退避期内跳过该节点
        #     （不再反复打爆雅虎，避免雪崩），请求被导向其它备份节点（S2/S3/S4 不同公网 IP）。
        #  2. 退避到期（半开）后自动重试，成功则 on_success 逐步降速恢复。
        #  3. 所有节点都处于退避/不可达 → 整条 yfinance 源暂时熔断，返回明确可重试错误。
        # 注意：退避作用在主服务侧（源入口），与子服务 yfinance:{symbol} 粒度熔断互补 —— 子服务防
        # 单标的 miss 误杀，主服务防雅虎整源熔断时仍高频重试打爆上游。
        throttlers = {n.name: rate_limit_registry.get_throttler(n.name) for n in nodes}
        throttled_all = True
        tried = []
        for node in nodes:
            throttler = throttlers[node.name]
            # 退避中：跳过该节点（不发起请求，不计入失败），导向备份节点
            if throttler.should_throttle():
                logger.info(
                    f"[YFinance] 节点 {node.name} 退避中（剩余 {throttler.remaining_throttle_seconds():.0f}s），跳过"
                )
                continue
            throttled_all = False
            tried.append(node.name)
            try:
                payload = {
                    "source": "yfinance",
                    "action": _YF_ACTION_MAP.get(fetch_type.lower(), fetch_type.upper()),
                    "params": self._normalize_outbound_params({"ticker": ticker, **kwargs}),
                }
                result = await self._send_request(node, "yfinance", payload)

                # 检查返回结果中是否包含错误分类信息（含文本兜底：子服务未带
                # error_category 时按 message 识别限流，避免限流误判为普通失败）
                error_category = _infer_error_category(result)

                if result.get("status") == "success" or result.get("success"):
                    await self._update_node_status(node.name, success=True, record_breaker=record_breaker)
                    throttler.on_success()
                    return result

                # 非普通错误类处理
                if error_category != ErrorCategory.NORMAL:
                    if error_category == ErrorCategory.DATA_UNAVAILABLE:
                        # DIST-SEC-04/05(2026-08-14): 该标的 Yahoo 无数据属标的层面问题。
                        # 但雅虎常把『服务暂时不可用』伪装成 delisted/No data，故仍尝试 failover 到
                        # 下一个备份节点（不同 IP 可能正常）；若已是最后一个节点则干净返回。
                        logger.warning(f"[YFinance] 节点 {node.name} 数据不可用 ({ticker}): {result.get('error')}")
                        if node is not nodes[-1]:
                            continue
                        return {
                            "success": False,
                            "status": "error",
                            "message": f"数据不可用 (Yahoo 无 {ticker} 数据): {result.get('error')}",
                            "error_category": "data_unavailable",
                            "source": "yfinance",
                        }
                    # 限流类错误：不计入熔断器，进入退避并 failover 到下一节点
                    logger.warning(f"[YFinance] 节点 {node.name} 限流 ({error_category.value}): {ticker}")
                    throttler.on_rate_limit()
                    await self._update_node_status(
                        node.name,
                        success=False,
                        error="rate_limit",
                        error_category=error_category,
                        record_breaker=record_breaker,
                    )
                    continue

                # 普通错误（连接失败/超时/5xx/源级故障）：计入熔断 + 退避，failover 到下一节点
                logger.warning(f"[YFinance] 节点 {node.name} 源级失败: {ticker}, {result.get('message')}")
                throttler.on_rate_limit()
                await self._update_node_status(
                    node.name,
                    success=False,
                    error=str(result.get("message")),
                    error_category=ErrorCategory.NORMAL,
                    record_breaker=record_breaker,
                )

            except Exception as e:
                logger.warning(f"[YFinance] 节点 {node.name} 失败: {ticker}, {str(e)}")
                throttler.on_rate_limit()
                await self._update_node_status(
                    node.name,
                    success=False,
                    error=str(e),
                    error_category=ErrorCategory.NORMAL,
                    record_breaker=record_breaker,
                )

        if throttled_all:
            logger.warning("[YFinance] 所有子服务节点均在退避期（雅虎熔断保护中），整源暂不可用")
            return {
                "success": False,
                "status": "error",
                "message": "YFinance 源熔断保护中（雅虎限流/不可用），退避结束后再试",
                "error_category": "rate_limit",
                "source": "yfinance",
                "throttled_nodes": list(throttlers.keys()),
            }

        logger.warning(f"[YFinance] 所有子服务节点失败（已尝试 {tried}，后端已移除本地兜底）")
        return {
            "success": False,
            "message": "All YFinance subservice nodes failed (local yfinance disabled)",
        }

    async def fetch_akshare(self, action: str, **kwargs) -> Dict[str, Any]:
        """AKShare 远程节点代理 (北京单节点 DS_CAPABILITIES=akshare)。

        设计原则 (2026-08-07): 仅远程，移除本地 SDK 降级。router 未启用或远程节点
        不可用时直接返回失败（源失效在监控中如实显示）。成功响应仍存档 STALE/热点
        缓存，        供 CN 断连时监控侧识别降级，但不自动回退本地。
        """
        record_breaker = bool(kwargs.pop("_record_breaker", True))
        offline = self._maybe_offline("akshare", action, **kwargs)
        if offline is not None:
            return offline

        remote_node = self._nodes.get("akshare_remote")
        remote_action = action.upper()
        if (
            not self._enabled
            or not remote_node
            or not self._pin_node_usable(remote_node)
            or not self._action_usable(remote_node, remote_action)
        ):
            logger.warning("[AKShare] 远程节点不可用（后端已移除本地兜底）")
            return {"status": "error", "message": "No healthy AKShare remote node (local SDK disabled)"}

        try:
            payload = {
                "source": "akshare",
                "action": remote_action,
                "params": self._normalize_outbound_params(dict(kwargs)),
            }
            result = await self._send_request(remote_node, "akshare", payload)

            if result.get("status") == "success":
                await self._update_node_status(
                    remote_node.name, success=True, action=remote_action, record_breaker=record_breaker
                )
                # 成功响应存档，供监控侧识别降级（不再回退本地）
                await self._save_akshare_stale(action, kwargs, result)
                await self._save_akshare_cache(action, kwargs, result)
                return result

            # 零幻觉红线：远程明确判定 UNSUPPORTED（如 AKShare 不支持港股）时，
            # 是确定性结论，禁止降级到 STALE 缓存（缓存可能是错误标的的空数据，
            # 如 market=A + data=[]，降级会把假数据当成功返回）。
            # 直接透传 UNSUPPORTED 错误，让 facade 改走下一候选源（Futu/YFinance）。
            if result.get("error_category") == "UNSUPPORTED":
                return result

            await self._update_node_status(
                remote_node.name,
                success=False,
                error=str(result.get("message")),
                action=remote_action,
                record_breaker=record_breaker,
            )

        except Exception as e:
            logger.warning(f"[AKShare] 远程节点失败：{remote_node.name}, {action}, {str(e)}")
            await self._update_node_status(
                remote_node.name, success=False, error=str(e), action=remote_action, record_breaker=record_breaker
            )

        # BE-ARCH-08f: 远程失败不返回裸错，先尝试 STALE 缓存降级 (DIST-19)。
        # _get_akshare_stale 命中即打 degraded/stale_source 标记（并已上报指标）。
        stale = await self._get_akshare_stale(action, kwargs)
        if stale is not None:
            return stale

        logger.warning("[AKShare] 远程节点失败且无 STALE 缓存（后端已移除本地兜底）")
        return {"status": "error", "message": "AKShare remote node failed (local SDK disabled)"}

    async def fetch_tushare(self, action: str, **params) -> Dict[str, Any]:
        """Tushare 远程节点代理 (北京从节点 DS_CAPABILITIES=tushare,akshare)。

        设计原则 (2026-08-07): 仅远程，移除本地适配器降级。所有 tushare action
        经 _TS_ACTION_MAP 归一化后走远程；子服务不支持的 action 直接返回失败，
        不再回退本地 TushareService。
        """
        record_breaker = bool(params.pop("_record_breaker", True))
        offline = self._maybe_offline("tushare", action, **params)
        if offline is not None:
            return offline

        remote_node = self._nodes.get("tushare_remote")
        remote_action = _TS_ACTION_MAP.get(action.lower())
        if remote_action is None:
            logger.warning(f"[Tushare] action={action} 远程子服务不支持，本地兜底已移除")
            return {"success": False, "message": f"unsupported tushare action (remote-only): {action}"}

        if (
            not self._enabled
            or not remote_node
            or not self._pin_node_usable(remote_node)
            or not self._action_usable(remote_node, remote_action)
        ):
            logger.warning("[Tushare] 远程节点不可用（后端已移除本地兜底）")
            return {"success": False, "message": "No healthy Tushare remote node (local adapter disabled)"}

        try:
            payload = {
                "source": "tushare",
                "action": remote_action,
                "params": self._normalize_outbound_params(dict(params)),
            }
            result = await self._send_request(remote_node, "tushare", payload)
            if result.get("success"):
                await self._update_node_status(
                    remote_node.name, success=True, action=remote_action, record_breaker=record_breaker
                )
                return result
            await self._update_node_status(
                remote_node.name,
                success=False,
                error=str(result.get("message")),
                action=remote_action,
                record_breaker=record_breaker,
            )
        except Exception as e:
            logger.warning(f"[Tushare] 远程节点失败: {remote_node.name}, {action}, {str(e)}")
            await self._update_node_status(
                remote_node.name, success=False, error=str(e), action=remote_action, record_breaker=record_breaker
            )

        logger.warning("[Tushare] 远程节点失败（后端已移除本地兜底）")
        return {"success": False, "message": "Tushare remote node failed (local adapter disabled)"}

    async def fetch_futu(self, action: str, **params) -> Dict[str, Any]:
        """Futu 主节点 HTTP 代理 (source="futu", pin 主节点)。

        Futu OpenD 仅部署在 US-MASTER 主节点 (127.0.0.1:11111), 由主节点
        data_subservice (DS_CAPABILITIES=futu) 持有长连接并对外提供 source=futu。
        主服务不持有 SDK, 所有 futu 访问经本路由 pin 到 futu_master 节点。

        设计原则 (2026-08-07): 仅远程，移除本地 futu_service 降级通道。
        """
        record_breaker = bool(params.pop("_record_breaker", True))
        offline = self._maybe_offline("futu", action, **params)
        if offline is not None:
            return offline

        remote_action = _FUTU_ACTION_MAP.get(action.lower(), action.upper())

        # 业务侧统一用 ticker/tickers, 子服务 worker 契约用 symbol/symbols, 此处对齐
        norm_params = self._futu_normalize_params(remote_action, params)

        remote_node = self._nodes.get("futu_master")
        if (
            not self._enabled
            or not remote_node
            or not self._pin_node_usable(remote_node)
            or not self._action_usable(remote_node, remote_action)
        ):
            logger.warning("[Futu] 远程节点不可用（后端已移除本地兜底）")
            return {"status": "error", "message": "No healthy Futu remote node (local SDK disabled)"}

        # DIST-23 + DIST-SEC-03: 交易类 / 权限依赖型 action 与行情类 action 熔断隔离
        # 根因(2026-08-11 实战): OpenD 行情已 CONNECTED, 但交易连接(TrdCtx)因未解锁
        # 返回 error, 此前 ACCOUNT_INFO 失败会触发 futu_master 全局熔断 → 连 QUOTE 行情
        # 一起被误杀, 监控却只显示行情 CONNECTED, 形成隐蔽故障。
        # 现约定: 账户/交易类 + 权限依赖型扩展行情(FUND_FLOW/OPTION_CHAIN 等)失败
        # 不入熔断器失败计数(避免误伤行情通道), 仅记录日志。
        # (BE-ARCH-08i 下, 行情类 action 间也已按 action 维度隔离, 此豁免是额外一层保护)
        # DIST-SEC-03 (2026-08-14 实战): S1 未配置 FUTU_PWD_UNLOCK(RSA 私钥), 交易连接
        # 未解锁 → FUND_FLOW(资金流, 部分市场需交易权限)持续返回 error → 被普通计数累积
        # → 多个 action 同时熔断 → 整节点 futu_master unhealthy → QUOTE/HEALTH 行情通道
        # 被误杀, 前端全盘报 "No healthy Futu remote node"。将其纳入豁免集彻底隔离。
        _FUTU_TRADE_ACTIONS = {
            "ACCOUNT_INFO",
            "PLACE_ORDER",
            "MODIFY_ORDER",
            "QUERY_ORDER",
            "EMERGENCY_LIQUIDATION",
            # DIST-SEC-03: 权限/交易依赖型扩展行情, 失败属"数据不可用"而非"节点宕机",
            # 不应触发节点级熔断误伤 QUOTE/HEALTH 等核心行情通道
            "FUND_FLOW",
            "OPTION_CHAIN",
            "WARRANT_CHAIN",
            "FUNDAMENTAL",
            # F4 扩展行情同样属"数据不可用"型, 失败不污染节点/全局熔断
            "CAPITAL_DISTRIBUTION",
            "HEAT_MAP",
            "ANALYST_CONSENSUS",
            "FED_WATCH",
        }
        is_trade_action = remote_action in _FUTU_TRADE_ACTIONS

        try:
            payload = {
                "source": "futu",
                "action": remote_action,
                "params": norm_params,
            }
            result = await self._send_request(remote_node, "futu", payload)
            if result.get("status") == "success":
                await self._update_node_status(
                    remote_node.name, success=True, action=remote_action, record_breaker=record_breaker
                )
                # 直接透传子服务信封 (含 status/data 字段)
                return result
            if is_trade_action:
                # 账户/交易/权限依赖型 action 失败: 只记录, 不计入节点熔断, 保护行情通道
                logger.warning(
                    f"[Futu] 非行情通道 action={remote_action} 失败(不触发熔断, 隔离行情通道): {result.get('message')}"
                )
                return result
            await self._update_node_status(
                remote_node.name,
                success=False,
                error=str(result.get("message")),
                action=remote_action,
                record_breaker=record_breaker,
            )
            # 透传子服务原始信封（含真实 message/status），避免被下方硬编码错误覆盖；
            # 子服务失败信封可能缺 source 字段，此处补齐以便上层识别来源
            result.setdefault("source", "futu")
            return result
        except Exception as e:
            logger.warning(f"[Futu] 远程节点失败: {remote_node.name}, {remote_action}, {str(e)}")
            if is_trade_action:
                # 同上: 交易/权限依赖型 action 异常不误伤行情熔断
                return {"status": "error", "message": str(e), "trade_action_skipped_breaker": True}
            await self._update_node_status(
                remote_node.name, success=False, error=str(e), action=remote_action, record_breaker=record_breaker
            )

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

    @staticmethod
    def _normalize_outbound_params(params: Dict[str, Any]) -> Dict[str, Any]:
        """BE-ARCH-08b: 业务侧统一用 ticker/tickers，子服务 worker 读 symbol/symbols，
        全链路无归一导致子服务收到 symbol=None（线上取不到数）。

        一处 guard：双键兼容——业务侧键名映射副本的同时保留原键，使子服务无论读
        symbol 还是 ticker 均能命中，消除 yfinance/akshare/fmp/tushare 的键名错位。
        ponytail: 不做字段语义转换（如 ktype→interval），仅解决键名错位这一明确天花板。
        """
        out = dict(params)
        if "ticker" in out and "symbol" not in out:
            out["symbol"] = out["ticker"]
        if "tickers" in out and "symbols" not in out:
            out["symbols"] = out["tickers"]
        return out

    async def fetch_fmp(self, action: str, **params) -> Dict[str, Any]:
        """FMP 主节点 HTTP 代理 (source="fmp", pin 主节点)。

        FMP 数据源连接层 (REST + credit 配额/指标) 已下沉 data_subservice
        (_internal/fmp + fmp_worker.py::handle_fmp)。主服务不持有 REST 客户端,
        所有 fmp 访问经本路由 pin 到 fmp_master 节点。

        设计原则 (2026-08-07): 仅远程，移除本地 _local_get 直连兜底。
        """
        record_breaker = bool(params.pop("_record_breaker", True))
        offline = self._maybe_offline("fmp", action, **params)
        if offline is not None:
            return offline

        _FMP_ACTION_MAP = {
            "quote": "QUOTE",
            "profile": "PROFILE",
            "income_statement": "INCOME_STATEMENT",
            # BE-ARCH-08g: Facade 的 get_fundamental/get_fundamental_info 以 FUNDAMENTAL/INFO
            # 抵达, 显式映射避免回退到 action.upper() 的隐式约定, 保证 worker 分支命中。
            "fundamental": "FUNDAMENTAL",
            "info": "INFO",
        }
        remote_action = _FMP_ACTION_MAP.get(action.lower(), action.upper())

        norm_params = self._normalize_outbound_params(dict(params))

        remote_node = self._nodes.get("fmp_master")
        if (
            not self._enabled
            or not remote_node
            or not self._pin_node_usable(remote_node)
            or not self._action_usable(remote_node, remote_action)
        ):
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
                await self._update_node_status(
                    remote_node.name, success=True, action=remote_action, record_breaker=record_breaker
                )
                # 配额耗尽错误已带 error_category=quota, 透传给业务侧
                if result.get("error_category") == "quota":
                    await self._update_node_status(
                        remote_node.name,
                        success=False,
                        error="quota",
                        error_category=ErrorCategory.QUOTA_EXHAUSTED,
                        record_breaker=record_breaker,
                    )
                    return result
                return result
            # BE-ARCH-08d: 失败但可能是限流类 (429/quota/ip_blocked), 透传 error_category
            # 使 RateLimitThrottler 退避与熔断分流生效, 而非一律计入普通失败触发熔断
            ec = result.get("error_category")
            if ec:
                await self._update_node_status(
                    remote_node.name,
                    success=False,
                    error=str(result.get("message")),
                    error_category=ErrorCategory(ec)
                    if ec in {e.value for e in ErrorCategory}
                    else ErrorCategory.NORMAL,
                    action=remote_action,
                    record_breaker=record_breaker,
                )
            else:
                await self._update_node_status(
                    remote_node.name,
                    success=False,
                    error=str(result.get("message")),
                    action=remote_action,
                    record_breaker=record_breaker,
                )
        except Exception as e:
            logger.warning(f"[FMP] 远程节点失败: {remote_node.name}, {remote_action}, {str(e)}")
            await self._update_node_status(
                remote_node.name, success=False, error=str(e), action=remote_action, record_breaker=record_breaker
            )

        logger.warning("[FMP] 远程节点失败（后端已移除本地兜底）")
        return {"status": "error", "message": "FMP remote node failed (local fallback disabled)"}

    async def fetch_finnhub(self, action: str, **params) -> Dict[str, Any]:
        """Finnhub 远程节点代理 (主节点 DS_CAPABILITIES=finnhub)。

        Finnhub 连接层 (REST + WS tick 订阅) 已下沉 data_subservice
        (_internal/finnhub + finnhub_worker.py)。主服务不持有 FinnhubService / WS 订阅，
        quote 走 REST 快照。仅远程，无本地 SDK 兜底。
        """
        record_breaker = bool(params.pop("_record_breaker", True))
        offline = self._maybe_offline("finnhub", action, **params)
        if offline is not None:
            return offline

        remote_action = _FINNHUB_ACTION_MAP.get(action.lower(), action.upper())
        remote_node = self._nodes.get("finnhub_master")
        if (
            not self._enabled
            or not remote_node
            or not self._pin_node_usable(remote_node)
            or not self._action_usable(remote_node, remote_action)
        ):
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
                await self._update_node_status(
                    remote_node.name, success=True, action=remote_action, record_breaker=record_breaker
                )
                return result
            # BE-ARCH-08d: 失败但可能是限流类 (429/ip_blocked), 透传 error_category
            ec = result.get("error_category")
            if ec:
                await self._update_node_status(
                    remote_node.name,
                    success=False,
                    error=str(result.get("message")),
                    error_category=ErrorCategory(ec)
                    if ec in {e.value for e in ErrorCategory}
                    else ErrorCategory.NORMAL,
                    action=remote_action,
                    record_breaker=record_breaker,
                )
            else:
                await self._update_node_status(
                    remote_node.name,
                    success=False,
                    error=str(result.get("message")),
                    action=remote_action,
                    record_breaker=record_breaker,
                )
        except Exception as e:
            logger.warning(f"[Finnhub] 远程节点失败: {remote_node.name}, {remote_action}, {str(e)}")
            await self._update_node_status(
                remote_node.name, success=False, error=str(e), action=remote_action, record_breaker=record_breaker
            )

        logger.warning("[Finnhub] 远程节点失败（后端已移除本地兜底）")
        return {"status": "error", "message": "Finnhub remote node failed (local SDK disabled)"}

    async def fetch_fred(self, action: str, **params) -> Dict[str, Any]:
        """FRED 远程节点代理 (主节点 DS_CAPABILITIES=fred)。

        宏观连接层 (FRED REST) 已下沉 data_subservice (_internal/fred + fred_worker.py)。
        主服务不再本地调用 fred_service。仅远程。
        """
        record_breaker = bool(params.pop("_record_breaker", True))
        offline = self._maybe_offline("fred", action, **params)
        if offline is not None:
            return offline

        remote_node = self._nodes.get("fred_master")
        remote_action = action.upper()
        if (
            not self._enabled
            or not remote_node
            or not self._pin_node_usable(remote_node)
            or not self._action_usable(remote_node, remote_action)
        ):
            logger.warning("[FRED] 远程节点不可用（后端已移除本地兜底）")
            return {"status": "error", "message": "No healthy FRED remote node (local service disabled)"}

        try:
            payload = {
                "source": "fred",
                "action": remote_action,
                "params": dict(params),
            }
            result = await self._send_request(remote_node, "fred", payload)
            if result.get("status") == "success":
                await self._update_node_status(
                    remote_node.name, success=True, action=remote_action, record_breaker=record_breaker
                )
                return result
            await self._update_node_status(
                remote_node.name,
                success=False,
                error=str(result.get("message")),
                action=remote_action,
                record_breaker=record_breaker,
            )
        except Exception as e:
            logger.warning(f"[FRED] 远程节点失败: {remote_node.name}, {action}, {str(e)}")
            await self._update_node_status(
                remote_node.name, success=False, error=str(e), action=remote_action, record_breaker=record_breaker
            )

        logger.warning("[FRED] 远程节点失败（后端已移除本地兜底）")
        return {"status": "error", "message": "FRED remote node failed (local service disabled)"}

    async def fetch_dbnomics(self, action: str, **params) -> Dict[str, Any]:
        """DBnomics 远程节点代理 (主节点 DS_CAPABILITIES=dbnomics)。

        宏观连接层 (DBnomics REST) 已下沉 data_subservice (_internal/dbnomics + dbnomics_worker.py)。
        仅远程。
        """
        record_breaker = bool(params.pop("_record_breaker", True))
        offline = self._maybe_offline("dbnomics", action, **params)
        if offline is not None:
            return offline

        remote_node = self._nodes.get("dbnomics_master")
        remote_action = action.upper()
        if (
            not self._enabled
            or not remote_node
            or not self._pin_node_usable(remote_node)
            or not self._action_usable(remote_node, remote_action)
        ):
            logger.warning("[DBnomics] 远程节点不可用（后端已移除本地兜底）")
            return {"status": "error", "message": "No healthy DBnomics remote node (local service disabled)"}

        try:
            payload = {
                "source": "dbnomics",
                "action": remote_action,
                "params": dict(params),
            }
            result = await self._send_request(remote_node, "dbnomics", payload)
            if result.get("status") == "success":
                await self._update_node_status(
                    remote_node.name, success=True, action=remote_action, record_breaker=record_breaker
                )
                return result
            await self._update_node_status(
                remote_node.name,
                success=False,
                error=str(result.get("message")),
                action=remote_action,
                record_breaker=record_breaker,
            )
        except Exception as e:
            logger.warning(f"[DBnomics] 远程节点失败: {remote_node.name}, {action}, {str(e)}")
            await self._update_node_status(
                remote_node.name, success=False, error=str(e), action=remote_action, record_breaker=record_breaker
            )

        logger.warning("[DBnomics] 远程节点失败（后端已移除本地兜底）")
        return {"status": "error", "message": "DBnomics remote node failed (local service disabled)"}

    async def fetch_rbi(self, action: str, **params) -> Dict[str, Any]:
        """RBI 远程节点代理 (主节点 DS_CAPABILITIES=rbi)。

        宏观连接层 (RBI 爬虫) 已下沉 data_subservice (_internal/rbi + rbi_worker.py)。
        仅远程。
        """
        record_breaker = bool(params.pop("_record_breaker", True))
        offline = self._maybe_offline("rbi", action, **params)
        if offline is not None:
            return offline

        remote_node = self._nodes.get("rbi_master")
        remote_action = action.upper()
        if (
            not self._enabled
            or not remote_node
            or not self._pin_node_usable(remote_node)
            or not self._action_usable(remote_node, remote_action)
        ):
            logger.warning("[RBI] 远程节点不可用（后端已移除本地兜底）")
            return {"status": "error", "message": "No healthy RBI remote node (local service disabled)"}

        try:
            payload = {
                "source": "rbi",
                "action": remote_action,
                "params": dict(params),
            }
            result = await self._send_request(remote_node, "rbi", payload)
            if result.get("status") == "success":
                await self._update_node_status(
                    remote_node.name, success=True, action=remote_action, record_breaker=record_breaker
                )
                return result
            await self._update_node_status(
                remote_node.name,
                success=False,
                error=str(result.get("message")),
                action=remote_action,
                record_breaker=record_breaker,
            )
        except Exception as e:
            logger.warning(f"[RBI] 远程节点失败: {remote_node.name}, {action}, {str(e)}")
            await self._update_node_status(
                remote_node.name, success=False, error=str(e), action=remote_action, record_breaker=record_breaker
            )

        logger.warning("[RBI] 远程节点失败（后端已移除本地兜底）")
        return {"status": "error", "message": "RBI remote node failed (local service disabled)"}

    async def fetch_search(self, source: str, **params) -> Dict[str, Any]:
        """搜索/抓取源远程代理 (Tavily / Bocha / Jina)。

        外部搜索/抓取经 data_subservice 统一代理 (search_worker.py)，主服务不再直接
        httpx 外部 API。source ∈ {tavily, bocha, jina}。仅远程。

        params 中的本地控制键 `_record_breaker`（bool，默认 True）：False 时表示
        探针/链接测试流量，失败不写入熔断计数（BE-ARCH-08i，避免 test-link 探测
        污染业务熔断器）。该键为本地控制标记，会被剥离、不透传给子服务。
        """
        # 剥离本地控制标记，避免污染子服务 payload
        record_breaker = bool(params.pop("_record_breaker", True))

        offline = self._maybe_offline("search", source, **params)
        if offline is not None:
            return offline

        remote_node = self._nodes.get("search_master")
        # search 节点承载 tavily/bocha/jina 三个源, 以 source 作为 action 维度隔离
        if (
            not self._enabled
            or not remote_node
            or not self._pin_node_usable(remote_node)
            or not self._action_usable(remote_node, source)
        ):
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
                await self._update_node_status(
                    remote_node.name, success=True, action=source, record_breaker=record_breaker
                )
                return result
            await self._update_node_status(
                remote_node.name,
                success=False,
                error=str(result.get("message")),
                action=source,
                record_breaker=record_breaker,
            )
        except Exception as e:
            logger.warning(f"[Search/{source}] 远程节点失败: {remote_node.name}, {str(e)}")
            await self._update_node_status(
                remote_node.name, success=False, error=str(e), action=source, record_breaker=record_breaker
            )

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

            # BE-ARCH-08i: 暴露 action 级熔断状态（当前处于熔断冷却期的 action + 剩余秒数）
            action_breakers = {
                action: max(0, int(until - now)) for action, until in node.action_breaker_until.items() if until > now
            }

            status["nodes"][name] = {
                "name": node.name,
                "url": node.url,
                "enabled": node.enabled,
                "weight": node.weight,
                "status": node.status,
                "capabilities": node.capabilities,
                "error_count": node.error_count,
                "cooldown_remaining": max(0, int(node.circuit_breaker_until - now)),
                # BE-ARCH-08i: action 级熔断状态（仅含冷却未到期的 action）
                "action_breakers": action_breakers,
                "action_error_counts": dict(node.action_errors),
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
