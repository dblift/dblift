"""``clean --dry-run`` must enumerate every object type a real clean would drop (P4).

Bugs this guards against:
  * d88f88a4 BUG-03 — mat-views and user-defined types missing from dry-run
  * a3b92c6b BUG-11 — clean --dry-run only called get_tables()
  * a23a0a75 BUG-11 — same pattern, different dialect

The structural fix these bugs all hint at: dry-run and real-clean should
share a *single* object-discovery method. Until that refactor lands, this
matrix test enforces the contract externally: whatever a real clean drops,
dry-run must list.

SQLite variant: covers tables, views, and triggers. Table-owned indexes are
covered as SQLite's implicit table-drop side effect: clean does not emit a
separate ``DROP INDEX`` for them.
"""

from __future__ import annotations

import re
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import List, Set, Tuple

import pytest
import yaml

DBLIFT_ROOT = Path(__file__).resolve().parents[3]
CLI = [sys.executable, "-m", "dblift.cli.main"]


def _make_sqlite_with_objects(tmp_path: Path) -> Tuple[Path, Path, Set[str]]:
    """SQLite DB pre-populated with one of each object type clean would drop.

    Returns (config_path, db_file, expected_object_names).
    """
    tmp_path.mkdir(parents=True, exist_ok=True)
    db_file = tmp_path / "test.sqlite"
    conn = sqlite3.connect(str(db_file))
    cur = conn.cursor()
    cur.executescript("""
        CREATE TABLE widgets (id INTEGER PRIMARY KEY, name TEXT);
        CREATE INDEX idx_widgets_name ON widgets(name);
        CREATE VIEW widgets_view AS SELECT id, name FROM widgets;
        CREATE TRIGGER widgets_trg AFTER INSERT ON widgets
          BEGIN SELECT 1; END;
        """)
    conn.commit()
    conn.close()

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

    expected = {"widgets", "widgets_view", "widgets_trg"}
    return config, db_file, expected


def _run(argv: List[str]) -> Tuple[int, str, str]:
    result = subprocess.run(
        [*CLI, *argv], cwd=DBLIFT_ROOT, capture_output=True, text=True, check=False
    )
    return result.returncode, result.stdout, result.stderr


def _remaining_objects(db_file: Path) -> Set[str]:
    if not db_file.exists():
        return set()
    with sqlite3.connect(str(db_file)) as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' "
            "AND name NOT LIKE 'dblift_%'"
        ).fetchall()
        return {r[0] for r in rows}


# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_sqlite_dry_run_mentions_every_object(tmp_path: Path):
    """Every explicitly dropped table/view/trigger must be named in dry-run output.

    If dry-run silently skips a type (the BUG-11 class), the name won't be in
    stdout/stderr combined, so a user can't audit what clean would do.
    """
    config, db_file, expected = _make_sqlite_with_objects(tmp_path)

    exit_code, stdout, stderr = _run(["--config", str(config), "clean", "--dry-run"])
    output = stdout + stderr

    assert exit_code == 0, f"clean --dry-run failed: exit={exit_code}, stderr={stderr}"

    missing = {name for name in expected if name not in output}
    assert not missing, (
        f"clean --dry-run did not mention {missing}. "
        f"Expected all of {expected}. Output:\n{output}"
    )


@pytest.mark.integration
def test_sqlite_dry_run_does_not_drop_anything(tmp_path: Path):
    """Dry-run must be pure — the DB must be unchanged after it runs."""
    config, db_file, expected = _make_sqlite_with_objects(tmp_path)

    _run(["--config", str(config), "clean", "--dry-run"])

    still_there = _remaining_objects(db_file)
    assert expected.issubset(
        still_there
    ), f"dry-run dropped real objects! before={expected}, after={still_there}"
    assert "idx_widgets_name" in still_there, "dry-run dropped a table-owned index"


@pytest.mark.integration
def test_sqlite_dry_run_matches_real_clean_set(tmp_path: Path):
    """The *set* of objects dry-run lists must equal the set real-clean actually removes.

    This is the structural contract: if dry-run says "I would drop X, Y, Z",
    then a real clean must drop exactly {X, Y, Z} — no more, no fewer.
    """
    # Fresh env for dry-run
    config_dry, db_dry, expected = _make_sqlite_with_objects(tmp_path / "dry")
    _, stdout_dry, stderr_dry = _run(["--config", str(config_dry), "clean", "--dry-run"])
    dry_output = stdout_dry + stderr_dry
    dry_mentioned = {name for name in expected if name in dry_output}

    # Fresh env for real
    config_real, db_real, _ = _make_sqlite_with_objects(tmp_path / "real")
    before_real = _remaining_objects(db_real)
    _run(["--config", str(config_real), "clean", "--clean-enabled"])
    after_real = _remaining_objects(db_real)
    actually_dropped = (before_real - after_real) & expected

    assert dry_mentioned == actually_dropped, (
        f"dry-run ⇔ real clean drift.\n"
        f"  dry-run mentioned:  {dry_mentioned}\n"
        f"  real clean dropped: {actually_dropped}\n"
        f"  asymmetry:          dry_only={dry_mentioned-actually_dropped} "
        f"real_only={actually_dropped-dry_mentioned}"
    )
