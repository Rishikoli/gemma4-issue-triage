# Gemma 4 Issue Triage

**Locate the bug, find the tests, reproduce it — offline, before a human looks. Never auto-fix.**

> Work in progress for the Gemma 4 Developer Agent Paper Track. Demo, results and a runnable notebook
> are coming; see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the design.

<p align="center"><img src="docs/architecture.svg" alt="Architecture: a Gemma 4 localizer and CPU retrieval agree on a confidence level; a Gemma 4 reproducer and a call-graph test finder follow; a template writes the report; the maintainer decides." width="100%"></p>

When a new issue is filed, a maintainer's first hour goes to three questions: *where in the code is
it, which tests cover that code, and can I reproduce it?* This tool answers them with an offline
Gemma 4 agent and the repository's code graph, then hands the report to the maintainer with a
confidence level. It writes no fix: in our measurements, agents that find the right file still get
the fix wrong surprisingly often, and their own tests rarely notice.

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
| `triage/` | Deterministic steps: call-graph test finder, agreement-based confidence |
| `notebooks/` | Runnable demo |
| `eval/` | Rebuild labels from the competition data and score reports |
| `adapters/` | LoRA adapters (planned) |
| `docs/` | Architecture, figures, example reports |

No competition data, labels or traces are included; the evaluation scripts rebuild them for anyone
with access to the competition data.

## License

Apache 2.0.
