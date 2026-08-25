# pytest-dblift PyPI Package Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `pip install pytest-dblift` install a real pytest plugin (separate 0.1.0 wheel) whose fixtures and CLI match `docs/superpowers/specs/2026-08-20-pytest-dblift-pypi-design.md`, and publish it from the existing PyPI workflow when that version is new.

**Architecture:** A second setuptools project lives at `packages/pytest-dblift/` and is not part of the `dblift` wheel. It registers `pytest11` entry point `dblift = pytest_dblift.plugin`. Fixtures call `sqlalchemy.create_engine(url)` then `DBLiftClient.from_sqlalchemy`. Drivers come from the consumer environment (`dblift[<extra>]`); this package depends on bare `dblift>=3.9`. Publish builds a separate `dist/` and skips PyPI upload if `pytest-dblift==<version>` already exists.

**Tech Stack:** Python 3.11+, pytest 7.3+ (`pytest11` plugin), SQLAlchemy 2, dblift public client, setuptools, GitHub Actions trusted publishing.

**Spec:** `docs/superpowers/specs/2026-08-20-pytest-dblift-pypi-design.md`

**Dev install (repo root, existing venv with dblift editable):**

```bash
pip install -e ".[dev]"
pip install -e packages/pytest-dblift
```

---

## File map

Create:

| Path | Responsibility |
| --- | --- |
| `packages/pytest-dblift/pyproject.toml` | Package metadata, `pytest11` entry, deps (`dblift>=3.9`, pytest, sqlalchemy). No engine extras. |
| `packages/pytest-dblift/README.md` | Consumer docs: install, extras, fixtures, CLI, `dblift_config` override. |
| `packages/pytest-dblift/pytest_dblift/__init__.py` | Version `0.1.0`. |
| `packages/pytest-dblift/pytest_dblift/plugin.py` | `pytest_addoption`, marker, `pytest_plugins`. No `--dblift-no-migrate`. |
| `packages/pytest-dblift/pytest_dblift/_client.py` | URL/config resolution, xdist worker SQLite paths, `from_sqlalchemy` wrapper. |
| `packages/pytest-dblift/pytest_dblift/fixtures.py` | Session `dblift_config`/`engine`/`client`; function `migrated_db`/`empty_db`/`validate`/`undo`. |
| `packages/pytest-dblift/tests/conftest.py` | Session override: `migrations_dir` → `tests/migrations`. |
| `packages/pytest-dblift/tests/migrations/V1__init.sql` | Smoke table. |
| `packages/pytest-dblift/tests/migrations/U1__init.sql` | Companion undo for that table. |
| `packages/pytest-dblift/tests/test_plugin_options.py` | `--help` includes url/migrations-dir, excludes `--dblift-no-migrate`. |
| `packages/pytest-dblift/tests/test_fixtures_sqlite.py` | Fixture graph + `--dblift-url` helper. Public API only. |
| `packages/pytest-dblift/tests/test_undo.py` | `dblift_undo` with `U*` script. |
| `packages/pytest-dblift/tests/test_xdist_isolation.py` | Default SQLite URL contains worker id under xdist. |

Modify:

| Path | Change |
| --- | --- |
| `.github/workflows/unit-tests.yml` | `pip install -e packages/pytest-dblift` and run plugin tests. |
| `.github/workflows/publish-pypi.yml` | Same test install; build plugin dist; PyPI 404/200/other; conditional publish. |
| `README.md` | One sentence: separate package, not `dblift[pytest]`. |
| `docs/examples/sqlalchemy-integration.md` | Point at plugin README; xdist = default SQLite only. |
| `docs/developer-guide/plugin-entry-points.md` | Short `pytest-dblift` note. |
| `CHANGELOG.md` | `[Unreleased]` Added: pytest-dblift 0.1.0 on PyPI. Do not edit 1.8.0. |

Do not touch root `[tool.setuptools.packages.find]` include list. Do not add website files.

---

### Task 1: Installable package and CLI options

**Files:**

- Create: `packages/pytest-dblift/tests/test_plugin_options.py`
- Create: `packages/pytest-dblift/pyproject.toml`
- Create: `packages/pytest-dblift/pytest_dblift/__init__.py`
- Create: `packages/pytest-dblift/pytest_dblift/plugin.py`
- Create: `packages/pytest-dblift/pytest_dblift/fixtures.py` (empty module so `pytest_plugins` can load)
- Create: `packages/pytest-dblift/README.md` (minimal, enough for `readme = "README.md"`; Task 7 rewrites it)

- [ ] **Step 1: Write the failing options test**

