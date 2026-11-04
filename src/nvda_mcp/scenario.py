"""Records what NVDA says during a scripted scenario and compares it with a saved baseline."""

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

BASELINE_FORMAT_VERSION = 1


@dataclass
class StepRecord:
    action: str
    spoken: str
    focus: str

    def to_dict(self) -> dict[str, str]:
        return {"action": self.action, "spoken": self.spoken, "focus": self.focus}


@dataclass
class Recording:
    steps: list[StepRecord] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"version": BASELINE_FORMAT_VERSION, "steps": [step.to_dict() for step in self.steps]}

    def to_markdown(self) -> str:
        lines = ["| Step | Action | NVDA said | Focus after |", "|---|---|---|---|"]
        for number, step in enumerate(self.steps, 1):
            cells = [str(number), step.action, step.spoken or "(nothing)", step.focus]
            lines.append("| " + " | ".join(_cell(cell) for cell in cells) + " |")
        return "\n".join(lines)


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def focus_label(focus: dict[str, Any]) -> str:
    return f"{focus.get('name') or '(no name)'} ({focus.get('role') or '?'})"


def load_baseline(path: Path) -> Recording:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("version") != BASELINE_FORMAT_VERSION:
        raise ValueError(f"{path} is not a baseline this version of nvda-mcp can read.")
    return Recording([StepRecord(**step) for step in data["steps"]])


def save_baseline(path: Path, recording: Recording) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(recording.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def text_normaliser(ignore_pattern: str | None, *, collapse_whitespace: bool = False) -> Callable[[str], str]:
    """A function that prepares text for comparing, shared by scenarios and interaction recordings.

    :param ignore_pattern: A regular expression for text that changes from run to run, such as times;
        each match is replaced by "…".
    :param collapse_whitespace: Whether to turn runs of whitespace, including no-break spaces, into one space
        and strip the ends first, so that a time written with a narrow no-break space, as WhatsApp Web does,
        matches a pattern written with a plain space.
    """
    ignore = re.compile(ignore_pattern) if ignore_pattern else None

    def normal(text: str) -> str:
        if collapse_whitespace:
            text = " ".join(text.split())
        return ignore.sub("…", text) if ignore else text

    return normal


def compare(baseline: Recording, recording: Recording, ignore_pattern: str | None = None) -> list[str]:
    """Differences between a baseline and a new recording, one line each; empty when they match.

    :param ignore_pattern: A regular expression for text that changes from run to run, such as times;
        matches are ignored in both recordings.
    """
    normal = text_normaliser(ignore_pattern)
    differences = []
    if [step.action for step in baseline.steps] != [step.action for step in recording.steps]:
        message = (
            "The steps differ from the baseline's, so the runs cannot be compared. "
            "Run with update_baseline to record a new baseline."
        )
        return [message]
    for number, (old, new) in enumerate(zip(baseline.steps, recording.steps), 1):
        if normal(old.spoken) != normal(new.spoken):
            differences.append(
                f"Step {number} ({new.action}): NVDA said {new.spoken or '(nothing)'!r}, "
                f"baseline {old.spoken or '(nothing)'!r}"
            )
        if normal(old.focus) != normal(new.focus):
            differences.append(f"Step {number} ({new.action}): focus on {new.focus}, baseline {old.focus}")
    return differences
