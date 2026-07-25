"""宏观服务包：按领域聚合 fred / macro_calendar / sentiment 模块。

重导出各子模块公开符号，规范访问路径为 `backend.services.macro.X`。
"""

from .fred_service import *  # noqa: F401,F403
from .macro_calendar_service import *  # noqa: F401,F403
from .sentiment_service import *  # noqa: F401,F403
from .sentiment_tracker import *  # noqa: F401,F403
