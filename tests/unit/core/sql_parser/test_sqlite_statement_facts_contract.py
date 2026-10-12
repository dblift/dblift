"""SQLite statement facts replace text-based object extraction."""

import importlib.util

from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer
from dblift.core.sql_model.base import SqlObjectType, SqlStatementType
from dblift.core.sql_parser.parser_factory import SqlParserFactory


UPDATE = "UPDATE child SET parent_id = 2 WHERE id = 1;"


def test_update_target_is_reported_in_the_existing_parse_result_shape():
    result = SqlParserFactory("sqlite", parser_type="hybrid").parse_sql(UPDATE)

    assert result.success
    assert len(result.statements) == 1
    statement = result.statements[0]
    assert statement.statement_type == SqlStatementType.DML
    assert [(obj.object_type, obj.name) for obj in statement.affected_objects] == [
        (SqlObjectType.TABLE, "child")
    ]


def test_sql_analyzer_objects_do_not_use_the_regex_extractor(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("legacy regex extraction reached")

    monkeypatch.setattr(SqlAnalyzer, "_extract_objects_regex", forbidden)
    assert SqlAnalyzer("sqlite").extract_objects(UPDATE) == [
        {"object_type": "TABLE", "object_name": "default_schema.child"}
    ]


def test_sqlite_regex_extractor_module_is_removed():
    assert importlib.util.find_spec("dblift.db.plugins.sqlite.parser.sqlite_regex_parser") is None
