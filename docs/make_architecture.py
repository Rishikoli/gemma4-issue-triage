#!/usr/bin/env python3
"""Render docs/architecture.svg (animated), docs/architecture.png (static) and docs/architecture.gif.

A sequential infographic of one issue (FastAPI #14458) moving through the system. On a 10.5 s loop
the arrows fire one after another in the order data moves: each draws in with a dot riding its
tip, its arrowhead pops, the card it feeds flashes and the stage number ripples, while the other
arrows rest faint. The first loop also builds the diagram stage by stage. Two complementary hues
only: blue is Gemma 4, orange is deterministic code, and the gradient marks where the two meet.
Everything animated switches off under prefers-reduced-motion, which leaves the complete static
picture (that is the PNG). Numbers are from the evaluated runs (docs/results.png, eval/).

    python docs/make_architecture.py [--gif]   (needs Google Chrome; the GIF also needs ffmpeg)
"""
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
W, H, T = 1280, 764, 10.5  # canvas, loop length in seconds
SERIF = "'Iowan Old Style', 'Palatino Linotype', Palatino, Georgia, serif"
SANS = "ui-sans-serif, system-ui, -apple-system, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif"
MONO = "ui-monospace, SFMono-Regular, Menlo, Consolas, 'Liberation Mono', monospace"
PAPER, RULE = "#f7f5f0", "#e2ded4"
INK, INK2, INK3 = "#1d1e23", "#55575f", "#8b8d95"
BLUE, BLUE_T, BLUE_M = "#2f5fd0", "#eaf0fd", "#9db5ec"
ORG, ORG_T, ORG_M = "#e2701b", "#fdf0e4", "#f2b384"

parts: list[str] = []
add = parts.append
keyframes: list[str] = []


def looped(name: str, frames: list[tuple[float, str]]) -> str:
    """A CSS animation on the shared T-second loop; frames are (seconds, declarations)."""
    body = "".join(f"{round(t / T * 100, 3)}%{{{css}}}" for t, css in frames)
    keyframes.append(f"@keyframes {name}{{{body}}}")
    return f"animation:{name} {T}s linear infinite"


def text(x, y, s, size=13, weight=400, fill=INK, anchor="start", family=SANS, extra=""):
    return (f'<text x="{x}" y="{y}" font-family="{family}" font-size="{size}" font-weight="{weight}" '
            f'fill="{fill}" text-anchor="{anchor}" {extra}>{s}</text>')


def caps(x, y, s, fill=INK3, size=10.5, anchor="start"):
    return text(x, y, s, size, 700, fill, anchor, extra='letter-spacing="1.2"')


def card(x, y, w, h, fill="#ffffff", stroke=RULE, sw=1, r=14):
    return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{fill}" stroke="{stroke}" '
            f'stroke-width="{sw}" filter="url(#lift)"/>')


def reveal(at: float, body: str) -> None:
    """A group that rises into view at `at` seconds, once."""
    add(f'<g class="a" style="animation-delay:{at}s">{body}</g>')


def ring(name, x, y, w, h, r, color, at):
    """The card an arrow feeds flashes when the arrow arrives."""
    add(f'<rect class="p" x="{x - 3}" y="{y - 3}" width="{w + 6}" height="{h + 6}" rx="{r + 3}" fill="none" '
        f'stroke="{color}" stroke-width="2.5" style="{looped(name, [(0, "opacity:0"), (at, "opacity:0"), (at + 0.12, "opacity:.9"), (at + 0.9, "opacity:0"), (T, "opacity:0")])}"/>')


TIP = {"right": "l-8 -4.5 v9 z", "down": "l-4.5 -8 h9 z"}


