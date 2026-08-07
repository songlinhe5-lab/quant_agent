"""
API 鉴权覆盖率测试 (BE-SEC-COVERAGE)
====================================
目标：把"敏感端点漏鉴权"卡进 CI，防止有人新增敏感路由时忘记加 Depends 鉴权。

设计：
- 通过 introspect FastAPI app 的路由，检测每条路由是否挂载了鉴权依赖
  （get_current_user / get_current_user_optional / get_current_username）。
- WebSocket 端点鉴权为手动校验（从 query_params 取 token 并 jwt.decode），
  故检测 handler 源码是否含 `query_params` + `token` 判定。
- 仅对「关键敏感前缀」强制要求鉴权，避免误杀本就公开的行情/计算类端点。
- 公开例外（看起来敏感但确实有意公开）显式列出，防止被误判为漏网。

注意：本测试刻意只对"关键敏感前缀"失败。良性公开端点（/options/*、/macro/*、
/briefing/*、/backtest 计算、/auth 登录入口、/health、/docs 等）不在此列，
由产品侧确认其公开性，不在本测试强制范围内。
"""

import inspect

from fastapi.routing import APIRoute, APIWebSocketRoute

from backend.main import app
from backend.routers.auth import get_current_user, get_current_user_optional
from backend.routers.chat import get_current_username

AUTH_CALLABLES = {get_current_user, get_current_user_optional, get_current_username}

# 关键敏感前缀：这些路径下的路由「必须」携带鉴权依赖，否则视为漏网
CRITICAL_MUST_AUTH_PREFIXES = (
    "/api/v1/trade",
    "/api/v1/strategy/deploy-to-oms",
    "/api/v1/strategy/save",
    "/api/v1/strategy/draft",
    "/api/v1/strategy/",
    "/api/v1/audit",
    "/api/v1/alert",
    "/api/v1/oms",
    "/api/v1/settings",
    "/api/v1/system",
    "/api/v1/preferences",
    "/api/v1/screener",
    "/api/v1/logs",
    "/api/v1/chat",
    "/api/v1/sessions",
    "/api/v1/auth/me",
    "/api/v1/auth/change-password",
)

# 公开例外：路径落在关键前缀内，但属有意公开（行情/计算/登录入口），不强制
PUBLIC_EXCEPTIONS = (
    "/api/v1/strategy/generate",  # 策略生成：公开计算端点
    "/api/v1/oms/algo/analytics",  # 算法绩效：客户端输入的计算端点
    "/api/v1/auth/login",
    "/api/v1/auth/refresh",
    "/api/v1/auth/register",
    "/api/v1/auth/forgot-password",
    "/api/v1/auth/reset-password",
    "/api/v1/settings/news-tags",  # 资讯标签规则：公开配置
    "/api/v1/settings/yfinance",  # YF 节点配置：公开配置
)

# 系统级公开端点（非 /api/v1 下）。注意：勿用 "/" 作前缀，否则 startswith 会匹配所有路径
SYSTEM_PUBLIC_PREFIXES = ("/health", "/docs", "/redoc", "/openapi.json")


def _collect(dep):
    found = set()
    if dep is None:
        return found
    if getattr(dep, "call", None) in AUTH_CALLABLES:
        found.add(dep.call)
    for sub in dep.dependencies or []:
        found |= _collect(sub)
    return found


def _route_has_auth(route) -> bool:
    for d in route.dependencies or []:
        if _collect(getattr(d, "dependant", None)):
            return True
    if _collect(getattr(route, "dependant", None)):
        return True
    return False


def _is_public_exception(path: str) -> bool:
    return any(path.startswith(p) for p in PUBLIC_EXCEPTIONS)


def _is_system_public(path: str) -> bool:
    return path in SYSTEM_PUBLIC_PREFIXES or path == "/"


def _is_critical(path: str) -> bool:
    return any(path.startswith(p) for p in CRITICAL_MUST_AUTH_PREFIXES)


def test_no_unauthenticated_critical_routes():
    """关键敏感前缀下的路由必须携带鉴权依赖；WebSocket 必须手动校验 token。"""
    http_leaks = []
    ws_leaks = []

    for route in app.routes:
        if isinstance(route, APIRoute):
            # 系统级公开端点直接跳过
            if _is_system_public(route.path):
                continue
            # 已鉴权 → OK
            if _route_has_auth(route):
                continue
            # 公开例外 → OK
            if _is_public_exception(route.path):
                continue
            # 纯 OPTIONS 路由 (CORS preflight) 跳过
            if route.methods and route.methods == {"OPTIONS"}:
                continue
            # 命中关键敏感前缀且无鉴权 → 漏网
            if _is_critical(route.path):
                methods = ",".join(sorted(route.methods)) if route.methods else ""
                http_leaks.append(f"{methods:8} {route.path}")

        elif isinstance(route, APIWebSocketRoute):
            src = inspect.getsource(route.endpoint)
            manual_token = ("query_params" in src) and ("token" in src)
            if not manual_token:
                ws_leaks.append(route.path)

    assert not http_leaks, (
        "发现关键敏感路由缺失鉴权依赖（应加 Depends(get_current_user) 或移入 PUBLIC_EXCEPTIONS）：\n"
        + "\n".join(f"  - {r}" for r in sorted(http_leaks))
    )
    assert not ws_leaks, "发现 WebSocket 端点未做 token 握手鉴权（应校验 query_params.token）：\n" + "\n".join(
        f"  - {r}" for r in sorted(ws_leaks)
    )
