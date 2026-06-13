"""SQLite snapshot table create / legacy migration."""

import json

import pytest

from config import DbliftConfig
from core.logger import NullLog
from db.plugins.sqlite.provider import SQLiteProvider
from db.plugins.sqlite.sqlite.snapshot_table import _SNAPSHOT_COLS


@pytest.mark.unit
def test_sqlite_snapshot_legacy_schema_migrated(tmp_path):
    db_path = tmp_path / "snap.db"
    config_dict = {
        "database": {"type": "sqlite", "path": str(db_path)},
        "migrations": {"directory": str(tmp_path), "table": "dblift_schema_history"},
    }
    config = DbliftConfig.from_dict(config_dict)
    provider = SQLiteProvider(config, NullLog())

    try:
        provider.create_connection()
        conn = provider._get_connection()
        qe = provider.query_executor
        conn.executescript("""
            CREATE TABLE "dblift_schema_snapshots" (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_name TEXT,
                schema_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """)
        payload = {
            "tables": [],
            "views": [],
            "indexes": [],
            "sequences": [],
            "triggers": [],
            "events": [],
            "procedures": [],
            "functions": [],
            "packages": [],
            "synonyms": [],
            "user_defined_types": [],
            "extensions": [],
            "foreign_data_wrappers": [],
            "foreign_servers": [],
            "database_links": [],
            "metadata": {"dialect": "sqlite"},
        }
        conn.execute(
            "INSERT INTO dblift_schema_snapshots (snapshot_name, schema_json, created_at) "
            "VALUES (?, ?, ?)",
            ("snap-a", json.dumps(payload), "2024-01-15T10:00:00Z"),
        )
        conn.commit()

        provider.create_snapshot_table_if_not_exists("main", "dblift_schema_snapshots")

        pragma = qe.execute_query(conn, 'PRAGMA table_info("dblift_schema_snapshots")')
        col_names = {str(r["name"]).lower() for r in pragma}
        assert _SNAPSHOT_COLS.issubset(col_names)

        rows = qe.execute_query(
            conn,
            "SELECT snapshot_id, captured_at, checksum, model_data FROM dblift_schema_snapshots",
        )
        assert len(rows) == 1
        assert rows[0].get("snapshot_id") == "snap-a"
        assert rows[0].get("captured_at")
        assert rows[0].get("checksum")
        assert rows[0].get("model_data")
    finally:
        provider.close()


@pytest.mark.unit
def test_sqlite_snapshot_unknown_columns_recreated_empty(tmp_path):
    db_path = tmp_path / "snap2.db"
    config_dict = {
        "database": {"type": "sqlite", "path": str(db_path)},
        "migrations": {"directory": str(tmp_path), "table": "dblift_schema_history"},
    }
    config = DbliftConfig.from_dict(config_dict)
    provider = SQLiteProvider(config, NullLog())

    try:
        provider.create_connection()
        conn = provider._get_connection()
        qe = provider.query_executor
        conn.executescript("""
            CREATE TABLE "dblift_schema_snapshots" (foo TEXT, bar TEXT);
            INSERT INTO dblift_schema_snapshots VALUES ('x', 'y');
            """)
        conn.commit()

        provider.create_snapshot_table_if_not_exists("main", "dblift_schema_snapshots")

        pragma = qe.execute_query(conn, 'PRAGMA table_info("dblift_schema_snapshots")')
        col_names = {str(r["name"]).lower() for r in pragma}
        assert _SNAPSHOT_COLS.issubset(col_names)
        rows = qe.execute_query(conn, "SELECT COUNT(*) AS c FROM dblift_schema_snapshots")
        assert int(rows[0]["c"]) == 0
    finally:
        provider.close()
