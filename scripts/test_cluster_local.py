#!/usr/bin/env python3
"""
本地集群通信验证脚本 (无需 Docker)

验证流程:
1. 清理 Redis 中的旧集群数据
2. 模拟 slave 心跳注册到 Redis
3. 验证 ClusterManager 从 Redis 发现 slave 节点
4. 模拟 Master 调用 slave /collect 端点
5. 验证 callback_redis 写入

用法:
  python scripts/test_cluster_local.py
"""

import asyncio
import json
import os
import sys
import time

import redis.asyncio as aioredis

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# 从 .env 加载
from dotenv import load_dotenv

load_dotenv()

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD")

PASS = 0
FAIL = 0


def log_pass(msg):
    global PASS
    PASS += 1
    print(f"  \033[92m[PASS]\033[0m {msg}")


def log_fail(msg):
    global FAIL
    FAIL += 1
    print(f"  \033[91m[FAIL]\033[0m {msg}")


def log_info(msg):
    print(f"  \033[93m[INFO]\033[0m {msg}")


async def main():
    print("\n" + "=" * 50)
    print("  本地集群通信验证 (无 Docker)")
    print("=" * 50 + "\n")

    # 连接 Redis
    r = aioredis.Redis(
        host=REDIS_HOST, port=REDIS_PORT, password=REDIS_PASSWORD, decode_responses=True
    )
    try:
        await r.ping()
        log_pass("Redis 连接成功")
    except Exception as e:
        log_fail(f"Redis 连接失败: {e}")
        return

    # ==========================================
    # Step 1: 清理旧数据
    # ==========================================
    log_info("Step 1: 清理 Redis 集群数据...")
    cursor = 0
    cleaned = 0
    while True:
        cursor, keys = await r.scan(cursor=cursor, match="quant:node:*", count=50)
        for key in keys:
            await r.delete(key)
            cleaned += 1
        if cursor == 0:
            break
    cursor = 0
    while True:
        cursor, keys = await r.scan(cursor=cursor, match="quant:cache:*", count=50)
        for key in keys:
            await r.delete(key)
            cleaned += 1
        if cursor == 0:
            break
    log_info(f"  清理了 {cleaned} 个旧 key")

    # ==========================================
    # Step 2: 模拟 slave 心跳注册
    # ==========================================
    log_info("Step 2: 模拟 slave 心跳注册到 Redis...")
    node_info = {
        "uuid": "test-uuid-001",
        "node_id": "test-slave-1",
        "role": "slave",
        "host": "localhost",
        "port": 8001,
        "collectors": ["yfinance", "finnhub"],
        "started_at": time.time(),
        "status": "healthy",
    }
    await r.set("quant:node:test-slave-1", json.dumps(node_info), ex=15)
    log_pass("slave 心跳已写入 Redis (quant:node:test-slave-1)")

    # 验证写入
    raw = await r.get("quant:node:test-slave-1")
    assert raw is not None
    data = json.loads(raw)
    assert data["node_id"] == "test-slave-1"
    assert data["role"] == "slave"
    assert "yfinance" in data["collectors"]
    log_pass("心跳数据验证: node_id=test-slave-1, role=slave, collectors=[yfinance, finnhub]")

    # ==========================================
    # Step 3: ClusterManager 发现 slave
    # ==========================================
    log_info("Step 3: 验证 ClusterManager 从 Redis 发现 slave...")
    from backend.workers.cluster_manager import ClusterManager

    cm = ClusterManager()
    # 模拟 _callback_redis
    cm._callback_redis = {"host": REDIS_HOST, "port": REDIS_PORT, "password": REDIS_PASSWORD}

    # 直接调用 _refresh_from_redis
    # 需要 mock redis_client 模块级导入
    import backend.core.redis_client as redis_module

    original_client = redis_module.redis_client
    redis_module.redis_client = r

    try:
        await cm._refresh_from_redis()
    finally:
        redis_module.redis_client = original_client

    # 验证发现
    assert "test-slave-1" in cm._nodes, f"未发现 slave! nodes={list(cm._nodes.keys())}"
    log_pass("ClusterManager 发现 test-slave-1 节点")

    node = cm._nodes["test-slave-1"]
    assert node.host == "localhost"
    assert node.port == 8001
    assert "yfinance" in node.collectors
    log_pass(f"节点属性正确: host={node.host}, port={node.port}, collectors={node.collectors}")

    # 验证服务池
    assert "yfinance" in cm._pools
    assert "test-slave-1" in cm._pools["yfinance"]
    assert "finnhub" in cm._pools
    log_pass(f"服务池构建成功: pools={dict(cm._pools)}")

    # 验证集群状态
    status = cm.get_cluster_status()
    assert len(status["slaves"]) == 1
    assert status["slaves"][0]["node_id"] == "test-slave-1"
    log_pass(f"集群状态查询成功: {len(status['slaves'])} slave(s)")

    # ==========================================
    # Step 4: 验证 payload 格式
    # ==========================================
    log_info("Step 4: 验证 _call_node payload 格式...")
    import httpx

    captured_payload = None

    class MockResponse:
        status_code = 200

        def json(self):
            return {"code": 0, "data": {"price": 150.0}}

        def raise_for_status(self):
            pass

    class MockClient:
        async def post(self, url, json=None):
            nonlocal captured_payload
            captured_payload = json
            return MockResponse()

    cm._http_client = MockClient()

    result = await cm.call_collector("yfinance", "fetch_quote", {"ticker": "AAPL", "period": "3mo"})

    assert captured_payload is not None
    assert captured_payload["ticker"] == "AAPL"
    assert captured_payload["params"]["period"] == "3mo"
    assert "callback_redis" in captured_payload
    assert "ticker" not in captured_payload["params"]
    log_pass("payload 格式正确: ticker 在顶层, params 嵌套, callback_redis 携带")

    # ==========================================
    # Step 5: 验证本地降级
    # ==========================================
    log_info("Step 5: 验证本地降级回退...")

    # 创建一个没有从节点的 ClusterManager
    cm2 = ClusterManager()
    cm2._callback_redis = {"host": REDIS_HOST, "port": REDIS_PORT, "password": REDIS_PASSWORD}
    cm2._http_client = MockClient()

    # mock 本地采集器
    from unittest.mock import AsyncMock, patch

    mock_dispatch = AsyncMock(return_value={"price": 200.0})
    with patch("backend.workers.collector_registry.get_enabled_collectors", return_value=["yfinance"]):
        with patch("backend.slave_app._dispatch_collect", mock_dispatch):
            result = await cm2.call_collector("yfinance", "fetch_quote", {"ticker": "AAPL"})

    assert result["data"]["price"] == 200.0
    assert result["source_node"] == "local"
    log_pass("本地降级成功: 无从节点时自动回退到本地采集器")

    # ==========================================
    # Step 6: 验证 CollectRequest 兼容性
    # ==========================================
    log_info("Step 6: 验证 CollectRequest 新旧格式兼容...")
    from backend.slave_app import CollectRequest

    # 新格式
    req_new = CollectRequest(ticker="AAPL", params={"period": "3mo"})
    assert req_new.ticker == "AAPL"
    assert req_new.params == {"period": "3mo"}
    log_pass("新格式解析正确: ticker + params")

    # 旧格式 (平铺参数)
    req_old = CollectRequest.model_validate(
        {"ticker": "AAPL", "period": "3mo", "interval": "1d"}
    )
    assert req_old.ticker == "AAPL"
    assert req_old.params is None
    assert req_old.model_extra.get("period") == "3mo"
    assert req_old.model_extra.get("interval") == "1d"
    log_pass("旧格式解析正确: 额外字段通过 model_extra 访问")

    # ==========================================
    # Step 7: 清理
    # ==========================================
    log_info("Step 7: 清理测试数据...")
    await r.delete("quant:node:test-slave-1")
    await r.aclose()
    log_pass("测试数据已清理")

    # ==========================================
    # 结果汇总
    # ==========================================
    print(f"\n{'=' * 50}")
    print(f"  验证结果: \033[92m{PASS} passed\033[0m, \033[91m{FAIL} failed\033[0m")
    print(f"{'=' * 50}\n")

    if FAIL > 0:
        sys.exit(1)
    print("全部验证通过!")


if __name__ == "__main__":
    asyncio.run(main())
