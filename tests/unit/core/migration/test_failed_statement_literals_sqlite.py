"""SQLite regression: a failing statement is identified, not echoed with its literals.

String literals in a migration can be secrets (``CREATE USER ... PASSWORD '...'``,
``INSERT ... VALUES ('token')``). At INFO and above the failure names the script
and the statement's verb and target; the full text only appears at DEBUG. No
Docker needed.
"""

import logging

from sqlalchemy import create_engine

from dblift.api import DBLiftClient
from dblift.core.migration.journals.migration_journal import EntryType

SENTINEL = "SENTINEL-SECRET-42"


def _run_failing_migration(tmp_path, log_level):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "V1__seed.sql").write_text(
        "CREATE TABLE t (id INTEGER);\n"
        f"INSERT INTO missing_table VALUES ('password', '{SENTINEL}');\n"
    )
    log_dir = tmp_path / "logs"
    engine = create_engine(f"sqlite:///{tmp_path / 'app.db'}")
    client = DBLiftClient.from_sqlalchemy(
        engine, migrations_dir=migrations, log_level=log_level, log_file=str(log_dir / "dblift.log")
    )
    try:
        result = client.migrate()
    finally:
        client.close()
        engine.dispose()
    assert not result.success
    return result, "".join(f.read_text() for f in log_dir.iterdir())


def _failed_statement_entries(result):
    return [e for e in result.journal.entries if e.entry_type == EntryType.STATEMENT_FAILED]


def test_failed_statement_literals_do_not_reach_info_output(tmp_path, caplog, capfd):
    with caplog.at_level(logging.INFO):
        result, log_file_text = _run_failing_migration(tmp_path, "INFO")
    captured = capfd.readouterr()
    output = captured.out + captured.err

    assert SENTINEL not in output
    assert SENTINEL not in caplog.text
    assert SENTINEL not in log_file_text
    assert SENTINEL not in (result.error_message or "")
    # The failure is still identified: script, statement and the driver's reason.
    for text in (output, log_file_text):
        assert "V1__seed.sql" in text
        assert "INSERT INTO missing_table" in text
        assert "no such table" in text

    (failed,) = _failed_statement_entries(result)
    assert SENTINEL not in failed.statement
    assert SENTINEL not in failed.error_message
    assert failed.statement.startswith("INSERT INTO missing_table VALUES (")
    assert "no such table" in failed.error_message


def test_full_failed_statement_is_available_at_debug(tmp_path, capfd):
    _, log_file_text = _run_failing_migration(tmp_path, "DEBUG")
    captured = capfd.readouterr()

    assert SENTINEL in captured.out + captured.err
    assert SENTINEL in log_file_text
