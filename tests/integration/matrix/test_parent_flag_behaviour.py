"""Parent-level CLI flags must reach every subcommand handler (P1).

Bugs this guards against:
  * bb47769c BUG-01/02 — ``--config`` and ``--scripts`` redefined on subparsers,
    silently overwriting the top-level value.
  * 9219eaa9 — identical bug for ``--dry-run``.
  * NEW-BUG-10 (1.3.x) — same root cause, different flag.

``test_parser_invariants.py`` guards the structural invariant. This file
guards the behavioral invariant: a user running ``dblift --dry-run migrate``
must actually get a dry run — not a real migration.

Runs ``python -m cli.main`` as a subprocess against a local SQLite file so
every test exercises argparse + config merge + command dispatch end-to-end.
No mocks.
"""

from __future__ import annotations

import sqlite3
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import List, Tuple

import pytest
import yaml

DBLIFT_ROOT = Path(__file__).resolve().parents[3]
CLI = [sys.executable, "-m", "dblift.cli.main"]


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
    (migrations_dir / "V1__init.sql").write_text("CREATE TABLE widgets (id INTEGER PRIMARY KEY);")
    return config, migrations_dir, db_file


def _run(argv: List[str], cwd: Path | None = None) -> Tuple[int, str, str]:
    result = subprocess.run(
        [*CLI, *argv],
        cwd=cwd or DBLIFT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode, result.stdout, result.stderr


def _sqlite_tables(db_file: Path) -> set[str]:
    if not db_file.exists():
        return set()
    with sqlite3.connect(str(db_file)) as conn:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        return {r[0] for r in rows}


# --- --dry-run propagation (P1, the 1.3.x regression family) -----------------


@pytest.mark.integration
def test_dry_run_parent_flag_prevents_migrate_writes(tmp_path: Path):
    """``dblift --dry-run migrate`` must NOT create the schema_history table.

    Directly exercises the 9219eaa9 / BUG-01 regression: if a subparser
    redefines ``--dry-run`` with default=False, the parent True gets clobbered
    and a real migration runs.
    """
    config, _, db_file = _make_sqlite_config(tmp_path)

    exit_code, stdout, stderr = _run(["--config", str(config), "--dry-run", "migrate"])

    assert exit_code == 0, f"dry-run migrate failed: exit={exit_code}, stderr={stderr}"
    tables = _sqlite_tables(db_file)
    assert (
        "widgets" not in tables
    ), f"dry-run migrate created real tables! tables={tables}, stderr={stderr}"
    assert (
        "dblift_schema_history" not in tables
    ), f"dry-run migrate created history table! tables={tables}"


@pytest.mark.integration
def test_dry_run_subcommand_position_is_equivalent(tmp_path: Path):
    """``dblift migrate --dry-run`` and ``dblift --dry-run migrate`` must behave identically."""
    config_a, _, db_a = _make_sqlite_config(tmp_path / "a")
    config_b, _, db_b = _make_sqlite_config(tmp_path / "b")

    _run(["--config", str(config_a), "--dry-run", "migrate"])
    _run(["--config", str(config_b), "migrate", "--dry-run"])

    assert _sqlite_tables(db_a) == _sqlite_tables(
        db_b
    ), "Position of --dry-run relative to subcommand must not change behavior"


# --- --config propagation (P1, bb47769c BUG-01/02) ---------------------------


@pytest.mark.integration
def test_config_parent_flag_used_by_every_migration_subcommand(tmp_path: Path):
    """``dblift --config X <subcmd>`` must use X, not fall back to a subparser default."""
    config, _, db_file = _make_sqlite_config(tmp_path)

    for subcmd in ["info", "validate", "migrate"]:
        exit_code, stdout, stderr = _run(["--config", str(config), subcmd])
        assert exit_code == 0, (
            f"{subcmd}: expected exit 0 with valid parent --config, "
            f"got exit={exit_code}, stderr={stderr}"
        )


@pytest.mark.integration
def test_bogus_config_fails_even_when_subcommand_follows(tmp_path: Path):
    """A bogus ``--config`` on the parent must propagate to every subcommand and fail.

    (If a subparser redefined ``--config`` with a default, this would silently
     fall back to the default and succeed — which is the 1.3.1 BUG-01 class.)
    """
    for subcmd in ["info", "migrate", "validate", "clean", "undo"]:
        exit_code, _, stderr = _run(["--config", "/definitely/missing.yaml", subcmd])
        assert exit_code != 0, f"{subcmd} succeeded with a bogus --config (parent flag ignored)"
        assert "Traceback" not in stderr, f"{subcmd} leaked traceback on bad --config"


# --- --scripts propagation (P1) ---------------------------------------------


@pytest.mark.integration
def test_scripts_parent_flag_wins_over_config_directory(tmp_path: Path):
    """``dblift --scripts DIR migrate`` must read from DIR, not the config's ``directory``."""
    config, config_migrations, db_file = _make_sqlite_config(tmp_path)

    # Override: a different scripts dir with a different migration.
    override_dir = tmp_path / "override"
    override_dir.mkdir()
    (override_dir / "V1__override.sql").write_text("CREATE TABLE gadgets (id INTEGER PRIMARY KEY);")

    exit_code, stdout, stderr = _run(
        ["--config", str(config), "--scripts", str(override_dir), "migrate"]
    )

    assert exit_code == 0, f"migrate with --scripts failed: stderr={stderr}"
    tables = _sqlite_tables(db_file)
    assert (
        "gadgets" in tables
    ), f"--scripts override was ignored — config directory was used. tables={tables}"
    assert (
        "widgets" not in tables
    ), f"--scripts override was ignored — widgets from config dir was created. tables={tables}"
