#!/usr/bin/env python3
"""Offline localization and test selection on the competition's code graphs (Paper 2, CPU only).

For each task with a code graph, rank the repository's modules for the issue text and score the
ranking against the reference fix (labels from eval/triage_labels.py):

  Localization (source modules)
    bm25_file   BM25 over modules (each module = the code of its functions and classes)
    bm25_node   BM25 over individual functions/classes; a module scores its best node
    graph_tool  the agent's own `search_similar_code` tool, queried with the issue title
    bm25_calls  bm25_node + scores spread along call edges (graph reasoning)
    bm25_embed  bm25_node + embedding neighbours of the top hits (the organizers' embeddings)
  Test selection (existing test modules)
    test_bm25   BM25 over test modules
    test_name   tests.test_<module> for the top-ranked source module (oracle: the gold module)
    test_calls  test modules ranked by call edges into the top-ranked source module (oracle: gold)

Metrics: hit@1/3/5 (any gold module in the top k) and MRR. Writes per-task rankings and a summary to
results/triage/ (gitignored: derived from competition data).

Usage: python eval/triage_localize.py [--subset all|dev|holdout|unused] [--sound-only]
"""
from __future__ import annotations

import argparse
import json
import math
import re
import statistics
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"  # the competition data: tasks.jsonl, graphs/, embeddings/ (not redistributed)
STOP = set("the a an and or of to in is it be for on with this that as are was by not if at from can use "
           "using when should would which what how we you i do does".split())


def tokens(text: str) -> list[str]:
    """Identifier-aware tokens: split camelCase and snake_case, lowercase, drop stopwords and digits."""
    out = []
    for word in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", text or ""):
        for part in re.split(r"_+|(?<=[a-z0-9])(?=[A-Z])", word):
            p = part.lower()
            if len(p) > 1 and p not in STOP and not p.isdigit():
                out.append(p)
    return out


class BM25:
    def __init__(self, docs: dict[str, list[str]], k1: float = 1.5, b: float = 0.75):
        self.docs, self.k1, self.b = docs, k1, b
        self.len = {d: len(t) for d, t in docs.items()}
        self.avg = statistics.mean(self.len.values()) if docs else 1
        self.tf = {d: Counter(t) for d, t in docs.items()}
        df = Counter(w for t in docs.values() for w in set(t))
        n = len(docs)
        self.idf = {w: math.log(1 + (n - c + 0.5) / (c + 0.5)) for w, c in df.items()}

    def scores(self, query: list[str]) -> dict[str, float]:
        q = Counter(query)
        out = {}
        for d, tf in self.tf.items():
            s = 0.0
            norm = self.k1 * (1 - self.b + self.b * self.len[d] / self.avg)
            for w in q:
                f = tf.get(w)
                if f:
                    s += self.idf[w] * f * (self.k1 + 1) / (f + norm)
            if s:
                out[d] = s
        return out


def is_test_module(mod: str) -> bool:
    parts = mod.split(".")
    return parts[0] in ("tests", "test", "testing") or parts[-1].startswith("test_") or parts[-1] == "conftest"


def node_module(name: str, nodes: set[str]) -> str:
    """Longest proper prefix of a node name that is not itself a node (modules aren't nodes)."""
    parts = name.split(".")
    for i in range(len(parts) - 1, 0, -1):
        prefix = ".".join(parts[:i])
        if prefix not in nodes:
            return prefix
    return parts[0]


def ranked(scores: dict[str, float]) -> list[str]:
    return [k for k, _ in sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))]


def hit_rank(ranking: list[str], gold: set[str]) -> int | None:
    for i, m in enumerate(ranking, 1):
        if m in gold:
            return i
    return None


