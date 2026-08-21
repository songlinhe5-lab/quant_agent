import asyncio
import time
from typing import Any, Dict, List, Optional

from hermes_agent.middleware import (
    FailureTracker,
    ToolContext,
    ToolMiddlewarePipeline,
    ToolResult,
    core_tool_execute,
    make_circuit_breaker_middleware,
)
from hermes_agent.scopes import ToolScope
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


def register_tool(scopes=None):
    """
    类装饰器工厂：自动将 Tool 类加入全局注册列表。

    用法：
        @register_tool()                          # 无参，默认全量
        @register_tool(scopes=["quote", "fundamental"])  # 带 scopes 参数

    Args:
        scopes: 工具所属场景标签列表，如 ["quote", "fundamental"]；未指定时默认为全量 DEFAULT_SET
    Returns:
        装饰器函数
    """

    def decorator(cls):
        setattr(cls, "_tool_scopes", scopes or [])
        if cls not in _AUTO_REGISTERED_TOOLS:
            _AUTO_REGISTERED_TOOLS.append(cls)
        return cls

    return decorator


# 💡 必须在 register_tool 定义之后导入 tools，触发 @register_tool
# 使用 lazy import 避免循环导入
def _load_tools():
    """延迟加载所有 tools（避免 circular import）"""
    import hermes_agent.tools  # noqa: F401


