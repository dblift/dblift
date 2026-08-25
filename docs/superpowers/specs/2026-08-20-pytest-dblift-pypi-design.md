# pytest-dblift as a published PyPI package

Date: 2026-08-20

## Problem

`pytest-dblift` is documented as a Python-ecosystem integration (`pip install pytest-dblift` in the root README, CHANGELOG 1.8.0, SQLAlchemy examples). It has never been a buildable or published artifact: there is no package in the current tree, no `pytest11` extra on `dblift`, and no project on PyPI. A reader who follows the README cannot install it.

Unpackaged plugin source exists (fixtures, `pytest11` entry point, SQLite self-tests). It is not a wheel: its `pyproject.toml` has no `[build-system]`, and it was never included in the publish pipeline.

## Goal

Make `pip install pytest-dblift` install a real pytest plugin that matches the documented 0.1.0 surface, and publish that wheel from this repository's existing PyPI workflow.

Success:

- `pip install pytest-dblift` from PyPI loads the plugin without a manual import.
- Fixtures listed below are available in consumer tests.
- Docs in this repo describe the fixtures and CLI options that actually ship.
- A GitHub Release that publishes `dblift` also publishes `pytest-dblift` only when that package version is new.

## Non-goals

- New fixtures beyond replacing `dblift_undo_smoke` with `dblift_undo`.
- Implementing `--dblift-no-migrate` (declared today, never read).
- A `validate_sql` fixture, testcontainers, multi-dialect plugin tests.
- A separate GitHub repository or independent `pytest-dblift-v*` tags.
- Lockstep version numbers with `dblift`.
- Website / marketing orbit copy (different repository). Once PyPI exists, `pip install pytest-dblift` there becomes true without this change.
- Rewriting the 1.8.0 CHANGELOG entry.

## Package identity and layout

Path: `packages/pytest-dblift/`. Not part of the `dblift` wheel. Root `[tool.setuptools.packages.find]` stays limited to `api*`, `cli*`, `config*`, `core*`, `db*`, `integrations*`.

| Field | Value |
| --- | --- |
| PyPI name | `pytest-dblift` |
| Version | `0.1.0` (first publish; independent of `dblift`) |
| Import package | `pytest_dblift` |
| pytest11 entry | `dblift = pytest_dblift.plugin` |
| Python | `>=3.11` |
| License | Apache-2.0 |
| Dependencies | `dblift>=3.9`, `pytest>=7.3`, `sqlalchemy>=2.0` |
| Build backend | setuptools, same as the root package |
| URLs | `https://github.com/dblift/dblift` |

`python -m build` run from `packages/pytest-dblift/` produces that package's sdist and wheel only.

`pytest-dblift` depends on bare `dblift`, not `dblift[postgresql]` or any other engine extra. Engine plugins ship in the `dblift` wheel; extras only install native drivers. A SQLite-only consumer must not pull `psycopg` (or any other driver) via this package.

Ship: `pytest_dblift/` (plugin code), `pyproject.toml`, package `README.md`, package tests. Do not ship local `logs/`, `*.egg-info`, or `__pycache__`.

## Plugin surface (0.1.0)

pytest loads `pytest_dblift.plugin` via the `pytest11` entry point. Fixtures live in `pytest_dblift.fixtures`, not in a consumer `conftest.py`. No fixture is `autouse`.

### CLI options

- `--dblift-url` — SQLAlchemy URL. Default: session-scoped temporary SQLite **file** (not `:memory:`).
- `--dblift-migrations-dir` — a single migrations directory, default `migrations` (resolved against pytest `rootdir` when relative). Not a comma-separated list: the current resolver does not split, so the help text must not claim that.

`--dblift-no-migrate` is removed from `pytest_addoption`. It is not implemented.

### Fixtures

| Fixture | Scope | Depends on | Behavior |
| --- | --- | --- | --- |
| `dblift_config` | session | pytest config, `tmp_path_factory` | Dict with `url`, `migrations_dir`, optional `schema`. Overridable. |
| `dblift_engine` | session | `dblift_config` | `create_engine(url)`; `dispose()` on teardown. Overridable. |
| `dblift_client` | session | `dblift_engine`, `dblift_config` | `DBLiftClient.from_sqlalchemy(...)`; `close()` on teardown. |
| `dblift_migrated_db` | function | `dblift_client` | `client.migrate()`; assert success; yield the client. |
| `dblift_empty_db` | function | `dblift_client` | `client.clean(clean_enabled=True)`; assert success; yield the client. |
| `dblift_validate` | function | `dblift_client` | Return a callable that runs `client.validate(**kwargs)` and asserts success. |
| `dblift_undo` | function | `dblift_client` | Return a callable that runs `client.undo(**kwargs)` and asserts success. |

`dblift_undo` does **not** auto-migrate. A test that needs applied migrations requests `dblift_migrated_db` as well:

```python
def test_rollback(dblift_migrated_db, dblift_undo):
    result = dblift_undo(target_version="0")
    assert result.success
```

Undo uses companion `U*` scripts, the same as the rest of dblift. There is no `undo()` function inside a `V*.py` migration.

`dblift_undo_smoke` is not part of the public surface. It was an alias of `dblift_migrated_db` for an internal smoke test.

Marker `dblift` stays registered.

### xdist

Only the **default** SQLite file path is worker-specific (`test_gw0.db`, …) via pytest-xdist `workerinput`. A URL passed with `--dblift-url` is used as-is.

Consumers override `dblift_config` or `dblift_engine` in their `conftest.py` (same pattern as pytest-alembic).

