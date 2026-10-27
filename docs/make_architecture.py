#!/usr/bin/env python3
"""Render docs/architecture.svg (animated) and docs/architecture.png (static).

Two complementary hues only: blue is Gemma 4 (it investigates), orange is deterministic code (it
checks); the report, where the two meet, carries the gradient between them. The animation follows
one issue (FastAPI #14458) through the system in a 10 s loop. Everything animated switches off
under prefers-reduced-motion, which leaves the complete static picture (that is the PNG).
Numbers are from the evaluated runs (docs/results.png, eval/).

    python docs/make_architecture.py   (needs Google Chrome for the PNG)
"""
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
W, H, LOOP = 1280, 784, 10.0
SANS = "ui-sans-serif, system-ui, -apple-system, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif"
MONO = "ui-monospace, SFMono-Regular, Menlo, Consolas, 'Liberation Mono', monospace"
BLUE_L, BLUE, BLUE_D = "#9cc0ff", "#4f86ff", "#2453d6"
ORG_L, ORG, ORG_D = "#ffb98a", "#ff8a3d", "#e0560c"
INK, INK2, INK3 = "#f3f5fb", "#b0bad5", "#7883a3"

keyframes: list[str] = []


def pct(t: float) -> float:
    return round(t / LOOP * 100, 2)


def appear(name: str, t: float) -> str:
    """Hidden until t, then visible until the loop resets."""
    p = pct(t)
    keyframes.append(f"@keyframes {name}{{0%,{p}%{{opacity:0}}{p + 2.5}%,95%{{opacity:1}}98.5%,100%{{opacity:0}}}}")
    return f'class="seq" style="animation:{name} {LOOP}s linear infinite"'


def dim_until(name: str, t: float) -> str:
    """Dim until t, then lit until the loop resets (budget ticks)."""
    p = pct(t)
    keyframes.append(f"@keyframes {name}{{0%,{p}%{{opacity:.16}}{p + 0.6}%,95%{{opacity:1}}98.5%,100%{{opacity:.16}}}}")
    return f'class="seq" style="animation:{name} {LOOP}s linear infinite"'


def glow(name: str, t0: float, t1: float) -> str:
    """An overlay that lights up from t0 to t1."""
    a, b = pct(t0), pct(t1)
    keyframes.append(f"@keyframes {name}{{0%,{a}%{{opacity:0}}{a + 2}%,{max(a + 2.1, b - 2)}%{{opacity:1}}{b}%,100%{{opacity:0}}}}")
    return f'class="anim" style="animation:{name} {LOOP}s ease-in-out infinite"'


def text(x, y, s, size=13, weight=400, fill=INK, anchor="start", family=SANS, extra=""):
    return (f'<text x="{x}" y="{y}" font-family="{family}" font-size="{size}" font-weight="{weight}" '
            f'fill="{fill}" text-anchor="{anchor}" {extra}>{s}</text>')


def caps(x, y, s, fill=INK3, size=11, anchor="start"):
    return text(x, y, s, size, 700, fill, anchor, extra='letter-spacing="1.3"')


def card(x, y, w, h, fill, stroke, sw=1.5, r=16, extra=""):
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}" {extra}/>'


def packet(path, t0, t1, c0, c1=None, r=5):
    k0, k1 = round(t0 / LOOP, 4), round(t1 / LOOP, 4)
    fill = (f'<animate attributeName="fill" dur="{LOOP}s" repeatCount="indefinite" calcMode="linear" '
            f'values="{c0};{c0};{c1};{c1}" keyTimes="0;{k0};{k1};1"/>') if c1 else ""
    return (f'<g class="anim"><circle r="{r}" fill="{c0}" opacity="0" filter="url(#soft)">'
            f'<animateMotion dur="{LOOP}s" repeatCount="indefinite" calcMode="linear" path="{path}" '
            f'keyPoints="0;0;1;1" keyTimes="0;{k0};{k1};1"/>'
            f'<animate attributeName="opacity" dur="{LOOP}s" repeatCount="indefinite" calcMode="linear" '
            f'values="0;0;1;1;0;0" keyTimes="0;{round(k0 - 0.002, 4)};{k0};{k1};{round(k1 + 0.008, 4)};1"/>'
            f'{fill}</circle></g>')


