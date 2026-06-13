# Python Migrations

Python (`.py`) migration scripts give you full Python for complex logic, data transformations, conditional DDL, or calls that cannot be expressed (or safely parameterized) in plain SQL.

A Python migration is a file named `V<ver>__<desc>.py` (or repeatable `R__...py`, or undo `U<ver>__...py`) containing:

```python
# migrations/V1__seed_and_transform.py
from api import MigrationContext  # recommended for type hints

def migrate(context: MigrationContext) -> None:
    """Apply the change."""
    context.log.info("Starting Python migration")
    if context.dry_run:
        context.log.info("[DRY-RUN] would make changes")
        return

    # Use execute for any SQL (auto-routes SELECT/WITH to query, others to statement)
    context.execute("CREATE TABLE IF NOT EXISTS items (id INTEGER PRIMARY KEY, name TEXT)")

    # Read data
    rows = context.execute("SELECT COUNT(*) as c FROM items")
    context.log.info(f"Current row count: {rows}")

    # Access rich context
    if context.schema:
        context.log.info(f"Target schema: {context.schema}")
    if context.placeholders:
        context.log.info(f"Placeholders available: {dict(context.placeholders)}")
    if context.engine is not None:
        context.log.info("SQLAlchemy engine is available (from_sqlalchemy path)")

def undo(context: MigrationContext) -> None:
    """Rollback the change (optional)."""
    if context.dry_run:
        return
    context.execute("DROP TABLE IF EXISTS items")
    context.log.info("Dropped items table")
```

The only requirement: a top-level `def migrate(context):` (and optionally `def undo(context):` for rollback support).

## End-to-End Runnable Example (SQLite + from_sqlalchemy)

This block is self-contained and copy-paste runnable (uses a temp file DB and temp migrations dir so it works anywhere).

```python
import tempfile
from pathlib import Path

from sqlalchemy import create_engine

from api import DBLiftClient, MigrationContext


def main():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        # Write a real Python migration file
        py_mig = migrations_dir / "V1__demo_python_migration.py"
        py_mig.write_text('''"""Demo Python migration using the full MigrationContext surface."""

from api import MigrationContext


def migrate(context: MigrationContext) -> None:
    context.log.info("Python migrate starting")
    context.log.info(f"schema={context.schema!r}")
    context.log.info(f"placeholders={dict(context.placeholders)}")
    context.log.info(f"has_engine={context.engine is not None}")
    context.log.info(f"has_connection={context.connection is not None}")
    context.log.info(f"dry_run={context.dry_run}")
    context.log.info(f"provider_type={type(context.provider).__name__}")

    if context.dry_run:
        context.log.info("[DRY-RUN] skipping writes")
        return

    # DDL + DML via the convenience execute (works for both query and statement forms)
    context.execute("""
        CREATE TABLE IF NOT EXISTS demo (
            id INTEGER PRIMARY KEY,
            label TEXT NOT NULL
        )
    """)

    # Insert (statement path)
    context.execute("INSERT INTO demo (label) VALUES (?)", params=["first"])
    context.execute("INSERT INTO demo (label) VALUES (:label)", params={"label": "second"})

    # Query (routes to execute_query)
    result = context.execute("SELECT label FROM demo ORDER BY id")
    labels = [r[0] if isinstance(r, (list, tuple)) else r["label"] for r in (result or [])]
    context.log.info(f"Inserted rows: {labels}")

    # DBAPI-compat shims also work (classic patterns)
    cur = context.cursor()
    cur.execute("SELECT COUNT(*) FROM demo")
    count = cur.fetchone() if hasattr(cur, "fetchone") else None
    # (In practice the provider returns rows directly; the shim lets old code parse.)
    context.log.info(f"Row count via cursor shim: {count}")

    context.log.info("Python migration complete")


def undo(context: MigrationContext) -> None:
    if context.dry_run:
        context.log.info("[DRY-RUN] would drop demo")
        return
    context.execute("DROP TABLE IF EXISTS demo")
    context.log.info("Undid demo table")
''')

        # Use a real file-backed SQLite so the DB survives client close/reopen if desired.
        # (":memory:" also works with from_sqlalchemy thanks to the SQLite attach path.)
        db_file = tmp_path / "app.db"
        engine = create_engine(f"sqlite:///{db_file}")

        # Primary integration point: hand your engine (or connection=) to DBLift.
        # The client does not own/dispose the engine.
        client = DBLiftClient.from_sqlalchemy(
            engine,
            migrations_dir=migrations_dir,
            # schema="public",  # if using a schema
            # You can also pass a pre-built config= or logger= here.
        )

        print("=== Before migrate ===")
        info_before = client.info()
        print(f"Pending: {getattr(info_before, 'pending_count', '?')}")

        print("=== Running migrate ===")
        migrate_result = client.migrate()
        print(f"Success: {migrate_result.success}")
        print(f"Applied: {len(getattr(migrate_result, 'migrations_applied', []))}")

        print("=== After migrate ===")
        info_after = client.info()
        print(f"Pending after: {getattr(info_after, 'pending_count', 0)}")

        # Undo example (the same .py file supplies the undo function)
        print("=== Running undo ===")
        undo_result = client.undo()
        print(f"Undo success: {undo_result.success}")

        # Re-migrate so the DB is left in the "current" state
        client.migrate()

        # Engine is still fully usable after client.close()
        client.close()
        with engine.connect() as conn:
            rows = conn.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table' AND name='demo'").fetchall()
            print(f"Engine still sees demo table after close: {bool(rows)}")

        print("Done. (Temporary files cleaned up.)")


if __name__ == "__main__":
    main()
```

