#!/usr/bin/env python3
"""Freeze a dev/holdout split of the competition tasks. Run ONCE, commit the output.

Usage:
    python eval/make_split.py --tasks data/tasks.jsonl --dev 40 --holdout 20

The split is stratified by repository so no single codebase dominates dev.
Tasks not picked for dev or holdout are listed as "unused" (handy for
self-training data later — they never touch evaluation).

Accepts .jsonl, .json (list of objects) or .csv. Field names are auto-detected;
override with --id-field / --repo-field once you've looked at the real file.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

ID_CANDIDATES = ["instance_id", "task_id", "id", "name"]
REPO_CANDIDATES = ["repo", "repository", "repo_name", "project"]


def load_tasks(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".jsonl":
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    if path.suffix == ".json":
        data = json.loads(text)
        if isinstance(data, dict):  # e.g. {"tasks": [...]}
            for value in data.values():
                if isinstance(value, list):
                    return value
            raise SystemExit("JSON object has no list of tasks inside it")
        return data
    if path.suffix == ".csv":
        with path.open(newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))
    raise SystemExit(f"Unsupported file type: {path.suffix} (use .jsonl, .json or .csv)")


def pick_field(row: dict, explicit: str | None, candidates: list[str], what: str) -> str | None:
    if explicit:
        if explicit not in row:
            raise SystemExit(f"--{what}-field '{explicit}' not found. Fields: {sorted(row)}")
        return explicit
    for name in candidates:
        if name in row:
            return name
    return None


def repo_from_id(task_id: str) -> str:
    # SWE-bench style ids look like "owner__repo-1234"; fall back to the prefix.
    if "__" in task_id:
        return task_id.split("__")[0] + "__" + task_id.split("__")[1].rsplit("-", 1)[0]
    return task_id.rsplit("-", 1)[0]


def stratified_take(groups: dict[str, list[str]], n: int, rng: random.Random) -> list[str]:
    """Take n ids, allocated to repos in proportion to their size (largest remainder),
    with at least one per repo when n allows, so the subset mirrors the full task mix."""
    sizes = {repo: len(ids) for repo, ids in groups.items() if ids}
    total = sum(sizes.values())
    quota = {repo: n * size / total for repo, size in sizes.items()}
    alloc = {repo: int(q) for repo, q in quota.items()}
    if n >= len(sizes):
        for repo in sizes:
            alloc[repo] = max(alloc[repo], 1)
    # Hand out remaining slots by largest fractional remainder; trim if the floor-of-1 overshot.
    by_remainder = sorted(sizes, key=lambda r: (-(quota[r] - int(quota[r])), r))
    i = 0
    while sum(alloc.values()) < n:
        repo = by_remainder[i % len(by_remainder)]
        if alloc[repo] < sizes[repo]:
            alloc[repo] += 1
        i += 1
    by_largest = sorted(sizes, key=lambda r: (-alloc[r], r))
    i = 0
    while sum(alloc.values()) > n:
        repo = by_largest[i % len(by_largest)]
        if alloc[repo] > 1:
            alloc[repo] -= 1
        i += 1

    taken: list[str] = []
    for repo in sorted(alloc):
        ids = groups[repo][:]
        rng.shuffle(ids)
        taken.extend(ids[: alloc[repo]])
    taken_set = set(taken)
    for repo in groups:  # remove taken ids from the shared groups
        groups[repo] = [i for i in groups[repo] if i not in taken_set]
    return taken


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tasks", required=True, type=Path, help="tasks file from the harness")
    ap.add_argument("--dev", type=int, default=40, help="number of dev tasks (default 40)")
    ap.add_argument("--holdout", type=int, default=20, help="number of holdout tasks (default 20)")
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--id-field", help="field holding the task id (auto-detected if omitted)")
    ap.add_argument("--repo-field", help="field holding the repo name (auto-detected if omitted)")
    ap.add_argument("--out", type=Path, default=Path("results/split.json"))
    ap.add_argument("--force", action="store_true", help="overwrite an existing split (don't!)")
    args = ap.parse_args()

    if args.out.exists() and not args.force:
        sys.exit(f"{args.out} already exists. The split must stay frozen. "
                 "Use --force only if you truly mean to reset every experiment.")

    tasks = load_tasks(args.tasks)
    if not tasks:
        sys.exit("No tasks found")

    id_field = pick_field(tasks[0], args.id_field, ID_CANDIDATES, "id")
    if not id_field:
        sys.exit(f"Couldn't find a task id field. Fields: {sorted(tasks[0])}. Use --id-field.")
    repo_field = pick_field(tasks[0], args.repo_field, REPO_CANDIDATES, "repo")

    groups: dict[str, list[str]] = defaultdict(list)
    seen: set[str] = set()
    for t in tasks:
        tid = str(t[id_field])
        if tid in seen:
            sys.exit(f"Duplicate task id: {tid}")
        seen.add(tid)
        repo = str(t[repo_field]) if repo_field else repo_from_id(tid)
        groups[repo].append(tid)
    for repo in groups:
        groups[repo].sort()  # deterministic before shuffling

    total = len(seen)
    if args.dev + args.holdout > total:
        sys.exit(f"Asked for {args.dev}+{args.holdout} tasks but only {total} exist")

    rng = random.Random(args.seed)
    holdout = stratified_take(groups, args.holdout, rng)  # holdout first: guarantees coverage
    dev = stratified_take(groups, args.dev, rng)
    unused = sorted(i for ids in groups.values() for i in ids)

    split = {
        "created": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "source_file": str(args.tasks),
        "source_sha256": hashlib.sha256(args.tasks.read_bytes()).hexdigest(),
        "seed": args.seed,
        "id_field": id_field,
        "repo_field": repo_field or "(derived from id)",
        "counts": {"dev": len(dev), "holdout": len(holdout), "unused": len(unused), "total": total},
        "dev": sorted(dev),
        "holdout": sorted(holdout),
        "unused": unused,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(split, indent=2) + "\n", encoding="utf-8")

    # Per-repo summary
    repo_of = {}
    for t in tasks:
        tid = str(t[id_field])
        repo_of[tid] = str(t[repo_field]) if repo_field else repo_from_id(tid)
    print(f"Wrote {args.out}: dev={len(dev)}, holdout={len(holdout)}, unused={len(unused)} (total {total})")
    print(f"{'repo':40s} {'dev':>4s} {'hold':>5s} {'unused':>7s}")
    for repo in sorted(set(repo_of.values())):
        d = sum(repo_of[i] == repo for i in dev)
        h = sum(repo_of[i] == repo for i in holdout)
        u = sum(repo_of[i] == repo for i in unused)
        print(f"{repo[:40]:40s} {d:4d} {h:5d} {u:7d}")
    print("\nDeterministic for this tasks file (seed and sha256 recorded above): rebuild it rather than share it.")


if __name__ == "__main__":
    main()
