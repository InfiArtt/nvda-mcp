# Instructions for AI coding agents

This file is read by AI coding agents (Claude Code, Codex, GitHub Copilot, Cursor, Gemini and others) working in this repository. People should start with the README and the [InfiArtt contributing guide](https://github.com/InfiArtt/.github/blob/main/CONTRIBUTING.md).

## About this project

<!-- Replace with: what the project does, who uses it, and its main language and framework. -->

## Commands

<!-- Replace with this project's real commands. These are the defaults that CI (.github/workflows/ci.yml) runs. -->

- Python: `pip install -r requirements.txt`, then `pytest`. CI also runs `python -m compileall -q .`.
- Node.js: `npm ci`, then `npm run lint`, `npm run build` and `npm test`.

Run the tests before committing, and add a test when you fix a bug.

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

<!-- Add what an agent should know about this project as you learn it: architecture, pitfalls, how releases work, files that must not be edited by hand. -->
