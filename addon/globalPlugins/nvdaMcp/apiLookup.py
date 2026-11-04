# NVDA MCP add-on
# Copyright (C) 2026 InfiArtt
# This file is covered by the GNU General Public License.

"""Looks up names in the Python code NVDA is running, for add-on developers.

NVDA's API changes from one year's release to the next, so code written from memory often uses names
that no longer exist. This reads the running NVDA instead: whether a name exists, what it is,
its signature and docstring, and its members. It never calls the code it looks at, except a module's
``__getattr__``, which NVDA uses to keep deprecated names working.

This module does not import NVDA, so it can be unit tested on its own.
"""

import difflib
import enum
import importlib.util
import inspect
import re
import sys
import time
import types
from collections.abc import Callable, Mapping
from types import ModuleType
from typing import Any

MAX_DOC_CHARS = 1500
MAX_MEMBERS = 150
MAX_REPR_CHARS = 200
MAX_SUGGESTIONS = 8
MAX_SEARCH_CANDIDATES = 500
SEARCH_SECONDS = 2.0
# Packages NVDA bundles that are not NVDA's own code; searching them only adds noise.
THIRD_PARTY_PACKAGES = frozenset(
	{
		"brlapi",
		"certifi",
		"charset_normalizer",
		"comtypes",
		"configobj",
		"diff_match_patch",
		"fast_diff_match_patch",
		"idna",
		"l2m4m",
		"latex2mathml",
		"louis",
		"markdown",
		"mdx_gh_links",
		"mdx_truly_sane_lists",
		"nh3",
		"numpy",
		"pycaw",
		"pythoncom",
		"pywintypes",
		"requests",
		"serial",
		"six",
		"typing_extensions",
		"urllib3",
		"validate",
		"win32api",
		"win32con",
		"win32gui",
		"winrt",
		"wx",
	},
)
_MISSING = object()
# Enum members' properties are DynamicClassAttribute objects rather than plain properties.
_PROPERTY_TYPES = (property, types.DynamicClassAttribute)


def isOwnModule(name: str) -> bool:
	"""Whether a module is NVDA's or an add-on's, rather than Python's standard library or a bundled package."""
	top = name.partition(".")[0]
	return top not in sys.stdlib_module_names and top not in THIRD_PARTY_PACKAGES


def sourceUrl(moduleName: str, isPackage: bool, line: int | None, nvdaVersion: str) -> str | None:
	"""Where NVDA's own module is on GitHub, for the release that is running; None for alpha and beta builds."""
	if not re.fullmatch(r"\d{4}\.\d+(\.\d+)?", nvdaVersion):
		return None
	path = moduleName.replace(".", "/") + ("/__init__.py" if isPackage else ".py")
	anchor = f"#L{line}" if line else ""
	return f"https://github.com/nvaccess/nvda/blob/release-{nvdaVersion}/source/{path}{anchor}"


def _firstLine(doc: str | None) -> str | None:
	if not doc:
		return None
	for line in inspect.cleandoc(doc).splitlines():
		if line.strip():
			return line.strip()[:MAX_REPR_CHARS]
	return None


def _doc(value: Any) -> str | None:
	doc = value.__doc__ if isinstance(value, (type, ModuleType)) else getattr(value, "__doc__", None)
	if not isinstance(doc, str) or not doc.strip():
		return None
	doc = inspect.cleandoc(doc)
	return doc if len(doc) <= MAX_DOC_CHARS else doc[:MAX_DOC_CHARS] + " …"


def _ownAttribute(value: Any, name: str) -> Any:
	"""An attribute stored on the object itself, read without running any of its code."""
	try:
		return object.__getattribute__(value, "__dict__").get(name)
	except (AttributeError, TypeError):
		return None


def _isGetter(value: Any) -> bool:
	"""Whether a value is a property of NVDA's own kind: baseObject.Getter, made from a _get_ method."""
	return hasattr(type(value), "__get__") and _ownAttribute(value, "fget") is not None


def _function(value: Any) -> Any:
	"""The plain function behind a staticmethod, classmethod or property getter, if any."""
	if isinstance(value, (staticmethod, classmethod)):
		return value.__func__
	if isinstance(value, _PROPERTY_TYPES):
		return value.fget
	if _isGetter(value):
		getter = _ownAttribute(value, "fget")
		return getter.__func__ if isinstance(getter, classmethod) else getter
	return value


