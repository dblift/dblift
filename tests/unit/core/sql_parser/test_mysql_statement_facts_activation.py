"""MySQL and MariaDB read statement facts through the shared reader; the client rules stay in the split."""

from unittest.mock import MagicMock

import pytest

from dblift.core.exceptions import UnsupportedMetaCommandError
from dblift.core.migration.scripting.undo_script_generator import UndoScriptGenerator
from dblift.core.migration.sql.script_analysis import analyse_script
from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer
from dblift.core.migration.sql.sql_execution_service import SqlExecutionService
from dblift.core.sql_parser import redaction
from dblift.core.sql_parser.hybrid_parser import HybridParser
from dblift.core.sql_parser.parser_factory import SqlParserFactory
from dblift.core.sql_parser.sqlglot_parser import SqlGlotParser
from dblift.core.sql_parser.statement_facts import SqlglotStatementFactsReader
from dblift.core.sql_parser.statement_facts_parser import StatementFactsParser
from dblift.db.dml_analysis import analyze_dml, statement_dml_table
from dblift.db.plugins.mariadb.regex_parser import MariaDbRegexParser
from dblift.db.plugins.mysql.parser.mysql_regex_parser import MySqlRegexParser
from dblift.db.plugins.mysql.parser.mysql_tokenizer import MySQLTokenizer
from dblift.db.provider_registry import ProviderRegistry
from tests.unit._migration_factory import make_migration

DIALECTS = ("mysql", "mariadb")
MODES = ("regex", "hybrid", "sqlglot")
UPDATE = "UPDATE t SET a = 1"
EXECUTABLE = "/*!50001 CREATE TABLE t (id INT) */"
MARIA_EXECUTABLE = "/*M!100000 CREATE TABLE t (id INT) */"
DELIMITER_SCRIPT = (
    "DELIMITER //\nCREATE PROCEDURE p() BEGIN UPDATE t SET a = 1; END //\nDELIMITER ;\n"
    "UPDATE t SET a = 2;\n"
)

_quirks = ProviderRegistry.get_quirks


@pytest.mark.parametrize("dialect", DIALECTS)
def test_the_plugin_reads_facts_through_the_shared_reader(dialect):
    quirks = _quirks(dialect)

    assert quirks.supports_statement_facts
    assert quirks.statement_facts_class is SqlglotStatementFactsReader
    facts = quirks.statement_facts(UPDATE)
    assert (facts.operation, facts.target, facts.events) == ("UPDATE", "t", frozenset({"UPDATE"}))


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize("mode", ("hybrid", "sqlglot"))
def test_the_factory_projects_facts_in_the_hybrid_and_sqlglot_modes(dialect, mode):
    factory = SqlParserFactory(dialect, mode)
    parser = factory.get_parser()

    assert isinstance(parser, StatementFactsParser)
    assert parser.dialect_name == dialect
    result = factory.parse_sql("CREATE TABLE t (id INT); UPDATE t SET a = 1;")
    assert result.success, result.errors
    assert [s.statement_type.value for s in result.statements] == ["DDL", "DML"]
    assert [[o.name for o in s.affected_objects] for s in result.statements] == [["t"], ["t"]]
    assert [o.name for o in factory.extract_objects(UPDATE)] == ["t"]
    assert factory.validate_sql(UPDATE) == {"valid": True, "statements_found": 1, "errors": []}


@pytest.mark.parametrize(
    ("dialect", "parser_class"), [("mysql", MySqlRegexParser), ("mariadb", MariaDbRegexParser)]
)
def test_the_regex_mode_keeps_the_client_delegate_for_records_and_masking(dialect, parser_class):
    parser = SqlParserFactory(dialect, "regex").get_parser()

    assert type(parser) is parser_class
    assert parser.tokenizer_class is MySQLTokenizer
    assert redaction._dialect_tokenizer(dialect) is MySQLTokenizer
    assert (
        redaction.mask_string_literals("INSERT INTO t VALUES ('x', \"y\")", dialect)
        == "INSERT INTO t VALUES ('?', '?')"
    )
    records = parser.split("SELECT 1;\nSELECT 2")
    assert [(r.text, r.line, r.terminator) for r in records] == [
        ("SELECT 1", 1, ";"),
        ("SELECT 2", 2, None),
    ]


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize("mode", MODES)
def test_the_delimiter_script_splits_the_same_in_every_mode(dialect, mode):
    units = SqlParserFactory(dialect, mode).split_statements(DELIMITER_SCRIPT)

    assert units == [
        "CREATE PROCEDURE p() BEGIN UPDATE t SET a = 1; END",
        "UPDATE t SET a = 2",
    ]


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize("parser_class", [HybridParser, SqlGlotParser])
def test_the_generic_text_parsers_refuse_the_plugin(dialect, parser_class):
    with pytest.raises(ValueError, match="StatementFactsParser"):
        parser_class(dialect)


