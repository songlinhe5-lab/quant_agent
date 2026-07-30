"""单测：datalake/object_store.S3ObjectStore

覆盖：配置门控（未配置→no-op）、PyArrow 分区写入与读回、按天数过滤、
本地文件系统注入（无需真实 S3 凭证即可验证 S3FileSystem 同构路径）。
"""

from datetime import datetime, timedelta, timezone

import pandas as pd
import pyarrow as pa
import pytest

from backend.services.datalake.object_store import S3ObjectStore


def _make_df(days_back_start=400, days_back_end=380):
    """构造跨两个自然月的冷数据 DataFrame"""
    rows = []
    base = datetime.now(timezone.utc)
    for d in range(days_back_start, days_back_end, -1):
        dt = base - timedelta(days=d)
        rows.append(
            {
                "time": dt,
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.5,
                "volume": 1000.0,
            }
        )
    return pd.DataFrame(rows)


def _local_store(tmp_path):
    store = S3ObjectStore()
    store._fs_override = (pa.fs.LocalFileSystem(), str(tmp_path))
    return store


def test_configured_requires_bucket_and_endpoint_or_key(monkeypatch):
    monkeypatch.setattr(
        "backend.services.datalake.object_store.os.getenv",
        lambda k, default=None: {"KLINE_L3_BUCKET": "bk"}.get(k, default),
    )
    # 仅 bucket 无 endpoint/key -> 未配置
    assert S3ObjectStore().configured is False


def test_save_and_load_roundtrip(tmp_path):
    store = _local_store(tmp_path)
    df = _make_df()
    import asyncio

    asyncio.get_event_loop().run_until_complete(store.save("US.AAPL", "K_DAY", df))

    # 确认 Hive 分区目录已落盘
    parts = list(tmp_path.glob("K_DAY/US_AAPL/year=*"))
    assert parts, "应生成 year= 分区目录"

    loaded = asyncio.get_event_loop().run_until_complete(store.load("US.AAPL", "K_DAY", days=500))
    assert loaded is not None
    assert len(loaded) == len(df)
    assert set(["open", "high", "low", "close", "volume"]).issubset(loaded.columns)


def test_load_filters_by_days(tmp_path):
    store = _local_store(tmp_path)
    df = _make_df()
    import asyncio

    asyncio.get_event_loop().run_until_complete(store.save("US.AAPL", "K_DAY", df))
    # 仅请求最近 10 天 -> 冷数据全在 380+ 天前，应返回 None
    loaded = asyncio.get_event_loop().run_until_complete(store.load("US.AAPL", "K_DAY", days=10))
    assert loaded is None


def test_not_configured_is_noop():
    store = S3ObjectStore()  # 无 env -> 未配置
    import asyncio

    assert store.configured is False
    # save/load 不应抛异常
    asyncio.get_event_loop().run_until_complete(store.save("US.AAPL", "K_DAY", _make_df()))
    assert asyncio.get_event_loop().run_until_complete(store.load("US.AAPL", "K_DAY", 400)) is None


def test_save_skips_when_no_cold_data(tmp_path):
    store = _local_store(tmp_path)
    # 全部为最近数据 (< 365 天) -> 无冷数据可归档
    recent = pd.DataFrame(
        [
            {
                "time": datetime.now(timezone.utc) - timedelta(days=1),
                "open": 1,
                "high": 1,
                "low": 1,
                "close": 1,
                "volume": 1,
            },
        ]
    )
    import asyncio

    asyncio.get_event_loop().run_until_complete(store.save("US.AAPL", "K_DAY", recent))
    # 不应生成任何分区文件
    assert not list(tmp_path.glob("K_DAY/US_AAPL/year=*"))


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