def kindOf(value: Any, inClass: bool = False) -> str:
	"""What a value is, as an add-on developer would call it."""
	if inspect.ismodule(value):
		return "module"
	if isinstance(value, type):
		return "enum" if issubclass(value, enum.Enum) else "class"
	if isinstance(value, enum.Enum):
		return "enum member"
	if isinstance(value, staticmethod):
		return "static method"
	if isinstance(value, classmethod):
		return "class method"
	if isinstance(value, _PROPERTY_TYPES) or _isGetter(value):
		return "property"
	if inspect.isfunction(value):
		return "method" if inClass else "function"
	if inspect.isbuiltin(value) or inspect.ismethoddescriptor(value):
		return "built-in function"
	if callable(value):
		return "callable"
	return "value"


def _signature(value: Any) -> str | None:
	try:
		return str(inspect.signature(value))
	except (TypeError, ValueError):
		return None


def _line(value: Any) -> int | None:
	code = getattr(value, "__code__", None)
	return getattr(code, "co_firstlineno", None)


def _safeRepr(value: Any) -> str | None:
	"""A repr only for plain data, so no object's own code runs; NVDA objects may talk to other processes."""
	if isinstance(value, enum.Enum):
		return f"{type(value).__name__}.{value.name} = {value.value!r}"[:MAX_REPR_CHARS]
	if value is None or isinstance(value, (bool, int, float, str, bytes)):
		return repr(value)[:MAX_REPR_CHARS]
	if isinstance(value, (tuple, list, set, frozenset, dict)) and len(value) <= 50:
		items = list(value.items()) if isinstance(value, dict) else list(value)
		flat = [item for pair in items for item in (pair if isinstance(value, dict) else (pair,))]
		if all(item is None or isinstance(item, (bool, int, float, str)) for item in flat):
			return repr(value)[:MAX_REPR_CHARS]
	return None


def _deprecation(value: Any, doc: str | None) -> str | None:
	"""Why a value looks deprecated, if it does."""
	message = getattr(_function(value), "__deprecated__", None)
	if isinstance(message, str):
		return message or "Marked as deprecated."
	if doc and "deprecated" in doc.casefold():
		return "Its docstring mentions that it is deprecated."
	return None


def _members(container: Any, moduleName: str | None) -> list[dict[str, Any]]:
	"""The public names a class or module defines itself, with what each is."""
	inClass = isinstance(container, type)
	members = []
	for name, value in list(vars(container).items()):
		if name.startswith("_"):
			continue
		if not inClass:
			if inspect.ismodule(value):
				continue
			defined = (
				getattr(value, "__module__", None)
				if isinstance(value, type) or inspect.isfunction(value)
				else None
			)
			if defined is not None and defined != moduleName:
				# Imported from elsewhere, such as "from logHandler import log".
				continue
		member: dict[str, Any] = {"name": name, "kind": kindOf(value, inClass)}
		summary = (
			_firstLine(getattr(_function(value), "__doc__", None)) if member["kind"] != "value" else None
		)
		if summary:
			member["summary"] = summary
		members.append(member)
		if len(members) >= MAX_MEMBERS:
			break
	return members


def _suggestions(name: str, candidates: list[str]) -> list[str]:
	folded = {candidate.casefold(): candidate for candidate in candidates}
	matches = [
		folded[match] for match in difflib.get_close_matches(name.casefold(), folded, MAX_SUGGESTIONS, 0.6)
	]
	needle = name.casefold()
	for candidate in candidates:
		if len(matches) >= MAX_SUGGESTIONS:
			break
		if needle in candidate.casefold() and candidate not in matches:
			matches.append(candidate)
	return matches


def _publicNames(container: Any) -> list[str]:
	try:
		return [name for name in dir(container) if not name.startswith("__")]
	except Exception:  # noqa: BLE001 - a broken __dir__
		return []


def _findSpec(name: str) -> bool:
	try:
		return importlib.util.find_spec(name) is not None
	except (ImportError, ValueError):
		return False


def _canonicalName(value: Any, owner: Any) -> str | None:
	"""The name to use for a class, function or enum member, rather than another name for it."""
	if isinstance(value, enum.Enum):
		cls = type(value)
		if isinstance(owner, ModuleType) and vars(owner).get(cls.__name__) is cls:
			return f"{owner.__name__}.{cls.__name__}.{value.name}"
		return f"{cls.__module__}.{cls.__qualname__}.{value.name}"
	if isinstance(value, type) or inspect.isfunction(value):
		return f"{value.__module__}.{value.__qualname__}"
	return None


