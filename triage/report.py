"""Read the agents' TRIAGE/ files, check the reproduction, set confidence, and write the final report."""
from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .graph import path_to_module

TEST_PATH = re.compile(r"(^|/)(tests?|testing)/|(^|/)test_[^/]*\.py$|_test\.py$|(^|/)conftest\.py$")


def section(text: str, title: str) -> str:
    m = re.search(rf"^##\s*{re.escape(title)}\s*$(.*?)(?=^##\s|\Z)", text, flags=re.M | re.S | re.I)
    return m.group(1).strip() if m else ""


def test_module(path: str) -> str | None:
    path = path.split("::")[0].strip().lstrip("/").removeprefix("workspace/")
    if not path.endswith(".py"):
        return None
    parts = path[:-3].split("/")
    return ".".join(parts[1:] if parts[0] == "src" else parts)


@dataclass
class AgentFindings:
    suspects: list[str] = field(default_factory=list)      # modules, most likely first
    tests: list[str] = field(default_factory=list)         # test modules
    claimed_repro: str | None = None                       # what the agent said
    observed: str = ""
    questions: str = ""


def read_agent_files(triage_dir: Path) -> AgentFindings:
    """Works for the single agent (report.md) and the localizer + reproducer pair (locations.md, repro.md)."""
    parts = [p.read_text(errors="replace") for name in ("report.md", "locations.md", "repro.md")
             if (p := triage_dir / name).exists()]
    text = "\n".join(parts)
    f = AgentFindings()
    for p in re.findall(r"([\w./-]+\.py)", section(text, "Suspected location")):
        if not TEST_PATH.search(p) and (m := path_to_module(p)) and m not in f.suspects:
            f.suspects.append(m)
    for p in re.findall(r"([\w./-]+\.py)", section(text, "Tests to run")):
        if (m := test_module(p)) and m not in f.tests:
            f.tests.append(m)
    status = re.search(r"Status:\s*(REPRODUCED|NOT_REPRODUCED|NOT_ATTEMPTED)", section(text, "Reproduction"), re.I)
    f.claimed_repro = status.group(1).upper() if status else None
    f.observed = section(text, "Reproduction")
    f.questions = section(text, "Open questions for the maintainer")
    return f


def check_reproduction(workspace: Path, timeout: int = 60) -> tuple[str, str]:
    """Re-run TRIAGE/repro.py ourselves. The agent's own 'REPRODUCED' was right 44% of the time in our runs;
    trusting the exit code instead (fails on the current code = reproduced) raised that to 61%."""
    script = workspace / "TRIAGE" / "repro.py"
    if not script.exists():
        return "NOT_ATTEMPTED", ""
    paths = [str(workspace / "src")] if (workspace / "src").is_dir() else []
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(paths + [str(workspace)]), PYTHONDONTWRITEBYTECODE="1")
    try:
        p = subprocess.run([sys.executable, str(script)], cwd=workspace, env=env, capture_output=True,
                           text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return "NOT_REPRODUCED", f"timed out after {timeout} s"
    tail = "\n".join((p.stdout + p.stderr).strip().splitlines()[-4:])
    return ("REPRODUCED" if p.returncode != 0 else "NOT_REPRODUCED"), tail


def confidence(agent_top: str | None, retrieval: list[str]) -> str:
    """Agreement between the agent's top suspect and model-free retrieval. In our runs the agent was right
    98% of the time when both agreed on the top module, 86% when its pick was in retrieval's top 3."""
    if not agent_top or not retrieval:
        return "LOW"
    if agent_top == retrieval[0]:
        return "HIGH"
    return "MEDIUM" if agent_top in retrieval[:3] else "LOW"


def render(issue_title: str, suspects: list[str], source: str, conf: str, retrieval: list[str],
           tests: list[str], repro_status: str, repro_tail: str, findings: AgentFindings) -> str:
    why = {"HIGH": "the agent and model-free retrieval agree", "MEDIUM": "the agent's pick is in retrieval's top 3",
           "LOW": "the agent and retrieval disagree, or the agent named no location"}[conf]
    out = [f"# Triage: {issue_title}", "", f"**Confidence: {conf}** ({why})", "", "## Suspected location"]
    out += [f"{i}. `{m}`" for i, m in enumerate(suspects[:3], 1)] or ["(none)"]
    out += ["", f"_Source: {source}. Retrieval's top 3: {', '.join(f'`{m}`' for m in retrieval[:3]) or '(none)'}._",
            "", "## Tests to run"]
    out += [f"- `{t}`" for t in tests[:5]] or ["- (none found)"]
    out += ["", "## Reproduction", f"Status (checked by running the script): **{repro_status}**"]
    if findings.claimed_repro and findings.claimed_repro != repro_status:
        out.append(f"_The agent reported {findings.claimed_repro}._")
    if repro_tail:
        out += ["```", repro_tail, "```"]
    out += ["", "## Open questions for the maintainer", findings.questions or "- (none)"]
    return "\n".join(out) + "\n"
