"""
ServiceRegistry — 分布式节点服务注册表
==========================================

基于 Redis Hash + Sorted Set + Set 三结构协同，实现跨 VPS 节点的服务注册与发现。

（复制自 backend.core.service_registry，物理解耦到 data_subservice._internal，
 仅改 logger 为相对 import，不再依赖 backend 包。）

Redis 键空间设计:
  - Hash   quant:registry:nodes          → {node_id: NodeInfo JSON}
  - ZSet   quant:registry:heartbeats     → {node_id: last_heartbeat_ts}  (按心跳时间排序)
  - Set    quant:registry:draining       → {node_id, ...}                (优雅下线中的节点)
  - Hash   quant:registry:stats:{node_id} → {success_count, error_count, avg_latency_ms, ...}
"""

from __future__ import annotations

import json
import time
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from data_subservice._internal.logger import logger

# ─────────────────────────────────────────
#  Redis 键前缀
# ─────────────────────────────────────────
_KEY_NODES = "quant:registry:nodes"
_KEY_HEARTBEATS = "quant:registry:heartbeats"
_KEY_DRAINING = "quant:registry:draining"
_KEY_STATS_PREFIX = "quant:registry:stats"

# ─────────────────────────────────────────
#  默认配置
# ─────────────────────────────────────────
DEFAULT_HEARTBEAT_TTL = 30  # 心跳超时秒数（超过此时间未心跳视为 dead）
DEFAULT_NODE_WEIGHT = 10


class NodeStatus(str, Enum):
    """节点状态"""

    ACTIVE = "active"
    DRAINING = "draining"
    DEAD = "dead"


class NodeInfo(BaseModel):
    """节点信息模型"""

    node_id: str = Field(..., description="节点唯一标识 (如 ca-primary, beijing-aux)")
    url: str = Field(..., description="节点 API 地址 (如 http://38.60.126.42:8000)")
    region: str = Field(default="us-west", description="地理区域 (us-west / cn-north)")
    weight: int = Field(default=DEFAULT_NODE_WEIGHT, ge=1, le=100, description="路由权重 (1-100)")
    capabilities: List[str] = Field(default_factory=list, description="支持的数据源能力列表")
    status: NodeStatus = Field(default=NodeStatus.ACTIVE, description="节点状态")
    last_heartbeat: float = Field(default_factory=time.time, description="最后心跳时间戳")
    registered_at: float = Field(default_factory=time.time, description="首次注册时间戳")
    metadata: Dict[str, str] = Field(default_factory=dict, description="扩展元数据")

    def is_alive(self, ttl: int = DEFAULT_HEARTBEAT_TTL) -> bool:
        """判断节点是否在 TTL 内有心跳"""
        return (time.time() - self.last_heartbeat) < ttl