```python
# packages/pytest-dblift/tests/test_plugin_options.py
"""CLI options registered by the pytest-dblift plugin."""

from __future__ import annotations

import subprocess
import sys


def test_help_lists_dblift_url_and_migrations_dir() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    help_text = result.stdout
    assert "--dblift-url" in help_text
    assert "--dblift-migrations-dir" in help_text
    assert "--dblift-no-migrate" not in help_text
```

- [ ] **Step 2: Run test to verify it fails**

Run from repo root:

```bash
python -m pytest packages/pytest-dblift/tests/test_plugin_options.py -v
```

Expected: FAIL with `assert '--dblift-url' in help_text` (plugin not installed).

- [ ] **Step 3: Write minimal package + plugin**

`packages/pytest-dblift/pyproject.toml`:

```toml
[build-system]
requires = ["setuptools>=83.0.0", "wheel>=0.46.2"]
build-backend = "setuptools.build_meta"

[project]
name = "pytest-dblift"
version = "0.1.0"
description = "pytest plugin for DBLift migrations"
readme = "README.md"
requires-python = ">=3.11"
license = { text = "Apache-2.0" }
authors = [{ name = "DBLift" }]
dependencies = [
    "dblift>=3.9",
    "pytest>=7.3",
    "sqlalchemy>=2.0",
]
classifiers = [
    "Framework :: Pytest",
    "License :: OSI Approved :: Apache Software License",
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
]
urls = { Homepage = "https://github.com/dblift/dblift" }

[project.entry-points.pytest11]
dblift = "pytest_dblift.plugin"

[project.optional-dependencies]
dev = ["pytest-xdist>=3.3"]

[tool.setuptools.packages.find]
include = ["pytest_dblift*"]
```

`packages/pytest-dblift/README.md` (placeholder; Task 7 replaces this entire file):

```markdown
# pytest-dblift

pytest plugin for DBLift. See the full README in a later commit.
```

`packages/pytest-dblift/pytest_dblift/__init__.py`:

```python
"""pytest-dblift: pytest plugin for DBLift migrations."""

__version__ = "0.1.0"
```

`packages/pytest-dblift/pytest_dblift/plugin.py`:

```python
"""pytest11 entry: CLI options and fixture loading."""

from __future__ import annotations

import pytest

pytest_plugins = ["pytest_dblift.fixtures"]


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("dblift", "dblift pytest integration")
    group.addoption(
        "--dblift-url",
        action="store",
        default=None,
        help="Database URL for dblift (e.g. sqlite:////tmp/test.db or postgresql+psycopg://...). "
        "Used when no dblift_config fixture override is provided.",
    )
    group.addoption(
        "--dblift-migrations-dir",
        action="store",
        default="migrations",
        help="Path to the migrations directory. Defaults to migrations.",
    )


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "dblift: marks tests as using dblift fixtures (provided by pytest-dblift)",
    )
```

`packages/pytest-dblift/pytest_dblift/fixtures.py`:

```python
"""pytest-dblift fixtures. Populated in later tasks."""
```

Then install the plugin into the same venv:

```bash
pip install -e packages/pytest-dblift
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m pytest packages/pytest-dblift/tests/test_plugin_options.py -v
```

Expected: PASS (`1 passed`).

Confirm the wheel does not include tests:

```bash
python -m pip install --upgrade build
python -m build packages/pytest-dblift
unzip -l packages/pytest-dblift/dist/pytest_dblift-0.1.0-py3-none-any.whl
```

Expected: `pytest_dblift/` modules present; no `tests/` in the wheel.

- [ ] **Step 5: Commit**

```bash
git add packages/pytest-dblift/pyproject.toml \
  packages/pytest-dblift/README.md \
  packages/pytest-dblift/pytest_dblift/__init__.py \
  packages/pytest-dblift/pytest_dblift/plugin.py \
  packages/pytest-dblift/pytest_dblift/fixtures.py \
  packages/pytest-dblift/tests/test_plugin_options.py
git commit -m "feat: scaffold pytest-dblift package with pytest11 CLI options"
```

---

### Task 2: Config and xdist URL helpers

**Files:**

- Create: `packages/pytest-dblift/pytest_dblift/_client.py`
- Modify: `packages/pytest-dblift/tests/test_fixtures_sqlite.py` (create this file with helper tests only; Task 3 appends fixture tests)

- [ ] **Step 1: Write the failing helper tests**

Create `packages/pytest-dblift/tests/test_fixtures_sqlite.py`:

