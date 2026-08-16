"""PushHandler.register_all_handlers 路由编排测试。

mock quote_ctx.set_handler 成功 / 抛异常, 覆盖 register_all_handlers
的正常与异常分支 (各 _make_*_handler 工厂返回 futu 基类实例, 已安装 futu)。
"""

from unittest.mock import MagicMock

import pytest

from data_subservice.futu_src import push_handler as ph


class TestRegisterAllHandlers:
    def test_success(self):
        quote_ctx = MagicMock()
        quote_ctx.set_handler.return_value = None
        ph.register_all_handlers(quote_ctx)
        # 所有 handler 都应被 set 出去
        assert quote_ctx.set_handler.call_count >= 5

    def test_exception_branch(self):
        quote_ctx = MagicMock()
        quote_ctx.set_handler.side_effect = RuntimeError("set_handler boom")
        ph.register_all_handlers(quote_ctx)
        # 异常被吞, 不抛出; handler 不可用计数应增加
        assert quote_ctx.set_handler.call_count >= 1

    def test_no_quote_ctx(self):
        # quote_ctx 为 None 时直接跳过, 不抛
        ph.register_all_handlers(None)
