"""
DQ-03a · 数据湖 manifest 纯函数

manifest_hash = sha256(canonical_json(manifest without manifest_hash))
与 docs/15 RunManifest.code_hash / docs/16 同算法族。
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from typing import Any, Dict, List, Optional


def canonical_json(obj: Any) -> str:
    """确定性 JSON：sort_keys + 无多余空白，日期转 ISO。"""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=_json_default)


def _json_default(o: Any) -> str:
    if isinstance(o, (datetime, date)):
        return o.isoformat()
    raise TypeError(f"Object of type {type(o).__name__} is not JSON serializable")


def compute_manifest_hash(manifest: Dict[str, Any]) -> str:
    """计算 manifest 数据指纹（不含 manifest_hash 字段本身）。"""
    payload = {k: v for k, v in manifest.items() if k != "manifest_hash"}
    digest = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    return digest


def build_manifest(
    *,
    snapshot_id: str,
    as_of_date: str,
    files: List[Dict[str, Any]],
    sidecars: Optional[Dict[str, Any]] = None,
    ktypes_included: Optional[List[str]] = None,
    engine_version: str = "quant-agent@dev",
    status: str = "published",
    quality_gate: Optional[Dict[str, Any]] = None,
    created_at: Optional[str] = None,
    source_sync_lock: Optional[str] = None,
) -> Dict[str, Any]:
    """构造完整 manifest（含 manifest_hash）。"""
    total_bytes = sum(int(f.get("bytes", 0) or 0) for f in files)
    ticker_count = len({f.get("path", "").split("/")[-1].replace(".parquet", "") for f in files})
    body: Dict[str, Any] = {
        "snapshot_id": snapshot_id,
        "as_of_date": as_of_date,
        "created_at": created_at or datetime.utcnow().isoformat() + "Z",
        "status": status,
        "engine_version": engine_version,
        "ktypes_included": ktypes_included or ["K_DAY"],
        "ticker_count": ticker_count,
        "total_bytes": total_bytes,
        "files": files,
        "sidecars": sidecars or {"universe": None, "pit_store": None},
        "quality_gate": quality_gate or {"passed": True, "dirty_rate_max": 0.02, "sources_checked": []},
    }
    if source_sync_lock:
        body["source_sync_lock"] = source_sync_lock
    body["manifest_hash"] = compute_manifest_hash(body)
    return body


def validate_manifest(manifest: Dict[str, Any]) -> bool:
    """校验 manifest_hash 与内容一致；缺失或错误则 False。"""
    expected = manifest.get("manifest_hash")
    if not expected or not isinstance(expected, str):
        return False
    # 兼容文档中的 "sha256:..." 前缀
    bare = expected.removeprefix("sha256:")
    actual = compute_manifest_hash(manifest)
    return bare == actual
