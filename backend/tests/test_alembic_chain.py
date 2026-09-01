"""
迁移链完整性（防回归）
======================

历史上出过两类故障，都会让 `alembic upgrade head` 直接不可用：
  1. 三个 `down_revision = None` 的独立头（多 head）
  2. `down_revision` 写成了**文件名**而不是 revision id（悬空父版本）

本测试用 `ast` 静态解析版本文件（不 import，因此不依赖安装 alembic），锁住：
  - revision id 唯一且与文件一一对应
  - 有且仅有一个 root（链根）
  - 每个 down_revision 都指向真实存在的 revision
  - 有且仅有一个 head（链尾）
"""

import ast
from pathlib import Path
from typing import Any, Dict, Tuple

VERSIONS_DIR = Path(__file__).resolve().parents[1] / "alembic" / "versions"

_FIELDS = ("revision", "down_revision")


def _literal(node: ast.AST | None) -> Any:
    if node is None:
        return None
    return ast.literal_eval(node)


def _load_revisions() -> Dict[str, Tuple[Any, str]]:
    """{revision_id: (down_revision, 文件名)}"""
    revisions: Dict[str, Tuple[Any, str]] = {}
    for path in sorted(VERSIONS_DIR.glob("*.py")):
        if path.name.startswith("_"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        values: Dict[str, Any] = {}
        for node in tree.body:
            if isinstance(node, ast.Assign):
                targets, value = node.targets, node.value
            elif isinstance(node, ast.AnnAssign):
                targets, value = [node.target], node.value
            else:
                continue
            for target in targets:
                if isinstance(target, ast.Name) and target.id in _FIELDS:
                    values[target.id] = _literal(value)
        revision = values.get("revision")
        if revision:
            revisions[revision] = (values.get("down_revision"), path.name)
    return revisions


def _parents(revisions: Dict[str, Tuple[Any, str]]) -> set:
    parents: set = set()
    for down, _ in revisions.values():
        if down is None:
            continue
        parents.update(down) if isinstance(down, (tuple, list)) else parents.add(down)
    return parents


def test_version_files_are_discoverable():
    revisions = _load_revisions()
    assert revisions, "未解析到任何迁移版本文件，测试路径可能失效"


def test_revision_ids_are_unique():
    revisions = _load_revisions()
    files = [p.name for p in VERSIONS_DIR.glob("*.py") if not p.name.startswith("_")]
    assert len(revisions) == len(files), "存在重复的 revision id 或解析失败的文件"


def test_exactly_one_root():
    roots = [rev for rev, (down, _) in _load_revisions().items() if down is None]
    assert len(roots) == 1, f"迁移链必须只有一个 root，当前有 {len(roots)} 个: {roots}"


def test_all_down_revisions_exist():
    revisions = _load_revisions()
    dangling = [
        (rev, down, filename)
        for rev, (down, filename) in revisions.items()
        if down is not None and down not in revisions
    ]
    assert not dangling, f"down_revision 指向不存在的版本（多半写成了文件名）: {dangling}"


def test_exactly_one_head():
    revisions = _load_revisions()
    parents = _parents(revisions)
    heads = sorted(set(revisions) - parents)
    assert len(heads) == 1, f"迁移链必须只有一个 head，当前有 {len(heads)} 个: {heads}"


def test_no_self_reference():
    revisions = _load_revisions()
    assert [rev for rev, (down, _) in revisions.items() if down == rev] == []
