"""DuckDB facts activate consumers without replacing the engine script scanner."""

import subprocess
import sys

import pytest

from dblift.core.exceptions import UnsafeStatementSplitError, UnsupportedMetaCommandError
from dblift.core.migration.scripting.undo_script_generator import UndoScriptGenerator
from dblift.core.migration.sql.script_analysis import analyse_script
from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer
from dblift.core.sql_parser import SqlParserFactory
from dblift.db.dml_analysis import analyze_dml, statement_dml_table, updates_restore_key
from dblift.db.plugins.duckdb.parser.parser_config import DuckDBParserConfig
from dblift.db.plugins.duckdb.quirks import DuckDBQuirks
from dblift.db.provider_registry import ProviderRegistry
from tests.unit._migration_factory import make_migration

_quirks = ProviderRegistry.get_quirks

CTE_UPDATE = "WITH x AS (SELECT 1) UPDATE child SET id = 2"
COPY_FROM = "COPY child FROM 'input.csv'"


@pytest.mark.parametrize("mode", ["regex", "hybrid", "sqlglot"])
def test_factory_projects_facts_without_constructing_regex_config(mode, monkeypatch):
    def refuse_regex_config(self):
        raise AssertionError("DuckDB facts must not construct regex configuration")

    monkeypatch.setattr(DuckDBParserConfig, "__init__", refuse_regex_config)
    factory = SqlParserFactory("duckdb", mode)
    result = factory.parse_sql(CTE_UPDATE)

    assert result.success, result.errors
    assert result.statements[0].statement_type.value == "DML"
    assert [obj.name for obj in factory.extract_objects(CTE_UPDATE)] == ["child"]
    assert factory.validate_sql(CTE_UPDATE) == {
        "valid": True,
        "statements_found": 1,
        "errors": [],
    }
    assert factory.split_statements("SELECT 1;\n-- note\n") == ["SELECT 1"]
    parser = factory.get_parser()
    assert parser.dialect_name == "duckdb"
    assert parser.split_for_analysis("SELECT 1;\n-- note\n") == ["SELECT 1"]
    assert parser.split_for_extraction("SELECT 1;\n-- note\n") == ["SELECT 1"]
    records = parser.split("SELECT 1;\nSELECT 2")
    assert [
        (record.text, record.line, record.terminator, record.source_start, record.source_end)
        for record in records
    ] == [("SELECT 1", 1, ";", 0, 9), ("SELECT 2", 2, None, 10, 18)]


def test_plugin_reads_facts_without_a_lexical_spec():
    facts = DuckDBQuirks().statement_facts(CTE_UPDATE)

    assert facts.operation == "UPDATE"
    assert facts.target == "child"
    assert facts.events == frozenset({"UPDATE"})


def test_plugin_comment_only_facts_have_no_diagnostic():
    facts = DuckDBQuirks().statement_facts("/* outer /* inner */ tail */")

    assert facts.operation == "UNKNOWN"
    assert facts.kind == "UNKNOWN"
    assert facts.diagnostic is None
    assert facts.error is None
    assert facts.objects == ()


@pytest.mark.parametrize("mode", ["regex", "hybrid", "sqlglot"])
@pytest.mark.parametrize("sql", [CTE_UPDATE, COPY_FROM])
def test_factory_preserves_mutation_target_in_each_supported_mode(mode, sql):
    result = SqlParserFactory("duckdb", mode).parse_sql(sql)

    assert result.success, result.errors
    assert len(result.statements) == 1
    statement = result.statements[0]
    assert statement.statement_type.value == "DML"
    assert [(obj.object_type.value, obj.name) for obj in statement.affected_objects] == [
        ("TABLE", "child")
    ]


@pytest.mark.parametrize(
    ("sql", "operation", "kind", "objects"),
    [
        (CTE_UPDATE, "UPDATE", "DML", [("TABLE", "child")]),
        (COPY_FROM, "COPY", "DML", [("TABLE", "child")]),
        ("/* outer /* inner ; */ tail */ SELECT 1;", "SELECT", "QUERY", []),
    ],
)
def test_script_analysis_uses_facts_and_preserves_scanner_units(sql, operation, kind, objects):
    analysis = analyse_script(sql, "duckdb")

    assert analysis.errors == ()
    assert len(analysis.statements) == 1
    statement = analysis.statements[0]
    assert (statement.operation, statement.kind) == (operation, kind)
    assert [(obj.type, obj.name) for obj in statement.objects] == objects
    if sql == CTE_UPDATE:
        assert statement.full_table
        assert [caution.code for caution in analysis.cautions] == ["dml-no-where"]


