<p align="center">
  <img src="https://raw.githubusercontent.com/dblift/dblift/main/logo/dblift_logo.png" width="240" alt="DBLift">
</p>

<h3 align="center">Plain SQL migrations for Python. See the exact SQL before it runs.</h3>

<p align="center">
  <a href="https://pypi.org/project/dblift/"><img src="https://img.shields.io/pypi/v/dblift" alt="PyPI"></a>
  <a href="https://pypi.org/project/dblift/"><img src="https://img.shields.io/pypi/dm/dblift" alt="Downloads"></a>
  <img src="https://img.shields.io/pypi/pyversions/dblift" alt="Python versions">
  <img src="https://img.shields.io/badge/license-Apache--2.0-blue" alt="Apache 2.0">
  <a href="https://djangopackages.org/packages/p/dblift/"><img src="https://img.shields.io/badge/PyPI-dblift-tags-8c3c26.svg" alt="Latest on Django Packages"></a>
  <a href="https://github.com/dblift/dblift/actions/workflows/unit-tests.yml"><img src="https://github.com/dblift/dblift/actions/workflows/unit-tests.yml/badge.svg" alt="Unit tests"></a>
  <a href="https://codecov.io/gh/dblift/dblift"><img src="https://codecov.io/gh/dblift/dblift/graph/badge.svg" alt="Coverage"></a>
</p>

<p align="center">
  <a href="https://docs.dblift.com/getting-started/"><b>Get started</b></a> ·
  <a href="https://docs.dblift.com/"><b>Documentation</b></a> ·
  <a href="https://docs.dblift.com/move-from-flyway/"><b>Coming from Flyway</b></a> ·
  <a href="https://docs.dblift.com/adopt-existing-database/"><b>Adopt an existing database</b></a>
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/dblift/dblift/main/logo/dblift-migrate-dry-run.gif" width="720" alt="dblift migrate --dry-run --show-sql previewing pending V1__create_users.sql and the exact CREATE TABLE SQL">
</p>

DBLift applies versioned `.sql` files to your database and remembers what ran. Same file convention as Flyway (`V1__create_users.sql`), installed with `pip`, usable as a CLI or as a Python library. Preview, undo, checksums and locking are part of the open-source package. Apache 2.0.

## Try it in 60 seconds

No database server needed — this runs against a local SQLite file.

```bash
pip install dblift

mkdir migrations
echo "CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT NOT NULL UNIQUE);" > migrations/V1__create_users.sql
echo "DROP TABLE users;" > migrations/U1__create_users.sql

export DBLIFT_DB_URL="sqlite:///app.db"

dblift migrate --dry-run --show-sql   # prints the SQL, applies nothing
dblift migrate                        # applies V1
dblift info                           # what ran, when, by whom, and whether it can be undone
dblift undo                           # runs U1, rolls the last migration back
```

For a real database, install the driver extra and point the URL at it:

```bash
pip install "dblift[postgresql]"
export DBLIFT_DB_URL="postgresql+psycopg://user@localhost:5432/mydb"
export DBLIFT_DB_PASSWORD="..."
```

