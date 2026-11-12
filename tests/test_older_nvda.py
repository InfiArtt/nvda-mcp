"""The add-on supports NVDA 2025.1 and later; these check the parts that differ before 2026.3."""

import ast
import configparser
import importlib.util
import sys
import types

import pytest
from conftest import ROOT

ADDON_DIR = ROOT / "addon"


def load_install_tasks():
    spec = importlib.util.spec_from_file_location("nvdaMcpInstallTasks", ADDON_DIR / "installTasks.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def config_without_sections(monkeypatch):
    # NVDA before 2026.3: a config package with no configSections module.
    monkeypatch.setitem(sys.modules, "config", types.ModuleType("config"))
    monkeypatch.delitem(sys.modules, "config.configSections", raising=False)


def test_installing_on_nvda_without_config_sections_does_not_fail(config_without_sections):
    tasks = load_install_tasks()
    tasks.onInstall()
    tasks.onUninstall()


def test_installing_on_nvda_with_config_sections_registers_the_section(monkeypatch):
    calls = []
    config_sections = types.ModuleType("config.configSections")
    config_sections.registerSection = lambda name, spec, isBaseOnly: calls.append(
        ("register", name, isBaseOnly)
    )
    config_sections.unregisterSection = lambda name: calls.append(("unregister", name))
    config_package = types.ModuleType("config")
    config_package.configSections = config_sections
    monkeypatch.setitem(sys.modules, "config", config_package)
    monkeypatch.setitem(sys.modules, "config.configSections", config_sections)
    tasks = load_install_tasks()
    tasks.onInstall()
    tasks.onUninstall()
    assert calls == [("register", "nvdaMcp", True), ("unregister", "nvdaMcp")]


def test_braille_extensions_import_falls_back_to_the_braille_module():
    # braille.extensions exists only from NVDA 2026.3; an unguarded import stops the plugin loading.
    for path in ADDON_DIR.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        guarded = {
            id(node)
            for try_node in ast.walk(tree)
            if isinstance(try_node, ast.Try)
            and any(
                isinstance(handler.type, ast.Name) and handler.type.id == "ImportError"
                for handler in try_node.handlers
            )
            for statement in try_node.body
            for node in ast.walk(statement)
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "braille.extensions":
                assert id(node) in guarded, f"Unguarded braille.extensions import in {path}:{node.lineno}"


def test_manifest_supports_nvda_2025_1():
    manifest = configparser.ConfigParser()
    manifest.read_string("[addon]\n" + (ADDON_DIR / "manifest.ini").read_text(encoding="utf-8"))
    assert manifest["addon"]["minimumNVDAVersion"].strip('"') == "2025.1"
