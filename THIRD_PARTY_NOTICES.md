# Third-party notices

NVDA MCP is free software under the GNU General Public License, version 2 or later ([COPYING.txt](COPYING.txt)).
It is copyright (C) 2026 InfiArtt. This file lists the work of others that it uses.

## The NVDA add-on

The add-on (`nvdaMcp-<version>.nvda-addon`) contains only NVDA MCP's own code, its translations, its help pages and
its license. It bundles no third-party code.

- It runs inside [NVDA](https://www.nvaccess.org), copyright NV Access Limited, licensed under the
  [GNU General Public License, version 2](https://github.com/nvaccess/nvda/blob/master/copying.txt),
  and uses NVDA's programming interfaces. That is why the add-on is GPL-licensed too.
- `COPYING.txt` is the text of the GNU General Public License, version 2, copyright the Free Software Foundation,
  which permits copying and distributing it verbatim.

## The nvda-mcp server

The server's packages (`nvda_mcp-<version>.whl` and `.tar.gz`) contain only NVDA MCP's own code.
When you install the server, pip or uv downloads the packages below from the Python Package Index;
each comes with its own license file. They are listed here for your information.

The versions are the ones current when this list was last checked; the server accepts newer ones within the ranges
in `pyproject.toml`. Its direct dependencies are **mcp** and **httpx**; the rest are what those depend on.

| Package | Version | License | Source |
|---|---|---|---|
| annotated-types | 0.8.0 | MIT | https://github.com/annotated-types/annotated-types |
| anyio | 4.16.0 | MIT | https://github.com/agronholm/anyio |
| attrs | 26.1.0 | MIT | https://github.com/python-attrs/attrs |
| certifi | 2026.10.23 | MPL-2.0 | https://github.com/certifi/python-certifi |
| click | 8.5.0 | BSD-3-Clause | https://github.com/pallets/click |
| h11 | 0.16.0 | MIT | https://github.com/python-hyper/h11 |
| httpcore | 1.0.9 | BSD-3-Clause | https://github.com/encode/httpcore |
| httpcore2 | 2.16.0 | BSD-3-Clause | https://github.com/pydantic/httpx2 |
| httpx | 0.28.1 | BSD-3-Clause | https://github.com/encode/httpx |
| httpx2 | 2.16.0 | BSD-3-Clause | https://github.com/pydantic/httpx2 |
| idna | 3.20 | BSD-3-Clause | https://github.com/kjd/idna |
| jsonschema | 4.26.0 | MIT | https://github.com/python-jsonschema/jsonschema |
| jsonschema-specifications | 2025.9.1 | MIT | https://github.com/python-jsonschema/jsonschema-specifications |
| mcp (MCP Python SDK) | 2.3.0 | MIT | https://github.com/modelcontextprotocol/python-sdk |
| mcp-types | 2.3.0 | MIT | https://github.com/modelcontextprotocol/python-sdk |
| opentelemetry-api | 1.45.2 | Apache-2.0 | https://github.com/open-telemetry/opentelemetry-python |
| pydantic | 2.14.2 | MIT | https://github.com/pydantic/pydantic |
| pydantic_core | 2.50.2 | MIT | https://github.com/pydantic/pydantic-core |
| PyJWT | 2.15.1 | MIT | https://github.com/jpadilla/pyjwt |
| python-multipart | 0.0.33 | Apache-2.0 | https://github.com/Kludex/python-multipart |
| pywin32 | 312 | PSF-2.0 | https://github.com/mhammond/pywin32 |
| referencing | 0.37.0 | MIT | https://github.com/python-jsonschema/referencing |
| rpds-py | 2026.9.1 | MIT | https://github.com/crate-py/rpds |
| sse-starlette | 3.6.0 | BSD-3-Clause | https://github.com/sysid/sse-starlette |
| starlette | 1.10.0 | BSD-3-Clause | https://github.com/Kludex/starlette |
| truststore | 0.10.5 | MIT | https://github.com/sethmlarson/truststore |
| typing_extensions | 4.16.0 | PSF-2.0 | https://github.com/python/typing_extensions |
| typing-inspection | 0.4.4 | MIT | https://github.com/pydantic/typing-inspection |
| uvicorn | 0.54.0 | BSD-3-Clause | https://github.com/Kludex/uvicorn |

All of these licenses allow use with GPL software. The Apache-2.0 and MPL-2.0 packages are compatible with
the GNU GPL version 3, which NVDA MCP's "or later" clause allows.

## Tools used to build and test

These are used to develop NVDA MCP but are not part of anything it distributes:

| Tool | License | Source |
|---|---|---|
| hatchling | MIT | https://github.com/pypa/hatch |
| build | MIT | https://github.com/pypa/build |
| Python-Markdown (makes the add-on's help pages) | BSD-3-Clause | https://github.com/Python-Markdown/markdown |
| pytest | MIT | https://github.com/pytest-dev/pytest |
| Ruff | MIT | https://github.com/astral-sh/ruff |

## Services

- [uv](https://github.com/astral-sh/uv) (MIT or Apache-2.0), which the README suggests for running the server,
  is installed separately by the user and is not distributed with NVDA MCP.
- Donations go through PayPal; NVDA MCP only links to the PayPal page and sends it no data.