def evaluate_task(label: dict, task: dict, graph_dir: Path, emb_dir: Path, use_graph_tool: bool) -> dict:
    short = task["repo"].split("/")[-1]
    g = json.loads((graph_dir / f"{short}_{task['base_commit']}.json").read_text())
    nodes = {n["name"]: (n.get("text") or "") for n in g["nodes"]}
    names = set(nodes)
    mod_of = {n: node_module(n, names) for n in nodes}
    src_nodes = {n for n in nodes if not is_test_module(mod_of[n])}
    query = tokens(task["problem_statement"])
    gold = set(label["gold_modules"])
    gold_tests = {m for p in label["gold_test_files"] if (m := _test_module(p))}
    out = {"task_id": label["task_id"], "gold": sorted(gold), "gold_tests": sorted(gold_tests),
           "gold_in_graph": bool(gold & set(mod_of.values()))}

    # bm25_file: a module's document is all of its nodes' names and code
    mod_docs = defaultdict(list)
    for n in src_nodes:
        mod_docs[mod_of[n]] += tokens(n) + tokens(nodes[n])
    r_file = ranked(BM25(mod_docs).scores(query))

    # bm25_node: a module scores its best function/class
    node_scores = BM25({n: tokens(n) + tokens(nodes[n]) for n in src_nodes}).scores(query)
    best = defaultdict(float)
    for n, s in node_scores.items():
        best[mod_of[n]] = max(best[mod_of[n]], s)
    r_node = ranked(best)

    # bm25_calls: add half the mean score of each node's call neighbours, then best-node per module
    nbrs = defaultdict(set)
    for e in g["edges"]:
        if e["source"] in src_nodes and e["target"] in src_nodes:
            nbrs[e["source"]].add(e["target"]); nbrs[e["target"]].add(e["source"])
    spread = {n: s + 0.5 * statistics.mean([node_scores.get(m, 0.0) for m in nbrs[n]] or [0.0])
              for n, s in node_scores.items()}
    best_c = defaultdict(float)
    for n, s in spread.items():
        best_c[mod_of[n]] = max(best_c[mod_of[n]], s)
    r_calls = ranked(best_c)

    # bm25_embed: embedding neighbours (organizers' vectors) of the top-3 nodes vote for their modules
    r_embed = r_node
    try:
        import numpy as np
        z = np.load(emb_dir / f"{short}_{task['base_commit']}.npz", allow_pickle=True)
        vec = {k: z[k] for k in z.files if k in src_nodes}
        top = [n for n, _ in sorted(node_scores.items(), key=lambda kv: -kv[1])[:3] if n in vec]
        if top and vec:
            keys = list(vec); mat = np.stack([vec[k] for k in keys]).astype("float32")
            mat /= (np.linalg.norm(mat, axis=1, keepdims=True) + 1e-9)
            emb = defaultdict(float, best)
            for t in top:
                q = vec[t] / (np.linalg.norm(vec[t]) + 1e-9)
                sims = mat @ q
                for i in np.argsort(-sims)[:20]:
                    emb[mod_of[keys[i]]] += float(sims[i]) * node_scores[t] * 0.2
            r_embed = ranked(emb)
    except FileNotFoundError:
        pass

    # graph_tool: the agent's own search_similar_code with the issue title as query
    r_tool = []
    if use_graph_tool:
        from swegemma import graph as sg
        title = task["problem_statement"].strip().splitlines()[0][:200]
        try:
            res = sg.get_similar_nodes(node=title, repo_name=task["repo"], k=50,
                                       graph_dir=str(graph_dir), embeddings_dir=str(emb_dir),
                                       base_commit=task["base_commit"], use_local_storage=True)
            for item in res or []:
                m = mod_of.get(item.get("node_name"), None) or node_module(item.get("node_name", ""), names)
                if m and not is_test_module(m) and m not in r_tool:
                    r_tool.append(m)
        except Exception as e:  # tool returns nothing useful for free text: record as a miss
            out["graph_tool_error"] = repr(e)[:120]

    for key, r in (("bm25_file", r_file), ("bm25_node", r_node), ("graph_tool", r_tool),
                   ("bm25_calls", r_calls), ("bm25_embed", r_embed)):
        out[key] = {"rank": hit_rank(r, gold), "top5": r[:5]}

    # Test selection
    test_mods = sorted({mod_of[n] for n in nodes if is_test_module(mod_of[n])})
    t_docs = defaultdict(list)
    for n in nodes:
        if is_test_module(mod_of[n]):
            t_docs[mod_of[n]] += tokens(n) + tokens(nodes[n])
    out["test_bm25"] = {"rank": hit_rank(ranked(BM25(t_docs).scores(query)), gold_tests)}

    def by_name(src_mod: str) -> list[str]:
        last = src_mod.split(".")[-1]
        return [m for m in test_mods if m.split(".")[-1] in (f"test_{last}", f"{last}_test")]

    def by_calls(src_mods: set[str]) -> list[str]:
        c = Counter()
        for e in g["edges"]:
            s, t = e["source"], e["target"]
            if s in nodes and t in nodes and is_test_module(mod_of[s]) and mod_of[t] in src_mods:
                c[mod_of[s]] += 1
        return [m for m, _ in c.most_common()]

    top1 = r_node[0] if r_node else ""
    out["test_name"] = {"rank": hit_rank(by_name(top1), gold_tests)}
    out["test_name_oracle"] = {"rank": hit_rank([m for g_ in sorted(gold) for m in by_name(g_)], gold_tests)}
    out["test_calls"] = {"rank": hit_rank(by_calls({top1}), gold_tests)}
    out["test_calls_oracle"] = {"rank": hit_rank(by_calls(gold), gold_tests)}
    out["n_test_modules"] = len(test_mods)
    return out


