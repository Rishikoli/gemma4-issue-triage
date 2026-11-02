#!/usr/bin/env python3
"""Build a CPU Kaggle notebook (internet on) that turns issues from projects outside the competition
into harness tasks: SWE-bench Verified issues, each with a repository snapshot at its base commit,
our own code graph (triage/build_graph.py) and placeholder embeddings, in the competition's layout.

Selection: SWE-bench Verified (princeton-nlp/SWE-bench_Verified, test split), `--per-repo` issues from
each of REPOS, drawn with a fixed seed. Projects in the competition (psf/requests) and projects that need
compiled extensions before their code can run (matplotlib, scikit-learn, astropy) are left out. The
embeddings only switch on the harness's graph-tool prompt; the triage agent never searches them.

Usage:
    python eval/make_ext_tasks_notebook.py --owner <kaggle_user>     # writes results/ext/tasks.jsonl too
    kaggle kernels push -p notebooks/gemma4-ext-tasks
Then run the agent on them (python notebooks/make_demo_notebook.py --owner <kaggle_user> --ext-data
<kaggle_user>/gemma4-ext-tasks --run-name triage_ext_r1 --slug triage-run) and score with --tasks/--graphs
pointing at that output.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import random
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "eval"))
from make_repro_check_notebook import code_cell, md_cell  # noqa: E402

URL = "https://huggingface.co/api/datasets/princeton-nlp/SWE-bench_Verified/parquet/default/test/0.parquet"
REPOS = ["django/django", "sympy/sympy", "sphinx-doc/sphinx", "pydata/xarray", "pytest-dev/pytest", "pylint-dev/pylint"]
FIELDS = ["instance_id", "repo", "base_commit", "patch", "test_patch", "problem_statement", "hints_text", "created_at"]

BUILD_CELL = r'''
import json, re, shutil, subprocess, sys, tempfile, time, zlib
from pathlib import Path
import numpy as np

OUT = Path('/kaggle/working')
pkg = Path(tempfile.mkdtemp()) / 'triage'
pkg.mkdir()
for name, text in PACKAGE.items():
    (pkg / name).write_text(text)
sys.path.insert(0, str(pkg.parent))
from triage.build_graph import build_graph

for d in ('snapshots', 'graphs', 'embeddings'):
    (OUT / d).mkdir(exist_ok=True)


def hashed(text, dim=256):
    """Placeholder embedding: hashed identifier counts, L2-normalised (only used to enable the graph tools)."""
    v = np.zeros(dim, np.float32)
    for tok in re.findall(r'[A-Za-z_][A-Za-z0-9_]*', text or ''):
        v[zlib.crc32(tok.lower().encode()) % dim] += 1
    n = np.linalg.norm(v)
    return v / n if n else v


def git(*args, cwd):
    subprocess.run(['git', *args], cwd=cwd, check=True, capture_output=True, text=True)


rows, t0 = [], time.time()
for t in TASKS:
    work = Path(tempfile.mkdtemp(prefix='ext_'))
    name = f"{t['repo'].split('/')[-1]}_{t['base_commit']}"
    try:
        git('init', '-q', cwd=work)
        git('remote', 'add', 'origin', f"https://github.com/{t['repo']}.git", cwd=work)
        git('fetch', '-q', '--depth', '1', 'origin', t['base_commit'], cwd=work)
        git('checkout', '-q', '-B', 'main', 'FETCH_HEAD', cwd=work)
        subprocess.run(['tar', '-czf', str(OUT / 'snapshots' / f"{t['instance_id']}.tgz"), '-C', str(work), '.'], check=True)
        g = build_graph(work, name)
        (OUT / 'graphs' / f'{name}.json').write_text(json.dumps(g))
        np.savez_compressed(OUT / 'embeddings' / f'{name}.npz', **{n['name']: hashed(n['name'] + ' ' + n['text']) for n in g['nodes']})
        rows.append(t)
        print(f"[{len(rows)}/{len(TASKS)}] {t['instance_id']}: {len(g['nodes'])} nodes, {len(g['edges'])} edges", flush=True)
    except subprocess.CalledProcessError as e:
        print(f"{t['instance_id']}: FAILED {e.cmd} {e.stderr[-300:]}", flush=True)
    finally:
        shutil.rmtree(work, ignore_errors=True)
(OUT / 'tasks.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows))
print(f'{len(rows)} tasks in {(time.time() - t0) / 60:.1f} min')
'''


def select(parquet: bytes, per_repo: int, seed: int) -> list[dict]:
    import pandas as pd
    df = pd.read_parquet(io.BytesIO(parquet))
    rng = random.Random(seed)
    picked = []
    for repo in REPOS:
        ids = sorted(df.loc[df["repo"] == repo, "instance_id"])
        picked += rng.sample(ids, per_repo)
    rows = df.set_index("instance_id").loc[picked].reset_index()
    return [{k: (str(r[k]) if r[k] is not None else "") for k in FIELDS} for _, r in rows.iterrows()]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--owner", required=True)
    ap.add_argument("--per-repo", type=int, default=5)
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--slug", default="gemma4-ext-tasks")
    args = ap.parse_args()
    parquet = urllib.request.urlopen(URL, timeout=120).read()
    digest = hashlib.sha256(parquet).hexdigest()
    tasks = select(parquet, args.per_repo, args.seed)
    local = ROOT / "results" / "ext"
    local.mkdir(parents=True, exist_ok=True)
    (local / "tasks.jsonl").write_text("".join(json.dumps(t) + "\n" for t in tasks))
    (local / "selection.json").write_text(json.dumps({"source": URL, "sha256": digest, "seed": args.seed,
                                                      "per_repo": args.per_repo, "repos": REPOS,
                                                      "instance_ids": [t["instance_id"] for t in tasks]}, indent=1))
    package = {p.name: p.read_text() for p in (ROOT / "triage").glob("*.py")}
    params = f"TASKS = {json.dumps(tasks)}\nPACKAGE = {json.dumps(package)}\n"
    nb = {"cells": [md_cell(f"# {len(tasks)} SWE-bench Verified issues as harness tasks\n\nGenerated by "
                            "`eval/make_ext_tasks_notebook.py`. Snapshots at each base commit, our own code graphs, "
                            "placeholder embeddings. CPU only, needs internet."), code_cell(params), code_cell(BUILD_CELL)],
          "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
                       "language_info": {"name": "python"}},
          "nbformat": 4, "nbformat_minor": 5}
    out = ROOT / "notebooks" / args.slug
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{args.slug}.ipynb").write_text(json.dumps(nb, indent=1) + "\n", encoding="utf-8")
    meta = {"id": f"{args.owner}/{args.slug}", "title": args.slug, "code_file": f"{args.slug}.ipynb",
            "language": "python", "kernel_type": "notebook", "is_private": True, "enable_gpu": False,
            "enable_tpu": False, "enable_internet": True, "dataset_sources": [], "competition_sources": [],
            "kernel_sources": [], "model_sources": []}
    (out / "kernel-metadata.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {out}/ and {local}/tasks.jsonl: {len(tasks)} issues (sha256 {digest[:12]}), "
          + ", ".join(f"{r.split('/')[1]} {sum(t['repo'] == r for t in tasks)}" for r in REPOS))


if __name__ == "__main__":
    main()
