"""ConnectionManager 单元测试 (连接探测/切换/关闭/交易上下文前置分支)。

通过 mock socket 与 _is_opend_reachable, 避免真实连接 Futu OpenD。
"""

from unittest.mock import MagicMock, patch

import pytest

from data_subservice.futu_src.connection_manager import ConnectionManager


class TestOpendReachable:
    def test_reachable(self):
        cm = ConnectionManager()
        with patch("data_subservice.futu_src.connection_manager.socket.socket") as mock_sock_cls:
            mock_sock = MagicMock()
            mock_sock_cls.return_value.__enter__.return_value = mock_sock
            mock_sock_cls.return_value.__exit__.return_value = False
            assert cm._is_opend_reachable() is True

    def test_unreachable(self):
        cm = ConnectionManager()
        with patch("data_subservice.futu_src.connection_manager.socket.socket") as mock_sock_cls:
            inst = mock_sock_cls.return_value
            inst.__enter__.side_effect = OSError("cannot connect")
            assert cm._is_opend_reachable() is False


class TestConnectOpenDUnreachable:
    def test_sets_error_status(self):
        cm = ConnectionManager()
        # 强制 OpenD 不可达, connect 应提前返回并置 ERROR
        with patch.object(cm, "_is_opend_reachable", return_value=False):
            cm.connect()
        assert cm.status == "ERROR"
        assert cm.quote_ctx is None
        assert "OpenD 不可达" in cm.error_msg


class TestSwitchHost:
    def test_unchanged(self):
        cm = ConnectionManager()
        res = cm.switch_host(cm._host, cm._port)
        assert res["status"] == "unchanged"

    def test_change_triggers_connect(self):
        cm = ConnectionManager()
        with patch.object(cm, "_is_opend_reachable", return_value=False):
            res = cm.switch_host("10.0.0.99", 11111)
        assert res["new_host"] == "10.0.0.99"
        assert res["status"] == "ERROR"  # 不可达 → ERROR


class TestClose:
    def test_close_without_ctx(self):
        cm = ConnectionManager()
        # quote_ctx 为 None 时不应抛
        cm.close()
        assert cm.quote_ctx is None
        assert cm.status == "DISCONNECTED"


class TestTargetProperty:
    def test_target_format(self):
        cm = ConnectionManager()
        assert cm.target == f"{cm._host}:{cm._port}"


class TestGetTradeContextUnreachable:
    def test_raises_connection_error(self):
        cm = ConnectionManager()
        with patch.object(cm, "_is_opend_reachable", return_value=False):
            with pytest.raises(ConnectionError):
                cm.get_trade_context(market=__import__("futu").TrdMarket.HK,
                                     trd_env=__import__("futu").TrdEnv.REAL)
