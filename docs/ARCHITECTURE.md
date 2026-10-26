# Architecture

Offline issue triage with Gemma 4: when a new issue arrives, answer the maintainer's first three
questions (where is it, which tests cover it, can it be reproduced) before a human looks, on one
machine, without writing a fix.

```
 GitHub issue
     │
     ▼
 ┌─────────────────────────── Orchestrator (Python, deterministic) ───────────────────────────┐
 │                                                                                            │
 │  ① Localizer agent (Gemma 4)        ② Retrieval (CPU, no model)                            │
 │     read-only: grep, read files        BM25 + call-graph spreading                         │
 │     → ranked suspect files/functions   → ranked suspects                                   │
 │              └──────────────┬──────────────┘                                               │
 │                             ▼                                                              │
 │  ③ Agreement → confidence  HIGH · MEDIUM · LOW                                             │
 │                             ▼                                                              │
 │  ④ Reproducer agent (Gemma 4, fresh context)   ⑤ Test finder (call graph, CPU)             │
 │     writes + runs TRIAGE/repro.py                 tests that call the suspect code         │
 │     → REPRODUCED / NOT_REPRODUCED                 → tests to run                           │
 │                             └──────────────┬──────────────┘                                │
 │                                            ▼                                               │
 │  ⑥ Report writer (template) → report.md: location · tests · repro · confidence · questions │
 └────────────────────────────────────────────┬───────────────────────────────────────────────┘
                                              ▼
        ⑦ Human in the loop (maintainer)
           HIGH → draft comment; the maintainer approves or edits it
           LOW / not reproduced → review queue, with the agent's open questions
           maintainer's answer → re-run ① / ④ with the hint (one loop)
```

## Components

| # | Component | Kind | Why it is built this way |
|---|---|---|---|
| ① | Localizer agent | Gemma 4, read-only tools | The model finds the right file far more often than retrieval (first file opened: 77% vs 39% top-1 on our dev tasks) |
| ② | Retrieval | BM25 + call-graph spreading over the repository's code graph | Independent second opinion; call edges add 5 points over plain BM25 |
| ③ | Confidence | Agreement between ① and ② | When they agree the localizer is right 98% of the time; when they differ, 59% |
| ④ | Reproducer agent | Gemma 4, separate context | A failing script is the strongest evidence for a maintainer; a fresh context keeps it focused |
| ⑤ | Test finder | Call graph: test functions that call the suspect module | The model alone touches the right test file 25% of the time; adding call edges raises it to 39% |
| ⑥ | Report writer | Template | Fixed format, nothing invented |
| ⑦ | Human in the loop | Maintainer | The tool never edits code; it routes work by confidence |

Numbers are from the authors' runs on the Gemma 4 Developer Agent competition tasks and will be
updated as the full evaluation lands.

## Where it runs

- **Reference:** Gemma 4 31B (4-bit) on 4×L4 (Kaggle), served with vLLM.
- **Consumer GPU:** the same pipeline with Gemma 4 12B or E4B on one RTX-class GPU.
- Fully offline: no code leaves the machine.

## Post-training (planned)

A LoRA adapter for the localizer, trained on labels derived from reference fixes of tasks never used
for evaluation, and only on Gemma's own outputs (no data from other models).
