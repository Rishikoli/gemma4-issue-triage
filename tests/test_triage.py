"""Self-contained checks (no competition data): a tiny code graph and a fake workspace."""
import json
import tempfile
from pathlib import Path

from triage.build_graph import build_graph
from triage.graph import CodeGraph, node_module, path_to_module
from triage.orchestrate import triage
from triage.report import confidence
from triage.trace import opened_modules


def tiny_graph(tmp: Path) -> CodeGraph:
    g = {"nodes": [{"name": "pkg.parser.parse_header", "text": "def parse_header(value): split charset"},
                   {"name": "pkg.client.Client", "text": "class Client: ..."},
                   {"name": "pkg.client.Client.send", "text": "def send(self): retry timeout"},
                   {"name": "tests.test_parser.test_parse_header", "text": "def test_parse_header(): ..."}],
         "edges": [{"type": "calls", "source": "tests.test_parser.test_parse_header", "target": "pkg.parser.parse_header"}]}
    (tmp / "g.json").write_text(json.dumps(g))
    return CodeGraph.load(tmp / "g.json")


def test_module_mapping():
    assert path_to_module("src/requests/utils.py") == "requests.utils"
    assert path_to_module("rich/__init__.py") == "rich"
    assert node_module("pkg.mod.Class.method", {"pkg.mod.Class", "pkg.mod.Class.method"}) == "pkg.mod"


def test_confidence_levels():
    assert confidence("a", ["a", "b"]) == "HIGH"
    assert confidence("b", ["a", "b", "c"]) == "MEDIUM"
    assert confidence("z", ["a", "b", "c"]) == "LOW"
    assert confidence(None, ["a"]) == "LOW"


def test_end_to_end_without_agent_report():
    with tempfile.TemporaryDirectory() as d:
        ws = Path(d)
        graph = tiny_graph(ws)
        (ws / "TRIAGE").mkdir()
        (ws / "TRIAGE" / "repro.py").write_text("assert 1 == 2, 'charset is parsed wrongly'\n")
        report, info = triage(ws, "parse_header splits the charset wrongly", graph)
        assert info["suspects"][0] == "pkg.parser"          # falls back to retrieval
        assert info["confidence"] == "LOW"                  # no agent location → never HIGH
        assert info["tests"] == ["tests.test_parser"]       # found through the call edge
        assert info["reproduction"] == "REPRODUCED"         # the script fails on the current code
        assert "## Tests to run" in report


def test_build_graph_follows_reexports():
    with tempfile.TemporaryDirectory() as d:
        repo = Path(d)
        (repo / "src" / "pkg").mkdir(parents=True)
        (repo / "tests").mkdir()
        (repo / "src" / "pkg" / "__init__.py").write_text("from .parser import parse_header\n")
        (repo / "src" / "pkg" / "parser.py").write_text(
            "def split(v):\n    return v.split(';')\n\n"
            "def parse_header(v):\n    return split(v)\n")
        (repo / "tests" / "test_parser.py").write_text(
            "from pkg import parse_header\n\ndef test_it():\n    assert parse_header('a;b')\n")
        (repo / "g.json").write_text(json.dumps(build_graph(repo, "pkg")))
        g = CodeGraph.load(repo / "g.json")
        assert ("pkg.parser.parse_header", "pkg.parser.split") in g.edges          # same-module call
        assert ("tests.test_parser.test_it", "pkg.parser.parse_header") in g.edges  # through the package re-export
        assert g.test_modules_calling({"pkg.parser"}) == ["tests.test_parser"]


def test_fallback_to_opened_files():
    calls = [("write_file", "/workspace/TRIAGE/repro.py"), ("read_file", "/workspace/tests/test_client.py"),
             ("read_file", "/workspace/src/pkg/client.py"), ("read_file", "pkg/parser.py"),
             ("read_file", "/workspace/src/pkg/client.py")]
    trace = {"steps": [{"source": "agent", "tool_calls": [{"function_name": f, "arguments": {"filepath": p}}]}
                       for f, p in calls]}
    assert opened_modules(trace) == ["pkg.client", "pkg.parser"]   # no notes, no tests, no repeats
    with tempfile.TemporaryDirectory() as d:
        ws = Path(d)
        _, info = triage(ws, "parse_header splits the charset wrongly", tiny_graph(ws),
                         opened_files=opened_modules(trace), run_repro=False)
        assert info["suspects"][:2] == ["pkg.client", "pkg.parser"]
        assert info["confidence"] == "LOW"                  # retrieval ranks pkg.parser first
        _, info = triage(ws, "Client.send ignores the retry timeout", tiny_graph(ws),
                         opened_files=opened_modules(trace), run_repro=False)
        assert info["confidence"] == "HIGH"                 # what the agent opened first agrees with retrieval
