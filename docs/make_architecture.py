#!/usr/bin/env python3
"""Render docs/architecture.svg (animated), docs/architecture.png (static) and docs/architecture.gif.

The figure tells the story of one issue (FastAPI #14458) once: each stage appears and its
connections draw in as the issue reaches it. Then particles keep flowing along every connection,
showing what moves where. Two complementary hues only: blue is Gemma 4, orange is deterministic code.
The handoff from one to the other, and the report where they meet, carry the gradient between them.
Everything animated switches off under prefers-reduced-motion, which leaves the complete static
picture (that is the PNG). Numbers are from the evaluated runs (docs/results.png, eval/).

    python docs/make_architecture.py [--gif]   (needs Google Chrome; the GIF also needs ffmpeg)
"""
import math
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
W, H = 1280, 764
SERIF = "'Iowan Old Style', 'Palatino Linotype', Palatino, Georgia, serif"
SANS = "ui-sans-serif, system-ui, -apple-system, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif"
MONO = "ui-monospace, SFMono-Regular, Menlo, Consolas, 'Liberation Mono', monospace"
PAPER, RULE = "#f7f5f0", "#e2ded4"
INK, INK2, INK3 = "#1d1e23", "#55575f", "#8b8d95"
BLUE, BLUE_T, BLUE_M = "#2f5fd0", "#eaf0fd", "#9db5ec"
ORG, ORG_T, ORG_M = "#e2701b", "#fdf0e4", "#f2b384"
SPEED = 75  # particle speed, px per second

parts: list[str] = []
add = parts.append


def path_length(d: str) -> float:
    toks = re.findall(r"[MLHVC]|-?\d+(?:\.\d+)?", d)
    i, x, y, total, cmd = 0, 0.0, 0.0, 0.0, None
    while i < len(toks):
        if toks[i] in "MLHVC":
            cmd = toks[i]
            i += 1
        if cmd == "M":
            x, y = float(toks[i]), float(toks[i + 1])
            i += 2
        elif cmd == "L":
            nx, ny = float(toks[i]), float(toks[i + 1])
            total += math.hypot(nx - x, ny - y)
            x, y, i = nx, ny, i + 2
        elif cmd == "H":
            nx = float(toks[i])
            total, x, i = total + abs(nx - x), nx, i + 1
        elif cmd == "V":
            ny = float(toks[i])
            total, y, i = total + abs(ny - y), ny, i + 1
        elif cmd == "C":
            x1, y1, x2, y2, x3, y3 = map(float, toks[i:i + 6])
            px, py = x, y
            for k in range(1, 41):
                t = k / 40
                qx = (1 - t) ** 3 * x + 3 * (1 - t) ** 2 * t * x1 + 3 * (1 - t) * t * t * x2 + t ** 3 * x3
                qy = (1 - t) ** 3 * y + 3 * (1 - t) ** 2 * t * y1 + 3 * (1 - t) * t * t * y2 + t ** 3 * y3
                total += math.hypot(qx - px, qy - py)
                px, py = qx, qy
            x, y, i = x3, y3, i + 6
    return total


def text(x, y, s, size=13, weight=400, fill=INK, anchor="start", family=SANS, extra=""):
    return (f'<text x="{x}" y="{y}" font-family="{family}" font-size="{size}" font-weight="{weight}" '
            f'fill="{fill}" text-anchor="{anchor}" {extra}>{s}</text>')


def caps(x, y, s, fill=INK3, size=10.5, anchor="start"):
    return text(x, y, s, size, 700, fill, anchor, extra='letter-spacing="1.2"')


def card(x, y, w, h, fill="#ffffff", stroke=RULE, sw=1, r=14):
    return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{fill}" stroke="{stroke}" '
            f'stroke-width="{sw}" filter="url(#lift)"/>')


def reveal(at: float, body: str) -> None:
    """A group that rises into view at `at` seconds."""
    add(f'<g class="a" style="animation-delay:{at}s">{body}</g>')


def draw(d, stroke, at, width=1.6, dur=0.6, label=None, lx=0, ly=0):
    """A connection that draws itself in at `at` seconds."""
    add(f'<path class="d" pathLength="1" d="{d}" fill="none" stroke="{stroke}" stroke-width="{width}" '
        f'stroke-linecap="round" stroke-linejoin="round" style="animation-delay:{at}s;animation-duration:{dur}s"/>')
    if label:
        reveal(at + dur * 0.5, "".join(text(lx, ly + i * 12, line, 10.5, 600, INK3, "middle") for i, line in enumerate(label)))


