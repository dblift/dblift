"""Execution runs batches; extraction and reporting still read one statement at a time."""

from dblift.core.sql_parser.hybrid_parser import HybridParser
from dblift.core.sql_parser.parser_factory import SqlParserFactory
from dblift.db.plugins.sqlserver.parser.sqlserver_regex_parser import SqlServerRegexParser

SCRIPT = (
    "CREATE TABLE a (id INT PRIMARY KEY);\n"
    "CREATE INDEX ix_a ON a (id);\n"
    "CREATE VIEW v AS SELECT id FROM a;\n"
    "ALTER TABLE a ADD name VARCHAR(10);\n"
)


def test_execution_sees_one_batch_and_extraction_four_statements():
    parser = SqlServerRegexParser()
    assert len(parser.split_statements(SCRIPT)) == 1
    assert len(parser.split_for_extraction(SCRIPT)) == 4


def test_split_for_extraction_still_cuts_at_go():
    parser = SqlServerRegexParser()
    assert parser.split_for_extraction("SELECT 1\nGO\nSELECT 2\nGO\n") == ["SELECT 1", "SELECT 2"]


def test_parse_sql_reports_one_statement_per_semicolon():
    for parser_type in ("regex", "hybrid"):
        parser = SqlParserFactory("sqlserver", parser_type=parser_type).get_parser()
        result = parser.parse_sql(SCRIPT)
        assert len(result.statements) == 4, parser_type


def test_hybrid_extraction_of_a_batch_equals_extraction_statement_by_statement():
    parser = HybridParser("sqlserver")

    def names(objects):
        return sorted((o.object_type.name, o.name) for o in objects)

    one_by_one = [o for s in parser.split_for_extraction(SCRIPT) for o in parser.extract_objects(s)]
    assert names(parser.extract_objects(SCRIPT)) == names(one_by_one)
    assert {n for _, n in names(one_by_one)} >= {"a", "ix_a", "v"}


def test_the_default_split_for_extraction_is_the_execution_split():
    parser = SqlParserFactory("postgresql", parser_type="regex").get_parser()
    script = "CREATE TABLE a (x INT);\nCREATE TABLE b (y INT);\n"
    assert parser.split_for_extraction(script) == parser.split_statements(script)
