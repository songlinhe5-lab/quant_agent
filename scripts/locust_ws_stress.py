"""
Locust WebSocket 压力测试 (TEST-03)
=====================================

目标: /ws/quotes 1000 并发连接，P95 延迟 < 100ms

用法:
  # 安装依赖
  pip install locust websockets

  # 单机模式 (1000 用户, 10 用户/秒 孵化)
  locust -f scripts/locust_ws_stress.py --host ws://localhost:8000

  # 分布式 master
  locust -f scripts/locust_ws_stress.py --host ws://localhost:8000 --master

  # 分布式 worker
  locust -f scripts/locust_ws_stress.py --host ws://localhost:8000 --worker

  # 无头模式 (CI)
  locust -f scripts/locust_ws_stress.py --host ws://localhost:8000 \
         --headless -u 1000 -r 10 -t 60s --csv=locust_report
"""

import asyncio
import json
import time
from typing import Optional

import locust
from locust import HttpUser, User, between, events, task


class WebSocketClient:
    """轻量 WebSocket 客户端，用于 Locust 事件驱动集成。"""

    def __init__(self, host: str):
        self.host = host
        self._ws = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._connected = False

    def connect(self, path: str = "/ws/quotes", token: Optional[str] = None):
        """建立 WebSocket 连接（阻塞）"""
        if self._loop is None:
            self._loop = asyncio.new_event_loop()

        self._loop.run_until_complete(self._connect(path, token))

    async def _connect(self, path: str, token: Optional[str]):
        import websockets

        url = f"{self.host}{path}"
        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"

        start = time.perf_counter()
        try:
            self._ws = await websockets.connect(url, additional_headers=headers)
            self._connected = True
            elapsed_ms = (time.perf_counter() - start) * 1000

            events.request.fire(
                request_type="WS",
                name="connect",
                response_time=elapsed_ms,
                response_length=0,
                exception=None,
            )
        except Exception as e:
            elapsed_ms = (time.perf_counter() - start) * 1000
            events.request.fire(
                request_type="WS",
                name="connect",
                response_time=elapsed_ms,
                response_length=0,
                exception=e,
            )
            raise

    def subscribe(self, symbol: str):
        """发送订阅消息"""
        if not self._connected or not self._ws:
            return
        msg = json.dumps({"type": "subscribe", "topic": "quotes", "symbol": symbol})
        self._loop.run_until_complete(self._send(msg))

    async def _send(self, data: str):
        try:
            await self._ws.send(data)
        except Exception:
            self._connected = False

    def receive(self, timeout: float = 5.0) -> Optional[dict]:
        """接收一条消息（阻塞）"""
        if not self._connected or not self._ws:
            return None
        try:
            return self._loop.run_until_complete(self._receive(timeout))
        except Exception:
            self._connected = False
            return None

    async def _receive(self, timeout: float):
        try:
            data = await asyncio.wait_for(self._ws.recv(), timeout=timeout)
            return json.loads(data)
        except asyncio.TimeoutError:
            return None

    def close(self):
        """关闭连接"""
        if self._ws and self._loop:
            self._loop.run_until_complete(self._ws.close())
            self._connected = False


class QuotesWebSocketUser(User):
    """
    模拟 WebSocket 行情订阅用户。

    行为:
      1. 连接 /ws/quotes
      2. 订阅 1~3 个热门标的
      3. 持续接收行情消息，记录延迟
      4. 60s 后断开重连（模拟真实用户行为）
    """

    abstract = True  # 基类，不直接运行
    wait_time = between(0.1, 0.5)

    # 热门标的池
    SYMBOLS = [
        "AAPL", "MSFT", "GOOGL", "AMZN", "TSLA",
        "NVDA", "META", "BABA", "00700", "09988",
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ws_client: Optional[WebSocketClient] = None
        self._msg_count = 0
        self._session_start = 0

    def on_start(self):
        """连接 + 订阅"""
        self._session_start = time.time()
        self.ws_client = WebSocketClient(self.host)
        try:
            self.ws_client.connect("/ws/quotes")
        except Exception:
            return

        # 随机订阅 1~3 个标的
        import random
        n_subs = random.randint(1, 3)
        for sym in random.sample(self.SYMBOLS, min(n_subs, len(self.SYMBOLS))):
            self.ws_client.subscribe(sym)

    def on_stop(self):
        """断开连接"""
        if self.ws_client:
            self.ws_client.close()

    @task
    def receive_quotes(self):
        """接收行情消息并记录延迟"""
        if not self.ws_client or not self.ws_client._connected:
            return

        start = time.perf_counter()
        msg = self.ws_client.receive(timeout=2.0)
        elapsed_ms = (time.perf_counter() - start) * 1000

        if msg is not None:
            self._msg_count += 1
            events.request.fire(
                request_type="WS",
                name="receive_quote",
                response_time=elapsed_ms,
                response_length=len(json.dumps(msg)),
                exception=None,
            )
        else:
            # 超时不算失败，只是没有新数据
            pass

        # 模拟 60s 后重连
        if time.time() - self._session_start > 60:
            self.ws_client.close()
            try:
                self.ws_client.connect("/ws/quotes")
                import random
                for sym in random.sample(self.SYMBOLS, random.randint(1, 3)):
                    self.ws_client.subscribe(sym)
                self._session_start = time.time()
            except Exception:
                pass


class RestApiUser(HttpUser):
    """
    REST API 压力测试用户。

    测试核心 HTTP 端点的吞吐量和延迟。
    """

    abstract = True
    wait_time = between(0.5, 2.0)

    @task(3)
    def get_health(self):
        """GET /api/v1/health"""
        with self.client.get("/api/v1/health", catch_response=True) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"Health check failed: {resp.status_code}")

    @task(5)
    def get_quote(self):
        """GET /api/v1/market/quote?symbol=AAPL"""
        import random
        symbol = random.choice(QuotesWebSocketUser.SYMBOLS)
        with self.client.get(
            f"/api/v1/market/quote",
            params={"symbol": symbol},
            catch_response=True,
        ) as resp:
            if resp.status_code in (200, 404):
                resp.success()
            else:
                resp.failure(f"Quote failed: {resp.status_code}")

    @task(2)
    def get_kline(self):
        """GET /api/v1/market/kline?symbol=AAPL&period=K_DAY&count=100"""
        import random
        symbol = random.choice(QuotesWebSocketUser.SYMBOLS)
        with self.client.get(
            f"/api/v1/market/kline",
            params={"symbol": symbol, "period": "K_DAY", "count": 100},
            catch_response=True,
        ) as resp:
            if resp.status_code in (200, 404):
                resp.success()
            else:
                resp.failure(f"Kline failed: {resp.status_code}")

    @task(1)
    def get_screener(self):
        """POST /api/v1/screener/screen"""
        with self.client.post(
            "/api/v1/screener/screen",
            json={"market": ["US"], "max_pe": 30, "min_volume": 1000000},
            catch_response=True,
        ) as resp:
            if resp.status_code in (200, 422):
                resp.success()
            else:
                resp.failure(f"Screener failed: {resp.status_code}")
