"""Analyses a recorded walk through an application's keyboard focus order."""

from dataclasses import dataclass, field
from typing import Any

# Roles a keyboard user must be able to identify by name alone.
ROLES_NEEDING_NAMES = frozenset(
    {
        "button",
        "link",
        "check box",
        "radio button",
        "combo box",
        "edit",
        "menu item",
        "tab",
        "toggle button",
        "slider",
        "spin button",
        "split button",
        "menu button",
        "tree view item",
    }
)


def focus_signature(focus: dict[str, Any]) -> tuple:
    """Identifies a focused control well enough to notice cycles and stuck focus."""
    return (
        focus.get("name"),
        focus.get("role"),
        focus.get("appName"),
        tuple(focus.get("location") or ()),
    )


@dataclass
class AuditStep:
    index: int
    focus: dict[str, Any]
    spoken: str
    issues: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "step": self.index,
            "spoken": self.spoken,
            "name": self.focus.get("name"),
            "role": self.focus.get("role"),
            "states": self.focus.get("states", []),
            "issues": self.issues,
        }


@dataclass
class AuditReport:
    key: str
    app_name: str | None
    steps: list[AuditStep] = field(default_factory=list)
    stop_reason: str = ""

    @property
    def issue_count(self) -> int:
        return sum(len(step.issues) for step in self.steps)

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "appName": self.app_name,
            "stopReason": self.stop_reason,
            "issueCount": self.issue_count,
            "steps": [step.to_dict() for step in self.steps],
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Focus order audit: {self.app_name or 'unknown app'}",
            "",
            f"Pressed **{self.key}** {len(self.steps) - 1} times. Stopped because: {self.stop_reason}.",
            f"Found **{self.issue_count}** issue(s).",
            "",
            "| Step | NVDA said | Role | Name | Issues |",
            "|---|---|---|---|---|",
        ]
        for step in self.steps:
            cells = [
                str(step.index),
                step.spoken or "(nothing)",
                step.focus.get("role") or "",
                step.focus.get("name") or "",
                "; ".join(step.issues),
            ]
            lines.append(
                "| " + " | ".join(cell.replace("|", "\\|").replace("\n", " ") for cell in cells) + " |"
            )
        return "\n".join(lines)


class FocusOrderAuditor:
    """Accumulates steps and decides when the walk should stop.

    Feed it the starting focus, then each new focus with what NVDA said;
    :meth:`add_step` returns a stop reason once the walk is complete.
    """

    def __init__(self, key: str, start_focus: dict[str, Any], start_spoken: str = "") -> None:
        self.report = AuditReport(key=key, app_name=start_focus.get("appName"))
        self._start_signature = focus_signature(start_focus)
        self._first_step_by_label: dict[tuple, int] = {}
        self._unmoved_count = 0
        self._record(AuditStep(0, start_focus, start_spoken))

    def add_step(self, focus: dict[str, Any], spoken: str) -> str | None:
        step = AuditStep(len(self.report.steps), focus, spoken)
        previous = self.report.steps[-1]
        signature = focus_signature(focus)
        stop_reason = None
        if focus.get("appName") != self.report.app_name:
            step.issues.append(f"Focus left the application (now in {focus.get('appName') or 'unknown'})")
            stop_reason = "focus left the application"
        elif signature == self._start_signature:
            stop_reason = "focus returned to where the audit started"
        elif signature == focus_signature(previous.focus):
            self._unmoved_count += 1
            step.issues.append("Focus did not move: possible keyboard trap, or the end of the focus order")
            if self._unmoved_count >= 2:
                stop_reason = "focus stopped moving"
        else:
            self._unmoved_count = 0
        if not spoken:
            step.issues.append("NVDA said nothing when this control got focus")
        self._record(step)
        if stop_reason:
            self.report.stop_reason = stop_reason
        return stop_reason

    def finish(self, reason: str) -> AuditReport:
        if not self.report.stop_reason:
            self.report.stop_reason = reason
        return self.report

    def _record(self, step: AuditStep) -> None:
        focus = step.focus
        role = focus.get("role")
        name = (focus.get("name") or "").strip()
        if role in ROLES_NEEDING_NAMES and not name:
            step.issues.append(f"Unlabeled {role}: it has no accessible name")
        if name and step.index > 0 and focus_signature(focus) != self._start_signature:
            label = (name, role)
            first = self._first_step_by_label.setdefault(label, step.index)
            if first != step.index and focus_signature(focus) != focus_signature(
                self.report.steps[first].focus
            ):
                step.issues.append(f"Same name and role as step {first}: users cannot tell them apart")
        self.report.steps.append(step)
