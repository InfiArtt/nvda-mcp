# Contributing to NVDA MCP

Bug reports, ideas and pull requests are welcome. The organization's general rules are in the
[InfiArtt contributing guide](https://github.com/InfiArtt/.github/blob/main/CONTRIBUTING.md); this file covers this project.

## How it fits together

```
MCP client ⇄ (stdio) nvda-mcp server ⇄ (HTTP on 127.0.0.1, token) NVDA add-on ⇄ NVDA
```

- **`addon/`**: the NVDA add-on (NVDA 2025.1 or later). It records everything NVDA speaks and runs a small bridge
  that only accepts local, authenticated requests. When NVDA starts, it writes the bridge's port and a fresh token
  to `%APPDATA%\nvda\nvdaMcp\connection.json`.
- **`src/nvda_mcp/`**: the MCP server, built on the official MCP Python SDK. It reads that file on every call,
  so it survives NVDA restarts.

The add-on and the server share one version number and are released together. The bridge has its own protocol
version (`PROTOCOL_VERSION` in `addon/globalPlugins/nvdaMcp/bridge.py`, `SUPPORTED_PROTOCOL_VERSION` in
`src/nvda_mcp/bridge_client.py`). Raise both when a bridge method's parameters or results change incompatibly;
a server and add-on with different protocol versions refuse to work together and say which one to update.

## Development setup

On Windows, with Python 3.11 or later:

```
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
```

Check your work:

```
.venv\Scripts\python -m pytest
.venv\Scripts\ruff check .
.venv\Scripts\ruff format --check .
```

The tests run the real bridge and the real MCP server against a scripted window, so they need no NVDA.
CI runs the same checks on Windows with Python 3.11 and 3.13, and builds the add-on.

Build the add-on:

```
.venv\Scripts\python build_addon.py
```

It writes `dist\nvdaMcp-<version>.nvda-addon`, with the help pages made from `README.md` (English) and
`docs/README.id.md` (Indonesian).

## Trying changes in NVDA

- **Add-on code**: copy the changed files from `addon\globalPlugins\nvdaMcp\` to
  `%APPDATA%\nvda\addons\nvdaMcp\globalPlugins\nvdaMcp\`, then press NVDA+Ctrl+F3 to reload add-ons.
- **Server code**: point your MCP client at your checkout, for example
  `claude mcp add --scope user nvda -- <checkout>\.venv\Scripts\nvda-mcp.exe`.
  A client keeps running the server it started; stop it with `taskkill /IM nvda-mcp.exe /T /F`,
  and the next NVDA tool call starts the new code. Stop it before reinstalling with `pip install -e` as well:
  Windows locks the running `nvda-mcp.exe`, and pip then fails halfway and leaves the package uninstalled.

## Code style

- The add-on follows [NVDA's coding standards](https://github.com/nvaccess/nvda/blob/master/projectDocs/dev/codingStandards.md):
  tabs, camelCase, and every user-facing string wrapped in `_()` with a `# Translators:` comment above it.
- The server and the build script follow PEP 8.
- Write a test for every bug you fix.

Useful references: the [NVDA Developer Guide](https://www.nvaccess.org/files/nvda/documentation/developerGuide.html),
[What's New](https://www.nvaccess.org/files/nvda/documentation/changes.html) and the community
[Add-on Development Guide](https://github.com/nvdaaddons/DevGuide/wiki/NVDA-Add-on-Development-Guide).
Keep local copies in `docs/reference/` if you like; git ignores that folder.

## Translations

User-facing strings are in English. The Indonesian translation is `addon/locale/id/LC_MESSAGES/nvda.po`,
with the add-on's description in `addon/locale/id/manifest.ini` and the help page in `docs/README.id.md`.
`build_addon.py` compiles the `.po` file. A test fails if a translatable string has no translation,
or if a translation loses a `{placeholder}`.

## Releasing

1. Set the new version in `pyproject.toml` and `addon/manifest.ini`, and give the *Unreleased* section of
   `CHANGELOG.md` that version and the date. If dependencies changed, update `THIRD_PARTY_NOTICES.md`
   (`pip list` in a fresh environment with only the server installed shows them).
2. Merge that into `main` through a pull request.
3. Tag the release and push the tag:

   ```
   git tag v1.0.0
   git push origin v1.0.0
   ```

   The release workflow checks that the tag matches both versions, runs the tests, builds the add-on and the
   Python packages, publishes the server to PyPI and creates a GitHub release with the `.nvda-addon` file.
4. Submit the add-on to the NV Access Add-on Store yourself, through the
   [submission form](https://github.com/nvaccess/addon-datastore/issues/new?template=registerAddon.yml),
   with the `.nvda-addon` download link from the GitHub release.
   NV Access does not allow AI tools to interact with that repository.

PyPI publishing uses [trusted publishing](https://docs.pypi.org/trusted-publishers/): no password or token is
stored anywhere. The PyPI project trusts the `release.yml` workflow of this repository, in the `pypi` environment.
