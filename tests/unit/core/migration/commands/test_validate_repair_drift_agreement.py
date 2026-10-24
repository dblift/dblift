"""``repair`` fixes exactly the versioned checksum drift ``validate`` reports.

``validate`` and ``repair`` used to compare checksums separately. An unsigned
checksum from a driver was drift for ``repair`` but not for ``validate``, a
history row recorded under a directory-qualified script name was reported by
``validate`` but never matched by ``repair``, and ``repair`` compared failed
rows as well. Each scenario below runs the real client against SQLite and
requires the two commands to name the same scripts.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Callable, Dict, Set

import pytest
from sqlalchemy import create_engine

from dblift.api import DBLiftClient

pytestmark = [pytest.mark.unit, pytest.mark.sqlite]

_V1 = "CREATE TABLE a (id INTEGER PRIMARY KEY);"
_V1_PY = (
    "def migrate(context):\n" '    context.execute("CREATE TABLE a (id INTEGER PRIMARY KEY)")\n'
)
_V2 = "CREATE TABLE b (id INTEGER PRIMARY KEY);"
_MODIFIED = re.compile(r"Migration script (\S+) has been modified since it was applied")


def _client(tmp_path: Path, migrations: Path) -> DBLiftClient:
    return DBLiftClient.from_sqlalchemy(
        create_engine(f"sqlite:///{tmp_path / 'app.db'}"), migrations_dir=str(migrations)
    )


def _history(tmp_path: Path, sql: str, params: tuple = ()) -> None:
    with sqlite3.connect(tmp_path / "app.db") as conn:
        assert conn.execute(sql, params).rowcount == 1


def _validate_modified(tmp_path: Path, migrations: Path) -> Set[str]:
    result = _client(tmp_path, migrations).validate()
    return {m.group(1) for issue in result.issues if (m := _MODIFIED.search(issue))}


def _repair_drift(tmp_path: Path, migrations: Path) -> Set[str]:
    result = _client(tmp_path, migrations).repair(dry_run=True)
    return {info.script for info in result.aligned_migrations}


def _sql_edit(tmp_path: Path, migrations: Path) -> Set[str]:
    (migrations / "V1__a.sql").write_text(_V1 + "\n-- edited\n")
    return {"V1__a.sql"}


def _python_edit(tmp_path: Path, migrations: Path) -> Set[str]:
    (migrations / "V1__a.py").write_text(_V1_PY + "\n# edited\n")
    return {"V1__a.py"}


def _unsigned_checksum(tmp_path: Path, migrations: Path) -> Set[str]:
    _history(
        tmp_path,
        "UPDATE dblift_schema_history SET checksum = checksum + 4294967296 WHERE checksum < 0",
    )
    return set()


def _qualified_name_and_edit(tmp_path: Path, migrations: Path) -> Set[str]:
    _history(
        tmp_path,
        "UPDATE dblift_schema_history SET script = ? WHERE script = ?",
        ("extra/V1__a.sql", "V1__a.sql"),
    )
    (migrations / "V1__a.sql").write_text(_V1 + "\n-- edited\n")
    return {"extra/V1__a.sql"}


def _failed_v2_and_edited_v1(tmp_path: Path, migrations: Path) -> Set[str]:
    (migrations / "V2__b.sql").write_text("THIS IS NOT SQL;")
    assert _client(tmp_path, migrations).migrate().success is False
    # The failed script is then fixed on disk; only V1 has applied drift.
    (migrations / "V2__b.sql").write_text(_V2)
    (migrations / "V1__a.sql").write_text(_V1 + "\n-- edited\n")
    return {"V1__a.sql"}


def _undone_reapplied_then_edited(tmp_path: Path, migrations: Path) -> Set[str]:
    (migrations / "U1__a.sql").write_text("DROP TABLE a;")
    assert _client(tmp_path, migrations).undo().success
    assert _client(tmp_path, migrations).migrate().success
    (migrations / "V1__a.sql").write_text(_V1 + "\n-- edited\n")
    return {"V1__a.sql"}


_SCENARIOS: Dict[str, Callable[[Path, Path], Set[str]]] = {
    "sql_edit": _sql_edit,
    "python_edit": _python_edit,
    "unsigned_checksum": _unsigned_checksum,
    "qualified_name_and_edit": _qualified_name_and_edit,
    "failed_v2_and_edited_v1": _failed_v2_and_edited_v1,
    "undone_reapplied_then_edited": _undone_reapplied_then_edited,
}


@pytest.mark.parametrize("scenario", sorted(_SCENARIOS))
def test_validate_and_repair_agree_on_drift(tmp_path: Path, scenario: str) -> None:
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    if scenario == "python_edit":
        (migrations / "V1__a.py").write_text(_V1_PY)
    else:
        (migrations / "V1__a.sql").write_text(_V1)
    assert _client(tmp_path, migrations).migrate().success

    expected = _SCENARIOS[scenario](tmp_path, migrations)

    validate_modified = _validate_modified(tmp_path, migrations)
    repair_drift = _repair_drift(tmp_path, migrations)

    assert validate_modified == expected
    assert repair_drift == validate_modified

    assert _client(tmp_path, migrations).repair().success is True
    assert _validate_modified(tmp_path, migrations) == set()
    assert _client(tmp_path, migrations).validate().success is True