@pytest.mark.parametrize("mode", ["regex", "hybrid", "sqlglot"])
def test_comment_only_script_is_successful_and_has_no_statements(mode):
    factory = SqlParserFactory("duckdb", mode)
    result = factory.parse_sql("/* outer /* inner */ tail */")

    assert result.success, result.errors
    assert result.statements == []
    assert factory.split_statements("/* outer /* inner */ tail */") == []


@pytest.mark.parametrize(
    ("sql", "error"),
    [
        ("CREATE TABLE child(id INT);\n.mode csv\nSELECT 1;", UnsupportedMetaCommandError),
        ("CREATE TABLE child(id INT);\x00DROP TABLE child;", UnsafeStatementSplitError),
    ],
)
def test_refused_script_has_no_partial_analysis_or_undo(sql, error):
    analysis = analyse_script(sql, "duckdb")
    assert analysis.statements == ()
    assert analysis.errors
    for mode in ("regex", "hybrid", "sqlglot"):
        factory = SqlParserFactory("duckdb", mode)
        with pytest.raises(error):
            factory.split_statements(sql)
        parsed = factory.parse_sql(sql)
        assert not parsed.success
        assert parsed.statements == []
    migration = make_migration(script_name="V1__child.sql", content=sql)
    with pytest.raises(error):
        UndoScriptGenerator("duckdb")._generate_undo_statements(migration)


@pytest.mark.parametrize(
    "sql",
    [
        "CREATE OR REPLACE TABLE child(id INT)",
        "CREATE TABLE IF NOT EXISTS child(id INT)",
        "CREATE TABLE catalog.schema.items(id INT)",
    ],
)
def test_undo_requires_review_when_table_creation_cannot_be_safely_reversed(sql):
    migration = make_migration(script_name="V1__child.sql", content=sql)
    undo = UndoScriptGenerator("duckdb")._generate_undo_statements(migration)

    assert len(undo) == 1
    assert undo[0].requires_manual_review
    assert undo[0].warning
    assert all(line.lstrip().startswith("--") for line in undo[0].sql.splitlines() if line.strip())


@pytest.mark.parametrize("sql", [CTE_UPDATE, COPY_FROM])
def test_full_analyzer_classifies_mutations(sql):
    assert SqlAnalyzer("duckdb", analysis_mode="full").get_statement_type(sql) == "DML"


def test_execution_analyzer_does_not_import_sqlglot():
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; "
            "from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer; "
            "analyzer = SqlAnalyzer('duckdb', analysis_mode='execution'); "
            "assert analyzer.get_statement_type('UPDATE child SET id = 2') == 'DML'; "
            "analyzer.extract_objects('UPDATE child SET id = 2'); "
            "assert analyzer.analyze_statement('UPDATE child SET id = 2')['type'] == 'DML'; "
            "assert not any(name == 'sqlglot' or name.startswith('sqlglot.') "
            "for name in sys.modules)",
        ],
        capture_output=True,
        text=True,
    )
    assert probe.returncode == 0, probe.stdout + probe.stderr


@pytest.mark.parametrize(
    "sql", ["SELECT * FROM child", "COPY child TO 'output.csv'", "/* outer /* inner */ tail */"]
)
def test_read_only_statements_and_comments_need_no_undo(sql):
    migration = make_migration(script_name="V1__read.sql", content=sql)
    assert UndoScriptGenerator("duckdb")._generate_undo_statements(migration) == []


@pytest.mark.parametrize("sql", ["CREATE TABLE child(id INT)", "FUTURE COMMAND child"])
def test_mutations_and_unknown_commands_require_manual_undo(sql):
    migration = make_migration(script_name="V1__child.sql", content=sql)
    undo = UndoScriptGenerator("duckdb")._generate_undo_statements(migration)
    assert len(undo) == 1
    assert undo[0].requires_manual_review
    assert undo[0].warning
    assert all(line.lstrip().startswith("--") for line in undo[0].sql.splitlines() if line.strip())


@pytest.mark.parametrize("mode", ["regex", "hybrid", "sqlglot"])
@pytest.mark.parametrize("sql", [CTE_UPDATE, COPY_FROM])
def test_factory_affected_objects_projects_facts(mode, sql):
    objects = SqlParserFactory("duckdb", mode).get_affected_objects(sql)
    assert [(obj.object_type.value, obj.name) for obj in objects] == [("TABLE", "child")]


@pytest.mark.parametrize(
    "sql,name,schema",
    [
        ("DROP SCHEMA s CASCADE", "s", None),
        ('DROP SCHEMA "Warehouse"."Reporting" CASCADE', "Reporting", "Warehouse"),
    ],
)
def test_drop_schema_keeps_identity_and_destructive_caution(sql, name, schema):
    analysis = analyse_script(sql, "duckdb")
    assert analysis.errors == ()
    assert [(obj.type, obj.name, obj.schema) for obj in analysis.statements[0].objects] == [
        ("SCHEMA", name, schema)
    ]
    assert [(caution.level, caution.code) for caution in analysis.cautions] == [
        ("destroys", "drop-schema")
    ]


