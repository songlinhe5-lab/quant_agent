"""Bootstrap 包：应用生命周期管理 (ARCH-01)"""

from backend.bootstrap.lifecycle import app_lifespan, global_llm_client, global_registry

__all__ = ["app_lifespan", "global_registry", "global_llm_client"]
