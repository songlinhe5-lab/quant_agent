"""
BE-02 L3 冷归档对象存储 (Cloudflare R2 / S3 兼容)

列式直写：利用 PyArrow 内置的 C++ 级 S3 虚拟文件系统 (pyarrow.fs.S3FileSystem)，
直接把内存中的 DataFrame 分区写入远端对象存储，避免任何中间格式转换。

分区布局 (Hive 风格)：
    {prefix}/{period}/{symbol_safe}/year=YYYY/month=MM/part-*.parquet

配置 (环境变量，未配置时优雅降级为 no-op，不抛异常、不写假数据)：
    KLINE_L3_ENDPOINT_URL  R2/S3 的 endpoint (如 https://<acct>.r2.cloudflarestorage.com)
    KLINE_L3_BUCKET        桶名
    KLINE_L3_ACCESS_KEY    access key (留空则回退到默认 AWS 凭证链)
    KLINE_L3_SECRET_KEY    secret key
    KLINE_L3_REGION        region (默认 auto)
    KLINE_L3_PREFIX        对象键前缀 (默认 kline)
"""

import asyncio
import os
from typing import Optional, Tuple

import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.parquet as pq
import structlog

logger = structlog.get_logger(__name__)


class S3ObjectStore:
    """
    K线冷归档对象存储后端 (R2 / S3 兼容)。

    通过 PyArrow S3FileSystem 直连，支持 Hive 分区批量写入与读回。
    未配置时所有方法为空操作（save 跳过、load 返回 None）。
    """

    def __init__(self):
        self.endpoint: Optional[str] = os.getenv("KLINE_L3_ENDPOINT_URL") or None
        self.bucket: Optional[str] = os.getenv("KLINE_L3_BUCKET") or None
        self.access_key: Optional[str] = os.getenv("KLINE_L3_ACCESS_KEY") or None
        self.secret_key: Optional[str] = os.getenv("KLINE_L3_SECRET_KEY") or None
        self.region: Optional[str] = os.getenv("KLINE_L3_REGION") or "auto"
        self.prefix: str = os.getenv("KLINE_L3_PREFIX") or "kline"
        # 测试注入点：(pyarrow.fs.FileSystem, root_path)
        self._fs_override: Optional[Tuple[object, str]] = None

    @property
    def configured(self) -> bool:
        """是否已具备可用的对象存储配置"""
        return bool(self.bucket and (self.endpoint or self.access_key))

    def _build_filesystem(self) -> Tuple[Optional[object], Optional[str]]:
        """
        返回 (filesystem, root_uri)。未配置或测试覆盖时返回对应值。

        S3 场景 root_uri = "{bucket}/{prefix}"；本地覆盖场景 root_uri = 临时目录绝对路径。
        """
        if self._fs_override is not None:
            return self._fs_override
        if not self.configured:
            return None, None

        import pyarrow.fs as pafs

        fs = pafs.S3FileSystem(
            endpoint_override=self.endpoint or None,
            access_key=self.access_key or None,
            secret_key=self.secret_key or None,
            region=self.region or None,
            scheme="https",
        )
        root = f"{self.bucket}/{self.prefix}" if self.prefix else self.bucket
        return fs, root

    @staticmethod
    def _symbol_dir(root: str, period: str, symbol: str) -> str:
        safe = symbol.replace(".", "_").replace("/", "_")
        return f"{root}/{period}/{safe}"

    async def save(self, symbol: str, period: str, df: pd.DataFrame) -> None:
        """
        将 K线 DataFrame 按 year/month 分区写入对象存储 (幂等覆盖)。

        Args:
            symbol: 标的代码 (如 US.AAPL)
            period: K线周期 (K_DAY 等)
            df: 含 time/open/high/low/close/volume 列的 DataFrame
        """
        if df is None or df.empty:
            return

        fs, root = self._build_filesystem()
        if fs is None:
            logger.debug("[L3] 未配置对象存储，跳过冷归档", symbol=symbol)
            return

        try:
            data = df.copy()
            data["time"] = pd.to_datetime(data["time"])
            # 仅归档超过 1 年的冷数据，避免与 L2 温层重复写热数据
            cutoff = pd.Timestamp.utcnow() - pd.Timedelta(days=365)
            cold = data[data["time"] < cutoff]
            if cold.empty:
                logger.debug("[L3] 无冷数据可归档", symbol=symbol)
                return

            cold = cold.copy()
            cold["year"] = cold["time"].dt.year
            cold["month"] = cold["time"].dt.month
            table = pa.Table.from_pandas(cold, preserve_index=False)
            out_dir = self._symbol_dir(root, period, symbol)

            def _write():
                pq.write_to_dataset(
                    table,
                    root_path=out_dir,
                    partition_cols=["year", "month"],
                    filesystem=fs,
                )

            await asyncio.to_thread(_write)
            logger.info(
                "[L3] 冷归档完成",
                symbol=symbol,
                period=period,
                rows=len(cold),
                target=out_dir,
            )
        except Exception as e:
            logger.error("[L3] 写入失败", symbol=symbol, error=str(e))

    async def load(self, symbol: str, period: str, days: int) -> Optional[pd.DataFrame]:
        """
        从对象存储读回最近 N 天的冷数据。

        Returns:
            过滤后的 K线 DataFrame，或 None (未配置 / 无数据 / 失败)
        """
        fs, root = self._build_filesystem()
        if fs is None:
            return None

        out_dir = self._symbol_dir(root, period, symbol)

        def _read():
            try:
                dataset = ds.dataset(out_dir, filesystem=fs, format="parquet", partitioning="hive")
                return dataset.to_table().to_pandas()
            except (FileNotFoundError, OSError):
                return None

        try:
            df = await asyncio.to_thread(_read)
            if df is None or df.empty:
                return None
            df["time"] = pd.to_datetime(df["time"])
            cutoff = pd.Timestamp.utcnow() - pd.Timedelta(days=days)
            df = df[df["time"] >= cutoff].sort_values("time")
            return df if not df.empty else None
        except Exception as e:
            logger.error("[L3] 读取失败", symbol=symbol, error=str(e))
            return None


# ── 全局单例 ──────────────────────────────────────────────────────
_l3_object_store: Optional[S3ObjectStore] = None


def get_l3_object_store() -> S3ObjectStore:
    global _l3_object_store
    if _l3_object_store is None:
        _l3_object_store = S3ObjectStore()
    return _l3_object_store