def _deprecatedModule(
	owner: ModuleType, attr: str, value: Any, modules: Mapping[str, ModuleType]
) -> str | None:
	"""The deprecated-aliases module a module's name comes from, as with controlTypes.ROLE_BUTTON."""
	prefix = owner.__name__ + "."
	for moduleName, module in list(modules.items()):
		if (
			moduleName.startswith(prefix)
			and "deprecat" in moduleName.casefold()
			and isinstance(module, ModuleType)
			and vars(module).get(attr, _MISSING) is value
		):
			return moduleName
	return None


def lookUp(name: str, modules: Mapping[str, ModuleType]) -> dict[str, Any]:
	"""Describe a dotted name, such as ``controlTypes.Role.BUTTON`` or ``eventHandler.requestEvents``.

	:param modules: The loaded modules, normally ``sys.modules``.
	"""
	parts = [part for part in name.strip().split(".") if part]
	if not parts:
		return {"found": False, "name": name, "reason": "The name is empty."}
	split = len(parts)
	while split and parts and not isinstance(modules.get(".".join(parts[:split])), ModuleType):
		split -= 1
	if not split:
		if _findSpec(parts[0]):
			return {
				"found": False,
				"name": name,
				"notLoaded": parts[0],
				"reason": f"The module {parts[0]} exists but NVDA has not loaded it; importing it would load it.",
			}
		topLevel = sorted({moduleName.partition(".")[0] for moduleName in list(modules)})
		return {
			"found": False,
			"name": name,
			"reason": f"No loaded module is called {parts[0]}.",
			"suggestions": _suggestions(parts[0], topLevel),
		}
	moduleName = ".".join(parts[:split])
	value: Any = modules[moduleName]
	path = moduleName
	owner: Any = None
	notes: list[str] = []
	deprecated: str | None = None
	for attr in parts[split:]:
		try:
			found = inspect.getattr_static(value, attr)
		except AttributeError:
			found = _MISSING
		if found is _MISSING and inspect.ismodule(value):
			if _findSpec(f"{path}.{attr}"):
				return {
					"found": False,
					"name": name,
					"notLoaded": f"{path}.{attr}",
					"reason": f"The module {path}.{attr} exists but NVDA has not loaded it; importing it would load it.",
				}
			if "__getattr__" in vars(value):
				try:
					found = getattr(value, attr)
					deprecated = (
						f"{path} only provides {attr} through its module __getattr__, "
						"which NVDA uses to keep deprecated names working."
					)
				except Exception:  # noqa: BLE001 - AttributeError, or a broken __getattr__
					found = _MISSING
		if found is _MISSING:
			return {
				"found": False,
				"name": name,
				"reason": f"{path} has no {attr}.",
				"suggestions": [
					f"{path}.{suggestion}" for suggestion in _suggestions(attr, _publicNames(value))
				],
			}
		if deprecated is None and inspect.ismodule(value):
			source = _deprecatedModule(value, attr, found, modules)
			if source:
				deprecated = f"It comes from {source}, kept only so that old add-ons still work."
		owner, value, path = value, found, f"{path}.{attr}"
	canonical = _canonicalName(value, owner)
	if deprecated and canonical and canonical != path:
		deprecated += f" Use {canonical} instead."
	elif isinstance(value, enum.Enum) and canonical and path.rpartition(".")[2] != value.name:
		notes.append(f"Another name for {canonical}.")
	return describe(path, value, owner, notes, deprecated)


