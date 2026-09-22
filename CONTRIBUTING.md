# Contributing to DBLift

Thanks for taking the time. Bug reports, engine quirks, documentation fixes and code are all welcome.

## Questions and ideas

Use [Discussions](https://github.com/dblift/dblift/discussions) for "how do I…", "would you accept…" and "here is how we use it". Use [Issues](https://github.com/dblift/dblift/issues) for things that are broken.

Security problems: do not open an issue — follow [SECURITY.md](SECURITY.md).

## A good bug report

The fastest bugs to fix come with:

- `dblift --version`, the database engine and its version, and how you run DBLift (CLI, Python API, a framework integration);
- the smallest migration file that reproduces the problem — most bugs are about one statement the parser or an engine handles badly;
- the command you ran and the full output (`--log-level debug` helps).

Remove credentials from URLs and logs before pasting.

## Development setup

Python 3.11 or 3.12.

```bash
git clone https://github.com/dblift/dblift.git
cd dblift
python -m venv .venv && source .venv/bin/activate
python -m pip install -e ".[dev]"
python -m pip install -e packages/pytest-dblift   # only if you touch the pytest plugin
```

SQLite needs no server and no extra, so most of the code can be exercised locally. Add an engine extra when you work on one, e.g. `pip install -e ".[dev,postgresql]"` (DuckDB, `.[dev,duckdb]`, also runs without a server).

## Tests

```bash
python -m pytest tests/unit -q                 # unit suite, no services needed
python -m pytest packages/pytest-dblift/tests  # pytest plugin
```

Integration tests under `tests/integration/` run against real databases in containers; see [tests/integration/README.md](tests/integration/README.md). You do not need them for most changes — CI runs them.

**Write the test first.** For a bug, the first thing in the pull request is a test that fails against the current code for the reason you describe; then the fix. A test added after the fix proves much less.

## Before you push

```bash
./scripts/check_code_quality.sh
```

It runs the same black, isort, flake8 and mypy checks as CI. Line length is 100.

## Pull requests

- Branch from `develop` and open the pull request against `develop`. `main` only receives releases.
- Branch names: `fix/<slug>`, `feat/<slug>`, `docs/<slug>`.
- Commits follow [Conventional Commits](https://www.conventionalcommits.org/): `fix(sqlite): …`, `feat(cli): …`, `docs: …`.
- Add a line to `CHANGELOG.md` under `[Unreleased]` when a user can notice the change, written in the user's terms.
- Keep a pull request to one subject. Unrelated clean-ups belong in their own.
- Say what you verified and how. If a claim is about how a database engine behaves, cite the vendor documentation or show the output.

## Adding or changing engine behaviour

Engine differences live in each engine's plugin under `dblift/db/plugins/`. A statement about what an engine does is a factual claim — back it with a test against that engine or a link to its documentation, because a wrong capability silently affects every engine that inherits from it.

## Licence

DBLift is [Apache 2.0](LICENSE). By contributing you agree that your contribution is licensed under the same terms.

## Changing the public surface

`tests/unit/contracts/` fails when the CLI, the `DBLiftClient` parameters, the
SQLite history table, the `info --format json` keys or the exit codes change.

- **You added something** (a flag, a parameter with a default, a JSON key):
  add a line to the `Unreleased` section of `CHANGELOG.md`, then run
  `DBLIFT_UPDATE_CONTRACTS=1 python -m pytest tests/unit/contracts` and commit
  the updated snapshot with your change.
- **The failure says BREAKING:** something users rely on disappeared. Restore
  it. If it really has to go, deprecate it first as described in
  `docs/semver-policy.md` section 3.
- **The removal is intended and this is a MAJOR release:** regenerate the
  snapshot in the same commit, next to the CHANGELOG entry that announces
  the removal.

`scripts/check_debt_ratchet.py` fails when a structural-debt count grows. Fix
the new occurrence rather than raising the cap; when your change lowers a
count, lower the cap in `.debt-ratchet.json` in the same pull request.
