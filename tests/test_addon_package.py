import ast
import gettext
import zipfile

from conftest import ROOT

import build_addon

ADDON_DIR = ROOT / "addon"
INDONESIAN_PO = ADDON_DIR / "locale" / "id" / "LC_MESSAGES" / "nvda.po"


def translatable_strings() -> set[str]:
    """Every string literal passed to _() in the add-on's code."""
    found = set()
    for path in ADDON_DIR.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "_":
                assert isinstance(node.args[0], ast.Constant), (
                    f"Non-literal _() argument in {path}:{node.lineno}"
                )
                found.add(node.args[0].value)
    return found


def test_every_translatable_string_has_an_indonesian_translation():
    catalog = build_addon.parse_po(INDONESIAN_PO)
    missing = translatable_strings() - set(catalog)
    assert not missing, f"Add these to {INDONESIAN_PO.name}: {missing}"
    assert all(catalog[msgid] for msgid in translatable_strings())


def test_translations_keep_format_placeholders():
    for msgid, msgstr in build_addon.parse_po(INDONESIAN_PO).items():
        for placeholder in ("{port}", "{control}"):
            assert (placeholder in msgid) == (placeholder in msgstr), msgid


def test_built_mo_file_is_readable_by_gettext(tmp_path):
    mo_path = tmp_path / "nvda.mo"
    build_addon.write_mo(build_addon.parse_po(INDONESIAN_PO), mo_path)
    with mo_path.open("rb") as file:
        translations = gettext.GNUTranslations(file)
    assert translations.gettext("read only") == "hanya baca"


def test_package_contains_plugin_manifest_and_translations():
    output = build_addon.build()
    with zipfile.ZipFile(output) as archive:
        names = set(archive.namelist())
    assert {
        "manifest.ini",
        "installTasks.py",
        "globalPlugins/nvdaMcp/__init__.py",
        "locale/id/LC_MESSAGES/nvda.mo",
        "locale/id/manifest.ini",
    } <= names
    assert not any(name.endswith((".po", ".pyc", "ruff.toml")) for name in names)
    assert not any(part.startswith(".") for name in names for part in name.split("/"))
