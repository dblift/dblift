"""SQLite statement facts replace text-based object extraction."""

import importlib.util

from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer
from dblift.core.migration.sql.script_analysis import analyse_script
from dblift.core.sql_model.base import SqlObjectType, SqlStatementType
from dblift.core.sql_parser.parser_factory import SqlParserFactory
from dblift.db.plugins.sqlite.quirks import SqliteQuirks


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


def test_cte_update_has_one_target_and_full_table_caution(monkeypatch):
    from dblift.core.migration.sql import script_analysis

    def forbidden(*args, **kwargs):
        raise AssertionError("legacy extraction reached")

    monkeypatch.setattr(script_analysis, "_fallback_objects", forbidden)
    sql = "WITH x AS (SELECT 1) UPDATE child SET parent_id = 2;"
    analysis = analyse_script(sql, "sqlite")

    assert analysis.errors == ()
    assert analysis.statements[0].kind == "DML"
    assert [(obj.type, obj.name) for obj in analysis.statements[0].objects] == [
        ("TABLE", "child")
    ]
    assert analysis.statements[0].full_table
    assert analysis.cautions[0].code == "dml-no-where"


def test_opaque_trigger_keeps_identity_and_diagnostic():
    sql = "CREATE TRIGGER trg AFTER INSERT ON child BEGIN UPDATE child SET id = 2; END;"
    result = SqlParserFactory("sqlite").parse_sql(sql)

    assert len(result.statements) == 1
    assert [(obj.object_type, obj.name) for obj in result.statements[0].affected_objects] == [
        (SqlObjectType.TRIGGER, "trg")
    ]
    assert not result.success
    assert any("trigger" in error.lower() for error in result.errors)


def test_sqlite_dml_analysis_refuses_unparsed_mutation_instead_of_regex_guess():
    mutation = SqliteQuirks().analyze_dml("UPDATE child SET parent_id =")

    assert mutation.table == ""
    assert mutation.events is None
    assert mutation.updated_columns == []


def test_sqlite_parser_config_patterns_are_removed():
    assert importlib.util.find_spec("dblift.db.plugins.sqlite.parser.parser_config") is None
