"""
==========================================
Cluster Manager - 集群管理与服务池
==========================================
负责:
1. 扫描 Redis 发现所有已注册的从节点
2. 按采集器类型维护服务池 (collector → [slave_nodes])
3. 提供带 failover 的 HTTP 代理调用
4. 健康追踪 (失败自动降级，恢复自动升级)
"""

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

# 健康追踪参数
HEALTH_CHECK_INTERVAL = 10  # 秒
FAILURE_THRESHOLD = 3  # 连续失败次数后标记不健康
RECOVERY_INTERVAL = 30  # 不健康后多久尝试恢复 (秒)
REQUEST_TIMEOUT = 15  # HTTP 调用超时 (秒)

# ==========================================
# Prometheus 指标 (集群通信)
# ==========================================
try:
    import prometheus_client

    CLUSTER_CALL_TOTAL = prometheus_client.Counter(
        "quant_cluster_call_total",
        "Total cluster collector calls",
        ["collector", "action", "result"],  # result: success / failover / all_failed
    )
    CLUSTER_CALL_DURATION = prometheus_client.Histogram(
        "quant_cluster_call_duration_seconds",
        "Cluster collector call duration",
        ["collector", "action"],
        buckets=(0.1, 0.5, 1, 2, 5, 10, 15),
    )
    CLUSTER_NODES_DISCOVERED = prometheus_client.Gauge(
        "quant_cluster_nodes_discovered",
        "Number of slave nodes discovered",
    )
    CLUSTER_POOLS_SIZE = prometheus_client.Gauge(
        "quant_cluster_pool_size",
        "Pool size per collector",
        ["collector"],
    )
    _PROM_AVAILABLE = True
except ImportError:
    _PROM_AVAILABLE = False


@dataclass
class SlaveNode:
    """从节点信息"""

    node_id: str
    host: str
    port: int
    collectors: List[str]
    status: str = "healthy"  # healthy | unhealthy | unknown
    last_seen: float = 0.0
    consecutive_failures: int = 0
    last_failure_time: float = 0.0

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def is_available(self) -> bool:
        if self.status == "healthy":
            return True
        if self.status == "unhealthy":
            # 超过恢复间隔，允许尝试
            return (time.time() - self.last_failure_time) > RECOVERY_INTERVAL
        return False  # unknown


