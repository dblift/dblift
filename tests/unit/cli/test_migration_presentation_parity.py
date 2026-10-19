"""Visible migration presentation through the source CLI entry point."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[3]


def _project(tmp_path: Path, sql: str = "CREATE TABLE items (id INTEGER PRIMARY KEY);\n") -> Path:
    scripts = tmp_path / "migrations"
    scripts.mkdir()
    (scripts / "V1__create_items.sql").write_text(sql, encoding="utf-8")
    return tmp_path


def _run(project: Path, command: str, *options: str) -> subprocess.CompletedProcess[str]:
    env = {key: value for key, value in os.environ.items() if not key.startswith("DBLIFT_")}
    env.update(
        PYTHONPATH=str(_ROOT),
        DBLIFT_DISABLE_CLI_EXTENSIONS="1",
        NO_COLOR="1",
        COLUMNS="120",
    )
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "dblift.cli.main",
            "--db-url",
            "sqlite:///app.db",
            "--scripts",
            "migrations",
            "--log-dir",
            str(project / "logs"),
            command,
            *options,
        ],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


def _payload(process: subprocess.CompletedProcess[str]) -> dict:
    output = process.stdout.lstrip()
    payload, end = json.JSONDecoder().raw_decode(output)
    assert output[end:].strip() == "", process.stdout
    assert isinstance(payload, dict)
    return payload


def _table_exists(project: Path) -> bool:
    with sqlite3.connect(project / "app.db") as connection:
        return (
            connection.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='items'"
            ).fetchone()[0]
            == 1
        )


def _history_outcomes(project: Path) -> list[tuple[str, int]]:
    with sqlite3.connect(project / "app.db") as connection:
        return connection.execute(
            "SELECT version, success FROM dblift_schema_history ORDER BY installed_rank"
        ).fetchall()


def test_text_migrate_success_has_one_header_footer_and_applies_sql(tmp_path: Path) -> None:
    project = _project(tmp_path)

    process = _run(project, "migrate")

    assert process.returncode == 0, process.stderr
    assert process.stdout.count("DBLIFT COMMAND: MIGRATE") == 1
    assert process.stdout.count("Command MIGRATE completed successfully") == 1
    assert process.stderr.count("Successfully applied migration V1__create_items.sql") == 1
    assert _table_exists(project)


def test_json_migrate_success_has_one_payload_and_applies_sql(tmp_path: Path) -> None:
    project = _project(tmp_path)

    process = _run(project, "migrate", "--format", "json")

    assert process.returncode == 0, process.stderr
    payload = _payload(process)
    assert payload["success"] is True
    assert payload["dry_run"] is False
    assert payload["current_schema_version"] == "1"
    assert payload["migrations_applied"] == ["1"]
    assert "Command MIGRATE completed successfully" not in process.stdout
    assert _table_exists(project)


def test_empty_text_and_json_migrate_keep_success_and_one_completion(tmp_path: Path) -> None:
    project = _project(tmp_path)
    (project / "migrations" / "V1__create_items.sql").unlink()

    text = _run(project, "migrate")
    machine = _run(project, "migrate", "--format", "json")

    assert text.returncode == machine.returncode == 0
    assert text.stdout.count("No pending migrations found") == 1
    assert text.stdout.count("Command MIGRATE completed successfully") == 1
    assert machine.stderr.count("No pending migrations found") == 1
    payload = _payload(machine)
    assert payload["success"] is True
    assert payload["migrations"] == payload["migrations_applied"] == []
    assert not _table_exists(project)


def test_dry_run_warning_and_sql_stay_visible_without_database_effect(tmp_path: Path) -> None:
    project = _project(tmp_path, "DROP TABLE items;\n")

    process = _run(project, "migrate", "--dry-run", "--show-sql")

    assert process.returncode == 0, process.stderr
    assert process.stdout.count("Dry run — 1 migration(s) would be applied") == 1
    assert process.stdout.count("Command MIGRATE completed successfully") == 1
    assert process.stderr.count("V1__create_items.sql [UNSAFE]") == 1
    assert "WARNING:" in process.stderr
    assert "drop-table" in process.stderr
    assert process.stderr.count("SQL Statements:") == 1
    assert process.stderr.count("-- V1__create_items.sql") == 1
    assert "\nDROP TABLE items\n" in process.stderr.split("SQL Statements:", 1)[1]
    assert not _table_exists(project)


def test_json_dry_run_show_sql_has_one_payload_and_no_effect(tmp_path: Path) -> None:
    project = _project(tmp_path)

    process = _run(project, "migrate", "--dry-run", "--show-sql", "--format", "json")

    assert process.returncode == 0, process.stderr
    payload = _payload(process)
    assert payload["success"] is True
    assert payload["dry_run"] is True
    assert payload["dry_run_count"] == 1
    assert payload["migrations_applied"] == []
    assert payload["show_sql"] is True
    assert payload["sql"][0]["statements"] == ["CREATE TABLE items (id INTEGER PRIMARY KEY)"]
    assert process.stderr.count("DRY RUN: Would execute the following migrations:") == 1
    assert not _table_exists(project)


def test_real_show_sql_and_undo_keep_one_completion_each(tmp_path: Path) -> None:
    project = _project(tmp_path)
    (project / "migrations" / "U1__drop_items.sql").write_text(
        "DROP TABLE items;\n", encoding="utf-8"
    )

    migrated = _run(project, "migrate", "--show-sql")
    assert migrated.returncode == 0, migrated.stderr
    assert migrated.stdout.count("Command MIGRATE completed successfully") == 1
    assert migrated.stderr.count("SQL Statements:") == 1
    assert migrated.stderr.count("CREATE TABLE items (id INTEGER PRIMARY KEY)") == 1
    assert _table_exists(project)

    undone = _run(project, "undo", "--show-sql")
    assert undone.returncode == 0, undone.stderr
    assert undone.stdout.count("DBLIFT COMMAND: UNDO") == 1
    assert undone.stdout.count("Command UNDO completed successfully") == 1
    assert undone.stderr.count("Successfully undone migration V1__create_items.sql") == 1
    assert undone.stderr.count("DROP TABLE items") == 1
    assert not _table_exists(project)


def test_show_query_results_renders_one_table_without_show_sql(tmp_path: Path) -> None:
    project = _project(
        tmp_path,
        "CREATE TABLE items (id INTEGER PRIMARY KEY);\n"
        "INSERT INTO items VALUES (7);\n"
        "SELECT id FROM items;\n",
    )

    process = _run(project, "migrate", "--show-query-results")

    assert process.returncode == 0, process.stderr
    assert process.stdout.count("Command MIGRATE completed successfully") == 1
    assert len(re.findall(r"│\s*7\s*│", process.stderr)) == 1
    assert "SQL Statements:" not in process.stderr
    assert _table_exists(project)


@pytest.mark.parametrize(
    ("statement", "sql_preview"),
    [
        ("INSERT INTO absent VALUES (7)", "INSERT INTO absent"),
        ("SELECT id FROM absent", "SELECT id"),
    ],
    ids=["write", "query"],
)
def test_execution_failure_text_keeps_error_and_failed_footer(
    tmp_path: Path, statement: str, sql_preview: str
) -> None:
    project = _project(
        tmp_path,
        f"CREATE TABLE items (id INTEGER PRIMARY KEY);\n{statement};\n",
    )

    process = _run(project, "migrate")

    assert process.returncode == 1
    assert process.stdout.count("Command MIGRATE failed") == 1
    assert "Failed to execute statement 2 in V1__create_items.sql" in process.stdout
    assert "no such table: absent" in process.stderr
    assert process.stderr.count(f"ERROR: SQL: {sql_preview}") == 1
    assert "Command MIGRATE completed successfully" not in process.stdout
    assert _history_outcomes(project) == [("1", 0)]
    assert not _table_exists(project)


@pytest.mark.parametrize(
    ("statement", "sql_preview"),
    [
        ("INSERT INTO absent VALUES (7)", "INSERT INTO absent"),
        ("SELECT id FROM absent", "SELECT id"),
    ],
    ids=["write", "query"],
)
def test_execution_failure_json_has_one_error_payload(
    tmp_path: Path, statement: str, sql_preview: str
) -> None:
    project = _project(
        tmp_path,
        f"CREATE TABLE items (id INTEGER PRIMARY KEY);\n{statement};\n",
    )

    process = _run(project, "migrate", "--format", "json")

    assert process.returncode == 1
    payload = _payload(process)
    assert payload["success"] is False
    assert "no such table: absent" in payload["error"]
    assert payload["migrations_applied"] == []
    assert process.stderr.count(f"ERROR: SQL: {sql_preview}") == 1
    assert "Command MIGRATE failed" not in process.stdout
    assert _history_outcomes(project) == [("1", 0)]
    assert not _table_exists(project)


def test_failed_callback_keeps_one_sql_preview_and_error_cause(tmp_path: Path) -> None:
    project = _project(tmp_path)
    (project / "migrations" / "beforeMigrate__fail.sql").write_text(
        "SELECT id FROM absent;\n", encoding="utf-8"
    )

    process = _run(project, "migrate")

    assert process.returncode == 1
    assert process.stdout.count("Command MIGRATE failed") == 1
    assert "Callback beforeMigrate__fail.sql failed" in process.stdout
    assert "Error executing query: no such table: absent" in process.stderr
    assert process.stderr.count("ERROR: SQL: SELECT id") == 1
    assert not _table_exists(project)


def test_callback_without_execution_service_keeps_sql_preview() -> None:
    from dblift.core.migration.executor.execution_engine import ExecutionEngine
    from tests.unit._migration_factory import make_migration

    provider = MagicMock()
    provider.execute_query.side_effect = sqlite3.OperationalError("no such table: absent")
    analyzer = MagicMock()
    analyzer.dialect = "sqlite"
    analyzer.split_statements.return_value = ["SELECT id FROM absent"]
    analyzer.get_statement_type.return_value = "QUERY"
    log = MagicMock()
    engine = ExecutionEngine(provider, analyzer, log, sql_execution_service=None)
    callback = make_migration(
        script_name="beforeMigrate__fail.sql", content="SELECT id FROM absent", dialect="sqlite"
    )

    with pytest.raises(sqlite3.OperationalError, match="no such table: absent"):
        engine.execute_callback(callback)

    log.error.assert_any_call("Error executing callback SQL statement: no such table: absent")
    assert [call.args[0] for call in log.error.call_args_list].count("SQL: SELECT id") == 1
    provider.execute_query.assert_called_once_with("SELECT id FROM absent")


def test_info_json_pending_and_applied_statuses(tmp_path: Path) -> None:
    project = _project(tmp_path)

    before = _run(project, "info", "--format", "json")
    migrated = _run(project, "migrate")
    after = _run(project, "info", "--format", "json")

    assert before.returncode == migrated.returncode == after.returncode == 0
    pending = _payload(before)
    applied = _payload(after)
    assert pending["success"] is applied["success"] is True
    assert pending["current_schema_version"] is None
    assert applied["current_schema_version"] == "1"
    assert [row["status"] for row in pending["migrations"]] == ["PENDING"]
    assert [row["status"] for row in applied["migrations"]] == ["SUCCESS"]


def test_info_text_keeps_pending_table_and_one_footer(tmp_path: Path) -> None:
    project = _project(tmp_path)

    process = _run(project, "info")

    assert process.returncode == 0, process.stderr
    assert process.stdout.count("DBLIFT COMMAND: INFO") == 1
    assert process.stdout.count("Command INFO completed successfully") == 1
    assert process.stdout.count("Total migrations: 1") == 1
    assert "Pending" in process.stdout
    assert "V1__create_items.sql" not in process.stderr
    assert process.stderr.count("Pending Migrations: 1") == 1


def test_existing_render_helpers_and_logger_exports_keep_their_identity() -> None:
    from dblift.core import logger
    from dblift.core.logger import log, results
    from dblift.core.logger.formatters.formatter import OutputFormatter
    from dblift.core.logger.formatters.htmlformatter import HtmlFormatter
    from dblift.core.migration.commands.base_command import _props_text, _render_main_header_panel

    assert logger.Log is log.Log
    assert logger.NullLog is log.NullLog
    assert logger.MigrateResult is results.MigrateResult
    assert logger.OutputFormatter is OutputFormatter
    assert logger.JsonFormatter is log.JsonFormatter
    assert logger.HtmlFormatter is HtmlFormatter
    assert _props_text("Schema: main").plain == "Schema: main"
    rendered = _render_main_header_panel("DBLIFT DATABASE MIGRATION LOG\nSchema: main")
    assert rendered.count("DBLIFT DATABASE MIGRATION LOG") == 1
    assert "Schema: main" in rendered
