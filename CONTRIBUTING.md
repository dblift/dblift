# Contributing to dblift

## Current program: stabilization (v1.3.x → v2.0)

The project is in an active stabilization program. **New features are on
hold.** Pull requests outside this scope are declined unless explicitly
approved:

1. Bug fixes (with a regression test)
2. Refactors listed in `docs/stabilization-plan.md`
3. Test coverage additions
4. Documentation improvements
5. CI / tooling hardening

## Branches

| Branch | Purpose |
|---|---|
| `main` | Released code. Tagged. Protected. |
| `develop` | Integration branch. All PRs target this. Protected. |
| `fix/<short-desc>` or `refactor/<short-desc>` | Topic branches off `develop`. |
| `claude/<...>` | Agent-authored branches. Must still pass every gate. |

## Commit messages — Conventional Commits

Format: `type(scope): subject`.

Allowed `type`:

- `fix` — bug fix
- `refactor` — no behavior change
- `test` — tests only
- `docs` — documentation
- `ci`, `build`, `chore` — tooling
- `style` — formatting
- `feat` — frozen during stabilization; requires explicit approval
- `perf`, `sec` — performance / security

Subject: imperative mood, lowercase, no trailing period, < 72 chars.
Body (optional): wrap at 72 chars, explain the *why*.

## Quality gates

These run on every `pull_request` via `.github/workflows/code-quality.yml`
and locally via `pre-commit`:

- `black --check` (line length 100)
- `isort --check` (black profile)
- `flake8` per `.flake8` (ignore list is documented and shrinking)
- `mypy` per `pyproject.toml`

Additional gates, not yet blocking but tracked:

- Coverage (Codecov). Current floor: **77 %**. Do not regress.

### Running Tests Locally

Unit tests are safe to parallelize with pytest-xdist using scope-based
scheduling:

```bash
python -m pytest tests/unit -n auto --dist=loadscope -p no:benchmark
```

`--dist=loadscope` keeps tests from the same module/class on one worker,
which avoids most shared-state surprises from module-level monkeypatching
while still distributing independent modules. Use `-n 0` when debugging a
single flaky test serially.

### CI Test Evidence Policy

The full unit-test and integration-test workflows do **not** run on every
pull request — that would consume too many GitHub Actions minutes given
the size of the suites (unit-tests alone runs > 15 min × Python 3.11 +
3.12 matrix). Triggers:

- `push` to `main`, `release/**` → `unit-tests.yml`
  (full unit suite + `--cov-fail-under=77` absolute floor)
- `push` to `main`, `release/**` → `integration-tests-new.yml`
- PR-level: lightweight checks only — `lint`, `xenon` (cyclomatic
  complexity), `bandit` (static security), `gitleaks` (secret scanning),
  `pip-audit` (dependency vulnerabilities), `regression matrix`
  (SQLite-only subprocess regression suite, < 1 min). Full unit + full
  integration are intentionally deferred to release time.
- `workflow_dispatch` from any branch → either workflow on demand

The historical `pr-patch-coverage.yml` workflow (selective unit run via
`pytest-testmon`, codecov patch gate ≥ 80 %) was dropped — see CHANGELOG
1.6.0 § Removed. Rationale: the testmon index needs a full-suite refresh
to stay comprehensive, which costs the same as just running the full
unit suite on PR; and unit-only patch coverage understates real
coverage because integration tests contribute substantially to the
final number. The 77 % combined-coverage floor at release time is the
authoritative gate.

Contributors are still responsible for recording test evidence before merge:

- Run the relevant focused regression tests locally for every bug fix.
- Run `python -m pytest tests/unit -n auto --dist=loadscope -p no:benchmark`
  locally before requesting review (always parallel — the suite is large).
- For database-behavior changes, manually dispatch the relevant integration
  workflow or document why the change is covered by unit/matrix tests only.

**Release gate.** A release branch (`release/x.y.z`) automatically triggers
both `unit-tests.yml` and `integration-tests-new.yml` on every push. The
PR from `release/x.y.z` to `main` MUST not be merged until both workflows
are green — this is the project's invariant that every released version has
a passing full test suite.

**A PR is not mergeable** if any gate fails, any Bugbot `High` or `Medium`
thread is unresolved, or any new entry was added to the `.flake8` ignore
list without a cleanup ticket. **A release PR (`release/x.y.z` → `main`)
additionally requires both unit-tests.yml and integration-tests-new.yml
to be green on the release branch.**

### Local setup

```bash
python -m pip install -e ".[dev]"
pre-commit install
pre-commit run --all-files
```

## Pull requests

- **One logical change per PR.** Target < 600 lines of diff.
- Use the PR template checklist (`.github/pull_request_template.md`).
- **Squash-merge only.** Keeps history linear and readable.
- Fill the *why* in the PR description. Code already says *what*.
- Link the issue, ADR, or prior PR it depends on.

## Architecture Decision Records (ADR)

Any structural change — new module boundary, API contract change, new
dependency, process change — requires an ADR under `docs/adr/`:

```
docs/adr/NNNN-short-title.md
```

Use [MADR](https://adr.github.io/madr/) format. ADRs are immutable once
merged; supersede by writing a new one.

## Security / licensing

- The project license is **proprietary**. See `LICENSE`.
- Do not commit secrets, database driver binaries, or customer data. `.gitignore` is
  there; it is not infallible.
- Report vulnerabilities privately — see [`SECURITY.md`](SECURITY.md).