```python
"""SQLite tests for pytest-dblift helpers and fixtures."""

from __future__ import annotations

from typing import Any

import pytest


def test_resolve_dblift_config_reads_cli_url(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    from pytest_dblift._client import resolve_dblift_config

    class DummyConfig:
        rootdir = "/tmp"

        def getoption(self, name: str, default: Any = None) -> Any:
            if name == "--dblift-url":
                return "sqlite:////tmp/dblift_custom_test.db"
            if name == "--dblift-migrations-dir":
                return "migrations"
            return default

    cfg = resolve_dblift_config(DummyConfig(), tmp_path_factory=tmp_path_factory)
    assert "dblift_custom_test.db" in cfg["url"]
    assert "migrations" in cfg["migrations_dir"]


def test_worker_id_master_without_xdist(pytestconfig: pytest.Config) -> None:
    from pytest_dblift._client import _worker_id

    if getattr(pytestconfig, "workerinput", None):
        pytest.skip("this assertion is for a non-xdist controller process")
    assert _worker_id(pytestconfig) == "master"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest packages/pytest-dblift/tests/test_fixtures_sqlite.py::test_resolve_dblift_config_reads_cli_url -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'pytest_dblift._client'` (or `ImportError`).

- [ ] **Step 3: Implement `_client.py`**

```python
# packages/pytest-dblift/pytest_dblift/_client.py
"""URL resolution and DBLiftClient construction for pytest-dblift fixtures."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from api import DBLiftClient


def _worker_id(config: pytest.Config) -> str:
    """Return xdist worker id ('gw0', ...) or 'master' when not under xdist."""
    workerinput = getattr(config, "workerinput", None)
    if workerinput:
        return workerinput.get("workerid", "master")
    return "master"


def default_sqlite_file_url(
    tmp_path_factory: pytest.TempPathFactory, config: pytest.Config | None = None
) -> str:
    """Session-scoped temp SQLite file URL. Under xdist, suffix the filename with the worker id."""
    base = tmp_path_factory.mktemp("dblift_pytest", numbered=True)
    wid = _worker_id(config) if config is not None else "master"
    if wid != "master":
        db_path = base / f"test_{wid}.db"
    else:
        db_path = base / "test.db"
    return f"sqlite:///{db_path}"


def resolve_dblift_config(
    pytestconfig: pytest.Config,
    *,
    tmp_path_factory: pytest.TempPathFactory,
) -> dict[str, Any]:
    """Build config dict from CLI options + defaults.

    Returns dict with 'url' and 'migrations_dir' (absolute path str).
    A relative migrations dir is resolved against pytest rootdir.
    """
    url = pytestconfig.getoption("--dblift-url")
    if not url:
        url = default_sqlite_file_url(tmp_path_factory, pytestconfig)

    raw_mig = pytestconfig.getoption("--dblift-migrations-dir") or "migrations"
    rootdir = getattr(pytestconfig, "rootdir", None) or Path.cwd()
    rootdir = Path(rootdir)
    mig_path = Path(raw_mig)
    if not mig_path.is_absolute():
        mig_path = (rootdir / mig_path).resolve()

    return {
        "url": url,
        "migrations_dir": str(mig_path),
    }


def create_dblift_client(
    engine: Any,
    *,
    migrations_dir: str | Path | list[str | Path] | None,
    schema: str | None = None,
) -> DBLiftClient:
    return DBLiftClient.from_sqlalchemy(
        engine,
        migrations_dir=migrations_dir,
        schema=schema,
    )
```

- [ ] **Step 4: Run helper tests to verify they pass**

```bash
python -m pytest packages/pytest-dblift/tests/test_fixtures_sqlite.py::test_resolve_dblift_config_reads_cli_url packages/pytest-dblift/tests/test_fixtures_sqlite.py::test_worker_id_master_without_xdist -v
```

Expected: PASS (`2 passed`).

- [ ] **Step 5: Commit**

```bash
git add packages/pytest-dblift/pytest_dblift/_client.py \
  packages/pytest-dblift/tests/test_fixtures_sqlite.py
git commit -m "feat: resolve pytest-dblift config and xdist sqlite paths"
```

---

### Task 3: Session and function fixtures

**Files:**

- Create: `packages/pytest-dblift/tests/conftest.py`
- Create: `packages/pytest-dblift/tests/migrations/V1__init.sql`
- Modify: `packages/pytest-dblift/pytest_dblift/fixtures.py`
- Modify: `packages/pytest-dblift/tests/test_fixtures_sqlite.py` (append fixture tests)

- [ ] **Step 1: Write migrations, conftest override, and failing fixture tests**