def arrow(name, d, color, at, dur, width=1.8, label=None, lx=0, ly=0, head=None, recolor=None, dashed=False):
    """A connection in the sequence: a faint base line, plus a pulse that draws it in at `at` seconds
    with a dot riding its tip and a popping arrowhead, every loop."""
    end = at + dur
    if dashed:
        add(f'<path class="a base" d="{d}" fill="none" stroke="{INK3}" stroke-opacity=".5" stroke-width="1.4" '
            f'stroke-dasharray="5 6" stroke-linejoin="round" style="animation-delay:{at}s"/>')
    else:
        add(f'<path class="d base" pathLength="1" d="{d}" fill="none" stroke="{color}" stroke-opacity=".42" '
            f'stroke-width="{width}" stroke-linecap="round" stroke-linejoin="round" '
            f'style="animation-delay:{at}s;animation-duration:{dur}s"/>')
    pulse = looped(f"{name}P", [(0, "stroke-dashoffset:1;opacity:0"), (at - 0.001, "stroke-dashoffset:1;opacity:0"),
                                (at, "stroke-dashoffset:1;opacity:1"), (end, "stroke-dashoffset:0;opacity:1"),
                                (end + 0.35, "stroke-dashoffset:0;opacity:1"), (end + 0.85, "stroke-dashoffset:0;opacity:0"),
                                (T, "stroke-dashoffset:0;opacity:0")])
    add(f'<path class="p" pathLength="1" d="{d}" fill="none" stroke="{INK2 if dashed else color}" '
        f'stroke-width="{width + 1.6}" stroke-dasharray="1" stroke-linecap="round" stroke-linejoin="round" style="{pulse}"/>')
    c0 = {"url(#handoff)": BLUE, "url(#graphToOrg)": INK3}.get(color, INK2 if dashed else color)  # the riding dot
    k0, k1 = round(at / T, 4), round(end / T, 4)
    fill = (f'<animate attributeName="fill" dur="{T}s" repeatCount="indefinite" calcMode="linear" '
            f'values="{c0};{c0};{recolor};{recolor}" keyTimes="0;{k0};{k1};1"/>') if recolor else ""
    add(f'<g class="p"><circle r="4.2" fill="{c0}" stroke="#ffffff" stroke-width="1.5" opacity="0">'
        f'<animateMotion dur="{T}s" repeatCount="indefinite" calcMode="linear" path="{d}" '
        f'keyPoints="0;0;1;1" keyTimes="0;{k0};{k1};1"/>'
        f'<animate attributeName="opacity" dur="{T}s" repeatCount="indefinite" calcMode="linear" '
        f'values="0;0;1;1;0;0" keyTimes="0;{round(k0 - 0.001, 4)};{k0};{k1};{round(k1 + 0.01, 4)};1"/>{fill}</circle></g>')
    if label:
        reveal(at + dur * 0.5, "".join(text(lx, ly + i * 12, line, 10.5, 600, INK3, "middle") for i, line in enumerate(label)))
    if head:
        x, y, direction, hc = head
        tip = f"M{x} {y} {TIP[direction]}"
        reveal(end, f'<path d="{tip}" fill="{hc}"/>')
        pop = looped(f"{name}H", [(0, "opacity:0;transform:scale(1)"), (end - 0.001, "opacity:0;transform:scale(1)"),
                                  (end, "opacity:1;transform:scale(1.9)"), (end + 0.25, "opacity:1;transform:scale(1)"),
                                  (end + 0.85, "opacity:0;transform:scale(1)"), (T, "opacity:0;transform:scale(1)")])
        add(f'<path class="p pop" d="{tip}" fill="{hc}" style="{pop}"/>')
    return end


# ------------------------------------------------------------------ paper, header, stage headings
add(f'<rect x=".5" y=".5" width="{W - 1}" height="{H - 1}" rx="20" fill="{PAPER}" stroke="{RULE}"/>')
add(text(48, 64, "Gemma 4 Issue Triage", 31, 600, INK, family=SERIF))
add(text(48, 92, "How a new issue becomes a checked report: the model investigates, plain code verifies, "
                 "a person decides.", 15, 400, INK2))
