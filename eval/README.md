# Evaluation: rebuild every number in the paper

The labels and scores are derived from the Gemma 4 Developer Agent competition data, which may not be
redistributed. So this folder ships the scripts, not their outputs. Everything below runs on CPU,
except the agent runs themselves.

## 1. Data

Accept the competition rules, then download the data into `data/` (gitignored):

```bash
kaggle competitions download gemma-4-developer-agent -p data && (cd data && unzip -q gemma-4-developer-agent.zip)
pip install numpy data/wheelhouse/swegemma-*.whl   # swegemma only for the harness search-tool baseline
```

The scripts read `data/tasks.jsonl`, `data/graphs/` and `data/embeddings/`. Without `swegemma`, pass
`--no-graph-tool` to `triage_localize.py`. That drops one baseline row.

## 2. Labels and retrieval baselines (RQ1–RQ3)

```bash
python eval/make_split.py --tasks data/tasks.jsonl --dev 40 --holdout 20   # seed 2026: same split every time
python eval/triage_labels.py                                               # results/triage/labels.jsonl
python eval/triage_localize.py --subset dev     --out results/triage/localize_dev_all.jsonl
python eval/triage_localize.py --subset holdout --out results/triage/localize_holdout_all.jsonl
python eval/triage_localize.py                  --out results/triage/localize.jsonl   # all 129 tasks
```

`make_split.py` records the SHA-256 of `tasks.jsonl`. If yours differs, the split will too.

## 3. Agent runs

Each run of an agent in the competition harness (Kaggle, Gemma 4 4-bit on vLLM) is downloaded as
`results/<run>/results/<run>/` with `task_results.jsonl`, `patches/<task>.patch` (the agent's
`TRIAGE/` files) and `traces/trace_<task>.json`. Every run uses the budget in `eval_config.yaml`
(24 tool calls, 8 minutes per issue). The paper's runs:

| Run | Agent | Issues | Paper |
|---|---|---|---|
| `triage_dev_r1`, `triage_hold_r1` | `agent/`, Gemma 4 31B on 4×L4 | 40 dev, 20 holdout | §4.1–4.5 |
| `triage_multi_dev_r1`, `triage_multi_hold_r1` | `agent_multi/` (localizer → reproducer), 31B | the same 60 | §4.6 |
| `triage_ext_r1` | `agent/`, 31B | 30 outside issues (section 5) | §4.7 |
| `triage_e4b_dev_r1`, `triage_e4b_hold_r1` | `agent/` with `model: gemma-4-e4b-it-qat-w4a16-ct`, one L4 | the same 60 | §4.8 |
| `triage_dev_r2`, `triage_hold_r2` | `agent/`, 31B, run again | the same 60 | §4.9 |

Each run is one Kaggle notebook built by `notebooks/make_demo_notebook.py`, the same notebook as the
public demo, with the paper's issue order (round-robin across repositories) and four issues at a time:

```bash
python notebooks/make_demo_notebook.py --owner <kaggle_user> --subset dev --run-name triage_dev_r1 --slug triage-run
kaggle kernels push -p notebooks/triage-run                     # GPU: about 1 h on 4×L4 for 40 issues
kaggle kernels output <kaggle_user>/triage-run -p results/triage_dev_r1
```

Holdout: `--subset holdout`. Two agents: `--agent agent_multi`. E4B: `--model gemma-4-e4b-it-qat-w4a16-ct
--gpus 1`. Outside issues: `--ext-data <kaggle_user>/gemma4-ext-tasks` (section 5). Kaggle charges L4 time
double, so a 40-issue run costs about 2 h of the 30-hour weekly GPU quota. Sampling is not seeded: a new
run gives numbers like the paper's, not identical ones (§4.9 measures the spread). Everything after the
agent run is deterministic.

## 4. Scoring the agent and the orchestrator

```bash
python eval/triage_reports.py triage_dev_r1  --out results/triage/reports_triage_dev_r1.jsonl    # raw agent
python eval/triage_reports.py triage_hold_r1 --out results/triage/reports_triage_hold_r1.jsonl
python eval/make_repro_check_notebook.py --owner <kaggle_user> triage_dev_r1 triage_hold_r1
kaggle kernels push -p notebooks/gemma4-repro-check            # CPU notebook, no GPU quota
kaggle kernels output <kaggle_user>/gemma4-repro-check -p results/repro_check
python eval/triage_pipeline.py triage_dev_r1 triage_hold_r1    # orchestrator: reports + summary.jsonl
python eval/paper_stats.py                                     # leakage split, McNemar tests, fallbacks
python eval/check_package.py                                   # the shipped triage/ package gives the same reports
```

The other runs use the same scripts. Run the orchestrator on one run at a time to get dev and holdout
numbers separately:

```bash
for r in triage_dev_r2 triage_hold_r2 triage_e4b_dev_r1 triage_e4b_hold_r1 triage_multi_dev_r1 triage_multi_hold_r1; do
  python eval/triage_reports.py $r --out results/triage/reports_$r.jsonl   # also prints existing files modified
done
python eval/triage_pipeline.py triage_dev_r2  --out-dir results/triage/pipeline_r2
python eval/triage_pipeline.py triage_hold_r2 --out-dir results/triage/pipeline_r2
python eval/triage_pipeline.py triage_e4b_dev_r1 triage_e4b_hold_r1 --out-dir results/triage/pipeline_e4b \
    --repro-check results/repro_check_e4b/repro_check.jsonl
python eval/triage_pipeline.py triage_multi_dev_r1 triage_multi_hold_r1 --out-dir results/triage/pipeline_multi \
    --repro-check results/repro_check_multi/repro_check.jsonl
python eval/paper_stats.py --compare results/triage/pipeline_multi/summary.jsonl \
    --compare-runs triage_multi_dev_r1 triage_multi_hold_r1
```

