"""``--dry-run`` must leave the database byte-identical (P4, strict form).

Bugs this guards against:
  * 9219eaa9 / BUG-01 — subparser ``--dry-run`` default clobbered the
    parent True, so real migrations ran under the --dry-run flag.
  * PR 160 root cause — ``migrate --dry-run`` unconditionally called
    ``create_schema_and_history_table()`` before the dry-run short-circuit.
  * The ``clean --dry-run`` counterpart tested in
    ``test_dry_run_completeness.py``.

Existing tests assert structural properties ("table X must not appear").
They catch one way to violate purity but not all. This file expresses the
strongest possible invariant: after a ``--dry-run`` command, the SQLite
database file must be **byte-identical** to its pre-invocation state.
Any regression — history table creation, snapshot insertion, WAL
checkpoint write, metadata update — fails this test immediately and
points to the exact command and phase responsible.

If the SHA-256 check is too tight for a future legitimate reason (e.g.
SQLite rewrites a journal page without data change), fall back to the
weaker object-list check: the enumerated objects must still match.
"""

from __future__ import annotations

import hashlib
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import List, Tuple

import pytest
import yaml

DBLIFT_ROOT = Path(__file__).resolve().parents[3]
CLI = [sys.executable, "-m", "cli.main"]


# --- Fingerprinting helpers -------------------------------------------------


def _file_sha256(path: Path) -> str:
    """Byte-level SHA-256 of the given file. Raises if the file is missing."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _sqlite_object_list(db_file: Path) -> Tuple[str, ...]:
    """Sorted list of non-internal schema objects in a SQLite DB."""
    with sqlite3.connect(str(db_file)) as conn:
        rows = conn.execute(
            "SELECT type, name FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
        ).fetchall()
    return tuple(f"{typ}:{name}" for (typ, name) in rows)


# --- Environments -----------------------------------------------------------


def _make_env_with_pending_migration(tmp_path: Path) -> Tuple[Path, Path]:
    """Config + empty SQLite DB + one pending migration. For ``migrate --dry-run``."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    db_file = tmp_path / "test.sqlite"

    # Create the file with a single committed object so we have non-empty
    # content to hash. A truly empty SQLite file has length 0, which
    # makes SHA-256 less diagnostic.
    with sqlite3.connect(str(db_file)) as conn:
        conn.execute("CREATE TABLE seed (id INTEGER PRIMARY KEY);")
        conn.commit()

    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    (migrations_dir / "V1__create_widgets.sql").write_text(
        "CREATE TABLE widgets (id INTEGER PRIMARY KEY, name TEXT);"
    )

    config = tmp_path / "dblift.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "database": {"type": "sqlite", "path": str(db_file)},
                "migrations": {"directory": str(migrations_dir)},
            }
        )
    )
    return config, db_file


