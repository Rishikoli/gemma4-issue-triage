"""Build a code graph for any Python repository with the standard library's `ast`, in the same JSON
format as the competition's graphs, so the triage pipeline doesn't depend on a precomputed graph.

Nodes are classes and functions (methods and nested classes included), named by dotted path
(`pkg.module.Class.method`) with their source text. "calls" edges go from each class to its members
and from each function to what it calls, resolved through imports, `self.`/`cls.` and same-module
names; a call on an unknown object falls back to the few definitions sharing that method name.

Usage:
    python -m triage.build_graph /path/to/repo --out repo_graph.json [--name repo_name]
"""
from __future__ import annotations

import argparse
import ast
import json
from collections import defaultdict
from pathlib import Path

from .graph import path_to_module

SKIP_DIRS = {".git", ".hg", ".tox", ".nox", ".venv", "venv", "env", "build", "dist", "node_modules",
             "__pycache__", "site-packages", ".eggs", ".mypy_cache", ".pytest_cache"}
MAX_FALLBACK = 3  # link an unresolved obj.method() call only if at most this many definitions share the name


def python_files(root: Path) -> list[Path]:
    out = []
    for p in sorted(root.rglob("*.py")):
        rel = p.relative_to(root)
        if not any(part in SKIP_DIRS or (part.startswith(".") and part != ".") for part in rel.parts[:-1]):
            out.append(p)
    return out


class _Module:
    """One parsed file: its definitions, its imports, and the calls inside each definition."""

    def __init__(self, name: str, path: Path, source: str, tree: ast.Module):
        self.name, self.path, self.source = name, path, source
        self.package = name if path.name == "__init__.py" else name.rpartition(".")[0]
        self.defs: dict[str, ast.AST] = {}          # dotted name -> node
        self.imports: dict[str, str] = {}           # local alias -> dotted target
        self._collect(tree.body, name)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    self.imports[a.asname or a.name.split(".")[0]] = a.name if a.asname else a.name.split(".")[0]
            elif isinstance(node, ast.ImportFrom):
                base = self._absolute(node.module, node.level)
                for a in node.names:
                    if a.name != "*":
                        self.imports[a.asname or a.name] = f"{base}.{a.name}" if base else a.name

    def _absolute(self, module: str | None, level: int) -> str:
        if not level:
            return module or ""
        parts = self.package.split(".") if self.package else []
        base = parts[: len(parts) - (level - 1)] if level > 1 else parts
        return ".".join(base + ([module] if module else []))

    def _collect(self, body: list[ast.stmt], prefix: str) -> None:
        for node in body:
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                name = f"{prefix}.{node.name}"
                self.defs[name] = node
                if isinstance(node, ast.ClassDef):
                    self._collect(node.body, name)


def _call_targets(fn: ast.AST) -> list[tuple[str, str | None]]:
    """(kind, name) for each call in a function body: ("name", f), ("self", m), ("attr", "x.m") or ("method", m)."""
    out = []
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if isinstance(f, ast.Name):
            out.append(("name", f.id))
        elif isinstance(f, ast.Attribute):
            if isinstance(f.value, ast.Name) and f.value.id in ("self", "cls"):
                out.append(("self", f.attr))
            elif isinstance(f.value, ast.Name):
                out.append(("attr", f"{f.value.id}.{f.attr}"))
            else:
                out.append(("method", f.attr))
    return out


def build_graph(root: str | Path, repo_name: str | None = None) -> dict:
    root = Path(root)
    modules: list[_Module] = []
    for p in python_files(root):
        name = path_to_module(str(p.relative_to(root)))
        if not name:
            continue
        try:
            source = p.read_text(encoding="utf-8", errors="replace")
            modules.append(_Module(name, p, source, ast.parse(source)))
        except (SyntaxError, ValueError):
            continue
    nodes: dict[str, str] = {}
    for m in modules:
        for name, node in m.defs.items():
            nodes.setdefault(name, ast.get_source_segment(m.source, node) or "")
    by_short = defaultdict(list)
    for name in nodes:
        by_short[name.rsplit(".", 1)[-1]].append(name)
    by_module = {m.name: m for m in modules}

    def resolve(dotted: str | None, hops: int = 0) -> str | None:
        """A dotted name to the definition it denotes, following re-exports such as
        `from .sessions import Session` in a package's __init__."""
        if not dotted or dotted in nodes:
            return dotted
        if hops > 4:
            return None
        parts = dotted.split(".")
        for i in range(len(parts) - 1, 0, -1):
            mod = by_module.get(".".join(parts[:i]))
            if mod and parts[i] in mod.imports:
                return resolve(".".join([mod.imports[parts[i]], *parts[i + 1:]]), hops + 1)
        return None

    edges: set[tuple[str, str]] = set()
    for m in modules:
        for name, node in m.defs.items():
            if isinstance(node, ast.ClassDef):  # a class reaches its members
                edges.update((name, f"{name}.{c.name}") for c in node.body
                             if isinstance(c, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)))
                continue
            owner = name.rpartition(".")[0]
            for kind, target in _call_targets(node):
                hits: list[str] = []
                if kind == "name":
                    cand = resolve(m.imports.get(target)) or (f"{m.name}.{target}" if f"{m.name}.{target}" in nodes else None)
                    hits = [cand] if cand in nodes else []
                elif kind == "self":
                    cand = f"{owner}.{target}"
                    hits = [cand] if cand in nodes else [c for c in by_short.get(target, []) if c.startswith(owner.rpartition(".")[0])][:1]
                elif kind == "attr":
                    head, attr = target.split(".", 1)
                    base = m.imports.get(head) or (f"{m.name}.{head}" if f"{m.name}.{head}" in nodes else None)
                    cand = resolve(f"{base}.{attr}") if base else None
                    if cand in nodes:
                        hits = [cand]
                    elif len(by_short.get(attr, [])) <= MAX_FALLBACK:
                        hits = by_short.get(attr, [])
                elif kind == "method" and len(by_short.get(target, [])) <= MAX_FALLBACK:
                    hits = by_short.get(target, [])
                edges.update((name, h) for h in hits if h != name)

    return {"directed": True, "multigraph": True, "graph": {"repo_name": repo_name or root.name},
            "nodes": [{"id": n, "name": n, "text": t} for n, t in nodes.items()],
            "edges": [{"type": "calls", "source": s, "target": t, "key": 0} for s, t in sorted(edges)]}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("repo", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--name", help="repo name stored in the graph (default: the folder name)")
    args = ap.parse_args()
    g = build_graph(args.repo, args.name)
    args.out.write_text(json.dumps(g))
    print(f"{args.out}: {len(g['nodes'])} nodes, {len(g['edges'])} edges")


if __name__ == "__main__":
    main()
