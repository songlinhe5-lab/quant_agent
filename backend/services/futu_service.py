"""
FutuService 兼容层
为了保持向后兼容，从新的模块化架构中导入并导出 futu_service
"""

from backend.services.futu import FutuService, futu_service

# 保持原有的导出方式
__all__ = ["FutuService", "futu_service"]
