#!/usr/bin/env python3
"""Localization and test selection by the LLM agent, read from existing run traces (Paper 2, RQ1/RQ3).

For each task-run, the agent's file ranking is the order in which it first opened (read_file) or
edited (edit_file/write_file) each source file; its test ranking is the order in which test files
first appear in its read_file calls or test commands. Both are scored like eval/triage_localize.py
(hit@k against the reference fix's modules and the hidden tests' existing test files), plus
"first edited file" accuracy. No GPU: it reuses results/<run>/ traces.

Usage: python eval/triage_agent_baseline.py base_cap_r1 base_cap_r2 ... [--sound-only]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"  # the competition data: tasks.jsonl, graphs/, embeddings/ (not redistributed)
sys.path.insert(0, str(Path(__file__).resolve().parent))
from triage_labels import TEST_PATH, to_module  # noqa: E402


def test_module(path: str) -> str | None:
    if not path.endswith(".py"):
        return None
    parts = path.lstrip("/").removeprefix("workspace/")[:-3].split("/")
    return ".".join(parts[1:] if parts[0] == "src" else parts)


def norm(path: str) -> str:
    return path.strip().lstrip("/").removeprefix("workspace/")


def agent_rankings(trace: dict) -> tuple[list[str], list[str], str | None]:
    files, tests, first_edit = [], [], None
    for s in trace["steps"]:
        if s.get("source") != "agent":
            continue
        for c in s.get("tool_calls") or []:
            name, args = c.get("function_name"), c.get("arguments") or {}
            if name in ("read_file", "edit_file", "write_file") and args.get("filepath"):
                p = norm(str(args["filepath"]))
                if p.startswith(("tmp/", "TRIAGE/")):  # scratch files and the triage agent's own notes
                    continue
                if TEST_PATH.search(p):
                    m = test_module(p)
                    if m and m not in tests:
                        tests.append(m)
                elif (m := to_module(p)) and m not in files:
                    files.append(m)
                if name == "edit_file" and first_edit is None and not TEST_PATH.search(p):  # existing files only
                    first_edit = to_module(p)
            elif name == "run_command":
                cmd = str(args.get("command", ""))
                for p in re.findall(r"[\w./-]+\.py", cmd):
                    p = norm(p)
                    if TEST_PATH.search(p) and (m := test_module(p)) and m not in tests:
                        tests.append(m)
    return files, tests, first_edit


def rank_of(ranking: list[str], gold: set[str]) -> int | None:
    return next((i for i, m in enumerate(ranking, 1) if m in gold), None)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("runs", nargs="+", help="run names under results/")
    ap.add_argument("--labels", type=Path, default=ROOT / "results" / "triage" / "labels.jsonl")
    ap.add_argument("--sound-only", action="store_true")
    ap.add_argument("--with-graph-tests", action="store_true",
                    help="also feed the agent's first opened module to the call-graph and naming test finders")
    args = ap.parse_args()
    tasks = {t["instance_id"]: t for t in map(json.loads, (DATA / "tasks.jsonl").read_text().splitlines())}
    cache: dict = {}

    def graph_for(tid: str) -> dict:
        if tid not in cache:
            from collections import Counter
            from triage_localize import is_test_module, node_module
            t = tasks[tid]
            g = json.loads((DATA / "graphs" / f"{t['repo'].split('/')[-1]}_{t['base_commit']}.json").read_text())
            names = {n["name"] for n in g["nodes"]}
            mod_of = {n: node_module(n, names) for n in names}
            test_mods = sorted({m for m in mod_of.values() if is_test_module(m)})
            def by_calls(src: set) -> list:
                c = Counter(mod_of[e["source"]] for e in g["edges"] if e["source"] in names and e["target"] in names
                            and is_test_module(mod_of[e["source"]]) and mod_of[e["target"]] in src)
                return [m for m, _ in c.most_common()]
            def by_name(src: str) -> list:
                last = src.split(".")[-1]
                return [m for m in test_mods if m.split(".")[-1] in (f"test_{last}", f"{last}_test")]
            cache[tid] = {"by_calls": by_calls, "by_name": by_name}
        return cache[tid]
    labels = {l["task_id"]: l for l in map(json.loads, args.labels.read_text().splitlines()) if l}

    rows = []
    for run in args.runs:
        tdir = ROOT / "results" / run / "results" / run / "traces"
        for f in sorted(tdir.glob("trace_*.json")):
            tid = f.stem.removeprefix("trace_")
            lab = labels.get(tid)
            if not lab or (args.sound_only and not lab["sound"]):
                continue
            files, tests, first_edit = agent_rankings(json.loads(f.read_text()))
            gold = set(lab["gold_modules"])
            gold_tests = {m for p in lab["gold_test_files"] if (m := test_module(p))}
            combo_calls = combo_name = None
            if args.with_graph_tests and files:
                g = graph_for(tid)
                combo_calls = rank_of(g["by_calls"]({files[0]}), gold_tests)
                combo_name = rank_of(g["by_name"](files[0]), gold_tests)
            rows.append({"run": run, "task_id": tid, "file_rank": rank_of(files, gold),
                         "combo_calls": combo_calls, "combo_name": combo_name,
                         "test_rank": rank_of(tests, gold_tests), "first_edit_ok": first_edit in gold if first_edit else None,
                         "n_files": len(files), "n_tests": len(tests)})
    n = len(rows)
    if not n:
        sys.exit("no traces found")
    def hit(key, k): return sum(1 for r in rows if r[key] and r[key] <= k) / n
    def mrr(key): return sum(1 / r[key] for r in rows if r[key]) / n
    edited = [r for r in rows if r["first_edit_ok"] is not None]
    print(f"{n} task-runs from {len(args.runs)} runs ({len({r['task_id'] for r in rows})} tasks)"
          f"{', sound only' if args.sound_only else ''}")
    print(f"  {'agent':18s} {'hit@1':>6s} {'hit@3':>6s} {'hit@5':>6s} {'MRR':>6s}")
    print(f"  {'files opened':18s} {hit('file_rank',1):6.0%} {hit('file_rank',3):6.0%} {hit('file_rank',5):6.0%} {mrr('file_rank'):6.2f}")
    print(f"  {'tests touched':18s} {hit('test_rank',1):6.0%} {hit('test_rank',3):6.0%} {hit('test_rank',5):6.0%} {mrr('test_rank'):6.2f}")
    if args.with_graph_tests:
        print(f"  {'agent + call graph':18s} {hit('combo_calls',1):6.0%} {hit('combo_calls',3):6.0%} {hit('combo_calls',5):6.0%} {mrr('combo_calls'):6.2f}")
        print(f"  {'agent + naming':18s} {hit('combo_name',1):6.0%} {hit('combo_name',3):6.0%} {hit('combo_name',5):6.0%} {mrr('combo_name'):6.2f}")
    print(f"  first edited file is a gold file: {sum(r['first_edit_ok'] for r in edited)}/{len(edited)} task-runs that edited")
    print(f"  median files opened {sorted(r['n_files'] for r in rows)[n // 2]}, test files touched {sorted(r['n_tests'] for r in rows)[n // 2]}")


if __name__ == "__main__":
    main()