def _make_env_with_populated_db(tmp_path: Path) -> Tuple[Path, Path]:
    """Config + SQLite DB populated with several objects. For ``clean --dry-run``."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    db_file = tmp_path / "test.sqlite"
    with sqlite3.connect(str(db_file)) as conn:
        conn.executescript("""
            CREATE TABLE widgets (id INTEGER PRIMARY KEY, name TEXT);
            CREATE INDEX idx_widgets_name ON widgets(name);
            CREATE VIEW widgets_view AS SELECT id, name FROM widgets;
            CREATE TRIGGER widgets_trg AFTER INSERT ON widgets
              BEGIN SELECT 1; END;
            INSERT INTO widgets (name) VALUES ('a'), ('b');
            """)
        conn.commit()

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
    return config, db_file


def _run(argv: List[str]) -> Tuple[int, str, str]:
    result = subprocess.run(
        [*CLI, *argv], cwd=DBLIFT_ROOT, capture_output=True, text=True, check=False
    )
    return result.returncode, result.stdout, result.stderr


# --- Tests ------------------------------------------------------------------


@pytest.mark.integration
def test_migrate_dry_run_is_byte_identical(tmp_path: Path):
    """``migrate --dry-run`` must not change a single byte of the DB file.

    Strongest form of the purity contract. If this fails, something under
    dry-run is opening a write connection or committing a transaction —
    investigate ``_initialize_migration_execution`` / snapshot capture /
    history-table creation (all known failure modes).
    """
    config, db_file = _make_env_with_pending_migration(tmp_path)

    before_sha = _file_sha256(db_file)
    before_objects = _sqlite_object_list(db_file)
    before_size = db_file.stat().st_size

    exit_code, stdout, stderr = _run(["--config", str(config), "migrate", "--dry-run"])
    assert exit_code == 0, f"migrate --dry-run failed: stderr={stderr}"

    after_sha = _file_sha256(db_file)
    after_objects = _sqlite_object_list(db_file)
    after_size = db_file.stat().st_size

    assert after_sha == before_sha, (
        f"migrate --dry-run mutated the DB file.\n"
        f"  before sha: {before_sha}\n"
        f"  after  sha: {after_sha}\n"
        f"  before size: {before_size}  after size: {after_size}\n"
        f"  before objects: {before_objects}\n"
        f"  after  objects: {after_objects}"
    )


@pytest.mark.integration
def test_migrate_dry_run_preserves_object_list(tmp_path: Path):
    """Fallback (weaker) purity check — object catalogue must be unchanged.

    Kept separately from the SHA check so that if a future SQLite or driver
    write emits a page-level change with no schema impact, we still have
    a meaningful test (and a clearer error pointing at an actual object
    insertion, e.g. dblift_schema_history).
    """
    config, db_file = _make_env_with_pending_migration(tmp_path)
    before = _sqlite_object_list(db_file)

    exit_code, _, stderr = _run(["--config", str(config), "migrate", "--dry-run"])
    assert exit_code == 0, f"migrate --dry-run failed: stderr={stderr}"

    after = _sqlite_object_list(db_file)
    added = set(after) - set(before)
    removed = set(before) - set(after)
    assert not added and not removed, (
        f"migrate --dry-run changed the object catalogue.\n"
        f"  added:   {sorted(added)}\n"
        f"  removed: {sorted(removed)}"
    )


@pytest.mark.integration
def test_clean_dry_run_is_byte_identical(tmp_path: Path):
    """``clean --dry-run`` must not change a single byte of the DB file.

    Complements ``test_dry_run_completeness.py`` which checks enumeration;
    this one pins the "no writes" axis independently.
    """
    config, db_file = _make_env_with_populated_db(tmp_path)

    before_sha = _file_sha256(db_file)
    before_objects = _sqlite_object_list(db_file)

    exit_code, stdout, stderr = _run(["--config", str(config), "clean", "--dry-run"])
    assert exit_code == 0, f"clean --dry-run failed: stderr={stderr}"

    after_sha = _file_sha256(db_file)
    after_objects = _sqlite_object_list(db_file)

    assert after_sha == before_sha, (
        f"clean --dry-run mutated the DB file.\n"
        f"  before sha: {before_sha}\n"
        f"  after  sha: {after_sha}\n"
        f"  before objects: {before_objects}\n"
        f"  after  objects: {after_objects}"
    )


@pytest.mark.integration
def test_clean_dry_run_preserves_object_list(tmp_path: Path):
    """Fallback (weaker) purity check for clean — object catalogue unchanged."""
    config, db_file = _make_env_with_populated_db(tmp_path)
    before = _sqlite_object_list(db_file)

    exit_code, _, stderr = _run(["--config", str(config), "clean", "--dry-run"])
    assert exit_code == 0, f"clean --dry-run failed: stderr={stderr}"

    after = _sqlite_object_list(db_file)
    added = set(after) - set(before)
    removed = set(before) - set(after)
    assert not added and not removed, (
        f"clean --dry-run changed the object catalogue.\n"
        f"  added:   {sorted(added)}\n"
        f"  removed: {sorted(removed)}"
    )