def connector(d, stroke, marker, label=None, lx=0, ly=0, width=2, dash=""):
    out = [f'<path d="{d}" fill="none" stroke="{stroke}" stroke-width="{width}" stroke-linecap="round" '
           f'stroke-linejoin="round" marker-end="url(#{marker})" {dash}/>']
    for i, line in enumerate(label or []):
        out.append(text(lx, ly + i * 13, line, 10.5, 600, INK3, "middle", extra='letter-spacing=".3"'))
    return "\n".join(out)


parts = []
add = parts.append

# ---------------------------------------------------------------- background and header
add(f'<rect width="{W}" height="{H}" rx="24" fill="url(#bg)"/>')
add(f'<rect width="{W}" height="{H}" rx="24" fill="url(#ambientBlue)"/>')
add(f'<rect width="{W}" height="{H}" rx="24" fill="url(#ambientOrange)"/>')
add(f'<rect width="{W}" height="{H}" rx="24" fill="url(#dots)"/>')
add(text(48, 66, "Gemma 4 Issue Triage", 30, 800, INK, extra='letter-spacing="-.3"'))
add(text(48, 94, "One offline Gemma 4 agent investigates. Deterministic code checks every claim. "
                 "A maintainer decides.", 15, 400, INK2))
add(f'<rect x="968" y="46" width="14" height="14" rx="4" fill="url(#blueStroke)"/>')
add(text(992, 58, "Gemma 4 · investigates, never edits", 13, 500, INK2))
add(f'<rect x="968" y="72" width="14" height="14" rx="4" fill="url(#orgStroke)"/>')
add(text(992, 84, "Python · CPU · no model · checks", 13, 500, INK2))
for x, label, color in ((48, "INPUT", INK3), (312, "INVESTIGATE", BLUE_L), (676, "CHECK", ORG_L), (1060, "DECIDE", INK3)):
    add(caps(x, 134, label, color, 11))

# ---------------------------------------------------------------- connectors (under the cards)
add(connector("M238 204 H306", BLUE, "ahBlue", ["issue text"], 274, 194))
add(connector("M238 316 H306", INK3, "ahInk", ["read-only"], 274, 306, 1.5))
add(connector("M238 412 H306", INK3, "ahInk", ["neighbours"], 274, 402, 1.5))
add(connector("M143 450 V520 H670", "url(#graphToOrg)", "ahOrg", ["call edges"], 420, 510, 1.5))
add(connector("M612 300 H670", "url(#handoff)", "ahOrg", ["notes", "+ trace"], 644, 276, 3))
add(connector("M996 270 H1054", ORG, "ahOrg", ["fills", "template"], 1028, 246, 2))
add(connector("M1154 400 V434", INK2, "ahInk", None, 0, 0, 1.5))
add(text(1164, 422, "reads", 10.5, 600, INK3, extra='letter-spacing=".3"'))
loop = "M1154 588 V652 H28 V204 H42"
add(f'<path d="{loop}" fill="none" stroke="{INK3}" stroke-width="1.5" stroke-dasharray="6 7" '
    f'stroke-linejoin="round" marker-end="url(#ahInk)"/>')
add(f'<path class="anim" d="{loop}" fill="none" stroke="{INK}" stroke-opacity=".55" stroke-width="1.5" '
    f'stroke-dasharray="6 7" stroke-linejoin="round"><animate attributeName="stroke-dashoffset" '
    f'values="0;-26" dur="1.4s" repeatCount="indefinite"/></path>')
add(text(600, 644, "not convinced? the maintainer adds a hint to the issue and re-runs", 11.5, 500, INK3, "middle"))

# ---------------------------------------------------------------- inputs
add(card(48, 150, 190, 108, "url(#neutralFill)", "rgba(255,255,255,.16)"))
add(f'<rect x="48" y="150" width="190" height="108" rx="16" fill="none" stroke="{BLUE_L}" stroke-width="2.5" '
    f'filter="url(#glow)" {glow("gIssue", 0.0, 0.9)}/>')
