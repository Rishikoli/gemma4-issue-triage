"""What the agent looked at, from a harness run trace: the fallback suspects when it wrote no report."""
from __future__ import annotations

from .graph import path_to_module
from .report import TEST_PATH


def opened_modules(trace: dict) -> list[str]:
    """Source modules in the order the agent first read, edited or wrote them, skipping tests, scratch
    files and its own TRIAGE/ notes. When the agent ran out of budget before writing a report, the
    first of these was the right file in 14 of 17 issues in our runs."""
    out = []
    for step in trace.get("steps", []):
        if step.get("source") != "agent":
            continue
        for call in step.get("tool_calls") or []:
            args = call.get("arguments") or {}
            if call.get("function_name") not in ("read_file", "edit_file", "write_file") or not args.get("filepath"):
                continue
            path = str(args["filepath"]).strip().lstrip("/").removeprefix("workspace/")
            if path.startswith(("tmp/", "TRIAGE/")) or TEST_PATH.search(path):
                continue
            if (m := path_to_module(path)) and m not in out:
                out.append(m)
    return out
