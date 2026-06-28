"""
BE-17: pgvector 知识库迁移工具

功能：
1. 导出知识库数据（含向量）为 JSONL 格式，支持跨节点迁移
2. 导入知识库数据（支持增量合并与冲突处理）
3. 清理超期旧片段（默认 90 天）
4. 支持通过 Cloudflare R2 中转迁移

使用方式：
    # CLI 导出
    python -m backend.scripts.migrate_knowledge_base export --output ./kb_export.jsonl

    # CLI 导入
    python -m backend.scripts.migrate_knowledge_base import --input ./kb_export.jsonl

    # CLI 清理旧数据
    python -m backend.scripts.migrate_knowledge_base cleanup --days 90

    # Python API
    from backend.scripts.migrate_knowledge_base import KnowledgeBaseMigrator
    migrator = KnowledgeBaseMigrator()
    await migrator.export_to_file("kb_export.jsonl")
    await migrator.import_from_file("kb_export.jsonl")
    await migrator.cleanup_old_fragments(days=90)
"""

import asyncio
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import structlog

# 将项目根目录加入 sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from backend.core import models
from backend.core.database import SessionLocal

logger = structlog.get_logger(__name__)


class KnowledgeBaseMigrator:
    """
    pgvector 知识库迁移工具

    支持两种表：
    1. webpage_knowledge_base - 网页知识库
    2. quant_screener_rules - 选股规则库
    """

    def __init__(self):
        self._tables = {
            "webpage": models.WebpageKnowledgeBase,
            "screener_rule": models.ScreenerRule,
        }

    async def export_to_file(
        self,
        output_path: str,
        table: str = "webpage",
        user_id: Optional[int] = None,
        batch_size: int = 500,
    ) -> Dict[str, Any]:
        """
        导出知识库到 JSONL 文件

        Args:
            output_path: 输出文件路径
            table: 表名 ("webpage" | "screener_rule")
            user_id: 用户 ID（None=导出全部）
            batch_size: 批量读取大小

        Returns:
            导出统计信息
        """
        if table not in self._tables:
            raise ValueError(f"不支持的表: {table}，可选: {list(self._tables.keys())}")

        model_class = self._tables[table]
        exported_count = 0

        # 确保输出目录存在
        output_dir = os.path.dirname(output_path)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)

        logger.info(f"[KB导出] 开始导出 {table} 表到 {output_path}")

        with SessionLocal() as db:
            query = db.query(model_class)
            if user_id is not None:
                query = query.filter(model_class.user_id == user_id)

            # 分批导出
            offset = 0
            with open(output_path, "w", encoding="utf-8") as f:
                while True:
                    batch = query.offset(offset).limit(batch_size).all()
                    if not batch:
                        break

                    for record in batch:
                        data = self._record_to_dict(record, table)
                        f.write(json.dumps(data, ensure_ascii=False) + "\n")
                        exported_count += 1

                    offset += batch_size
                    logger.debug(f"[KB导出] 已导出 {exported_count} 条记录")

        stats = {
            "table": table,
            "output_path": output_path,
            "exported_count": exported_count,
            "exported_at": datetime.now(timezone.utc).isoformat(),
        }

        logger.info(f"[KB导出] 完成: {exported_count} 条记录 → {output_path}")
        return stats

    async def import_from_file(
        self,
        input_path: str,
        table: str = "webpage",
        on_conflict: str = "skip",  # "skip" | "update" | "overwrite"
        batch_size: int = 100,
    ) -> Dict[str, Any]:
        """
        从 JSONL 文件导入知识库

        Args:
            input_path: 输入文件路径
            table: 目标表名
            on_conflict: 冲突处理策略
                - "skip": 跳过已存在的记录
                - "update": 更新已存在的记录
                - "overwrite": 删除旧数据后重新导入
            batch_size: 批量写入大小

        Returns:
            导入统计信息
        """
        if not os.path.exists(input_path):
            raise FileNotFoundError(f"输入文件不存在: {input_path}")

        if table not in self._tables:
            raise ValueError(f"不支持的表: {table}")

        model_class = self._tables[table]
        imported_count = 0
        skipped_count = 0
        error_count = 0

        logger.info(f"[KB导入] 开始从 {input_path} 导入到 {table} 表 (冲突策略: {on_conflict})")  # noqa: E501

        # 如果是 overwrite 模式，先清空目标表
        if on_conflict == "overwrite":
            with SessionLocal() as db:
                if table == "webpage":
                    db.query(model_class).delete()
                else:
                    db.query(model_class).delete()
                db.commit()
            logger.info(f"[KB导入] 已清空 {table} 表（overwrite 模式）")

        with open(input_path, "r", encoding="utf-8") as f:
            batch_records = []

            for line_num, line in enumerate(f, 1):
                try:
                    data = json.loads(line.strip())
                    record = self._dict_to_record(data, table)
                    batch_records.append((data, record))

                    if len(batch_records) >= batch_size:
                        result = await self._batch_insert(batch_records, model_class, table, on_conflict)
                        imported_count += result["inserted"]
                        skipped_count += result["skipped"]
                        error_count += result["errors"]
                        batch_records = []

                except json.JSONDecodeError as e:
                    logger.warning(f"[KB导入] 第 {line_num} 行 JSON 解析失败: {e}")
                    error_count += 1
                except Exception as e:
                    logger.error(f"[KB导入] 第 {line_num} 行处理失败: {e}")
                    error_count += 1

            # 处理剩余记录
            if batch_records:
                result = await self._batch_insert(batch_records, model_class, table, on_conflict)
                imported_count += result["inserted"]
                skipped_count += result["skipped"]
                error_count += result["errors"]

        stats = {
            "table": table,
            "input_path": input_path,
            "imported_count": imported_count,
            "skipped_count": skipped_count,
            "error_count": error_count,
            "imported_at": datetime.now(timezone.utc).isoformat(),
        }

        logger.info(f"[KB导入] 完成: 导入 {imported_count} 条, 跳过 {skipped_count} 条, 错误 {error_count} 条")
        return stats

    async def cleanup_old_fragments(
        self,
        days: int = 90,
        table: str = "webpage",
        user_id: Optional[int] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """
        清理超期旧片段

        Args:
            days: 保留天数（超过此天数的记录将被删除）
            table: 表名
            user_id: 用户 ID（None=清理所有用户）
            dry_run: 仅统计不删除

        Returns:
            清理统计信息
        """
        if table not in self._tables:
            raise ValueError(f"不支持的表: {table}")

        model_class = self._tables[table]
        cutoff_ts = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp())

        with SessionLocal() as db:
            query = db.query(model_class).filter(model_class.timestamp < cutoff_ts)
            if user_id is not None:
                query = query.filter(model_class.user_id == user_id)

            # 统计待删除数量
            count = query.count()

            if dry_run:
                logger.info(f"[KB清理] (Dry Run) 将删除 {count} 条超过 {days} 天的记录")
                return {
                    "table": table,
                    "days": days,
                    "would_delete": count,
                    "dry_run": True,
                }

            # 执行删除
            deleted = query.delete(synchronize_session=False)
            db.commit()

            logger.info(f"[KB清理] 已删除 {deleted} 条超过 {days} 天的记录")

            return {
                "table": table,
                "days": days,
                "deleted_count": deleted,
                "dry_run": False,
                "cleaned_at": datetime.now(timezone.utc).isoformat(),
            }

    async def _batch_insert(
        self,
        batch: List[tuple],
        model_class,
        table: str,
        on_conflict: str,
    ) -> Dict[str, int]:
        """批量插入记录"""
        inserted = 0
        skipped = 0
        errors = 0

        with SessionLocal() as db:
            for data, record in batch:
                try:
                    # 检查是否已存在
                    existing = None
                    if table == "webpage":
                        existing = db.query(model_class).filter(model_class.id == record.id).first()
                    else:
                        existing = db.query(model_class).filter(model_class.id == record.id).first()

                    if existing:
                        if on_conflict == "skip":
                            skipped += 1
                            continue
                        elif on_conflict == "update":
                            # 更新现有记录
                            for key, value in record.__dict__.items():
                                if not key.startswith("_") and key != "id":
                                    setattr(existing, key, value)
                            inserted += 1
                    else:
                        db.add(record)
                        inserted += 1

                except Exception as e:
                    logger.error(f"[KB导入] 插入记录失败: {e}")
                    errors += 1

            db.commit()

        return {"inserted": inserted, "skipped": skipped, "errors": errors}

    def _record_to_dict(self, record, table: str) -> Dict[str, Any]:
        """将 SQLAlchemy 记录转换为可序列化字典"""
        data = {
            "id": record.id,
            "url": record.url if hasattr(record, "url") else "",
            "content": record.content,
            "timestamp": record.timestamp,
            "user_id": record.user_id,
        }

        # 向量需要特殊处理
        if hasattr(record, "embedding") and record.embedding is not None:
            # pgvector 返回的是 list 或 array
            embedding = record.embedding
            if hasattr(embedding, "tolist"):
                embedding = embedding.tolist()
            data["embedding"] = embedding

        return data

    def _dict_to_record(self, data: Dict[str, Any], table: str):
        """将字典转换为 SQLAlchemy 模型实例"""
        model_class = self._tables[table]

        kwargs = {
            "id": data["id"],
            "content": data["content"],
            "timestamp": data["timestamp"],
            "user_id": data.get("user_id"),
        }

        if table == "webpage":
            kwargs["url"] = data.get("url", "")
            if "embedding" in data:
                kwargs["embedding"] = data["embedding"]
        elif table == "screener_rule":
            kwargs["desc_text"] = data.get("desc_text", "")
            kwargs["rule_text"] = data.get("rule_text", "")
            kwargs["rule_type"] = data.get("rule_type")
            if "embedding" in data:
                kwargs["embedding"] = data["embedding"]

        return model_class(**kwargs)