class ToolRegistry:
    """
    工具注册表：注册、Schema 转换与安全执行。
    BE-12：execute() 统一走 ToolResultCache（Redis Hash）。
    AGENT-02：execute() 经中间件管线（circuit_breaker → classifier → timer → core）。
    AGENT-09：结果正交分类（success/empty/stale/rate_limited/error/circuit_breaker）。
    """

    def __init__(self, result_cache: Optional[ToolResultCache] = None):
        self.tools = {}
        self.result_cache = result_cache if result_cache is not None else default_tool_result_cache
        self.rate_limiter = AsyncTokenBucket(capacity=3, fill_rate=1.0)

        # AGENT-02: 失败追踪器 + 中间件管线
        self.failure_tracker = FailureTracker(threshold=3)
        self._pipeline = self._build_pipeline()

        _load_tools()  # 触发延迟加载
        for tool_cls in _AUTO_REGISTERED_TOOLS:
            self.register(tool_cls())

    def register(self, tool):
        if not hasattr(tool, "name") or not hasattr(tool, "description"):
            raise ValueError(f"⚠️ 工具 {tool.__class__.__name__} 缺失 name 或 description 属性")

        self.tools[tool.name] = tool
        print(f"✅ Tool 注册成功: {tool.name} - {tool.description}")

    def get_all_schemas(self, warn: bool = True) -> List[Dict[str, Any]]:
        """
        获取全部工具 schema（已废弃，建议改用 get_schemas_by_scopes()）。

        Args:
            warn: 是否打印废弃警告（默认 True）
        Returns:
            全部工具 schema 列表
        """
        if warn:
            import warnings

            warnings.warn(
                "get_all_schemas() is deprecated and will be removed in a future version. "
                "Use get_schemas_by_scopes(scopes=None) instead.",
                DeprecationWarning,
                stacklevel=2,
            )
        return self.get_schemas_by_scopes(scopes=None)

    def _matches_scope(self, scope_filter: str) -> bool:
        """
        判断当前工具是否匹配指定 scope（或全量通配符 None）。

        Args:
            scope_filter: 单个 scope 字符串；None 表示全量通配符
        """
        if scope_filter is None:
            return True
        try:
            target_scope = ToolScope(scope_filter)
        except ValueError:
            # 非法 scope → 视为不匹配
            return False
        tool_scopes = getattr(self.__class__, "_tool_scopes", [])
        return target_scope.value in tool_scopes

    def get_schemas_by_scopes(self, scopes: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """
        按场景过滤工具 schema。

        Args:
            scopes: 期望的场景标签列表，如 ["quote", "fundamental"]；
                    未指定或空列表时返回全部工具 schema（向后兼容）
        Returns:
            匹配工具的工具 schema 列表
        """
        if not scopes:
            # 未指定过滤条件 → 返回全部（带弃用警告可选项）
            import warnings

            warnings.warn(
                "Calling get_schemas_by_scopes(scopes=None or []) returns all tools. "
                "Consider specifying an explicit scopes list to reduce context size.",
                UserWarning,
                stacklevel=2,
            )
            return [self._tool_to_schema(name, tool) for name, tool in self.tools.items()]

        result = []
        for name, tool in self.tools.items():
            tool_scopes = getattr(tool, "_tool_scopes", [])
            match = any(s in tool_scopes for s in scopes)
            if match:
                result.append(self._tool_to_schema(name, tool))
        return result

    def _tool_to_schema(self, name: str, tool) -> Dict[str, Any]:
        """将单个工具实例转为 OpenAI function-calling schema。"""
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": tool.description,
                "parameters": getattr(tool, "parameters", {"type": "object", "properties": {}}),
            },
        }

    def _build_pipeline(self) -> ToolMiddlewarePipeline:
        """
        AGENT-02: 构建中间件管线。

        管线仅包含 circuit_breaker（需要短路能力的中间件）。
        结果分类和计时在 execute() 后处理中完成，避免对原始工具返回值的包装冲突。
        """
        pipeline = ToolMiddlewarePipeline()
        pipeline.use(make_circuit_breaker_middleware(self.failure_tracker))
        return pipeline

    async def execute(self, name: str, **kwargs) -> Any:
        """
        执行工具（AGENT-02 中间件管线入口）。

        管线: circuit_breaker → classifier → timer → core_execute
        返回: dict（向后兼容），内含正交 status 标志（AGENT-09）。

        AGENT-09 正交标志: success / empty / stale / rate_limited / error / circuit_breaker
        """
        if name not in self.tools:
            return {"status": "error", "message": f"未找到名为 '{name}' 的工具。"}

        # 缓存检查（在管线外，避免缓存命中走中间件开销）
        cached = await self.result_cache.get(name, kwargs)
        if cached is not None:
            print(f"⚡ [Tool Cache HIT] {name}")
            return cached

        _t_start = time.monotonic()

        # AGENT-02: 经中间件管线执行
        ctx = ToolContext(tool_name=name, kwargs=kwargs)

        async def core_with_cache(c: ToolContext) -> Any:
            """核心执行 + 缓存写入。"""
            raw_result = await core_tool_execute(c, self.tools)
            # 仅缓存成功结果（检查原始结果的 status 字段）
            is_success = True
            if isinstance(raw_result, dict):
                st = str(raw_result.get("status", "")).lower()
                if st in ("error", "failed", "rate_limited"):
                    is_success = False
            if is_success:
                await self.result_cache.set(name, kwargs, raw_result)
            return raw_result

        result = await self._pipeline.execute(ctx, core_with_cache)

        # ── 后处理：分类 + 计时 + 转 dict ──────────────────────────
        _t_end = time.monotonic()

        if isinstance(result, ToolResult):
            # 熔断器产生的 ToolResult
            output = result.to_dict()
        else:
            # 原始工具返回值 —— 确保有 status 字段
            output = result if isinstance(result, dict) else {"data": result}
            if "status" not in output:
                output["status"] = "success"

        output["execution_time"] = round(_t_end - _t_start, 3)

        # AGENT-09: 失败追踪（管线外，避免分类冲突）
        _st = str(output.get("status", "")).lower()
        if _st in ("error", "failed"):
            self.failure_tracker.record_failure(name, output.get("message", "未知错误"))
        elif _st != "rate_limited":
            # 成功 / 空 / 限流 → 重置计数（限流不计入 AGENTS.md §10.8）
            self.failure_tracker.record_success(name)

        # 日志
        if _st == "error":
            print(f"❌ [Tool Executor Error] {name}: {output.get('message', '')}")
        elif _st == "circuit_breaker":
            print(f"🚫 [Circuit Breaker] {name}: {output.get('message', '')}")
        else:
            print(f"🔧 [Tool Executor] {name} → {_st} ({output['execution_time']:.2f}s)")

        return output
