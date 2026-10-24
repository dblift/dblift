"""The Db2 plugin serves statement facts through its head reader."""

from unittest.mock import MagicMock

from dblift.core.migration.sql.script_analysis import analyse_script
from dblift.core.migration.sql.sql_execution_service import SqlExecutionService
from dblift.core.migration.sql.statement_reader import StatementReader
from dblift.core.sql_parser.statement_facts_parser import StatementFactsParser
from dblift.db.dml_analysis import DmlMutation, updates_restore_key
from dblift.db.plugins.db2.parser.statement_facts import Db2StatementFactsReader
from dblift.db.provider_registry import ProviderRegistry
from tests.support.facts_parser import facts_parser


def test_db2_quirks_declare_the_head_reader():
    quirks = ProviderRegistry.get_quirks("db2")
    assert quirks.supports_statement_facts
    assert isinstance(quirks.statement_facts_reader(), Db2StatementFactsReader)


def test_the_facts_parser_of_db2_is_built_from_its_plugin():
    parser = facts_parser("db2")
    assert isinstance(parser, StatementFactsParser)
    assert parser.dialect_name == "db2"


def test_facts_parser_extracts_the_folded_objects():
    objects = facts_parser("db2").extract_objects("CREATE TABLE app.t (id INT);\nDROP VIEW v;")
    assert [(o.object_type.value, o.name, o.schema) for o in objects] == [
        ("TABLE", "T", "APP"),
        ("VIEW", "V", None),
    ]


def test_analyse_script_takes_the_facts_path():
    analysis = analyse_script(
        "CREATE TABLE app.t (id INT);\nINSERT INTO app.t VALUES (1);\n"
        "SELECT 1 FROM sysibm.sysdummy1;\nDELETE FROM app.t;",
        "db2",
    )
    assert [
        (s.operation, s.kind, [(o.type, o.name, o.schema) for o in s.objects], s.full_table)
        for s in analysis.statements
    ] == [
        ("CREATE", "DDL", [("TABLE", "T", "APP")], False),
        ("INSERT", "DML", [("TABLE", "T", "APP")], False),
        ("SELECT", "QUERY", [], False),
        ("DELETE", "DML", [("TABLE", "T", "APP")], True),
    ]
    assert not analysis.errors


def test_sql_analyzer_extract_objects_reads_facts():
    assert StatementReader("db2").extract_objects("DROP TABLE app.orders") == [
        {"object_type": "TABLE", "object_name": "APP.ORDERS"}
    ]


def test_quirks_dml_helpers_read_the_facts():
    quirks = ProviderRegistry.get_quirks("db2")
    assert (
        quirks.statement_dml_table("UPDATE app.orders AS o SET a = 1 WHERE o.id = 1")
        == "app.orders AS o"
    )
    assert quirks.dml_where_predicate("DELETE FROM app.orders WHERE id = 1") == "id = 1"
    assert quirks.is_full_table_dml("DELETE FROM app.orders") is True
    assert quirks.is_full_table_dml("DELETE FROM app.orders WHERE id = 1") is False
    assert quirks.analyze_dml("UPDATE app.orders SET id = 5 WHERE x = 1") == DmlMutation(
        "APP.ORDERS", {"UPDATE"}, ["id"]
    )
    assert updates_restore_key("UPDATE t SET id = 5", ("ID",), quirks=quirks) is True


def test_execution_service_records_the_facts_objects():
    provider = MagicMock(spec=["execute_statement"])
    provider.execute_statement.return_value = 1
    journal = MagicMock()
    quirks = ProviderRegistry.get_quirks("db2")
    service = SqlExecutionService(provider, StatementReader("db2"), journal=journal, quirks=quirks)

    service.execute_statement("CREATE TABLE app.t (id INT)")

    objects = journal.record_object_changes.call_args.args[2]
    assert [(o["object_type"], o["object_name"], o["schema"]) for o in objects] == [
        ("TABLE", "T", "APP")
    ]