def arrowhead(x, y, direction, color, at):
    tip = {"right": f"M{x} {y} l-8 -4.5 v9 z", "down": f"M{x} {y} l-4.5 -8 h9 z"}[direction]
    reveal(at, f'<path d="{tip}" fill="{color}"/>')


def flow(d, at, c0, c1=None, r=3.2, spacing=95):
    """Particles moving along d forever, starting at `at` seconds."""
    length = path_length(d)
    dur = round(length / SPEED, 2)
    n = max(1, round(length / spacing))
    dots = []
    for k in range(n):
        begin = f"-{round(dur * k / n, 2)}s"
        recolor = (f'<animate attributeName="fill" values="{c0};{c1}" dur="{dur}s" begin="{begin}" '
                   f'repeatCount="indefinite"/>') if c1 else ""
        dots.append(f'<circle r="{r}" fill="{c0}"><animateMotion path="{d}" dur="{dur}s" begin="{begin}" '
                    f'repeatCount="indefinite"/>{recolor}</circle>')
    add(f'<g class="f" style="animation-delay:{at}s">{"".join(dots)}</g>')


# ------------------------------------------------------------------ paper, header, stage headings
add(f'<rect x=".5" y=".5" width="{W - 1}" height="{H - 1}" rx="20" fill="{PAPER}" stroke="{RULE}"/>')
add(text(48, 64, "Gemma 4 Issue Triage", 31, 600, INK, family=SERIF))
add(text(48, 92, "How a new issue becomes a checked report: the model investigates, plain code verifies, "
                 "a person decides.", 15, 400, INK2))
add(f'<rect x="1000" y="47" width="12" height="12" rx="3" fill="{BLUE}"/>')
add(text(1020, 57, "Gemma 4, the model", 12.5, 500, INK2))
add(f'<rect x="1000" y="69" width="12" height="12" rx="3" fill="{ORG}"/>')
add(text(1020, 79, "Python, no model", 12.5, 500, INK2))
add(f'<rect x="1000" y="91" width="12" height="12" rx="3" fill="url(#both)"/>')
add(text(1020, 101, "where the two meet", 12.5, 500, INK2))
stages = ((48, "1", "Issue arrives", INK3, 0.0), (320, "2", "Gemma 4 investigates", BLUE, 1.0),
          (690, "3", "Code checks every claim", ORG, 3.9), (1066, "4", "Maintainer decides", INK3, 6.0))
for x, n, label, color, at in stages:
    reveal(at, f'<circle cx="{x + 9}" cy="{136}" r="9" fill="{color}"/>'
           + text(x + 9, 140, n, 11, 700, "#ffffff", "middle") + text(x + 25, 141, label, 13.5, 700, INK))

# ------------------------------------------------------------------ connections (under the cards)
ISSUE, READS, NEIGH = "M238 216 H320", "M238 332 H320", "M238 428 H320"
HANDOFF = "M610 414 H690"
GRAPH_ORG = "M143 464 C143 560, 560 584, 690 584"
FANS = [("M984 288 C1030 288, 1022 238, 1066 238", 6.15), ("M984 436 C1030 436, 1022 282, 1066 282", 6.3),
        ("M984 510 C1030 510, 1022 326, 1066 326", 6.45), ("M984 584 C1030 584, 1022 370, 1066 370", 6.6)]
TO_HUMAN = "M1157 410 V446"
HINT = ("M1157 590 C1157 625, 1140 642, 1105 642 H90 C55 642, 28 617, 28 582 V252 "
        "C28 230, 34 216, 40 216")
RETR_CONF = "M706 362 C694 362, 694 436, 704 436"

draw(ISSUE, BLUE, 0.9, 2, label=["issue text"], lx=279, ly=206)
draw(READS, INK3, 1.6, label=["reads"], lx=279, ly=322)
draw(NEIGH, INK3, 1.75, label=["neighbours"], lx=279, ly=418)
draw(HANDOFF, "url(#handoff)", 3.85, 3.5, label=["notes", "+ trace"], lx=650, ly=388)
draw(GRAPH_ORG, "url(#graphToOrg)", 4.0, 1.6, 0.9, ["call edges"], 420, 590)
for d, at in FANS:
    draw(d, ORG_M, at, 1.6, 0.45)
