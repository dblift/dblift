"""``--format json`` output contract (P2, P5).

Bugs this guards against:
  * b72cc83a — ``ConsoleLog.info()`` printed a completion banner to stdout
    *after* the JSON payload, breaking ``json.loads(stdout)``.
  * c92a0e90 BUG-02 — ``info --format json`` crashed on string ``installed_on``
    because the serializer called ``.isoformat()`` on what turned out to be
    a plain string.
  * df143fb1 BUG-03 — ``checksum`` missing from ``migrations[*]`` entries.
  * a23a0a75 BUG-02 / d88f88a4 BUG-02 — duplicate "header" lines in output.
  * bb47769c BUG-06 — ``info`` did not support ``--format json`` at all.
Doctrine: stdout is for machine-readable payload; stderr is for humans. A
machine consumer must be able to run ``json.loads(result.stdout)`` without
stripping anything. This file exists to make that contract executable.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest
import yaml

DBLIFT_ROOT = Path(__file__).resolve().parents[3]
CLI = [sys.executable, "-m", "cli.main"]


def _make_sqlite_env(tmp_path: Path) -> Tuple[Path, Path]:
    """Create a fresh SQLite environment with one versioned migration."""
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
    return config, db_file


def _run(argv: List[str]) -> Tuple[int, str, str]:
    result = subprocess.run(
        [*CLI, *argv],
        cwd=DBLIFT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode, result.stdout, result.stderr


# --- stdout must be pure JSON -----------------------------------------------


@pytest.mark.integration
def test_info_json_stdout_is_parseable_empty_db(tmp_path: Path):
    """``info --format json`` on a fresh DB: stdout must be valid JSON, no banners."""
    config, _ = _make_sqlite_env(tmp_path)

    exit_code, stdout, stderr = _run(["--config", str(config), "info", "--format", "json"])

    assert exit_code == 0, f"info --format json failed: stderr={stderr}"
    assert stdout.strip(), "info --format json emitted nothing on stdout"

    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as e:
        pytest.fail(
            f"info --format json stdout is not valid JSON: {e}\n"
            f"stdout={stdout!r}\nstderr={stderr!r}"
        )

    assert isinstance(payload, (dict, list)), f"JSON root is not dict/list: {type(payload)}"


@pytest.mark.integration
def test_info_json_stdout_has_no_trailing_banner(tmp_path: Path):
    """Nothing — not even a completion message — may follow the JSON document on stdout."""
    config, _ = _make_sqlite_env(tmp_path)

    _, stdout, _ = _run(["--config", str(config), "info", "--format", "json"])

    # json.loads accepts a single JSON value; `JSONDecoder().raw_decode` tells us
    # how many chars it consumed. Anything non-whitespace after that is a banner.
    try:
        obj, end = json.JSONDecoder().raw_decode(stdout)
    except json.JSONDecodeError as e:
        pytest.fail(f"stdout not parseable: {e}\nstdout={stdout!r}")
    trailing = stdout[end:].strip()
    assert trailing == "", f"Banner/log text contaminated stdout after JSON: {trailing!r}"


@pytest.mark.integration
def test_info_json_after_migrate_has_checksum_field(tmp_path: Path):
    """Every applied migration in JSON output must carry a non-null ``checksum`` (BUG-03)."""
    config, _ = _make_sqlite_env(tmp_path)

    _run(["--config", str(config), "migrate"])
    exit_code, stdout, stderr = _run(["--config", str(config), "info", "--format", "json"])
    assert exit_code == 0, f"info failed after migrate: stderr={stderr}"

    payload = json.loads(stdout)
    migrations = _extract_migrations_list(payload)
    assert migrations, f"No migrations reported in JSON: {payload}"

    for m in migrations:
        # Applied migrations must have a checksum. Pending ones may not.
        if m.get("state", "").upper() in ("SUCCESS", "APPLIED") or m.get("installed_on"):
            assert m.get("checksum") not in (
                None,
                "",
            ), f"Applied migration has null checksum: {m}"


@pytest.mark.integration
def test_info_json_installed_on_is_string_not_datetime(tmp_path: Path):
    """``installed_on`` must be a JSON-serializable string.

    The BUG-02 class was an ``isoformat()`` call on an already-stringified date.
    Here we just assert the output round-trips through JSON cleanly — if the
    serializer crashes, the subprocess would exit non-zero and stderr would
    contain a traceback.
    """
    config, _ = _make_sqlite_env(tmp_path)

    _run(["--config", str(config), "migrate"])
    exit_code, stdout, stderr = _run(["--config", str(config), "info", "--format", "json"])

    assert exit_code == 0, f"info --format json crashed: exit={exit_code}, stderr={stderr}"
    assert "Traceback" not in stderr, f"Traceback on info --format json: {stderr}"

    payload = json.loads(stdout)  # must re-parse — already tested above, but asserts again
    for m in _extract_migrations_list(payload):
        if m.get("installed_on"):
            assert isinstance(
                m["installed_on"], str
            ), f"installed_on must be str, got {type(m['installed_on'])}: {m}"


# --- Helpers ----------------------------------------------------------------


def _extract_migrations_list(payload: Any) -> List[Dict[str, Any]]:
    """Find the migrations list regardless of top-level shape (dict wrapper vs bare list)."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("migrations", "migrationsData", "items", "data"):
            v = payload.get(key)
            if isinstance(v, list):
                return v
    return []