[Your first migration →](https://docs.dblift.com/your-first-migration/) · [Configuration →](https://docs.dblift.com/configuration/)

## Is this for you?

**You run Flyway from a Python project.** A JVM, a Docker image or a downloaded tarball, kept patched only to apply SQL files. DBLift reads the same `V` / `R` / `U` file names, and `dblift import-flyway` copies your `flyway_schema_history` so every environment keeps its history. What changes is the install line. [Move from Flyway →](https://docs.dblift.com/move-from-flyway/)

**You apply SQL with a `migrate.sh` or a home-made `migrate.py`.** It works until two files share a number, someone edits an applied file, a replica starts at the same time, or production turns out to be two migrations behind staging. That script is a migration tool you maintain by accident. Rename the files, run `dblift baseline` once per existing database, and delete it. [Adopt an existing database →](https://docs.dblift.com/adopt-existing-database/) · [Naming conventions →](https://docs.dblift.com/naming-conventions/)

**You want migrations you can read in a pull request.** Not revisions generated from an ORM — the SQL you wrote, reviewed as SQL, run as written. Works next to SQLAlchemy, Django, FastAPI and Flask, or with none of them.

## What you get

Everything below ships in the open-source package.

| | |
| --- | --- |
| **Preview** | `migrate --dry-run --show-sql` prints every statement that would run. Same for `undo`. |
| **Undo** | Pair `V3__x.sql` with `U3__x.sql`; `dblift undo` rolls back one step or to a target version. [Undo model →](https://docs.dblift.com/undo-model/) |
| **Checksums** | `dblift validate` fails when an applied file was edited, a recorded file is missing, or two files claim the same version. |
| **Baseline** | Adopt a database that already exists: declare "this one is at version N" and carry on from there. |
| **Repeatable migrations** | `R__views.sql` re-runs when its content changes — a home for views, functions, grants and seed data. |
| **Locking** | A lock table serialises concurrent runs; a second runner waits, then skips what the first one applied. |
| **Python migrations** | `V4__backfill.py` when a change needs logic. [Python migrations →](https://docs.dblift.com/python-migrations/) |
| **A Python API** | Sync and async clients, events and callbacks — run migrations from your app or your tests, not only from a shell. |
| **Transactions** | A migration that fails part-way is rolled back where the engine supports transactional DDL. |
| **No lock-in** | Your migrations stay plain `.sql` files in your repository. |

> **Ordering:** DBLift applies out-of-order migrations by default — if `V3` is applied and a teammate's `V2` merges later, `V2` still runs. This is the opposite of Flyway's default. Use `--strict` or `strict_mode: true` to enforce version order. [Versioning →](https://docs.dblift.com/migrations-versioning/)

## Use it from Python

Run migrations when your app starts:

```python
from sqlalchemy import create_engine
from dblift.api import DBLiftClient

engine = create_engine("postgresql+psycopg://user:pass@localhost/app")
with DBLiftClient.from_sqlalchemy(engine, migrations_dir="migrations") as client:
    client.migrate()
```

`AsyncDBLiftClient` (`from dblift.api.async_client import AsyncDBLiftClient`) does the same without blocking an event loop. [API →](https://docs.dblift.com/api/) · [Async client →](https://docs.dblift.com/async-client/)

Give your tests a migrated database:

```bash
pip install pytest-dblift
```

```python
def test_schema_is_current(dblift_migrated_db, dblift_client):
    assert dblift_client.info().pending_count == 0
```

[pytest-dblift →](https://docs.dblift.com/pytest-dblift/)

Integrations: [Django](https://docs.dblift.com/django/) management commands and system check · [FastAPI](https://docs.dblift.com/fastapi/) · [Flask](https://docs.dblift.com/flask/) · [SQLAlchemy](https://docs.dblift.com/sqlalchemy/) · [OpenTelemetry](https://docs.dblift.com/opentelemetry/) spans · [CI/CD recipes](https://docs.dblift.com/ci-cd/) for GitHub Actions, GitLab CI and pre-commit · an [MCP server](https://docs.dblift.com/mcp/) for AI assistants.

## How it compares

| | DBLift | Flyway Community | Alembic | Your own script |
| --- | --- | --- | --- | --- |
| Migrations are plain `.sql` files | ✅ | ✅ | Python revision files | ✅ |
| Runs without a JVM | ✅ | ❌ | ✅ | ✅ |
| Undo | ✅ | paid editions | ✅ `downgrade()` in Python | if you wrote it |
| Preview the SQL before applying | ✅ | paid editions | ✅ offline `--sql` mode | if you wrote it |
| Detects edited or duplicated migrations | ✅ | ✅ | ❌ | rarely |
| Importable as a Python library | ✅ | ❌ | ✅ | — |
| pytest fixtures | ✅ | ❌ | third-party plugin | — |
| Adopts an existing Flyway history | ✅ | — | ❌ | ❌ |

Alembic is the right choice when your schema is driven by SQLAlchemy models and you want autogenerated revisions. DBLift is for teams who write the SQL themselves.

## Databases

20 engines. SQLite works with a bare `pip install dblift`; every other engine has its own install extra, e.g. `pip install "dblift[postgresql]"`.

PostgreSQL · MySQL · MariaDB · SQL Server · Oracle · DB2 · SQLite · DuckDB · CockroachDB · Redshift · Snowflake · Neon · Supabase · Aurora PostgreSQL · AlloyDB · YugabyteDB · TimescaleDB · Citus · Azure Cosmos DB · MongoDB

What each engine supports is in the [capability matrix](https://docs.dblift.com/capability-matrix/); connection details are under [Engines](https://docs.dblift.com/choosing-an-engine/).

## What Pro adds

The OSS tier covers the full migration lifecycle: apply, preview, validate state,
roll back, and import from Flyway. When review risk grows, the Pro tier adds:

| Feature | Command | What it does |
|---|---|---|
| Static SQL analysis | `dblift validate-sql` | Lints migration files with rule-based checks — catches issues before they reach the database. Built-in rule profiles (core, enterprise, strict). CI-friendly output formats (GitHub Actions, SARIF, GitLab). |
| Schema drift detection | `dblift diff` | Compares live database state with what your migrations define. Surfaces objects that have drifted. |
| Schema export | `dblift export-schema` | Exports the current schema to SQL migration files. Useful for brownfield onboarding. |

[See pricing and Pro features →](https://dblift.com/pricing)

## Documentation

Everything lives at **[docs.dblift.com](https://docs.dblift.com/)**.

| Start | Day to day | Reference |
| --- | --- | --- |
| [Getting started](https://docs.dblift.com/getting-started/) | [Commands](https://docs.dblift.com/commands/) | [Configuration reference](https://docs.dblift.com/configuration-reference/) |
| [Installation](https://docs.dblift.com/installation/) | [Environments](https://docs.dblift.com/environments/) | [Schema history table](https://docs.dblift.com/schema-history-table/) |
| [Move from Flyway](https://docs.dblift.com/move-from-flyway/) | [Best practices](https://docs.dblift.com/best-practices/) | [Exit codes](https://docs.dblift.com/exit-codes/) · [Error codes](https://docs.dblift.com/error-codes/) |
| [Adopt an existing database](https://docs.dblift.com/adopt-existing-database/) | [Zero-downtime changes](https://docs.dblift.com/zero-downtime/) | [Events and callbacks](https://docs.dblift.com/events-callbacks/) |
| [Naming conventions](https://docs.dblift.com/naming-conventions/) | [Recovery](https://docs.dblift.com/recovery/) · [Troubleshooting](https://docs.dblift.com/troubleshooting/) | [Python API](https://docs.dblift.com/api/) |

## Project

- **Released on PyPI** with trusted publishing — see the [changelog](CHANGELOG.md) and [releases](https://github.com/dblift/dblift/releases).
- **Questions, ideas, "would this work for us?"** Ask in [Discussions](https://github.com/dblift/dblift/discussions).
- **Found a bug?** [Open an issue](https://github.com/dblift/dblift/issues). Reports with a failing migration file attached get fixed fastest.
- **Want to contribute?** See [CONTRIBUTING.md](CONTRIBUTING.md).
- **Security:** see [SECURITY.md](SECURITY.md).
- **License:** [Apache 2.0](LICENSE).

If DBLift saved you a JVM or a `migrate.sh`, a ⭐ helps other teams find it.
