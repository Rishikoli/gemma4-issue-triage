#!/usr/bin/env python3
"""The paper's derived statistics, from the outputs of the other eval scripts (Paper 2, §4).

  - localization by whether the issue text names the file to fix (leakage control)
  - exact McNemar tests on the pooled dev + holdout issues
  - how often the fallback (first file the agent opened) was right, and retrieval on the same issues
  - repro scripts that pass on the buggy code but print a different result once fixed
  - source modules per repository; embedding vs call-edge neighbours of retrieval's top functions

Usage: python eval/triage_pipeline.py triage_dev_r1 triage_hold_r1 && python eval/paper_stats.py
       [--dev RUN] [--holdout RUN] [--repro-check results/repro_check/repro_check.jsonl]
       [--compare results/triage/pipeline_multi/summary.jsonl --compare-runs DEV_RUN HOLDOUT_RUN]
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from collections import defaultdict
from math import comb
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"  # the competition data: tasks.jsonl, graphs/, embeddings/ (not redistributed)
TRIAGE = ROOT / "results" / "triage"
sys.path.insert(0, str(Path(__file__).resolve().parent))
from triage_localize import BM25, is_test_module, node_module, tokens  # noqa: E402


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


def graph_neighbours(ids: list[str], tasks: dict, labels: dict) -> None:
    """Repository size, and where the neighbours of BM25's top-3 functions lead: the 20 nearest by the
    organizers' embeddings vs call-graph edges (same module as the function; from a wrong module into
    the right one)."""
    import numpy as np
    size = defaultdict(list)
    count = {"embedding": [0, 0, 0], "call": [0, 0, 0]}  # neighbours, same module, wrong -> right module
    for t in ids:
        task = tasks[t]; short = task["repo"].split("/")[-1]; name = f"{short}_{task['base_commit']}"
        g = json.loads((DATA / "graphs" / f"{name}.json").read_text())
        text = {n["name"]: (n.get("text") or "") for n in g["nodes"]}
        mod = {n: node_module(n, set(text)) for n in text}
        src = {n for n in text if not is_test_module(mod[n])}
        size[short].append(len({mod[n] for n in src}))
        gold = set(labels[t]["gold_modules"])
        scores = BM25({n: tokens(n) + tokens(text[n]) for n in src}).scores(tokens(task["problem_statement"]))
        top = sorted(scores, key=lambda n: -scores[n])[:3]
        calls = defaultdict(set)
        for e in g["edges"]:
            if e["source"] in src and e["target"] in src:
                calls[e["source"]].add(e["target"]); calls[e["target"]].add(e["source"])
        z = np.load(DATA / "embeddings" / f"{name}.npz", allow_pickle=True)
        keys = [k for k in z.files if k in src]
        mat = np.stack([z[k] for k in keys]).astype("float32")
        mat /= np.linalg.norm(mat, axis=1, keepdims=True) + 1e-9
        for n in top:
            near = {"call": calls[n], "embedding": []}
            if n in keys:
                near["embedding"] = [keys[i] for i in np.argsort(-(mat @ mat[keys.index(n)]))[1:21]]
            for kind, ms in near.items():
                for m in ms:
                    c = count[kind]
                    c[0] += 1; c[1] += mod[m] == mod[n]; c[2] += mod[m] in gold and mod[n] not in gold
    print("\nSource modules per repository snapshot (median, range):",
          {r: f"{statistics.median(v):g} ({min(v)}-{max(v)})" for r, v in size.items()})
    print("Neighbours of BM25's top-3 functions (same module; leading from a wrong module into the right one):")
    for kind, (n, same, into) in count.items():
        print(f"  {kind:9s} {n:4d}: same module {same / n:.0%}, wrong -> right module {into / n:.1%}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dev", default="triage_dev_r1")
    ap.add_argument("--holdout", default="triage_hold_r1")
    ap.add_argument("--repro-check", type=Path, default=ROOT / "results" / "repro_check" / "repro_check.jsonl")
    ap.add_argument("--compare", type=Path, help="another system's pipeline summary.jsonl, for paired tests")
    ap.add_argument("--compare-runs", nargs=2, metavar=("DEV_RUN", "HOLDOUT_RUN"))
    args = ap.parse_args()
    RUNS = {args.dev: "dev", args.holdout: "holdout"}
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
    fb = [k for k in keys if pipe[k]["source"] == "files the agent opened"]
    print(f"  on those {len(fb)} fallback issues retrieval (BM25 + call graph) is right on "
          f"{sum(retr[k[1]]['bm25_calls']['rank'] == 1 for k in fb)}")

    checks = [c for c in jsonl(args.repro_check) if c["run"] in RUNS] if args.repro_check.exists() else []
    def norm(s: str | None) -> str:
        return re.sub(r"0x[0-9a-f]+|\d+\.\d+s|/tmp/\S+", "", s or "").strip()
    passes = [c for c in checks if c["verdict"] == "passes_before"]
    changed = [c["task_id"] for c in passes if norm(c["out_before"]) != norm(c["out_after"])]
    print(f"\nRepro scripts passing on the buggy code: {len(passes)}; output changes with the fix: {len(changed)}")
    print("  ", ", ".join(changed))
    inverted = [c["task_id"] for c in passes if re.search(r"reproduc\w* failed", c["out_after"] or "", re.I)]
    print(f"   of which print 'Reproduction failed' once fixed (an output check would read them backwards): {inverted}")

    graph_neighbours(sorted({k[1] for k in keys}), tasks, labels)

    if args.compare:  # same issues, another system (e.g. localizer -> reproducer)
        other = {r["task_id"]: r for r in jsonl(args.compare) if r["run"] in args.compare_runs}
        other_raw = {r["task_id"]: r for run in args.compare_runs for r in jsonl(TRIAGE / f"reports_{run}.jsonl")}
        ids = [k for k in keys if k[1] in other]
        print(f"\nPaired with {args.compare_runs} on {len(ids)} issues (this system right & other wrong, the reverse, p):")
        for name, a, b in (
                ("location, agent", [raw[k].get("loc_rank") == 1 for k in ids], [other_raw[k[1]].get("loc_rank") == 1 for k in ids]),
                ("location, + orchestrator", [pipe[k]["loc_rank"] == 1 for k in ids], [other[k[1]]["loc_rank"] == 1 for k in ids]),
                ("tests, agent", [raw[k].get("test_rank") == 1 for k in ids], [other_raw[k[1]].get("test_rank") == 1 for k in ids]),
                ("tests, + orchestrator", [pipe[k]["test_rank"] == 1 for k in ids], [other[k[1]]["test_rank"] == 1 for k in ids])):
            x, y, p = mcnemar(a, b)
            print(f"  {name:26s} {sum(a)}/{len(a)} vs {sum(b)}/{len(b)}: {x} / {y}, p = {p:.2g}")


if __name__ == "__main__":
    main()
