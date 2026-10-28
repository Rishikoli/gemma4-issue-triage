# Gemma 4 Issue Triage

**Locate the bug, find the tests, reproduce it — offline, before a human looks. Never auto-fix.**

> Work in progress for the Gemma 4 Developer Agent Paper Track. A demo and a runnable notebook
> are coming; see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the design.

<p align="center"><img src="docs/architecture.svg" alt="Animated architecture: one offline Gemma 4 triage agent investigates the issue and writes notes, a reproduction script and a trace; a deterministic orchestrator checks them in five steps (fallback, retrieval, agreement confidence, call-graph tests, re-running the reproduction) and fills the report the maintainer decides on." width="100%"></p>

When a new issue is filed, a maintainer's first hour goes to three questions: *where in the code is
it, which tests cover that code, and can I reproduce it?* This tool answers them with an offline
Gemma 4 agent and the repository's code graph, then hands the report to the maintainer with a
confidence level. It writes no fix: in our measurements, agents that find the right file still get
the fix wrong surprisingly often, and their own tests rarely notice.

## Example

<p align="center"><img src="docs/hero.png" alt="FastAPI issue 14458: Gemma 4's triage report points to fastapi/dependencies/models.py, lists tests/test_dependency_class.py and includes a failing reproduction; the merged fix changed that file, added tests there, and makes the reproduction pass." width="100%"></p>

## Results so far

<p align="center"><img src="docs/results.png" alt="Top-1 accuracy. Finding the file to fix: BM25 38% dev / 25% holdout, the harness code-search tool 28/40, BM25 with embeddings 28/30, BM25 with call-graph spreading 42/30, the Gemma 4 triage agent 75/55, agent plus orchestrator 92/90. Finding the test file: BM25 22/50, agent 48/25, agent plus orchestrator with call-graph tests 65/55." width="100%"></p>

Gemma 4 31B, one run on 40 dev and 20 holdout issues from the competition's repositories. The agent's
prompt was written from dev issues only; the orchestrator's rules were chosen after this run, so the
next runs, with the orchestrator frozen, are its clean test. Regenerate the figure with
`python docs/make_results_chart.py`.

## What you get per issue

- **Suspected location**: ranked files and functions, with evidence
- **Tests to run**: existing tests that exercise that code
- **Reproduction**: a small script that fails while the bug is present
- **Confidence**: HIGH / MEDIUM / LOW, so maintainers know which reports to trust
- **Open questions**: what the agent could not determine

## Layout

| Path | What |
|---|---|
| `agent/` | The triage agent: config, prompt, sampling, per-issue budget (24 tool calls, 8 minutes) |
| `triage/` | Deterministic steps around the agents: retrieval (BM25 + call-graph spreading), agreement-based confidence, call-graph test finder, a reproduction check that re-runs the script, the report writer (`python -m triage.orchestrate`), and a code-graph builder for any Python repository (`python -m triage.build_graph`) |
| `tests/` | Self-contained tests (`python -m pytest tests`) |
| `notebooks/` | `make_demo_notebook.py`: a Kaggle notebook that triages real issues end to end with Gemma 4 and prints the maintainer's reports |
| `eval/` | Rebuild the labels, baselines and every number in the paper from the competition data ([eval/README.md](eval/README.md)) |
| `adapters/` | LoRA adapters (planned) |
| `docs/` | Architecture, figures, example reports |

No competition data, labels or traces are included; the evaluation scripts rebuild them for anyone
with access to the competition data.

## License

Apache 2.0.
