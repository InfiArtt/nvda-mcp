import enum
import types

import apiLookup
from apiLookup import lookUp, search, sourceUrl


def _module(name, source):
    module = types.ModuleType(name)
    exec(source, module.__dict__)  # noqa: S102 - small fake NVDA modules written here
    return module


CONTROL_TYPES = _module(
    "controlTypes",
    '''
"""Roles and states."""
import enum

class Role(enum.IntEnum):
    """A control's role."""
    BUTTON = 1
    TOGGLEBUTTON = 2
    EDITABLETEXT = 3

def processAndLabelStates(role, states, reason):
    """Work out which states to report for a control."""
    return states
''',
)
CONTROL_TYPES.Role.__module__ = "controlTypes"
EVENT_HANDLER = _module(
    "eventHandler",
    '''
"""Handles NVDA events."""

def requestEvents(eventName=None, processId=None, windowClassName=None):
    """Request that NVDA always handle events of a certain type from a window in the background."""

lastQueuedFocusObject = None

class _EventExecuter:
    """Runs an event through its handlers."""
    def next(self):
        """Run the next handler."""
''',
)
# As "from controlTypes import Role" would.
EVENT_HANDLER.Role = CONTROL_TYPES.Role
OLD_API = _module(
    "speech",
    '''
"""Speech."""
def speakMessage(text):
    """Speak a message."""

def __getattr__(name):
    if name == "speakText":
        return speakMessage
    raise AttributeError(name)
''',
)
NVDA_OBJECTS = _module(
    "NVDAObjects",
    '''
class NVDAObject:
    """The base of every object NVDA works with."""
    def _get_name(self):
        """The object's name."""
    name = property(_get_name)

    def reportFocus(self):
        """Announce this object as it gains focus."""

    @classmethod
    def objectWithFocus(cls):
        """The object with focus."""
''',
)
MODULES = {
    "controlTypes": CONTROL_TYPES,
    "eventHandler": EVENT_HANDLER,
    "speech": OLD_API,
    "NVDAObjects": NVDA_OBJECTS,
    "json": __import__("json"),
}


def test_function_has_signature_docstring_and_line():
    result = lookUp("eventHandler.requestEvents", MODULES)
    assert result["found"] and result["kind"] == "function"
    assert result["signature"] == "(eventName=None, processId=None, windowClassName=None)"
    assert result["doc"].startswith("Request that NVDA always handle events")
    assert result["module"] == "eventHandler" and result["line"] == 4


def test_enum_member_and_enum_members():
    member = lookUp("controlTypes.Role.TOGGLEBUTTON", MODULES)
    assert member["kind"] == "enum member" and member["repr"] == "Role.TOGGLEBUTTON = 2"
    role = lookUp("controlTypes.Role", MODULES)
    assert role["kind"] == "enum" and role["memberCount"] == 3
    assert [entry["name"] for entry in role["members"]] == ["BUTTON", "TOGGLEBUTTON", "EDITABLETEXT"]


def test_class_lists_its_own_members_with_kinds():
    result = lookUp("NVDAObjects.NVDAObject", MODULES)
    assert result["kind"] == "class"
    kinds = {member["name"]: member["kind"] for member in result["members"]}
    assert kinds == {"name": "property", "reportFocus": "method", "objectWithFocus": "class method"}
    prop = lookUp("NVDAObjects.NVDAObject.name", MODULES)
    assert prop["kind"] == "property" and prop["doc"] == "The object's name." and not prop["settable"]


def test_module_lists_what_it_defines_but_not_what_it_imports():
    result = lookUp("eventHandler", MODULES)
    names = [member["name"] for member in result["members"]]
    assert names == ["requestEvents", "lastQueuedFocusObject"]
    assert result["doc"] == "Handles NVDA events."


def test_missing_name_suggests_close_ones():
    result = lookUp("controlTypes.Role.TOGGLE_BUTTON", MODULES)
    assert not result["found"]
    assert "controlTypes.Role.TOGGLEBUTTON" in result["suggestions"]
    module = lookUp("eventHandlr.requestEvents", MODULES)
    assert not module["found"] and "eventHandler" in module["suggestions"]


def test_name_kept_only_by_module_getattr_is_reported_as_deprecated():
    result = lookUp("speech.speakText", MODULES)
    assert result["found"] and result["kind"] == "function"
    assert "keep deprecated names working" in result["deprecated"]
    assert result["deprecated"].endswith("Use speech.speakMessage instead.")
    assert result["doc"] == "Speak a message."


