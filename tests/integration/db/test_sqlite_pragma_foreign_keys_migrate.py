"""``PRAGMA foreign_keys`` inside a real ``migrate()`` run.

SQLite refuses to change foreign-key enforcement while a transaction is open
(pragma.html#pragma_foreign_keys: "This pragma is a no-op within a
transaction"). ``dblift migrate`` wraps a migration script's statements in a
transaction whenever every statement can run there, so a migration whose only
statement is ``PRAGMA foreign_keys = OFF`` used to be classified as an
ordinary transactional statement, wrapped in ``BEGIN``/``COMMIT``, and the
pragma silently did nothing.

``SqliteQuirks.non_transactional_sql_patterns`` now flags the statement, so
the migration executor's ``TransactionPolicy`` (execution_engine.py /
transaction_policy.py) runs it in autocommit mode instead -- the same
mechanism already used for e.g. PostgreSQL's ``CREATE INDEX CONCURRENTLY``.
This test drives that through a real SQLite file via ``DBLiftClient``, not a
mock, and checks the migration completes and is recorded rather than being
rejected as a "mixes transactional and autocommit-only statements" migration
(which is what happens if a *single* migration file mixes a non-transactional
statement with transactional ones -- so each concern here gets its own
migration file, matching how a real project would author it).
"""

from __future__ import annotations

import sqlite3


def _migrate(tmp_path, migrations):
    from dblift.api.client import DBLiftClient
    from dblift.config import DbliftConfig

    db_path = tmp_path / "app.db"
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    for name, sql in migrations:
        (migrations_dir / name).write_text(sql)

    config = DbliftConfig.from_dict(
        {"database": {"type": "sqlite", "path": str(db_path), "schema": "main"}}
    )
    client = DBLiftClient.from_config(config, migrations_dir=str(migrations_dir))
    return client.migrate(), db_path


def test_a_pragma_only_migration_runs_in_autocommit_mode_and_succeeds(tmp_path):
    result, db_path = _migrate(
        tmp_path,
        [
            ("V1_0_1__create_tables.sql", "CREATE TABLE parent (id INTEGER PRIMARY KEY);\n"),
            ("V1_0_2__disable_fk.sql", "PRAGMA foreign_keys = OFF;\n"),
        ],
    )

    assert result.success, getattr(result, "error", result)
    conn = sqlite3.connect(str(db_path))
    try:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(dblift_schema_history)")}
        script_column = "script" if "script" in columns else "script_name"
        history = conn.execute(f"SELECT {script_column} FROM dblift_schema_history").fetchall()
    finally:
        conn.close()
    applied = {row[0] for row in history}
    assert "V1_0_1__create_tables.sql" in applied
    assert "V1_0_2__disable_fk.sql" in applied


def test_pragma_foreign_keys_on_migration_also_runs_standalone(tmp_path):
    result, db_path = _migrate(
        tmp_path,
        [
            (
                "V1_0_1__create_tables.sql",
                "CREATE TABLE parent (id INTEGER PRIMARY KEY);\n"
                "CREATE TABLE child (\n"
                "  id INTEGER PRIMARY KEY,\n"
                "  parent_id INTEGER REFERENCES parent(id)\n"
                ");\n",
            ),
            ("V1_0_2__enable_fk.sql", "PRAGMA foreign_keys = ON;\n"),
        ],
    )

    assert result.success, getattr(result, "error", result)
    conn = sqlite3.connect(str(db_path))
    try:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
    finally:
        conn.close()
    assert {"parent", "child"} <= tables


def test_a_migration_mixing_pragma_foreign_keys_with_ddl_is_rejected_not_silently_wrong(tmp_path):
    """One file mixing the two is refused rather than silently mis-executed.

    This documents existing ``TransactionPolicy`` behavior (the same as e.g.
    PostgreSQL ``CREATE INDEX CONCURRENTLY`` mixed with a plain ``CREATE
    TABLE``): once ``PRAGMA foreign_keys`` is classified non-transactional, a
    single migration file combining it with an ordinary transactional
    statement hits ``unsupported_mixed_mode`` and fails loudly, rather than
    running the pragma in a transaction where it would silently no-op.
    """
    result, _ = _migrate(
        tmp_path,
        [
            (
                "V1_0_1__mixed.sql",
                "PRAGMA foreign_keys = OFF;\nCREATE TABLE parent (id INTEGER PRIMARY KEY);\n",
            ),
        ],
    )

    assert not result.success
    assert "mixes transactional and autocommit-only statements" in (result.error or "")
