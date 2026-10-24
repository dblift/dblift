"""A dry run's --show-sql statements name the object each one acts on, as an applied run's do."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine

from dblift.api import DBLiftClient
from dblift.core.logger.formatters.htmlformatter import HtmlFormatter

V1_SQL = """\
CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT);
CREATE INDEX ix_items_name ON items (name);
INSERT INTO items (id, name) VALUES (1, 'a');
"""

U1_SQL = "DROP TABLE items;\n"


def _client(tmp_path: Path, analysis_mode: str) -> DBLiftClient:
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "V1__create_items.sql").write_text(V1_SQL)
    (migrations / "U1__drop_items.sql").write_text(U1_SQL)
    engine = create_engine(f"sqlite:///{tmp_path / 'app.db'}")
    return DBLiftClient.from_sqlalchemy(
        engine, migrations_dir=migrations, analysis_mode=analysis_mode
    )


def _rendered_objects(result, command: str) -> list:
    html = HtmlFormatter().format_result(result, "main", "app", command)
    rows = []
    for chunk in html.split('class="stmt-row"')[1:]:
        object_type = chunk.split('data-object-type="', 1)[1].split('"', 1)[0]
        object_name = chunk.split('data-object-name="', 1)[1].split('"', 1)[0]
        rows.append((object_type, object_name))
    return rows


@pytest.mark.unit
def test_migrate_dry_run_show_sql_names_each_statement_object(tmp_path):
    client = _client(tmp_path, "full")
    try:
        result = client.migrate(dry_run=True, show_sql=True)
    finally:
        client.close()

    assert result.success, result.error_message
    assert result.sql[0].annotations == [
        {"operation": "CREATE", "object_type": "TABLE", "object_name": "items"},
        {"operation": "CREATE", "object_type": "INDEX", "object_name": "ix_items_name"},
        {"operation": "INSERT", "object_type": "TABLE", "object_name": "items"},
    ]
    assert _rendered_objects(result, "MIGRATE") == [
        ("TABLE", "items"),
        ("INDEX", "ix_items_name"),
        ("TABLE", "items"),
    ]


@pytest.mark.unit
def test_dry_run_matches_the_applied_run_report(tmp_path):
    client = _client(tmp_path, "full")
    try:
        # Rendered before the run: the client's journal then holds the applied statements.
        previewed = _rendered_objects(client.migrate(dry_run=True, show_sql=True), "MIGRATE")
        applied = client.migrate(show_sql=True)
    finally:
        client.close()

    assert applied.success, applied.error_message
    assert previewed == _rendered_objects(applied, "MIGRATE")


@pytest.mark.unit
def test_undo_dry_run_show_sql_names_each_statement_object(tmp_path):
    client = _client(tmp_path, "full")
    try:
        assert client.migrate().success
        result = client.undo(dry_run=True, show_sql=True)
    finally:
        client.close()

    assert result.success, result.error_message
    assert result.sql[0].annotations == [
        {"operation": "DROP", "object_type": "TABLE", "object_name": "items"},
    ]
    assert _rendered_objects(result, "UNDO") == [("TABLE", "items")]


@pytest.mark.unit
def test_execution_analysis_mode_names_no_object(tmp_path):
    """Without object analysis an applied run records no object; the preview matches it."""
    client = _client(tmp_path, "execution")
    try:
        result = client.migrate(dry_run=True, show_sql=True)
    finally:
        client.close()

    assert result.success, result.error_message
    assert [a["object_type"] for a in result.sql[0].annotations] == ["", "", ""]
    assert [a["operation"] for a in result.sql[0].annotations] == ["CREATE", "CREATE", "INSERT"]
