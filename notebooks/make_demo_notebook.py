#!/usr/bin/env python3
"""Build a Kaggle notebook that triages a few real issues end to end and shows the maintainer's report.

The notebook runs the triage agent (agent/) with Gemma 4 on vLLM inside the competition harness, then
runs the deterministic orchestrator (triage/) on each issue's workspace: retrieval, agreement
confidence, call-graph tests, and a reproduction check that executes the agent's script. Each
final report is printed as Markdown and saved to /kaggle/working/triage_reports/.

Needs a Kaggle account that has joined the Gemma 4 Developer Agent competition (for its data and
harness wheels). Uses GPU quota: about 0.5 h for three issues on 4x L4 (Kaggle charges L4 time double).

Usage:
    python notebooks/make_demo_notebook.py --owner <kaggle_user> [--tasks fastapi_14458 rich_3130 ...]
        [--model gemma-4-e4b-it-qat-w4a16-ct --gpus 1]
    kaggle kernels push -p notebooks/triage-demo

The same notebook produces the paper's agent runs: --subset dev or holdout takes the issues from
results/split.json, --agent agent_multi selects the two-agent variant, and --run-name puts the harness
output where eval/ expects it (kaggle kernels output <kaggle_user>/<slug> -p results/<run-name>).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODELS = ("gemma-4-31b-it-qat-w4a16-ct", "gemma-4-12b-it-qat-w4a16-ct", "gemma-4-e4b-it-qat-w4a16-ct",
          "gemma-4-e2b-it-qat-w4a16-ct")
# The Kaggle image the competition harness was tested with, pinned: newer images ship a Starlette that
# breaks these FastAPI snapshots.
DOCKER_IMAGE = "gcr.io/kaggle-private-byod/python@sha256:37c64f7dd9c54116ecd1bcc88817c5469b88387388fade02bfa8bf3fc647d461"
# Dev issues where the evaluated run found the file, the tests and a verified reproduction (one per repository).
DEFAULT_TASKS = ["fastapi_14458", "rich_3130", "requests_7502"]

SETUP_CELL = r'''
import glob, json, logging, os, re, shutil, subprocess, sys, tempfile, time
from pathlib import Path

os.environ.update({
    'TRANSFORMERS_NO_TF': '1', 'TRANSFORMERS_NO_FLAX': '1', 'TRANSFORMERS_OFFLINE': '1',
    'VLLM_NO_USAGE_STATS': '1', 'VLLM_WORKER_MULTIPROC_METHOD': 'spawn',
    'VLLM_ENGINE_READY_TIMEOUT_S': '1200', 'VLLM_MEMORY_PROFILER_ESTIMATE_CUDAGRAPHS': '1',
    'NCCL_DEBUG': 'WARN', 'LITELLM_LOCAL_MODEL_COST_MAP': 'True', 'LITELLM_TELEMETRY': 'False',
    'LITELLM_LOG': 'WARNING', 'PYTORCH_CUDA_ALLOC_CONF': 'expandable_segments:True',
    'OTEL_SDK_DISABLED': 'true', 'OTEL_PYTHON_DISABLED': 'true',
})
os.environ.setdefault('OPENAI_API_KEY', 'EMPTY')
os.environ.setdefault('LOCAL_API_KEY', 'EMPTY')


def quiet_logs():
    for name in ('LiteLLM', 'LiteLLM Router', 'litellm', 'httpx', 'httpcore', 'openai', 'urllib3', 'opentelemetry'):
        lg = logging.getLogger(name)
        lg.setLevel(logging.WARNING)
        if 'litellm' in name.lower():
            lg.propagate = False
            lg.handlers.clear()


def find_input(*candidates):
    for c in candidates:
        if Path(c).exists():
            return Path(c)
    raise FileNotFoundError(f'None of these inputs are attached: {candidates}')


WHEELHOUSE_DIR = find_input('/kaggle/input/datasets/metric/gemma-4-developer-agent-wheelhouse',
                            '/kaggle/input/gemma-4-developer-agent-wheelhouse')
DATA_DIR = find_input('/kaggle/input/competitions/gemma-4-developer-agent', '/kaggle/input/gemma-4-developer-agent')
WORKING_DIR = Path('/kaggle/working')

# The harness wheels, installed the way the competition's getting-started notebook does
for pth in glob.glob('/usr/local/lib/python*/dist-packages/*cutlass*.pth'):
    try:
        os.unlink(pth)
    except OSError:
        pass
tmp_whl = Path('/tmp/wheelhouse')
tmp_whl.mkdir(parents=True, exist_ok=True)
for w in WHEELHOUSE_DIR.glob('*.whl'):
    if 'cutlass' not in w.name.lower():
        target = tmp_whl / (w.name.replace('cu128', '+cu128') if ('cu128' in w.name and '+' not in w.name) else w.name)
        if not target.exists():
            os.symlink(w, target)
subprocess.run([sys.executable, '-m', 'pip', 'install', '-q', '--no-deps', '--force-reinstall',
                *sorted(str(w) for w in tmp_whl.glob('*.whl'))], check=True)
quiet_logs()
print(subprocess.run(['nvidia-smi', '--query-gpu=index,name,memory.total', '--format=csv'],
                     capture_output=True, text=True).stdout)
'''

AGENT_CELL = r'''
from adk_submission import discover_adapters, validate_directory
from swegemma.config import ALLOWED_ADAPTER_EXTENSIONS, build_submission_limits

AGENT_DIR = WORKING_DIR / 'agent'
shutil.rmtree(AGENT_DIR, ignore_errors=True)
for rel, text in AGENT_FILES.items():
    (AGENT_DIR / rel).parent.mkdir(parents=True, exist_ok=True)
    (AGENT_DIR / rel).write_text(text, encoding='utf-8')
limits, gen_constraints = build_submission_limits()
validate_directory(AGENT_DIR, limits=limits)
adapters = discover_adapters(str(AGENT_DIR), adapter_extensions=ALLOWED_ADAPTER_EXTENSIONS)
adapter_map = getattr(adapters, 'adapters', None) or {}
print(f'Triage agent OK: model={MODEL_NAME}, adapters={sorted(adapter_map) or "none"}')
'''

VLLM_CELL = r'''
if GPUS:  # a maintainer's smaller machine: the model server sees only the first GPUS devices
    os.environ['CUDA_VISIBLE_DEVICES'] = ','.join(str(i) for i in range(GPUS))
import litellm
import torch
from adk_submission import VllmConfig, VllmServer

litellm.drop_params = True
MODEL_PATH = find_input(f'/kaggle/input/models/google/gemma-4/other/{MODEL_NAME}/2',
                        f'/kaggle/input/gemma-4/other/{MODEL_NAME}/2')
gpu_count = torch.cuda.device_count()
tp_size = 4 if gpu_count >= 4 else (2 if gpu_count >= 2 else 1)
t0 = time.time()
server = VllmServer(VllmConfig(
    model=str(MODEL_PATH), port=8000, host='127.0.0.1',
    tool_call_parser='gemma4', reasoning_parser='gemma4', max_model_len=32768,
    dtype='bfloat16' if torch.cuda.is_bf16_supported() else 'auto', gpu_memory_utilization=0.90,
    enable_auto_tool_choice=True, enable_lora=bool(adapter_map), max_loras=max(1, len(adapter_map)),
    max_lora_rank=128, scheduler_reserve_full_isl=False, tensor_parallel_size=tp_size, startup_timeout=60 * 20,
    extra_args=(('--hf-overrides', '{"architectures": ["Gemma4ForCausalLM"], "model_type": "gemma4"}')
                if MODEL_NAME.startswith('gemma-4-12b') else ()),
), adapter_manifest=adapters)
server.start()
print(f'vLLM ready with {MODEL_NAME} on {gpu_count} GPU(s) in {(time.time() - t0) / 60:.1f} min')
models = server.create_model_registry(aliases=[MODEL_NAME], model_prefix='openai/',
                                      api_key=os.environ.get('LOCAL_API_KEY', 'EMPTY'))
'''

RUN_CELL = r'''
import asyncio
import concurrent.futures
import yaml
from google.adk.agents.context_cache_config import ContextCacheConfig
from google.adk.apps._configs import EventsCompactionConfig
from swegemma.config import EvalConfig
from swegemma.evaluate import Evaluator
from swegemma.models import load_tasks

budget = yaml.safe_load((AGENT_DIR / 'eval_config.yaml').read_text())['evaluation']
# Issues from outside the competition (eval/make_ext_tasks_notebook.py): tasks, snapshots and graphs come from
# that notebook's output; the harness wheels still come from the competition data.
TASK_DIR = (find_input(f'/kaggle/input/notebooks/{EXT_DATA}', f"/kaggle/input/{EXT_DATA.split('/')[-1]}")
            if EXT_DATA else DATA_DIR)
all_tasks = {t.instance_id: t for t in load_tasks(TASK_DIR / 'tasks.jsonl')}
TASKS = [all_tasks[i] for i in TASK_IDS]
RESULTS_DIR = WORKING_DIR / 'results' / RUN_NAME
shutil.rmtree(RESULTS_DIR, ignore_errors=True)
RESULTS_DIR.mkdir(parents=True)
evaluator = Evaluator(EvalConfig(
    tasks_path=TASK_DIR / 'tasks.jsonl', snapshots_dir=TASK_DIR / 'snapshots', results_dir=RESULTS_DIR,
    submission_dir=AGENT_DIR, models=models, sandbox='subprocess', limits=limits,
    generation_constraints=gen_constraints, adapter_manifest=adapters,
    # same context settings as the competition scorer and our evaluated runs
    context_cache_config=ContextCacheConfig(min_tokens=2048, ttl_seconds=1800, cache_intervals=10),
    events_compaction_config=EventsCompactionConfig(
        compaction_interval=15, overlap_size=2, token_threshold=14336, event_retention_size=5),
    graph_dir=str(TASK_DIR / 'graphs'), embeddings_dir=str(TASK_DIR / 'embeddings'), wheels_dir=DATA_DIR / 'wheels',
    verbose=False, timeout_seconds=int(budget['timeout_seconds']), max_tool_calls=int(budget['max_tool_calls']),
    max_time_minutes=float(budget['max_time_minutes']), max_turns=int(budget['max_turns']),
    verification_timeout_seconds=60,  # the harness also runs the hidden tests; triage ignores them
))


async def run_all():
    sem = asyncio.Semaphore(4)

    async def one(i, task):
        async with sem:
            res = await evaluator.evaluate_task(task, task_index=i, total_tasks=len(TASKS))
            print(f'{task.instance_id}: agent done in {res.duration_seconds / 60:.1f} min, {res.tool_calls} tool calls',
                  flush=True)
            return res
    return await asyncio.gather(*(one(i, t) for i, t in enumerate(TASKS, 1)))


with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:  # the notebook already runs an event loop
    results = pool.submit(lambda: asyncio.run(run_all())).result()
server.stop()
'''

TRIAGE_CELL = r'''
from IPython.display import Markdown, display

PKG_DIR = WORKING_DIR / 'triage_pkg'
for rel, text in TRIAGE_PACKAGE.items():
    (PKG_DIR / 'triage' / rel).parent.mkdir(parents=True, exist_ok=True)
    (PKG_DIR / 'triage' / rel).write_text(text, encoding='utf-8')
sys.path.insert(0, str(PKG_DIR))
from triage.graph import CodeGraph
from triage.orchestrate import triage
from triage.trace import opened_modules

REPORTS = WORKING_DIR / 'triage_reports'
REPORTS.mkdir(exist_ok=True)
for res in results:
    task = all_tasks[res.instance_id]
    ws = Path(tempfile.mkdtemp(prefix=f'{task.instance_id}_'))
    subprocess.run(['tar', '-xzf', str(TASK_DIR / 'snapshots' / f'{task.instance_id}.tgz'), '-C', str(ws)], check=True)
    patch = (res.agent_patch or '').strip()
    if patch:  # the agent's TRIAGE/ notes; it may not touch anything else
        (ws / 'agent.patch').write_text(patch + '\n')
        r = subprocess.run(['git', 'apply', '--whitespace=nowarn', 'agent.patch'], cwd=ws, capture_output=True, text=True)
        if r.returncode:
            print(f'{task.instance_id}: could not apply the agent patch: {r.stderr[:200]}')
    trace = next(RESULTS_DIR.rglob(f'trace_{task.instance_id}.json'), None)
    opened = opened_modules(json.loads(trace.read_text())) if trace else None
    graph = CodeGraph.load(TASK_DIR / 'graphs' / f"{task.repo.split('/')[-1]}_{task.base_commit}.json")
    report, info = triage(ws, task.problem_statement, graph, opened_files=opened)
    (REPORTS / f'{task.instance_id}.md').write_text(report)
    display(Markdown(f'---\n**Issue `{task.instance_id}`** ({task.repo}): {task.problem_statement.strip()[:300]}...\n\n' + report))
'''


def code_cell(src: str) -> dict:
    return {"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [],
            "source": src.strip("\n").splitlines(keepends=True)}


def md_cell(src: str) -> dict:
    return {"cell_type": "markdown", "metadata": {}, "source": src.strip("\n").splitlines(keepends=True)}


def read_tree(base: Path, pattern: str) -> dict[str, str]:
    return {str(p.relative_to(base)): p.read_text(encoding="utf-8") for p in sorted(base.rglob(pattern))
            if p.is_file() and "__pycache__" not in p.parts}


def interleave_by_repo(ids: list[str]) -> list[str]:
    """Round-robin across repositories, the task order of the paper's runs."""
    queues = [sorted(i for i in ids if i.rsplit("_", 1)[0] == repo) for repo in sorted({i.rsplit("_", 1)[0] for i in ids})]
    return [q[k] for k in range(max(map(len, queues), default=0)) for q in queues if k < len(q)]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--owner", required=True, help="Kaggle username that will own the notebook")
    ap.add_argument("--tasks", nargs="+", default=DEFAULT_TASKS, help="competition task ids to triage")
    ap.add_argument("--model", default=MODELS[0], choices=MODELS)
    ap.add_argument("--gpus", type=int, default=0, help="expose only the first N GPUs to the model (1 = single L4)")
    ap.add_argument("--slug", default="triage-demo")
    ap.add_argument("--subset", choices=["dev", "holdout"], help="all issues of this split subset instead of --tasks")
    ap.add_argument("--split", type=Path, default=ROOT / "results" / "split.json", help="from eval/make_split.py")
    ap.add_argument("--agent", default="agent", choices=["agent", "agent_multi"], help="agent directory to run")
    ap.add_argument("--run-name", default="demo", help="harness output goes to /kaggle/working/results/<run-name>/")
    ap.add_argument("--ext-data", metavar="OWNER/SLUG", help="issues from outside the competition: the Kaggle notebook "
                    "built by eval/make_ext_tasks_notebook.py (all of its issues run)")
    ap.add_argument("--ext-tasks", type=Path, default=ROOT / "results" / "ext" / "tasks.jsonl",
                    help="with --ext-data: the local copy of its tasks.jsonl that make_ext_tasks_notebook.py wrote")
    args = ap.parse_args()
    if args.subset:  # the paper's runs: every issue of the subset, round-robin across repositories
        args.tasks = interleave_by_repo(json.loads(args.split.read_text(encoding="utf-8"))[args.subset])
    if args.ext_data:
        args.tasks = interleave_by_repo([json.loads(l)["instance_id"] for l in args.ext_tasks.read_text().splitlines()
                                         if l.strip()])

    agent = read_tree(ROOT / args.agent, "*")
    for rel in agent:  # every agent uses the same base model
        agent[rel] = agent[rel].replace(MODELS[0], args.model) if rel.endswith((".yaml", ".yml")) else agent[rel]
    params = (f"TASK_IDS = {json.dumps(args.tasks)}\nMODEL_NAME = {args.model!r}\nRUN_NAME = {args.run_name!r}\nEXT_DATA = {args.ext_data or ''!r}\n"
              f"GPUS = {args.gpus}  # 0 = all four L4s\n"
              f"AGENT_FILES = {json.dumps(agent, indent=1)}\n"
              f"TRIAGE_PACKAGE = {json.dumps(read_tree(ROOT / 'triage', '*.py'), indent=1)}\n")
    cells = [
        md_cell(f"# Offline issue triage with Gemma 4\n\nA Gemma 4 agent investigates each issue without "
                "fixing it. Deterministic code then writes the maintainer's report: suspected location, "
                "a confidence level from agreement with model-free retrieval, tests found through the call "
                "graph, and a reproduction status from actually running the agent's script.\n\n"
                f"Issues: {', '.join(f'`{t}`' for t in args.tasks)}. Model: `{args.model}`"
                f"{f' on {args.gpus} GPU(s)' if args.gpus else ''}. Generated by "
                "`notebooks/make_demo_notebook.py` in the gemma4-issue-triage repository."),
        md_cell("## Parameters"), code_cell(params),
        md_cell("## 1. Install the competition harness"), code_cell(SETUP_CELL),
        md_cell("## 2. Write and validate the triage agent"), code_cell(AGENT_CELL),
        md_cell("## 3. Serve Gemma 4 with vLLM"), code_cell(VLLM_CELL),
        md_cell("## 4. Let the agent investigate each issue"), code_cell(RUN_CELL),
        md_cell("## 5. The maintainer's reports"), code_cell(TRIAGE_CELL),
    ]
    nb = {"cells": cells, "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
                                       "language_info": {"name": "python"}}, "nbformat": 4, "nbformat_minor": 5}
    out = ROOT / "notebooks" / args.slug
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{args.slug}.ipynb").write_text(json.dumps(nb, indent=1) + "\n", encoding="utf-8")
    meta = {"id": f"{args.owner}/{args.slug}", "title": args.slug, "code_file": f"{args.slug}.ipynb",
            "language": "python", "kernel_type": "notebook", "is_private": False, "enable_gpu": True,
            "enable_tpu": False, "enable_internet": False,
            "dataset_sources": ["metric/gemma-4-developer-agent-wheelhouse"],
            "competition_sources": ["gemma-4-developer-agent"], "kernel_sources": [args.ext_data] if args.ext_data else [],
            "model_sources": [f"google/gemma-4/Other/{args.model}/2"], "machine_shape": "NvidiaL4",
            "docker_image": DOCKER_IMAGE, "docker_image_pinning_type": "original"}
    (out / "kernel-metadata.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {out}/: {len(args.tasks)} issues with {args.model}. Push (uses GPU quota): "
          f"kaggle kernels push -p {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
