#!/usr/bin/env python3
"""
BE-18: PostgreSQL 每日备份脚本

功能：
1. 使用 pg_dump 导出 PostgreSQL 数据库
2. 压缩备份文件（gzip）
3. 上传到 Cloudflare R2 / S3 兼容存储
4. 清理本地过期备份
5. 可选：发送备份结果通知

使用方式：
    # 手动执行
    python -m backend.scripts.pg_backup --output /tmp/backup

    # 通过 cron 定时（每天凌晨 4:00）
    0 4 * * * cd /path/to/quant_agent && python -m backend.scripts.pg_backup --upload

    # Docker 环境
    docker exec quant-agent python -m backend.scripts.pg_backup --upload --cleanup-days 7

环境变量：
    DATABASE_URL: PostgreSQL 连接字符串
    R2_ENDPOINT: Cloudflare R2 端点
    R2_ACCESS_KEY: R2 访问密钥
    R2_SECRET_KEY: R2 密钥
    R2_BUCKET: R2 存储桶名称
    R2_PREFIX: R2 对象前缀（默认 "backups/postgres"）
"""  # noqa: E501
import asyncio
import gzip
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import structlog

# 将项目根目录加入 sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

logger = structlog.get_logger(__name__)


class PostgresBackup:
    """PostgreSQL 备份管理器"""

    def __init__(
        self,
        database_url: Optional[str] = None,
        output_dir: str = "/tmp/pg_backup",
        r2_endpoint: Optional[str] = None,
        r2_access_key: Optional[str] = None,
        r2_secret_key: Optional[str] = None,
        r2_bucket: Optional[str] = None,
        r2_prefix: str = "backups/postgres",
    ):
        self.database_url = database_url or os.getenv("DATABASE_URL", "")
        self.output_dir = Path(output_dir)
        self.r2_endpoint = r2_endpoint or os.getenv("R2_ENDPOINT")
        self.r2_access_key = r2_access_key or os.getenv("R2_ACCESS_KEY")
        self.r2_secret_key = r2_secret_key or os.getenv("R2_SECRET_KEY")
        self.r2_bucket = r2_bucket or os.getenv("R2_BUCKET")
        self.r2_prefix = r2_prefix or os.getenv("R2_PREFIX", "backups/postgres")

        # 确保输出目录存在
        self.output_dir.mkdir(parents=True, exist_ok=True)

    async def backup(
        self,
        compress: bool = True,
        upload: bool = False,
        cleanup_days: int = 7,
    ) -> Dict[str, Any]:
        """
        执行完整备份流程

        Args:
            compress: 是否压缩备份文件
            upload: 是否上传到 R2
            cleanup_day: 清理多少天前的本地备份

        Returns:
            备份结果统计
        """
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        result = {
            "timestamp": timestamp,
            "status": "pending",
            "local_file": None,
            "file_size_mb": 0,
            "r2_url": None,
            "error": None,
        }

        try:
            # 1. 执行 pg_dump
            logger.info("[PG备份] 开始执行 pg_dump...")
            dump_file = await self._pg_dump(timestamp)

            if compress:
                # 2. 压缩备份文件
                logger.info(f"[PG备份] 压缩备份文件: {dump_file}")
                compressed_file = await self._compress(dump_file)
                # 删除未压缩文件
                dump_file.unlink(missing_ok=True)
                final_file = compressed_file
            else:
                final_file = dump_file

            # 获取文件大小
            file_size = final_file.stat().st_size
            result["local_file"] = str(final_file)
            result["file_size_mb"] = round(file_size / 1024 / 1024, 2)

            # 3. 上传到 R2
            if upload:
                logger.info("[PG备份] 上传到 Cloudflare R2...")
                r2_url = await self._upload_to_r2(final_file, timestamp)
                result["r2_url"] = r2_url

            # 4. 清理过期本地备份
            if cleanup_day > 0:  # noqa: F821
                logger.info(f"[PG备份] 清理 {cleanup_days} 天前的本地备份...")
                cleaned = await self._cleanup_local(cleanup_days)
                result["cleaned_files"] = cleaned

            result["status"] = "success"
            logger.info(f"[PG备份] 备份完成: {result['file_size_mb']} MB")

        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)
            logger.error(f"[PG备份] 备份失败: {e}")

        return result

    async def _pg_dump(self, timestamp: str) -> Path:
        """执行 pg_dump 导出"""
        output_file = self.output_dir / f"quant_agent_{timestamp}.sql"

        # 解析 DATABASE_URL
        if not self.database_url:
            raise ValueError("DATABASE_URL 未配置")

        # 构建 pg_dump 命令
        # 使用 --no-owner --no-privileges 确保跨环境兼容性
        cmd = [
            "pg_dump",
            "--no-owner",
            "--no-privileges",
            "--verbose",
            f"--file={output_file}",
            self.database_url,
        ]

        logger.debug(f"[PG备份] 执行命令: {' '.join(cmd)}")

        # 执行 pg_dump（在线程池中运行，避免阻塞事件循环）
        def _run_pg_dump():
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=3600,  # 1 小时超时
            )
            if result.returncode != 0:
                raise RuntimeError(f"pg_dump 失败: {result.stderr}")
            return result.stdout

        stdout = await asyncio.to_thread(_run_pg_dump)
        logger.debug(f"[PG备份] pg_dump 输出: {stdout[:500]}")

        return output_file

    async def _compress(self, input_file: Path) -> Path:
        """压缩备份文件"""
        output_file = input_file.with_suffix(".sql.gz")

        def _compress_file():
            with open(input_file, "rb") as f_in:
                with gzip.open(output_file, "wb", compresslevel=6) as f_out:
                    shutil.copyfileobj(f_in, f_out)

        await asyncio.to_thread(_compress_file)
        return output_file

    async def _upload_to_r2(self, file_path: Path, timestamp: str) -> str:
        """上传备份文件到 Cloudflare R2"""
        if not all([self.r2_endpoint, self.r2_access_key, self.r2_secret_key, self.r2_bucket]):  # noqa: E501
            raise ValueError("R2 配置不完整，请检查 R2_ENDPOINT/R2_ACCESS_KEY/R2_SECRET_KEY/R2_BUCKET")  # noqa: E501

        # 构建对象键
        object_key = f"{self.r2_prefix}/{timestamp}/{file_path.name}"

        # 使用 boto3 上传
        try:
            import boto3
            from botocore.config import Config

            s3_client = boto3.client(
                "s3",
                endpoint_url=self.r2_endpoint,
                aws_access_key_id=self.r2_access_key,
                aws_secret_access_key=self.r2_secret_key,
                config=Config(signature_version="s3v4"),
            )

            def _upload():
                s3_client.upload_file(
                    str(file_path),
                    self.r2_bucket,
                    object_key,
                    ExtraArgs={"ContentType": "application/gzip"},
                )

            await asyncio.to_thread(_upload)

            # 构建访问 URL
            r2_url = f"{self.r2_endpoint}/{self.r2_bucket}/{object_key}"
            logger.info(f"[PG备份] 上传成功: {r2_url}")
            return r2_url

        except ImportError:
            raise RuntimeError("需要安装 boto3: pip install boto3")

    async def _cleanup_local(self, days: int) -> int:
        """清理过期的本地备份文件"""
        cutoff = datetime.now() - timedelta(days=days)
        cleaned = 0

        for file in self.output_dir.glob("quant_agent_*.sql*"):
            if file.stat().st_mtime < cutoff.timestamp():
                logger.info(f"[PG备份] 删除过期备份: {file.name}")
                file.unlink()
                cleaned += 1

        return cleaned

    async def restore(
        self,
        backup_file: str,
        target_db: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        从备份文件恢复数据库

        ⚠️ 警告：此操作会覆盖目标数据库！

        Args:
            backup_file: 备份文件路径（支持 .sql 和 .sql.gz）
            target_db: 目标数据库 URL（默认使用 DATABASE_URL）

        Returns:
            恢复结果
        """
        target_url = target_db or self.database_url
        if not target_url:
            raise ValueError("目标数据库 URL 未配置")

        result = {
            "backup_file": backup_file,
            "status": "pending",
            "error": None,
        }

        try:
            backup_path = Path(backup_file)
            if not backup_path.exists():
                raise FileNotFoundError(f"备份文件不存在: {backup_file}")

            # 如果是压缩文件，先解压
            if backup_path.suffix == ".gz":
                logger.info("[PG恢复] 解压备份文件...")
                sql_file = backup_path.with_suffix("")

                def _decompress():
                    with gzip.open(backup_path, "rb") as f_in:
                        with open(sql_file, "wb") as f_out:
                            shutil.copyfileobj(f_in, f_out)

                await asyncio.to_thread(_decompress)
            else:
                sql_file = backup_path

            # 执行 psql 恢复
            logger.info(f"[PG恢复] 开始恢复到 {target_url[:30]}...")
            cmd = [
                "psql",
                "--verbose",
                f"--dbname={target_url}",
                f"--file={sql_file}",
            ]

            def _run_psql():
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=7200,  # 2 小时超时
                )
                if result.returncode != 0:
                    raise RuntimeError(f"psql 恢复失败: {result.stderr}")
                return result.stdout

            stdout = await asyncio.to_thread(_run_psql)

            result["status"] = "success"
            result["output"] = stdout[:1000]
            logger.info("[PG恢复] 恢复完成")

        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)
            logger.error(f"[PG恢复] 恢复失败: {e}")

        return result


# ── CLI 入口 ──────────────────────────────────────────────────────

async def main():
    """命令行入口"""
    import argparse

    parser = argparse.ArgumentParser(description="PostgreSQL 备份管理工具")
    parser.add_argument("--output", "-o", default="/tmp/pg_backup", help="备份输出目录")
    parser.add_argument("--upload", action="store_true", help="上传到 Cloudflare R2")
    parser.add_argument("--no-compress", action="store_true", help="不压缩备份文件")
    parser.add_argument("--cleanup-days", type=int, default=7, help="清理多少天前的本地备份（0=不清理）")  # noqa: E501
    parser.add_argument("--restore", help="从备份文件恢复数据库")

    args = parser.parse_args()

    backup_mgr = PostgresBackup(output_dir=args.output)

    if args.restore:
        result = await backup_mgr.restore(args.restore)
    else:
        result = await backup_mgr.backup(
            compress=not args.no_compress,
            upload=args.upload,
            cleanup_days=args.cleanup_days,
        )

    import json
    print(json.dumps(result, indent=2, ensure_ascii=False))

    # 返回退出码
    if result["status"] != "success":
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
