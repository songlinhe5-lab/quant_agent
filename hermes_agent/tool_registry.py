import traceback
import asyncio
import inspect
import time
from typing import Any, Dict, List, Optional

from hermes_agent.tool_result_cache import ToolResultCache, default_tool_result_cache


class AsyncTokenBucket:
    """异步令牌桶限流器"""

    def __init__(self, capacity: int, fill_rate: float):
        self.capacity = capacity
        self.tokens = float(capacity)
        self.fill_rate = fill_rate
        self.last_update = time.monotonic()
        self.lock = asyncio.Lock()

    async def acquire(self):
        async with self.lock:
            while True:
                now = time.monotonic()
                elapsed = now - self.last_update
                self.tokens = min(self.capacity, self.tokens + elapsed * self.fill_rate)
                self.last_update = now

                if self.tokens >= 1:
                    self.tokens -= 1
                    return
                wait_time = (1 - self.tokens) / self.fill_rate
                await asyncio.sleep(wait_time)


_AUTO_REGISTERED_TOOLS = []


def register_tool(cls):
    """
    类装饰器：自动将 Tool 类加入全局注册列表。
    带有此装饰器的类，在 ToolRegistry 初始化时会被自动实例化并注册。
    """
    if cls not in _AUTO_REGISTERED_TOOLS:
        _AUTO_REGISTERED_TOOLS.append(cls)
    return cls


# 💡 必须在 register_tool 定义之后导入 tools，触发 @register_tool
import hermes_agent.tools  # noqa: E402, F401


class ToolRegistry:
    """
    工具注册表：注册、Schema 转换与安全执行。
    BE-12：execute() 统一走 ToolResultCache（Redis Hash）。
    """

    def __init__(self, result_cache: Optional[ToolResultCache] = None):
        self.tools = {}
        self.result_cache = (
            result_cache if result_cache is not None else default_tool_result_cache
        )
        self.rate_limiter = AsyncTokenBucket(capacity=3, fill_rate=1.0)

        for tool_cls in _AUTO_REGISTERED_TOOLS:
            self.register(tool_cls())

    def register(self, tool):
        if not hasattr(tool, "name") or not hasattr(tool, "description"):
            raise ValueError(
                f"⚠️ 工具 {tool.__class__.__name__} 缺失 name 或 description 属性"
            )

        self.tools[tool.name] = tool
        print(f"✅ Tool 注册成功: {tool.name} - {tool.description}")

    def get_all_schemas(self) -> List[Dict[str, Any]]:
        schemas = []
        for name, tool in self.tools.items():
            schemas.append(
                {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": tool.description,
                        "parameters": getattr(
                            tool, "parameters", {"type": "object", "properties": {}}
                        ),
                    },
                }
            )
        return schemas

    async def execute(self, name: str, **kwargs) -> Any:
        """
        执行工具；捕获异常防 Agent 宕机。
        BE-12：先查 Redis Hash 缓存，命中则跳过外部 API。
        """
        if name not in self.tools:
            return {"status": "error", "message": f"未找到名为 '{name}' 的工具。"}

        try:
            cached = await self.result_cache.get(name, kwargs)
            if cached is not None:
                print(f"⚡ [Tool Cache HIT] {name}")
                return cached

            await self.rate_limiter.acquire()

            print(f"🔧 [Tool Executor] 正在调用 {name} | 参数: {kwargs}")
            tool = self.tools[name]
            if inspect.iscoroutinefunction(tool.run):
                result = await tool.run(**kwargs)
            else:
                result = await asyncio.to_thread(tool.run, **kwargs)

            await self.result_cache.set(name, kwargs, result)
            return result
        except Exception as e:
            error_msg = f"工具执行异常: {str(e)}\n{traceback.format_exc()}"
            print(f"❌ [Tool Executor Error] {error_msg}")
            return {"status": "error", "message": f"执行失败: {str(e)}"}
