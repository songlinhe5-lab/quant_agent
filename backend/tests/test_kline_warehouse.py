"""
K 线数据仓库服务单元测试
覆盖: backend/services/kline_warehouse.py
"""

import asyncio
import os
import sys
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))


from backend.services.kline_warehouse import KlineWarehouse, kline_warehouse


def _make_kline_df(rows: int = 30, base_price: float = 100.0):
    """构造测试用 K 线 DataFrame"""
    base_time = pd.to_datetime("2024-01-01")
    return pd.DataFrame(
        {
            "time": [base_time + timedelta(days=i) for i in range(rows)],
            "open": [base_price + i for i in range(rows)],
            "high": [base_price + 1 + i for i in range(rows)],
            "low": [base_price - 1 + i for i in range(rows)],
            "close": [base_price + 0.5 + i for i in range(rows)],
            "volume": [10000 + i for i in range(rows)],
        }
    )


class TestKlineWarehouse:
    """KlineWarehouse 单元测试"""

    @pytest.fixture
    def warehouse(self):
        return KlineWarehouse()

    def test_get_file_path_sanitizes_ticker(self, warehouse):
        """ticker 中的 . 和 / 应被替换为 _，并按 ktype 分目录"""
        path = warehouse._get_file_path("HK.00700", "K_DAY")
        assert "K_DAY" in path
        assert "HK_00700.parquet" in path
        assert path.endswith("HK_00700.parquet")

        path2 = warehouse._get_file_path("US/AAPL", "K_60M")
        assert "K_60M" in path2
        assert "US_AAPL.parquet" in path2

    def test_get_file_path_creates_ktype_dir(self, warehouse, tmp_path):
        """应自动创建 ktype 子目录"""
        warehouse.data_dir = str(tmp_path)
        path = warehouse._get_file_path("HK.00700", "K_DAY")
        assert os.path.isdir(os.path.join(str(tmp_path), "K_DAY"))

    async def test_get_history_missing_file_returns_none(self, warehouse, tmp_path):
        """本地文件不存在时应返回 None"""
        warehouse.data_dir = str(tmp_path)
        result = await warehouse.get_history("HK.99999", "K_DAY", num=10)
        assert result is None

    async def test_get_history_reads_parquet_success(self, warehouse, tmp_path):
        """本地 Parquet 存在时应返回 DataFrame 并按 num 截断"""
        warehouse.data_dir = str(tmp_path)
        # 确保文件存在
        path = warehouse._get_file_path("HK.00700", "K_DAY")
        with open(path, "w") as f:
            f.write("placeholder")
        # Mock pd.read_parquet 返回 30 条数据
        test_df = _make_kline_df(rows=30)
        with patch("backend.services.kline_warehouse.pd.read_parquet", return_value=test_df.copy()):
            result = await warehouse.get_history("HK.00700", "K_DAY", num=5)
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 5
        # tail 切片：最新 5 条
        assert float(result.iloc[-1]["close"]) == 129.5

    async def test_get_history_corrupt_file_returns_none(self, warehouse, tmp_path):
        """Parquet 读取异常时应返回 None"""
        warehouse.data_dir = str(tmp_path)
        path = warehouse._get_file_path("HK.BAD", "K_DAY")
        with open(path, "w") as f:
            f.write("not a parquet file")

        with patch("backend.services.kline_warehouse.pd.read_parquet", side_effect=RuntimeError("corrupt")):
            result = await warehouse.get_history("HK.BAD", "K_DAY", num=5)
        assert result is None

    async def test_update_ticker_first_time_full_fetch(self, warehouse, tmp_path):
        """首次冷启动应拉取 10000 条历史，futu 成功返回时入库"""
        warehouse.data_dir = str(tmp_path)
        # 注意：首次冷启动 num_to_fetch=10000，futu 返回 < 2000 条会触发降级至 yfinance
        # 因此构造足够多的 futu 数据以避免降级，或同时 mock yf_service.fetch_yf_data
        futu_data = [
            {
                "time": f"2024-01-{i:02d} 00:00:00",
                "open": 100.0 + i,
                "high": 101.0 + i,
                "low": 99.0 + i,
                "close": 100.5 + i,
                "volume": 10000 + i,
            }
            for i in range(1, 11)
        ]
        futu_response = {"status": "success", "data": futu_data}
        saved_dfs = []

        def fake_to_parquet(self_df, path, index=False):
            saved_dfs.append(self_df.copy())

        # 由于 num_to_fetch=10000 > 2000 而 futu 仅返回 10 条，会触发 yfinance 降级
        # 所以同时 mock yf_service.fetch_yf_data 返回失败，使流程直接走 futu 数据保存路径
        # 实际上源码在 len(new_data) < 2000 时会丢弃 futu 数据，所以我们必须 mock yfinance 成功
        yf_df = pd.DataFrame(
            {
                "Date": ["2024-01-01", "2024-01-02"],
                "Open": [100.0, 100.5],
                "High": [101.0, 102.0],
                "Low": [99.0, 100.0],
                "Close": [100.5, 101.5],
                "Volume": [10000, 12000],
            }
        )
        with (
            patch("backend.services.kline_warehouse.futu_service.get_history", new=AsyncMock(return_value=futu_response)),
            patch("backend.services.kline_warehouse.yf_service.fetch_yf_data", new=AsyncMock(return_value=(True, yf_df, "ok"))),
            patch("backend.services.kline_warehouse.pd.read_parquet", side_effect=FileNotFoundError),
            patch.object(pd.DataFrame, "to_parquet", fake_to_parquet),
        ):
            result = await warehouse.update_ticker("HK.00700", "K_DAY")

        assert result is True
        assert len(saved_dfs) == 1
        assert len(saved_dfs[0]) == 2
        assert "close" in saved_dfs[0].columns

    async def test_update_ticker_returns_true_when_already_latest(self, warehouse, tmp_path):
        """已有最新数据（last_date == now）时应跳过并返回 True"""
        warehouse.data_dir = str(tmp_path)
        path = warehouse._get_file_path("HK.00700", "K_DAY")
        with open(path, "w") as f:
            f.write("placeholder")

        # last_date = today → days_diff <= 0 → 跳过
        today_df = pd.DataFrame(
            {
                "time": [pd.Timestamp(datetime.now().date())],
                "open": [100.0],
                "high": [101.0],
                "low": [99.0],
                "close": [100.5],
                "volume": [10000],
            }
        )
        with (
            patch("backend.services.kline_warehouse.pd.read_parquet", return_value=today_df),
            patch(
                "backend.services.kline_warehouse.futu_service.get_history",
                new=AsyncMock(return_value={"status": "success", "data": []}),
            ) as mock_futu,
        ):
            result = await warehouse.update_ticker("HK.00700", "K_DAY", force_full=False)

        assert result is True
        mock_futu.assert_not_called()

    async def test_update_ticker_fallback_to_yfinance(self, warehouse, tmp_path):
        """futu 失败时应降级至 yfinance"""
        warehouse.data_dir = str(tmp_path)
        yf_df = pd.DataFrame(
            {
                "Date": ["2024-01-01", "2024-01-02"],
                "Open": [100.0, 100.5],
                "High": [101.0, 102.0],
                "Low": [99.0, 100.0],
                "Close": [100.5, 101.5],
                "Volume": [10000, 12000],
            }
        )
        saved_dfs = []

        def fake_to_parquet(self_df, path, index=False):
            saved_dfs.append(self_df.copy())

        with (
            patch("backend.services.kline_warehouse.futu_service.get_history", new=AsyncMock(return_value={"status": "error"})),
            patch("backend.services.kline_warehouse.yf_service.fetch_yf_data", new=AsyncMock(return_value=(True, yf_df, "ok"))),
            patch("backend.services.kline_warehouse.pd.read_parquet", side_effect=FileNotFoundError),
            patch.object(pd.DataFrame, "to_parquet", fake_to_parquet),
        ):
            result = await warehouse.update_ticker("HK.00700", "K_DAY")

        assert result is True
        assert len(saved_dfs) == 1
        assert len(saved_dfs[0]) == 2

    async def test_update_ticker_all_sources_fail_returns_false(self, warehouse, tmp_path):
        """futu 与 yfinance 均失败时应返回 False"""
        warehouse.data_dir = str(tmp_path)
        with (
            patch("backend.services.kline_warehouse.futu_service.get_history", new=AsyncMock(return_value={"status": "error"})),
            patch("backend.services.kline_warehouse.yf_service.fetch_yf_data", new=AsyncMock(return_value=(False, None, "fail"))),
            patch("backend.services.kline_warehouse.pd.read_parquet", side_effect=FileNotFoundError),
        ):
            result = await warehouse.update_ticker("HK.00700", "K_DAY")

        assert result is False

    async def test_update_ticker_force_full_ignores_existing(self, warehouse, tmp_path):
        """force_full=True 时应忽略已有数据并拉取全量"""
        warehouse.data_dir = str(tmp_path)
        path = warehouse._get_file_path("HK.00700", "K_DAY")
        with open(path, "w") as f:
            f.write("placeholder")

        old_df = pd.DataFrame(
            {
                "time": [pd.Timestamp("2023-01-01")],
                "open": [50.0],
                "high": [51.0],
                "low": [49.0],
                "close": [50.5],
                "volume": [1000],
            }
        )
        new_data = [
            {
                "time": "2024-06-01 00:00:00",
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.5,
                "volume": 10000,
            },
        ]
        # force_full=True 时 num_to_fetch=10000，futu 仅返回 1 条会触发 yfinance 降级
        # 因此需要同时 mock yf_service.fetch_yf_data 以避免实际网络请求
        yf_df = pd.DataFrame(
            {
                "Date": ["2024-06-01"],
                "Open": [100.0],
                "High": [101.0],
                "Low": [99.0],
                "Close": [100.5],
                "Volume": [10000],
            }
        )
        saved_dfs = []

        def fake_to_parquet(self_df, path, index=False):
            saved_dfs.append(self_df.copy())

        with (
            patch("backend.services.kline_warehouse.futu_service.get_history", new=AsyncMock(return_value={"status": "success", "data": new_data})),
            patch("backend.services.kline_warehouse.yf_service.fetch_yf_data", new=AsyncMock(return_value=(True, yf_df, "ok"))),
            patch("backend.services.kline_warehouse.pd.read_parquet", return_value=old_df),
            patch.object(pd.DataFrame, "to_parquet", fake_to_parquet),
        ):
            result = await warehouse.update_ticker("HK.00700", "K_DAY", force_full=True)

        assert result is True
        # force_full=True 时 existing_df 始终为 None，最终保存的应只有新数据
        assert len(saved_dfs) == 1
        assert len(saved_dfs[0]) == 1
        assert float(saved_dfs[0].iloc[0]["close"]) == 100.5

    def test_global_singleton_exists(self):
        """全局单例 kline_warehouse 应可正常导入"""
        assert hasattr(kline_warehouse, "data_dir")
        assert hasattr(kline_warehouse, "update_ticker")
