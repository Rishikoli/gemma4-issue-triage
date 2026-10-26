#!/usr/bin/env python3
"""Build triage ground truth from the competition's tasks.jsonl (Paper 2).

For every task, from the reference fix (`patch`) and the hidden tests (`test_patch`):
  gold_files      source files the fix changes (tests and Markdown docs excluded; docs_src/ code kept)
  gold_modules    the same as dotted module names, matching code-graph node names
  gold_symbols    enclosing def/class names from the fix's hunk headers (heuristic)
  gold_test_files test files the hidden tests modify that already existed (predictable)
  new_test_files  test files the hidden tests create (no method can predict these)
plus the task's split subset, soundness verdict and whether a code graph exists for it.

The output is derived from competition data, so it goes to results/ (gitignored) and must not be
published. Publish this script instead.

Usage: python eval/triage_labels.py [--tasks data/tasks.jsonl] [--out results/triage/labels.jsonl]
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"  # the competition data: tasks.jsonl, graphs/, embeddings/ (not redistributed)
TEST_PATH = re.compile(r"(^|/)(tests?|testing)/|(^|/)test_[^/]*\.py$|_test\.py$|(^|/)conftest\.py$")


def changed_files(patch: str) -> list[tuple[str, bool]]:
    """(path, created) for each file in a unified diff."""
    return [(m.group(2), m.group(1) == "/dev/null")
            for m in re.finditer(r"^--- (\S+)\n\+\+\+ b/(\S+)", patch or "", flags=re.M)]


def to_module(path: str) -> str | None:
    """'rich/style.py' -> 'rich.style'; 'src/requests/__init__.py' -> 'requests'."""
    if not path.endswith(".py"):
        return None
    parts = path[:-3].split("/")
    if parts[0] == "src":
        parts = parts[1:]
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts) or None


def is_source(path: str) -> bool:
    return path.endswith(".py") and not TEST_PATH.search(path)


def hunk_symbols(patch: str) -> dict[str, set[str]]:
    """file -> def/class names from '@@ ... @@ def foo(' hunk headers and added/removed def lines."""
    out: dict[str, set[str]] = {}
    current = None
    for line in (patch or "").splitlines():
        m = re.match(r"^\+\+\+ b/(\S+)", line)
        if m:
            current = m.group(1)
            continue
        if current is None:
            continue
        m = re.match(r"^@@ .*@@\s*(?:async\s+)?(?:def|class)\s+(\w+)", line)
        if m:
            out.setdefault(current, set()).add(m.group(1))
        m = re.match(r"^[+-]\s*(?:async\s+)?(?:def|class)\s+(\w+)", line)
        if m:
            out.setdefault(current, set()).add(m.group(1))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tasks", type=Path, default=DATA / "tasks.jsonl")
    ap.add_argument("--split", type=Path, default=ROOT / "results" / "split.json")
    ap.add_argument("--soundness", type=Path, default=ROOT / "results" / "soundness.json",
                    help="optional: which tasks the notebook environment can grade (gold passes, empty fails)")
    ap.add_argument("--graphs", type=Path, default=DATA / "graphs")
    ap.add_argument("--out", type=Path, default=ROOT / "results" / "triage" / "labels.jsonl")
    args = ap.parse_args()

    split = json.loads(args.split.read_text())
    subset_of = {t: s for s in ("dev", "holdout", "unused") for t in split[s]}
    sound = ({t for ids in json.loads(args.soundness.read_text())["sound"].values() for t in ids}
             if args.soundness.exists() else None)

    rows = []
    for t in map(json.loads, args.tasks.read_text().splitlines()):
        files = changed_files(t["patch"])
        gold_files = sorted(p for p, _ in files if is_source(p))
        syms = hunk_symbols(t["patch"])
        tests = changed_files(t["test_patch"])
        short = t["repo"].split("/")[-1]
        rows.append({
            "task_id": t["instance_id"], "repo": t["repo"], "subset": subset_of.get(t["instance_id"]),
            "sound": t["instance_id"] in sound if sound is not None else None,
            "has_graph": (args.graphs / f"{short}_{t['base_commit']}.json").exists(),
            "gold_files": gold_files,
            "gold_modules": sorted({m for p in gold_files if (m := to_module(p))}),
            "gold_symbols": sorted({f"{to_module(p)}:{s}" for p in gold_files for s in syms.get(p, ())}),
            "gold_test_files": sorted(p for p, created in tests if not created and p.endswith(".py")),
            "new_test_files": sorted(p for p, created in tests if created and p.endswith(".py")),
        })
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("".join(json.dumps(r) + "\n" for r in rows))

    n = len(rows)
    def frac(cond): return f"{sum(1 for r in rows if cond(r))}/{n}"
    print(f"Wrote {args.out}: {n} tasks")
    print(f"  with >=1 gold source file:        {frac(lambda r: r['gold_files'])}")
    print(f"  exactly 1 gold source file:       {frac(lambda r: len(r['gold_files']) == 1)}")
    print(f"  with gold symbols:                {frac(lambda r: r['gold_symbols'])}")
    print(f"  with an existing gold test file:  {frac(lambda r: r['gold_test_files'])}")
    print(f"  hidden tests only in new files:   {frac(lambda r: r['new_test_files'] and not r['gold_test_files'])}")
    print(f"  code graph available:             {frac(lambda r: r['has_graph'])}")
    print(f"  sound in our environment:         {frac(lambda r: r['sound']) if sound is not None else 'n/a (no soundness file)'}")
    print("  repos:", dict(Counter(r["repo"] for r in rows)))


if __name__ == "__main__":
    main()
