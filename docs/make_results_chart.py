#!/usr/bin/env python3
"""Render docs/results.png: top-1 accuracy of each method on the same 40 dev and 20 holdout issues.

Numbers come from the authors' evaluation (eval/ scripts on the competition data) and are entered here
by hand, since the labels themselves can't be published. Re-run after updating DATA:
    python docs/make_results_chart.py   (needs Google Chrome for the PNG)
"""
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = {
    "Finding the file to fix": [
        ("BM25 over the code", 38, 25, False),
        ("Agent's code-search tool", 28, 40, False),
        ("BM25 + embedding neighbours", 28, 30, False),
        ("BM25 + call-graph spreading", 42, 30, False),
        ("Gemma 4 triage agent", 75, 55, False),
        ("+ orchestrator", 92, 90, True),
    ],
    "Finding the test file the fix's tests go in": [
        ("BM25 over the test files", 22, 50, False),
        ("Gemma 4 triage agent", 48, 25, False),
        ("+ orchestrator (call-graph tests)", 65, 55, True),
    ],
}
W, LABEL_W, BAR_MAX, BAR_H, GAP, ROW_GAP = 738, 250, 420, 16, 2, 18


def panel(title: str, rows: list) -> str:
    h = 54 + len(rows) * (2 * BAR_H + GAP + ROW_GAP) + 24
    out = [f'<svg viewBox="0 0 {W} {h}" width="{W}" height="{h}" role="img" aria-label="{title}">',
           f'<text x="0" y="22" class="pt">{title}</text>']
    x0, y = LABEL_W, 46
    for pct in (0, 25, 50, 75, 100):                       # recessive grid
        gx = x0 + BAR_MAX * pct / 100
        out.append(f'<line x1="{gx}" x2="{gx}" y1="{y - 6}" y2="{h - 22}" class="grid"/>')
        out.append(f'<text x="{gx}" y="{h - 6}" class="tick" text-anchor="middle">{pct}%</text>')
    for label, dev, hold, ours in rows:
        cls = "lab ours" if ours else "lab"
        out.append(f'<text x="{x0 - 14}" y="{y + BAR_H + 4}" class="{cls}" text-anchor="end">{label}</text>')
        for i, (v, s) in enumerate(((dev, "s1"), (hold, "s2"))):
            by = y + i * (BAR_H + GAP)
            w = max(BAR_MAX * v / 100, 2)
            # bar anchored at the baseline, rounded only at the data end
            out.append(f'<path d="M{x0} {by} H{x0 + w - 4} Q{x0 + w} {by} {x0 + w} {by + 4} V{by + BAR_H - 4} '
                       f'Q{x0 + w} {by + BAR_H} {x0 + w - 4} {by + BAR_H} H{x0} Z" class="{s}"/>')
            out.append(f'<text x="{x0 + w + 6}" y="{by + BAR_H - 4}" class="val">{v}%</text>')
        y += 2 * BAR_H + GAP + ROW_GAP
    out.append("</svg>")
    return "\n".join(out)


html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Triage results</title><style>
.viz-root {{ --surface-1:#fcfcfb; --text-primary:#0b0b0b; --text-secondary:#52514e; --text-muted:#76756f;
  --grid:#e7e6e2; --series-1:#2a78d6; --series-2:#eb6834; color-scheme: light; }}
body {{ margin:0; background:var(--surface-1); font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }}
.viz-root {{ width:1600px; padding:36px 44px 28px; box-sizing:border-box; background:var(--surface-1); color:var(--text-primary); }}
h1 {{ font-size:26px; margin:0 0 4px; }} .sub {{ font-size:15px; color:var(--text-secondary); margin:0 0 14px; }}
.legend {{ display:flex; gap:22px; font-size:14px; color:var(--text-secondary); margin-bottom:12px; }}
.sw {{ display:inline-block; width:12px; height:12px; border-radius:3px; margin-right:7px; vertical-align:-1px; }}
.panels {{ display:flex; gap:36px; align-items:flex-start; }} svg {{ display:block; flex:none; }}
.pt {{ font-size:17px; font-weight:650; fill:var(--text-primary); }}
.lab {{ font-size:14px; fill:var(--text-secondary); }} .lab.ours {{ fill:var(--text-primary); font-weight:650; }}
.val {{ font-size:12.5px; fill:var(--text-secondary); }} .tick {{ font-size:12px; fill:var(--text-muted); }}
.grid {{ stroke:var(--grid); stroke-width:1; }} .s1 {{ fill:var(--series-1); }} .s2 {{ fill:var(--series-2); }}
.foot {{ font-size:13px; color:var(--text-muted); margin-top:6px; }}
</style></head><body><div class="viz-root">
<h1>Gemma 4 finds the bug; the code graph helps it find the tests</h1>
<p class="sub">Top-1 accuracy on the same issues for every method (Gemma 4 31B, offline). The orchestrator adds model-free steps around the agent.</p>
<div class="legend"><span><span class="sw" style="background:var(--series-1)"></span>Dev · 40 issues</span>
<span><span class="sw" style="background:var(--series-2)"></span>Holdout · 20 issues</span></div>
<div class="panels">{''.join(panel(t, r) for t, r in DATA.items())}</div>
<p class="foot">"Gemma 4 triage agent" counts a missing report as a miss; the orchestrator always writes one (falling back to the files the agent opened)
and merges in tests that call the suspected code. Ground truth: the files and test files changed by the merged fix.</p>
</div></body></html>"""

(HERE / "results.html").write_text(html)
subprocess.run(["google-chrome", "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=2",
                "--window-size=1600,610", "--virtual-time-budget=500", f"--screenshot={HERE / 'results.png'}",
                f"file://{HERE / 'results.html'}"], check=True, capture_output=True)
print("wrote", HERE / "results.png")
