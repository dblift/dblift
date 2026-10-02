"""SQLite regression: the HTML run report shows which migration failed.

A migration whose second statement fails was rendered as ``OK`` with only its
first statement, and a failed undo script had no per-migration entry at all,
while the JSON output reported both as failed. No Docker needed.
"""

import pytest
from sqlalchemy import create_engine

from dblift.api import DBLiftClient
from dblift.core.logger.formatters.htmlformatter import HtmlFormatter

pytestmark = [pytest.mark.integration]


def _migration_block(html: str, script: str) -> str:
    start = html.index(f'<span class="file">{script}</span>')
    end = html.find('<div class="mig-item', start)
    return html[start : end if end != -1 else len(html)]


def _client(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'app.db'}")
    return engine, DBLiftClient.from_sqlalchemy(engine, migrations_dir=tmp_path / "migrations")


def test_failed_statement_marks_migration_failed(tmp_path):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "V1__create_orders.sql").write_text(
        "CREATE TABLE orders (id INTEGER PRIMARY KEY);\n"
    )
    (migrations / "V2__add_currency.sql").write_text(
        "ALTER TABLE orders ADD COLUMN currency CHAR(3);\n"
        "UPDATE orders SET currency = 'EUR' WHERE shipping_country = 'FR';\n"
    )

    engine, client = _client(tmp_path)
    try:
        result = client.migrate()
    finally:
        client.close()
        engine.dispose()
    assert not result.success

    html = HtmlFormatter().format_result(result, "main", "app.db", "MIGRATE")

    assert "Failure root cause" in html
    assert "failed at statement #2" in html
    failed = _migration_block(html, "V2__add_currency.sql")
    assert "2 stmts" in failed
    assert '<span class="badge fail dot">Failed</span>' in failed
    assert "no such column: shipping_country" in failed
    assert '<span class="badge ok dot">OK</span>' in _migration_block(html, "V1__create_orders.sql")


def test_failed_undo_script_is_reported(tmp_path):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "V1__create_orders.sql").write_text(
        "CREATE TABLE orders (id INTEGER PRIMARY KEY);\n"
    )
    (migrations / "V2__create_items.sql").write_text("CREATE TABLE items (id INTEGER);\n")
    (migrations / "U2__drop_items.sql").write_text("DROP TABLE items;\nDROP TABLE missing_table;\n")

    engine, client = _client(tmp_path)
    try:
        assert client.migrate().success
        result = client.undo(target_version="1")
    finally:
        client.close()
        engine.dispose()
    assert not result.success
    assert result.undone_count == 0
    assert [(m.script, m.status) for m in result.migrations] == [("U2__drop_items.sql", "FAILED")]

    html = HtmlFormatter().format_result(result, "main", "app.db", "UNDO")

    failed = _migration_block(html, "U2__drop_items.sql")
    assert '<span class="badge fail dot">Failed</span>' in failed
    assert "no such table: missing_table" in failed
