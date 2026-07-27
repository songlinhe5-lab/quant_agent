"""DataSourceResult / DataSourcePort 单测"""

from backend.adapters.ports.data_source_port import DataSourcePort, DataSourceResult


def test_has_data():
    # 覆盖 DataSourceResult.has_data (line 81) 各分支
    assert DataSourceResult.success("x").has_data() is True
    assert DataSourceResult.success("").has_data() is False
    assert DataSourceResult.success(None).has_data() is False
    assert DataSourceResult.error("boom").has_data() is False


class _DummySource(DataSourcePort):
    """最小可实例化的 DataSourcePort 实现, 用于覆盖默认辅助方法"""

    @property
    def name(self) -> str:
        return "dummy"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def capabilities(self) -> list[str]:
        return ["quote", "history"]

    @property
    def is_available(self) -> bool:
        return True

    def fetch(self, action: str, params: dict) -> DataSourceResult:
        return DataSourceResult.success({"action": action})


def test_supports_action():
    src = _DummySource()
    # 覆盖 DataSourcePort.supports_action (line 197)
    assert src.supports_action("quote") is True
    assert src.supports_action("history") is True
    assert src.supports_action("unsupported") is False


def test_validate_params():
    src = _DummySource()
    # 覆盖 DataSourcePort.validate_params (lines 211-215)
    assert src.validate_params("quote", {}) is False
    assert src.validate_params("quote", "not-a-dict") is False
    assert src.validate_params("quote", {"ticker": "AAPL"}) is True