def describe(
	path: str,
	value: Any,
	owner: Any = None,
	notes: list[str] | None = None,
	deprecated: str | None = None,
) -> dict[str, Any]:
	"""What a looked-up value is: its kind, signature, docstring, where it is defined and its members."""
	inClass = isinstance(owner, type)
	kind = kindOf(value, inClass)
	function = _function(value)
	doc = _doc(function) if kind not in ("value", "enum member") else None
	result: dict[str, Any] = {"found": True, "name": path, "kind": kind, "notes": list(notes or [])}
	if doc:
		result["doc"] = doc
	deprecation = deprecated or (_deprecation(value, doc) if kind not in ("value", "enum member") else None)
	if deprecation:
		result["deprecated"] = deprecation
	if kind == "module":
		result["module"] = value.__name__
		result["isPackage"] = hasattr(value, "__path__")
		result["file"] = getattr(value, "__file__", None)
		result["members"] = _members(value, value.__name__)
		return result
	result["module"] = getattr(function, "__module__", None) or getattr(owner, "__module__", None)
	if isinstance(owner, ModuleType):
		result["module"] = getattr(function, "__module__", None) or owner.__name__
	if callable(function) or kind == "property":
		signature = _signature(function)
		if signature is not None:
			result["signature"] = signature
		line = _line(function)
		if line:
			result["line"] = line
	if kind == "property":
		result["settable"] = isinstance(value, _PROPERTY_TYPES) and getattr(value, "fset", None) is not None
	if kind in ("class", "enum"):
		result["bases"] = [f"{base.__module__}.{base.__qualname__}" for base in value.__bases__]
		result["mro"] = [f"{cls.__module__}.{cls.__qualname__}" for cls in value.__mro__[1:12]]
		if kind == "enum":
			result["members"] = [
				{"name": member.name, "kind": "enum member", "value": _safeRepr(member.value)}
				for member in list(value)[:MAX_MEMBERS]
			]
			result["memberCount"] = len(value)
		else:
			result["members"] = _members(value, None)
			result["inheritedCount"] = len(
				{name for base in value.__mro__[1:] for name in vars(base) if not name.startswith("_")}
			)
	if kind in ("value", "enum member"):
		result["type"] = f"{type(value).__module__}.{type(value).__qualname__}"
		shown = _safeRepr(value)
		if shown is not None:
			result["repr"] = shown
	return result


def search(
	text: str,
	modules: Mapping[str, ModuleType],
	limit: int = 30,
	isOwn: Callable[[str], bool] = isOwnModule,
	seconds: float = SEARCH_SECONDS,
) -> dict[str, Any]:
	"""Find names containing text in NVDA's and add-ons' loaded modules, and in the classes they define.

	Exact names come first, then names starting with the text, then the rest.
	"""
	needle = text.strip().casefold()
	if not needle:
		return {"results": [], "truncated": None}
	candidates: list[dict[str, Any]] = []
	truncated = None
	deadline = time.monotonic() + seconds

	def add(name: str, value: Any, inClass: bool = False) -> None:
		entry: dict[str, Any] = {"name": name, "kind": kindOf(value, inClass)}
		summary = _firstLine(getattr(_function(value), "__doc__", None)) if entry["kind"] != "value" else None
		if summary:
			entry["summary"] = summary
		candidates.append(entry)

	# A copy, as NVDA may import modules meanwhile.
	for moduleName, module in sorted(dict(modules).items(), key=lambda item: item[0]):
		if not isinstance(module, ModuleType) or not isOwn(moduleName):
			continue
		if time.monotonic() > deadline:
			truncated = f"stopped after {seconds:g} seconds"
			break
		if len(candidates) >= MAX_SEARCH_CANDIDATES:
			truncated = f"stopped after {MAX_SEARCH_CANDIDATES} matches"
			break
		if needle in moduleName.rpartition(".")[2].casefold():
			add(moduleName, module)
		try:
			items = list(vars(module).items())
		except TypeError:
			continue
		for name, value in items:
			if name.startswith("__") or inspect.ismodule(value):
				continue
			defined = (
				getattr(value, "__module__", None)
				if isinstance(value, type) or inspect.isfunction(value)
				else None
			)
			if defined is not None and defined != moduleName:
				continue
			if needle in name.casefold():
				add(f"{moduleName}.{name}", value)
			if isinstance(value, type):
				for memberName, member in list(vars(value).items()):
					if not memberName.startswith("__") and needle in memberName.casefold():
						add(f"{moduleName}.{name}.{memberName}", member, inClass=True)

	def rank(entry: dict[str, Any]) -> tuple[int, int, str]:
		last = entry["name"].rpartition(".")[2]
		folded = last.casefold()
		match = 0 if folded == needle else 1 if folded.startswith(needle) else 2
		return (match, last.startswith("_"), entry["name"].casefold())

	candidates.sort(key=rank)
	if len(candidates) > limit:
		truncated = truncated or f"{len(candidates)} matches, {limit} shown"
	return {"results": candidates[:limit], "truncated": truncated}