for y, fill, label in ((47, BLUE, "Gemma 4, the model"), (69, ORG, "Python, no model"), (91, "url(#both)", "where the two meet")):
    add(f'<rect x="1000" y="{y}" width="12" height="12" rx="3" fill="{fill}"/>')
    add(text(1020, y + 10, label, 12.5, 500, INK2))
stages = ((48, "1", "Issue arrives", INK3, 0.0, 0.3), (320, "2", "Gemma 4 investigates", BLUE, 1.0, 1.4),
          (690, "3", "Code checks every claim", ORG, 3.9, 4.3), (1066, "4", "Maintainer decides", INK3, 6.0, 6.55))
for x, n, label, color, at, active in stages:
    reveal(at, f'<circle cx="{x + 9}" cy="136" r="9" fill="{color}"/>'
           + text(x + 9, 140, n, 11, 700, "#ffffff", "middle") + text(x + 25, 141, label, 13.5, 700, INK))
    ripple = looped(f"st{n}", [(0, "opacity:0;transform:scale(1)"), (active, "opacity:.55;transform:scale(1)"),
                               (active + 0.8, "opacity:0;transform:scale(2.3)"), (T, "opacity:0;transform:scale(1)")])
    add(f'<circle class="p pop" cx="{x + 9}" cy="136" r="9" fill="none" stroke="{color}" stroke-width="2" style="{ripple}"/>')

# ------------------------------------------------------------------ the sequence of arrows (under the cards)
FANS = (("M984 288 C1030 288, 1022 238, 1066 238", 238), ("M984 436 C1030 436, 1022 282, 1066 282", 282),
        ("M984 510 C1030 510, 1022 326, 1066 326", 326), ("M984 584 C1030 584, 1022 370, 1066 370", 370))
arrow("issue", "M238 216 H320", BLUE, 0.9, 0.5, 2, ["issue text"], 279, 206, (320, 216, "right", BLUE))
arrow("reads", "M238 332 H320", INK3, 1.6, 0.4, 1.6, ["reads"], 279, 322, (320, 332, "right", INK3))
arrow("neigh", "M238 428 H320", INK3, 1.8, 0.4, 1.6, ["neighbours"], 279, 418, (320, 428, "right", INK3))
arrow("hand", "M610 414 H690", "url(#handoff)", 3.85, 0.45, 3.5, ["notes", "+ trace"], 650, 388,
      (690, 414, "right", ORG), recolor=ORG)
arrow("edges", "M143 464 C143 560, 560 584, 690 584", "url(#graphToOrg)", 4.0, 0.9, 1.6, ["call edges"], 420, 590,
      (690, 584, "right", ORG), recolor=ORG)
arrow("rc", "M706 362 C694 362, 694 436, 704 436", ORG, 5.4, 0.35, 1.4, head=(706, 436, "right", ORG))
for k, (d, y) in enumerate(FANS):
    arrow(f"fan{k}", d, ORG, 6.1 + k * 0.25, 0.45, 1.6, head=(1066, y, "right", ORG))
arrow("human", "M1157 410 V446", INK3, 7.4, 0.3, 1.6, head=(1157, 450, "down", INK3))
reveal(7.55, text(1167, 433, "reads", 10.5, 600, INK3))
arrow("hint", "M1157 590 C1157 625, 1140 642, 1105 642 H90 C55 642, 28 617, 28 582 V252 C28 230, 34 216, 40 216",
      INK3, 7.9, 1.3, head=(48, 216, "right", INK3), dashed=True)
reveal(8.2, text(330, 634, "not convinced? add a hint to the issue and run it again", 11.5, 500, INK3, "middle"))

# ------------------------------------------------------------------ stage 1: inputs
reveal(0.2, card(48, 160, 190, 112) + caps(64, 186, "NEW ISSUE") + text(64, 210, "fastapi #14458", 16, 700)
       + text(64, 232, "class with async __call__", 12.5, 400, INK2) + text(64, 250, "breaks as a dependency", 12.5, 400, INK2))
