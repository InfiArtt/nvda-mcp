# Instructions for AI coding agents

This file is read by AI coding agents (Claude Code, Codex, GitHub Copilot, Cursor, Gemini and others) working in this repository. People should start with the README and the [InfiArtt contributing guide](https://github.com/InfiArtt/.github/blob/main/CONTRIBUTING.md).

## About this project

NVDA MCP lets AI assistants work with the NVDA screen reader through the Model Context Protocol.
Its users are mostly blind or low vision; some are developers of NVDA add-ons and accessible applications.
It has two parts that share one version number and must be released together:

- `addon/`: an NVDA add-on (Python 3, NVDA 2026.3 or later) with a local HTTP bridge protected by a per-start token.
  It follows NVDA's coding standards: tabs, camelCase, user-facing strings wrapped in `_()` with `# Translators:` comments.
- `src/nvda_mcp/`: the MCP server (Python 3.11 or later, official MCP Python SDK), which talks to the bridge.
  It follows PEP 8.

[README.md](README.md) describes the tools and settings; [docs/using.md](docs/using.md) covers day-to-day use and updating.

## Commands

On Windows, from the repository root:

- Install: `python -m venv .venv`, then `.venv\Scripts\python -m pip install -e ".[dev]"`.
- Test: `.venv\Scripts\python -m pytest`. The tests run the real bridge and server against a scripted window; they need no NVDA.
- Lint: `.venv\Scripts\ruff check .` and `.venv\Scripts\ruff format --check .`.
- Build the add-on: `python build_addon.py` (writes `dist\nvdaMcp-<version>.nvda-addon`).

CI (`.github/workflows/ci.yml`) runs all of these on Windows. Run the tests before committing, and add a test when you fix a bug.

## Rules

- **Accessibility first.** InfiArtt is led by people with disabilities. Every control needs a label that screen readers announce, everything must work with the keyboard alone, and messages should say clearly what happened and what to do next.
- **Never commit secrets**: passwords, API keys, tokens, `.env` files. Push protection blocks known kinds of secrets, but don't rely on it.
- **Don't push to `main`.** Work on a branch and open a pull request.
- **Ask first** before anything that publishes or can't easily be undone: merging, releases, tags, deployments, package uploads, force-pushing, deleting branches or repositories.
- **Never post in other people's repositories** (issues, comments, pull requests, submissions) on the team's behalf. Some communities forbid AI tools from interacting with them; NV Access, for example, bans them from the NVDA Add-on Store repository. Prepare the facts and leave the posting to a person.
- **Be transparent about AI involvement.** Keep `Co-Authored-By` trailers in commits, and don't disguise AI-written text as written by a person.
- Keep changes focused, and match the existing code style, naming and comment density.
- Write code, comments and commit messages in English, with Conventional Commits prefixes (`feat:`, `fix:`, `docs:`, `test:`, `ci:`, `refactor:`). Talk to the team in the language they use with you, often Indonesian.

## Project-specific notes

- **Trying changes in a running NVDA.** Add-on code: copy the changed files to
  `%APPDATA%\nvda\addons\nvdaMcp\globalPlugins\nvdaMcp\`, then press NVDA+Ctrl+F3 or call `nvda_reload_plugins`.
  Server code: the session keeps running the server it started with; stop it with
  `taskkill /IM nvda-mcp.exe /T /F` and the next NVDA tool call starts the new code.
- **The user hears what you do.** Tools that press keys or type act on the user's real computer.
  Say what you will press before pressing it, and never retry after `controlDenied`.
- **Bridge protocol.** Changing a bridge method's parameters or results means raising the protocol version in
  `addon/globalPlugins/nvdaMcp/bridge.py` and `src/nvda_mcp/bridge_client.py` together.
- **Translations.** A test fails when a translatable string has no Indonesian translation in
  `addon/locale/id/LC_MESSAGES/nvda.po`. The `.mo` files are built by `build_addon.py`; don't commit them.
- **Versions** live in `pyproject.toml` and `addon/manifest.ini` and must match. Record changes in `CHANGELOG.md`.
- **Add-on Store.** Submissions to the NV Access Add-on Store are made by a person. Prepare the text and files;
  never open issues or pull requests in `nvaccess/addon-datastore`.
- `docs/reference/` (git-ignored) may hold local copies of NVDA's documentation; README.md links to the originals.
