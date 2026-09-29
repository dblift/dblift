"""SQLite changes that require a table rebuild remain visible in scripts."""

from types import SimpleNamespace

from dblift.core.state.sql_statement import SqlStatement
from dblift.db.plugins.sqlite.quirks import SqliteQuirks


def test_type_change_emits_rebuild_comment():
    diff = SimpleNamespace(data_type_diff=("TEXT", "INTEGER"))
    statement = SqliteQuirks().render_column_type_change(diff, '"t"', '"c"', "sqlite")
    assert isinstance(statement, SqlStatement)
    assert statement.statement_type == "COMMENT"
    assert statement.sql.startswith("-- ")
    assert '"t"' in statement.sql and '"c"' in statement.sql
    assert "INTEGER" in statement.sql and "TEXT" in statement.sql
    assert "rebuild" in statement.sql.lower()
    assert statement.object_type == "COLUMN"
    assert statement.object_name == '"t"."c"'
    assert statement.dialect == "sqlite"


def test_no_type_change_has_no_rebuild_comment():
    diff = SimpleNamespace(data_type_diff=None)
    assert SqliteQuirks().render_column_type_change(diff, '"t"', '"c"', "sqlite") is None