class ClusterManager:
    """集群管理器 - 服务发现 + 服务池 + failover 代理 (多 Master 支持)"""

    def __init__(self):
        self._nodes: Dict[str, SlaveNode] = {}  # node_id → SlaveNode
        self._pools: Dict[str, List[str]] = {}  # collector → [node_ids]
        self._http_client: Optional[httpx.AsyncClient] = None
        self._refresh_task: Optional[asyncio.Task] = None
        self._callback_redis: Optional[Dict[str, Any]] = None  # 本 master 的 Redis 回调信息

    async def start(self):
        """启动集群管理器"""
        # trust_env=False: 集群内部通信不走系统代理 (避免 macOS 代理工具导致内网 IP ReadTimeout)
        self._http_client = httpx.AsyncClient(timeout=REQUEST_TIMEOUT, trust_env=False)
        # 构建本 master 的 Redis 回调信息 (供 slave 写入缓存)
        self._callback_redis = {
            "host": os.getenv("REDIS_HOST", "localhost"),
            "port": int(os.getenv("REDIS_PORT", 6379)),
            "password": os.getenv("REDIS_PASSWORD") or None,
        }
        # 从 .env 解析静态配置的从节点 (兜底)
        self._parse_static_slaves()
        # 探测静态从节点的 /health 端点，填充 collectors 列表
        await self._probe_static_slaves()
        # 启动定期刷新
        self._refresh_task = asyncio.create_task(self._refresh_loop())
        # 立即刷新一次
        await self._refresh_from_redis()
        logger.info(f"[ClusterManager] started: {len(self._nodes)} nodes, pools: {list(self._pools.keys())}")

    async def stop(self):
        """停止集群管理器"""
        if self._refresh_task:
            self._refresh_task.cancel()
        if self._http_client:
            await self._http_client.aclose()

    def _parse_static_slaves(self):
        """从 SLAVE_NODES 环境变量解析静态配置的从节点"""
        slave_urls = os.getenv("SLAVE_NODES", "")
        if not slave_urls:
            return
        for url in slave_urls.split(","):
            url = url.strip()
            if not url:
                continue
            # 解析 http://host:port 格式
            try:
                from urllib.parse import urlparse

                parsed = urlparse(url)
                host = parsed.hostname or "localhost"
                port = parsed.port or 8001
                node_id = host  # 用 host 作为默认 ID
                self._nodes[node_id] = SlaveNode(
                    node_id=node_id,
                    host=host,
                    port=port,
                    collectors=[],  # 静态配置不知道 collectors，等 health 探测或 Redis 刷新填充
                    status="unknown",
                )
            except Exception as e:
                logger.warning(f"[ClusterManager] Failed to parse slave URL: {url}: {e}")

    async def _probe_static_slaves(self):
        """探测所有静态配置的从节点 /health 端点，填充 collectors 和状态"""
        for node_id, node in list(self._nodes.items()):
            if node.collectors or node.status == "healthy":
                continue  # 已通过 Redis 心跳获取过信息
            try:
                url = f"{node.base_url}/health"
                resp = await self._http_client.get(url, timeout=20.0)
                resp.raise_for_status()
                data = resp.json().get("data", {})
                node.collectors = data.get("collectors", [])
                node.status = "healthy"
                node.last_seen = time.time()
                logger.info(f"[ClusterManager] Probed {node_id}: collectors={node.collectors}")
            except Exception as e:
                logger.warning(f"[ClusterManager] Probe {node_id} failed: {e}")
        # 探测完成后重建服务池
        self._rebuild_pools()

    async def _refresh_from_redis(self):
        """从 Redis 扫描已注册的从节点，更新服务池并发布指标"""
        try:
            from backend.core.redis_client import redis_client

            discovered_ids = set()
            cursor = 0
            while True:
                cursor, keys = await redis_client.scan(cursor=cursor, match="quant:node:*", count=50)
                for key in keys:
                    key_str = key.decode("utf-8") if isinstance(key, bytes) else key
                    raw = await redis_client.get(key_str)
                    if not raw:
                        continue
                    try:
                        info = json.loads(raw)
                        node_id = info.get("node_id", key_str.split(":")[-1])
                        role = info.get("role", "slave")
                        if role == "master":
                            continue  # 跳过主节点自身

                        discovered_ids.add(node_id)

                        # 保留已有节点的健康状态，避免误判
                        existing = self._nodes.get(node_id)
                        if existing and existing.status == "unhealthy":
                            # 不健康节点重新被发现 → 标记为 unknown 待观察
                            existing.status = "unknown"
                            existing.last_seen = time.time()
                            existing.consecutive_failures = 0
                        else:
                            self._nodes[node_id] = SlaveNode(
                                node_id=node_id,
                                host=info.get("host", "unknown"),
                                port=info.get("port", 8001),
                                collectors=info.get("collectors", []),
                                status="healthy",
                                last_seen=time.time(),
                            )
                    except (json.JSONDecodeError, KeyError) as e:
                        logger.debug(f"[ClusterManager] skip invalid node key {key_str}: {e}")

                if cursor == 0:
                    break

            # 重建服务池
            self._rebuild_pools()

            # 发布 Prometheus 指标
            if _PROM_AVAILABLE:
                CLUSTER_NODES_DISCOVERED.set(len(self._nodes))
                for collector_name, node_ids in self._pools.items():
                    CLUSTER_POOLS_SIZE.labels(collector=collector_name).set(len(node_ids))

            if discovered_ids:
                logger.debug(f"[ClusterManager] refreshed: {len(self._nodes)} nodes, pools: {list(self._pools.keys())}")

        except Exception as e:
            logger.warning(f"[ClusterManager] Redis refresh failed: {e}")

    def _rebuild_pools(self):
        """根据所有已知节点重建 collector → [node_ids] 映射"""
        pools: Dict[str, List[str]] = {}
        for node_id, node in self._nodes.items():
            for collector in node.collectors:
                if collector not in pools:
                    pools[collector] = []
                if node_id not in pools[collector]:
                    pools[collector].append(node_id)
        self._pools = pools

    async def _refresh_loop(self):
        """定期刷新节点列表，清理超时节点"""
        stale_count = 0
        while True:
            try:
                await self._refresh_from_redis()
                # 清理超时未心跳的节点 (TTL=15s, 容忍 60s)
                now = time.time()
                stale = [nid for nid, n in self._nodes.items() if n.last_seen > 0 and (now - n.last_seen) > 60]
                for nid in stale:
                    logger.info(f"[ClusterManager] Node {nid} timed out (no heartbeat for >60s)")
                    del self._nodes[nid]
                if stale:
                    self._rebuild_pools()
                    stale_count += len(stale)
            except Exception as e:
                logger.warning(f"[ClusterManager] refresh loop error: {e}")
            await asyncio.sleep(HEALTH_CHECK_INTERVAL)

    # ==========================================
    # 服务池查询
    # ==========================================

    def get_pool(self, collector: str) -> List[SlaveNode]:
        """获取指定采集器的可用服务池"""
        node_ids = self._pools.get(collector, [])
        return [self._nodes[nid] for nid in node_ids if nid in self._nodes]

    def get_available_nodes(self, collector: str) -> List[SlaveNode]:
        """获取指定采集器当前可用的节点 (过滤掉不健康的)"""
        return [n for n in self.get_pool(collector) if n.is_available]

    def get_cluster_status(self) -> Dict[str, Any]:
        """获取集群整体状态 (供 /api/v1/cluster 使用)"""
        master_collectors = []
        from backend.workers.collector_registry import get_enabled_collectors

        if os.getenv("NODE_ROLE", "master") == "master":
            master_collectors = get_enabled_collectors()

        slaves = []
        for node in self._nodes.values():
            slaves.append(
                {
                    "node_id": node.node_id,
                    "host": node.host,
                    "port": node.port,
                    "collectors": node.collectors,
                    "status": node.status,
                    "consecutive_failures": node.consecutive_failures,
                    "last_seen_ago": (f"{int(time.time() - node.last_seen)}s" if node.last_seen > 0 else "never"),
                }
            )

        return {
            "master": {
                "collectors": master_collectors,
            },
            "slaves": slaves,
            "pools": {collector: [nid for nid in nids] for collector, nids in self._pools.items()},
        }

    # ==========================================
    # Failover 代理调用
    # ==========================================

    async def call_collector(
        self,
        collector: str,
        action: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        向指定采集器的服务池发起请求，自动 failover。
        若所有从节点不可用，降级尝试本地采集器。

        Args:
            collector: 采集器名称 (yfinance/futu/finnhub/akshare)
            action: 操作名 (fetch_quote/fetch_history/fetch_fund_flow 等)
            params: 请求参数

        Returns:
            采集结果 dict

        Raises:
            RuntimeError: 所有节点都不可用且无本地采集器
        """
        start_ts = time.monotonic()
        available = self.get_available_nodes(collector)

        if available:
            errors = []
            for node in available:
                try:
                    result = await self._call_node(node, action, params)
                    self._mark_healthy(node)
                    duration = time.monotonic() - start_ts
                    if _PROM_AVAILABLE:
                        CLUSTER_CALL_TOTAL.labels(collector=collector, action=action, result="success").inc()
                        CLUSTER_CALL_DURATION.labels(collector=collector, action=action).observe(duration)
                    return result
                except Exception as e:
                    self._mark_unhealthy(node)
                    errors.append(f"{node.node_id}({node.host}): {e}")
                    logger.warning(
                        f"[ClusterManager] {collector}/{action} failed on {node.node_id}: {e}, trying next..."
                    )
                    continue

            # 所有从节点失败，记录指标
            if _PROM_AVAILABLE:
                CLUSTER_CALL_TOTAL.labels(collector=collector, action=action, result="all_failed").inc()
            logger.warning(f"[ClusterManager] All {len(available)} slave nodes failed for {collector}/{action}")

        # 降级: 尝试本地采集器
        local_result = await self._try_local_fallback(collector, action, params)
        if local_result is not None:
            duration = time.monotonic() - start_ts
            if _PROM_AVAILABLE:
                CLUSTER_CALL_TOTAL.labels(collector=collector, action=action, result="local_fallback").inc()
                CLUSTER_CALL_DURATION.labels(collector=collector, action=action).observe(duration)
            return local_result

        raise RuntimeError(
            f"All nodes failed for {collector}/{action} and no local fallback available"
            + (f": {'; '.join(errors)}" if available else "")
        )

    async def _try_local_fallback(
        self,
        collector: str,
        action: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """尝试本地采集器作为降级方案"""
        from backend.workers.collector_registry import get_enabled_collectors

        local_collectors = get_enabled_collectors()
        if collector not in local_collectors:
            return None

        logger.info(f"[ClusterManager] Falling back to local {collector}/{action}")
        try:
            # 复用 slave_app 的 dispatch 逻辑
            from backend.slave_app import _dispatch_collect

            _params = dict(params or {})
            ticker = _params.pop("ticker", None)
            result = await _dispatch_collect(action, ticker, _params)
            return {"code": 0, "data": result, "source_node": "local"}
        except Exception as e:
            logger.warning(f"[ClusterManager] Local fallback {collector}/{action} failed: {e}")
            return None

    async def _call_node(
        self,
        node: SlaveNode,
        action: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        调用单个从节点的 HTTP 接口，携带本 master 的 Redis 回调信息。

        Payload 格式 (对齐 slave_app.CollectRequest):
          {"ticker": "AAPL", "params": {...}, "callback_redis": {...}}
        """
        url = f"{node.base_url}/collect/{action}"
        _params = dict(params or {})

        # 提取 ticker 到顶层 (slave CollectRequest 需要)
        ticker = _params.pop("ticker", None)

        payload = {
            "ticker": ticker,
            "params": _params,
            "callback_redis": self._callback_redis,
        }

        response = await self._http_client.post(url, json=payload)
        response.raise_for_status()
        return response.json()

    def _mark_healthy(self, node: SlaveNode):
        """标记节点健康"""
        if node.status != "healthy":
            logger.info(f"[ClusterManager] Node {node.node_id} recovered")
        node.status = "healthy"
        node.consecutive_failures = 0
        node.last_seen = time.time()

    def _mark_unhealthy(self, node: SlaveNode):
        """标记节点不健康"""
        node.consecutive_failures += 1
        node.last_failure_time = time.time()
        if node.consecutive_failures >= FAILURE_THRESHOLD:
            if node.status != "unhealthy":
                logger.warning(
                    f"[ClusterManager] Node {node.node_id} marked unhealthy after {node.consecutive_failures} failures"
                )
            node.status = "unhealthy"


# 全局单例
cluster_manager = ClusterManager()
