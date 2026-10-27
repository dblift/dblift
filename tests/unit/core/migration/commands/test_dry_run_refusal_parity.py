"""A dry run refuses the scripts a real run refuses, with or without --show-sql.

``neutralise_transaction_statements`` runs while a script's statements are prepared. A dry run
that only linted the script reported ``[SAFE]`` for a ``COMMIT`` in the middle of a script that
the real run then refused.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine

from dblift.api import DBLiftClient

COMMIT_MID_SCRIPT = "CREATE TABLE b (id INTEGER);\nCOMMIT;\nCREATE TABLE c (id INTEGER);\n"
CLEAN_SCRIPT = "CREATE TABLE b (id INTEGER);\nCREATE TABLE c (id INTEGER);\n"
MODES = pytest.mark.parametrize("analysis_mode", ["full", "execution"])


def _client(tmp_path: Path, analysis_mode: str, **scripts: str) -> DBLiftClient:
    migrations = tmp_path / "migrations"
    migrations.mkdir(exist_ok=True)
    for name, text in scripts.items():
        (migrations / f"{name}.sql").write_text(text)
    engine = create_engine(f"sqlite:///{tmp_path / 'app.db'}")
    return DBLiftClient.from_sqlalchemy(
        engine, migrations_dir=migrations, analysis_mode=analysis_mode
    )


@pytest.mark.unit
@MODES
@pytest.mark.parametrize("show_sql", [False, True])
def test_migrate_dry_run_refuses_what_the_real_run_refuses(tmp_path, analysis_mode, show_sql):
    client = _client(tmp_path, analysis_mode, V1__commit_inside=COMMIT_MID_SCRIPT)
    try:
        dry = client.migrate(dry_run=True, show_sql=show_sql)
        real = client.migrate()
    finally:
        client.close()

    assert not real.success
    assert "COMMIT manages the transaction" in real.error_message
    assert not dry.success
    assert dry.error_message in real.error_message


@pytest.mark.unit
@MODES
def test_migrate_dry_run_of_an_accepted_script_succeeds_and_records_no_sql(tmp_path, analysis_mode):
    client = _client(tmp_path, analysis_mode, V1__clean=CLEAN_SCRIPT)
    try:
        dry = client.migrate(dry_run=True)
    finally:
        client.close()

    assert dry.success, dry.error_message
    assert dry.dry_run_count == 1
    assert dry.sql == []


@pytest.mark.unit
@MODES
@pytest.mark.parametrize("show_sql", [False, True])
def test_undo_dry_run_refuses_what_the_real_undo_refuses(tmp_path, analysis_mode, show_sql):
    client = _client(
        tmp_path,
        analysis_mode,
        V1__clean=CLEAN_SCRIPT,
        U1__commit_inside="DROP TABLE c;\nCOMMIT;\nDROP TABLE b;\n",
    )
    try:
        assert client.migrate().success
        dry = client.undo(dry_run=True, show_sql=show_sql)
        real = client.undo()
    finally:
        client.close()

    assert not real.success
    assert "COMMIT manages the transaction" in real.error_message
    assert not dry.success
    assert dry.error_message in real.error_message
