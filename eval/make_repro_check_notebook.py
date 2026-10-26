#!/usr/bin/env python3
"""Build a CPU-only Kaggle notebook that verifies the triage agent's reproduction scripts (Paper 2, RQ4).

For every TRIAGE/repro.py found in the given triage runs' saved patches, the notebook extracts the
task's original snapshot, runs the script (it should FAIL: the bug is present), applies the reference
fix, and runs it again (it should PASS). Verdicts:

  verified       fails before the fix, passes after it
  passes_before  passes on the buggy code (does not reproduce the bug)
  fails_after    still fails with the fix applied (reproduces something else, or is broken)

Scripts run with the repository on PYTHONPATH and a 60 s timeout. Needs no GPU quota.

Usage:
    python eval/make_repro_check_notebook.py --owner <kaggle_user> triage_dev_r1 triage_hold_r1
    kaggle kernels push -p notebooks/gemma4-repro-check
    kaggle kernels output <kaggle_user>/gemma4-repro-check -p results/repro_check
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "eval"))
from triage_reports import files_in_patch  # noqa: E402

# The Kaggle image the agent runs used, pinned (see kernel-metadata below)
DOCKER_IMAGE = "gcr.io/kaggle-private-byod/python@sha256:37c64f7dd9c54116ecd1bcc88817c5469b88387388fade02bfa8bf3fc647d461"


def code_cell(src: str) -> dict:
    return {"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [],
            "source": src.strip("\n").splitlines(keepends=True)}


def md_cell(src: str) -> dict:
    return {"cell_type": "markdown", "metadata": {}, "source": src.strip("\n").splitlines(keepends=True)}


CHECK_CELL = r'''
import json, os, shutil, subprocess, sys, tempfile, time
from pathlib import Path

DATA_DIR = next(Path(c) for c in ('/kaggle/input/competitions/gemma-4-developer-agent',
                                  '/kaggle/input/gemma-4-developer-agent', LOCAL_DATA_DIR) if c and Path(c).exists())
OUT = Path('/kaggle/working') if Path('/kaggle/working').is_dir() else Path(LOCAL_OUT_DIR)
OUT.mkdir(parents=True, exist_ok=True)

# The repositories' runtime dependencies, from the competition's offline wheel cache
r = subprocess.run([sys.executable, '-m', 'pip', 'install', '-q', '--no-index', '--find-links', str(DATA_DIR / 'wheels'),
                    'fastapi', 'starlette', 'pydantic', 'httpx', 'rich', 'requests'], capture_output=True, text=True)
print('dependency install exit', r.returncode, r.stderr[-500:])

tasks = {t['instance_id']: t for t in map(json.loads, (DATA_DIR / 'tasks.jsonl').read_text().splitlines())}


def run_repro(work: Path) -> tuple[int, str]:
    paths = [str(work / 'src')] if (work / 'src').is_dir() else []
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(paths + [str(work)]), PYTHONDONTWRITEBYTECODE='1')
    p = subprocess.run(['timeout', '60', sys.executable, 'TRIAGE/repro.py'], cwd=work, env=env,
                       capture_output=True, text=True)
    return p.returncode, (p.stdout + p.stderr)[-500:]


rows, t0 = [], time.time()
for key, script in REPROS.items():
    run, tid = key.split('/', 1)
    work = Path(tempfile.mkdtemp(prefix='repro_'))
    try:
        subprocess.run(['tar', '-xzf', str(DATA_DIR / 'snapshots' / f'{tid}.tgz'), '-C', str(work)], check=True)
        (work / 'TRIAGE').mkdir(exist_ok=True)
        (work / 'TRIAGE' / 'repro.py').write_text(script)
        before = run_repro(work)
        (work / 'gold.patch').write_text(tasks[tid]['patch'])
        for cmd in (['git', 'apply', '--whitespace=nowarn', 'gold.patch'],
                    ['git', 'apply', '--whitespace=nowarn', '--recount', '--ignore-whitespace', 'gold.patch'],
                    ['patch', '-p1', '--batch', '--forward', '-l', '-i', 'gold.patch'],
                    ['patch', '-p0', '--batch', '--forward', '-l', '-i', 'gold.patch']):
            ap = subprocess.run(cmd, cwd=work, capture_output=True, text=True)
            if ap.returncode == 0:
                break
        after = run_repro(work) if ap.returncode == 0 else (None, 'reference patch did not apply')
        verdict = ('verified' if before[0] != 0 and after[0] == 0 else
                   'passes_before' if before[0] == 0 else 'fails_after')
        rows.append({'run': run, 'task_id': tid, 'verdict': verdict, 'exit_before': before[0], 'exit_after': after[0],
                     'out_before': before[1], 'out_after': after[1]})
    except Exception as e:
        rows.append({'run': run, 'task_id': tid, 'verdict': 'error', 'error': repr(e)[:300]})
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print(f"[{len(rows)}/{len(REPROS)}] {key}: {rows[-1]['verdict']}", flush=True)

(OUT / 'repro_check.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows))
from collections import Counter
print(json.dumps({'checked': len(rows), 'verdicts': dict(Counter(r['verdict'] for r in rows)),
                  'minutes': round((time.time() - t0) / 60, 1)}, indent=2))
'''


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--owner", required=True)
    ap.add_argument("runs", nargs="+", help="triage run names under results/")
    ap.add_argument("--slug", default="gemma4-repro-check")
    ap.add_argument("--local-data-dir", default="", help=argparse.SUPPRESS)  # for local testing
    ap.add_argument("--local-out-dir", default="", help=argparse.SUPPRESS)
    args = ap.parse_args()

    repros = {}
    for run in args.runs:
        pdir = ROOT / "results" / run / "results" / run / "patches"
        for pf in sorted(pdir.glob("*.patch")):
            script = files_in_patch(pf.read_text(errors="replace")).get("TRIAGE/repro.py")
            if script and script.strip():
                repros[f"{run}/{pf.stem}"] = script + "\n"
    if not repros:
        sys.exit("no TRIAGE/repro.py found in those runs")

    params = (f"REPROS = {json.dumps(repros, indent=1)}\n"
              f"LOCAL_DATA_DIR = {args.local_data_dir!r}\nLOCAL_OUT_DIR = {args.local_out_dir!r}\n")
    nb = {"cells": [md_cell(f"# Reproduction check: {len(repros)} triage repro scripts\n\nGenerated by "
                            "`eval/make_repro_check_notebook.py`. Runs each script on the original code "
                            "(should fail) and with the reference fix (should pass). CPU only."),
                    code_cell(params), code_cell(CHECK_CELL)],
          "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
                       "language_info": {"name": "python"}},
          "nbformat": 4, "nbformat_minor": 5}
    out = ROOT / "notebooks" / args.slug
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{args.slug}.ipynb").write_text(json.dumps(nb, indent=1) + "\n", encoding="utf-8")
    meta = {"id": f"{args.owner}/{args.slug}", "title": args.slug, "code_file": f"{args.slug}.ipynb",
            "language": "python", "kernel_type": "notebook", "is_private": True, "enable_gpu": False,
            "enable_tpu": False, "enable_internet": False, "dataset_sources": [],
            "competition_sources": ["gemma-4-developer-agent"], "kernel_sources": [], "model_sources": [],
            # same pinned image as the agent runs: Kaggle's latest image ships a Starlette too new for these
            # FastAPI snapshots (Router.__init__ rejects on_startup), which broke 16 of 56 checks
            "docker_image": DOCKER_IMAGE, "docker_image_pinning_type": "original"}
    (out / "kernel-metadata.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {out}/ with {len(repros)} repro scripts from {args.runs}")


if __name__ == "__main__":
    main()
