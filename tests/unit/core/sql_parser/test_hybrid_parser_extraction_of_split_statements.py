"""Extraction runs on statements that are already split; it must not re-split them strictly."""

import pytest

from dblift.core.sql_parser.parser_factory import SqlParserFactory


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
def test_extract_objects_from_an_already_split_statement(sql, kind, name):
    objects = _oracle_parser().extract_objects(sql, "S")

    assert [(o.object_type.name, o.name.upper()) for o in objects] == [(kind, name)]


def test_parse_sql_reports_the_refusal_without_partial_statements():
    result = _oracle_parser().parse_sql("CREATE TABLE t (id NUMBER); -- c\nDELETE FROM t;")

    assert any("is not the last text on line 1" in e for e in result.errors or [])
    assert not result.success
    assert result.statements == []
    assert result.tables == []
