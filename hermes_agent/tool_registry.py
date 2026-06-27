import traceback
import asyncio
import inspect
import time
import importlib
import pkgutil
import os
import sys
from typing import Dict, Any, List

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
                # 如果令牌不足，计算需要等待的时间后休眠释放控制权
                wait_time = (1 - self.tokens) / self.fill_rate
                await asyncio.sleep(wait_time)

# 全局工具类收集列表
_AUTO_REGISTERED_TOOLS = []

def register_tool(cls):
    """
    类装饰器：自动将 Tool 类加入全局注册列表。
    带有此装饰器的类，在 ToolRegistry 初始化时会被自动实例化并注册。
    """
    if cls not in _AUTO_REGISTERED_TOOLS:
        _AUTO_REGISTERED_TOOLS.append(cls)
    return cls

# 💡 核心修复：将导入内部 tools 包的代码移至 register_tool 定义之后。
# 这会执行 hermes_agent/tools/__init__.py，从而完美避开循环导入问题。
import hermes_agent.tools

class ToolRegistry:
    """
    工具注册表，用于管理 Agent 可用的 Tools
    职责：工具的注册、Schema 转换（适配大模型）与安全执行沙箱。
    """
    def __init__(self):
        self.tools = {}
        # 全局限流器：最大突发并发容量为 3，每秒恢复 1 个令牌（即限制最高 1 QPS，但允许开局瞬发 3 个）
        self.rate_limiter = AsyncTokenBucket(capacity=3, fill_rate=1.0)
        
        # 自动实例化并注册所有被 @register_tool 装饰的工具类
        for tool_cls in _AUTO_REGISTERED_TOOLS:
            self.register(tool_cls())

    def register(self, tool):
        # 校验 Tool 是否符合基础规范
        if not hasattr(tool, 'name') or not hasattr(tool, 'description'):
            raise ValueError(f"⚠️ 工具 {tool.__class__.__name__} 缺失 name 或 description 属性")
            
        self.tools[tool.name] = tool
        print(f"✅ Tool 注册成功: {tool.name} - {tool.description}")

    def get_all_schemas(self) -> List[Dict[str, Any]]:
        """
        获取所有已注册工具的 Schema，供 LLM 的 Function Calling 使用。
        """
        schemas = []
        for name, tool in self.tools.items():
            schemas.append({
                "type": "function",
                "function": {
                    "name": name,
                    "description": tool.description,
                    "parameters": getattr(tool, "parameters", {"type": "object", "properties": {}})
                }
            })
        return schemas

    async def execute(self, name: str, **kwargs) -> Any:
        """
        执行特定的工具，并捕获一切异常，防止单个工具崩溃导致整个 Agent 宕机。
        """
        if name not in self.tools:
            return {"status": "error", "message": f"未找到名为 '{name}' 的工具。"}
            
        try:
            # 触发执行前，先从令牌桶中获取执行权限，若令牌耗尽则自动排队等待
            await self.rate_limiter.acquire()
            
            print(f"🔧 [Tool Executor] 正在调用 {name} | 参数: {kwargs}")
            tool = self.tools[name]
            # 判断工具 run 方法是否为 async 协程，如果不是，则放入 asyncio 线程池运行，防止阻塞异步事件循环
            if inspect.iscoroutinefunction(tool.run):
                return await tool.run(**kwargs)
            else:
                return await asyncio.to_thread(tool.run, **kwargs)
        except Exception as e:
            error_msg = f"工具执行异常: {str(e)}\n{traceback.format_exc()}"
            print(f"❌ [Tool Executor Error] {error_msg}")
            # 遵守 AGENTS.md 防线：不崩溃，如实上报错误给 LLM
            return {"status": "error", "message": f"执行失败: {str(e)}"}