`packages/pytest-dblift/tests/migrations/V1__init.sql`:

```sql
CREATE TABLE pytest_dblift_smoke (id INTEGER PRIMARY KEY, name TEXT NOT NULL);
```

`packages/pytest-dblift/tests/conftest.py`:

```python
"""Self-test configuration: point migrations_dir at tests/migrations."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from pytest_dblift._client import resolve_dblift_config


@pytest.fixture(scope="session")
def dblift_config(
    pytestconfig: pytest.Config, tmp_path_factory: pytest.TempPathFactory
) -> dict[str, Any]:
    cfg = dict(resolve_dblift_config(pytestconfig, tmp_path_factory=tmp_path_factory))
    cfg["migrations_dir"] = str((Path(__file__).parent / "migrations").resolve())
    return cfg
```

Append to `packages/pytest-dblift/tests/test_fixtures_sqlite.py` (keep the two helper tests already in the file):

```python
from sqlalchemy import text

from api import DBLiftClient


def test_dblift_config_defaults_to_sqlite_file(dblift_config: dict[str, Any]) -> None:
    assert "sqlite" in dblift_config["url"]
    assert ":memory:" not in dblift_config["url"]
    assert (Path(dblift_config["migrations_dir"]) / "V1__init.sql").is_file()


def test_dblift_engine_connects(dblift_engine: Any, dblift_config: dict[str, Any]) -> None:
    from sqlalchemy.engine import Engine

    assert isinstance(dblift_engine, Engine)
    with dblift_engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    rendered = dblift_engine.url.render_as_string(hide_password=False)
    assert rendered.startswith("sqlite")


def test_dblift_client_is_public_client(dblift_client: DBLiftClient) -> None:
    assert isinstance(dblift_client, DBLiftClient)
    info = dblift_client.info()
    assert hasattr(info, "pending_count")


def test_migrated_db_applies_migrations(
    dblift_migrated_db: DBLiftClient, dblift_engine: Any
) -> None:
    assert dblift_migrated_db.info().pending_count == 0
    with dblift_engine.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM pytest_dblift_smoke")).scalar()
        assert count == 0


def test_empty_db_cleans_schema(
    dblift_migrated_db: DBLiftClient, dblift_empty_db: DBLiftClient, dblift_engine: Any
) -> None:
    with dblift_engine.connect() as conn:
        try:
            conn.execute(text("SELECT COUNT(*) FROM pytest_dblift_smoke"))
            exists = True
        except Exception:
            exists = False
    assert not exists


def test_validate_callable_succeeds(
    dblift_migrated_db: DBLiftClient, dblift_validate: Any
) -> None:
    dblift_migrated_db.migrate()
    result = dblift_validate()
    assert result.success is True
    result2 = dblift_validate(target_version=None)
    assert result2.success is True


def test_dblift_validate_is_callable(dblift_validate: Any) -> None:
    assert callable(dblift_validate)
```

Add `from pathlib import Path` to the existing imports at the top of `test_fixtures_sqlite.py`.

- [ ] **Step 2: Run fixture tests to verify they fail**

```bash
python -m pytest packages/pytest-dblift/tests/test_fixtures_sqlite.py::test_dblift_engine_connects -v
```

Expected: FAIL with fixture `dblift_engine` not found.

- [ ] **Step 3: Implement fixtures**

Replace `packages/pytest-dblift/pytest_dblift/fixtures.py` with:

```python
"""pytest-dblift fixtures.

Session scope for config/engine/client. Function scope for migrate/clean/validate/undo.
No autouse: tests opt in by requesting a fixture.
"""

from __future__ import annotations

from typing import Any, Callable, Iterator

import pytest
from sqlalchemy import create_engine

from api import DBLiftClient

from ._client import create_dblift_client, resolve_dblift_config


@pytest.fixture(scope="session")
def dblift_config(
    pytestconfig: pytest.Config, tmp_path_factory: pytest.TempPathFactory
) -> dict[str, Any]:
    """Session config from CLI or temp SQLite. Overridable in consumer conftest.py."""
    return resolve_dblift_config(pytestconfig, tmp_path_factory=tmp_path_factory)


@pytest.fixture(scope="session")
def dblift_engine(dblift_config: dict[str, Any]) -> Iterator[Any]:
    engine = create_engine(dblift_config["url"])
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def dblift_client(dblift_engine: Any, dblift_config: dict[str, Any]) -> Iterator[DBLiftClient]:
    client = create_dblift_client(
        dblift_engine,
        migrations_dir=dblift_config.get("migrations_dir"),
        schema=dblift_config.get("schema"),
    )
    yield client
    client.close()


@pytest.fixture
def dblift_migrated_db(dblift_client: DBLiftClient) -> Iterator[DBLiftClient]:
    result = dblift_client.migrate()
    assert getattr(result, "success", False), (
        f"migrate failed: {getattr(result, 'error_message', result)}"
    )
    yield dblift_client


@pytest.fixture
def dblift_empty_db(dblift_client: DBLiftClient) -> Iterator[DBLiftClient]:
    result = dblift_client.clean(clean_enabled=True)
    assert getattr(result, "success", False), (
        f"clean failed: {getattr(result, 'error_message', result)}"
    )
    yield dblift_client


@pytest.fixture
def dblift_validate(dblift_client: DBLiftClient) -> Callable[..., Any]:
    def _run_validate(**kwargs: Any) -> Any:
        result = dblift_client.validate(**kwargs)
        assert getattr(result, "success", False), (
            f"validate failed: {getattr(result, 'error_message', result)}"
        )
        return result

    return _run_validate
```