add(caps(64, 176, "NEW ISSUE"))
add(text(64, 200, "fastapi #14458", 16, 700))
add(text(64, 222, "class with async __call__", 12.5, 400, INK2))
add(text(64, 240, "breaks as a dependency", 12.5, 400, INK2))
add(card(48, 278, 190, 76, "url(#neutralFill)", "rgba(255,255,255,.16)"))
add(caps(64, 304, "REPOSITORY"))
add(text(64, 330, "checkout at the issue", 14, 500))
add(card(48, 374, 190, 76, "url(#neutralFill)", "rgba(255,255,255,.16)"))
add(caps(64, 400, "CODE GRAPH"))
add(text(64, 426, "functions + call edges", 14, 500))
for (x1, y1), (x2, y2) in (((200, 388), (216, 400)), ((200, 388), (186, 404)), ((216, 400), (186, 404))):
    add(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{INK3}" stroke-width="1.2"/>')
for cx, cy in ((200, 388), (216, 400), (186, 404)):
    add(f'<circle cx="{cx}" cy="{cy}" r="3.2" fill="{INK2}"/>')

# ---------------------------------------------------------------- the agent
add(card(312, 150, 300, 336, "url(#blueFill)", "url(#blueStroke)", 1.8, 18))
add(f'<rect x="312" y="150" width="300" height="336" rx="18" fill="none" stroke="{BLUE}" stroke-width="3" '
    f'filter="url(#glow)" {glow("gAgent", 1.0, 4.6)}/>')
add(caps(332, 178, "GEMMA 4 31B · 4-BIT · OFFLINE", BLUE_L))
add(text(332, 210, "Triage agent", 24, 800, extra='letter-spacing="-.2"'))
add(text(332, 234, "searches, reads and runs code;", 13, 400, INK2))
add(text(332, 252, "writes only to TRIAGE/", 13, 400, INK2))
add(caps(332, 282, "BUDGET · 24 TOOL CALLS · 8 MIN", INK3, 10.5))
for i in range(24):
    add(f'<rect x="{331 + i * 11}" y="292" width="8" height="18" rx="2.5" fill="url(#tick)" '
        f'{dim_until(f"t{i}", 1.1 + i * 0.125)}/>')
add(caps(332, 344, "WRITES", INK3, 10.5))
for j, (name, what) in enumerate((("TRIAGE/report.md", "suspects · tests"), ("TRIAGE/repro.py", "fails on the bug"),
                                  ("trace", "files it opened"))):
    y = 356 + j * 42
    add(f'<g {appear(f"c{j}", 4.15 + j * 0.15)}>'
        + card(332, y, 260, 34, "rgba(79,134,255,.14)", "rgba(156,192,255,.35)", 1, 9)
        + text(344, y + 22, name, 12.5, 600, INK, family=MONO)
        + text(580, y + 22, what, 11.5, 500, INK3, "end") + "</g>")

# ---------------------------------------------------------------- the orchestrator
add(card(676, 150, 320, 480, "url(#orgFill)", "url(#orgStroke)", 1.8, 18))
add(caps(696, 178, "PYTHON · CPU · NO MODEL", ORG_L))
add(text(696, 210, "Orchestrator", 24, 800, extra='letter-spacing="-.2"'))
add(text(696, 234, "checks the agent instead of trusting it", 13, 400, INK2))
steps = (("Fallback chain", "report → opened files → retrieval", "60/60 reports"),
         ("Retrieval", "BM25 + call-graph spreading", "0.1 s"),
         ("Confidence", "agent's pick vs retrieval's top 3", "HIGH·MED 29/29"),
         ("Call-graph tests", "test files that call the suspect", "40→62% hit"),
         ("Re-run repro.py", "non-zero exit means reproduced", "44→61% precise"))
for i, (title, detail, pill) in enumerate(steps):
    y = 252 + i * 74
    add(card(692, y, 288, 66, "rgba(255,255,255,.035)", "rgba(255,138,61,.30)", 1, 12))
    add(f'<rect x="692" y="{y}" width="288" height="66" rx="12" fill="rgba(255,138,61,.10)" stroke="{ORG}" '
        f'stroke-width="2" filter="url(#glow)" {glow(f"s{i}", 5.5 + i * 0.42, 6.6 + i * 0.42)}/>')
    add(f'<circle cx="716" cy="{y + 33}" r="13" fill="url(#orgStroke)"/>')
    add(text(716, y + 38, str(i + 1), 13, 800, "#1d0e04", "middle"))
    add(text(740, y + 28, title, 14.5, 700))
    add(text(740, y + 48, detail, 12, 400, INK2))
    pw = round(len(pill) * 6.3 + 16)
    add(f'<rect x="{968 - pw}" y="{y + 12}" width="{pw}" height="21" rx="10.5" fill="rgba(255,138,61,.12)" '
        f'stroke="rgba(255,185,138,.55)" stroke-width="1"/>')
    add(text(968 - pw / 2, y + 27, pill, 11, 700, ORG_L, "middle"))

# ---------------------------------------------------------------- report and maintainer
add(card(1060, 150, 188, 250, "url(#reportFill)", "url(#reportStroke)", 2, 16))
add(f'<rect x="1060" y="150" width="188" height="250" rx="16" fill="none" stroke="url(#reportStroke)" '
    f'stroke-width="3" filter="url(#glow)" {glow("gReport", 8.0, 9.1)}/>')
add(caps(1076, 176, "FINAL REPORT"))
add(text(1076, 200, "final_report.md", 14, 600, INK, family=MONO))
rows = (("LOCATION", "dependencies/models.py", INK, MONO, 11.5), ("CONFIDENCE", "HIGH", ORG_L, SANS, 13),
        ("TESTS", "test_dependency_class", INK, MONO, 11.5), ("REPRODUCTION", "REPRODUCED", ORG_L, SANS, 13))
for k, (key, value, color, family, size) in enumerate(rows):
    y = 228 + k * 42
    add(caps(1076, y, key, INK3, 9.5))
    add(f'<g {appear(f"r{k}", 8.15 + k * 0.18)}>'
        + text(1076, y + 18, value, size, 700 if family == SANS else 500, color, family=family) + "</g>")
add(card(1060, 440, 188, 148, "url(#neutralFill)", "rgba(255,255,255,.30)", 1.5, 16))
add(f'<rect x="1060" y="440" width="188" height="148" rx="16" fill="none" stroke="{INK}" stroke-width="2.5" '
    f'filter="url(#glow)" {glow("gHuman", 9.25, 9.9)}/>')
add(caps(1076, 466, "HUMAN IN THE LOOP"))
add(text(1076, 492, "Maintainer", 20, 800))
for k, line in enumerate(("HIGH → approve", "LOW → check first", "wrong → add a hint")):
    add(text(1076, 520 + k * 20, line, 12.5, 500, INK2))

# ---------------------------------------------------------------- packets: one issue moving through
add(packet("M238 204 H306", 0.2, 0.9, BLUE_L))
for t0, src in ((1.3, "M238 316 H306"), (2.0, "M238 412 H306"), (2.7, "M238 316 H306"), (3.4, "M238 412 H306")):
    add(packet(src, t0, t0 + 0.45, INK, r=4))
add(packet("M612 300 H670", 4.65, 5.3, BLUE_L, ORG_L, 6))
add(packet("M143 450 V520 H670", 4.5, 5.4, INK, ORG_L, 4))
add(packet("M996 270 H1054", 7.55, 8.05, ORG_L))
add(packet("M1154 400 V434", 9.05, 9.3, INK, r=4))

# ---------------------------------------------------------------- results strip
add(f'<line x1="48" y1="676" x2="1232" y2="676" stroke="rgba(255,255,255,.10)"/>')
for x, big, label, sub, off in ((48, "92% · 90%", "right file named first", "retrieval alone: 42% · 30%", 168),
                                (458, "65% · 55%", "right test file named first", "agent alone: 48% · 25%", 168),
                                (868, "0 / 60", "runs that edited source code", "the agent writes only its notes", 120)):
    add(text(x, 724, big, 30, 800, "url(#numGrad)", extra='letter-spacing="-.5"'))
    add(text(x + off, 709, label, 13.5, 600, INK))
    add(text(x + off, 728, sub, 12, 400, INK3))
add(text(48, 762, "Dev · holdout: 40 · 20 real issues from FastAPI, Rich, Requests and HTTPX. "
                  "Gemma 4 31B (4-bit) on vLLM, fully offline.", 11.5, 400, INK3))

defs = f"""<defs>
<linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#0a1020"/><stop offset="1" stop-color="#121a36"/></linearGradient>
<radialGradient id="ambientBlue" cx=".2" cy=".18" r=".55"><stop offset="0" stop-color="{BLUE}" stop-opacity=".20"/><stop offset="1" stop-color="{BLUE}" stop-opacity="0"/></radialGradient>
<radialGradient id="ambientOrange" cx=".82" cy=".72" r=".55"><stop offset="0" stop-color="{ORG}" stop-opacity=".14"/><stop offset="1" stop-color="{ORG}" stop-opacity="0"/></radialGradient>
<pattern id="dots" width="22" height="22" patternUnits="userSpaceOnUse"><circle cx="2" cy="2" r="1" fill="#ffffff" fill-opacity=".06"/></pattern>
<linearGradient id="neutralFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#ffffff" stop-opacity=".07"/><stop offset="1" stop-color="#ffffff" stop-opacity=".02"/></linearGradient>
<linearGradient id="blueFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{BLUE}" stop-opacity=".26"/><stop offset="1" stop-color="{BLUE_D}" stop-opacity=".07"/></linearGradient>
<linearGradient id="blueStroke" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{BLUE_L}"/><stop offset="1" stop-color="{BLUE_D}"/></linearGradient>
<linearGradient id="orgFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{ORG}" stop-opacity=".20"/><stop offset="1" stop-color="{ORG_D}" stop-opacity=".05"/></linearGradient>
<linearGradient id="orgStroke" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{ORG_L}"/><stop offset="1" stop-color="{ORG_D}"/></linearGradient>
<linearGradient id="reportFill" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{BLUE}" stop-opacity=".14"/><stop offset="1" stop-color="{ORG}" stop-opacity=".14"/></linearGradient>
<linearGradient id="reportStroke" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{BLUE_L}"/><stop offset="1" stop-color="{ORG_L}"/></linearGradient>
<linearGradient id="tick" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{BLUE_L}"/><stop offset="1" stop-color="{BLUE}"/></linearGradient>
<linearGradient id="handoff" gradientUnits="userSpaceOnUse" x1="612" y1="0" x2="670" y2="0"><stop offset="0" stop-color="{BLUE}"/><stop offset="1" stop-color="{ORG}"/></linearGradient>
<linearGradient id="graphToOrg" gradientUnits="userSpaceOnUse" x1="143" y1="0" x2="670" y2="0"><stop offset="0" stop-color="{INK3}"/><stop offset="1" stop-color="{ORG}"/></linearGradient>
<linearGradient id="numGrad" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="{BLUE_L}"/><stop offset="1" stop-color="{ORG_L}"/></linearGradient>
<filter id="glow" x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation="5"/></filter>
<filter id="soft" x="-200%" y="-200%" width="500%" height="500%"><feGaussianBlur in="SourceGraphic" stdDeviation="2.2" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
<marker id="ahBlue" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 0 L10 5 L0 10 z" fill="{BLUE}"/></marker>
<marker id="ahOrg" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 0 L10 5 L0 10 z" fill="{ORG}"/></marker>
<marker id="ahInk" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 0 L10 5 L0 10 z" fill="{INK3}"/></marker>
</defs>"""

style = ("<style>" + "".join(keyframes) +
         "@media (prefers-reduced-motion: reduce){.anim{display:none}.seq{animation:none!important;opacity:1!important}}"
         "</style>")
label = ("Architecture: a new issue, the repository and its code graph go to one offline Gemma 4 triage agent, "
         "which writes notes, a reproduction script and a trace. A deterministic orchestrator falls back when "
         "notes are missing, computes confidence from agreement with retrieval, finds tests through call edges "
         "and re-runs the reproduction. It fills the final report for a maintainer, who can add a hint and re-run.")
svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" '
       f'aria-label="{label}">\n<title>Gemma 4 Issue Triage architecture</title>\n{defs}\n{style}\n'
       + "\n".join(parts) + "\n</svg>\n")
(HERE / "architecture.svg").write_text(svg, encoding="utf-8")

subprocess.run(["google-chrome", "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=2",
                "--force-prefers-reduced-motion", f"--window-size={W},{H}", "--default-background-color=00000000",
                f"--screenshot={HERE / 'architecture.png'}", f"file://{HERE / 'architecture.svg'}"],
               check=True, capture_output=True)
print("wrote", HERE / "architecture.svg", "and", HERE / "architecture.png")
