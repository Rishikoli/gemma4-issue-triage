#!/usr/bin/env python3
"""Score the triage agent's reports (Paper 2). CPU only.

Reads each task's saved patch from a triage run (results/<run>/results/<run>/patches/<id>.patch),
extracts TRIAGE/report.md (or the multi-agent TRIAGE/locations.md + repro.md) and TRIAGE/repro.py, and scores the report against the labels from
eval/triage_labels.py:

  location     hit@1/@3: a suspected file is a file the reference fix changes (module level)
  tests        hit@1/@3: a listed test file is one the hidden tests modify
  tests+graph  the report's top suspected module fed to the code graph's call edges (deterministic
               step, no model): test modules that call into it, merged after the agent's own list
  confidence   location hit@1 by self-reported HIGH / MEDIUM / LOW
  reproduction self-reported status (verified separately by running repro.py before/after the fix)
  violations   tasks whose patch touches anything outside TRIAGE/

Usage: python eval/triage_reports.py triage_r1 [triage_r2 ...] [--sound-only]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"  # the competition data: tasks.jsonl, graphs/, embeddings/ (not redistributed)
sys.path.insert(0, str(Path(__file__).resolve().parent))
from triage_labels import TEST_PATH, to_module  # noqa: E402
from triage_localize import is_test_module, node_module  # noqa: E402

GRAPHS = DATA / "graphs"  # code graphs; --graphs swaps in another set (e.g. our own, eval/make_graphs_notebook.py)


def files_in_patch(patch: str) -> dict[str, str]:
    """path -> added text for every file in a unified diff (full text for newly created files)."""
    out: dict[str, list[str]] = {}
    current = None
    for line in patch.splitlines():
        m = re.match(r"^\+\+\+ b/(\S+)", line)
        if m:
            current = m.group(1)
            out.setdefault(current, [])
            continue
        if line.startswith("diff --git"):
            current = None
        elif current and line.startswith("+") and not line.startswith("+++"):
            out[current].append(line[1:])
    return {p: "\n".join(lines) for p, lines in out.items()}


def section(report: str, title: str) -> str:
    m = re.search(rf"^##\s*{re.escape(title)}\s*$(.*?)(?=^##\s|\Z)", report, flags=re.M | re.S | re.I)
    return m.group(1).strip() if m else ""


def test_module(path: str) -> str | None:
    path = path.split("::")[0].strip().lstrip("/").removeprefix("workspace/")
    if not path.endswith(".py"):
        return None
    parts = path[:-3].split("/")
    return ".".join(parts[1:] if parts[0] == "src" else parts)


def parse_report(report: str) -> dict:
    locs = []
    for p in re.findall(r"([\w./-]+\.py)", section(report, "Suspected location")):
        p = p.lstrip("/").removeprefix("workspace/")
        if not TEST_PATH.search(p) and (m := to_module(p)) and m not in locs:
            locs.append(m)
    tests = []
    for p in re.findall(r"([\w./-]+\.py)", section(report, "Tests to run")):
        if (m := test_module(p)) and m not in tests:
            tests.append(m)
    repro = re.search(r"Status:\s*(REPRODUCED|NOT_REPRODUCED|NOT_ATTEMPTED)", section(report, "Reproduction"), re.I)
    conf = re.search(r"\b(HIGH|MEDIUM|LOW)\b", section(report, "Confidence"), re.I)
    return {"locations": locs, "tests": tests, "repro": repro.group(1).upper() if repro else None,
            "confidence": conf.group(1).upper() if conf else None}


def graph_tests(task: dict, module: str) -> list[str]:
    g = json.loads((GRAPHS / f"{task['repo'].split('/')[-1]}_{task['base_commit']}.json").read_text())
    names = {n["name"] for n in g["nodes"]}
    mod_of = {n: node_module(n, names) for n in names}
    c = Counter(mod_of[e["source"]] for e in g["edges"] if e["source"] in names and e["target"] in names
                and is_test_module(mod_of[e["source"]]) and mod_of[e["target"]] == module)
    return [m for m, _ in c.most_common()]


def rank_of(ranking: list[str], gold: set[str]) -> int | None:
    return next((i for i, m in enumerate(ranking, 1) if m in gold), None)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("runs", nargs="+")
    ap.add_argument("--labels", type=Path, default=ROOT / "results" / "triage" / "labels.jsonl")
    ap.add_argument("--sound-only", action="store_true")
    ap.add_argument("--out", type=Path, default=ROOT / "results" / "triage" / "reports.jsonl")
    ap.add_argument("--graphs", type=Path, default=GRAPHS)
    ap.add_argument("--tasks", type=Path, default=DATA / "tasks.jsonl")
    args = ap.parse_args()
    globals()["GRAPHS"] = args.graphs
    labels = {l["task_id"]: l for l in map(json.loads, args.labels.read_text().splitlines()) if l}
    tasks = {t["instance_id"]: t for t in map(json.loads, args.tasks.read_text().splitlines()) if t}

    rows = []
    for run in args.runs:
        d = ROOT / "results" / run / "results" / run
        done = [json.loads(l)["instance_id"] for l in (d / "task_results.jsonl").read_text().splitlines() if l.strip()]
        for tid in done:
            lab = labels.get(tid)
            if not lab or (args.sound_only and not lab["sound"]):
                continue
            pf = d / "patches" / f"{tid}.patch"
            files = files_in_patch(pf.read_text(errors="replace")) if pf.exists() else {}
            # single agent: report.md; localizer → reproducer: locations.md + repro.md
            report = files.get("TRIAGE/report.md") or "\n".join(
                files[f] for f in ("TRIAGE/locations.md", "TRIAGE/repro.md") if files.get(f))
            parsed = parse_report(report) if report else {"locations": [], "tests": [], "repro": None, "confidence": None}
            gold = set(lab["gold_modules"])
            gold_tests = {m for p in lab["gold_test_files"] if (m := test_module(p))}
            g_tests = graph_tests(tasks[tid], parsed["locations"][0]) if parsed["locations"] else []
            merged = parsed["tests"] + [m for m in g_tests if m not in parsed["tests"]]
            rows.append({
                "run": run, "task_id": tid, "has_report": bool(report), "has_repro": "TRIAGE/repro.py" in files,
                "violation": sorted(p for p in files if not p.startswith("TRIAGE/")),
                **parsed, "loc_rank": rank_of(parsed["locations"], gold),
                "test_rank": rank_of(parsed["tests"], gold_tests),
                "graph_test_rank": rank_of(g_tests, gold_tests), "merged_test_rank": rank_of(merged, gold_tests)})
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("".join(json.dumps(r) + "\n" for r in rows))

    n = len(rows)
    if not n:
        sys.exit("no tasks found")
    def hit(key, k): return sum(1 for r in rows if r[key] and r[key] <= k) / n
    print(f"{n} task-runs from {args.runs}{' (sound only)' if args.sound_only else ''}")
    print(f"  reports written {sum(r['has_report'] for r in rows)}/{n}, repro scripts {sum(r['has_repro'] for r in rows)}/{n}, "
          f"edits outside TRIAGE/ {sum(bool(r['violation']) for r in rows)}/{n}")
    print(f"  {'':22s} {'hit@1':>6s} {'hit@3':>6s}")
    for name, key in (("location", "loc_rank"), ("tests (agent)", "test_rank"),
                      ("tests (graph step)", "graph_test_rank"), ("tests (agent+graph)", "merged_test_rank")):
        print(f"  {name:22s} {hit(key, 1):6.0%} {hit(key, 3):6.0%}")
    by_conf = defaultdict(list)
    for r in rows:
        by_conf[r["confidence"] or "missing"].append(bool(r["loc_rank"] == 1))
    print("  location@1 by confidence:", {k: f"{sum(v)}/{len(v)}" for k, v in sorted(by_conf.items())})
    print("  reproduction status:", dict(Counter(r["repro"] or "missing" for r in rows)))


if __name__ == "__main__":
    main()
