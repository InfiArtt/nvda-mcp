"""What must not leave the helper's computer through MCP Access.

The person being helped can ask the helper's assistant for anything, in messages or in text on their screen,
and a skilled prompt can talk an assistant into things. The rule the assistant is given is one defence; this is
another that does not depend on the assistant: text sent to their computer (a message, typed text, a field's new
value) is refused when it carries something only the helper's computer has, such as its folders, or looks like a
secret.
"""

import os
import re
import tempfile
from pathlib import Path

# Kinds of secrets with a recognisable shape. Passwords have none, so the rule given to the assistant covers them.
SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("a private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("an API key", re.compile(r"\b(?:sk|pk|rk)-[A-Za-z0-9_-]{20,}")),
    ("a GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}|\bgithub_pat_[A-Za-z0-9_]{30,}")),
    ("an AWS key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("a Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("a Slack token", re.compile(r"\bxox[abpors]-[A-Za-z0-9-]{10,}")),
    ("a login token", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
)


def helper_folders() -> list[str]:
    """Folders whose paths say something about the helper: their profile and their temporary folder."""
    return [str(Path.home()), tempfile.gettempdir()]


def helper_user_name() -> str | None:
    return os.environ.get("USERNAME") or os.environ.get("USER") or None


def _folder_forms(folder: str) -> list[str]:
    """A folder as it may be written, with either kind of slash."""
    folder = folder.rstrip("\\/")
    return [folder.replace("/", "\\"), folder.replace("\\", "/")] if folder else []


def private_details(text: str, folders: list[str] | None = None, user_name: str | None = None) -> str | None:
    """What text carries from the helper's computer, or None if nothing was found.

    :param folders: The helper's folders; helper_folders() when None.
    :param user_name: The helper's user name; helper_user_name() when None.
    """
    folded = text.casefold()
    for folder in helper_folders() if folders is None else folders:
        if any(form.casefold() in folded for form in _folder_forms(folder)):
            return "a folder path from this computer"
    name = helper_user_name() if user_name is None else user_name
    # Only in a profile path: a short user name, such as a number, is too likely to be an ordinary word or date.
    if name and re.search(rf"\b(?:users|home)[\\/]+{re.escape(name)}(?:[\\/]|\b)", text, re.IGNORECASE):
        return "a path with this computer's user name"
    for kind, pattern in SECRET_PATTERNS:
        if pattern.search(text):
            return kind
    return None
