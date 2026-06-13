"""Create and migrate SQLite ``dblift_schema_snapshots`` table."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set

from core.logger import Log, NullLog
from core.migration.snapshots.schema_snapshot import (
    SchemaSnapshotPayload,
    _isoformat,
    _parse_iso,
    _to_utc,
    compute_payload_checksum,
    decode_payload,
    encode_payload,
)

if TYPE_CHECKING:
    from db.plugins.sqlite.sqlite.query_executor import SQLiteQueryExecutor

_SNAPSHOT_COLS = frozenset({"snapshot_id", "captured_at", "checksum", "model_data"})


def _snapshot_column_names(
    query_executor: "SQLiteQueryExecutor", connection: sqlite3.Connection, table_lower: str
) -> Set[str]:
    rows = query_executor.execute_query(connection, f'PRAGMA table_info("{table_lower}")')
    names: Set[str] = set()
    for r in rows:
        name = r.get("name")
        if name is not None:
            names.add(str(name).lower())
    return names


def _is_legacy_snapshot_schema(cols: Set[str]) -> bool:
    if _SNAPSHOT_COLS.issubset(cols):
        return False
    if "schema_json" in cols:
        return True
    if "model_data" in cols:
        return False
    return bool(cols & {"snapshot_name", "created_at"}) or bool(
        "id" in cols and "created_at" in cols
    )


def _normalize_row(row: Dict[str, Any]) -> Dict[str, Any]:
    return {str(k).lower(): v for k, v in row.items() if isinstance(k, str)}


def _coerce_model_and_checksum(schema_json_val: Any) -> tuple[str, str]:
    if schema_json_val is None:
        payload = SchemaSnapshotPayload()
        return encode_payload(payload), compute_payload_checksum(payload)
    if isinstance(schema_json_val, bytes):
        schema_json_val = schema_json_val.decode("utf-8")
    s = str(schema_json_val).strip()
    try:
        data = json.loads(s)
        if isinstance(data, dict):
            payload = SchemaSnapshotPayload.from_dict(data)
            return encode_payload(payload), compute_payload_checksum(payload)
    except json.JSONDecodeError:
        pass
    except Exception:
        pass
    payload = decode_payload(s)
    return encode_payload(payload), compute_payload_checksum(payload)


def _coerce_captured_at(value: Any) -> str:
    if value is None:
        return _isoformat(datetime.now(timezone.utc))
    if isinstance(value, datetime):
        return _isoformat(_to_utc(value))
    if isinstance(value, str) and value:
        return _isoformat(_to_utc(_parse_iso(value)))
    return _isoformat(datetime.now(timezone.utc))


def _legacy_row_to_insert_values(row: Dict[str, Any]) -> List[Any]:
    r = _normalize_row(row)
    # Prefer snapshot_name over numeric id for legacy SQL layouts
    sid = r.get("snapshot_id") or r.get("snapshot_name") or r.get("id")
    if sid is None:
        sid = str(uuid.uuid4())
    sid = str(sid)
    cap = _coerce_captured_at(r.get("captured_at") or r.get("created_at"))
    model_data, checksum = _coerce_model_and_checksum(r.get("schema_json"))
    return [sid, cap, checksum, model_data]


def _create_snapshot_table_sql(table_lower: str) -> str:
    return f"""
        CREATE TABLE IF NOT EXISTS "{table_lower}" (
            snapshot_id TEXT PRIMARY KEY,
            captured_at TEXT NOT NULL,
            checksum TEXT NOT NULL,
            model_data TEXT NOT NULL
        )
        """


def _create_snapshot_table(
    query_executor: "SQLiteQueryExecutor", connection: sqlite3.Connection, table_lower: str
) -> None:
    query_executor.execute_statement(connection, _create_snapshot_table_sql(table_lower))


def _migrate_legacy_snapshot_table(
    query_executor: "SQLiteQueryExecutor",
    connection: sqlite3.Connection,
    table_lower: str,
    log: Log,
) -> None:
    backup = f"{table_lower}_dblift_legacy"
    legacy_rows = query_executor.execute_query(connection, f'SELECT * FROM "{table_lower}"')
    query_executor.execute_statement(connection, f'DROP TABLE IF EXISTS "{backup}"')
    query_executor.execute_statement(
        connection, f'ALTER TABLE "{table_lower}" RENAME TO "{backup}"'
    )
    try:
        _create_snapshot_table(query_executor, connection, table_lower)
        inserted = 0
        for row in legacy_rows:
            try:
                vals = _legacy_row_to_insert_values(row)
                query_executor.execute_statement(
                    connection,
                    f'INSERT INTO "{table_lower}" '
                    f"(snapshot_id, captured_at, checksum, model_data) VALUES (?,?,?,?)",
                    vals,
                )
                inserted += 1
            except Exception as e:
                log.warning(f"Skipping legacy snapshot row during migration: {e}")
        log.info(
            f"Migrated legacy SQLite snapshot table {table_lower} "
            f"({inserted} of {len(legacy_rows)} row(s))."
        )
        query_executor.execute_statement(connection, f'DROP TABLE "{backup}"')
    except Exception:
        try:
            query_executor.execute_statement(connection, f'DROP TABLE IF EXISTS "{table_lower}"')
        except Exception:
            pass
        try:
            query_executor.execute_statement(
                connection, f'ALTER TABLE "{backup}" RENAME TO "{table_lower}"'
            )
        except Exception:
            log.error(
                f"Snapshot table migration failed and could not restore table {table_lower} "
                f"from backup {backup}."
            )
        raise


def _recreate_snapshot_table(
    query_executor: "SQLiteQueryExecutor",
    connection: sqlite3.Connection,
    table_lower: str,
    log: Log,
) -> None:
    log.warning(
        f"Snapshot table {table_lower} exists with unexpected columns; recreating empty table."
    )
    query_executor.execute_statement(connection, f'DROP TABLE "{table_lower}"')
    _create_snapshot_table(query_executor, connection, table_lower)


def ensure_sqlite_snapshot_table_exists(
    query_executor: "SQLiteQueryExecutor",
    connection: sqlite3.Connection,
    schema: str,
    table_name: str,
    log: Optional[Log] = None,
) -> None:
    """Ensure the snapshot table exists and matches the current column layout.

    Migrates legacy layouts (e.g. ``schema_json`` / ``created_at``) in place when detected.
    """
    _ = schema  # SQLite has no separate schema namespace for these tables
    lg = log if log is not None else NullLog()
    tl = table_name.lower()

    if not query_executor.table_exists(connection, schema, tl):
        _create_snapshot_table(query_executor, connection, tl)
        lg.debug(f"Created snapshot table: {table_name}")
        return

    cols = _snapshot_column_names(query_executor, connection, tl)
    if _SNAPSHOT_COLS.issubset(cols):
        lg.debug(f"Snapshot table {table_name} already exists with current schema")
        return

    if _is_legacy_snapshot_schema(cols):
        lg.info(f"Upgrading legacy SQLite snapshot table {tl} to current schema.")
        _migrate_legacy_snapshot_table(query_executor, connection, tl, lg)
        return

    _recreate_snapshot_table(query_executor, connection, tl, lg)
    lg.debug(f"Recreated snapshot table: {table_name}")
