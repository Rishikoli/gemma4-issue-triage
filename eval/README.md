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

Each run of `agent/` in the competition harness (Kaggle, 4×L4, Gemma 4 31B) is downloaded as
`results/<run>/results/<run>/` with `task_results.jsonl`, `patches/<task>.patch` (the agent's
`TRIAGE/` files) and `traces/trace_<task>.json`. The paper's runs are `triage_dev_r1` (40 dev issues)
and `triage_hold_r1` (20 holdout issues).

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

The repro check runs every `TRIAGE/repro.py` before and after the reference fix. It uses the same
pinned Kaggle image as the agent runs, because the latest image's Starlette breaks these FastAPI
snapshots.

## Where each result comes from

| Paper | Script → file |
|---|---|
| Table 1, retrieval rows | `triage_localize.py` → `localize_*_all.summary.json` → `localization` |
| Table 1, agent row; "right whenever it wrote a report" | `triage_reports.py` → `reports_*.jsonl` (`loc_rank`, `has_report`) |
| Table 1, orchestrator row | `triage_pipeline.py` → `pipeline/summary.jsonl` |
| Leakage split, McNemar tests, fallback accuracy, repro scripts that print instead of assert | `paper_stats.py` |
| Table 2 | `triage_localize.py` (`test_selection`), `triage_reports.py`, `triage_pipeline.py` (`test_rank`) |
| §4.4 reproduction verdicts and precision | `results/repro_check/repro_check.jsonl`; `triage_pipeline.py` prints both precisions |
| §4.5 confidence on triage reports | `triage_pipeline.py` (confidence → location hit@1) |

`triage_agent_baseline.py` computes the same localization and test metrics from any run's traces
(the order in which the agent opened files). We used it on earlier fixing-agent runs.

Two independent checkouts (the authors' working repository and this one) produce byte-identical
outputs for every file above. Results do not depend on Python's hash seed.
