# Claude Code — project memory for dblift

## Always run unit tests in parallel

Use `-n auto --dist=loadscope` with pytest to run tests in parallel. Serial runs
take 6+ minutes; parallel runs complete in ~60 seconds.

```bash
python -m pytest tests/unit/ -n auto --dist=loadscope -q --no-header
```

## Known environment issue

The system `cryptography` package has a broken Rust/pyo3 extension (`_cffi_backend`
missing). This causes every test to fail locally because `tests/unit/conftest.py`
has an autouse fixture that imports `core.licensing`, which imports `jwt`, which
imports `cryptography`. **This is not a code bug** — CI passes (clean container).

## Always subscribe to PR activity

After opening a PR, immediately call `mcp__github__subscribe_pr_activity` for
it. CI failures and Bugbot / reviewer comments are then delivered as
`<github-webhook-activity>` messages so the session can respond without
polling.

## Pre-push gate: scripts/check_code_quality.sh

**Always run `./scripts/check_code_quality.sh` before pushing a branch.** It runs
the same `black` / `isort` / `flake8` / `mypy` pipeline CI runs and uses
`python -m mypy` so the mypy version matches whichever `requirements-dev.txt`
resolves at install time (currently 2.x — see "mypy version skew" below).

## mypy version skew

CI installs `mypy>=1.3.0` from `requirements-dev.txt`, which resolves to **mypy
2.x** at install time. The system `mypy` on this image is 1.19.1; the
`requirements-dev.txt` install lands a newer 2.x at `/root/.local/bin/mypy`.
The two versions disagree on `unused-ignore` diagnoses — mypy 2.x detects
underlying type errors that 1.19.1 silently passes. Always validate with
`/root/.local/bin/mypy` (the CI-equivalent) before pushing strict-zone changes.

```bash
/root/.local/bin/mypy --config-file pyproject.toml --show-error-codes api/ cli/ config/ core/ db/
```