# ── CLI 入口 ──────────────────────────────────────────────────────


async def main():
    """命令行入口"""
    import argparse

    parser = argparse.ArgumentParser(description="pgvector 知识库迁移工具")
    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # export 子命令
    export_parser = subparsers.add_parser("export", help="导出知识库")
    export_parser.add_argument("--output", "-o", required=True, help="输出文件路径")
    export_parser.add_argument("--table", "-t", default="webpage", choices=["webpage", "screener_rule"])  # noqa: E501
    export_parser.add_argument("--user-id", "-u", type=int, help="用户 ID（可选）")

    # import 子命令
    import_parser = subparsers.add_parser("import", help="导入知识库")
    import_parser.add_argument("--input", "-i", required=True, help="输入文件路径")
    import_parser.add_argument("--table", "-t", default="webpage", choices=["webpage", "screener_rule"])  # noqa: E501
    import_parser.add_argument("--on-conflict", default="skip", choices=["skip", "update", "overwrite"])  # noqa: E501

    # cleanup 子命令
    cleanup_parser = subparsers.add_parser("cleanup", help="清理旧数据")
    cleanup_parser.add_argument("--days", "-d", type=int, default=90, help="保留天数")
    cleanup_parser.add_argument("--table", "-t", default="webpage", choices=["webpage", "screener_rule"])  # noqa: E501
    cleanup_parser.add_argument("--user-id", "-u", type=int, help="用户 ID（可选）")
    cleanup_parser.add_argument("--dry-run", action="store_true", help="仅统计不删除")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    migrator = KnowledgeBaseMigrator()

    if args.command == "export":
        result = await migrator.export_to_file(
            output_path=args.output,
            table=args.table,
            user_id=args.user_id,
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))

    elif args.command == "import":
        result = await migrator.import_from_file(
            input_path=args.input,
            table=args.table,
            on_conflict=args.on_conflict,
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))

    elif args.command == "cleanup":
        result = await migrator.cleanup_old_fragments(
            days=args.days,
            table=args.table,
            user_id=args.user_id,
            dry_run=args.dry_run,
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
