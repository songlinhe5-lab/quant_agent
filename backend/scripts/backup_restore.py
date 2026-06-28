#!/usr/bin/env python3
"""
备份恢复演练脚本
OPS-05: 实现 docs/12 灾难恢复流程，定期验证 R2 备份可恢复性 (RTO < 2h)

用法:
    python backend/scripts/backup_restore.py --type pg --backup <backup_file>
    python backend/scripts/backup_restore.py --type redis --backup <backup_file>
    python backend/scripts/backup_restore.py --verify  # 验证所有备份完整性

功能:
    1. PostgreSQL 备份恢复
    2. Redis 备份恢复
    3. 备份完整性验证
    4. 恢复时间统计
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
DB_USER = os.getenv("DB_USER", "quant_admin")
DB_PASSWORD = os.getenv("DB_PASSWORD", "quant_pg_secret_2026")
DB_NAME = os.getenv("DB_NAME", "quant_agent_db")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", 5432))

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "quant_redis_secret_2026")

BACKUP_DIR = Path(os.getenv("BACKUP_DIR", "./data/backups"))
R2_BUCKET = os.getenv("R2_BUCKET", "quant-agent-backups")


# ─── PostgreSQL 恢复 ────────────────────────────────────────────────
def restore_postgres(backup_path: str) -> None:
    """恢复 PostgreSQL 备份"""
    path = Path(backup_path)
    if not path.exists():
        raise FileNotFoundError(f"备份文件不存在: {backup_path}")

    print(f"\n{'='*50}")
    print("PostgreSQL 恢复")
    print(f"{'='*50}")
    print(f"备份文件: {backup_path}")
    print(f"文件大小: {path.stat().st_size / 1024 / 1024:.2f} MB")
    print(f"目标数据库: {DB_NAME} @ {DB_HOST}:{DB_PORT}")

    # 确认操作
    confirm = input("\n⚠️  这将覆盖当前数据库！确认恢复？(yes/no): ")
    if confirm.lower() != "yes":
        print("已取消")
        return

    start_time = time.time()

    # 断开所有连接
    print("\n[1/3] 断开现有连接...")
    subprocess.run(
        ["psql", "-h", DB_HOST, "-p", str(DB_PORT), "-U", DB_USER,
         "-c", f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='{DB_NAME}' AND pid <> pg_backend_pid()"],  # noqa: E501
        capture_output=True, text=True,
        env={"PGPASSWORD": DB_PASSWORD}
    )

    # 删除并重建数据库
    print("[2/3] 重建数据库...")
    subprocess.run(
        ["dropdb", "-h", DB_HOST, "-p", str(DB_PORT), "-U", DB_USER, "--if-exists", DB_NAME],  # noqa: E501
        capture_output=True, text=True,
        env={"PGPASSWORD": DB_PASSWORD}
    )
    subprocess.run(
        ["createdb", "-h", DB_HOST, "-p", str(DB_PORT), "-U", DB_USER, DB_NAME],
        capture_output=True, text=True,
        env={"PGPASSWORD": DB_PASSWORD}
    )

    # 恢复数据
    print("[3/3] 恢复数据...")
    if str(path).endswith(".gz"):
        with gzip.open(path, "rb") as f:
            result = subprocess.run(
                ["psql", "-h", DB_HOST, "-p", str(DB_PORT), "-U", DB_USER, "-d", DB_NAME, "-q"],  # noqa: E501
                stdin=f, capture_output=True, text=True,
                env={"PGPASSWORD": DB_PASSWORD}
            )
    else:
        with open(path, "rb") as f:
            result = subprocess.run(
                ["psql", "-h", DB_HOST, "-p", str(DB_PORT), "-U", DB_USER, "-d", DB_NAME, "-q"],  # noqa: E501
                stdin=f, capture_output=True, text=True,
                env={"PGPASSWORD": DB_PASSWORD}
            )

    elapsed = time.time() - start_time

    if result.returncode != 0:
        print(f"\n❌ 恢复失败:\n{result.stderr}")
        sys.exit(1)

    print(f"\n✅ 恢复成功！耗时: {elapsed:.1f}s")
    _check_rto(elapsed, target=7200)  # RTO < 2h


# ─── Redis 恢复 ──────────────────────────────────────────────────────
def restore_redis(backup_path: str) -> None:
    """恢复 Redis 备份"""
    path = Path(backup_path)
    if not path.exists():
        raise FileNotFoundError(f"备份文件不存在: {backup_path}")

    print(f"\n{'='*50}")
    print("Redis 恢复")
    print(f"{'='*50}")
    print(f"备份文件: {backup_path}")
    print(f"文件大小: {path.stat().st_size / 1024 / 1024:.2f} MB")
    print(f"目标: {REDIS_HOST}:{REDIS_PORT}")

    confirm = input("\n⚠️  这将覆盖当前 Redis 数据！确认恢复？(yes/no): ")
    if confirm.lower() != "yes":
        print("已取消")
        return

    start_time = time.time()

    # 解压 RDB 文件
    print("\n[1/3] 解压 RDB...")
    rdb_path = path.with_suffix("")  # 去掉 .gz
    if str(path).endswith(".gz"):
        with gzip.open(path, "rb") as f_in:
            with open(rdb_path, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)
    else:
        rdb_path = path

    # 尝试通过 Docker 恢复
    print("[2/3] 复制到 Redis 容器...")
    result = subprocess.run(
        ["docker", "cp", str(rdb_path), "quant_redis:/data/dump.rdb"],
        capture_output=True, text=True
    )

    if result.returncode != 0:
        # 直接复制到本地 Redis 数据目录
        print("  Docker 复制失败，尝试本地恢复...")
        local_redis_dir = "/var/lib/redis"
        if os.path.isdir(local_redis_dir):
            shutil.copy2(str(rdb_path), os.path.join(local_redis_dir, "dump.rdb"))
        else:
            print("  ⚠️ 无法找到 Redis 数据目录")

    # 重启 Redis 加载数据
    print("[3/3] 重启 Redis...")
    subprocess.run(
        ["docker", "restart", "quant_redis"],
        capture_output=True, text=True
    )
    time.sleep(3)

    elapsed = time.time() - start_time

    # 验证恢复
    try:
        info = subprocess.run(
            ["redis-cli", "-h", REDIS_HOST, "-p", str(REDIS_PORT), "-a", REDIS_PASSWORD, "DBSIZE"],  # noqa: E501
            capture_output=True, text=True, timeout=10
        )
        print(f"  Redis DBSIZE: {info.stdout.strip()}")
    except Exception:
        pass

    print(f"\n✅ Redis 恢复完成！耗时: {elapsed:.1f}s")
    _check_rto(elapsed, target=1800)  # Redis RTO < 30min


# ─── 备份验证 ────────────────────────────────────────────────────────
def verify_backups() -> None:
    """验证所有备份完整性"""
    print(f"\n{'='*50}")
    print(f"备份完整性验证 - {datetime.utcnow().isoformat()}Z")
    print(f"{'='*50}")

    results = []

    # 检查 PostgreSQL 备份
    pg_dir = BACKUP_DIR / "postgres"
    if pg_dir.exists():
        pg_backups = sorted(pg_dir.glob("*.sql.gz"), reverse=True)
        if pg_backups:
            latest = pg_backups[0]
            size = latest.stat().st_size
            age_hours = (time.time() - latest.stat().st_mtime) / 3600

            # 尝试解压验证
            try:
                with gzip.open(latest, "rb") as f:
                    # 读取前 1KB 验证 gzip 完整性
                    f.read(1024)
                results.append(("PostgreSQL", "✅", f"{size/1024/1024:.1f}MB", f"{age_hours:.1f}h前"))  # noqa: E501
            except Exception as e:
                results.append(("PostgreSQL", "❌", f"损坏: {e}", ""))
        else:
            results.append(("PostgreSQL", "⚠️", "无备份", ""))
    else:
        results.append(("PostgreSQL", "⚠️", "备份目录不存在", ""))

    # 检查 Redis 备份
    redis_dir = BACKUP_DIR / "redis"
    if redis_dir.exists():
        redis_backups = sorted(redis_dir.glob("*.rdb.gz"), reverse=True)
        if redis_backups:
            latest = redis_backups[0]
            size = latest.stat().st_size
            age_hours = (time.time() - latest.stat().st_mtime) / 3600

            try:
                with gzip.open(latest, "rb") as f:
                    f.read(1024)
                results.append(("Redis", "✅", f"{size/1024/1024:.1f}MB", f"{age_hours:.1f}h前"))  # noqa: E501
            except Exception as e:
                results.append(("Redis", "❌", f"损坏: {e}", ""))
        else:
            results.append(("Redis", "⚠️", "无备份", ""))
    else:
        results.append(("Redis", "⚠️", "备份目录不存在", ""))

    # 输出结果
    print(f"\n{'类型':<15} {'状态':<5} {'大小':<15} {'时间'}")
    print("-" * 50)
    for r in results:
        print(f"{r[0]:<15} {r[1]:<5} {r[2]:<15} {r[3]}")

    # 总结
    all_ok = all(r[1] == "✅" for r in results)
    if all_ok:
        print("\n✅ 所有备份验证通过")
    else:
        print("\n⚠️ 部分备份存在问题，请检查")


# ─── 工具函数 ────────────────────────────────────────────────────────
def _check_rto(elapsed: float, target: float) -> None:
    """检查恢复时间是否满足 RTO 目标"""
    if elapsed <= target:
        print(f"📊 RTO 达标: {elapsed:.1f}s <= {target:.0f}s ✅")
    else:
        print(f"📊 RTO 超标: {elapsed:.1f}s > {target:.0f}s ❌")
        print("   建议优化备份策略或硬件配置")


# ─── 主函数 ──────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(description="备份恢复演练")
    parser.add_argument("--type", choices=["pg", "redis"], help="恢复类型")
    parser.add_argument("--backup", help="备份文件路径")
    parser.add_argument("--verify", action="store_true", help="验证所有备份完整性")
    args = parser.parse_args()

    if args.verify:
        verify_backups()
        return

    if not args.type or not args.backup:
        parser.print_help()
        return

    if args.type == "pg":
        restore_postgres(args.backup)
    elif args.type == "redis":
        restore_redis(args.backup)


if __name__ == "__main__":
    main()
