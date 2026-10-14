"""SQLite statement facts replace text-based object extraction."""

import importlib.util
from unittest.mock import MagicMock

import pytest

from dblift.core.migration.migration import Migration
from dblift.core.migration.scripting.undo_script_generator import UndoScriptGenerator
from dblift.core.migration.sql.script_analysis import analyse_script
from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer
from dblift.core.migration.sql.sql_execution_service import SqlExecutionService
from dblift.core.sql_model.base import SqlObjectType, SqlStatementType
from dblift.core.sql_parser.hybrid_parser import HybridParser
from dblift.core.sql_parser.parser_factory import SqlParserFactory
from dblift.core.sql_parser.sqlglot_parser import SqlGlotParser
from dblift.core.sql_parser.statement_facts import SqlglotStatementFactsReader
from dblift.db.dml_analysis import analyze_dml, statement_dml_table
from dblift.db.plugins.sqlite.parser.lexical_spec import SQLITE_SPEC
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


def test_sqlite_sqlglot_factory_type_remains_unsupported():
    assert SqliteQuirks().parser_class("sqlglot") is None


@pytest.mark.parametrize("parser_class", [HybridParser, SqlGlotParser])
def test_direct_generic_parser_construction_rejects_sqlite(parser_class):
    with pytest.raises(ValueError, match="SQLiteFactsParser"):
        parser_class("sqlite")


@pytest.mark.parametrize("parser_class", [HybridParser, SqlGlotParser])
def test_direct_generic_parser_remains_available_for_unmigrated_dialect(parser_class):
    assert parser_class("postgresql").dialect_name == "postgresql"


def test_index_facts_separate_indexed_columns_from_declared_table_columns():
    facts = SqlglotStatementFactsReader("sqlite", SQLITE_SPEC).read(
        "CREATE INDEX ix ON child (parent_id, id)"
    )
    assert facts.indexed_table == "child"
    assert facts.indexed_columns == ("parent_id", "id")
    assert facts.declared_columns == ()


def test_cte_update_has_one_target_and_full_table_caution(monkeypatch):
    from dblift.core.migration.sql import script_analysis

    def forbidden(*args, **kwargs):
        raise AssertionError("legacy extraction reached")

    monkeypatch.setattr(script_analysis, "_fallback_objects", forbidden)
    sql = "WITH x AS (SELECT 1) UPDATE child SET parent_id = 2;"
    analysis = analyse_script(sql, "sqlite")

    assert analysis.errors == ()
    assert analysis.statements[0].kind == "DML"
    assert [(obj.type, obj.name) for obj in analysis.statements[0].objects] == [("TABLE", "child")]
    assert analysis.statements[0].full_table
    assert analysis.cautions[0].code == "dml-no-where"


def test_opaque_trigger_keeps_identity_without_an_error():
    sql = "CREATE TRIGGER trg AFTER INSERT ON child BEGIN UPDATE child SET id = 2; END;"
    result = SqlParserFactory("sqlite").parse_sql(sql)

    assert len(result.statements) == 1
    assert [(obj.object_type, obj.name) for obj in result.statements[0].affected_objects] == [
        (SqlObjectType.TRIGGER, "trg")
    ]
    assert result.success
    assert result.errors == []


def test_sqlite_dml_analysis_of_unparsed_mutation_names_only_the_head_target():
    mutation = SqliteQuirks().analyze_dml("UPDATE child SET parent_id =")

    assert mutation.table == "child"
    assert mutation.events == {"UPDATE"}
    assert mutation.updated_columns == []


def test_direct_sqlite_dml_helpers_read_only_the_head_after_parse_failure():
    sql = "UPDATE child SET parent_id ="
    assert analyze_dml(sql, sqlglot_dialect="sqlite").table == "child"
    assert statement_dml_table(sql, dialect="sqlite") == "child"
    assert analyze_dml(sql, sqlglot_dialect="sqlite").updated_columns == []


def test_sqlite_parser_config_patterns_are_removed():
    assert importlib.util.find_spec("dblift.db.plugins.sqlite.parser.parser_config") is None


def test_comment_only_segment_remains_visible_without_parse_diagnostic():
    analysis = analyse_script("-- note\n", "sqlite")
    assert len(analysis.statements) == 1
    assert analysis.statements[0].kind == "UNKNOWN"
    assert analysis.errors == ()


def test_cte_update_journal_records_the_ast_target():
    provider = MagicMock(spec=["execute_statement"])
    provider.execute_statement.return_value = 1
    journal = MagicMock()
    service = SqlExecutionService(
        provider, SqlAnalyzer("sqlite"), journal=journal, quirks=SqliteQuirks()
    )

    service.execute_statement("WITH x AS (SELECT 1) UPDATE child SET parent_id = 2")

    objects = journal.record_object_changes.call_args.args[2]
    assert [(obj["object_type"], obj["object_name"]) for obj in objects] == [("TABLE", "child")]


def test_sqlite_undo_add_column_uses_facts_instead_of_regex_extractor(monkeypatch):
    generator = UndoScriptGenerator("sqlite")

    def forbidden(*args, **kwargs):
        raise AssertionError("legacy column extractor reached")

    monkeypatch.setattr(generator, "_extract_column_name_from_add", forbidden)
    migration = Migration(
        script_name="V1__alter.sql", content="ALTER TABLE child ADD COLUMN value INT;"
    )

    statements = generator._generate_undo_statements(migration)
    assert len(statements) == 1
    assert statements[0].sql == 'ALTER TABLE "child" DROP COLUMN "value";'
    assert not statements[0].requires_manual_review


def test_sqlite_undo_of_an_opaque_trigger_drops_it():
    generator = UndoScriptGenerator("sqlite")
    migration = Migration(
        script_name="V1__trigger.sql",
        content="CREATE TRIGGER trg AFTER INSERT ON child BEGIN UPDATE child SET id = 2; END;",
    )

    statements = generator._generate_undo_statements(migration)
    assert [(s.sql, s.requires_manual_review) for s in statements] == [
        ('DROP TRIGGER IF EXISTS "trg";', False)
    ]


@pytest.mark.parametrize("mode", ["full", "execution"])
def test_sqlite_analyzer_modes_preserve_cte_mutation_target(mode):
    analyzer = SqlAnalyzer("sqlite", analysis_mode=mode)
    assert analyzer.extract_objects("WITH x AS (SELECT 1) UPDATE child SET parent_id = 2") == [
        {"object_type": "TABLE", "object_name": "default_schema.child"}
    ]


@pytest.mark.parametrize("mode", ["full", "execution"])
def test_sqlite_analyzer_modes_preserve_statement_facts(mode):
    result = SqlAnalyzer("sqlite", analysis_mode=mode).analyze_statement("CREATE TABLE t (x INT)")
    assert result == {
        "type": "DDL",
        "objects": [{"object_type": "TABLE", "object_name": "default_schema.t"}],
        "is_valid": True,
        "errors": [],
        "parsed_with": "facts",
    }
