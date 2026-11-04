"""Markdown for nvda_lookup_api: what a name in NVDA's running Python code is, or which names match a search."""

from typing import Any


def _running(result: dict[str, Any]) -> str:
    version = result.get("nvdaVersion")
    return f"NVDA {version}, running now" if version else "the NVDA running now"


def lookup_markdown(result: dict[str, Any]) -> str:
    name = result.get("name", "")
    if not result.get("found"):
        lines = [f"`{name}` was not found in {_running(result)}: {result.get('reason', '')}"]
        if result.get("notLoaded"):
            lines.append(
                f"An add-on can import `{result['notLoaded']}`; look it up again after something has imported it."
            )
        if result.get("suggestions"):
            lines.append(
                "Did you mean: " + ", ".join(f"`{suggestion}`" for suggestion in result["suggestions"])
            )
        return "\n".join(lines)
    lines = [f"## `{name}` ({result['kind']})", f"Found in {_running(result)}."]
    if result.get("deprecated"):
        lines.append(f"- Deprecated: {result['deprecated']}")
    lines.extend(f"- Note: {note}" for note in result.get("notes", []))
    if result.get("signature") is not None:
        lines.append(f"- Signature: `{name.rpartition('.')[2]}{result['signature']}`")
    if result.get("repr"):
        lines.append(f"- Value: `{result['repr']}`")
    elif result.get("type"):
        lines.append(f"- Type: `{result['type']}`")
    if result.get("kind") == "property":
        lines.append("- Can be set" if result.get("settable") else "- Read only")
    where = result.get("module")
    if where:
        lines.append(f"- Defined in: `{where}`" + (f", line {result['line']}" if result.get("line") else ""))
    if result.get("source"):
        lines.append(f"- Source: {result['source']}")
    elif result.get("file"):
        lines.append(f"- File: {result['file']}")
    if result.get("bases"):
        lines.append("- Bases: " + ", ".join(f"`{base}`" for base in result["bases"]))
    if result.get("doc"):
        lines += ["", "### Docstring", "```text", result["doc"], "```"]
    members = result.get("members")
    if members:
        total = result.get("memberCount", len(members))
        lines += [
            "",
            f"### Members ({total})" if total == len(members) else f"### Members ({len(members)} of {total})",
        ]
        for member in members:
            line = f"- `{member['name']}` ({member['kind']})"
            if member.get("value") is not None:
                line += f" = {member['value']}"
            if member.get("summary"):
                line += f": {member['summary']}"
            lines.append(line)
    if result.get("inheritedCount"):
        lines.append(
            f"\nIt also inherits {result['inheritedCount']} public names; "
            "look up a base class to see them, or the full dotted name of one."
        )
    return "\n".join(lines)


def search_markdown(result: dict[str, Any], text: str) -> str:
    entries = result.get("results", [])
    version = result.get("nvdaVersion")
    where = (
        f"the modules of NVDA {version} and its add-ons" if version else "the modules of NVDA and its add-ons"
    )
    if not entries:
        return f'No names containing "{text}" in {where}.'
    lines = [f'Names containing "{text}" in {where}:']
    if result.get("truncated"):
        lines[0] += f" ({result['truncated']})"
    for entry in entries:
        line = f"- `{entry['name']}` ({entry['kind']})"
        if entry.get("summary"):
            line += f": {entry['summary']}"
        lines.append(line)
    lines.append("\nLook one up with name for its signature, docstring and members.")
    return "\n".join(lines)