reveal(0.5, card(48, 296, 190, 72) + caps(64, 322, "REPOSITORY") + text(64, 348, "checkout at the issue", 14, 500))
nodes = ((200, 406), (216, 418), (186, 422))
glyph = "".join(f'<line x1="{a[0]}" y1="{a[1]}" x2="{b[0]}" y2="{b[1]}" stroke="{INK3}" stroke-width="1.2"/>'
                for a, b in zip(nodes, nodes[1:] + nodes[:1]))
glyph += "".join(f'<circle cx="{cx}" cy="{cy}" r="3" fill="{INK2}"/>' for cx, cy in nodes)
reveal(0.65, card(48, 392, 190, 72) + caps(64, 418, "CODE GRAPH") + glyph + text(64, 444, "functions + call edges", 14, 500))
ring("rIssue", 48, 160, 190, 112, 14, INK2, 9.2)

# ------------------------------------------------------------------ stage 2: the agent
reveal(1.3, card(320, 160, 290, 320, "url(#blueCard)", BLUE, 1.5, 16)
       + caps(340, 188, "GEMMA 4 31B · 4-BIT · OFFLINE", BLUE)
       + text(340, 218, "Triage agent", 22, 700)
       + text(340, 242, "searches, reads and runs code;", 13, 400, INK2)
       + text(340, 260, "writes only to TRIAGE/", 13, 400, INK2)
       + caps(340, 290, "BUDGET · 24 TOOL CALLS · 8 MIN", INK3, 10))
ring("rAgent", 320, 160, 290, 320, 16, BLUE, 1.4)
for i in range(24):
    lit = round(1.9 + i * 0.07, 2)
    style = looped(f"t{i}", [(0, "opacity:.14"), (lit, "opacity:.14"), (lit + 0.05, "opacity:1"),
                             (T - 0.5, "opacity:1"), (T - 0.2, "opacity:.14"), (T, "opacity:.14")])
    add(f'<rect class="t" x="{340 + i * 10.5}" y="300" width="7.5" height="18" rx="2" fill="{BLUE}" style="{style}"/>')
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
ring("rOrg", 690, 160, 310, 470, 16, ORG, 4.3)
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
ring("rConf", 706, 404, 278, 64, 10, ORG, 5.75)

# ------------------------------------------------------------------ stage 4: report and maintainer
reveal(6.0, card(1066, 160, 182, 250, "#ffffff", "url(#both)", 2, 14)
       + caps(1082, 186, "FINAL REPORT") + text(1082, 208, "final_report.md", 13, 600, INK, family=MONO))
fields = (("LOCATION", "dependencies/models.py", INK, MONO, 11), ("CONFIDENCE", "HIGH", ORG, SANS, 13),
          ("TESTS", "test_dependency_class", INK, MONO, 11), ("REPRODUCTION", "REPRODUCED", ORG, SANS, 13))
for k, (key, value, color, family, size) in enumerate(fields):
    y = 232 + k * 44
    reveal(6.55 + k * 0.25, caps(1082, y, key, INK3, 9.5)
           + text(1082, y + 18, value, size, 700 if family == SANS else 500, color, family=family))
    ring(f"rField{k}", 1074, y - 14, 166, 38, 6, ORG, 6.55 + k * 0.25)
reveal(7.6, card(1066, 450, 182, 140, "#ffffff", INK3, 1.2, 14) + caps(1082, 476, "HUMAN IN THE LOOP")
       + text(1082, 502, "Maintainer", 19, 700)
       + "".join(text(1082, 528 + k * 20, line, 12.5, 500, INK2)
                 for k, line in enumerate(("HIGH → approve", "LOW → check first", "wrong → add a hint"))))
ring("rHuman", 1066, 450, 182, 140, 14, INK2, 7.7)

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
reveal(8.6, body)

