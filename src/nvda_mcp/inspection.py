"""Turn what NVDA knows about a control into ways an add-on could recognize it.

The add-on sends the raw facts (role, IAccessible2 attributes, UIA properties, containers);
this module ranks them by how likely they are to survive the application being updated.
"""

import re
from dataclasses import dataclass
from typing import Any

# Longer names usually include content that changes, such as a chat's last message.
MAX_NAME_FOR_MATCHING = 40
MAX_SHOWN_CHARS = 60
MAX_CONDITIONS_IN_CODE = 4

# Meta's atomic CSS, as in WhatsApp Web, Facebook and Instagram: x1n2onr6, xjb2p0i, xeuugli.
_ATOMIC_CLASS = re.compile(r"^x[0-9a-z]{5,8}$")
# CSS-in-JS libraries: emotion (css-1x2y3z), styled-components (sc-bdVaJa), styled-jsx (jsx-123).
_CSS_IN_JS_CLASS = re.compile(r"^(css|sc|jsx|emotion)-[0-9A-Za-z_-]+$")
# Letters and digits mixed together, as hashes are: a1b2c3, Button_root__3xk9a. Not h1, col-12 or mt-4.
_MIXED_HASH = re.compile(r"[A-Za-z]\d+[A-Za-z]|\d[A-Za-z]+\d")
# Classes that come and go with the control's state.
_STATE_CLASS = re.compile(
    r"(^|[-_])(focus(ed)?|active|selected|hover(ed)?|open(ed)?|expanded|collapsed|checked|disabled|visible|hidden)$"
    r"|^(is|has)-",
    re.IGNORECASE,
)


def looks_generated_class(token: str) -> bool:
    """Whether a class name looks made by a build tool, so it changes whenever the app is rebuilt."""
    if _ATOMIC_CLASS.match(token) or _CSS_IN_JS_CLASS.match(token):
        return True
    digits = sum(char.isdigit() for char in token)
    return digits >= 2 and _MIXED_HASH.search(token) is not None


def looks_generated_id(value: str) -> bool:
    """Whether an HTML id looks generated: React's useId (:r1:), counters (mui-12345) or hashes."""
    return ":" in value or re.search(r"[-_]\d+$", value) is not None or looks_generated_class(value)


def is_state_class(token: str) -> bool:
    return _STATE_CLASS.search(token) is not None


@dataclass(frozen=True)
class Condition:
    label: str
    expression: str
    why: str
    needs_ia2: bool = False
    needs_uia: bool = False
    # Too common to use unless nothing better is known, such as the HTML tag div.
    weak: bool = False


