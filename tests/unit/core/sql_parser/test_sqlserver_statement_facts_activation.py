"""SQL Server statement facts reach the public parser and analyzer paths."""

import pytest

from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer
from dblift.core.sql_parser import SqlParserFactory
from dblift.core.sql_parser.hybrid_parser import HybridParser
from dblift.core.sql_parser.sqlglot_parser import SqlGlotParser
from dblift.core.sql_parser.sqlglot_statement_facts import read_statement_facts
from dblift.core.sql_parser.statement_facts import SqlglotStatementFactsReader
from dblift.core.sql_parser.statement_facts_parser import StatementFactsParser
from dblift.db.provider_registry import ProviderRegistry


def test_plugin_reads_statement_facts():
    quirks = ProviderRegistry.get_quirks("sqlserver")

    assert quirks.supports_statement_facts
    assert isinstance(quirks.statement_facts_reader(), SqlglotStatementFactsReader)
    facts = quirks.statement_facts("CREATE TABLE [MiXeD].[a]]b] (id INT)")
    assert (facts.operation, facts.kind) == ("CREATE", "DDL")
    assert [(obj.name, obj.schema, obj.role) for obj in facts.affected_objects] == [
        ("a]b", "MiXeD", "created")
    ]


def test_default_factory_uses_facts_and_keeps_go_batches_lexical():
    factory = SqlParserFactory("sqlserver")
    parser = factory.get_parser()

    assert isinstance(parser, StatementFactsParser)
    script = "CREATE TABLE [MiXeD].[a]]b] (id INT)\nGO\nDROP TABLE [MiXeD].[a]]b]"
    assert factory.split_statements(script) == [
        "CREATE TABLE [MiXeD].[a]]b] (id INT)",
        "DROP TABLE [MiXeD].[a]]b]",
    ]
    assert [(obj.name, obj.schema) for obj in factory.extract_objects(script)] == [
        ("a]b", "MiXeD"),
        ("a]b", "MiXeD"),
    ]


@pytest.mark.parametrize("parser_class", [HybridParser, SqlGlotParser])
def test_direct_generic_parser_construction_refuses_sqlserver(parser_class):
    with pytest.raises(ValueError, match="StatementFactsParser"):
        parser_class("sqlserver")


def test_analyzer_extracts_objects_from_facts_without_regex(monkeypatch):
    analyzer = SqlAnalyzer("sqlserver")

    def forbidden(*args, **kwargs):
        raise AssertionError("regex extraction reached")

    monkeypatch.setattr(analyzer, "_extract_objects_regex", forbidden)
    sql = "UPDATE [MiXeD].[a]]b] SET id = 2 WHERE id = 1"

    assert analyzer.extract_objects(sql) == [
        {"object_type": "TABLE", "object_name": "MiXeD.a]b"}
    ]
    assert analyzer.analyze_statement(sql)["parsed_with"] == "facts"


@pytest.mark.parametrize(
    ("sql", "operation", "kind", "name", "schema", "role"),
    [
        ("CREATE TABLE [a]]b] (id INT)", "CREATE", "DDL", "a]b", None, "created"),
        (
            "CREATE TABLE [MiXeD].[a]]b] (id INT)",
            "CREATE",
            "DDL",
            "a]b",
            "MiXeD",
            "created",
        ),
        (
            "CREATE TABLE [DbOne].[MiXeD].[a]]b] (id INT)",
            "CREATE",
            "DDL",
            "a]b",
            "DbOne.MiXeD",
            "created",
        ),
        (
            "UPDATE [MiXeD].[a]]b] SET id = 2 WHERE id = 1",
            "UPDATE",
            "DML",
            "a]b",
            "MiXeD",
            "altered",
        ),
    ],
)
def test_raw_reader_preserves_written_names(sql, operation, kind, name, schema, role):
    facts = read_statement_facts(sql, dialect="tsql")

    assert (facts.operation, facts.kind) == (operation, kind)
    assert [(obj.name, obj.schema, obj.role) for obj in facts.affected_objects] == [
        (name, schema, role)
    ]
    assert facts.diagnostic is None


def test_unread_xml_index_stays_opaque():
    facts = read_statement_facts("CREATE XML INDEX [ix] ON [MiXeD].[t] ([doc])", dialect="tsql")

    assert (facts.operation, facts.kind) == ("CREATE", "DDL")
    assert facts.objects == ()
    assert facts.opaque
    assert facts.diagnostic
    assert facts.error is None


def test_unread_update_top_does_not_invent_a_target():
    facts = read_statement_facts(
        "UPDATE TOP (1) dbo.t SET x=2 OUTPUT inserted.x WHERE id=1", dialect="tsql"
    )

    assert (facts.operation, facts.kind) == ("UPDATE", "DML")
    assert facts.target is None
    assert facts.affected_objects == ()
    assert facts.diagnostic


def test_unsupported_trigger_command_does_not_invent_an_object():
    facts = read_statement_facts(
        "CREATE TRIGGER [tr] ON [dbo].[t] AFTER INSERT AS SELECT 1", dialect="tsql"
    )

    assert (facts.operation, facts.kind) == ("CREATE", "DDL")
    assert facts.affected_objects == ()
    assert facts.diagnostic


def test_four_part_reference_does_not_drop_a_name_component():
    facts = read_statement_facts("SELECT * FROM [Srv].[Db].[dbo].[MiXeD]", dialect="tsql")

    assert (facts.operation, facts.kind) == ("SELECT", "QUERY")
    if facts.objects:
        assert [(obj.schema, obj.name, obj.role) for obj in facts.objects] == [
            ("Srv.Db.dbo", "MiXeD", "referenced")
        ]
    else:
        assert facts.diagnostic


def test_select_into_records_its_created_table():
    facts = read_statement_facts("SELECT id INTO dbo.NewTable FROM dbo.Source", dialect="tsql")

    assert (facts.operation, facts.kind) == ("SELECT", "DML")
    assert [(obj.schema, obj.name, obj.role) for obj in facts.objects] == [
        ("dbo", "NewTable", "created"),
        ("dbo", "Source", "referenced"),
    ]
