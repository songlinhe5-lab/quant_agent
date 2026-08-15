import os
import sys
import traceback

sys.path.insert(0, "/app")
try:
    from dotenv import load_dotenv

    load_dotenv("/app/.env")
    print("env loaded, DATABASE_URL prefix:", os.getenv("DATABASE_URL", "")[:40], flush=True)
    from backend.core.database import engine

    print("db import ok", flush=True)
    print("model import ok", flush=True)
    from sqlalchemy import text

    with engine.connect() as c:
        e = c.execute(
            text("SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = :t)"),
            {"t": "webpage_knowledge_base"},
        ).scalar()
        print("table exists:", e, flush=True)
    print("DIAG_DONE", flush=True)
except Exception:
    traceback.print_exc()
    print("DIAG_FAIL", flush=True)