class ServiceRegistry:
    """
    分布式节点服务注册表。

    所有操作均为异步 (async)，依赖 Redis 作为共享状态存储。
    线程安全由 Redis 原子操作保证。

    用法:
        registry = ServiceRegistry(redis_client)
        await registry.register(node_info)
        await registry.heartbeat("ca-primary")
        nodes = await registry.discover(capability="yfinance")
        await registry.deregister("beijing-aux")
    """

    def __init__(self, redis_client, heartbeat_ttl: int = DEFAULT_HEARTBEAT_TTL):
        self._redis = redis_client
        self._heartbeat_ttl = heartbeat_ttl

    # ─────────────────────────────────────────
    #  注册 / 注销
    # ─────────────────────────────────────────
    async def register(self, node: NodeInfo) -> bool:
        now = time.time()
        node.last_heartbeat = now
        node.registered_at = now

        try:
            async with self._redis.pipeline() as pipe:
                pipe.hset(_KEY_NODES, node.node_id, node.model_dump_json())
                pipe.zadd(_KEY_HEARTBEATS, {node.node_id: now})
                await pipe.execute()

            logger.info(
                f"[ServiceRegistry] 节点注册成功: {node.node_id} "
                f"url={node.url} region={node.region} capabilities={node.capabilities}"
            )
            return True
        except Exception as e:
            logger.error(f"[ServiceRegistry] 注册失败: {node.node_id}, error={e}")
            return False

    async def deregister(self, node_id: str) -> bool:
        try:
            async with self._redis.pipeline() as pipe:
                pipe.hdel(_KEY_NODES, node_id)
                pipe.zrem(_KEY_HEARTBEATS, node_id)
                pipe.srem(_KEY_DRAINING, node_id)
                pipe.delete(f"{_KEY_STATS_PREFIX}:{node_id}")
                await pipe.execute()

            logger.info(f"[ServiceRegistry] 节点注销成功: {node_id}")
            return True
        except Exception as e:
            logger.error(f"[ServiceRegistry] 注销失败: {node_id}, error={e}")
            return False

    # ─────────────────────────────────────────
    #  心跳
    # ─────────────────────────────────────────
    async def heartbeat(self, node_id: str, metrics: Optional[Dict[str, float]] = None) -> bool:
        now = time.time()

        try:
            node_json = await self._redis.hget(_KEY_NODES, node_id)
            if node_json is None:
                logger.warning(f"[ServiceRegistry] 心跳失败: 节点 {node_id} 未注册")
                return False

            node_data = json.loads(node_json)
            node_data["last_heartbeat"] = now

            async with self._redis.pipeline() as pipe:
                pipe.zadd(_KEY_HEARTBEATS, {node_id: now})
                pipe.hset(_KEY_NODES, node_id, json.dumps(node_data))
                await pipe.execute()

            if metrics:
                await self._update_stats(node_id, metrics)

            return True
        except Exception as e:
            logger.error(f"[ServiceRegistry] 心跳更新失败: {node_id}, error={e}")
            return False

    # ─────────────────────────────────────────
    #  发现 / 查询
    # ─────────────────────────────────────────
    async def discover(
        self,
        capability: Optional[str] = None,
        region: Optional[str] = None,
        include_draining: bool = False,
    ) -> List[NodeInfo]:
        all_nodes = await self.get_all_nodes()

        result = []
        for node in all_nodes:
            if not node.is_alive(self._heartbeat_ttl):
                continue
            if not include_draining and node.status == NodeStatus.DRAINING:
                continue
            if capability and capability not in node.capabilities:
                continue
            if region and node.region != region:
                continue
            result.append(node)

        result.sort(key=lambda n: n.weight, reverse=True)
        return result

    async def get_node(self, node_id: str) -> Optional[NodeInfo]:
        try:
            node_json = await self._redis.hget(_KEY_NODES, node_id)
            if node_json is None:
                return None
            return NodeInfo.model_validate_json(node_json)
        except Exception as e:
            logger.error(f"[ServiceRegistry] 获取节点失败: {node_id}, error={e}")
            return None

    async def get_all_nodes(self) -> List[NodeInfo]:
        try:
            all_data = await self._redis.hgetall(_KEY_NODES)
            nodes = []
            for node_id, node_json in all_data.items():
                try:
                    node = NodeInfo.model_validate_json(node_json)
                    is_draining = await self._redis.sismember(_KEY_DRAINING, node_id)
                    if is_draining:
                        node.status = NodeStatus.DRAINING
                    elif not node.is_alive(self._heartbeat_ttl):
                        node.status = NodeStatus.DEAD
                    nodes.append(node)
                except Exception as e:
                    logger.warning(f"[ServiceRegistry] 解析节点 {node_id} 失败: {e}")
            return nodes
        except Exception as e:
            logger.error(f"[ServiceRegistry] 获取所有节点失败: error={e}")
            return []

    # ─────────────────────────────────────────
    #  优雅下线 (Draining)
    # ─────────────────────────────────────────
    async def mark_draining(self, node_id: str) -> bool:
        try:
            node_json = await self._redis.hget(_KEY_NODES, node_id)

            async with self._redis.pipeline() as pipe:
                pipe.sadd(_KEY_DRAINING, node_id)
                if node_json:
                    node_data = json.loads(node_json)
                    node_data["status"] = NodeStatus.DRAINING.value
                    pipe.hset(_KEY_NODES, node_id, json.dumps(node_data))
                await pipe.execute()

            logger.info(f"[ServiceRegistry] 节点标记为 draining: {node_id}")
            return True
        except Exception as e:
            logger.error(f"[ServiceRegistry] mark_draining 失败: {node_id}, error={e}")
            return False

    async def unmark_draining(self, node_id: str) -> bool:
        try:
            node_json = await self._redis.hget(_KEY_NODES, node_id)

            async with self._redis.pipeline() as pipe:
                pipe.srem(_KEY_DRAINING, node_id)
                if node_json:
                    node_data = json.loads(node_json)
                    node_data["status"] = NodeStatus.ACTIVE.value
                    pipe.hset(_KEY_NODES, node_id, json.dumps(node_data))
                await pipe.execute()

            logger.info(f"[ServiceRegistry] 节点取消 draining: {node_id}")
            return True
        except Exception as e:
            logger.error(f"[ServiceRegistry] unmark_draining 失败: {node_id}, error={e}")
            return False

    # ─────────────────────────────────────────
    #  死节点清理
    # ─────────────────────────────────────────
    async def cleanup_dead_nodes(self) -> List[str]:
        now = time.time()
        cutoff = now - self._heartbeat_ttl

        try:
            dead_ids = await self._redis.zrangebyscore(_KEY_HEARTBEATS, "-inf", cutoff)
            if not dead_ids:
                return []

            async with self._redis.pipeline() as pipe:
                for node_id in dead_ids:
                    pipe.hdel(_KEY_NODES, node_id)
                    pipe.zrem(_KEY_HEARTBEATS, node_id)
                    pipe.srem(_KEY_DRAINING, node_id)
                    pipe.delete(f"{_KEY_STATS_PREFIX}:{node_id}")
                await pipe.execute()

            logger.warning(f"[ServiceRegistry] 清理 {len(dead_ids)} 个死节点: {dead_ids}")
            return dead_ids
        except Exception as e:
            logger.error(f"[ServiceRegistry] 清理死节点失败: error={e}")
            return []

    # ─────────────────────────────────────────
    #  统计指标
    # ─────────────────────────────────────────
    async def _update_stats(self, node_id: str, metrics: Dict[str, float]) -> None:
        try:
            stats_key = f"{_KEY_STATS_PREFIX}:{node_id}"
            async with self._redis.pipeline() as pipe:
                for key, value in metrics.items():
                    pipe.hincrbyfloat(stats_key, key, value)
                pipe.expire(stats_key, 3600)
                await pipe.execute()
        except Exception as e:
            logger.debug(f"[ServiceRegistry] 更新统计失败: {node_id}, error={e}")

    async def get_stats(self, node_id: str) -> Dict[str, float]:
        try:
            stats_key = f"{_KEY_STATS_PREFIX}:{node_id}"
            raw = await self._redis.hgetall(stats_key)
            return {k: float(v) for k, v in raw.items()} if raw else {}
        except Exception as e:
            logger.debug(f"[ServiceRegistry] 获取统计失败: {node_id}, error={e}")
            return {}

    # ─────────────────────────────────────────
    #  集群总览
    # ─────────────────────────────────────────
    async def get_cluster_overview(self) -> Dict:
        all_nodes = await self.get_all_nodes()

        active = [n for n in all_nodes if n.status == NodeStatus.ACTIVE]
        draining = [n for n in all_nodes if n.status == NodeStatus.DRAINING]
        dead = [n for n in all_nodes if n.status == NodeStatus.DEAD]

        regions: Dict[str, int] = {}
        for n in active:
            regions[n.region] = regions.get(n.region, 0) + 1

        return {
            "total_nodes": len(all_nodes),
            "active_nodes": len(active),
            "draining_nodes": len(draining),
            "dead_nodes": len(dead),
            "nodes": [n.model_dump() for n in all_nodes],
            "regions": regions,
        }
