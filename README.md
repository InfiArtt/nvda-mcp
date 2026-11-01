# Project name

One or two sentences about what this project does and who it is for.

## Using this template

This repository is the starting point for new InfiArtt projects. On GitHub, choose **Use this template**, then **Create a new repository**. Your new repository comes with:

- **CI** (`.github/workflows/ci.yml`): on every push to `main` and every pull request, it checks Python code (installs requirements, checks that every file compiles, runs `pytest` if there is a `tests` folder) and Node.js code (installs, then runs the `lint`, `build` and `test` scripts if they exist). Steps for a language you don't use are skipped.
- **Dependabot** (`.github/dependabot.yml`): weekly pull requests that keep the GitHub Actions used by CI up to date. Add your package ecosystem (pip, npm, ...) there once the project has dependencies.
- A **`.gitignore`** for Python, Node.js, editors and operating systems.
- **`AGENTS.md`** (and `CLAUDE.md`, which loads it): instructions for AI coding agents such as Claude Code, Codex or Copilot. Agents read it automatically, so the team's rules apply whichever tool someone uses.

Issue forms, the pull request template and the contributing guide come from the organization automatically.

After creating your repository:

1. Replace this README with one about your project.
2. Fill in the project sections of `AGENTS.md` (what it is, the real commands), and add notes there as you learn them.
3. Add a license if the project needs one (**Add file** > **Create new file** > name it `LICENSE`, then **Choose a license template**).

Public repositories get secret scanning and push protection as soon as they are created, and protection for the default branch (no deleting it, no force-pushing) within a day.

## Contributing

See the [InfiArtt contributing guide](https://github.com/InfiArtt/.github/blob/main/CONTRIBUTING.md).
