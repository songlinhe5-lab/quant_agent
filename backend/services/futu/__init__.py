"""
Futu 服务模块包
提供 Futu OpenD 连接、行情、交易等功能的模块化实现

主节点不安装 futu-api 时，提供 stub 对象避免启动崩溃。
"""


class _FutuStub:
    """futu-api 未安装时的占位对象，避免顶层 import 崩溃。"""

    status = "UNAVAILABLE"
    error_msg = "futu-api SDK 未安装，主节点走 HTTP 路由"

    def __getattr__(self, name: str):
        """任何方法调用返回 stub 响应而非崩溃。"""

        def _stub_method(*args, **kwargs):
            return {"status": "error", "message": self.error_msg}

        return _stub_method


try:
    from .service import FutuService, futu_service

    __all__ = ["FutuService", "futu_service"]
except ImportError:
    # 主节点无 futu-api 包，提供 stub
    futu_service = _FutuStub()  # type: ignore[assignment]
    FutuService = None  # type: ignore[assignment,misc]

    __all__ = ["FutuService", "futu_service"]
