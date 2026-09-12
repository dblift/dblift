"""``validate`` reporting driven through a real validator, not hand-authored lists.

The unit tests for ``_record_validated_migrations`` set ``checked_scripts`` /
``failed_scripts`` by hand, so they cannot catch a validator path that fails to
record one. That gap shipped a payload reporting a migration which had *failed
in history* as ``validated`` with ``status: SUCCESS`` — worse than the empty
lists it replaced, since it asserts a check that contradicts the truth.

These run the real ``ValidateCommand`` against a real SQLite database.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


def _run(tmp_path: Path, *args: str, scripts: Path, db: Path):
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "dblift.cli.main",
            "--scripts",
            str(scripts),
            "--log-dir",
            str(tmp_path / "logs"),
            "--db-url",
            f"sqlite:///{db}",
            *args,
        ],
        capture_output=True,
        text=True,
    )


def _payload(proc: subprocess.CompletedProcess) -> dict:
    return json.loads(proc.stdout)


@pytest.fixture
def project(tmp_path: Path):
    scripts = tmp_path / "migrations"
    scripts.mkdir()
    (scripts / "V1__a.sql").write_text("CREATE TABLE a (id INTEGER PRIMARY KEY);")
    return scripts, tmp_path / "t.db"


def test_a_migration_that_failed_in_history_is_never_reported_as_validated(tmp_path, project):
    scripts, db = project
    (scripts / "V2__bad.sql").write_text(
        "CREATE TABLE b (id INTEGER);\nINSERT INTO nonexistent_tbl VALUES (1);"
    )
    _run(tmp_path, "migrate", scripts=scripts, db=db)  # records V2 as failed

    payload = _payload(_run(tmp_path, "validate", "--format", "json", scripts=scripts, db=db))

    assert payload["success"] is False
    validated = {m["script"] for m in payload["validated_migrations"]}
    assert "V2__bad.sql" not in validated, "a failed migration reported as validated"
    assert "V2__bad.sql" in {m["script"] for m in payload["failed_migrations"]}
    assert payload["error_count"] >= 1


def test_checksum_drift_names_every_drifted_script(tmp_path, project):
    scripts, db = project
    (scripts / "V2__b.sql").write_text("CREATE TABLE b (id INTEGER);")
    _run(tmp_path, "migrate", scripts=scripts, db=db)

    for name in ("V1__a.sql", "V2__b.sql"):
        (scripts / name).write_text((scripts / name).read_text() + "\n-- drift\n")

    payload = _payload(_run(tmp_path, "validate", "--format", "json", scripts=scripts, db=db))

    assert payload["success"] is False
    assert {m["script"] for m in payload["failed_migrations"]} == {"V1__a.sql", "V2__b.sql"}
    assert payload["error_count"] == 2
    assert sum("has been modified" in i for i in payload["issues"]) == 2


def test_duplicate_versions_name_both_colliding_scripts(tmp_path, project):
    scripts, db = project
    (scripts / "V1__duplicate.sql").write_text("CREATE TABLE dup (id INTEGER);")

    payload = _payload(_run(tmp_path, "validate", "--format", "json", scripts=scripts, db=db))

    assert payload["success"] is False
    assert {m["script"] for m in payload["failed_migrations"]} == {
        "V1__a.sql",
        "V1__duplicate.sql",
    }


def test_a_clean_run_reports_what_it_validated_and_no_failures(tmp_path, project):
    scripts, db = project
    _run(tmp_path, "migrate", scripts=scripts, db=db)

    payload = _payload(_run(tmp_path, "validate", "--format", "json", scripts=scripts, db=db))

    assert payload["success"] is True
    assert payload["error_count"] == 0
    assert payload["failed_migrations"] == []
    assert "V1__a.sql" in {m["script"] for m in payload["validated_migrations"]}


def test_undo_scripts_are_not_reported_as_validated(tmp_path, project):
    """They are collected, then exempted from every check (unchanged behaviour)."""
    scripts, db = project
    (scripts / "U1__undo_a.sql").write_text("DROP TABLE a;")
    _run(tmp_path, "migrate", scripts=scripts, db=db)

    payload = _payload(_run(tmp_path, "validate", "--format", "json", scripts=scripts, db=db))

    assert payload["success"] is True
    assert "U1__undo_a.sql" not in {m["script"] for m in payload["validated_migrations"]}


def test_a_command_level_failure_still_counts(tmp_path):
    """``error_count`` must not read 0 beside ``success: false``."""
    scripts = tmp_path / "migrations"
    scripts.mkdir()
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "dblift.cli.main",
            "--scripts",
            str(scripts),
            "--log-dir",
            str(tmp_path / "logs"),
            "--db-url",
            "postgresql://127.0.0.1:1/nope",
            "--db-username",
            "u",
            "--db-password",
            "p",
            "validate",
            "--format",
            "json",
        ],
        capture_output=True,
        text=True,
    )
    payload = json.loads(proc.stdout)
    assert payload["success"] is False
    assert payload["error_count"] >= 1, "a failed command reported error_count: 0"
