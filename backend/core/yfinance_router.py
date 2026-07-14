"""
YFinanceRouter — YFinance 客户端路由器
==========================================

基于 ServiceRegistry 动态发现节点，实现加权轮询 + 熔断过滤 + failover + STALE 缓存降级。

核心流程:
  1. _refresh_nodes(): 从 ServiceRegistry 发现节点 (5s 本地缓存)
  2. _select_nodes():   加权轮询 + 过滤熔断节点 + 限流压力排序
  3. call():            选节点 → 请求 → 成功则存档 STALE → 失败则 failover 下一节点
  4. _fallback_stale(): 所有节点失败 → 返回 Redis STALE 缓存 (降级)
  5. _save_stale_cache(): 成功响应存档到 Redis (供降级使用)

Redis 键空间:
  - String  quant:yf:stale:{cache_key}  → 最近一次成功响应的 JSON (TTL=24h)

依赖:
  - ServiceRegistry (DIST-01): 节点发现
  - CircuitBreaker (core/circuit_breaker.py): 每节点独立熔断
  - Redis: STALE 缓存存储

设计文档: docs/14 §分布式数据源服务架构
任务编号: DIST-02
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from typing import Any, Dict, List, Optional

import httpx

from backend.core.logger import logger
from backend.core.service_registry import NodeInfo, ServiceRegistry

# ─────────────────────────────────────────
#  常量
# ─────────────────────────────────────────
_NODE_CACHE_TTL = 5.0  # 本地节点缓存刷新间隔 (秒)
_STALE_CACHE_TTL = 86400  # STALE 缓存 TTL (24h)
_STALE_KEY_PREFIX = "quant:yf:stale"
_REQUEST_TIMEOUT = 15.0
_CONNECT_TIMEOUT = 5.0


class YFinanceRouter:
    """
    YFinance 客户端路由器。

    通过 ServiceRegistry 动态发现可用节点，加权轮询选择最优节点，
    失败时自动 failover 到下一节点，所有节点不可用时降级 STALE 缓存。

    用法:
        router = YFinanceRouter(service_registry, redis_client, hmac_secret="...")
        result = await router.call("quote", {"ticker": "AAPL"})
    """

    def __init__(
        self,
        service_registry: ServiceRegistry,
        redis_client,
        hmac_secret: str = "",
        capability: str = "yfinance",
    ):
        self._registry = service_registry
        self._redis = redis_client
        self._hmac_secret = hmac_secret
        self._capability = capability

        # 本地节点缓存
        self._cached_nodes: List[NodeInfo] = []
        self._cache_refreshed_at: float = 0.0

        # 加权轮询计数器
        self._rr_counter: int = 0
        self._rr_lock = asyncio.Lock()

        # HTTP 客户端 (懒初始化)
        self._http_client: Optional[httpx.AsyncClient] = None

        # 每节点连续失败计数 (内存级快速熔断，与 CircuitBreaker 互补)
        self._node_fail_counts: Dict[str, int] = {}
        self._node_circuit_until: Dict[str, float] = {}

    # ─────────────────────────────────────────
    #  节点发现与选择
    # ─────────────────────────────────────────

    async def _refresh_nodes(self) -> List[NodeInfo]:
        """
        从 ServiceRegistry 刷新节点列表。

        5s 本地缓存 + double-check locking，避免每次请求都查 Redis。
        """
        now = time.time()
        if self._cached_nodes and (now - self._cache_refreshed_at) < _NODE_CACHE_TTL:
            return self._cached_nodes

        nodes = await self._registry.discover(capability=self._capability)
        self._cached_nodes = nodes
        self._cache_refreshed_at = now

        logger.debug(f"[YFinanceRouter] 刷新节点: {len(nodes)} 个可用")
        return nodes

    async def _select_nodes(self) -> List[NodeInfo]:
        """
        选择可用节点列表，按加权轮询排序。

        过滤条件:
        1. 节点未处于熔断冷却期
        2. 节点连续失败未达阈值 (< 3 次)

        排序规则:
        1. 按 weight 降序 (高权重优先)
        2. 同权重按轮询计数器偏移 (公平分配)
        """
        nodes = await self._refresh_nodes()
        if not nodes:
            return []

        now = time.time()
        available = []
        for node in nodes:
            # 检查内存级熔断冷却期
            if now < self._node_circuit_until.get(node.node_id, 0):
                continue
            # 检查连续失败次数
            if self._node_fail_counts.get(node.node_id, 0) >= 3:
                continue
            available.append(node)

        if not available:
            return []

        # 加权轮询排序: 按 weight 降序，同权重按轮询偏移
        async with self._rr_lock:
            self._rr_counter += 1
            counter = self._rr_counter

        # 按 weight 降序排序，weight 相同则保持原有顺序
        available.sort(key=lambda n: n.weight, reverse=True)

        # 轮询偏移: 将第一个节点移到列表末尾，实现轮询效果
        if len(available) > 1:
            offset = counter % len(available)
            available = available[offset:] + available[:offset]

        return available

    # ─────────────────────────────────────────
    #  核心调用链路
    # ─────────────────────────────────────────

    async def call(
        self,
        endpoint: str,
        payload: Dict[str, Any],
        cache_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        路由器核心调用入口。

        流程:
        1. 选择可用节点 (加权轮询)
        2. 依次尝试每个节点
        3. 成功 → 存档 STALE 缓存 → 返回
        4. 限流/失败 → 记录失败 → failover 下一节点
        5. 所有节点失败 → 降级 STALE 缓存

        Args:
            endpoint: 远程 API 路径 (如 "yfinance", "quote")
            payload: 请求参数
            cache_key: STALE 缓存键 (如 "quote:AAPL")，不传则不存档/降级
        """
        nodes = await self._select_nodes()
        if not nodes:
            logger.warning("[YFinanceRouter] 无可用节点，降级 STALE 缓存")
            return await self._fallback_stale(cache_key)

        last_error = None
        for node in nodes:
            try:
                result = await self._send_request(node, endpoint, payload)

                # 判断是否成功
                if result.get("status") == "success" or result.get("success"):
                    # 重置失败计数
                    self._node_fail_counts[node.node_id] = 0
                    # 存档 STALE 缓存
                    if cache_key:
                        await self._save_stale_cache(cache_key, result)
                    return result

                # 限流类错误: 不计入熔断，触发 failover
                error_category = result.get("error_category", "normal")
                if error_category != "normal":
                    logger.warning(f"[YFinanceRouter] 节点 {node.node_id} 限流 ({error_category}): endpoint={endpoint}")
                    # 限流不计入熔断失败计数，但记录日志
                    continue

                # 普通错误: 计入失败计数
                self._record_failure(node.node_id)
                last_error = result.get("message", "unknown error")

            except Exception as e:
                logger.warning(f"[YFinanceRouter] 节点 {node.node_id} 异常: {e}")
                self._record_failure(node.node_id)
                last_error = str(e)

        # 所有节点失败，降级 STALE 缓存
        logger.warning(f"[YFinanceRouter] 所有节点失败，降级 STALE 缓存: {last_error}")
        return await self._fallback_stale(cache_key)

    # ─────────────────────────────────────────
    #  HTTP 请求
    # ─────────────────────────────────────────

    def _ensure_http_client(self):
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(_REQUEST_TIMEOUT, connect=_CONNECT_TIMEOUT),
                limits=httpx.Limits(max_connections=20),
            )

    async def _send_request(self, node: NodeInfo, endpoint: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """向指定节点发送 HTTP 请求"""
        self._ensure_http_client()
        url = f"{node.url}/api/v1/data-source/proxy/{endpoint}"
        headers = {"Content-Type": "application/json"}

        # HMAC 签名 (如果配置了密钥)
        if self._hmac_secret:
            timestamp = str(int(time.time()))
            signature = self._sign_request(payload, timestamp)
            headers["X-Data-Source-Signature"] = signature
            headers["X-Data-Source-Timestamp"] = timestamp

        if self._http_client is None:
            return {"status": "error", "message": "HTTP client not initialized"}

        resp = await self._http_client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        return resp.json()

    def _sign_request(self, payload: dict, timestamp: str) -> str:
        """HMAC-SHA256 签名"""
        payload_with_ts = payload.copy()
        payload_with_ts["__timestamp"] = timestamp
        data_str = json.dumps(payload_with_ts, sort_keys=True).encode("utf-8")
        return hashlib.sha256(self._hmac_secret.encode("utf-8") + data_str).hexdigest()

    # ─────────────────────────────────────────
    #  失败记录与熔断
    # ─────────────────────────────────────────

    def _record_failure(self, node_id: str):
        """记录节点失败，连续 3 次触发内存级熔断 (30s 冷却)"""
        count = self._node_fail_counts.get(node_id, 0) + 1
        self._node_fail_counts[node_id] = count

        if count >= 3:
            self._node_circuit_until[node_id] = time.time() + 30.0
            logger.warning(f"[YFinanceRouter] 节点 {node_id} 连续失败 {count} 次，触发内存熔断 (30s 冷却)")

    def _record_success(self, node_id: str):
        """重置节点失败计数"""
        self._node_fail_counts[node_id] = 0

    # ─────────────────────────────────────────
    #  STALE 缓存降级
    # ─────────────────────────────────────────

    async def _save_stale_cache(self, cache_key: str, data: Dict[str, Any]) -> None:
        """将成功响应存档到 Redis，供降级时使用"""
        try:
            redis_key = f"{_STALE_KEY_PREFIX}:{cache_key}"
            await self._redis.set(redis_key, json.dumps(data), ex=_STALE_CACHE_TTL)
        except Exception as e:
            logger.debug(f"[YFinanceRouter] STALE 缓存存档失败: {e}")

    async def _fallback_stale(self, cache_key: Optional[str]) -> Dict[str, Any]:
        """从 Redis STALE 缓存降级返回"""
        if not cache_key:
            return {
                "status": "error",
                "message": "所有节点不可用且无缓存键",
                "degraded": True,
            }

        try:
            redis_key = f"{_STALE_KEY_PREFIX}:{cache_key}"
            cached = await self._redis.get(redis_key)
            if cached:
                data = json.loads(cached)
                # 标记为降级数据
                data["degraded"] = True
                data["stale_source"] = True
                # DIST-20: 记录 STALE 降级指标
                try:
                    from backend.core.metrics import DIST_YF_STALE_TOTAL
                    DIST_YF_STALE_TOTAL.labels(cache_key=cache_key[:64]).inc()
                except Exception:
                    pass
                logger.warning(f"[YFinanceRouter] 降级返回 STALE 缓存: {cache_key}")
                return data
        except Exception as e:
            logger.debug(f"[YFinanceRouter] STALE 缓存读取失败: {e}")

        return {
            "status": "error",
            "message": f"所有节点不可用且无 STALE 缓存: {cache_key}",
            "degraded": True,
        }

    # ─────────────────────────────────────────
    #  状态查询
    # ─────────────────────────────────────────

    async def get_status(self) -> Dict[str, Any]:
        """获取路由器状态 (用于监控)"""
        nodes = await self._refresh_nodes()
        now = time.time()

        node_details = []
        for node in nodes:
            fail_count = self._node_fail_counts.get(node.node_id, 0)
            circuit_until = self._node_circuit_until.get(node.node_id, 0)
            node_details.append(
                {
                    "node_id": node.node_id,
                    "url": node.url,
                    "weight": node.weight,
                    "region": node.region,
                    "fail_count": fail_count,
                    "circuit_remaining": max(0, int(circuit_until - now)),
                    "is_circuit_open": now < circuit_until,
                }
            )

        return {
            "enabled": True,
            "capability": self._capability,
            "total_nodes": len(nodes),
            "available_nodes": len([n for n in node_details if not n["is_circuit_open"]]),
            "nodes": node_details,
        }

    async def close(self):
        """关闭 HTTP 客户端"""
        if self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None
