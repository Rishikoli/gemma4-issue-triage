"""Model-free localization: BM25 over functions/classes, scores spread along call edges, ranked by module."""
from __future__ import annotations

import math
import re
import statistics
from collections import Counter, defaultdict

from .graph import CodeGraph

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


def bm25(docs: dict[str, list[str]], query: list[str], k1: float = 1.5, b: float = 0.75) -> dict[str, float]:
    if not docs:
        return {}
    avg = statistics.mean(len(t) for t in docs.values()) or 1
    df = Counter(w for t in docs.values() for w in set(t))
    n = len(docs)
    idf = {w: math.log(1 + (n - c + 0.5) / (c + 0.5)) for w, c in df.items()}
    q = Counter(query)
    out = {}
    for d, toks in docs.items():
        tf, norm, s = Counter(toks), k1 * (1 - b + b * len(toks) / avg), 0.0
        for w in q:
            if (f := tf.get(w)):
                s += idf[w] * f * (k1 + 1) / (f + norm)
        if s:
            out[d] = s
    return out


def rank_modules(graph: CodeGraph, issue_text: str, spread: float = 0.5) -> list[str]:
    """Source modules ranked for an issue: BM25 per function/class, plus `spread` x the mean score of its
    call-graph neighbours; a module scores its best function."""
    src = set(graph.source_nodes())
    scores = bm25({n: tokens(n) + tokens(graph.nodes[n]) for n in src}, tokens(issue_text))
    nbrs = defaultdict(set)
    for s, t in graph.edges:
        if s in src and t in src:
            nbrs[s].add(t)
            nbrs[t].add(s)
    best = defaultdict(float)
    for n, s in scores.items():
        v = s + spread * statistics.mean([scores.get(m, 0.0) for m in nbrs[n]] or [0.0])
        best[graph.module_of[n]] = max(best[graph.module_of[n]], v)
    return [m for m, _ in sorted(best.items(), key=lambda kv: (-kv[1], kv[0]))]
