"""
ServiceRegistry — 分布式节点服务注册表
==========================================

基于 Redis Hash + Sorted Set + Set 三结构协同，实现跨 VPS 节点的服务注册与发现。

Redis 键空间设计:
  - Hash   quant:registry:nodes          → {node_id: NodeInfo JSON}
  - ZSet   quant:registry:heartbeats     → {node_id: last_heartbeat_ts}  (按心跳时间排序)
  - Set    quant:registry:draining       → {node_id, ...}                (优雅下线中的节点)
  - Hash   quant:registry:stats:{node_id} → {success_count, error_count, avg_latency_ms, ...}

设计文档: docs/14 §分布式数据源服务架构
任务编号: DIST-01
"""

from __future__ import annotations

import json
import time
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from backend.core.logger import logger

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
        """
        注册节点到 Redis。

        写入 Hash (节点信息) + ZSet (心跳时间戳)。
        如果节点已存在则覆盖更新。

        Returns:
            True 注册成功, False Redis 异常
        """
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
        """
        注销节点，移除所有注册信息。

        清理 Hash + ZSet + Set + Stats。
        """
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
        """
        更新节点心跳时间戳。

        同时更新 ZSet 中的 score 和 Hash 中的 last_heartbeat 字段。
        可选传入 metrics 更新统计信息。

        Returns:
            True 心跳更新成功, False 节点不存在或 Redis 异常
        """
        now = time.time()

        try:
            # 检查节点是否存在
            node_json = await self._redis.hget(_KEY_NODES, node_id)
            if node_json is None:
                logger.warning(f"[ServiceRegistry] 心跳失败: 节点 {node_id} 未注册")
                return False

            # 更新心跳时间 + Hash 中的 last_heartbeat
            node_data = json.loads(node_json)
            node_data["last_heartbeat"] = now

            async with self._redis.pipeline() as pipe:
                pipe.zadd(_KEY_HEARTBEATS, {node_id: now})
                pipe.hset(_KEY_NODES, node_id, json.dumps(node_data))
                await pipe.execute()

            # draining 节点发心跳保持 draining 状态，无需额外操作

            # 更新统计指标 (如果有)
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
        """
        发现可用节点。

        Args:
            capability: 按能力过滤 (如 "yfinance", "akshare")
            region: 按区域过滤 (如 "us-west", "cn-north")
            include_draining: 是否包含 draining 状态的节点

        Returns:
            符合条件的活跃节点列表 (已排除 dead 节点)
        """
        all_nodes = await self.get_all_nodes()
        now = time.time()

        result = []
        for node in all_nodes:
            # 排除 dead 节点 (心跳超时)
            if not node.is_alive(self._heartbeat_ttl):
                continue

            # 排除 draining 节点 (除非明确要求)
            if not include_draining and node.status == NodeStatus.DRAINING:
                continue

            # 按能力过滤
            if capability and capability not in node.capabilities:
                continue

            # 按区域过滤
            if region and node.region != region:
                continue

            result.append(node)

        # 按权重降序排序
        result.sort(key=lambda n: n.weight, reverse=True)
        return result

    async def get_node(self, node_id: str) -> Optional[NodeInfo]:
        """获取单个节点信息"""
        try:
            node_json = await self._redis.hget(_KEY_NODES, node_id)
            if node_json is None:
                return None
            return NodeInfo.model_validate_json(node_json)
        except Exception as e:
            logger.error(f"[ServiceRegistry] 获取节点失败: {node_id}, error={e}")
            return None

    async def get_all_nodes(self) -> List[NodeInfo]:
        """获取所有已注册节点 (包括 dead)"""
        try:
            all_data = await self._redis.hgetall(_KEY_NODES)
            nodes = []
            for node_id, node_json in all_data.items():
                try:
                    node = NodeInfo.model_validate_json(node_json)
                    # 同步 draining 状态
                    is_draining = await self._redis.sismember(_KEY_DRAINING, node_id)
                    if is_draining:
                        node.status = NodeStatus.DRAINING
                    # 标记 dead 状态
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
        """
        将节点标记为 draining (优雅下线中)。

        Draining 节点:
        - 仍然有心跳，不会被 cleanup 清除
        - discover() 默认不返回，除非 include_draining=True
        - 用于通知路由器停止向该节点发送新请求
        """
        try:
            # 先读取节点数据
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
        """取消 draining 标记，恢复为 active"""
        try:
            # 先读取节点数据
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
        """
        清理心跳超时的死节点。

        通过 ZSet score 范围查询找到超时节点，批量移除。
        建议由后台守护任务定期调用 (每 30s)。

        Returns:
            被清理的节点 ID 列表
        """
        now = time.time()
        cutoff = now - self._heartbeat_ttl

        try:
            # 找到所有心跳超时的节点
            dead_ids = await self._redis.zrangebyscore(
                _KEY_HEARTBEATS, "-inf", cutoff
            )

            if not dead_ids:
                return []

            # 批量清理
            async with self._redis.pipeline() as pipe:
                for node_id in dead_ids:
                    pipe.hdel(_KEY_NODES, node_id)
                    pipe.zrem(_KEY_HEARTBEATS, node_id)
                    pipe.srem(_KEY_DRAINING, node_id)
                    pipe.delete(f"{_KEY_STATS_PREFIX}:{node_id}")
                await pipe.execute()

            logger.warning(
                f"[ServiceRegistry] 清理 {len(dead_ids)} 个死节点: {dead_ids}"
            )
            return dead_ids
        except Exception as e:
            logger.error(f"[ServiceRegistry] 清理死节点失败: error={e}")
            return []

    # ─────────────────────────────────────────
    #  统计指标
    # ─────────────────────────────────────────

    async def _update_stats(self, node_id: str, metrics: Dict[str, float]) -> None:
        """更新节点统计指标 (原子递增)"""
        try:
            stats_key = f"{_KEY_STATS_PREFIX}:{node_id}"
            async with self._redis.pipeline() as pipe:
                for key, value in metrics.items():
                    pipe.hincrbyfloat(stats_key, key, value)
                pipe.expire(stats_key, 3600)  # 1h TTL
                await pipe.execute()
        except Exception as e:
            logger.debug(f"[ServiceRegistry] 更新统计失败: {node_id}, error={e}")

    async def get_stats(self, node_id: str) -> Dict[str, float]:
        """获取节点统计指标"""
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
        """
        获取集群总览信息。

        Returns:
            {
                "total_nodes": int,
                "active_nodes": int,
                "draining_nodes": int,
                "dead_nodes": int,
                "nodes": [NodeInfo, ...],
                "regions": {"us-west": count, "cn-north": count},
            }
        """
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