defs = f"""<defs>
<linearGradient id="blueCard" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{BLUE_T}"/><stop offset="1" stop-color="#ffffff"/></linearGradient>
<linearGradient id="orgCard" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{ORG_T}"/><stop offset="1" stop-color="#ffffff"/></linearGradient>
<linearGradient id="both" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="{BLUE}"/><stop offset="1" stop-color="{ORG}"/></linearGradient>
<linearGradient id="handoff" gradientUnits="userSpaceOnUse" x1="610" y1="0" x2="690" y2="0"><stop offset="0" stop-color="{BLUE}"/><stop offset="1" stop-color="{ORG}"/></linearGradient>
<linearGradient id="graphToOrg" gradientUnits="userSpaceOnUse" x1="143" y1="0" x2="690" y2="0"><stop offset="0" stop-color="{INK3}"/><stop offset="1" stop-color="{ORG}"/></linearGradient>
<filter id="lift" x="-5%" y="-5%" width="110%" height="115%"><feDropShadow dx="0" dy="1.5" stdDeviation="1.6" flood-color="#3b3526" flood-opacity=".08"/></filter>
</defs>"""
style = ("<style>"
         ".a{opacity:0;animation:rise .55s ease-out forwards}"
         ".d{stroke-dasharray:1;stroke-dashoffset:1;animation:draw .6s ease-in-out forwards}"
         ".pop{transform-box:fill-box;transform-origin:center}"
         "@keyframes rise{from{opacity:0;transform:translateY(5px)}to{opacity:1;transform:none}}"
         "@keyframes draw{to{stroke-dashoffset:0}}"
         + "".join(keyframes) +
         "@media (prefers-reduced-motion:reduce){.a{opacity:1;animation:none;transform:none}"
         ".d{stroke-dasharray:none;stroke-dashoffset:0;animation:none}.base{stroke-opacity:1}"
         ".t{opacity:1;animation:none!important}.p{display:none}}"
         "</style>")
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


def frame(t: float, out: Path, tmp: Path, *flags: str) -> None:
    """Screenshot the animation frozen at t seconds (CSS and SMIL)."""
    (tmp / "frame.html").write_text(
        f'<!doctype html><html><body style="margin:0;background:{PAPER}">{svg}<script>'
        f"const s=document.querySelector('svg');s.pauseAnimations();s.setCurrentTime({t});"
        f"for(const a of document.getAnimations()){{a.pause();a.currentTime={t * 1000};}}</script></body></html>")
    chrome(f"file://{tmp / 'frame.html'}", out, "--virtual-time-budget=400", *flags)


chrome(f"file://{HERE / 'architecture.svg'}", HERE / "architecture.png", "--force-device-scale-factor=2",
       "--force-prefers-reduced-motion")
print("wrote", HERE / "architecture.svg", "and", HERE / "architecture.png")

if "--frames" in sys.argv:  # stills for checking the sequence: python docs/make_architecture.py --frames 12.3 15.1 ...
    out_dir = HERE.parent / "results" / "frames"  # gitignored
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        for t in map(float, sys.argv[sys.argv.index("--frames") + 1:]):
            frame(t, out_dir / f"architecture_{t}.png", Path(tmp))
            print("wrote", out_dir / f"architecture_{t}.png")

if "--gif" in sys.argv:
    # One loop of the finished diagram (the second loop, after the build), so the GIF repeats seamlessly.
    fps = 12
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        for f in range(int(fps * T)):
            frame(T + f / fps, tmp / f"f{f:04d}.png", tmp)
        palette = tmp / "palette.png"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(fps), "-i", str(tmp / "f%04d.png"),
                        "-vf", "scale=960:-1:flags=lanczos,palettegen=stats_mode=diff", str(palette)], check=True)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(fps), "-i", str(tmp / "f%04d.png"),
                        "-i", str(palette), "-lavfi", "scale=960:-1:flags=lanczos[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=4",
                        "-loop", "0", str(HERE / "architecture.gif")], check=True)
    print("wrote", HERE / "architecture.gif")
