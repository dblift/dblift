"""``import-flyway`` must preserve Flyway's own ``installed_on`` dates.

The command copies ``installed_by`` verbatim but used to let the target
table's ``CURRENT_TIMESTAMP`` default stamp ``installed_on``, so every
imported row claimed the person named in ``installed_by`` had applied the
migration at import time. A history that reports a real name against a
fabricated date is worse than one with no date at all: it is the record
teams reach for during an incident.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine, text

from dblift.api import DBLiftClient

pytestmark = [pytest.mark.unit, pytest.mark.sqlite]

_SCRIPT_CONTENT = "CREATE TABLE t (id INTEGER PRIMARY KEY);\n"

#: What the source Flyway row says: applied in 2023, by a real person.
_FLYWAY_INSTALLED_ON = "2023-04-15 09:12:00"
_FLYWAY_INSTALLED_BY = "alice"


def _seed_flyway_history(engine: Any) -> None:
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE t (id INTEGER PRIMARY KEY)"))
        conn.execute(text("""
                CREATE TABLE flyway_schema_history (
                    installed_rank INTEGER PRIMARY KEY,
                    version TEXT,
                    description TEXT,
                    type TEXT,
                    script TEXT,
                    checksum INTEGER,
                    installed_by TEXT,
                    installed_on TEXT,
                    execution_time INTEGER,
                    success INTEGER
                )
                """))
        conn.execute(
            text("""
                INSERT INTO flyway_schema_history
                (installed_rank, version, description, type, script, checksum,
                 installed_by, installed_on, execution_time, success)
                VALUES (1, '1', 'a', 'SQL', 'V1__a.sql', 12345,
                        :installed_by, :installed_on, 7, 1)
                """),
            {"installed_by": _FLYWAY_INSTALLED_BY, "installed_on": _FLYWAY_INSTALLED_ON},
        )


def _make_client(tmp_path: Path) -> DBLiftClient:
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    (migrations_dir / "V1__a.sql").write_text(_SCRIPT_CONTENT)

    engine = create_engine(f"sqlite:///{tmp_path / 'db.sqlite'}")
    _seed_flyway_history(engine)
    return DBLiftClient.from_sqlalchemy(engine, migrations_dir=str(migrations_dir))


def test_imported_row_keeps_the_flyway_installed_on(tmp_path: Path) -> None:
    client = _make_client(tmp_path)

    assert client.import_flyway().success is True

    rows = client.provider.execute_query(
        "SELECT installed_by, installed_on FROM dblift_schema_history WHERE script = ?",
        ["V1__a.sql"],
    )
    assert len(rows) == 1
    assert rows[0]["installed_by"] == _FLYWAY_INSTALLED_BY
    assert str(rows[0]["installed_on"]) == _FLYWAY_INSTALLED_ON


def test_migrate_still_stamps_its_own_rows(tmp_path: Path) -> None:
    """The ``migrate`` path supplies no ``installed_on``; the column default must still fill it."""
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    (migrations_dir / "V1__a.sql").write_text(_SCRIPT_CONTENT)
    engine = create_engine(f"sqlite:///{tmp_path / 'db.sqlite'}")
    client = DBLiftClient.from_sqlalchemy(engine, migrations_dir=str(migrations_dir))

    assert client.migrate().success is True

    rows = client.provider.execute_query(
        "SELECT installed_on FROM dblift_schema_history WHERE script = ?", ["V1__a.sql"]
    )
    assert len(rows) == 1
    assert rows[0]["installed_on"], "migrate must leave a timestamp behind"
    assert not str(rows[0]["installed_on"]).startswith("2023-")
