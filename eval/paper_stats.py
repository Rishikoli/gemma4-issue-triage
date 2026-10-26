#!/usr/bin/env python3
"""The paper's derived statistics, from the outputs of the other eval scripts (Paper 2, §4).

  - localization by whether the issue text names the file to fix (leakage control)
  - exact McNemar tests on the pooled dev + holdout issues
  - how often the fallback (first file the agent opened) was right
  - repro scripts that pass on the buggy code but print a different result once fixed

Usage: python eval/triage_pipeline.py triage_dev_r1 triage_hold_r1 && python eval/paper_stats.py
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from math import comb
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"  # the competition data: tasks.jsonl, graphs/, embeddings/ (not redistributed)
TRIAGE = ROOT / "results" / "triage"
RUNS = {"triage_dev_r1": "dev", "triage_hold_r1": "holdout"}


def jsonl(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def names_file(text: str, gold_files: list[str]) -> bool:
    """The issue text contains a gold file's path or dotted module name."""
    for f in gold_files:
        if f.endswith(".py"):
            mod = f[:-3].removeprefix("src/").replace("/", ".")
            if f in text or f.removeprefix("src/") in text or mod in text:
                return True
    return False


def mcnemar(a: list[bool], b: list[bool]) -> tuple[int, int, float]:
    """Exact two-sided McNemar test: (a right & b wrong, b right & a wrong, p)."""
    x = sum(1 for i, j in zip(a, b) if i and not j)
    y = sum(1 for i, j in zip(a, b) if j and not i)
    n = x + y
    p = min(1.0, 2 * sum(comb(n, i) for i in range(min(x, y) + 1)) / 2 ** n) if n else 1.0
    return x, y, p


def main() -> None:
    tasks = {t["instance_id"]: t for t in jsonl(DATA / "tasks.jsonl")}
    labels = {l["task_id"]: l for l in jsonl(TRIAGE / "labels.jsonl")}
    pipe = {(r["run"], r["task_id"]): r for r in jsonl(TRIAGE / "pipeline" / "summary.jsonl")}
    raw = {(r["run"], r["task_id"]): r for run in RUNS for r in jsonl(TRIAGE / f"reports_{run}.jsonl")}
    retr = {r["task_id"]: r for s in RUNS.values() for r in jsonl(TRIAGE / f"localize_{s}_all.jsonl")}
    keys = sorted(k for k in pipe if k[0] in RUNS)

    print("Localization top-1 by whether the issue names the file (retrieval = BM25 + call graph):")
    for run in RUNS:
        for named in (True, False):
            ks = [k for k in keys if k[0] == run
                  and names_file(tasks[k[1]]["problem_statement"], labels[k[1]]["gold_files"]) == named]
            if ks:
                n = len(ks)
                print(f"  {RUNS[run]:8s} names file={named!s:5s} n={n:2d}: "
                      f"retrieval {sum(retr[k[1]]['bm25_calls']['rank'] == 1 for k in ks)}/{n}, "
                      f"agent {sum(raw[k].get('loc_rank') == 1 for k in ks)}/{n}, "
                      f"agent + orchestrator {sum(pipe[k]['loc_rank'] == 1 for k in ks)}/{n}")

    orch = [pipe[k]["loc_rank"] == 1 for k in keys]
    agent = [raw[k].get("loc_rank") == 1 for k in keys]
    bm25c = [retr[k[1]]["bm25_calls"]["rank"] == 1 for k in keys]
    orch_t = [pipe[k]["test_rank"] == 1 for k in keys]
    agent_t = [raw[k].get("test_rank") == 1 for k in keys]
    bm25_t = [retr[k[1]]["test_bm25"]["rank"] == 1 for k in keys]
    print(f"\nExact McNemar, pooled {len(keys)} issues (first right & second wrong, the reverse, p):")
    for name, a, b in (("location: orchestrated vs retrieval", orch, bm25c),
                       ("location: agent vs retrieval", agent, bm25c),
                       ("location: orchestrated vs agent", orch, agent),
                       ("tests: orchestrated vs agent", orch_t, agent_t),
                       ("tests: orchestrated vs BM25", orch_t, bm25_t)):
        x, y, p = mcnemar(a, b)
        print(f"  {name:38s} {sum(a)}/{len(a)} vs {sum(b)}/{len(b)}: {x} / {y}, p = {p:.2g}")

    by = defaultdict(lambda: [0, 0])
    for k in keys:
        by[pipe[k]["source"]][0] += 1
        by[pipe[k]["source"]][1] += pipe[k]["loc_rank"] == 1
    print("\nOrchestrated location by suspect source:", {s: f"{c}/{n}" for s, (n, c) in by.items()})

    checks = jsonl(ROOT / "results" / "repro_check" / "repro_check.jsonl")
    def norm(s: str | None) -> str:
        return re.sub(r"0x[0-9a-f]+|\d+\.\d+s|/tmp/\S+", "", s or "").strip()
    passes = [c for c in checks if c["verdict"] == "passes_before"]
    changed = [c["task_id"] for c in passes if norm(c["out_before"]) != norm(c["out_after"])]
    print(f"\nRepro scripts passing on the buggy code: {len(passes)}; output changes with the fix: {len(changed)}")
    print("  ", ", ".join(changed))


if __name__ == "__main__":
    main()
