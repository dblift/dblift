"""Callback events must not fire on prefix-substring collisions (end-to-end).

Several callback event prefixes are literal substrings of others
(``afterMigrate`` ⊂ ``afterMigrateError``, ``beforeEach`` ⊂
``beforeEachMigrate``, …). Event selection used a bare ``startswith()``, so a
file named with the longer prefix was also picked up by the shorter event.

Observable end-to-end on SQLite:

* ``afterMigrateError__notify.sql`` executed during a *successful* ``migrate``.
* ``beforeEachMigrate__mark.sql`` executed twice per migration script, because
  ``MigrateCommand`` dispatches ``beforeEach`` and ``beforeEachMigrate`` as two
  separate events and the file matched both.

Runs ``python -m cli.main migrate`` as a subprocess against a local SQLite file
so the whole path — script discovery, event dispatch, execution — is exercised.
No mocks. See ``tests/integration/matrix/README.md`` doctrine #2 and #4.
"""

from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import List, Tuple

import pytest
import yaml

DBLIFT_ROOT = Path(__file__).resolve().parents[3]
CLI = [sys.executable, "-m", "cli.main"]

# Every callback in this module appends one row here, tagged with its event.
CALLBACK_LOG_DDL = """
CREATE TABLE IF NOT EXISTS callback_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT
);
"""


def _make_sqlite_config(tmp_path: Path) -> Tuple[Path, Path, Path]:
    """Create dblift.yaml + migrations dir + sqlite db file. Returns (config, migrations, db)."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    db_file = tmp_path / "test.sqlite"
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    config = tmp_path / "dblift.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "database": {"type": "sqlite", "path": str(db_file)},
                "migrations": {"directory": str(migrations_dir)},
            }
        )
    )
    return config, migrations_dir, db_file


def _run(argv: List[str]) -> Tuple[int, str, str]:
    result = subprocess.run(
        [*CLI, *argv],
        cwd=DBLIFT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode, result.stdout, result.stderr


def _logged_events(db_file: Path) -> List[str]:
    with sqlite3.connect(str(db_file)) as conn:
        rows = conn.execute("SELECT event_type FROM callback_log ORDER BY id").fetchall()
    return [row[0] for row in rows]


def _log_callback(migrations_dir: Path, filename: str, event_label: str) -> None:
    migrations_dir.joinpath(filename).write_text(
        f"{CALLBACK_LOG_DDL}\nINSERT INTO callback_log (event_type) VALUES ('{event_label}');\n"
    )


@pytest.mark.integration
@pytest.mark.sqlite
def test_error_callback_does_not_run_on_successful_migrate(tmp_path: Path):
    """``afterMigrateError`` must stay silent when every migration succeeds.

    The safety-critical symptom: alerting / incident / compensating SQL running
    on a green migrate because ``afterMigrate`` is a prefix of
    ``afterMigrateError``.
    """
    config, migrations_dir, db_file = _make_sqlite_config(tmp_path)
    migrations_dir.joinpath("V1__widgets.sql").write_text(
        "CREATE TABLE widgets (id INTEGER PRIMARY KEY);"
    )
    _log_callback(migrations_dir, "afterMigrate__finalize.sql", "afterMigrate")
    _log_callback(migrations_dir, "afterMigrateError__notify.sql", "afterMigrateError")

    exit_code, stdout, stderr = _run(["--config", str(config), "migrate"])

    assert exit_code == 0, f"migrate failed: exit={exit_code}, stdout={stdout}, stderr={stderr}"
    events = _logged_events(db_file)
    assert "afterMigrateError" not in events, (
        "error callback ran on a fully successful migrate: " f"{events}"
    )
    assert events == ["afterMigrate"]


@pytest.mark.integration
@pytest.mark.sqlite
def test_each_migrate_callback_runs_once_per_script(tmp_path: Path):
    """``beforeEachMigrate`` must run once per script, not once per matching event.

    ``MigrateCommand`` dispatches ``beforeEach`` and ``beforeEachMigrate``
    separately; the file must be selected by exactly one of them. Two
    migrations therefore produce two rows, not four.
    """
    config, migrations_dir, db_file = _make_sqlite_config(tmp_path)
    migrations_dir.joinpath("V1__widgets.sql").write_text(
        "CREATE TABLE widgets (id INTEGER PRIMARY KEY);"
    )
    migrations_dir.joinpath("V2__gadgets.sql").write_text(
        "CREATE TABLE gadgets (id INTEGER PRIMARY KEY);"
    )
    _log_callback(migrations_dir, "beforeEachMigrate__mark.sql", "beforeEachMigrate")

    exit_code, stdout, stderr = _run(["--config", str(config), "migrate"])

    assert exit_code == 0, f"migrate failed: exit={exit_code}, stdout={stdout}, stderr={stderr}"
    events = _logged_events(db_file)
    assert events == ["beforeEachMigrate", "beforeEachMigrate"], (
        "beforeEachMigrate callback executed the wrong number of times for "
        f"2 migrations: {events}"
    )
