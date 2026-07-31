"""``repair`` must clear checksum drift for every versioned format.

The drift scan only considered applied rows recorded as ``SQL``. Versioned
Python scripts are recorded as ``PYTHON``, so an edited ``.py`` migration was
reported by ``validate`` and then silently skipped by ``repair``, which still
reported success while the stored checksum stayed stale.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from api import DBLiftClient

pytestmark = [pytest.mark.unit, pytest.mark.sqlite]

_ORIGINAL = {
    "sql": ("V1__a.sql", "CREATE TABLE a (id INTEGER PRIMARY KEY);"),
    "py": (
        "V1__a.py",
        'def migrate(context):\n    context.execute("CREATE TABLE a (id INTEGER PRIMARY KEY)")\n',
    ),
}

_EDIT = {
    "sql": "\n-- edited after apply\n",
    "py": "\n# edited after apply\n",
}


def _client(tmp_path: Path, migrations: Path) -> DBLiftClient:
    return DBLiftClient.from_sqlalchemy(
        create_engine(f"sqlite:///{tmp_path / 'app.db'}"), migrations_dir=str(migrations)
    )


def _stored_checksum(tmp_path: Path, script: str) -> str:
    with sqlite3.connect(tmp_path / "app.db") as conn:
        row = conn.execute(
            "SELECT checksum FROM dblift_schema_history WHERE script = ?", (script,)
        ).fetchone()
    return str(row[0])


@pytest.mark.parametrize("fmt", ["sql", "py"])
def test_repair_fixes_checksum_drift_for_every_versioned_format(tmp_path: Path, fmt: str) -> None:
    name, body = _ORIGINAL[fmt]
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    script = migrations / name
    script.write_text(body)

    assert _client(tmp_path, migrations).migrate().success
    applied_checksum = _stored_checksum(tmp_path, name)

    # Genuine content drift: the file changes, the stored checksum does not.
    script.write_text(body + _EDIT[fmt])
    assert _client(tmp_path, migrations).validate().success is False

    assert _client(tmp_path, migrations).repair().success is True
    assert _stored_checksum(tmp_path, name) != applied_checksum

    assert _client(tmp_path, migrations).validate().success is True
