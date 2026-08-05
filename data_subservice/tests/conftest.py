"""data_subservice 单测统一入口。

注入两条路径以确保与原 backend/tests 下运行行为一致:
  1. 仓库根目录 -> 使 `data_subservice` 作为顶层包可被 `import data_subservice.main`
  2. data_subservice 目录本身 -> 兼容 `from _internal.tushare import service` 这类
     以 data_subservice 为根的隐式绝对导入 (原 test_subservice_tushare_service.py 用法)

复用主工程 pyproject.toml 的 pytest 配置 (asyncio_mode=auto 等),
本目录被纳入 testpaths 后随 backend/tests 一并由 CI 执行。
"""

import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_SUB = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for _p in (_ROOT, _SUB):
    if _p not in sys.path:
        sys.path.insert(0, _p)
