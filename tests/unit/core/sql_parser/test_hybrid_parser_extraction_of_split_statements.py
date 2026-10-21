"""Extraction runs on statements that are already split; it must not re-split them strictly."""

import pytest

from dblift.core.sql_parser.parser_factory import SqlParserFactory
from dblift.db.provider_registry import ProviderRegistry


def _oracle_parser():
    return SqlParserFactory("oracle").get_parser()


@pytest.mark.parametrize(
    "sql, kind, name",
    [
        ("CREATE OR REPLACE PROCEDURE p IS BEGIN NULL; END;", "PROCEDURE", "P"),
        ("CREATE OR REPLACE FUNCTION f RETURN NUMBER IS BEGIN RETURN 1; END;", "FUNCTION", "F"),
        ("CREATE TABLE t (id NUMBER); -- c", "TABLE", "T"),
    ],
)
def test_the_facts_of_an_already_split_statement_name_its_object(sql, kind, name):
    facts = ProviderRegistry.get_quirks("oracle").statement_facts(sql)

    assert [(o.type.name, o.name) for o in facts.objects] == [(kind, name)]


def test_parse_sql_reports_the_refusal_without_partial_statements():
    result = _oracle_parser().parse_sql("CREATE TABLE t (id NUMBER); -- c\nDELETE FROM t;")

    assert any("is not the last text on line 1" in e for e in result.errors or [])
    assert not result.success
    assert result.statements == []
    assert result.tables == []