def test_name_from_a_deprecated_aliases_module_says_what_to_use():
    # As controlTypes does: "from .deprecatedAliases import *".
    aliases = _module("controlTypes.deprecatedAliases", "")
    aliases.ROLE_BUTTON = CONTROL_TYPES.Role.BUTTON
    CONTROL_TYPES.ROLE_BUTTON = CONTROL_TYPES.Role.BUTTON
    try:
        result = lookUp("controlTypes.ROLE_BUTTON", {**MODULES, "controlTypes.deprecatedAliases": aliases})
    finally:
        del CONTROL_TYPES.ROLE_BUTTON
    assert result["deprecated"] == (
        "It comes from controlTypes.deprecatedAliases, kept only so that old add-ons still work. "
        "Use controlTypes.Role.BUTTON instead."
    )


def test_another_name_for_an_enum_member_is_pointed_out():
    CONTROL_TYPES.DEFAULT_ROLE = CONTROL_TYPES.Role.BUTTON
    try:
        result = lookUp("controlTypes.DEFAULT_ROLE", MODULES)
    finally:
        del CONTROL_TYPES.DEFAULT_ROLE
    assert "deprecated" not in result
    assert result["notes"] == ["Another name for controlTypes.Role.BUTTON."]


def test_nvda_getters_are_properties_with_the_getter_docstring():
    class Getter:
        """Like NVDA's baseObject.Getter, which AutoPropertyObject makes from _get_ methods."""

        def __init__(self, fget):
            self.fget = fget

        def __get__(self, instance, owner):
            return self if instance is None else self.fget(instance)

    def _get_liveRegionPoliteness(self):
        """How politely a live region's changes are announced."""

    cls = type("Ia2Web", (), {"liveRegionPoliteness": Getter(_get_liveRegionPoliteness)})
    modules = {"ia2Web": _module("ia2Web", "")}
    modules["ia2Web"].Ia2Web = cls
    result = lookUp("ia2Web.Ia2Web.liveRegionPoliteness", modules)
    assert result["kind"] == "property" and not result["settable"]
    assert result["doc"] == "How politely a live region's changes are announced."
    assert result["signature"] == "(self)"


def test_existing_module_that_is_not_loaded_is_reported():
    result = lookUp("json.tool", MODULES)
    assert not result["found"] and result["notLoaded"] == "json.tool"


def test_plain_values_show_their_repr_but_objects_do_not_run_code():
    class Talkative:
        def __repr__(self):
            raise AssertionError("repr must not run")

    modules = {"globalVars": _module("globalVars", "focusObject = None\nappArgs = None")}
    modules["globalVars"].focusObject = Talkative()
    modules["globalVars"].appArgs = ("--minimal", 3)
    talkative = lookUp("globalVars.focusObject", modules)
    assert talkative["kind"] == "value" and "repr" not in talkative
    assert lookUp("globalVars.appArgs", modules)["repr"] == "('--minimal', 3)"


def test_search_ranks_exact_then_prefix_and_skips_the_standard_library():
    names = [entry["name"] for entry in search("focus", MODULES)["results"]]
    assert set(names) == {
        "eventHandler.lastQueuedFocusObject",
        "NVDAObjects.NVDAObject.reportFocus",
        "NVDAObjects.NVDAObject.objectWithFocus",
    }
    assert search("report", MODULES)["results"][0]["name"] == "NVDAObjects.NVDAObject.reportFocus"
    assert search("dumps", MODULES)["results"] == []
    exact = search("requestEvents", MODULES)["results"]
    assert exact[0] == {
        "name": "eventHandler.requestEvents",
        "kind": "function",
        "summary": "Request that NVDA always handle events of a certain type from a window in the background.",
    }


def test_search_does_not_list_imported_names_twice_and_says_when_cut():
    names = [entry["name"] for entry in search("role", MODULES)["results"]]
    assert "controlTypes.Role" in names and "eventHandler.Role" not in names
    cut = search("e", MODULES, limit=2)
    assert len(cut["results"]) == 2 and "2 shown" in cut["truncated"]


def test_own_modules_exclude_the_standard_library_and_bundled_packages():
    assert apiLookup.isOwnModule("NVDAObjects.IAccessible")
    assert apiLookup.isOwnModule("globalPlugins.nvdaMcp.bridge")
    assert not apiLookup.isOwnModule("json.decoder")
    assert not apiLookup.isOwnModule("wx.lib")


def test_source_url_points_at_the_running_release():
    assert sourceUrl("api", False, 39, "2026.3") == (
        "https://github.com/nvaccess/nvda/blob/release-2026.3/source/api.py#L39"
    )
    assert sourceUrl("NVDAObjects", True, None, "2026.3.1").endswith("/source/NVDAObjects/__init__.py")
    assert sourceUrl("api", False, 39, "2026.4beta1") is None


def test_kinds():
    assert apiLookup.kindOf(enum) == "module"
    assert apiLookup.kindOf(len) == "built-in function"
    assert apiLookup.kindOf(staticmethod(len)) == "static method"
