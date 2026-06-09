# Contributing to dblift

Thank you for your interest in contributing! All contributions are welcome —
bug fixes, new features, database provider support, tests, and documentation
improvements.

## Branches

| Branch | Purpose |
|---|---|
| `main` | Released code. Tagged. Protected. |
| `develop` | Integration branch. All PRs target this. Protected. |
| `fix/<short-desc>` or `feat/<short-desc>` | Topic branches off `develop`. |

## Commit messages — Conventional Commits

Format: `type(scope): subject`.

Allowed `type`:

- `fix` — bug fix
- `feat` — new feature
- `refactor` — no behavior change
- `test` — tests only
- `docs` — documentation
- `ci`, `build`, `chore` — tooling
- `style` — formatting
- `perf`, `sec` — performance / security

Subject: imperative mood, lowercase, no trailing period, < 72 chars.
Body (optional): wrap at 72 chars, explain the *why*.

## Quality gates

These run on every `pull_request` via `.github/workflows/code-quality.yml`
and locally via `pre-commit`:

- `black --check` (line length 100)
- `isort --check` (black profile)
- `flake8` per `.flake8`
- `mypy` per `pyproject.toml`

Coverage floor: **77 %**. Do not regress.

### Running Tests Locally

```bash
python -m pip install -e ".[dev]"
pre-commit install
```

Unit tests are safe to parallelize with pytest-xdist:

```bash
python -m pytest tests/unit -n auto --dist=loadscope -p no:benchmark
```

`--dist=loadscope` keeps tests from the same module/class on one worker
to avoid shared-state surprises while still distributing independent
modules. Use `-n 0` when debugging a single flaky test serially.

### CI

- **PR-level**: lightweight checks — lint, complexity, security scanning,
  secret scanning, dependency audit, regression matrix (SQLite-only, < 1 min).
- **On push to `main` / `release/**`**: full unit suite with coverage gate.
- **`workflow_dispatch`**: trigger any workflow on demand from any branch.

## Pull requests

- **One logical change per PR.** Target < 600 lines of diff.
- **Squash-merge only.** Keeps history linear and readable.
- Fill the *why* in the PR description. Code already says *what*.
- Link any issue or prior PR it depends on.

## Security

- The project license is **MIT**. See `LICENSE`.
- Do not commit secrets, database driver binaries, or customer data.
- Report vulnerabilities privately — see [`SECURITY.md`](SECURITY.md).
