"""扫描 backend 中「模块级实例化触发反向 import」的潜在循环依赖。

原理：构建有向图，边分两类
  1. import 边：模块 M 导入 N（含函数体内的 import，因为 __init__ 里的 import
     会在实例化时触发）
  2. 实例化边：模块 M 在**模块顶层** `X = SomeClass(...)`，则导入 M 时会执行
     SomeClass 的 __init__ -> 边 M -> SomeClass 所在模块

若图中存在环路且该环路至少包含一条实例化边，则导入 M 时会在运行时触发循环导入
（macro_calendar_service 当年就是这种：legacy_market_data 顶层实例化
MarketDataGateway()，其 __init__ 反向拉入 macro 包）。

仅报告含实例化边的环路（真正的 latent 风险），纯 import 环路另行列出供人工 review。
"""

from __future__ import annotations

import ast
import os
import sys

BACKEND_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend")


def iter_py_files():
    for dirpath, dirnames, filenames in os.walk(BACKEND_ROOT):
        # 跳过非源码 / 测试目录
        dirnames[:] = [d for d in dirnames if d not in ("__pycache__", ".git", "node_modules", "migrations", "tests")]
        for fn in filenames:
            if not fn.endswith(".py"):
                continue
            full = os.path.join(dirpath, fn)
            # 跳过测试文件（test_*.py 或位于 tests 目录）
            if os.sep + "tests" + os.sep in full or fn.startswith("test_"):
                continue
            yield full


def module_name(path: str) -> str:
    rel = os.path.relpath(path, BACKEND_ROOT)[:-3]
    return "backend." + rel.replace(os.sep, ".")


def collect_edges(path: str):
    """返回 (import_edges: set[(src,dst)], instantiate_edges: set[(src,dst)], error)"""
    import_edges = set()
    instantiate_edges = set()
    src = module_name(path)
    try:
        tree = ast.parse(open(path, "r", encoding="utf-8").read(), filename=path)
    except Exception as e:  # noqa: BLE001
        return import_edges, instantiate_edges, str(e)

    # 构建本模块的符号 -> 模块 映射（用于解析顶层 Name 实例化）
    name_to_module = {}

    def visit_imports(node):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("backend"):
            import_edges.add((src, node.module))
            for alias in node.names:
                local = alias.asname or alias.name
                name_to_module[local] = node.module
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("backend"):
                    import_edges.add((src, alias.name))
                    local = alias.asname or alias.name.split(".")[0]
                    name_to_module[local] = alias.name

    for node in ast.walk(tree):
        visit_imports(node)

    # 模块级赋值实例化（仅顶层 Assign，嵌套的不在 import 时触发）
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not isinstance(node.value, ast.Call):
            continue
        func = node.value.func
        # 计算 dotted path
        parts = []
        cur = func
        while isinstance(cur, ast.Attribute):
            parts.append(cur.attr)
            cur = cur.value
        if isinstance(cur, ast.Name):
            parts.append(cur.id)
        else:
            continue
        parts.reverse()
        if len(parts) >= 2:
            mod_candidate = ".".join(parts[:-1])
            if mod_candidate.startswith("backend"):
                instantiate_edges.add((src, mod_candidate))
        else:
            # 单名：用 import 映射解析
            target = name_to_module.get(parts[0])
            if target:
                instantiate_edges.add((src, target))

    return import_edges, instantiate_edges, None


def tarjan_scc(nodes, adj):
    index_counter = [0]
    stack = []
    lowlink = {}
    index = {}
    on_stack = {}
    result = []

    def strongconnect(v):
        index[v] = index_counter[0]
        lowlink[v] = index_counter[0]
        index_counter[0] += 1
        stack.append(v)
        on_stack[v] = True
        for w in adj.get(v, ()):
            if w not in index:
                strongconnect(w)
                lowlink[v] = min(lowlink[v], lowlink[w])
            elif on_stack.get(w):
                lowlink[v] = min(lowlink[v], index[w])
        if lowlink[v] == index[v]:
            comp = []
            while True:
                w = stack.pop()
                on_stack[w] = False
                comp.append(w)
                if w == v:
                    break
            result.append(comp)

    for v in nodes:
        if v not in index:
            strongconnect(v)
    return result


def main():
    all_import = set()
    all_inst = set()
    errors = []
    for path in iter_py_files():
        if "/tests/" in path or path.endswith(os.sep + "tests") or os.sep + "tests" + os.sep in path:
            # 仅扫描生产代码
            continue
        ie, inst, err = collect_edges(path)
        if err:
            errors.append((path, err))
        all_import |= ie
        all_inst |= inst

    nodes = set()
    for a, b in all_import | all_inst:
        nodes.add(a)
        nodes.add(b)
    adj = {n: set() for n in nodes}
    for a, b in all_import | all_inst:
        adj[a].add(b)

    sccs = tarjan_scc(nodes, adj)
    risky = []
    pure = []
    for comp in sccs:
        if len(comp) < 2:
            continue
        comp_set = set(comp)
        has_inst = any((a, b) in all_inst and a in comp_set and b in comp_set for (a, b) in all_inst)
        if has_inst:
            risky.append(comp)
        else:
            pure.append(comp)

    print("=" * 70)
    print("Circular-import scan (backend, production code only)")
    print("=" * 70)
    print(f"modules scanned: {len(nodes)} | import edges: {len(all_import)} | instantiate edges: {len(all_inst)}")
    if errors:
        print(f"\n[!] {len(errors)} files failed to parse:")
        for p, e in errors[:10]:
            print(f"    {p}: {e}")

    if not risky and not pure:
        print("\n✅ No circular imports detected.")
        return 0

    if risky:
        print(f"\n🔴 HIGH ({len(risky)} SCC): latent circular import via module-level instantiation")
        for comp in risky:
            print("   cycle:", " -> ".join(sorted(comp)))
            for a, b in all_inst:
                if a in comp and b in comp:
                    print(f"      instantiate edge: {a} -> {b}")
    if pure:
        print(f"\n🟡 REVIEW ({len(pure)} SCC): pure import cycle (no instantiation edge)")
        for comp in pure:
            print("   cycle:", " -> ".join(sorted(comp)))

    return 1 if risky else 0


if __name__ == "__main__":
    sys.exit(main())