### Connecting (drivers)

The plugin does not open its own database URL besides `create_engine(url)` and `DBLiftClient.from_sqlalchemy(engine, ...)`. It uses whatever driver is already importable in the environment.

- **SQLite (default):** no extra. `sqlite3` is stdlib; a file URL is enough.
- **Any other engine:** the consumer installs the matching dblift extra *before* (or together with) the plugin, then points pytest at that database:

```bash
pip install pytest-dblift "dblift[postgresql]"
pytest --dblift-url "postgresql+psycopg://user:pass@localhost/app_test"
```

Installing the extra installs the native driver (`psycopg`, `PyMySQL`, …). `pytest-dblift` does not declare those extras and does not substitute a second connection. A missing driver fails at `create_engine` / first connect, the same as any other SQLAlchemy program.

## Failure behavior

`dblift_migrated_db`, `dblift_empty_db`, `dblift_validate`, and `dblift_undo` assert `result.success` and fail the test with `result.error_message`. They do not translate dblift errors into a parallel exception hierarchy.

A PyPI version that already exists is a skipped publish of `pytest-dblift`, not a failed `dblift` release.

## CI

`.github/workflows/unit-tests.yml`: after the existing `pip install -e ".[dev,…]"` of dblift, `pip install -e packages/pytest-dblift`, then:

```bash
python -m pytest packages/pytest-dblift/tests \
  -n auto --dist=loadscope \
  -p no:benchmark --timeout=120
```

Same Python matrix as the unit job (3.11, 3.12). SQLite only. Plugin coverage is not required on the dblift Codecov upload.

`.github/workflows/publish-pypi.yml` keeps building `dblift` from the repo root into root `dist/`. Additionally:

1. `python -m build` in `packages/pytest-dblift/` into that directory's own `dist/` (not mixed into root `dist/`).
2. GET `https://pypi.org/pypi/pytest-dblift/<version>/json`.
3. HTTP 404 → publish that `dist/` with a second `pypa/gh-action-pypi-publish` step whose `packages-dir` is `packages/pytest-dblift/dist`.
4. HTTP 200 → skip `pytest-dblift`; still publish `dblift`.
5. Any other HTTP status (or a failed request) fails the job. Do not skip on network errors.

`workflow_dispatch` remains available. No second workflow, no `pytest-dblift-v*` tags.

Bump `packages/pytest-dblift/pyproject.toml` `version` only when the plugin changes.

## Docs (this repository)

- `packages/pytest-dblift/README.md` — consumer README: install, fixtures (`dblift_migrated_db`, `dblift_client`, `dblift_undo`, `dblift_validate`, `dblift_empty_db`), CLI options, overriding `dblift_config`. Document that SQLite needs no extra, and that any other engine requires `pip install "dblift[<extra>]"` so the driver is present; the plugin then uses that environment. No "Phase 4", no `pending_migrations`, no in-file `undo()` on `V*.py`.
- Root `README.md` — keep `pip install pytest-dblift` and the `pending_count` snippet. One sentence: it is a separate package, not `dblift[pytest]`.
- `docs/examples/sqlalchemy-integration.md` — the dedicated-package sentence stays; point at the plugin README; xdist claim limited to default SQLite.
- `docs/developer-guide/plugin-entry-points.md` — short note that `pytest-dblift` is a separate PyPI package (`pytest11`), not an extra of `dblift`.
- `CHANGELOG.md` `[Unreleased]` — `pytest-dblift` 0.1.0 is published to PyPI. Do not rewrite the 1.8.0 section.

## Tests

Package-local, SQLite only, under `packages/pytest-dblift/tests/`.

Keep:

- `tests/conftest.py` — session override of `dblift_config` pointing at `tests/migrations`.
- `tests/migrations/V1__init.sql` — smoke table.
- `test_fixtures_sqlite.py` — config → engine → client → migrated / empty / validate, plus `--dblift-url`.
- `test_xdist_isolation.py` — under xdist workers, default SQLite URL contains the worker id.

Replace `test_undo_smoke.py` with a `dblift_undo` test: versioned `V*` script plus companion `U*` script (not `def undo()` in the `V*.py`). Migrate, call `dblift_undo(target_version=...)`, assert success and reverted state.

Self-tests use the public client API (`migrate`, `info`, `clean`, `validate`, `undo`) and SQLAlchemy engine queries. They must not call unpublished private methods such as `_get_scripts_dir()`.

Strip internal task comments (`Task 4.x`, TDD RED notes) from package tests and plugin modules.

Do not add multi-dialect or testcontainers tests.

Add one small options test: after plugin load, `pytest --help` includes `--dblift-url` and `--dblift-migrations-dir`, and does not include `--dblift-no-migrate`. Fixture collection is otherwise the proof that `pytest11` works.

## Implementation notes

Add `packages/pytest-dblift/` with `pytest_dblift/{__init__,plugin,fixtures,_client}.py` implementing the surface above (the unpackaged fixture graph already written: session config/engine/client, function migrated/empty/validate, xdist SQLite paths). Then:

1. Complete `pyproject.toml` (`[build-system]`, description, license, readme, classifiers, URLs, `packages.find` limited to `pytest_dblift*`).
2. Drop `--dblift-no-migrate`.
3. Replace `dblift_undo_smoke` with `dblift_undo`.
4. Rewrite the package README and the docs listed above.
5. Wire unit and publish workflows.

`dblift>=3.9` is the dependency floor because that is the client API this repo tests against (`from_sqlalchemy`, `pending_count`, companion `U*` undo).
