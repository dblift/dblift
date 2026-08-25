# pytest-dblift

pytest plugin for [DBLift](https://github.com/dblift/dblift). It applies your migrations in tests and exposes a `DBLiftClient`.

This is a **separate PyPI package**, not `dblift[pytest]`.

## Install

SQLite (default, stdlib driver):

```bash
pip install pytest-dblift
```

Any other engine: install the matching dblift extra so the native driver is present. The plugin does not install drivers and does not open a second connection — it calls `create_engine(url)` then `DBLiftClient.from_sqlalchemy`.

```bash
pip install pytest-dblift "dblift[postgresql]"
pytest --dblift-url "postgresql+psycopg://user:pass@localhost/app_test"
```

## Quickstart

```python
def test_schema(dblift_migrated_db, dblift_client):
    info = dblift_client.info()
    assert info.pending_migrations == []
```

`dblift_migrated_db` applies pending migrations (function scope). `dblift_client` is a session-scoped `DBLiftClient`. No fixture is autouse: request what you need.

## Fixtures

| Fixture | Scope | Role |
| --- | --- | --- |
| `dblift_config` | session | Dict with `url`, `migrations_dir`, optional `schema`. Override in `conftest.py`. |
| `dblift_engine` | session | SQLAlchemy engine from that URL. Override to inject your app engine. |
| `dblift_client` | session | `DBLiftClient.from_sqlalchemy(...)`. |
| `dblift_migrated_db` | function | `client.migrate()`, then yield the client. |
| `dblift_empty_db` | function | `client.clean(clean_enabled=True)`, then yield the client. |
| `dblift_validate` | function | Callable: `dblift_validate(**kwargs)` runs `client.validate` and asserts success. |
| `dblift_undo` | function | Callable: `dblift_undo(**kwargs)` runs `client.undo` and asserts success. Does not migrate. |

Undo uses companion `U*` scripts (same as dblift). There is no `undo()` function inside a `V*.py` file.

```python
def test_rollback(dblift_migrated_db, dblift_undo):
    result = dblift_undo(target_version="0")
    assert result.success
```

Override config in `tests/conftest.py`:

```python
import pytest

@pytest.fixture(scope="session")
def dblift_config():
    return {
        "url": "postgresql+psycopg://user:pass@localhost/app_test",
        "migrations_dir": "migrations",
    }
```

## CLI options

| Option | What it does |
| --- | --- |
| `--dblift-url` | Database URL when `dblift_config` is not overridden. Default: a temp SQLite **file**. |
| `--dblift-migrations-dir` | One migrations directory (not a comma-separated list). Default: `migrations`. |

pytest-xdist: only the default SQLite file is per-worker (`test_gw0.db`, …). A URL you pass with `--dblift-url` is used as-is.
