#!/usr/bin/env python3
"""
BE-19: 导出 OpenAPI schema 到 docs/openapi.json，供 Swagger / 契约互校。

用法（仓库根目录）:
  python scripts/export_openapi.py
  python scripts/export_openapi.py --check   # 与已有文件 diff，不一致则 exit 1
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# 在 import app 前关掉副作用
os.environ.setdefault("OTEL_ENABLED", "false")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("QUANT_ENV", "testing")
os.environ.setdefault("JWT_SECRET_KEY", "export-openapi-secret")
os.environ.setdefault("ENCRYPTION_MASTER_KEY", "00" * 32)
os.environ.setdefault("BCRYPT_ROUNDS", "4")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OUT_PATH = ROOT / "docs" / "openapi.json"


def _load_schema() -> dict:
    from backend.core.openapi_schema import build_openapi_schema
    from backend.main import app

    # 清缓存，保证导出是最新 enrich 结果
    app.openapi_schema = None
    return build_openapi_schema(app)


def main() -> int:
    parser = argparse.ArgumentParser(description="Export Quant Agent OpenAPI schema")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Compare with docs/openapi.json; fail if out of date",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=OUT_PATH,
        help="Output path (default: docs/openapi.json)",
    )
    args = parser.parse_args()

    schema = _load_schema()
    text = json.dumps(schema, ensure_ascii=False, indent=2) + "\n"

    if args.check:
        if not args.out.exists():
            print(f"[BE-19] missing {args.out}; run without --check to generate", file=sys.stderr)
            return 1
        existing = args.out.read_text(encoding="utf-8")
        if existing != text:
            print(
                f"[BE-19] {args.out} is stale. Run: python scripts/export_openapi.py",
                file=sys.stderr,
            )
            return 1
        ops = sum(
            1
            for p in (schema.get("paths") or {}).values()
            if isinstance(p, dict)
            for m in p
            if m not in ("parameters", "summary", "description", "servers")
        )
        print(f"[BE-19] openapi.json OK ({ops} operations)")
        return 0

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding="utf-8")
    print(f"[BE-19] wrote {args.out} ({len(schema.get('paths') or {})} paths)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