@pytest.mark.parametrize(
    "sql,kind",
    [
        ("COMMENT ON TABLE child IS 'note'", "DDL"),
        ("SHOW TABLES", "QUERY"),
        ("DESCRIBE child", "QUERY"),
    ],
)
def test_metadata_statements_keep_full_analyzer_classification(sql, kind):
    assert SqlAnalyzer("duckdb", analysis_mode="full").get_statement_type(sql) == kind


def test_comment_on_table_preserves_script_ddl_classification():
    analysis = analyse_script("COMMENT ON TABLE child IS 'note'", "duckdb")
    assert analysis.errors == ()
    assert analysis.statements[0].kind == "DDL"
    assert [(obj.type, obj.name) for obj in analysis.statements[0].objects] == [("TABLE", "child")]


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE child AS c SET id = 2 WHERE c.id = 1",
        "UPDATE ONLY child SET id = 2",
        "DELETE FROM ONLY child WHERE id = 1",
        "DELETE FROM child AS c WHERE c.id = 1",
        "MERGE INTO child AS c USING source AS s ON c.id = s.id WHEN MATCHED THEN DELETE",
    ],
)
def test_dml_target_sql_excludes_statement_local_modifiers(sql):
    assert statement_dml_table(sql, "duckdb") == "child"


def test_dml_target_sql_preserves_qualified_quoted_identity_without_alias():
    sql = 'UPDATE "Warehouse"."Sales"."Order Items" AS c SET id = 2 WHERE c.id = 1'
    assert statement_dml_table(sql, "duckdb") == '"Warehouse"."Sales"."Order Items"'


@pytest.mark.parametrize("sql", ["CREATE TYPE mood AS ENUM ('ok')", "DROP TYPE mood"])
def test_opaque_type_statements_require_manual_review_without_guessed_identity(sql):
    facts = DuckDBQuirks().statement_facts(sql)
    assert facts.kind == "DDL"
    assert facts.opaque
    assert facts.objects == ()
    undo = UndoScriptGenerator("duckdb")._generate_undo_statements(
        make_migration(script_name="V1__type.sql", content=sql)
    )
    assert len(undo) == 1
    assert undo[0].requires_manual_review
    assert undo[0].sql.startswith("-- WARNING:")


@pytest.mark.parametrize(
    "sql,kind",
    [
        ("COMMENT ON COLUMN child.id IS 'note'", "DDL"),
        ("COMMENT ON VIEW v IS 'note'", "DDL"),
        ("COMMENT ON INDEX idx IS 'note'", "DDL"),
        ("COMMENT ON SEQUENCE seq IS 'note'", "DDL"),
        ("SHOW DATABASES", "QUERY"),
    ],
)
def test_opaque_metadata_preserves_high_level_classification(sql, kind):
    facts = DuckDBQuirks().statement_facts(sql)
    assert facts.kind == kind
    assert facts.opaque
    assert facts.objects == ()
    assert SqlAnalyzer("duckdb").get_statement_type(sql) == kind


@pytest.mark.parametrize(
    "sql,columns,updates_key",
    [
        ("INSERT INTO child(value) VALUES(10) ON CONFLICT(value) DO UPDATE SET id=2", ["id"], True),
        ("INSERT INTO child(id,value) VALUES(1,10)", [], False),
        (
            "INSERT INTO child(id,value) VALUES(1,10) ON CONFLICT(id) DO UPDATE SET value=20",
            ["value"],
            False,
        ),
    ],
)
@pytest.mark.parametrize("dialect", ["duckdb", "sqlite"])
def test_insert_facts_keep_update_assignments_for_restore_key_checks(
    sql, columns, updates_key, dialect
):
    assert analyze_dml(sql, quirks=_quirks(dialect)).updated_columns == columns
    assert updates_restore_key(sql, ["id"], quirks=_quirks(dialect)) is updates_key


def test_prepared_execute_keeps_dml_classification():
    facts = DuckDBQuirks().statement_facts("EXECUTE stmt")
    assert facts.kind == "DML"
    assert facts.opaque
    assert facts.objects == ()
    assert SqlAnalyzer("duckdb").get_statement_type("EXECUTE stmt") == "DML"


def test_copy_import_columns_do_not_count_as_restore_key_updates():
    sql = "COPY child(id) FROM 'x.csv'"
    facts = DuckDBQuirks().statement_facts(sql)
    assert facts.events == frozenset({"INSERT"})
    assert facts.affected_columns == ("id",)
    assert analyze_dml(sql, quirks=_quirks("duckdb")).updated_columns == []
    assert not updates_restore_key(sql, ["id"], quirks=_quirks("duckdb"))
