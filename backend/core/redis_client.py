import os
import asyncio
import time
import redis.asyncio as redis
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

# ==========================================
# 初始化全局 Redis 连接池 (作为数据总线与共享缓存)
# ==========================================
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))

REDIS_PASSWORD = os.getenv("REDIS_PASSWORD")
# 容错拦截：如果 .env 中写了 REDIS_PASSWORD= 导致读到空字符串 ""，将其转为 None
if not REDIS_PASSWORD:
    REDIS_PASSWORD = None
    
redis_client = redis.Redis(
    host=REDIS_HOST, 
    port=REDIS_PORT, 
    password=REDIS_PASSWORD, 
    decode_responses=True,
    protocol=2  # 💡 升级到 redis-py 5.x 后，重新加回此参数以强制使用 RESP2 协议向下兼容
)

# ==========================================
# 💡 高频异步批量写入队列 (Redis Async Batch Writer)
# 解决高频 set 导致的 TCP 网络带宽堵塞与 RTT 延迟问题
# ==========================================
class RedisAsyncBatchWriter:
    def __init__(self, client: redis.Redis, batch_size: int = 100, flush_interval: float = 1.0):
        self.redis = client
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        self.queue = asyncio.Queue()
        self._task = None

    def start(self):
        """启动后台消费协程"""
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._worker())

    async def stop(self):
        """优雅停机，确保积压的数据写入完毕"""
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await self._flush_all()

    def put_set_nowait(self, key: str, value: str, ex: Optional[int] = None):
        """🔥 真正的 Fire-and-Forget 接口，完全不阻塞当前事件循环"""
        self.queue.put_nowait(("set", key, value, ex))

    async def _worker(self):
        batch = []
        while True:
            try:
                # 1. 挂起等待，直到队列有第一个数据或超时发车
                item = await asyncio.wait_for(self.queue.get(), timeout=self.flush_interval)
                batch.append(item)
                self.queue.task_done()
                
                # 2. 一旦有数据，迅速将队列中堆积的其他数据吸干（最多凑齐 batch_size）
                while len(batch) < self.batch_size:
                    try:
                        batch.append(self.queue.get_nowait())
                        self.queue.task_done()
                    except asyncio.QueueEmpty:
                        break
                        
                # 3. 通过 Pipeline 批量发送，节省 N 倍的网络往返时间 (RTT)
                await self._flush_batch(batch)
                batch = []
            except asyncio.TimeoutError:
                continue # 超时说明没数据，继续等
            except asyncio.CancelledError:
                if batch:
                    await self._flush_batch(batch)
                break
            except Exception as e:
                print(f"⚠️ [RedisBatchWriter] 队列消费异常: {e}")

    async def _flush_batch(self, batch):
        if not batch: return
        try:
            async with self.redis.pipeline() as pipe:
                for op in batch:
                    if op[0] == "set":
                        pipe.set(op[1], op[2], ex=op[3])
                await pipe.execute()
        except Exception as e:
            print(f"⚠️ [RedisBatchWriter] Pipeline 批量写入失败: {e}")
            
    async def _flush_all(self):
        batch = []
        while not self.queue.empty():
            batch.append(self.queue.get_nowait())
            self.queue.task_done()
        if batch:
            await self._flush_batch(batch)

# 初始化全局队列写入器
redis_batch_writer = RedisAsyncBatchWriter(redis_client, batch_size=200, flush_interval=0.5)

# ==========================================
# 💡 进程内 L1 本地短效缓存 (Memory L1 Cache)
# 彻底消除极高频读取 (如配置字典、系统开关) 的 Redis TCP 网络开销
# ==========================================
class LocalL1Cache:
    def __init__(self, client: redis.Redis, default_ttl: float = 10.0, max_size: int = 5000):
        self.redis = client
        self.default_ttl = default_ttl
        self.max_size = max_size
        self._cache = {}
        self._cleanup_task = None

    def _ensure_cleanup_task(self):
        """确保后台清理任务在事件循环中运行 (懒加载启动)"""
        if self._cleanup_task is None or self._cleanup_task.done():
            try:
                self._cleanup_task = asyncio.create_task(self._sweep_daemon())
            except RuntimeError:
                pass # 忽略事件循环尚未启动时的调用

    async def _sweep_daemon(self):
        """后台定时安全清理过期数据，彻底杜绝冷门 Key 堆积导致的内存泄漏"""
        while True:
            await asyncio.sleep(60)
            try:
                now = time.time()
                # 必须转为 list 进行迭代，防止在遍历时字典发生修改抛出 RuntimeError
                expired_keys = [k for k, (v, exp) in self._cache.items() if now > exp]
                for k in expired_keys:
                    self._cache.pop(k, None)
            except Exception:
                pass

    async def get(self, key: str):
        self._ensure_cleanup_task()
        now = time.time()
        # 1. 尝试命中本地内存 (0 延迟，0 阻塞)
        if key in self._cache:
            val, exp = self._cache[key]
            if now < exp:
                return val
            else:
                del self._cache[key]  # 惰性清理过期 Key

        # 2. 未命中或已过期，穿透查询远端 Redis (L2 Cache)
        val = await self.redis.get(key)
        
        # 3. 将结果回写至 L1 内存字典
        if val is not None:
            self._cache[key] = (val, now + self.default_ttl)
        return val
        
    async def set(self, key: str, value: str, ex: Optional[int] = None):
        """同步写入远端 Redis (L2) 并立刻更新本地内存 (L1)，保证数据绝对一致"""
        self._ensure_cleanup_task()
        
        # 💡 容量保护机制：如果堆积数量超出上限，直接清空 L1 字典
        # (由于是 L1 缓存，清空是绝对安全的，下一次 get 会自动穿透到 L2 重建)
        if len(self._cache) >= self.max_size:
            self._cache.clear()
            print(f"⚠️ [L1 Cache] 字典容量触及上限 ({self.max_size})，已执行安全熔断清空")
            
        await self.redis.set(key, value, ex=ex)
        now = time.time()
        self._cache[key] = (value, now + self.default_ttl)
        
    def invalidate(self, key: str):
        self._cache.pop(key, None)

# 导出全局 L1 缓存实例 (10秒自动过期)
l1_cached_redis = LocalL1Cache(redis_client, default_ttl=10.0)