The repro checks for E4B and the localizer → reproducer come from `make_repro_check_notebook.py` with
those runs, downloaded to `results/repro_check_e4b/` and `results/repro_check_multi/`.

## 5. Issues from other projects (§4.7)

30 SWE-bench Verified issues, five each from Django, SymPy, Sphinx, xarray, pytest and pylint (seed 2026),
with snapshots at the base commit and our own code graphs. These need no competition data.

```bash
python eval/make_ext_tasks_notebook.py --owner <kaggle_user>   # also writes results/ext/tasks.jsonl
kaggle kernels push -p notebooks/gemma4-ext-tasks             # CPU, internet on, about 20 minutes
kaggle kernels output <kaggle_user>/gemma4-ext-tasks -p results/ext_data
E=(--tasks results/ext/tasks.jsonl --graphs results/ext_data/graphs)
python eval/triage_labels.py "${E[@]}" --out results/triage/labels_ext.jsonl
python eval/triage_localize.py "${E[@]}" --labels results/triage/labels_ext.jsonl --no-graph-tool \
    --out results/triage/localize_ext.jsonl
python eval/triage_reports.py triage_ext_r1 "${E[@]}" --labels results/triage/labels_ext.jsonl \
    --out results/triage/reports_triage_ext_r1.jsonl
python eval/triage_pipeline.py triage_ext_r1 "${E[@]}" --labels results/triage/labels_ext.jsonl \
    --retrieval results/triage/localize_ext.jsonl --out-dir results/triage/pipeline_ext
```

The agent run `triage_ext_r1` comes from `python notebooks/make_demo_notebook.py --owner <kaggle_user>
--ext-data <kaggle_user>/gemma4-ext-tasks --run-name triage_ext_r1 --slug triage-run` (section 3). There is no repro check for these issues: each project needs
its own environment.

The repro check runs every `TRIAGE/repro.py` before and after the reference fix. It uses the same
pinned Kaggle image as the agent runs, because the latest image's Starlette breaks these FastAPI
snapshots.

## Where each result comes from

| Paper | Script → file |
|---|---|
| Table 1, retrieval rows | `triage_localize.py` → `localize_*_all.summary.json` → `localization` |
| Table 1, agent row; "right whenever it wrote a report" | `triage_reports.py` → `reports_*.jsonl` (`loc_rank`, `has_report`) |
| Table 1, orchestrator row | `triage_pipeline.py` → `pipeline/summary.jsonl` |
| Table 1 last row (issues that do not name the file), McNemar tests, fallback accuracy and retrieval on the same issues, repository sizes (§4.4), embedding vs call-edge neighbours (§4.2), repro scripts that print instead of assert | `paper_stats.py` |
| Table 2 | `triage_localize.py` (`test_selection`), `triage_reports.py`, `triage_pipeline.py` (`test_rank`) |
| §4.4 reproduction verdicts and precision | `results/repro_check/repro_check.jsonl`; `triage_pipeline.py` prints both precisions |
| §4.5 confidence on triage reports | `triage_pipeline.py` (confidence → location hit@1) |
| Our own graph instead of the competition's (§4.2) | `make_graphs_notebook.py` (CPU, builds `triage/build_graph.py` graphs from the snapshots) → `results/graphs_ast/`; then the commands above with `--graphs results/graphs_ast` (and `--no-graph-tool` for `triage_localize.py`) |
| §4.6 one agent vs localizer → reproducer | `paper_stats.py --compare <other pipeline summary.jsonl> --compare-runs <dev run> <holdout run>`; runs that hit the 8-minute limit: `error` is "Agent exceeded session timeout" in the runs' `task_results.jsonl` |
| §4.7 other projects | section 5: `localize_ext.summary.json` (retrieval), `triage_reports.py` (agent alone, files outside `TRIAGE/`), `triage_pipeline.py` (orchestrator, confidence) |
| §4.8 E4B | `triage_reports.py` (agent alone, scripts written, existing files modified), `triage_pipeline.py` with `repro_check_e4b` (orchestrator, verified reproductions) |
| §4.9 second run | `triage_reports.py` and `triage_pipeline.py` on `triage_dev_r2`, `triage_hold_r2` |
| Runs that modified an existing file (§3, §4.6, §4.8, §4.9, Limitations) | `triage_reports.py`: "existing files modified" (changed or deleted, not newly created) |
| Abstract: HIGH or MEDIUM right 73 of 74 | the confidence line of `triage_pipeline.py` for the first run (29/29), the other projects (16/16) and the second run (28/29) |

`triage_agent_baseline.py` computes the same localization and test metrics from any run's traces
(the order in which the agent opened files). We used it on earlier fixing-agent runs.

A fresh clone of this repository, given the competition data and the first run's folders, reproduces
the authors' outputs byte for byte (checked 2026-11-01): retrieval, agent reports, the orchestrator's
summary and the output of `paper_stats.py`. `labels.jsonl` then differs only in the optional `sound`
field, because the soundness file is not shipped. Results do not depend on Python's hash seed.
