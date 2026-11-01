"""Package the NVDA add-on into ``dist/<name>-<version>.nvda-addon``.

It compiles the translations, turns the READMEs into the add-on's help pages, and adds the license.
Usage: python build_addon.py
Needs the ``markdown`` package, which ``pip install -e ".[dev]"`` installs.
"""

import ast
import configparser
import html
import re
import struct
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ADDON_DIR = ROOT / "addon"
DIST_DIR = ROOT / "dist"
EXCLUDED_SUFFIXES = {".po", ".pyc"}
# Development-only files that live next to the add-on code. Hidden files and folders (caches) are skipped too.
EXCLUDED_NAMES = {"ruff.toml"}
# The help page for each language, made from these files. NVDA opens doc/<language>/readme.html.
HELP_SOURCES = {"en": ROOT / "README.md", "id": ROOT / "docs" / "README.id.md"}
LICENSE_FILE = ROOT / "COPYING.txt"
# Markdown links that are not web addresses or anchors, such as docs/using.md.
_RELATIVE_LINK = re.compile(r"\]\((?!https?:|#|mailto:)([^)\s]+)\)")


def parse_po(path: Path) -> dict[str, str]:
    """Read msgid/msgstr pairs from a .po file. Supports the subset this project uses: no plurals or contexts."""
    catalog: dict[str, str] = {}
    current: dict[str, str] = {}
    field = None
    for raw_line in path.read_text(encoding="utf-8").splitlines() + [""]:
        line = raw_line.strip()
        if line.startswith("msgid "):
            if "msgstr" in current:
                catalog[current["msgid"]] = current["msgstr"]
            current, field = {"msgid": ""}, "msgid"
            line = line[len("msgid ") :]
        elif line.startswith("msgstr "):
            current["msgstr"], field = "", "msgstr"
            line = line[len("msgstr ") :]
        elif not line.startswith('"'):
            continue
        current[field] += ast.literal_eval(line)
    if "msgstr" in current:
        catalog[current["msgid"]] = current["msgstr"]
    return catalog


def write_mo(catalog: dict[str, str], path: Path) -> None:
    """Write a GNU .mo file, the format Python's gettext reads."""
    ids = sorted(catalog)
    id_bytes = [msgid.encode("utf-8") for msgid in ids]
    str_bytes = [catalog[msgid].encode("utf-8") for msgid in ids]
    header_size = 7 * 4
    ids_table = header_size
    strs_table = ids_table + len(ids) * 8
    data_start = strs_table + len(ids) * 8
    offsets, data = [], b""
    for entry in id_bytes + str_bytes:
        offsets.append((len(entry), data_start + len(data)))
        data += entry + b"\0"
    header = struct.pack("<7I", 0x950412DE, 0, len(ids), ids_table, strs_table, 0, 0)
    tables = b"".join(struct.pack("<2I", length, offset) for length, offset in offsets)
    path.write_bytes(header + tables + data)


def read_manifest() -> configparser.SectionProxy:
    parser = configparser.ConfigParser()
    parser.read_string("[manifest]\n" + (ADDON_DIR / "manifest.ini").read_text(encoding="utf-8"))
    return parser["manifest"]


def help_page(markdown_path: Path, language: str, title: str, repository_url: str) -> str:
    """A standalone HTML help page from a Markdown file.

    Links to other files in the repository point to them on GitHub, since only this page is in the add-on.
    """
    import markdown

    text = markdown_path.read_text(encoding="utf-8")
    base = markdown_path.parent.relative_to(ROOT).as_posix()
    prefix = f"{repository_url}/blob/main/" + (f"{base}/" if base != "." else "")
    text = _RELATIVE_LINK.sub(lambda match: f"]({prefix}{match.group(1)})", text)
    body = markdown.markdown(text, extensions=["tables", "fenced_code", "toc"])
    return (
        "<!DOCTYPE html>\n"
        f'<html lang="{language}">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{html.escape(title)}</title>\n"
        "<style>body{font-family:sans-serif;max-width:50em;margin:auto;padding:1em;line-height:1.5}"
        "table{border-collapse:collapse}th,td{border:1px solid #888;padding:.3em .6em;text-align:left}"
        "pre{overflow-x:auto;background:#f4f4f4;padding:.6em}</style>\n"
        f"</head>\n<body>\n{body}\n</body>\n</html>\n"
    )


def build() -> Path:
    for po_path in ADDON_DIR.glob("locale/*/LC_MESSAGES/*.po"):
        write_mo(parse_po(po_path), po_path.with_suffix(".mo"))
    manifest = read_manifest()
    name, version = manifest["name"].strip('"'), manifest["version"].strip('"')
    summary, url = manifest["summary"].strip('"'), manifest["url"].strip('"')
    doc_file_name = manifest["docFileName"].strip('"')
    DIST_DIR.mkdir(exist_ok=True)
    output = DIST_DIR / f"{name}-{version}.nvda-addon"
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(ADDON_DIR.rglob("*")):
            relative = path.relative_to(ADDON_DIR)
            if (
                path.is_dir()
                or path.suffix in EXCLUDED_SUFFIXES
                or path.name in EXCLUDED_NAMES
                or "__pycache__" in relative.parts
                or any(part.startswith(".") for part in relative.parts)
            ):
                continue
            archive.write(path, relative.as_posix())
        for language, source in HELP_SOURCES.items():
            archive.writestr(f"doc/{language}/{doc_file_name}", help_page(source, language, summary, url))
        archive.write(LICENSE_FILE, LICENSE_FILE.name)
    return output


if __name__ == "__main__":
    print(f"Built {build()}")