@pytest.mark.parametrize("dialect", DIALECTS)
def test_script_analysis_reads_facts(dialect):
    analysis = analyse_script("UPDATE t SET a = 1;\nTRUNCATE t;\nDROP TABLE s.t;", dialect)

    assert analysis.errors == ()
    assert [
        (s.operation, s.kind, [(o.name, o.schema) for o in s.objects]) for s in analysis.statements
    ] == [
        ("UPDATE", "DML", [("t", None)]),
        ("TRUNCATE", "DDL", [("t", None)]),
        ("DROP", "DDL", [("t", "s")]),
    ]
    assert analysis.statements[0].full_table
    assert [c.code for c in analysis.cautions] == ["dml-no-where", "truncate", "drop-table"]


@pytest.mark.parametrize("dialect", DIALECTS)
def test_an_executable_comment_is_an_unread_statement_not_a_guess(dialect):
    analysis = analyse_script(EXECUTABLE, dialect)

    assert analysis.errors == ()
    (statement,) = analysis.statements
    assert (statement.operation, statement.kind, statement.objects) == ("UNKNOWN", "UNKNOWN", ())
    assert statement.names_unread


def test_the_mariadb_executable_comment_is_read_by_the_mariadb_plugin_only():
    through_mariadb = analyse_script(MARIA_EXECUTABLE, "mariadb")
    through_mysql = analyse_script(MARIA_EXECUTABLE, "mysql")

    assert [(s.operation, s.names_unread) for s in through_mariadb.statements] == [
        ("UNKNOWN", True)
    ]
    assert through_mysql.statements == ()
    assert through_mysql.errors == () == through_mariadb.errors


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize(
    "script", ["source other.sql\nCREATE TABLE a (id INT);\n", "CREATE TABLE a (id INT);\nexit\n"]
)
def test_a_client_command_refuses_the_whole_script_on_every_path(dialect, script):
    analysis = analyse_script(script, dialect)
    assert analysis.statements == ()
    assert len(analysis.errors) == 1
    for mode in MODES:
        factory = SqlParserFactory(dialect, mode)
        with pytest.raises(UnsupportedMetaCommandError):
            factory.split_statements(script)
        parsed = factory.parse_sql(script)
        assert not parsed.success
        assert parsed.statements == []
    migration = make_migration(script_name="V1__a.sql", content=script)
    with pytest.raises(UnsupportedMetaCommandError):
        UndoScriptGenerator(dialect)._generate_undo_statements(migration)


@pytest.mark.parametrize("dialect", DIALECTS)
def test_execution_tracking_records_the_facts_object(dialect):
    provider = MagicMock(spec=["execute_statement"])
    provider.execute_statement.return_value = 1
    journal = MagicMock()
    service = SqlExecutionService(
        provider, SqlAnalyzer(dialect), journal=journal, quirks=_quirks(dialect)
    )

    service.execute_statement("UPDATE s.t SET a = 1")

    objects = journal.record_object_changes.call_args.args[2]
    assert [(obj["object_name"], obj["schema"]) for obj in objects] == [("t", "s")]


@pytest.mark.parametrize("dialect", DIALECTS)
def test_the_analyzer_reads_objects_from_facts(dialect):
    assert SqlAnalyzer(dialect).extract_objects(UPDATE) == [
        {"object_type": "TABLE", "object_name": "default_schema.t"}
    ]
    assert SqlAnalyzer(dialect).analyze_statement(UPDATE)["parsed_with"] == "facts"


