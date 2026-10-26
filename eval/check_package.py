#!/usr/bin/env python3
"""Check that the shipped orchestrator (triage/) behaves like the evaluated one (eval/triage_pipeline.py).

For every task-run, rebuilds the agent's TRIAGE/ notes from its saved patch, runs triage.orchestrate
(reproduction off: snapshots aren't needed) and compares the suspect source, confidence, rank of the
right file and rank of the right test file with results/triage/pipeline/summary.jsonl.

Usage: python eval/triage_pipeline.py triage_dev_r1 triage_hold_r1 && python eval/check_package.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"  # the competition data: tasks.jsonl, graphs/, embeddings/ (not redistributed)
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from triage.graph import CodeGraph  # noqa: E402
from triage.orchestrate import triage  # noqa: E402
from triage.trace import opened_modules  # noqa: E402
from triage_reports import files_in_patch, rank_of, test_module  # noqa: E402


def main() -> None:
    tasks = {t["instance_id"]: t for t in map(json.loads, (DATA / "tasks.jsonl").read_text().splitlines())}
    labels = {l["task_id"]: l for l in map(json.loads, (ROOT / "results/triage/labels.jsonl").read_text().splitlines())}
    rows = [json.loads(l) for l in (ROOT / "results/triage/pipeline/summary.jsonl").read_text().splitlines()]
    agree = dict.fromkeys(("source", "confidence", "loc_rank", "test_rank"), 0)
    for r in rows:
        t, d = tasks[r["task_id"]], ROOT / "results" / r["run"] / "results" / r["run"]
        pf, tf = d / "patches" / f"{r['task_id']}.patch", d / "traces" / f"trace_{r['task_id']}.json"
        notes = files_in_patch(pf.read_text(errors="replace")) if pf.exists() else {}
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            (ws / "TRIAGE").mkdir()
            for path, text in notes.items():
                if path.startswith("TRIAGE/"):
                    (ws / path).write_text(text)
            graph = CodeGraph.load(DATA / "graphs" / f"{t['repo'].split('/')[-1]}_{t['base_commit']}.json")
            opened = opened_modules(json.loads(tf.read_text())) if tf.exists() else None
            _, info = triage(ws, t["problem_statement"], graph, opened_files=opened, run_repro=False)
        gold = set(labels[r["task_id"]]["gold_modules"])
        gold_tests = {m for p in labels[r["task_id"]]["gold_test_files"] if (m := test_module(p))}
        mine = {"source": info["source"].split(" (")[0], "confidence": info["confidence"],
                "loc_rank": rank_of(info["suspects"], gold), "test_rank": rank_of(info["tests"], gold_tests)}
        for k in agree:
            if mine[k] == r[k]:
                agree[k] += 1
            else:
                print(f"differs: {r['run']}/{r['task_id']} {k}: package {mine[k]!r}, evaluated {r[k]!r}")
    print(f"{len(rows)} task-runs; package agrees with the evaluated orchestrator on:",
          {k: f"{v}/{len(rows)}" for k, v in agree.items()})


if __name__ == "__main__":
    main()
