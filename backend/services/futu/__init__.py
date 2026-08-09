"""
Futu 服务模块包
提供 Futu OpenD 连接、行情、交易等功能的模块化实现

BE-ARCH-08a: 主镜像不安装 futu-api SDK，故包顶层禁止无条件 import service（其裸
`from futu import ...` 会让 backend.main 在 import 阶段即 ModuleNotFoundError 崩溃）。
纯函数工具（utils）零 SDK 依赖，安全顶层暴露；service 仅在 futu-api 可用时惰性导入，
缺失时置 None，既保证主服务 import 链不崩，又保留子服务（已装 futu-api）的正常使用。
"""

from .utils import format_ticker, is_futu_unsupported

try:
    from .service import FutuService, futu_service
except ImportError:
    # 主镜像未安装 futu-api：惰性降级，不阻断 import 链
    FutuService = None  # type: ignore[assignment]
    futu_service = None  # type: ignore[assignment]

__all__ = ["is_futu_unsupported", "format_ticker", "FutuService", "futu_service"]