draw(TO_HUMAN, INK3, 7.15, 1.6, 0.35)
reveal(7.3, text(1167, 433, "reads", 10.5, 600, INK3))
add(f'<path class="a" d="{HINT}" fill="none" stroke="{INK3}" stroke-width="1.4" stroke-dasharray="5 6" '
    f'stroke-linejoin="round" style="animation-delay:7.7s"/>')
reveal(7.9, text(330, 634, "not convinced? add a hint to the issue and run it again", 11.5, 500, INK3, "middle"))
arrowhead(320, 216, "right", BLUE, 1.4)
arrowhead(320, 332, "right", INK3, 2.1)
arrowhead(320, 428, "right", INK3, 2.25)
arrowhead(690, 414, "right", ORG, 4.35)
arrowhead(690, 584, "right", ORG, 4.8)
for d, at in FANS:
    arrowhead(1066, int(d.split()[-1]), "right", ORG, at + 0.4)
arrowhead(1157, 450, "down", INK3, 7.45)
arrowhead(48, 216, "right", INK3, 8.0)

# ------------------------------------------------------------------ stage 1: inputs
reveal(0.2, card(48, 160, 190, 112) + caps(64, 186, "NEW ISSUE") + text(64, 210, "fastapi #14458", 16, 700)
       + text(64, 232, "class with async __call__", 12.5, 400, INK2) + text(64, 250, "breaks as a dependency", 12.5, 400, INK2))
reveal(0.5, card(48, 296, 190, 72) + caps(64, 322, "REPOSITORY") + text(64, 348, "checkout at the issue", 14, 500))
nodes = ((200, 406), (216, 418), (186, 422))
glyph = "".join(f'<line x1="{a[0]}" y1="{a[1]}" x2="{b[0]}" y2="{b[1]}" stroke="{INK3}" stroke-width="1.2"/>'
                for a, b in zip(nodes, nodes[1:] + nodes[:1]))
glyph += "".join(f'<circle cx="{cx}" cy="{cy}" r="3" fill="{INK2}"/>' for cx, cy in nodes)
reveal(0.65, card(48, 392, 190, 72) + caps(64, 418, "CODE GRAPH") + glyph + text(64, 444, "functions + call edges", 14, 500))

# ------------------------------------------------------------------ stage 2: the agent
reveal(1.3, card(320, 160, 290, 320, "url(#blueCard)", BLUE, 1.5, 16)
       + caps(340, 188, "GEMMA 4 31B · 4-BIT · OFFLINE", BLUE)
       + text(340, 218, "Triage agent", 22, 700)
       + text(340, 242, "searches, reads and runs code;", 13, 400, INK2)
       + text(340, 260, "writes only to TRIAGE/", 13, 400, INK2)
       + caps(340, 290, "BUDGET · 24 TOOL CALLS · 8 MIN", INK3, 10))
for i in range(24):
    add(f'<rect class="t" x="{340 + i * 10.5}" y="300" width="7.5" height="18" rx="2" fill="{BLUE}" '
        f'style="animation-delay:{round(1.9 + i * 0.07, 2)}s"/>')
reveal(3.4, caps(340, 348, "WRITES", INK3, 10))
for j, (name, what) in enumerate((("TRIAGE/report.md", "suspects · tests"), ("TRIAGE/repro.py", "fails on the bug"),
                                  ("trace", "files it opened"))):
    y = 358 + j * 40
    reveal(3.45 + j * 0.12, f'<rect x="340" y="{y}" width="250" height="32" rx="8" fill="#ffffff" stroke="{BLUE_M}"/>'
           + text(352, y + 21, name, 12, 600, INK, family=MONO) + text(578, y + 21, what, 11.5, 500, INK3, "end"))

# ------------------------------------------------------------------ stage 3: the orchestrator
reveal(4.2, card(690, 160, 310, 470, "url(#orgCard)", ORG, 1.5, 16)
       + caps(710, 188, "PYTHON · CPU · NO MODEL", ORG)
       + text(710, 218, "Orchestrator", 22, 700)
       + text(710, 240, "checks the agent instead of trusting it", 13, 400, INK2))