Do **not** add `dblift_undo` yet (Task 4). Do **not** add `dblift_undo_smoke`.

- [ ] **Step 4: Run fixture tests to verify they pass**

```bash
python -m pytest packages/pytest-dblift/tests/test_fixtures_sqlite.py packages/pytest-dblift/tests/test_plugin_options.py -v
```

Expected: PASS. Do not call `_get_scripts_dir` or any other private client method.

- [ ] **Step 5: Commit**

```bash
git add packages/pytest-dblift/pytest_dblift/fixtures.py \
  packages/pytest-dblift/tests/conftest.py \
  packages/pytest-dblift/tests/migrations/V1__init.sql \
  packages/pytest-dblift/tests/test_fixtures_sqlite.py
git commit -m "feat: add pytest-dblift session and function fixtures"
```

---

### Task 4: `dblift_undo` callable and companion `U*` script

**Files:**

- Create: `packages/pytest-dblift/tests/migrations/U1__init.sql`
- Create: `packages/pytest-dblift/tests/test_undo.py`
- Modify: `packages/pytest-dblift/pytest_dblift/fixtures.py`

- [ ] **Step 1: Write the failing undo test and U1 script**

`packages/pytest-dblift/tests/migrations/U1__init.sql`:

```sql
DROP TABLE pytest_dblift_smoke;
```

`packages/pytest-dblift/tests/test_undo.py`:

```python
"""dblift_undo uses companion U* scripts, not an undo() function inside V*.py."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

from api import DBLiftClient


def test_dblift_undo_reverts_via_companion_script(
    dblift_migrated_db: DBLiftClient,
    dblift_undo: Any,
    dblift_engine: Any,
) -> None:
    with dblift_engine.connect() as conn:
        conn.execute(text("INSERT INTO pytest_dblift_smoke (name) VALUES ('before-undo')"))
        conn.commit()
        count = conn.execute(text("SELECT COUNT(*) FROM pytest_dblift_smoke")).scalar()
        assert count == 1

    result = dblift_undo(target_version="0")
    assert result.success is True

    with dblift_engine.connect() as conn:
        try:
            conn.execute(text("SELECT COUNT(*) FROM pytest_dblift_smoke"))
            exists = True
        except Exception:
            exists = False
    assert not exists


def test_dblift_undo_is_callable(dblift_undo: Any) -> None:
    assert callable(dblift_undo)
```

There must be no `def undo(` inside a `V*.py` in this package.

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest packages/pytest-dblift/tests/test_undo.py::test_dblift_undo_is_callable -v
```

Expected: FAIL with fixture `dblift_undo` not found.

- [ ] **Step 3: Add the fixture**

Append to `packages/pytest-dblift/pytest_dblift/fixtures.py`:

```python
@pytest.fixture
def dblift_undo(dblift_client: DBLiftClient) -> Callable[..., Any]:
    def _run_undo(**kwargs: Any) -> Any:
        result = dblift_client.undo(**kwargs)
        assert getattr(result, "success", False), (
            f"undo failed: {getattr(result, 'error_message', result)}"
        )
        return result

    return _run_undo
```

`dblift_undo` depends on `dblift_client` only (no auto-migrate).

- [ ] **Step 4: Run undo + fixture tests**

```bash
python -m pytest packages/pytest-dblift/tests/test_undo.py packages/pytest-dblift/tests/test_fixtures_sqlite.py -v
```

Expected: PASS. `test_migrated_db_applies_migrations` still works after undo tests because `dblift_migrated_db` calls `migrate()` again.

- [ ] **Step 5: Commit**

```bash
git add packages/pytest-dblift/pytest_dblift/fixtures.py \
  packages/pytest-dblift/tests/migrations/U1__init.sql \
  packages/pytest-dblift/tests/test_undo.py
