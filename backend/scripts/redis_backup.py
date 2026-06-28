#!/usr/bin/env python3
"""
Redis RDB 备份脚本
OPS-04: Redis AOF 持久化 + 每日自动 RDB 备份到 Cloudflare R2

用法:
    python backend/scripts/redis_backup.py [--upload]

功能:
    1. 触发 Redis BGSAVE 生成 RDB 快照
    2. 等待 BGSAVE 完成
    3. 压缩 RDB 文件
    4. (可选) 上传到 Cloudflare R2
"""

import argparse
import gzip
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# ─── 配置 ──────────────────────────────────────────────────────────
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "quant_redis_secret_2026")
REDIS_DATA_DIR = os.getenv("REDIS_DATA_DIR", "/tmp/redis_data")
BACKUP_DIR = Path(os.getenv("BACKUP_DIR", "./data/backups/redis"))
R2_BUCKET = os.getenv("R2_BUCKET", "quant-agent-backups")
R2_ENDPOINT = os.getenv("R2_ENDPOINT", "")
R2_ACCESS_KEY = os.getenv("R2_ACCESS_KEY_ID", "")
R2_SECRET_KEY = os.getenv("R2_SECRET_ACCESS_KEY", "")


def redis_cli(*args: str) -> str:
    """执行 redis-cli 命令"""
    cmd = ["redis-cli", "-h", REDIS_HOST, "-p", str(REDIS_PORT)]
    if REDIS_PASSWORD:
        cmd.extend(["-a", REDIS_PASSWORD])
    cmd.extend(args)

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(f"redis-cli 失败: {result.stderr.strip()}")
    return result.stdout.strip()


def trigger_bgsave() -> None:
    """触发 Redis BGSAVE"""
    print("[1/4] 触发 BGSAVE...")
    response = redis_cli("BGSAVE")
    print(f"  Redis 响应: {response}")


def wait_for_bgsave(timeout: int = 120) -> None:
    """等待 BGSAVE 完成"""
    print("[2/4] 等待 BGSAVE 完成...")
    start = time.time()

    while time.time() - start < timeout:
        info = redis_cli("INFO", "persistence")
        for line in info.split("\n"):
            if line.startswith("rdb_bgsave_in_progress:"):
                if line.strip().endswith("0"):
                    elapsed = time.time() - start
                    print(f"  BGSAVE 完成 ({elapsed:.1f}s)")
                    return
        time.sleep(1)

    raise TimeoutError(f"BGSAVE 超时 ({timeout}s)")


def compress_backup() -> Path:
    """压缩 RDB 文件"""
    print("[3/4] 压缩备份...")

    # 找到 RDB 文件
    rdb_path = None
    info = redis_cli("INFO", "server")
    for line in info.split("\n"):
        if line.startswith("config_file:"):
            config = line.split(":", 1)[1].strip()
            if config and config != "":
                rdb_dir = os.path.dirname(config)
                rdb_path = os.path.join(rdb_dir, "dump.rdb")

    # 如果找不到，尝试常见路径
    if not rdb_path or not os.path.exists(rdb_path):
        for candidate in [
            os.path.join(REDIS_DATA_DIR, "dump.rdb"),
            "/data/dump.rdb",
            "/tmp/redis_data/dump.rdb",
        ]:
            if os.path.exists(candidate):
                rdb_path = candidate
                break

    if not rdb_path or not os.path.exists(rdb_path):
        # 尝试通过 Docker 复制
        print("  尝试从 Docker 容器复制 RDB...")
        docker_rdb = Path(BACKUP_DIR) / "dump.rdb"
        docker_rdb.parent.mkdir(parents=True, exist_ok=True)

        result = subprocess.run(
            ["docker", "cp", "quant_redis:/data/dump.rdb", str(docker_rdb)],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            rdb_path = str(docker_rdb)
        else:
            raise FileNotFoundError("无法找到 Redis RDB 文件")

    # 压缩
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    backup_name = f"redis_rdb_{timestamp}.rdb.gz"
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backup_path = BACKUP_DIR / backup_name

    rdb_size = os.path.getsize(rdb_path)
    print(f"  RDB 大小: {rdb_size / 1024 / 1024:.2f} MB")

    with open(rdb_path, "rb") as f_in:
        with gzip.open(backup_path, "wb", compresslevel=6) as f_out:
            shutil.copyfileobj(f_in, f_out)

    gz_size = os.path.getsize(backup_path)
    ratio = (1 - gz_size / rdb_size) * 100 if rdb_size > 0 else 0
    print(f"  压缩后: {gz_size / 1024 / 1024:.2f} MB (压缩率 {ratio:.1f}%)")
    print(f"  保存至: {backup_path}")

    return backup_path


def upload_to_r2(backup_path: Path) -> None:
    """上传到 Cloudflare R2"""
    print("[4/4] 上传到 Cloudflare R2...")

    if not R2_ACCESS_KEY or not R2_SECRET_KEY or not R2_ENDPOINT:
        print("  ⚠️ R2 凭证未配置，跳过上传")
        print("  设置环境变量: R2_ENDPOINT, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY")
        return

    try:
        import boto3
        from botocore.config import Config

        s3 = boto3.client(
            "s3",
            endpoint_url=R2_ENDPOINT,
            aws_access_key_id=R2_ACCESS_KEY,
            aws_secret_access_key=R2_SECRET_KEY,
            config=Config(signature_version="s3v4"),
            region_name="auto",
        )

        key = f"redis/{backup_path.name}"
        s3.upload_file(str(backup_path), R2_BUCKET, key)
        print(f"  ✅ 上传成功: s3://{R2_BUCKET}/{key}")
    except ImportError:
        print("  ⚠️ boto3 未安装，跳过上传 (pip install boto3)")
    except Exception as e:
        print(f"  ❌ 上传失败: {e}")
        raise


def cleanup_old_backups(keep_days: int = 30) -> int:
    """清理过期备份"""
    cutoff = time.time() - keep_days * 86400
    removed = 0

    if not BACKUP_DIR.exists():
        return 0

    for f in BACKUP_DIR.glob("redis_rdb_*.rdb.gz"):
        if f.stat().st_mtime < cutoff:
            f.unlink()
            removed += 1

    if removed:
        print(f"  清理 {removed} 个过期备份 (>{keep_days}天)")

    return removed


def main() -> None:
    parser = argparse.ArgumentParser(description="Redis RDB 备份")
    parser.add_argument("--upload", action="store_true", help="上传到 Cloudflare R2")
    parser.add_argument("--cleanup", action="store_true", help="清理过期备份")
    parser.add_argument("--keep-days", type=int, default=30, help="保留天数")
    args = parser.parse_args()

    print(f"{'='*50}")
    print(f"Redis RDB 备份 - {datetime.utcnow().isoformat()}Z")
    print(f"{'='*50}")

    try:
        trigger_bgsave()
        wait_for_bgsave()
        backup_path = compress_backup()

        if args.upload:
            upload_to_r2(backup_path)

        if args.cleanup:
            cleanup_old_backups(args.keep_days)

        print(f"\n✅ 备份完成: {backup_path}")
    except Exception as e:
        print(f"\n❌ 备份失败: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