def _short(text: str, limit: int = MAX_SHOWN_CHARS) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _python_string(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def suggest(info: dict[str, Any]) -> tuple[list[Condition], list[str]]:
    """Conditions that identify the control, most stable first, and what to avoid matching on.

    :param info: The result of the bridge's inspectObject method.
    """
    obj = info.get("object", {})
    attributes = info.get("attributes", {})
    uia = info.get("uia", {})
    conditions: list[Condition] = []
    avoid: list[str] = []

    if info.get("roleConstant"):
        conditions.append(
            Condition(
                f"role {obj.get('role', info['roleConstant'])}",
                f"obj.role == controlTypes.Role.{info['roleConstant']}",
                "stable",
            )
        )
    xml_roles = attributes.get("xml-roles")
    if xml_roles:
        conditions.append(
            Condition(
                f"ARIA role {xml_roles}",
                f'obj.IA2Attributes.get("xml-roles") == {_python_string(xml_roles)}',
                "stable: the page sets it on purpose",
                needs_ia2=True,
            )
        )
    automation_id = uia.get("automationId")
    if automation_id:
        if looks_generated_id(automation_id):
            avoid.append(f"the AutomationId {automation_id!r}: it looks generated")
        else:
            conditions.append(
                Condition(
                    f"AutomationId {automation_id!r}",
                    f"obj.UIAAutomationId == {_python_string(automation_id)}",
                    "stable: the developer sets it for automation",
                    needs_uia=True,
                )
            )
    name = obj.get("name")
    name_from = attributes.get("name-from")
    if name:
        if name_from == "contents":
            avoid.append(f'the name "{_short(name)}": it is made from the text inside, which changes')
        elif len(name) > MAX_NAME_FOR_MATCHING:
            avoid.append(f'the name "{_short(name)}": it is long, so it probably includes changing content')
        else:
            source = f" (from {name_from})" if name_from else ""
            why = "stable until the app renames it; different when the app runs in another language"
            expression = f"obj.name == {_python_string(name)}"
            if name != name.strip():
                # Spaces around a label are easy to lose in the next version of the app.
                expression = f'(obj.name or "").strip() == {_python_string(name.strip())}'
                why += "; the name has spaces around it, so compare it stripped"
            conditions.append(Condition(f'name "{name}"{source}', expression, why))
    html_id = attributes.get("id")
    if html_id:
        if looks_generated_id(html_id):
            avoid.append(
                f'the HTML id "{_short(html_id)}": it looks generated, so it can change on every load'
            )
        else:
            conditions.append(
                Condition(
                    f'HTML id "{html_id}"',
                    f'obj.IA2Attributes.get("id") == {_python_string(html_id)}',
                    "fairly stable",
                    needs_ia2=True,
                )
            )
    tokens = attributes.get("class", "").split()
    generated = [token for token in tokens if looks_generated_class(token)]
    states = [token for token in tokens if token not in generated and is_state_class(token)]
    for token in [token for token in tokens if token not in generated and token not in states][:2]:
        conditions.append(
            Condition(
                f'class "{token}"',
                f'{_python_string(token)} in obj.IA2Attributes.get("class", "").split()',
                "changes only if the page changes the library or code behind it",
                needs_ia2=True,
            )
        )
    if generated:
        shown = ", ".join(generated[:3]) + (", …" if len(generated) > 3 else "")
        avoid.append(
            f"{len(generated)} class name(s) that look generated by a build tool ({shown}): "
            "they change when the app is updated"
        )
    if states:
        avoid.append(f"class names that follow the control's state ({', '.join(states)}): they come and go")
    tag = attributes.get("tag")
    if tag:
        conditions.append(
            Condition(
                f"HTML tag {tag}",
                f'obj.IA2Attributes.get("tag") == {_python_string(tag)}',
                "stable, but matches many elements on its own",
                needs_ia2=True,
                weak=True,
            )
        )
    window_class = obj.get("windowClassName")
    if window_class and not attributes and not window_class.startswith("Chrome_"):
        conditions.append(
            Condition(
                f"window class {window_class}",
                f"obj.windowClassName == {_python_string(window_class)}",
                "stable in desktop applications",
            )
        )
    return conditions, avoid


def overlay_code(conditions: list[Condition], api: str | None) -> str:
    """Example chooseNVDAObjectOverlayClasses code using the most stable conditions, in NVDA's style."""
    strong = [condition for condition in conditions if not condition.weak]
    chosen = (strong if len(strong) >= 2 else conditions)[:MAX_CONDITIONS_IN_CODE]
    if not chosen:
        return ""
    checks = [condition.expression for condition in chosen]
    imports = ["import controlTypes", "import globalPluginHandler"]
    if any(condition.needs_ia2 for condition in chosen):
        imports.append("from NVDAObjects.IAccessible import IAccessible")
        checks.insert(0, "isinstance(obj, IAccessible)")
    elif api == "UIA" or any(condition.needs_uia for condition in chosen):
        imports.append("from NVDAObjects.UIA import UIA")
        checks.insert(0, "isinstance(obj, UIA)")
    body = "\n\t\t\tand ".join(checks)
    # A global plugin, since the app module of a browser is shared by every site.
    return (
        "\n".join(imports)
        + "\n\n\nclass GlobalPlugin(globalPluginHandler.GlobalPlugin):\n"
        + "\tdef chooseNVDAObjectOverlayClasses(self, obj, clsList):\n"
        + f"\t\tif (\n\t\t\t{body}\n\t\t):\n"
        + "\t\t\tclsList.insert(0, MyOverlayClass)\n"
    )


def _entry_label(entry: dict[str, Any]) -> str:
    label = entry.get("role") or "?"
    if entry.get("name"):
        label += f' "{_short(entry["name"], 40)}"'
    attributes = entry.get("attributes", {})
    extras = [f"{key}={attributes[key]}" for key in ("xml-roles", "id") if attributes.get(key)]
    if attributes.get("tag") and attributes.get("tag") != entry.get("role"):
        extras.insert(0, f"<{attributes['tag']}>")
    if extras:
        label += f" [{', '.join(extras)}]"
    return label


def _attribute_value(key: str, value: str) -> str:
    if key == "class":
        tokens = value.split()
        generated = sum(looks_generated_class(token) for token in tokens)
        shown = " ".join(tokens[:6]) + (" …" if len(tokens) > 6 else "")
        if generated:
            return f"{shown} ({len(tokens)} classes, {generated} look generated)"
        return shown
    return _short(value, 120)


def to_markdown(info: dict[str, Any]) -> str:
    obj = info.get("object", {})
    attributes = info.get("attributes", {})
    title = f"{obj.get('role', 'unknown role')}"
    if obj.get("name"):
        title += f' "{_short(obj["name"])}"'
    lines = [f"## {title}"]
    api = info.get("api")
    if api or info.get("nvdaClass"):
        lines.append(f"- API: {api or '?'}, NVDA class {info.get('nvdaClass', '?')}")
    if info.get("roleConstant"):
        lines.append(f"- Role constant: controlTypes.Role.{info['roleConstant']}")
    for key, label in (
        ("value", "Value"),
        ("description", "Description"),
        ("states", "States"),
        ("appName", "Application"),
        ("windowClassName", "Window class"),
    ):
        if key in obj:
            value = obj[key]
            lines.append(
                f"- {label}: {', '.join(value) if isinstance(value, list) else _short(str(value), 120)}"
            )
    if info.get("ancestors"):
        path = [_entry_label(entry) for entry in info["ancestors"]]
        lines.append(f"- Inside: {' › '.join(path)}")
    if attributes:
        lines += ["", "### IAccessible2 attributes"]
        lines += [f"- {key}: {_attribute_value(key, value)}" for key, value in sorted(attributes.items())]
    if info.get("uia"):
        lines += ["", "### UI Automation"]
        lines += [f"- {key}: {value}" for key, value in info["uia"].items()]
    table = info.get("table")
    if table:
        lines += ["", "### Rows"]
        reported = _reported_rows(info)
        if reported is not None:
            lines.append(f"- The application says it has: {reported}")
        loaded = f"{table['loadedRows']}{'+' if table.get('loadedRowsIsCut') else ''}"
        lines.append(f"- In the accessibility tree now: {loaded}")
        if reported is not None and table["loadedRows"] < reported:
            lines.append(
                "- The rest are created only when scrolled into view (a virtual list). "
                "An add-on has to scroll the real list to reach them."
            )
    children = info.get("children")
    if children and children.get("first"):
        shown = len(children["first"])
        lines += [
            "",
            f"### Children (first {shown}, unnamed layout containers skipped; {children.get('count', '?')} direct)",
        ]
        lines += [f"- {_entry_label(child)}" for child in children["first"]]
    conditions, avoid = suggest(info)
    lines += ["", "### How an add-on could recognize it"]
    if conditions:
        lines.append("Most stable first:")
        lines += [
            f"{number}. {condition.label}: `{condition.expression}` ({condition.why})"
            for number, condition in enumerate(conditions, 1)
        ]
    else:
        lines.append("Nothing about this control is distinctive; match a container above it instead.")
    if avoid:
        lines += ["", "Avoid matching on:"]
        lines += [f"- {item}" for item in avoid]
    code = overlay_code(conditions, api)
    if code:
        lines += ["", "```python", code.rstrip("\n"), "```"]
    return "\n".join(lines)


def _reported_rows(info: dict[str, Any]) -> int | None:
    """How many rows the application says the table or list has, from ARIA or IAccessibleTable."""
    for value in (info.get("attributes", {}).get("rowcount"), info.get("table", {}).get("rowCount")):
        try:
            count = int(value)
        except (TypeError, ValueError):
            continue
        if count >= 0:
            return count
    return None