git commit -m "feat: add dblift_undo fixture using companion U* scripts"
```

---

### Task 5: xdist worker isolation

**Files:**

- Create: `packages/pytest-dblift/tests/test_xdist_isolation.py`

- [ ] **Step 1: Write the isolation test**

```python
# packages/pytest-dblift/tests/test_xdist_isolation.py
"""Default SQLite URLs are per xdist worker."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import text

from pytest_dblift._client import _worker_id


def test_xdist_worker_isolation(
    pytestconfig: pytest.Config,
    dblift_config: dict[str, Any],
    dblift_migrated_db: Any,
    dblift_engine: Any,
) -> None:
    wid = _worker_id(pytestconfig)
    url = dblift_config["url"]

    if wid != "master":
        assert wid in url, (
            f"worker isolation missing: worker {wid!r} not in default url {url!r}"
        )

    assert "sqlite" in url and ":memory:" not in url
    tag = f"iso-{wid}"
    with dblift_engine.connect() as conn:
        conn.execute(text("INSERT INTO pytest_dblift_smoke (name) VALUES (:n)"), {"n": tag})
        conn.commit()
        cnt = conn.execute(
            text("SELECT COUNT(*) FROM pytest_dblift_smoke WHERE name = :n"), {"n": tag}
        ).scalar()
        assert cnt == 1
```

- [ ] **Step 2: Run under xdist to verify worker ids appear in URLs**

`_worker_id` and `default_sqlite_file_url` already suffix `test_{wid}.db`. This step should PASS if Task 2 is correct. Run it anyway:

```bash
python -m pytest packages/pytest-dblift/tests/test_xdist_isolation.py -n 2 --dist=loadscope -v
```

Expected: PASS (`1 passed`). pytest-xdist still runs the test once, on one worker (`gw0` or `gw1`); that worker's URL must contain the worker id. Do not expect the test to execute twice.

If it FAIL because `wid` is not in `url`, fix `default_sqlite_file_url` in `packages/pytest-dblift/pytest_dblift/_client.py` so non-master workers use `test_{wid}.db` (already specified in Task 2). Do not rewrite `--dblift-url` values.

- [ ] **Step 3: Run the full plugin suite as CI will**

```bash
python -m pytest packages/pytest-dblift/tests -n auto --dist=loadscope -p no:benchmark --timeout=120
```

Expected: PASS. Root `pytest.ini` `testpaths = tests` is ignored when the path argument is given.

- [ ] **Step 4: Commit**

```bash
git add packages/pytest-dblift/tests/test_xdist_isolation.py
git commit -m "test: isolate pytest-dblift default sqlite files per xdist worker"
```

---

### Task 6: Consumer README

**Files:**

- Modify: `packages/pytest-dblift/README.md` (replace the Task 1 placeholder)

- [ ] **Step 1: Write the consumer README**

Replace `packages/pytest-dblift/README.md` entirely with:

```markdown
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
    assert info.pending_count == 0
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
```

- [ ] **Step 2: Grep the package for discourse bugs**

```bash
rg -n "Phase 4|pending_migrations|dblift_undo_smoke|dblift-no-migrate|def undo\(|comma-separated" packages/pytest-dblift
```

Expected: no matches in `pytest_dblift/` or `README.md`. `tests/` may mention `dblift-no-migrate` only as the string that must be absent from `--help`.

- [ ] **Step 3: Commit**

```bash
git add packages/pytest-dblift/README.md
git commit -m "docs: consumer README for pytest-dblift"
```

---

### Task 7: Align repository docs

**Files:**

- Modify: `README.md` (the `pytest-dblift` quickstart block around lines 69–83)
- Modify: `docs/examples/sqlalchemy-integration.md` (paragraph after the in-test example)
- Modify: `docs/developer-guide/plugin-entry-points.md` (after Install Extras)
- Modify: `CHANGELOG.md` (`## [Unreleased]` / `### Added`)

- [ ] **Step 1: Root README — one sentence, keep the snippet**

In `README.md`, inside the `<!-- BEGIN: OSS README sync: python-install -->` block, replace the pytest-dblift quickstart with:

```markdown
`pytest-dblift` quickstart (separate package, not `dblift[pytest]`):

```bash
pip install pytest-dblift
```

SQLite works with a bare `dblift`. Other engines need `pip install "dblift[<extra>]"` so the driver is already installed; then pass `--dblift-url` or override `dblift_config`.

```python
# tests/test_foo.py
import pytest

def test_something(dblift_migrated_db, dblift_client):
    # dblift_migrated_db ensures migrations applied (function scope by default)
    result = dblift_client.info()
    assert result.pending_count == 0
```
```

Keep `pending_count`. Keep the `BEGIN`/`END` sync markers.

- [ ] **Step 2: SQLAlchemy example**

In `docs/examples/sqlalchemy-integration.md`, replace the sentence after the in-test code block:

```markdown
(The dedicated [`pytest-dblift`](../../packages/pytest-dblift/README.md) package provides reusable fixtures that do the above. pytest-xdist isolation applies to the default SQLite file only.)
```

- [ ] **Step 3: Plugin entry-points note**

In `docs/developer-guide/plugin-entry-points.md`, insert after the Install Extras section (before `## Provider Packages`):

```markdown
## pytest-dblift

`pytest-dblift` is a separate PyPI package (`pip install pytest-dblift`), not a `dblift` extra. It registers a `pytest11` plugin. A bare `dblift` is enough for SQLite; other engines need the matching extra so the native driver is installed. See [`packages/pytest-dblift/README.md`](../../packages/pytest-dblift/README.md).
```

- [ ] **Step 4: CHANGELOG `[Unreleased]`**

Under `## [Unreleased]` → `### Added`, add this bullet as the first item (do not edit the 1.8.0 section):

```markdown
- **`pytest-dblift` 0.1.0 on PyPI.** Separate package (`pip install pytest-dblift`)
  with a `pytest11` plugin, fixtures (`dblift_migrated_db`, `dblift_empty_db`,
  `dblift_validate`, `dblift_undo`, session `dblift_client` / `dblift_engine` /
  `dblift_config`), and per-worker default SQLite files under xdist. It depends
  on bare `dblift`; non-SQLite engines still need `dblift[<extra>]` for the
  driver.
```

- [ ] **Step 5: Commit**

```bash
git add README.md \
  docs/examples/sqlalchemy-integration.md \
  docs/developer-guide/plugin-entry-points.md \
  CHANGELOG.md
git commit -m "docs: align pytest-dblift install and fixture surface"
```

---

### Task 8: Unit-test CI

**Files:**

- Modify: `.github/workflows/unit-tests.yml`

- [ ] **Step 1: Add plugin install + test steps after the existing unit pytest, before Codecov**

After the `Run unit tests` step, insert:

```yaml
      - name: Install pytest-dblift
        run: python -m pip install -e packages/pytest-dblift

      - name: Run pytest-dblift tests
        run: |
          python -m pytest packages/pytest-dblift/tests \
            -n auto \
            --dist=loadscope \
            -p no:benchmark \
            --timeout=120
```

Do not add plugin coverage to the Codecov `--cov=` flags.

- [ ] **Step 2: Sanity-check YAML indentation locally**

```bash
python -c "import yaml,pathlib; yaml.safe_load(pathlib.Path('.github/workflows/unit-tests.yml').read_text())"
```

Expected: no exception. If PyYAML is missing: `python -m pip install pyyaml` then re-run.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/unit-tests.yml
git commit -m "ci: run pytest-dblift tests on unit-test workflow"
```

---

### Task 9: Publish workflow (second wheel, skip if version exists)

**Files:**

- Modify: `.github/workflows/publish-pypi.yml`

- [ ] **Step 1: Extend the test job so a release cannot publish a broken plugin**

In the `test` job, after `Run unit tests`, add the same two steps as Task 8 (`Install pytest-dblift` and `Run pytest-dblift tests`). Keep the existing `pip install -e ".[dev,…]"` line.

- [ ] **Step 2: Build plugin dist separately and publish only on PyPI 404**

Replace the `publish` job `steps` after `setup-python` with:

```yaml
      - name: Build dblift distributions
        run: |
          python -m pip install --upgrade pip build
          python -m build

      - name: Publish dblift
        uses: pypa/gh-action-pypi-publish@release/v1

      - name: Build pytest-dblift distributions
        run: python -m build packages/pytest-dblift

      - name: Check whether pytest-dblift version is on PyPI
        id: pytest_dblift_pypi
        run: |
          VERSION=$(python -c "import tomllib; print(tomllib.load(open('packages/pytest-dblift/pyproject.toml','rb'))['project']['version'])")
          echo "version=${VERSION}" >> "$GITHUB_OUTPUT"
          set +e
          CODE=$(curl -sS -o /tmp/pypi-pytest-dblift.json -w "%{http_code}" \
            "https://pypi.org/pypi/pytest-dblift/${VERSION}/json")
          CURL_STATUS=$?
          set -e
          if [ "$CURL_STATUS" -ne 0 ]; then
            echo "PyPI lookup failed (curl exit ${CURL_STATUS})"
            exit 1
          fi
          echo "PyPI HTTP ${CODE} for pytest-dblift==${VERSION}"
          if [ "$CODE" = "200" ]; then
            echo "publish=false" >> "$GITHUB_OUTPUT"
          elif [ "$CODE" = "404" ]; then
            echo "publish=true" >> "$GITHUB_OUTPUT"
          else
            echo "Unexpected PyPI status ${CODE}"
            cat /tmp/pypi-pytest-dblift.json || true
            exit 1
          fi

      - name: Publish pytest-dblift
        if: steps.pytest_dblift_pypi.outputs.publish == 'true'
        uses: pypa/gh-action-pypi-publish@release/v1
        with:
          packages-dir: packages/pytest-dblift/dist
```

`python -m build packages/pytest-dblift` must write into `packages/pytest-dblift/dist/`, not root `dist/`. Confirm locally:

```bash
python -m build packages/pytest-dblift
ls packages/pytest-dblift/dist
ls dist
```

Expected: plugin wheel/sdist only under `packages/pytest-dblift/dist/`. Root `dist/` still only has `dblift` artifacts from `python -m build` at repo root.

HTTP 200 → skip plugin publish, dblift still publishes. HTTP 404 → publish plugin. Any other code or curl failure → job fails.

- [ ] **Step 3: Validate YAML**

```bash
python -c "import yaml,pathlib; yaml.safe_load(pathlib.Path('.github/workflows/publish-pypi.yml').read_text())"
```

Expected: no exception.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/publish-pypi.yml
git commit -m "ci: publish pytest-dblift wheel when its version is new"
```

---

### Task 10: Final verification

**Files:** none new.

- [ ] **Step 1: Full plugin suite**

```bash
pip install -e ".[dev]"
pip install -e packages/pytest-dblift
python -m pytest packages/pytest-dblift/tests -n auto --dist=loadscope -p no:benchmark --timeout=120
```

Expected: PASS.

- [ ] **Step 2: Discourse grep**

```bash
rg -n "dblift_undo_smoke|--dblift-no-migrate|pending_migrations" packages/pytest-dblift README.md docs/examples/sqlalchemy-integration.md docs/developer-guide/plugin-entry-points.md
```

Expected: the only hit is `tests/test_plugin_options.py` asserting `--dblift-no-migrate` is absent. No `dblift_undo_smoke`. Root README still uses `pending_count`.

- [ ] **Step 3: Wheel contents**

```bash
python -m build packages/pytest-dblift
python -c "import zipfile,glob; z=zipfile.ZipFile(glob.glob('packages/pytest-dblift/dist/*.whl')[0]); names=z.namelist(); assert any(n.startswith('pytest_dblift/') for n in names); assert not any(n.startswith('tests/') for n in names); print('\n'.join(names))"
```

Expected: plugin package files only; assertion holds.

---

## Self-review (spec coverage)

| Spec requirement | Task |
| --- | --- |
| `packages/pytest-dblift/` not in dblift wheel | Task 1 `packages.find` include `pytest_dblift*` only; root find unchanged |
| PyPI name/version 0.1.0, pytest11, Apache-2.0, `dblift>=3.9`, no engine extras | Task 1 `pyproject.toml` |
| `--dblift-url`, `--dblift-migrations-dir`, no `--dblift-no-migrate`, no comma-separated | Tasks 1, 6 |
| Fixtures table including `dblift_undo` callable, no `undo_smoke`, no autouse | Tasks 3–4 |
| Companion `U*` undo, not `def undo()` in `V*.py` | Task 4 |
| xdist only default SQLite | Tasks 2, 5 |
| Driver extra contract | Tasks 1 deps, 6 README, 7 root README |
| Fail via `result.success` / `error_message` | Task 3–4 fixtures |
| unit-tests.yml plugin job | Task 8 |
| publish skip 200 / publish 404 / fail other | Task 9 |
| Docs: package README, root README, sqlalchemy, entry-points, CHANGELOG Unreleased | Tasks 6–7 |
| No website, no 1.8.0 rewrite, no testcontainers | omitted by design |
| Public API only in self-tests | Task 3 (no `_get_scripts_dir`) |
