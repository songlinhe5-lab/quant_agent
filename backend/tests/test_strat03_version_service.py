"""
STRAT-03a: 策略版本服务测试
"""
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from backend.core.models import StrategyVersion
from backend.services import strategy_version_service


@pytest.fixture
def mock_db():
    """Mock database session"""
    db = MagicMock(spec=Session)
    db.query.return_value = MagicMock()
    return db


def test_compute_code_hash():
    """测试代码哈希计算"""
    code = "print('hello')"
    hash1 = strategy_version_service.compute_code_hash(code)
    hash2 = strategy_version_service.compute_code_hash(code)

    # 同一代码应产生相同 hash
    assert hash1 == hash2
    # SHA256 长度为 64
    assert len(hash1) == 64


def test_save_version_new(mock_db):
    """测试保存新版本"""
    # Mock: 策略不存在
    mock_db.query.return_value.filter.return_value.first.return_value = None
    # Mock: 无现有版本
    mock_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = None
    # Mock: commit 成功
    mock_db.commit.return_value = None

    result = strategy_version_service.save_version(
        db=mock_db,
        strategy_name="TestStrategy",
        code="print('test')",
        source="manual",
        message="Initial version",
    )

    assert result["is_new"] is True
    assert result["seq"] == 1
    assert len(result["version_id"]) > 0
    mock_db.add.assert_called()
    mock_db.commit.assert_called_once()


def test_save_version_idempotent(mock_db):
    """测试幂等性：同 hash 不重复创建"""
    existing_version = MagicMock(spec=StrategyVersion)
    existing_version.id = "existing-id"
    existing_version.seq = 5
    existing_version.code_hash = "abc123"

    # Mock: 已存在相同 hash 的版本
    mock_db.query.return_value.filter.return_value.first.return_value = existing_version

    result = strategy_version_service.save_version(
        db=mock_db,
        strategy_name="TestStrategy",
        code="print('test')",
        source="manual",
    )

    assert result["is_new"] is False
    assert result["version_id"] == "existing-id"
    assert result["seq"] == 5
    mock_db.add.assert_not_called()


def test_get_versions(mock_db):
    """测试获取版本列表"""
    # Mock: 返回两个版本
    v1 = MagicMock(spec=StrategyVersion)
    v1.id = "v1"
    v1.seq = 1
    v1.source = "manual"
    v1.message = "Initial"
    v1.code_hash = "hash1"
    v1.parent_id = None
    v1.created_at = None

    v2 = MagicMock(spec=StrategyVersion)
    v2.id = "v2"
    v2.seq = 2
    v2.source = "ai-apply"
    v2.message = "AI generated"
    v2.code_hash = "hash2"
    v2.parent_id = None
    v2.created_at = None

    mock_db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = [v2, v1]

    result = strategy_version_service.get_versions(mock_db, "TestStrategy")

    assert len(result) == 2
    assert result[0]["seq"] == 2  # 倒序
    assert result[1]["seq"] == 1
    assert result[0]["code_hash"] == "hash2"  # hash 太短则原样返回


def test_get_version(mock_db):
    """测试获取单个版本"""
    version = MagicMock(spec=StrategyVersion)
    version.id = "v1"
    version.strategy_id = "TestStrategy"
    version.seq = 1
    version.code = "print('test')"
    version.code_hash = "hash1"
    version.source = "manual"
    version.message = "Initial"
    version.parent_id = None
    version.params_schema = None
    version.created_at = None

    mock_db.query.return_value.filter.return_value.first.return_value = version

    result = strategy_version_service.get_version(mock_db, "v1")

    assert result is not None
    assert result["id"] == "v1"
    assert result["code"] == "print('test')"


def test_get_version_not_found(mock_db):
    """测试获取不存在的版本"""
    mock_db.query.return_value.filter.return_value.first.return_value = None

    result = strategy_version_service.get_version(mock_db, "nonexistent")

    assert result is None


def test_restore_version(mock_db):
    """测试版本恢复"""
    # Mock: 源版本
    source_version = MagicMock(spec=StrategyVersion)
    source_version.id = "v1"
    source_version.code = "original code"
    source_version.params_schema = {"param1": 10}

    mock_db.query.return_value.filter.return_value.first.return_value = source_version

    # Mock: save_version 返回
    with patch.object(strategy_version_service, 'save_version') as mock_save:
        mock_save.return_value = {
            "version_id": "v2",
            "seq": 2,
            "code_hash": "hash2",
            "is_new": True,
        }

        result = strategy_version_service.restore_version(
            db=mock_db,
            strategy_name="TestStrategy",
            version_id="v1",
        )

        assert result is not None
        assert result["version_id"] == "v2"
        mock_save.assert_called_once()
        # 验证 source 为 "restore"
        call_kwargs = mock_save.call_args[1]
        assert call_kwargs["source"] == "restore"
        assert call_kwargs["parent_id"] == "v1"


def test_restore_version_not_found(mock_db):
    """测试恢复不存在的版本"""
    mock_db.query.return_value.filter.return_value.first.return_value = None

    result = strategy_version_service.restore_version(
        db=mock_db,
        strategy_name="TestStrategy",
        version_id="nonexistent",
    )

    assert result is None