def _test_module(path: str) -> str | None:
    if not path.endswith(".py"):
        return None
    parts = path[:-3].split("/")
    return ".".join(parts[1:] if parts[0] == "src" else parts)


def summarize(rows: list[dict], keys: list[str]) -> dict:
    out = {}
    for k in keys:
        ranks = [r[k]["rank"] for r in rows if k in r]
        n = len(ranks)
        if not n:
            continue
        out[k] = {"n": n, **{f"hit@{j}": sum(1 for x in ranks if x and x <= j) / n for j in (1, 3, 5)},
                  "mrr": sum(1 / x for x in ranks if x) / n}
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--labels", type=Path, default=ROOT / "results" / "triage" / "labels.jsonl")
    ap.add_argument("--tasks", type=Path, default=DATA / "tasks.jsonl")
    ap.add_argument("--graphs", type=Path, default=DATA / "graphs")
    ap.add_argument("--embeddings", type=Path, default=DATA / "embeddings")
    ap.add_argument("--subset", default="all", choices=["all", "dev", "holdout", "unused"])
    ap.add_argument("--sound-only", action="store_true")
    ap.add_argument("--no-graph-tool", action="store_true", help="skip the slow search_similar_code calls")
    ap.add_argument("--out", type=Path, default=ROOT / "results" / "triage" / "localize.jsonl")
    args = ap.parse_args()

    tasks = {t["instance_id"]: t for t in map(json.loads, args.tasks.read_text().splitlines())}
    labels = [json.loads(l) for l in args.labels.read_text().splitlines() if l.strip()]
    labels = [l for l in labels if l["has_graph"] and (args.subset == "all" or l["subset"] == args.subset)
              and (l["sound"] or not args.sound_only)]
    rows = []
    for i, lab in enumerate(labels, 1):
        rows.append(evaluate_task(lab, tasks[lab["task_id"]], args.graphs, args.embeddings, not args.no_graph_tool))
        if i % 20 == 0:
            print(f"  {i}/{len(labels)} tasks", flush=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("".join(json.dumps(r) + "\n" for r in rows))

    loc = ["bm25_file", "bm25_node", "graph_tool", "bm25_calls", "bm25_embed"]
    tst = ["test_bm25", "test_name", "test_name_oracle", "test_calls", "test_calls_oracle"]
    summary = {"n_tasks": len(rows), "gold_module_in_graph": sum(r["gold_in_graph"] for r in rows),
               "localization": summarize(rows, loc), "test_selection": summarize(rows, tst)}
    (args.out.with_suffix(".summary.json")).write_text(json.dumps(summary, indent=2))
    print(f"\n{len(rows)} tasks ({args.subset}{', sound only' if args.sound_only else ''}); "
          f"gold module present in the graph for {summary['gold_module_in_graph']}")
    for title, block in (("Localization (source modules)", summary["localization"]),
                         ("Test selection (existing test modules)", summary["test_selection"])):
        print(f"\n{title}\n  {'method':18s} {'hit@1':>6s} {'hit@3':>6s} {'hit@5':>6s} {'MRR':>6s}")
        for k, v in block.items():
            print(f"  {k:18s} {v['hit@1']:6.0%} {v['hit@3']:6.0%} {v['hit@5']:6.0%} {v['mrr']:6.2f}")


if __name__ == "__main__":
    main()