steps = (("Fallback chain", "report → opened files → retrieval", "60/60 reports"),
         ("Retrieval", "BM25 + call-graph spreading", "0.1 s"),
         ("Confidence", "agent's pick vs retrieval's top 3", "HIGH·MED 29/29"),
         ("Call-graph tests", "test files that call the suspect", "40→62% hit"),
         ("Re-run repro.py", "non-zero exit means reproduced", "44→61% precise"))
for i, (title, detail, pill) in enumerate(steps):
    y = 256 + i * 74
    pw = round(len(pill) * 6.2 + 16)
    reveal(4.5 + i * 0.3, f'<rect x="706" y="{y}" width="278" height="64" rx="10" fill="#ffffff" stroke="{ORG_M}"/>'
           + f'<circle cx="729" cy="{y + 32}" r="12" fill="{ORG}"/>' + text(729, y + 36.5, str(i + 1), 12.5, 700, "#ffffff", "middle")
           + text(751, y + 27, title, 14, 700) + text(751, y + 46, detail, 12, 400, INK2)
           + f'<rect x="{972 - pw}" y="{y + 12}" width="{pw}" height="20" rx="10" fill="{ORG_T}"/>'
           + text(972 - pw / 2, y + 26, pill, 10.5, 700, ORG, "middle"))
draw(RETR_CONF, ORG, 5.4, 1.4, 0.35)
arrowhead(706, 436, "right", ORG, 5.7)

# ------------------------------------------------------------------ stage 4: report and maintainer
reveal(6.0, card(1066, 160, 182, 250, "#ffffff", "url(#both)", 2, 14)
       + caps(1082, 186, "FINAL REPORT") + text(1082, 208, "final_report.md", 13, 600, INK, family=MONO))
fields = (("LOCATION", "dependencies/models.py", INK, MONO, 11), ("CONFIDENCE", "HIGH", ORG, SANS, 13),
          ("TESTS", "test_dependency_class", INK, MONO, 11), ("REPRODUCTION", "REPRODUCED", ORG, SANS, 13))
for k, (key, value, color, family, size) in enumerate(fields):
    y = 232 + k * 44
    reveal(6.55 + k * 0.15, caps(1082, y, key, INK3, 9.5)
           + text(1082, y + 18, value, size, 700 if family == SANS else 500, color, family=family))
reveal(7.3, card(1066, 450, 182, 140, "#ffffff", INK3, 1.2, 14) + caps(1082, 476, "HUMAN IN THE LOOP")
       + text(1082, 502, "Maintainer", 19, 700)
       + "".join(text(1082, 528 + k * 20, line, 12.5, 500, INK2)
                 for k, line in enumerate(("HIGH → approve", "LOW → check first", "wrong → add a hint"))))

# ------------------------------------------------------------------ particles: what moves where
flow(ISSUE, 1.5, BLUE)
flow(READS, 2.2, INK3, r=2.6)
flow(NEIGH, 2.35, INK3, r=2.6)
flow(HANDOFF, 4.4, BLUE, ORG, 3.6, 40)
flow(GRAPH_ORG, 4.9, INK3, ORG, 2.6, 120)
flow(RETR_CONF, 5.75, ORG, r=2.4, spacing=40)
for d, at in FANS:
    flow(d, at + 0.45, ORG, r=2.8, spacing=60)
flow(TO_HUMAN, 7.5, INK2, r=2.6, spacing=40)
flow(HINT, 8.1, INK3, r=2.2, spacing=230)

# ------------------------------------------------------------------ results
results = ((48, "92% · 90%", "right file named first", "retrieval alone: 42% · 30%", 150),
           (458, "65% · 55%", "right test file named first", "agent alone: 48% · 25%", 150),
           (868, "0 / 60", "runs that edited source code", "the agent writes only its notes", 104))
body = f'<line x1="48" y1="664" x2="1232" y2="664" stroke="{RULE}"/>'
for x, big, label, sub, off in results:
    body += (text(x, 708, big, 28, 600, INK, family=SERIF) + f'<rect x="{x}" y="716" width="{off - 22}" height="3" rx="1.5" fill="url(#both)"/>'
             + text(x + off, 696, label, 13.5, 600, INK) + text(x + off, 715, sub, 12, 400, INK3))
body += text(48, 748, "Dev · holdout: 40 · 20 real issues from FastAPI, Rich, Requests and HTTPX. "
                      "Gemma 4 31B (4-bit) on vLLM, fully offline.", 11.5, 400, INK3)
reveal(8.4, body)

