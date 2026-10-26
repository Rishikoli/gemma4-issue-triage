"""Turn the agents' TRIAGE/ notes into the final report: fallbacks, retrieval, confidence, tests, reproduction.

Usage:
    python -m triage.orchestrate --workspace /path/to/repo --issue issue.md --graph repo_graph.json [--trace trace.json]
writes <workspace>/TRIAGE/final_report.md and prints it.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .graph import CodeGraph
from .report import check_reproduction, confidence, read_agent_files, render
from .retrieval import rank_modules
from .trace import opened_modules


def triage(workspace: Path, issue_text: str, graph: CodeGraph, opened_files: list[str] | None = None,
           run_repro: bool = True) -> tuple[str, dict]:
    findings = read_agent_files(workspace / "TRIAGE")
    retrieval = rank_modules(graph, issue_text)
    if findings.suspects:
        suspects, source = findings.suspects, "agent report"
    elif opened_files:
        suspects, source = opened_files, "files the agent opened (no report written)"
    else:
        suspects, source = retrieval, "retrieval only (agent wrote nothing)"
    # The agent's pick, from its report or what it opened first, against retrieval; retrieval alone is LOW
    conf = confidence(suspects[0] if suspects and retrieval is not suspects else None, retrieval)
    tests = findings.tests + [m for m in (graph.test_modules_calling({suspects[0]}) if suspects else [])
                              if m not in findings.tests]
    status, tail = check_reproduction(workspace) if run_repro else (findings.claimed_repro or "NOT_ATTEMPTED", "")
    title = issue_text.strip().splitlines()[0][:120] if issue_text.strip() else "(untitled issue)"
    report = render(title, suspects, source, conf, retrieval, tests, status, tail, findings)
    return report, {"suspects": suspects, "source": source, "confidence": conf, "tests": tests,
                    "reproduction": status, "retrieval": retrieval[:5]}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workspace", type=Path, required=True, help="repository checkout containing TRIAGE/")
    ap.add_argument("--issue", type=Path, required=True, help="file with the issue text")
    ap.add_argument("--graph", type=Path, required=True, help="the repository's code graph (JSON)")
    ap.add_argument("--trace", type=Path, help="the agent's run trace: its opened files are the fallback suspects")
    ap.add_argument("--no-repro", action="store_true", help="don't execute TRIAGE/repro.py")
    args = ap.parse_args()
    opened = opened_modules(json.loads(args.trace.read_text())) if args.trace else None
    report, _ = triage(args.workspace, args.issue.read_text(), CodeGraph.load(args.graph), opened_files=opened,
                       run_repro=not args.no_repro)
    (args.workspace / "TRIAGE").mkdir(exist_ok=True)
    (args.workspace / "TRIAGE" / "final_report.md").write_text(report)
    print(report)


if __name__ == "__main__":
    main()