Run it:

```bash
python -c '
# paste the whole block above, or save as demo_python_migs.py and run
python demo_python_migs.py
'
```

## Context Surface Reference (for .py migrations)

Inside `migrate(context)` / `undo(context)` you receive a `MigrationContext` with:

- `context.execute(sql, params=None)` — the primary way to run SQL. It inspects the statement and calls the right provider method (`execute_query` for SELECT/WITH/etc, `execute_statement` otherwise). Works on every supported dialect.
- `context.log` — the DBLift structured logger (`.info()`, `.debug()`, `.warning()`, `.error()`).
- `context.dry_run` (bool) — respect this; when True your script must not perform writes.
- `context.provider` — the live `BaseProvider` (or subclass). Use for advanced cases.
- `context.connection` — the active provider connection object (if exposed by the provider).
- `context.engine` — the SQLAlchemy `Engine` when you used `DBLiftClient.from_sqlalchemy(engine=...)` (None otherwise).
- `context.schema` — the target schema string from config (or None).
- `context.placeholders` — read-only `Mapping[str, str]` coming from your `dblift.yaml` / CLI `--placeholders` / config (see D5: **no automatic `${...}` substitution happens inside `execute()`** — substitute manually in your Python code if you need the values in generated SQL).
- `context.config` — the full resolved `DbliftConfig`.
- `context.database` / `context.client` — CosmosDB objects (always None for relational/SQLAlchemy providers).
- `context.cursor()`, `context.commit()`, `context.rollback()`, `context.close()` — no-op / self-returning shims so classic DBAPI-style code (`cur = conn.cursor(); cur.execute(...); cur.close()`) continues to work without changes.

Type it:

```python
from api import MigrationContext

def migrate(context: MigrationContext) -> None:
    ...
```

(The symbol is re-exported from the top-level `api` package so migration authors do not need to reach into `core`.)

## Placeholders in Python Migrations

Pass them at the client or migrate call site (they flow into the context):

```python
client = DBLiftClient.from_sqlalchemy(engine, migrations_dir=..., config=your_config_with_placeholders)
result = client.migrate(placeholders={"table_prefix": "app_", "env": "test"})
# inside the .py:
prefix = context.placeholders.get("table_prefix", "")
context.execute(f"CREATE TABLE {prefix}items (...)")  # manual use
```

`context.placeholders` is a plain mapping (no magic). The values are strings.

## Undo Support

- Implement `def undo(context):` in the **same** `.py` file as the corresponding `migrate`.
- `client.undo()` (or `U<ver>__*.py` files) will invoke it when rolling back that version.
- `supports_rollback` is detected by the presence of the `def undo(` string (simple but reliable).

See the runnable example above for a complete migrate + undo round-trip.

## Notes

- Python migrations are executed by `PythonMigrationExecutor` (registered alongside the SQL executor). The `ExecutionEngine` chooses the executor based on file extension (`.py` → Python).
- Validation (syntax + presence of `migrate(`) happens before execution.
- Keep side effects minimal; the ExecutionEngine owns the transaction boundary.
- For pure SQL prefer `.sql` files. Use `.py` when you need loops, conditionals on live data, external service calls, or complex Python libraries.
- The same `MigrationContext` is used for both `migrate` and `undo` of a given script.
- See `docs/examples/sqlalchemy-integration.md` for wiring `from_sqlalchemy` into app startup, pytest, scripts, and framework lifespans.
- All of the above is OSS and works with `pip install dblift[sqlite]` (or the matching extra for your DB).

These examples were validated against the current `MigrationContext` implementation (properties + shims + `from_sqlalchemy` engine hand-off) and the public `api` export.
