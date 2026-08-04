"""GH-831: undo --dry-run must fail on a missing undo script, not preview success.

Before this fix, UndoCommand.execute()'s dry-run branch only checked whether
the undo script existed when show_sql=True (inside the ``if show_sql:``
block). With show_sql=False (the default), dry-run skipped straight to
logging "DRY RUN: Would undo the following migrations" and returned a
successful result -- even though the real (non-dry-run) undo for the same
migration set fails immediately with "No undo script found for ...".

The fix makes the dry-run path check for the undo script's existence for
every migration to undo, regardless of show_sql, mirroring the real path.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from api import DBLiftClient

pytestmark = [pytest.mark.unit, pytest.mark.sqlite]


def _client(tmp_path: Path, migrations: Path) -> DBLiftClient:
    return DBLiftClient.from_sqlalchemy(
        create_engine(f"sqlite:///{tmp_path / 'app.db'}"), migrations_dir=str(migrations)
    )


def test_dry_run_without_undo_script_reports_same_failure_as_real_undo(tmp_path):
    """V1 has no U1__ script: dry-run must fail, not print a false 'would undo' preview."""
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "V1__create_a.sql").write_text("CREATE TABLE a (id INTEGER PRIMARY KEY);")
    # No U1__*.sql undo script.

    client = _client(tmp_path, migrations)
    assert client.migrate().success

    dry_run_result = client.undo(dry_run=True)
    assert not dry_run_result.success
    assert "No undo script found" in (dry_run_result.error_message or "")

    real_result = client.undo(dry_run=False)
    assert not real_result.success
    assert dry_run_result.error_message == real_result.error_message
    client.close()


def test_dry_run_with_undo_script_still_previews_successfully(tmp_path):
    """Regression guard: dry-run must still succeed when the undo script DOES exist."""
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "V1__create_a.sql").write_text("CREATE TABLE a (id INTEGER PRIMARY KEY);")
    (migrations / "U1__drop_a.sql").write_text("DROP TABLE a;")

    client = _client(tmp_path, migrations)
    assert client.migrate().success

    dry_run_result = client.undo(dry_run=True)
    assert dry_run_result.success, dry_run_result

    client.close()

    # dry-run must not have actually undone anything
    with sqlite3.connect(tmp_path / "app.db") as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='a'"
        ).fetchall()
    assert rows, "dry-run must not perform any writes"