@pytest.mark.parametrize("dialect", DIALECTS)
def test_undo_requires_manual_review_for_schema_changes_and_none_for_queries(dialect):
    migration = make_migration(script_name="V1__t.sql", content="CREATE TABLE t (id INT);")
    (undo,) = UndoScriptGenerator(dialect)._generate_undo_statements(migration)
    assert undo.requires_manual_review
    assert undo.sql.startswith("-- WARNING:")

    migration = make_migration(script_name="V2__q.sql", content="SELECT 1;")
    assert UndoScriptGenerator(dialect)._generate_undo_statements(migration) == []


@pytest.mark.parametrize("dialect", DIALECTS)
def test_dml_analysis_reads_the_modifier_bearing_target_through_facts(dialect):
    quirks = _quirks(dialect)

    assert analyze_dml("UPDATE LOW_PRIORITY t SET a = 1", quirks=quirks).table == "t"
    assert (
        statement_dml_table("DELETE QUICK FROM `Cap Probe` WHERE id = 1", quirks=quirks)
        == "`Cap Probe`"
    )


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize("char", [" ", "\u0085", " ", " ", "　"])
def test_a_non_ascii_blank_beside_a_name_proves_no_object_through_the_plugin(dialect, char):
    facts = _quirks(dialect).statement_facts(f"DROP INDEX idx ON t{char}")

    assert facts.indexed_table is None
    assert all(obj.type.value != "TABLE" for obj in facts.objects)


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize(
    ("sql", "target", "predicate"),
    [
        ("UPDATE ignore.t SET a = 1 WHERE id = 1", "ignore.t", "id = 1"),
        ("DELETE FROM ignore.t WHERE id = 1", "ignore.t", "id = 1"),
        ("UPDATE ignore.t SET a = 1", "ignore.t", None),
    ],
)
def test_a_schema_named_like_a_keyword_keeps_its_target_and_predicate(
    dialect, sql, target, predicate
):
    # Both engines run these (the schema `ignore` exists in the probe); sqlglot's grammar does not,
    # so the reader proves the single target and the WHERE from the text instead of guessing nothing.
    quirks = _quirks(dialect)
    facts = quirks.statement_facts(sql)

    assert facts.target == target
    assert facts.predicate == predicate
    assert quirks.statement_dml_table(sql) == target
    assert quirks.is_full_table_dml(sql) is (predicate is None)
    analysis = analyse_script(sql + ";", dialect)
    assert analysis.statements[0].full_table is (predicate is None)
    assert [c.code for c in analysis.cautions if c.code == "dml-no-where"] == (
        ["dml-no-where"] if predicate is None else []
    )


@pytest.mark.parametrize(
    ("sql", "full_table"),
    [
        ("UPDATE ignore.t SET a = 1 # WHERE z", True),
        ("UPDATE ignore.t SET a = 1 WHERE id = 3 # WHERE z", False),
        ("UPDATE ignore.t SET a = 1 # WHERE z\n WHERE id = 3", False),
        ("UPDATE ignore.t SET a = 'x\\' WHERE y'", True),
        ("UPDATE ignore.t SET a = 'x\\' WHERE y' WHERE id = 1", False),
        ("DELETE FROM ignore.t # c\n WHERE id = 1", False),
        ("DELETE FROM ignore.t WHERE a = 'it\\'s' # tail", False),
    ],
)
def test_a_hash_comment_or_an_escaped_quote_never_feeds_the_predicate(sql, full_table):
    # ``#`` opens a comment and ``\'`` is an escaped quote in MySQL: a WHERE inside either is text.
    # The reader may prove the predicate or report the statement unread; it may not misread it.
    quirks = _quirks("mysql")
    facts = quirks.statement_facts(sql)

    if facts.predicate is not None:
        assert "z" not in facts.predicate and "y" not in facts.predicate
        assert "#" not in facts.predicate and "'" not in facts.predicate.replace("'it\\'s'", "")
        assert quirks.is_full_table_dml(sql) is False
        assert full_table is False
    else:
        assert quirks.is_full_table_dml(sql) is True
    if facts.target is not None:
        assert facts.target == "ignore.t"
