"""Code graph helpers: load a repository's call graph and map functions/classes to their modules.

The graph is the competition's JSON format: {"nodes": [{"name": "pkg.mod.Class.method", "text": "..."}],
"edges": [{"type": "calls", "source": ..., "target": ...}]}. Modules are not nodes, so a node's module is
the longest proper prefix of its name that is not itself a node.
"""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path


def is_test_module(module: str) -> bool:
    parts = module.split(".")
    return parts[0] in ("tests", "test", "testing") or parts[-1].startswith("test_") or parts[-1] == "conftest"


def node_module(name: str, nodes: set[str]) -> str:
    parts = name.split(".")
    for i in range(len(parts) - 1, 0, -1):
        prefix = ".".join(parts[:i])
        if prefix not in nodes:
            return prefix
    return parts[0]


def path_to_module(path: str) -> str | None:
    """'rich/style.py' -> 'rich.style'; 'src/requests/__init__.py' -> 'requests'."""
    path = path.strip().lstrip("/").removeprefix("workspace/")
    if not path.endswith(".py"):
        return None
    parts = path[:-3].split("/")
    if parts and parts[0] == "src":
        parts = parts[1:]
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts) or None


@dataclass
class CodeGraph:
    nodes: dict[str, str]                       # node name -> source text
    edges: list[tuple[str, str]]                # (caller, callee) "calls" edges between known nodes
    module_of: dict[str, str] = field(default_factory=dict)

    @classmethod
    def load(cls, path: str | Path) -> "CodeGraph":
        g = json.loads(Path(path).read_text())
        nodes = {n["name"]: (n.get("text") or "") for n in g["nodes"]}
        edges = [(e["source"], e["target"]) for e in g["edges"]
                 if e.get("type", "calls") == "calls" and e["source"] in nodes and e["target"] in nodes]
        names = set(nodes)
        return cls(nodes, edges, {n: node_module(n, names) for n in nodes})

    def source_nodes(self) -> list[str]:
        return [n for n in self.nodes if not is_test_module(self.module_of[n])]

    def test_modules_calling(self, modules: set[str]) -> list[str]:
        """Test modules ranked by how many call edges go from their functions into `modules`."""
        c = Counter(self.module_of[s] for s, t in self.edges
                    if is_test_module(self.module_of[s]) and self.module_of[t] in modules)
        return [m for m, _ in c.most_common()]
