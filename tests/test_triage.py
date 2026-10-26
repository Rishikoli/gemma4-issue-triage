"""Self-contained checks (no competition data): a tiny code graph and a fake workspace."""
import json
import tempfile
from pathlib import Path

from triage.graph import CodeGraph, node_module, path_to_module
from triage.orchestrate import triage
from triage.report import confidence


def tiny_graph(tmp: Path) -> CodeGraph:
    g = {"nodes": [{"name": "pkg.parser.parse_header", "text": "def parse_header(value): split charset"},
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
