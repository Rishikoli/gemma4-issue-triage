#!/usr/bin/env python3
"""The deterministic orchestrator of the triage pipeline (Paper 2): build the final report per task.

Works on single-agent runs (agent wrote TRIAGE/report.md) and multi-agent runs (TRIAGE/locations.md
+ TRIAGE/repro.md). For each task it:
  1. takes the agent's ranked suspects; if the agents wrote none, falls back to the files the agent
     opened (trace), then to retrieval, so a report always exists;
  2. compares the agent's top suspect with retrieval (BM25 + call-graph spreading):
     same top-1 → HIGH, in retrieval's top-3 → MEDIUM, otherwise (or no agent suspect) → LOW;
  3. merges the agent's tests with call-graph tests for the top suspect;
  4. reports reproduction by the script's exit code on the original code (from
     eval/make_repro_check_notebook.py), not by what the agent claimed;
  5. writes report.md and scores it like eval/triage_reports.py.

Reports go to results/triage/pipeline/<run>/<task>.md (gitignored: derived from competition data).

Usage: python eval/triage_pipeline.py triage_dev_r1 triage_hold_r1 [--retrieval results/triage/localize_*_all.jsonl]
                                      [--repro-check results/repro_check/repro_check.jsonl]
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"  # the competition data: tasks.jsonl, graphs/, embeddings/ (not redistributed)
sys.path.insert(0, str(Path(__file__).resolve().parent))
from triage_agent_baseline import agent_rankings  # noqa: E402
import triage_reports  # noqa: E402
from triage_reports import files_in_patch, graph_tests, parse_report, rank_of, section, test_module  # noqa: E402


def agent_outputs(files: dict[str, str]) -> dict:
    """Suspects, tests, repro status and open questions from either agent layout."""
    if "TRIAGE/report.md" in files:
        rep = files["TRIAGE/report.md"]
        p = parse_report(rep)
        p["questions"] = section(rep, "Open questions for the maintainer")
        p["observed"] = section(rep, "Reproduction")
        return p
    loc, rep = files.get("TRIAGE/locations.md", ""), files.get("TRIAGE/repro.md", "")
    p = parse_report(loc + "\n" + rep)
    p["questions"] = section(rep, "Open questions for the maintainer")
    p["observed"] = section(rep, "Reproduction")
    return p


def build_report(tid: str, suspects: list[str], source: str, conf: str, tests: list[str],
                 out: dict, retrieval: list[str]) -> str:
    lines = [f"# Triage report: {tid}", "", f"**Confidence: {conf}** "
             f"({'agent and retrieval agree' if conf == 'HIGH' else 'agent pick in retrieval top-3' if conf == 'MEDIUM' else 'agent and retrieval disagree, or no agent suspect'})",
             "", "## Suspected location"]
    lines += [f"{i}. `{m}`" for i, m in enumerate(suspects[:3], 1)] or ["(none)"]
    lines += [f"", f"_Source: {source}. Retrieval's top 3: {', '.join(f'`{m}`' for m in retrieval[:3]) or '(none)'}._",
              "", "## Tests to run"]
    lines += [f"- `{t}`" for t in tests[:5]] or ["- (none found)"]
    lines += ["", "## Reproduction", f"Status (checked by running the script): **{out['checked_repro']}**"
              if out.get("checked_repro") else "", out.get("observed") or "Status: NOT_ATTEMPTED", "",
              "## Open questions for the maintainer", out.get("questions") or "- (none)"]
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("runs", nargs="+")
    ap.add_argument("--labels", type=Path, default=ROOT / "results" / "triage" / "labels.jsonl")
    ap.add_argument("--retrieval", nargs="+", default=sorted(glob.glob(str(ROOT / "results/triage/localize_*_all.jsonl"))))
    ap.add_argument("--out-dir", type=Path, default=ROOT / "results" / "triage" / "pipeline")
    ap.add_argument("--repro-check", type=Path, default=ROOT / "results" / "repro_check" / "repro_check.jsonl")
    ap.add_argument("--graphs", type=Path, default=triage_reports.GRAPHS, help="code graphs for call-graph tests")
    args = ap.parse_args()
    triage_reports.GRAPHS = args.graphs
    labels = {l["task_id"]: l for l in map(json.loads, args.labels.read_text().splitlines()) if l}
    tasks = {t["instance_id"]: t for t in map(json.loads, (DATA / "tasks.jsonl").read_text().splitlines())}
    retr = {}
    for f in args.retrieval:
        for r in map(json.loads, Path(f).read_text().splitlines()):
            retr[r["task_id"]] = r["bm25_calls"]["top5"]
    checks = {}
    if args.repro_check.exists():
        checks = {(c["run"], c["task_id"]): c for c in map(json.loads, args.repro_check.read_text().splitlines()) if c}

    rows = []
    for run in args.runs:
        d = ROOT / "results" / run / "results" / run
        out_dir = args.out_dir / run
        out_dir.mkdir(parents=True, exist_ok=True)
        for tid in [json.loads(l)["instance_id"] for l in (d / "task_results.jsonl").read_text().splitlines() if l.strip()]:
            lab = labels[tid]
            pf, tf = d / "patches" / f"{tid}.patch", d / "traces" / f"trace_{tid}.json"
            files = files_in_patch(pf.read_text(errors="replace")) if pf.exists() else {}
            out = agent_outputs(files)
            check = checks.get((run, tid))
            if "TRIAGE/repro.py" not in files:
                out["checked_repro"] = "NOT_ATTEMPTED"
            elif check:
                out["checked_repro"] = "REPRODUCED" if check["exit_before"] != 0 else "NOT_REPRODUCED"
            r = retr.get(tid, [])
            if out["locations"]:
                suspects, source = out["locations"], "agent report"
            else:
                opened = agent_rankings(json.loads(tf.read_text()))[0] if tf.exists() else []
                suspects, source = (opened, "files the agent opened") if opened else (r, "retrieval only")
            if source == "retrieval only" or not suspects:
                conf = "LOW"
            else:
                conf = "HIGH" if r and suspects[0] == r[0] else "MEDIUM" if suspects[0] in r[:3] else "LOW"
            g = graph_tests(tasks[tid], suspects[0]) if suspects else []
            tests = out["tests"] + [m for m in g if m not in out["tests"]]
            (out_dir / f"{tid}.md").write_text(build_report(tid, suspects, source, conf, tests, out, r))
            gold = set(lab["gold_modules"])
            gold_tests = {m for p in lab["gold_test_files"] if (m := test_module(p))}
            rows.append({"run": run, "task_id": tid, "source": source, "confidence": conf,
                         "self_conf": out.get("confidence"), "loc_rank": rank_of(suspects, gold),
                         "test_rank": rank_of(tests, gold_tests), "repro": out.get("repro"),
                         "checked_repro": out.get("checked_repro"),
                         "repro_verified": check["verdict"] == "verified" if check else None})

    n = len(rows)
    def hit(key, k, sub=rows): return sum(1 for r in sub if r[key] and r[key] <= k) / max(len(sub), 1)
    print(f"{n} task-runs from {args.runs}: a report for every task ({dict((s, sum(r['source'] == s for r in rows)) for s in ('agent report', 'files the agent opened', 'retrieval only'))})")
    print(f"  location hit@1 {hit('loc_rank', 1):.0%}, hit@3 {hit('loc_rank', 3):.0%}")
    print(f"  tests (agent + call graph) hit@1 {hit('test_rank', 1):.0%}, hit@3 {hit('test_rank', 3):.0%}")
    by = defaultdict(list)
    for r in rows:
        by[r["confidence"]].append(r)
    print("  confidence → location hit@1:", {c: f"{sum(1 for r in v if r['loc_rank'] == 1)}/{len(v)}" for c, v in sorted(by.items())})
    for key, what in (("repro", "agent's claim"), ("checked_repro", "exit code")):
        said = [r for r in rows if r[key] == "REPRODUCED"]
        print(f"  REPRODUCED by {what}: {len(said)}, verified (fails before the fix, passes after) "
              f"{sum(1 for r in said if r['repro_verified'])}")
    print(f"  reports written to {args.out_dir}/<run>/")
    (args.out_dir / "summary.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))


if __name__ == "__main__":
    main()