defs = f"""<defs>
<linearGradient id="blueCard" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{BLUE_T}"/><stop offset="1" stop-color="#ffffff"/></linearGradient>
<linearGradient id="orgCard" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{ORG_T}"/><stop offset="1" stop-color="#ffffff"/></linearGradient>
<linearGradient id="both" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="{BLUE}"/><stop offset="1" stop-color="{ORG}"/></linearGradient>
<linearGradient id="handoff" gradientUnits="userSpaceOnUse" x1="610" y1="0" x2="690" y2="0"><stop offset="0" stop-color="{BLUE}"/><stop offset="1" stop-color="{ORG}"/></linearGradient>
<linearGradient id="graphToOrg" gradientUnits="userSpaceOnUse" x1="143" y1="0" x2="690" y2="0"><stop offset="0" stop-color="{INK3}"/><stop offset="1" stop-color="{ORG}"/></linearGradient>
<filter id="lift" x="-5%" y="-5%" width="110%" height="115%"><feDropShadow dx="0" dy="1.5" stdDeviation="1.6" flood-color="#3b3526" flood-opacity=".08"/></filter>
</defs>"""
style = """<style>
.a{opacity:0;animation:rise .55s ease-out forwards}
.d{stroke-dasharray:1;stroke-dashoffset:1;animation:draw .6s ease-in-out forwards}
.t{opacity:.14;animation:lit .15s linear forwards}
.f{opacity:0;animation:rise .3s linear forwards}
@keyframes rise{from{opacity:0;transform:translateY(5px)}to{opacity:1;transform:none}}
@keyframes draw{to{stroke-dashoffset:0}}
@keyframes lit{to{opacity:1}}
@media (prefers-reduced-motion:reduce){.a,.t{opacity:1;animation:none;transform:none}.d{stroke-dasharray:none;stroke-dashoffset:0;animation:none}.f{display:none}}
</style>"""
label = ("Architecture: a new issue, the repository and its code graph go to one offline Gemma 4 triage agent, which "
         "writes notes, a reproduction script and a trace. A deterministic orchestrator falls back when notes are "
         "missing, computes confidence from agreement with retrieval, finds tests through call edges and re-runs the "
         "reproduction; each check fills one field of the final report, which a maintainer reads and can answer with a hint.")
svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" '
       f'aria-label="{label}">\n<title>Gemma 4 Issue Triage: how an issue flows through the system</title>\n'
       f"{defs}\n{style}\n" + "\n".join(parts) + "\n</svg>\n")
(HERE / "architecture.svg").write_text(svg, encoding="utf-8")


def chrome(url: str, out: Path, *flags: str) -> None:
    subprocess.run(["google-chrome", "--headless=new", "--disable-gpu", "--hide-scrollbars", f"--window-size={W},{H}",
                    *flags, f"--screenshot={out}", url], check=True, capture_output=True)


chrome(f"file://{HERE / 'architecture.svg'}", HERE / "architecture.png", "--force-device-scale-factor=2",
       "--force-prefers-reduced-motion")
print("wrote", HERE / "architecture.svg", "and", HERE / "architecture.png")

if "--gif" in sys.argv:
    # Freeze the animation at each frame time (CSS and SMIL), screenshot, then encode with ffmpeg.
    fps, seconds = 12, 13.0
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        for f in range(int(fps * seconds)):
            t = f / fps
            (tmp / "frame.html").write_text(
                f'<!doctype html><html><body style="margin:0;background:{PAPER}">{svg}<script>'
                f"const s=document.querySelector('svg');s.pauseAnimations();s.setCurrentTime({t});"
                f"for(const a of document.getAnimations()){{a.pause();a.currentTime={t * 1000};}}</script></body></html>")
            chrome(f"file://{tmp / 'frame.html'}", tmp / f"f{f:04d}.png", "--virtual-time-budget=400")
        palette = tmp / "palette.png"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(fps), "-i", str(tmp / "f%04d.png"),
                        "-vf", "scale=960:-1:flags=lanczos,palettegen=stats_mode=diff", str(palette)], check=True)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(fps), "-i", str(tmp / "f%04d.png"),
                        "-i", str(palette), "-lavfi", "scale=960:-1:flags=lanczos[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=4",
                        "-loop", "0", str(HERE / "architecture.gif")], check=True)
    print("wrote", HERE / "architecture.gif")
